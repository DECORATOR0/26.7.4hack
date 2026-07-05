from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import load_intern_config
from .intern_client import InternClient
from .io_utils import (
    ensure_dir,
    image_to_data_url,
    read_json,
    seconds_to_timestamp,
    timestamp_to_seconds,
    write_json,
    write_text,
)


@dataclass
class ScoreboardGoalOptions:
    source_events_path: Path
    frame_index_path: Path
    out_dir: Path
    precomputed_goals_path: Path | None = None
    precomputed_readings_path: Path | None = None
    output_version: str = "v4_3"
    goal_timestamp_policy: str = "first_after_jump"
    video_path: Path | None = None
    coarse_interval_sec: int = 20
    batch_size: int = 12
    rpm_limit: float | None = 12.0
    min_confidence: float = 0.5
    refine_goal_times: bool = True
    refine_max_gap_sec: int = 180
    home_team: str = "德国"
    away_team: str = "库拉索"
    resume: bool = False
    no_model: bool = False


@dataclass
class ScoreboardReading:
    frame_id: str
    video_time_sec: float
    visible: bool
    home_score: int | None
    away_score: int | None
    clock: str | None
    confidence: float
    raw_text: str
    replay: bool = False
    image_path: str | None = None

    def score_tuple(self) -> tuple[int, int] | None:
        if self.home_score is None or self.away_score is None:
            return None
        return self.home_score, self.away_score


