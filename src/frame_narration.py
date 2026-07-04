from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_intern_config
from .intern_client import InternClient
from .io_utils import ensure_dir, extract_json_object, image_to_data_url, read_json, seconds_to_timestamp, timestamp_to_seconds, write_json, write_text


@dataclass
class FrameNarrationOptions:
    frame_index_path: Path
    out_dir: Path
    segment_seconds: float = 60.0
    max_images: int = 30
    concurrency: int = 3
    rpm_limit: float | None = 15.0
    temperature: float = 0.1
    max_tokens: int = 6000
    resume: bool = False
    max_segments: int | None = None
    no_model: bool = False


class FrameNarrationRunner:
    def __init__(self, options: FrameNarrationOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.raw_dir = ensure_dir(self.out_dir / "raw_segments")
        self.client = InternClient(load_intern_config(), timeout=300)

    def run(self) -> Path:
        frames = read_json(self.options.frame_index_path)
        segments = self._build_segments(frames)
        if self.options.max_segments:
            segments = segments[: self.options.max_segments]
        write_json(self.out_dir / "segment_plan.json", segments)

        if self.options.no_model:
            write_json(self.out_dir / "segment_descriptions.json", [])
            write_text(self.out_dir / "match_observation_timeline.md", "# Match Observation Timeline\n")
            return self.out_dir

        results = self._run_segments(segments)
        write_json(self.out_dir / "segment_results.json", results)
        descriptions = self._collect_descriptions(results)
        write_json(self.out_dir / "segment_descriptions.json", descriptions)
        write_text(self.out_dir / "match_observation_timeline.md", self._build_timeline_md(descriptions))
        write_json(self.out_dir / "narration_runtime_summary.json", self._runtime_summary(results))
        return self.out_dir

    def _build_segments(self, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not frames:
            return []
        max_second = max(float(item.get("timestamp_seconds") or timestamp_to_seconds(item.get("timestamp"))) for item in frames)
        segment_count = int(max_second // self.options.segment_seconds) + 1
        segments = []
        for segment_idx in range(segment_count):
            start = segment_idx * self.options.segment_seconds
            end = start + self.options.segment_seconds
            segment_frames = [
                item for item in frames
                if start <= float(item.get("timestamp_seconds") or timestamp_to_seconds(item.get("timestamp"))) < end
            ]
            if not segment_frames:
                continue
            if len(segment_frames) > self.options.max_images:
                segment_frames = self._downsample_frames(segment_frames, self.options.max_images)
            segments.append(
                {
                    "segment_id": f"S{segment_idx + 1:04d}",
                    "start": seconds_to_timestamp(start),
                    "end": seconds_to_timestamp(min(end - 0.001, max_second)),
                    "start_seconds": round(start, 3),
                    "end_seconds": round(min(end, max_second), 3),
                    "frames": segment_frames,
                }
            )
        return segments

    def _downsample_frames(self, frames: list[dict[str, Any]], max_images: int) -> list[dict[str, Any]]:
        if len(frames) <= max_images:
            return frames
        # Preserve temporal coverage. For 2s frames and 60s segments, this usually keeps all 30.
        step = (len(frames) - 1) / (max_images - 1)
        selected = [frames[round(i * step)] for i in range(max_images)]
        return selected

    def _run_segments(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        started = time.time()
        results: list[dict[str, Any]] = []
        min_submit_interval = 60.0 / self.options.rpm_limit if self.options.rpm_limit else 0.0
        last_submit = 0.0

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.options.concurrency) as executor:
            future_map = {}
            for segment in segments:
                raw_path = self.raw_dir / f"{segment['segment_id']}.json"
                request_fingerprint = self._request_fingerprint(segment)
                if self.options.resume and raw_path.exists():
                    cached = read_json(raw_path)
                    if self._can_reuse_cached_result(cached, request_fingerprint):
                        results.append(cached)
                        continue
                if min_submit_interval > 0 and last_submit > 0:
                    wait = min_submit_interval - (time.time() - last_submit)
                    if wait > 0:
                        time.sleep(wait)
                future = executor.submit(self._run_one_segment, segment, raw_path, request_fingerprint)
                future_map[future] = segment
                last_submit = time.time()

            for future in concurrent.futures.as_completed(future_map):
                segment = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    result = {
                        "segment_id": segment["segment_id"],
                        "ok": False,
                        "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                    }
                    write_json(self.raw_dir / f"{segment['segment_id']}.json", result)
                    results.append(result)

        results.sort(key=lambda item: item.get("segment_id", ""))
        runtime = self._runtime_summary(results)
        runtime["wall_elapsed_seconds"] = round(time.time() - started, 3)
        write_json(self.out_dir / "narration_runtime_summary.json", runtime)
        return results

    def _request_fingerprint(self, segment: dict[str, Any]) -> str:
        payload = {
            "stage": "frame_narration",
            "prompt_version": "v4_ocr_score_panel",
            "max_tokens": self.options.max_tokens,
            "temperature": self.options.temperature,
            "segment": segment,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _can_reuse_cached_result(cached: dict[str, Any], request_fingerprint: str) -> bool:
        if not cached.get("ok"):
            return False
        if cached.get("finish_reason") == "length":
            return False
        return cached.get("request_fingerprint") == request_fingerprint

    def _run_one_segment(self, segment: dict[str, Any], raw_path: Path, request_fingerprint: str) -> dict[str, Any]:
        prompt = self._build_prompt(segment)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for frame in segment["frames"]:
            content.append(
                {
                    "type": "text",
                    "text": f"FRAME {frame['frame_index']} | timestamp={frame['timestamp']} | motion_score={frame.get('motion_score')}",
                }
            )
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(Path(frame["path"]))}})

        messages = [
            {"role": "system", "content": "你是足球转播视频的视觉观察记录员。只输出 JSON，不要输出推理过程。"},
            {"role": "user", "content": content},
        ]
        started = time.time()
        response = self.client.chat(
            messages,
            temperature=self.options.temperature,
            max_tokens=self.options.max_tokens,
            thinking_mode=False,
        )
        parsed = None
        parse_error = None
        try:
            parsed = extract_json_object(response.content)
        except Exception as exc:
            parse_error = str(exc)
        finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")

        result = {
            "segment_id": segment["segment_id"],
            "start": segment["start"],
            "end": segment["end"],
            "frame_count": len(segment["frames"]),
            "ok": parse_error is None and finish_reason != "length",
            "request_fingerprint": request_fingerprint,
            "request_max_tokens": self.options.max_tokens,
            "prompt_version": "v4_ocr_score_panel",
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
        }
        write_json(raw_path, result)
        return result

    def _build_prompt(self, segment: dict[str, Any]) -> str:
        frame_table = "\n".join(
            f"- FRAME {frame['frame_index']}: {frame['timestamp']} motion={frame.get('motion_score')}"
            for frame in segment["frames"]
        )
        return f"""你会看到一段足球转播视频中按时间排序的抽帧。该段约 1 分钟，通常每 2 秒一帧。

本场比赛固定信息：
- 比赛双方固定为：德国 vs 库拉索。
- 德国队通常为白/黑球衣，库拉索队通常为蓝/黄元素球衣。
- CURAÇAO、CURACAO、Curaçao、库拉索都指库拉索。
- 禁止把库拉索误写成哥伦比亚、委内瑞拉或其他第三方国家队。
- 如果画面或比分牌看不清队名，只能写“德国球员”“库拉索球员”或 unknown，不要猜新队名。

本段信息：
- segment_id: {segment['segment_id']}
- time_range: {segment['start']} - {segment['end']}
- frame_count: {len(segment['frames'])}

帧索引：
{frame_table}

任务：
请把这一分钟画面转换成尽量详尽但不胡编的“视觉观察文字”。这一步不是最终判罚，而是把图片压缩成后续可分析的文本。

记录重点：
1. 比赛状态：赛前仪式、正常比赛、死球、回放、庆祝、半场/全场等。
2. 镜头变化：全景、近景、观众席、替补席、裁判、比分牌、转播字幕、回放画面。
3. 攻防过程：哪一方在进攻、防守是否密集、是否在禁区/球门附近、是否形成射门或混战。
4. 可能事件：goal_or_celebration、replay、corner、free_kick、penalty、substitution、card_scene、referee_dispute、attack_highlight、halftime、fulltime。
5. 可见文字：比分牌、时间、球员名、字幕条、阵容/换人/进球信息。如果看不清就写 unknown。
6. OCR/比分牌面板：遇到射门、入网、扑出、庆祝、回放、点球或任意球直接攻门时，必须先记录前后可见比分、比赛分钟、进球信息条、回放标识，再描述射门姿态和结果。

约束：
1. 不要编造球员姓名；只有画面字幕清楚出现时才可记录。
2. 不要把赛前入场、阵容展示误写成比赛事件。
3. 不确定时写“疑似”，并降低 confidence。
4. 每条 observation 必须绑定给定帧的 timestamp。
5. 输出严格 JSON，不要 Markdown，不要 Thinking Process。

输出格式：
{{
  "segment_id": "{segment['segment_id']}",
  "start": "{segment['start']}",
  "end": "{segment['end']}",
  "segment_summary": "这一分钟的整体视觉过程概述",
  "score_panel_summary": "本段可见比分牌/OCR/进球信息条摘要；没有则 unknown",
  "observations": [
    {{
      "frame_index": 0,
      "timestamp": "00:00:00",
      "scene_type": "pre_match|live_play|dead_ball|replay|celebration|close_up|crowd|bench|referee|set_piece|scoreboard|halftime|fulltime|unknown",
      "description": "画面上实际看到的内容",
      "visible_text": "可见字幕/比分/球员名；没有则 unknown",
      "scoreboard": "如 1-0；看不清则 unknown",
      "score_panel": "比赛分钟、比分变化、进球信息条、REPLAY/LIVE 标识；没有则 unknown",
      "possible_events": ["goal_or_celebration|replay|corner|free_kick|penalty|substitution|card_scene|referee_dispute|attack_highlight|halftime|fulltime"],
      "confidence": 0.0
    }}
  ],
  "event_candidates": [
    {{
      "timestamp": "00:00:00",
      "event_type": "goal_or_celebration|replay|corner|free_kick|penalty|substitution|card_scene|referee_dispute|attack_highlight|halftime|fulltime",
      "confidence": 0.0,
      "evidence": ["基于哪些观察"],
      "needs_image_review": true
    }}
  ]
}}"""

    def _collect_descriptions(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        for result in results:
            parsed = result.get("parsed")
            if isinstance(parsed, dict):
                descriptions.append(parsed)
            elif isinstance(parsed, list):
                descriptions.append(
                    {
                        "segment_id": result.get("segment_id"),
                        "start": result.get("start"),
                        "end": result.get("end"),
                        "segment_summary": "",
                        "observations": parsed,
                        "event_candidates": [],
                    }
                )
            else:
                descriptions.append(
                    {
                        "segment_id": result.get("segment_id"),
                        "start": result.get("start"),
                        "end": result.get("end"),
                        "segment_summary": f"PARSE_FAILED: {result.get('parse_error')}",
                        "observations": [],
                        "event_candidates": [],
                    }
                )
        descriptions.sort(key=lambda item: item.get("segment_id", ""))
        return descriptions

    def _build_timeline_md(self, descriptions: list[dict[str, Any]]) -> str:
        lines = ["# Match Observation Timeline", ""]
        for segment in descriptions:
            lines.extend(
                [
                    f"## {segment.get('segment_id')} {segment.get('start')} - {segment.get('end')}",
                    "",
                    segment.get("segment_summary") or "",
                    "",
                ]
            )
            observations = segment.get("observations") or []
            for obs in observations:
                if isinstance(obs, str):
                    lines.append(f"- {obs}")
                    continue
                if not isinstance(obs, dict):
                    continue
                possible = ", ".join(obs.get("possible_events") or [])
                lines.append(
                    f"- `{obs.get('timestamp')}` [{obs.get('scene_type')}] {obs.get('description')} "
                    f"(text: {obs.get('visible_text')}; score: {obs.get('scoreboard')}; events: {possible}; conf: {obs.get('confidence')})"
                )
            candidates = segment.get("event_candidates") or []
            if candidates:
                lines.extend(["", "Candidates:"])
                for cand in candidates:
                    lines.append(
                        f"- `{cand.get('timestamp')}` {cand.get('event_type')} conf={cand.get('confidence')} "
                        f"needs_review={cand.get('needs_image_review')} evidence={cand.get('evidence')}"
                    )
            lines.append("")
        return "\n".join(lines)

    def _runtime_summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = sum((item.get("usage") or {}).get("prompt_tokens", 0) for item in results)
        completion = sum((item.get("usage") or {}).get("completion_tokens", 0) for item in results)
        total = sum((item.get("usage") or {}).get("total_tokens", 0) for item in results)
        return {
            "segments": len(results),
            "success": sum(1 for item in results if item.get("ok")),
            "failures": sum(1 for item in results if not item.get("ok")),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "avg_total_tokens_per_segment": round(total / len(results), 1) if results else 0,
            "sum_request_elapsed_seconds": round(sum(item.get("elapsed_seconds", 0.0) for item in results), 3),
            "concurrency": self.options.concurrency,
            "rpm_limit": self.options.rpm_limit,
        }
