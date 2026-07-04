from __future__ import annotations

import concurrent.futures
import json
import math
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .config import load_intern_config
from .intern_client import InternClient
from .io_utils import ensure_dir, extract_json_object, image_to_data_url, seconds_to_timestamp, timestamp_to_seconds, write_json, write_text


CORE_DETECTORS = [
    "goal_celebration",
    "replay",
    "corner",
    "free_kick",
    "penalty",
    "substitution",
    "card_scene",
    "referee_dispute",
    "attack_highlight",
]

MULTI_EVENT_TYPES = [
    "goal_or_celebration",
    "replay",
    "corner",
    "free_kick",
    "penalty",
    "substitution",
    "card_scene",
    "referee_dispute",
    "attack_highlight",
    "halftime",
    "fulltime",
    "unknown",
]

DETECTOR_SPECS: dict[str, dict[str, str]] = {
    "goal_celebration": {
        "event_type": "goal_or_celebration",
        "definition": """判断是否展示进球或进球后庆祝。
典型视觉特征：
1. 多名队友拥抱、奔跑、滑跪或冲向同一名球员。
2. 观众席出现大面积欢呼或镜头切到看台。
3. 对方球员低头、摊手，门将回头看球网。
4. 转播画面可能切到慢动作回放。
5. 比分牌或转播图层可能发生变化。
不要误判：只看到射门动作但没有庆祝/比分变化时，输出 attack_highlight，不要判定为进球。""",
    },
    "replay": {
        "event_type": "replay",
        "definition": """判断是否是转播回放。
典型视觉特征：
1. 画面上明确出现 Replay、回放、慢动作或转播品牌回放标识。
2. 画面速度像慢动作。
3. 同一动作以不同角度重复出现。
4. 有转播特效、LOGO 转场、镜头拉近、慢镜头质感。
5. 画面不是正常比赛连续推进，而像事后重放。""",
    },
    "corner": {
        "event_type": "corner",
        "definition": """判断是否展示角球。
典型视觉特征：
1. 画面靠近球场角落，可能看到角旗、底线、边线。
2. 一名进攻球员在角旗附近摆球、后退助跑或准备传中。
3. 禁区内有大量攻防球员集中站位，准备争顶。
4. 镜头常在角旗区和禁区之间切换。
不要误判：边线附近控球不是角球；双手从头顶掷球是边线球；明显人墙更像任意球。""",
    },
    "free_kick": {
        "event_type": "free_kick",
        "definition": """判断是否展示任意球。
典型视觉特征：
1. 球静止摆放在犯规地点。
2. 主罚球员站在球后，可能有助跑距离。
3. 防守方多人排成人墙。
4. 裁判可能站在球和人墙之间，指挥距离。
5. 靠近禁区时，镜头通常正对球门、人墙和主罚球员。
不要误判：角旗区是角球；点球点是点球；中圈开球或门球没有人墙。""",
    },
    "penalty": {
        "event_type": "penalty",
        "definition": """判断是否展示点球。
典型视觉特征：
1. 球静止放在点球点。
2. 主罚球员独自站在球后。
3. 门将站在球门线上。
4. 其他球员站在禁区外或禁区弧外。
5. 镜头通常正对球门和主罚球员。
不要误判：有人墙更像任意球；角旗区是角球；运动战单刀不是点球。""",
    },
    "substitution": {
        "event_type": "substitution",
        "definition": """判断是否展示换人。
典型视觉特征：
1. 第四官员在场边举电子换人牌。
2. 一名球员从场内走向边线，另一名球员准备上场。
3. 画面出现替补席或技术区。
4. 转播字幕可能显示球员号码和换人图标。
不要误判：普通边线球、球员热身或教练指挥不是换人。""",
    },
    "card_scene": {
        "event_type": "card_scene",
        "definition": """判断是否展示出牌或纪律处罚场景。
典型视觉特征：
1. 裁判出现在画面中心或近景。
2. 裁判手臂举起，手中可能有黄色或红色小矩形牌。
3. 被判罚球员或多名球员围在裁判附近。
4. 转播字幕可能显示球员名、犯规信息或牌的图标。
要求：看不清牌色时输出 card_scene；明确看到黄色才写 yellow_card；明确看到红色才写 red_card。""",
    },
    "referee_dispute": {
        "event_type": "referee_dispute",
        "definition": """判断是否展示判罚争议。
典型视觉特征：
1. 多名球员围住裁判。
2. 球员有摊手、抗议、指向某处等动作。
3. 裁判做解释或制止手势。
4. 可能出现 VAR 标识，或裁判指向耳机/场边屏幕。
不要误判：普通犯规后球员站在一起，不要高置信度判为争议。""",
    },
    "attack_highlight": {
        "event_type": "attack_highlight",
        "definition": """判断是否是有解说价值的进攻高光。
典型视觉特征：
1. 球门附近出现高强度攻防。
2. 多名球员在禁区内聚集。
3. 门将、后卫、进攻球员都集中在门前区域。
4. 可能出现射门、封堵、解围、门前混战。
要求：无法确认扑救、射正、击中门框时，不要细分，只输出 attack_highlight。""",
    },
}