class ScoreboardGoalRunner:
    def __init__(self, options: ScoreboardGoalOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.crop_dir = ensure_dir(self.out_dir / "scoreboard_crops")
        self.refined_crop_dir = ensure_dir(self.out_dir / "scoreboard_refined_crops")
        self.raw_dir = ensure_dir(self.out_dir / "scoreboard_raw")
        self.client = InternClient(load_intern_config(), timeout=300)

    def run(self) -> Path:
        source_doc = read_json(self.options.source_events_path)
        source_events = _extract_events(source_doc)

        if self.options.precomputed_goals_path:
            goal_events = _load_precomputed_goal_events(self.options.precomputed_goals_path)
            merged_doc = self._merge_goal_events(source_doc, source_events, goal_events)
            write_json(self.out_dir / "scoreboard_goal_events.json", goal_events)
            write_json(self.out_dir / f"final_events_guarded_{self.options.output_version}.json", merged_doc)
            write_text(self.out_dir / "scoreboard_goal_report.md", _build_scoreboard_goal_report([], [], goal_events, merged_doc, self.options.output_version))
            return self.out_dir

        if self.options.precomputed_readings_path:
            readings = _load_scoreboard_readings(self.options.precomputed_readings_path)
            goals = detect_score_jumps(readings, self.options.min_confidence)
            goal_events = [
                _goal_to_v4_event(
                    goal,
                    index,
                    self.options.home_team,
                    self.options.away_team,
                    self.options.goal_timestamp_policy,
                )
                for index, goal in enumerate(goals, start=1)
            ]
            merged_doc = self._merge_goal_events(source_doc, source_events, goal_events)
            write_json(self.out_dir / "scoreboard_readings_merged.json", [reading.__dict__ for reading in readings])
            write_json(self.out_dir / "scoreboard_goal_events.json", goal_events)
            write_json(self.out_dir / f"final_events_guarded_{self.options.output_version}.json", merged_doc)
            write_text(self.out_dir / "scoreboard_goal_report.md", _build_scoreboard_goal_report([], [], goal_events, merged_doc, self.options.output_version))
            return self.out_dir

        frames = _load_frame_index(self.options.frame_index_path)

        coarse_frames = _select_interval_frames(frames, self.options.coarse_interval_sec)
        coarse_crops = self._extract_crops_from_frames(coarse_frames, self.crop_dir, prefix="sb")
        coarse_readings = self._read_scoreboard_crops(coarse_crops, stage="coarse")
        readings = list(coarse_readings)

        initial_goals = detect_score_jumps(readings, self.options.min_confidence)
        refined_readings: list[ScoreboardReading] = []
        if self.options.refine_goal_times and initial_goals:
            refined_readings = self._refine_goal_windows(initial_goals, frames)
            if refined_readings:
                readings = merge_scoreboard_readings(readings, refined_readings)

        goals = detect_score_jumps(readings, self.options.min_confidence)
        goal_events = [
            _goal_to_v4_event(
                goal,
                index,
                self.options.home_team,
                self.options.away_team,
                self.options.goal_timestamp_policy,
            )
            for index, goal in enumerate(goals, start=1)
        ]
        merged_doc = self._merge_goal_events(source_doc, source_events, goal_events)

        write_json(self.out_dir / "scoreboard_readings_coarse.json", [reading.__dict__ for reading in coarse_readings])
        write_json(self.out_dir / "scoreboard_readings_refined.json", [reading.__dict__ for reading in refined_readings])
        write_json(self.out_dir / "scoreboard_readings_merged.json", [reading.__dict__ for reading in readings])
        write_json(self.out_dir / "scoreboard_goal_events.json", goal_events)
        write_json(self.out_dir / f"final_events_guarded_{self.options.output_version}.json", merged_doc)
        write_text(self.out_dir / "scoreboard_goal_report.md", _build_scoreboard_goal_report(coarse_readings, refined_readings, goal_events, merged_doc, self.options.output_version))
        return self.out_dir

    def _extract_crops_from_frames(self, frames: list[dict[str, Any]], out_dir: Path, prefix: str) -> list[tuple[str, Path, float]]:
        out_dir.mkdir(parents=True, exist_ok=True)
        crops: list[tuple[str, Path, float]] = []
        for frame in frames:
            image_path = Path(frame["path"])
            if not image_path.is_absolute():
                image_path = Path.cwd() / image_path
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            video_time = float(frame.get("timestamp_seconds") or timestamp_to_seconds(frame.get("timestamp")))
            crop = crop_scoreboard(image)
            frame_id = f"{prefix}_{int(round(video_time)):05d}"
            path = out_dir / f"{frame_id}.jpg"
            cv2.imwrite(str(path), crop)
            crops.append((frame_id, path, video_time))
        return crops

    def _extract_crops_from_video(self, times_sec: list[int], out_dir: Path, prefix: str) -> list[tuple[str, Path, float]]:
        if self.options.video_path is None:
            return []
        video_path = _opencv_safe_video_path(self.options.video_path, self.out_dir)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []
        out_dir.mkdir(parents=True, exist_ok=True)
        crops: list[tuple[str, Path, float]] = []
        for second in times_sec:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0, int(second * 1000)))
            ok, frame = cap.read()
            if not ok:
                continue
            crop = crop_scoreboard(frame)
            frame_id = f"{prefix}_{int(second):05d}"
            path = out_dir / f"{frame_id}.jpg"
            cv2.imwrite(str(path), crop)
            crops.append((frame_id, path, float(second)))
        cap.release()
        return crops

    def _read_scoreboard_crops(self, crops: list[tuple[str, Path, float]], stage: str) -> list[ScoreboardReading]:
        if self.options.no_model:
            return []
        if not self.client.enabled():
            raise RuntimeError("INTERN_S2_API_KEY is not configured; cannot run scoreboard OCR.")
        readings: list[ScoreboardReading] = []
        batch_size = max(1, self.options.batch_size)
        min_submit_interval = 60.0 / self.options.rpm_limit if self.options.rpm_limit else 0.0
        last_submit = 0.0
        for start in range(0, len(crops), batch_size):
            batch = crops[start : start + batch_size]
            batch_index = start // batch_size
            raw_path = self.raw_dir / f"{stage}_batch_{batch_index:04d}.json"
            fingerprint = _fingerprint_batch(batch, stage)
            if self.options.resume and raw_path.exists():
                cached = read_json(raw_path)
                if cached.get("ok") and cached.get("request_fingerprint") == fingerprint:
                    readings.extend(_readings_from_cached(cached, batch))
                    continue
            if min_submit_interval > 0 and last_submit > 0:
                wait = min_submit_interval - (time.time() - last_submit)
                if wait > 0:
                    time.sleep(wait)
            result = self._read_one_batch(batch, batch_index, stage, fingerprint)
            write_json(raw_path, result)
            readings.extend(_readings_from_cached(result, batch))
            last_submit = time.time()
        return sorted(readings, key=lambda item: item.video_time_sec)

    def _read_one_batch(
        self,
        batch: list[tuple[str, Path, float]],
        batch_index: int,
        stage: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        prompt = (
            "You are a football broadcast scoreboard OCR tool. Read only the broadcast scoreboard from each crop. "
            "Return JSON Lines only, one compact JSON object per frame_id. "
            "Fields: frame_id, visible, home_score, away_score, clock, confidence, raw_text, replay. "
            "The match is Germany vs Curacao. The left/home score is Germany, the right/away score is Curacao. "
            "If the scoreboard is not visible or unreadable, use visible=false and null scores/clock. "
            "If the crop is a replay graphic or the clock/score belongs to a replay, set replay=true. "
            "Do not infer goals, do not use outside match knowledge, and do not add explanations."
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for frame_id, path, video_time in batch:
            content.append({"type": "text", "text": f"frame_id={frame_id} video_time={seconds_to_timestamp(video_time)}"})
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(path)}})
        started = time.time()
        response = self.client.chat(
            [{"role": "user", "content": content}],
            temperature=0,
            max_tokens=min(6000, max(1000, len(batch) * 180)),
            thinking_mode=False,
        )
        finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
        parsed = None
        parse_error = None
        try:
            parsed = _parse_readings_payload(response.content)
        except Exception as exc:
            parse_error = str(exc)
        return {
            "ok": parse_error is None and finish_reason != "length",
            "stage": stage,
            "batch_index": batch_index,
            "request_fingerprint": fingerprint,
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
            "frames": [
                {"frame_id": frame_id, "path": str(path), "video_time_sec": video_time}
                for frame_id, path, video_time in batch
            ],
        }

    def _refine_goal_windows(self, goals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> list[ScoreboardReading]:
        all_refined: list[ScoreboardReading] = []
        for index, goal in enumerate(goals, start=1):
            previous = goal.get("previous_reading")
            current = goal.get("current_reading")
            if not isinstance(previous, ScoreboardReading) or not isinstance(current, ScoreboardReading):
                continue
            start = int(previous.video_time_sec) + 1
            end = int(current.video_time_sec)
            if end <= start or end - start > self.options.refine_max_gap_sec:
                continue
            times = list(range(start, end + 1))
            refine_dir = self.refined_crop_dir / f"G{index:02d}"
            crops = self._extract_crops_from_video(times, refine_dir, prefix=f"g{index:02d}")
            if not crops:
                selected_frames = _select_nearest_frames(frames, times)
                crops = self._extract_crops_from_frames(selected_frames, refine_dir, prefix=f"g{index:02d}")
            all_refined.extend(self._read_scoreboard_crops(crops, stage=f"refine_g{index:02d}"))
        return all_refined

    def _merge_goal_events(
        self,
        source_doc: Any,
        source_events: list[dict[str, Any]],
        goal_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        non_goal_events = [dict(event) for event in source_events if str(event.get("event_type") or "") != "goal"]
        merged_events = sorted([*non_goal_events, *goal_events], key=lambda event: _event_video_seconds(event))
        for index, event in enumerate(merged_events, start=1):
            event["event_id"] = f"F{index:04d}"
        doc = dict(source_doc) if isinstance(source_doc, dict) else {"source_events": source_doc}
        doc["final_events"] = merged_events
        summary = {
            "policy": "scoreboard_ocr_score_jump_goals",
            "goal_timestamp_policy": self.options.goal_timestamp_policy,
            "source_events": len(source_events),
            "source_goal_events": sum(1 for event in source_events if str(event.get("event_type") or "") == "goal"),
            "scoreboard_goal_events": len(goal_events),
            "final_events": len(merged_events),
        }
        doc["v4_3_scoreboard_goal_summary"] = summary
        doc[f"{self.options.output_version}_scoreboard_goal_summary"] = summary
        notes = list(doc.get("quality_notes") or [])
        notes.append(f"{self.options.output_version.upper()}: goal events replaced by scoreboard OCR score-jump detections.")
        doc["quality_notes"] = notes
        return doc


def crop_scoreboard(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    x0 = int(width * 0.70)
    x1 = width
    y0 = 0
    y1 = int(height * 0.22)
    return frame[y0:y1, x0:x1]


def detect_score_jumps(readings: list[ScoreboardReading], min_confidence: float = 0.5) -> list[dict[str, Any]]:
    goals: list[dict[str, Any]] = []
    previous: ScoreboardReading | None = None
    for reading in sorted(readings, key=lambda item: item.video_time_sec):
        score = reading.score_tuple()
        if (
            not reading.visible
            or reading.replay
            or reading.confidence < min_confidence
            or score is None
            or not _score_in_reasonable_range(score)
        ):
            continue
        if previous is None:
            previous = reading
            continue
        previous_score = previous.score_tuple()
        if previous_score is None:
            previous = reading
            continue
        if score == previous_score:
            previous = reading
            continue
        home_delta = score[0] - previous_score[0]
        away_delta = score[1] - previous_score[1]
        if home_delta < 0 or away_delta < 0:
            continue
        if home_delta + away_delta != 1:
            continue
        goals.append(
            {
                "previous_score": previous_score,
                "score_after": score,
                "team": "home" if home_delta == 1 else "away",
                "video_time_sec": reading.video_time_sec,
                "clock": reading.clock,
                "confidence": reading.confidence,
                "previous_reading": previous,
                "current_reading": reading,
            }
        )
        previous = reading
    return goals


def merge_scoreboard_readings(
    coarse: list[ScoreboardReading],
    refined: list[ScoreboardReading],
) -> list[ScoreboardReading]:
    by_time: dict[float, ScoreboardReading] = {reading.video_time_sec: reading for reading in coarse}
    for reading in refined:
        existing = by_time.get(reading.video_time_sec)
        if existing is None or reading.confidence >= existing.confidence:
            by_time[reading.video_time_sec] = reading
    return sorted(by_time.values(), key=lambda item: item.video_time_sec)


def _goal_to_v4_event(
    goal: dict[str, Any],
    index: int,
    home_team: str,
    away_team: str,
    goal_timestamp_policy: str = "first_after_jump",
) -> dict[str, Any]:
    previous: ScoreboardReading = goal["previous_reading"]
    current: ScoreboardReading = goal["current_reading"]
    previous_score = goal["previous_score"]
    score_after = goal["score_after"]
    anchor = previous if goal_timestamp_policy == "last_before_jump" else current
    team = home_team if goal["team"] == "home" else away_team
    score_text = f"{score_after[0]}-{score_after[1]}"
    previous_clock = _normalize_clock(previous.clock)
    current_clock = _normalize_clock(current.clock)
    clock = _normalize_clock(anchor.clock) or current_clock or previous_clock
    video_timestamp = seconds_to_timestamp(anchor.video_time_sec)
    previous_timestamp = seconds_to_timestamp(previous.video_time_sec)
    current_timestamp = seconds_to_timestamp(current.video_time_sec)
    match_minute, stoppage = _clock_to_minute(clock)
    source_event_ids = [anchor.frame_id]
    if goal_timestamp_policy == "last_before_jump" and current.frame_id != anchor.frame_id:
        source_event_ids.append(current.frame_id)
    return {
        "event_id": f"G{index:04d}",
        "video_timestamp": video_timestamp,
        "timestamp": video_timestamp,
        "match_time": clock or video_timestamp,
        "period": "first_half" if anchor.video_time_sec < 3600 else "second_half",
        "match_minute": match_minute,
        "stoppage_minute": stoppage,
        "match_time_source": "scoreboard_ocr",
        "event_type": "goal",
        "title": f"{team} team goal, score becomes {score_text}",
        "certainty": "confirmed",
        "evidence_level": "scoreboard_ocr",
        "confidence": round(float(current.confidence), 3),
        "importance": "high",
        "source_event_ids": source_event_ids,
        "linked_event_id": "",
        "score_after": score_text,
        "team": team,
        "goal_timestamp_policy": goal_timestamp_policy,
        "score_jump_previous_timestamp": previous_timestamp,
        "score_jump_current_timestamp": current_timestamp,
        "evidence": [
            f"Scoreboard jumped from {previous_score[0]}-{previous_score[1]} to {score_text}",
            (
                f"Last-before-jump OCR anchor: score {previous_score[0]}-{previous_score[1]}, "
                f"clock {previous_clock or 'unknown'}, video {previous_timestamp}; "
                f"first-after-jump OCR: score {score_text}, clock {current_clock or 'unknown'}, video {current_timestamp}"
            ),
        ],
        "needs_more_review": False,
        "script_angle": f"{team} goal confirmed by scoreboard score jump to {score_text}",
    }


def _build_scoreboard_goal_report(
    coarse: list[ScoreboardReading],
    refined: list[ScoreboardReading],
    goal_events: list[dict[str, Any]],
    merged_doc: dict[str, Any],
    output_version: str = "v4_3",
) -> str:
    summary = merged_doc.get(f"{output_version}_scoreboard_goal_summary") or merged_doc.get("v4_3_scoreboard_goal_summary") or {}
    lines = [
        f"# {output_version.upper()} Scoreboard Goal Report",
        "",
        f"- Coarse OCR readings: {len(coarse)}",
        f"- Refined OCR readings: {len(refined)}",
        f"- Source goal events: {summary.get('source_goal_events')}",
        f"- Scoreboard goal events: {summary.get('scoreboard_goal_events')}",
        f"- Final events: {summary.get('final_events')}",
        f"- Goal timestamp policy: {summary.get('goal_timestamp_policy')}",
        "",
        "| # | Video Time | Match Clock | Team | Score After | Confidence | Evidence |",
        "|---:|---|---|---|---|---:|---|",
    ]
    for index, event in enumerate(goal_events, start=1):
        evidence = " ; ".join(str(item) for item in event.get("evidence") or [])
        lines.append(
            f"| {index} | {event.get('video_timestamp')} | {event.get('match_time')} | "
            f"{event.get('team')} | {event.get('score_after')} | {event.get('confidence')} | {evidence} |"
        )
    lines.append("")
    return "\n".join(lines)


def _load_precomputed_goal_events(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, dict):
        raw_events = data.get("scoreboard_goal_events") or data.get("final_events") or data.get("events") or []
    elif isinstance(data, list):
        raw_events = data
    else:
        raw_events = []

    goals: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        if item.get("event_type") not in (None, "", "goal"):
            continue
        event = dict(item)
        event["event_type"] = "goal"
        video_timestamp = event.get("video_timestamp") or event.get("timestamp") or event.get("start")
        if not video_timestamp:
            continue
        event["video_timestamp"] = video_timestamp
        event["timestamp"] = video_timestamp
        goals.append(event)
    goals.sort(key=_event_video_seconds)
    return goals


def _load_scoreboard_readings(path: Path) -> list[ScoreboardReading]:
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"scoreboard readings must be a list: {path}")
    readings: list[ScoreboardReading] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        readings.append(
            ScoreboardReading(
                frame_id=str(item.get("frame_id") or ""),
                video_time_sec=_to_seconds_float(item.get("video_time_sec")),
                visible=_to_bool(item.get("visible", False)),
                home_score=_to_int_or_none(item.get("home_score")),
                away_score=_to_int_or_none(item.get("away_score")),
                clock=_normalize_clock(item.get("clock")),
                confidence=_to_float(item.get("confidence")),
                raw_text=str(item.get("raw_text") or ""),
                replay=_to_bool(item.get("replay", False)),
                image_path=str(item.get("image_path")) if item.get("image_path") else None,
            )
        )
    return sorted(readings, key=lambda item: item.video_time_sec)


def _load_frame_index(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"frame index must be a list: {path}")
    frames = [dict(item) for item in data if isinstance(item, dict) and item.get("path")]
    frames.sort(key=lambda item: float(item.get("timestamp_seconds") or timestamp_to_seconds(item.get("timestamp"))))
    return frames


def _select_interval_frames(frames: list[dict[str, Any]], interval_sec: int) -> list[dict[str, Any]]:
    if not frames:
        return []
    duration = int(float(frames[-1].get("timestamp_seconds") or timestamp_to_seconds(frames[-1].get("timestamp"))))
    times = list(range(0, duration + 1, max(1, interval_sec)))
    if duration not in times:
        times.append(duration)
    return _select_nearest_frames(frames, times)


def _select_nearest_frames(frames: list[dict[str, Any]], times: list[int]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    if not frames:
        return selected
    frame_times = [float(item.get("timestamp_seconds") or timestamp_to_seconds(item.get("timestamp"))) for item in frames]
    cursor = 0
    seen: set[str] = set()
    for time_sec in times:
        while cursor + 1 < len(frames) and abs(frame_times[cursor + 1] - time_sec) <= abs(frame_times[cursor] - time_sec):
            cursor += 1
        frame = frames[cursor]
        key = str(frame.get("path"))
        if key not in seen:
            selected.append(frame)
            seen.add(key)
    return selected


def _extract_events(source_doc: Any) -> list[dict[str, Any]]:
    if isinstance(source_doc, dict):
        events = source_doc.get("final_events") or source_doc.get("events") or []
    elif isinstance(source_doc, list):
        events = source_doc
    else:
        events = []
    return [dict(event) for event in events if isinstance(event, dict)]


def _readings_from_cached(result: dict[str, Any], batch: list[tuple[str, Path, float]]) -> list[ScoreboardReading]:
    frame_meta = {frame_id: (path, video_time) for frame_id, path, video_time in batch}
    readings: list[ScoreboardReading] = []
    parsed = result.get("parsed")
    if not isinstance(parsed, list):
        return readings
    for item in parsed:
        if not isinstance(item, dict):
            continue
        frame_id = str(item.get("frame_id") or "")
        path, video_time = frame_meta.get(frame_id, (None, 0.0))
        readings.append(
            ScoreboardReading(
                frame_id=frame_id,
                video_time_sec=float(video_time),
                visible=_to_bool(item.get("visible", False)),
                home_score=_to_int_or_none(item.get("home_score")),
                away_score=_to_int_or_none(item.get("away_score")),
                clock=_normalize_clock(item.get("clock")),
                confidence=_to_float(item.get("confidence")),
                raw_text=str(item.get("raw_text") or ""),
                replay=_to_bool(item.get("replay", False)),
                image_path=str(path) if path else None,
            )
        )
    return readings


def _parse_readings_payload(text: str) -> list[dict[str, Any]]:
    cleaned = (text or "").strip()
    fence = re.search(r"```(?:json|jsonl)?\s*(.*?)```", cleaned, flags=re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        payload = json.loads(cleaned)
        return _as_items(payload)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end >= start:
        try:
            payload = json.loads(cleaned[start : end + 1])
            items = _as_items(payload)
            if items:
                return items
        except json.JSONDecodeError:
            pass

    items = []
    for line in cleaned.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped.startswith("{"):
            continue
        try:
            items.extend(_as_items(json.loads(stripped)))
        except json.JSONDecodeError:
            continue
    if items:
        return items

    decoder = json.JSONDecoder()
    index = 0
    while index < len(cleaned):
        start = cleaned.find("{", index)
        if start < 0:
            break
        try:
            payload, end = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        items.extend(_as_items(payload))
        index = start + end
    if items:
        return items
    raise ValueError("No scoreboard JSON objects found in OCR response")


def _as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _fingerprint_batch(batch: list[tuple[str, Path, float]], stage: str) -> str:
    payload = {
        "stage": stage,
        "frames": [(frame_id, str(path), video_time) for frame_id, path, video_time in batch],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _opencv_safe_video_path(video_path: Path, out_dir: Path) -> Path:
    cap = cv2.VideoCapture(str(video_path))
    if cap.isOpened():
        cap.release()
        return video_path
    cap.release()
    safe = out_dir / "_video_ascii_link.mp4"
    if not safe.exists():
        try:
            os.link(video_path, safe)
        except OSError:
            return video_path
    return safe


def _event_video_seconds(event: dict[str, Any]) -> float:
    return timestamp_to_seconds(event.get("video_timestamp") or event.get("timestamp") or event.get("start"))


def _score_in_reasonable_range(score: tuple[int, int]) -> bool:
    return 0 <= score[0] <= 12 and 0 <= score[1] <= 12


def _normalize_clock(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unknown"}:
        return None
    plus = re.search(r"(\d{1,3})\s*\+\s*(\d{1,2})", text)
    if plus:
        return f"{int(plus.group(1))}+{int(plus.group(2))}'"
    clock = re.search(r"(\d{1,3})\s*[:：]\s*(\d{1,2})", text)
    if clock:
        return f"{int(clock.group(1)):02d}:{int(clock.group(2)):02d}"
    minute = re.search(r"(\d{1,3})", text)
    if minute:
        return f"{int(minute.group(1)):02d}:00"
    return text


def _clock_to_minute(clock: str | None) -> tuple[int, int]:
    if not clock:
        return 0, 0
    plus = re.fullmatch(r"(\d{1,3})\+(\d{1,2})'?", clock)
    if plus:
        return int(plus.group(1)), int(plus.group(2))
    match = re.fullmatch(r"(\d{1,3}):(\d{2})", clock)
    if match:
        return int(match.group(1)), 0
    minute = re.search(r"(\d{1,3})", clock)
    return (int(minute.group(1)), 0) if minute else (0, 0)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _to_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else None


def _to_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _to_seconds_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return timestamp_to_seconds(value)