@dataclass
class VisualSpottingOptions:
    video_path: Path
    out_dir: Path
    interval_seconds: float = 2.0
    start_second: float = 0.0
    end_second: float | None = None
    batch_sizes: list[int] | None = None
    detectors: list[str] | None = None
    concurrency: int = 1
    rpm_limit: float | None = None
    max_frames: int | None = None
    max_batches_per_size: int | None = None
    reuse_frames: bool = False
    no_model: bool = False
    temperature: float = 0.1


class VisualSpottingRunner:
    def __init__(self, options: VisualSpottingOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.client = InternClient(load_intern_config(), timeout=240)

    def run(self) -> Path:
        frame_index = self._load_or_extract_frames()
        write_json(self.out_dir / "frame_index_2s.json", frame_index)
        batch_sizes = self.options.batch_sizes or [15, 30, 60]
        detectors = self._resolve_detectors(self.options.detectors or ["core"])
        plan = self._build_plan(frame_index, batch_sizes, detectors)
        write_json(self.out_dir / "spotting_plan.json", plan)

        if self.options.no_model:
            write_json(self.out_dir / "visual_events.json", [])
            return self.out_dir

        results = self._run_batches(plan)
        write_json(self.out_dir / "batch_results.json", results)
        events = self._collect_events(results)
        write_json(self.out_dir / "visual_events.json", events)
        merged_events = self._merge_events(events)
        write_json(self.out_dir / "merged_events.json", merged_events)
        summary = self._summarize(frame_index, plan, results, events, merged_events)
        write_text(self.out_dir / "visual_spotting_report.md", summary)
        return self.out_dir

    def _load_or_extract_frames(self) -> list[dict[str, Any]]:
        index_path = self.out_dir / "frame_index_2s.json"
        if self.options.reuse_frames and index_path.exists():
            return json.loads(index_path.read_text(encoding="utf-8"))

        frames_dir = ensure_dir(self.out_dir / "frames_2s")
        cap = cv2.VideoCapture(str(self.options.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.options.video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        duration = frame_count / fps if fps > 0 else 0.0
        start_second = max(0.0, self.options.start_second)
        end_second = min(duration, self.options.end_second) if self.options.end_second else duration
        seconds_list = list(np.arange(start_second, end_second, max(0.5, self.options.interval_seconds)))
        if self.options.max_frames:
            seconds_list = seconds_list[: self.options.max_frames]

        frame_index: list[dict[str, Any]] = []
        previous_thumb = None
        for idx, second in enumerate(seconds_list, start=1):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(second) * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            timestamp = seconds_to_timestamp(float(second))
            safe_ts = timestamp.replace(":", "-")
            path = frames_dir / f"frame_{idx:05d}_{safe_ts}.jpg"

            resized = self._resize_for_llm(frame)
            cv2.imwrite(str(path), resized, [int(cv2.IMWRITE_JPEG_QUALITY), 78])

            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            thumb = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
            motion_score = 0.0
            if previous_thumb is not None:
                motion_score = float(np.mean(cv2.absdiff(thumb, previous_thumb)))
            previous_thumb = thumb
            frame_index.append(
                {
                    "frame_index": idx,
                    "timestamp": timestamp,
                    "timestamp_seconds": round(float(second), 3),
                    "path": str(path),
                    "jpeg_bytes": path.stat().st_size,
                    "motion_score": round(motion_score, 3),
                }
            )
        cap.release()
        return frame_index

    def _resize_for_llm(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        max_side = 768
        scale = min(max_side / max(width, height), 1.0)
        if scale >= 1.0:
            return frame
        new_size = (int(width * scale), int(height * scale))
        return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)

    def _resolve_detectors(self, detectors: list[str]) -> list[str]:
        if len(detectors) == 1 and detectors[0] == "multi":
            return ["multi_event"]
        if len(detectors) == 1 and detectors[0] == "core":
            return CORE_DETECTORS
        if len(detectors) == 1 and detectors[0] == "all":
            return list(DETECTOR_SPECS)
        unknown = [name for name in detectors if name not in DETECTOR_SPECS and name != "multi_event"]
        if unknown:
            raise ValueError(f"Unknown detectors: {unknown}")
        return detectors

    def _build_plan(
        self,
        frame_index: list[dict[str, Any]],
        batch_sizes: list[int],
        detectors: list[str],
    ) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for batch_size in batch_sizes:
            batches = [
                frame_index[start : start + batch_size]
                for start in range(0, len(frame_index), batch_size)
            ]
            if self.options.max_batches_per_size:
                batches = batches[: self.options.max_batches_per_size]
            for batch_idx, frames in enumerate(batches, start=1):
                if not frames:
                    continue
                for detector in detectors:
                    plan.append(
                        {
                            "batch_id": f"bs{batch_size}_b{batch_idx:04d}_{detector}",
                            "batch_size": batch_size,
                            "batch_index": batch_idx,
                            "detector": detector,
                            "start": frames[0]["timestamp"],
                            "end": frames[-1]["timestamp"],
                            "frames": frames,
                        }
                    )
        return plan

    def _run_batches(self, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raw_dir = ensure_dir(self.out_dir / "raw_batches")
        results: list[dict[str, Any]] = []
        started = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.options.concurrency) as executor:
            future_map = {}
            min_submit_interval = 60.0 / self.options.rpm_limit if self.options.rpm_limit else 0.0
            last_submit = 0.0
            for item in plan:
                if min_submit_interval > 0 and last_submit > 0:
                    wait = min_submit_interval - (time.time() - last_submit)
                    if wait > 0:
                        time.sleep(wait)
                future = executor.submit(self._run_one_batch, item, raw_dir)
                future_map[future] = item
                last_submit = time.time()
            for future in concurrent.futures.as_completed(future_map):
                item = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        {
                            "batch_id": item["batch_id"],
                            "detector": item["detector"],
                            "batch_size": item["batch_size"],
                            "ok": False,
                            "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                        }
                    )
        results.sort(key=lambda x: (x.get("batch_size", 0), x.get("batch_id", "")))
        write_json(
            self.out_dir / "runtime_summary.json",
            {
                "requests": len(plan),
                "concurrency": self.options.concurrency,
                "rpm_limit": self.options.rpm_limit,
                "elapsed_seconds": round(time.time() - started, 3),
            },
        )
        return results

    def _run_one_batch(self, item: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
        detector = item["detector"]
        prompt = self._build_prompt(item)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for frame in item["frames"]:
            content.append(
                {
                    "type": "text",
                    "text": f"FRAME {frame['frame_index']} | timestamp={frame['timestamp']} | motion_score={frame['motion_score']}",
                }
            )
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(Path(frame["path"]))}})

        messages = [
            {"role": "system", "content": "你是足球转播视频事件识别器。只输出 JSON，不要输出推理过程。"},
            {"role": "user", "content": content},
        ]
        started = time.time()
        response = self.client.chat(
            messages,
            temperature=self.options.temperature,
            max_tokens=2400,
            thinking_mode=False,
        )
        parsed = None
        parse_error = None
        try:
            parsed = extract_json_object(response.content)
        except Exception as exc:
            parse_error = str(exc)

        result = {
            "batch_id": item["batch_id"],
            "detector": detector,
            "batch_size": item["batch_size"],
            "start": item["start"],
            "end": item["end"],
            "ok": parse_error is None,
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": response.raw.get("choices", [{}])[0].get("finish_reason"),
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
        }
        write_json(raw_dir / f"{item['batch_id']}.json", result)
        return result

    def _build_prompt(self, item: dict[str, Any]) -> str:
        if item["detector"] == "multi_event":
            return self._build_multi_event_prompt(item)
        spec = DETECTOR_SPECS[item["detector"]]
        frame_table = "\n".join(
            f"- FRAME {frame['frame_index']}: {frame['timestamp']} motion={frame['motion_score']}"
            for frame in item["frames"]
        )
        return f"""你会看到同一个足球转播视频中按时间排序的一批抽帧。

本批信息：
- batch_id: {item['batch_id']}
- detector: {item['detector']}
- expected_event_type: {spec['event_type']}
- time_range: {item['start']} - {item['end']}
- frame_count: {len(item['frames'])}

帧索引：
{frame_table}

识别任务：
{spec['definition']}

要求：
1. 只识别 expected_event_type 相关事件，不要顺手识别其他事件。
2. 如果本批没有明确证据，events 返回空数组。
3. 时间戳精度只能使用给定帧的 timestamp。
4. 不要编造球员姓名。
5. 只有看到明确视觉证据，confidence 才能 >= 0.75。
6. 模糊但可能有价值的片段可以给 0.55-0.74。
7. 证据不足时不要输出事件。
8. 对 replay 检测，普通转播水印、赛前入场、普通镜头切换都不能算 replay；必须看到明确回放/慢动作/多角度重复证据。
9. 只输出严格 JSON，不要 Markdown，不要 Thinking Process。

输出格式：
{{
  "batch_id": "{item['batch_id']}",
  "detector": "{item['detector']}",
  "events": [
    {{
      "frame_index": 0,
      "timestamp": "00:00:00",
      "event_type": "{spec['event_type']}",
      "confidence": 0.0,
      "certainty": "confirmed|probable|uncertain",
      "visual_evidence": ["..."],
      "commentary_value": "low|medium|high",
      "notes": ""
    }}
  ],
  "batch_summary": "一句话总结本批是否有相关事件"
}}"""

    def _build_multi_event_prompt(self, item: dict[str, Any]) -> str:
        frame_table = "\n".join(
            f"- FRAME {frame['frame_index']}: {frame['timestamp']} motion={frame['motion_score']}"
            for frame in item["frames"]
        )
        return f"""你会看到同一个足球转播视频中按时间排序的一批抽帧。

本批信息：
- batch_id: {item['batch_id']}
- detector: multi_event
- time_range: {item['start']} - {item['end']}
- frame_count: {len(item['frames'])}

帧索引：
{frame_table}

任务：
请在这一批图中识别所有有解说价值的足球事件。只允许从下面事件类型中选择：
{", ".join(MULTI_EVENT_TYPES)}

事件定义：
1. goal_or_celebration：进球或进球后庆祝。多名队友拥抱、奔跑、滑跪、门将回头看球网、看台欢呼、比分牌变化等。
2. replay：明确回放/慢动作/多角度重复/回放转场。普通转播水印、普通镜头切换、赛前入场不能算 replay。
3. corner：角旗区、底线边线、角球开出、禁区内多人准备争顶。
4. free_kick：静止球、人墙、裁判指挥距离、主罚球员助跑。
5. penalty：点球点、主罚球员独自面对球门、门将站门线、其他球员在禁区外。
6. substitution：必须看到场边换人牌、两名球员在边线交接、或明确换人字幕。单独看到教练/替补席/手势不能判为 substitution。
7. card_scene：裁判出牌或纪律处罚场景。看不清牌色时不要强分黄/红。
8. referee_dispute：多名球员围裁判、抗议、VAR、裁判解释。
9. attack_highlight：门前高强度攻防、射门/封堵/混战，但无法确认进球、扑救或门框。
10. halftime/fulltime：半场或全场结束，球员退场、握手、转播比分总结。

要求：
1. 每个事件必须绑定到某一张给定帧的 timestamp。
2. 不要编造球员姓名。
3. 没有明确证据的事件不要输出。
4. confidence >= 0.75 需要明确视觉证据。
5. 模糊但有价值的事件给 0.55-0.74。
6. 同一事件在相邻几帧重复出现，只输出一次。
7. 如果整批没有事件，events 返回空数组。
8. 对 substitution，必须有换人牌、球员上下场交接或换人字幕；只有教练站在场边/做手势时不要输出 substitution。
9. 只输出严格 JSON，不要 Markdown，不要 Thinking Process。

输出格式：
{{
  "batch_id": "{item['batch_id']}",
  "detector": "multi_event",
  "events": [
    {{
      "frame_index": 0,
      "timestamp": "00:00:00",
      "event_type": "goal_or_celebration|replay|corner|free_kick|penalty|substitution|card_scene|referee_dispute|attack_highlight|halftime|fulltime",
      "confidence": 0.0,
      "certainty": "confirmed|probable|uncertain",
      "visual_evidence": ["..."],
      "commentary_value": "low|medium|high",
      "notes": ""
    }}
  ],
  "batch_summary": "一句话总结本批识别结果"
}}"""

    def _collect_events(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for result in results:
            if not result.get("ok"):
                continue
            parsed = result.get("parsed") or {}
            if isinstance(parsed, list):
                parsed_events = parsed
            elif isinstance(parsed, dict):
                parsed_events = parsed.get("events", [])
            else:
                parsed_events = []
            for event in parsed_events:
                if not isinstance(event, dict):
                    continue
                confidence = float(event.get("confidence") or 0.0)
                if confidence < 0.45:
                    continue
                key = (result["detector"], str(event.get("timestamp")), str(event.get("event_type")))
                if key in seen:
                    continue
                seen.add(key)
                enriched = {
                    "event_id": f"V{len(events)+1:04d}",
                    "batch_id": result["batch_id"],
                    "batch_size": result["batch_size"],
                    "detector": result["detector"],
                    "source": "vlm",
                    **event,
                }
                events.append(enriched)
        events.sort(key=lambda x: (str(x.get("timestamp", "")), str(x.get("event_type", ""))))
        return events

    def _merge_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []

        priority = {
            "goal_or_celebration": 100,
            "penalty": 90,
            "card_scene": 80,
            "yellow_card": 80,
            "red_card": 85,
            "substitution": 70,
            "referee_dispute": 65,
            "corner": 60,
            "free_kick": 60,
            "attack_highlight": 55,
            "replay": 40,
        }

        enriched: list[dict[str, Any]] = []
        for event in events:
            item = dict(event)
            item["_seconds"] = timestamp_to_seconds(item.get("timestamp"))
            enriched.append(item)
        enriched.sort(key=lambda x: x["_seconds"])

        clusters: list[dict[str, Any]] = []
        for event in enriched:
            attached = False
            event_type = event.get("event_type", "")
            for cluster in reversed(clusters[-3:]):
                delta = abs(event["_seconds"] - cluster["center_seconds"])
                window = 60.0 if event_type == "replay" or cluster.get("primary_event_type") == "replay" else 35.0
                if delta <= window:
                    cluster["supporting_events"].append(_strip_internal(event))
                    cluster["start_seconds"] = min(cluster["start_seconds"], event["_seconds"])
                    cluster["end_seconds"] = max(cluster["end_seconds"], event["_seconds"])
                    cluster["center_seconds"] = (cluster["start_seconds"] + cluster["end_seconds"]) / 2
                    if priority.get(event_type, 0) > priority.get(cluster["primary_event_type"], 0):
                        cluster["primary_event_type"] = event_type
                        cluster["title"] = _event_title(event)
                    cluster["confidence"] = max(float(cluster["confidence"]), float(event.get("confidence") or 0.0))
                    attached = True
                    break
            if attached:
                continue
            clusters.append(
                {
                    "event_id": f"M{len(clusters)+1:04d}",
                    "timestamp": event.get("timestamp"),
                    "start_seconds": event["_seconds"],
                    "end_seconds": event["_seconds"],
                    "center_seconds": event["_seconds"],
                    "primary_event_type": event_type,
                    "title": _event_title(event),
                    "confidence": float(event.get("confidence") or 0.0),
                    "supporting_events": [_strip_internal(event)],
                }
            )

        merged = []
        for cluster in clusters:
            supporting = cluster["supporting_events"]
            visual_evidence: list[str] = []
            detectors: list[str] = []
            for event in supporting:
                detectors.append(str(event.get("detector", "")))
                evidence_items = event.get("visual_evidence") or []
                if isinstance(evidence_items, str):
                    evidence_items = [evidence_items]
                for evidence in evidence_items:
                    if evidence not in visual_evidence:
                        visual_evidence.append(evidence)
            merged.append(
                {
                    "event_id": cluster["event_id"],
                    "timestamp": seconds_to_timestamp(cluster["center_seconds"]),
                    "start": seconds_to_timestamp(cluster["start_seconds"]),
                    "end": seconds_to_timestamp(cluster["end_seconds"]),
                    "event_type": cluster["primary_event_type"],
                    "title": cluster["title"],
                    "confidence": round(cluster["confidence"], 3),
                    "detectors": sorted(set(detectors)),
                    "visual_evidence": visual_evidence[:8],
                    "supporting_events": supporting,
                }
            )
        return merged

    def _summarize(
        self,
        frame_index: list[dict[str, Any]],
        plan: list[dict[str, Any]],
        results: list[dict[str, Any]],
        events: list[dict[str, Any]],
        merged_events: list[dict[str, Any]],
    ) -> str:
        ok = sum(1 for r in results if r.get("ok"))
        failed = len(results) - ok
        usage_tokens = 0
        for result in results:
            usage = result.get("usage") or {}
            usage_tokens += int(usage.get("total_tokens") or 0)

        by_detector: dict[str, int] = {}
        by_batch_size: dict[str, int] = {}
        for event in events:
            by_detector[event.get("detector", "unknown")] = by_detector.get(event.get("detector", "unknown"), 0) + 1
            by_batch_size[str(event.get("batch_size"))] = by_batch_size.get(str(event.get("batch_size")), 0) + 1

        lines = [
            "# Visual Spotting Report",
            "",
            f"- Extracted frames: {len(frame_index)}",
            f"- Planned API requests: {len(plan)}",
            f"- Completed requests: {ok}",
            f"- Failed/parse-error requests: {failed}",
            f"- Total returned events: {len(events)}",
            f"- Merged events: {len(merged_events)}",
            f"- Approx total API tokens reported: {usage_tokens}",
            f"- Concurrency: {self.options.concurrency}",
            f"- RPM limit: {self.options.rpm_limit}",
            "",
            "## Events by Detector",
            "",
        ]
        for name, count in sorted(by_detector.items()):
            lines.append(f"- {name}: {count}")
        lines.extend(["", "## Events by Batch Size", ""])
        for name, count in sorted(by_batch_size.items(), key=lambda x: int(x[0])):
            lines.append(f"- {name}: {count}")
        lines.extend(["", "## Merged Events", ""])
        if merged_events:
            lines.extend(["| 时间 | 类型 | 置信度 | 标题 |", "|---|---|---:|---|"])
            for event in merged_events[:80]:
                lines.append(
                    f"| {event.get('timestamp')} | {event.get('event_type')} | {event.get('confidence')} | {event.get('title')} |"
                )
        else:
            lines.append("No merged events.")
        lines.extend(["", "## Output Files", "", "- frame_index_2s.json", "- spotting_plan.json", "- batch_results.json", "- visual_events.json", "- merged_events.json", "- raw_batches/"])
        return "\n".join(lines)


def _strip_internal(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if not k.startswith("_")}


def _event_title(event: dict[str, Any]) -> str:
    event_type = event.get("event_type") or event.get("detector") or "event"
    timestamp = event.get("timestamp", "")
    return f"{timestamp} {event_type}"
