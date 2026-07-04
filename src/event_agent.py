from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import load_intern_config
from .intern_client import InternClient
from .io_utils import (
    ensure_dir,
    extract_json_object,
    image_to_data_url,
    read_json,
    seconds_to_timestamp,
    timestamp_to_seconds,
    write_json,
    write_text,
)


EVENT_TYPES_V2 = [
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
]

EVENT_TYPES_V3 = [
    "goal",
    "penalty",
    "shot_chance",
    "corner",
    "free_kick",
    "foul_card_dispute",
    "offside",
    "substitution",
    "celebration",
    "half_full_time",
]

EVENT_TYPES = EVENT_TYPES_V2


@dataclass
class EventAgentOptions:
    descriptions_path: Path
    frame_index_path: Path
    out_dir: Path
    chunk_segments: int = 12
    concurrency: int = 3
    rpm_limit: float | None = 12.0
    temperature: float = 0.1
    text_max_tokens: int = 10000
    review_window_seconds: float = 8.0
    review_max_frames: int = 9
    max_chunks: int | None = None
    max_reviews: int | None = None
    final_max_events: int = 30
    final_consolidation_max_tokens: int | None = None
    schema_version: str = "v2"
    final_only: bool = False
    pure_model_output: bool = False
    resume: bool = False
    skip_image_review: bool = False
    no_model: bool = False


class EventAgentRunner:
    def __init__(self, options: EventAgentOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.raw_text_dir = ensure_dir(self.out_dir / "raw_text_chunks")
        self.raw_review_dir = ensure_dir(self.out_dir / "raw_image_reviews")
        self.client = InternClient(load_intern_config(), timeout=300)

    def run(self) -> Path:
        if self.options.final_only:
            return self._run_final_only()

        descriptions = read_json(self.options.descriptions_path)
        frames = read_json(self.options.frame_index_path)
        chunks = self._build_chunks(descriptions)
        if self.options.max_chunks:
            chunks = chunks[: self.options.max_chunks]
        write_json(self.out_dir / "text_chunk_plan.json", chunks)

        if self.options.no_model:
            write_json(self.out_dir / "text_agent_events.json", [])
            write_json(self.out_dir / "image_review_results.json", [])
            write_json(self.out_dir / "final_events.json", {"final_events": []})
            if self.options.schema_version == "v3":
                write_json(self.out_dir / "final_events_clean_v3.json", {"final_events": [], "match_time_anchors": []})
                write_json(self.out_dir / "match_time_anchors.json", [])
            write_text(self.out_dir / "event_agent_report.md", "# Event Agent Report\n")
            return self.out_dir

        text_results = self._run_text_agent(chunks)
        write_json(self.out_dir / "text_agent_results.json", text_results)
        text_events = self._collect_text_events(text_results)
        write_json(self.out_dir / "text_agent_events.json", text_events)

        review_results: list[dict[str, Any]] = []
        if not self.options.skip_image_review:
            review_requests = [event for event in text_events if event.get("needs_image_review")]
            if self.options.max_reviews is not None:
                review_requests = review_requests[: self.options.max_reviews]
            write_json(self.out_dir / "image_review_requests.json", review_requests)
            review_results = self._run_image_reviews(review_requests, frames, text_events)
        else:
            write_json(self.out_dir / "image_review_requests.json", [])
        write_json(self.out_dir / "image_review_results.json", review_results)

        final = self._run_final_consolidation(text_events, review_results)
        write_json(self.out_dir / "final_events.json", final)
        if self.options.schema_version == "v3":
            write_json(self.out_dir / "final_events_clean_v3.json", final)
            write_json(self.out_dir / "match_time_anchors.json", final.get("match_time_anchors") or [])
        write_text(self.out_dir / "event_agent_report.md", self._build_report(text_results, text_events, review_results, final))
        write_json(self.out_dir / "event_agent_runtime_summary.json", self._runtime_summary(text_results, review_results, final))
        return self.out_dir

    def _run_final_only(self) -> Path:
        text_results_path = self.out_dir / "text_agent_results.json"
        text_events_path = self.out_dir / "text_agent_events.json"
        review_results_path = self.out_dir / "image_review_results.json"
        if not text_events_path.exists():
            raise FileNotFoundError(f"Cached text events not found: {text_events_path}")
        if not review_results_path.exists():
            raise FileNotFoundError(f"Cached image review results not found: {review_results_path}")

        text_results = read_json(text_results_path) if text_results_path.exists() else []
        text_events = read_json(text_events_path)
        review_results = read_json(review_results_path)
        final = self._run_final_consolidation(text_events, review_results)
        write_json(self.out_dir / "final_events.json", final)
        if self.options.schema_version == "v3":
            write_json(self.out_dir / "final_events_clean_v3.json", final)
            write_json(self.out_dir / "match_time_anchors.json", final.get("match_time_anchors") or [])
        write_text(self.out_dir / "event_agent_report.md", self._build_report(text_results, text_events, review_results, final))
        write_json(self.out_dir / "event_agent_runtime_summary.json", self._runtime_summary(text_results, review_results, final))
        return self.out_dir

    def _build_chunks(self, descriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for start in range(0, len(descriptions), self.options.chunk_segments):
            segments = descriptions[start : start + self.options.chunk_segments]
            if not segments:
                continue
            chunks.append(
                {
                    "chunk_id": f"C{len(chunks) + 1:04d}",
                    "start_segment": segments[0].get("segment_id"),
                    "end_segment": segments[-1].get("segment_id"),
                    "start": segments[0].get("start"),
                    "end": segments[-1].get("end"),
                    "segments": segments,
                    "text": "\n\n".join(self._format_segment(segment) for segment in segments),
                }
            )
        return chunks

    def _format_segment(self, segment: dict[str, Any]) -> str:
        lines = [
            f"SEGMENT {segment.get('segment_id')} {segment.get('start')} - {segment.get('end')}",
            f"SUMMARY: {segment.get('segment_summary') or ''}",
            "OBSERVATIONS:",
        ]
        observations = segment.get("observations") or []
        for obs in observations:
            if isinstance(obs, str):
                lines.append(f"- {obs}")
                continue
            if not isinstance(obs, dict):
                continue
            possible = ", ".join(str(item) for item in (obs.get("possible_events") or []))
            lines.append(
                "- "
                f"t={obs.get('timestamp')} "
                f"frame={obs.get('frame_index')} "
                f"scene={obs.get('scene_type')} "
                f"score={obs.get('scoreboard')} "
                f"text={obs.get('visible_text')} "
                f"possible=[{possible}] "
                f"conf={obs.get('confidence')} "
                f"desc={obs.get('description')}"
            )
        candidates = segment.get("event_candidates") or []
        if candidates:
            lines.append("NARRATION_STAGE_CANDIDATES:")
            for cand in candidates:
                if not isinstance(cand, dict):
                    continue
                evidence = cand.get("evidence")
                lines.append(
                    "- "
                    f"t={cand.get('timestamp')} "
                    f"type={cand.get('event_type')} "
                    f"conf={cand.get('confidence')} "
                    f"needs_image_review={cand.get('needs_image_review')} "
                    f"evidence={evidence}"
                )
        return "\n".join(lines)

    def _run_text_agent(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._run_parallel(
            chunks,
            self.raw_text_dir,
            self._run_one_text_chunk,
            "chunk_id",
            {
                "stage": "text_agent",
                "prompt_version": self._text_prompt_version(),
                "max_tokens": self.options.text_max_tokens,
                "temperature": self.options.temperature,
            },
        )

    def _run_one_text_chunk(self, chunk: dict[str, Any], raw_path: Path, request_fingerprint: str) -> dict[str, Any]:
        if self.options.schema_version == "v3":
            system_prompt = (
                "你是世界杯视频解说 Harness 的 V3 事项定位 Agent。你只能基于上一阶段视觉观察员写出的文本判断，"
                "按固定 10 类事项输出，不能编造画面没有给出的事实。只输出 JSON。"
            )
        else:
            system_prompt = (
                "你是世界杯视频解说 Harness 的事件定位 Agent。你只能基于上一阶段视觉观察员写出的文本判断，"
                "不要用关键词硬匹配，不要编造画面没有给出的事实。只输出 JSON。"
            )
        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {"role": "user", "content": self._build_text_agent_prompt(chunk)},
        ]
        started = time.time()
        response = None
        parsed = None
        parse_error = None
        finish_reason = None
        for attempt in range(3):
            response = self.client.chat(
                messages,
                temperature=self.options.temperature,
                max_tokens=self.options.text_max_tokens,
                thinking_mode=False,
            )
            parsed, parse_error = _parse_response(response.content)
            finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
            validation_error = self._validate_text_agent_parsed(parsed)
            if parse_error is None and validation_error is None and finish_reason != "length":
                break
            parse_error = parse_error or validation_error
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        assert response is not None
        result = {
            "chunk_id": chunk["chunk_id"],
            "start": chunk["start"],
            "end": chunk["end"],
            "ok": parse_error is None and finish_reason != "length",
            "request_fingerprint": request_fingerprint,
            "request_max_tokens": self.options.text_max_tokens,
            "prompt_version": self._text_prompt_version(),
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
        }
        write_json(raw_path, result)
        return result

    def _validate_text_agent_parsed(self, parsed: Any) -> str | None:
        if not isinstance(parsed, dict):
            return "text agent response is not a JSON object"
        events = parsed.get("events")
        if not isinstance(events, list):
            return "text agent response missing events array"
        return None

    def _text_prompt_version(self) -> str:
        return "v3_fixed_event_set" if self.options.schema_version == "v3" else "v2_more_events"

    def _build_text_agent_prompt(self, chunk: dict[str, Any]) -> str:
        if self.options.schema_version == "v3":
            return self._build_text_agent_prompt_v3(chunk)
        return self._build_text_agent_prompt_v2(chunk)

    def _build_text_agent_prompt_v2(self, chunk: dict[str, Any]) -> str:
        return f"""你将读取一段已经由视觉大模型转写出来的足球比赛观察文本。
现在你的任务不是再看图，而是作为事件定位 Agent，判断这些观察文本中哪些位置对应目标事件。

目标事件类型只能是：
{", ".join(EVENT_TYPES)}

事件定义：
1. goal_or_celebration：进球发生、比分变化、进球后庆祝。新进球必须有比分增加、明确“比分更新/扩大优势”的文本，或清楚的 live play 进球上下文；如果同一比分下反复出现球入网、庆祝或进球者字幕，优先判断为同一进球的 replay/celebration，不要写成“再入一球”。
2. replay：慢动作、多角度重放、同一动作事后复现。普通镜头切换不是 replay。
3. corner：角旗区、角球开出、禁区内多人等待争顶等明确角球语境。
4. free_kick：静止球、人墙、主罚球员助跑、裁判指挥距离等任意球语境。
5. penalty：点球点、主罚球员单独面对门将、其他球员在禁区外。
6. substitution：换人牌、换人字幕、球员在边线完成上下场交接。只看见教练或替补席不算。
7. card_scene：裁判出牌或纪律处罚场景；看不清牌色时保持 card_scene。
8. referee_dispute：多名球员围裁判、明显抗议、VAR 或裁判解释争议。
9. attack_highlight：门前高强度进攻、射门、扑救、封堵、禁区混战，但无法确认进球。
10. halftime/fulltime：半场或全场结束，球员退场、比分总结、握手等。

判断规则：
1. 你要读前后文，不要只因为某个 observation 的 possible_events 里有某个词就输出事件。
2. 如果文本已经足够明确，needs_image_review=false。
3. 如果文本含糊、前后冲突、或事件很关键但缺少直接证据，则 needs_image_review=true，并写清楚希望回看的时间点和理由。
4. 对进球、点球、红黄牌、换人这类高价值且可能影响脚本的事件，如果只有单条模糊描述，优先要求回看图片。
5. 同一事件在连续观察里重复出现，只输出一个事件；回放可以作为 replay 单独输出，但要说明它对应哪个主事件。
6. 新进球判定硬门槛：如果观察文本里的比分牌没有变化，例如前后都是 1-0，即使又看到“球入网”，也必须优先判为 replay 或同一进球庆祝，不能判为新的 goal_or_celebration。
7. 不要编造球员姓名；只有观察文本里明确写出才可以使用。
8. 没有事件就返回空 events。
9. 只输出严格 JSON，不要 Markdown，不要 Thinking Process。

当前 chunk：
- chunk_id: {chunk["chunk_id"]}
- time_range: {chunk["start"]} - {chunk["end"]}
- segment_range: {chunk["start_segment"]} - {chunk["end_segment"]}

观察文本：
{chunk["text"]}

输出格式：
{{
  "chunk_id": "{chunk["chunk_id"]}",
  "events": [
    {{
      "timestamp": "00:00:00",
      "start": "00:00:00",
      "end": "00:00:00",
      "event_type": "goal_or_celebration|replay|corner|free_kick|penalty|substitution|card_scene|referee_dispute|attack_highlight|halftime|fulltime",
      "title": "一句话标题",
      "confidence": 0.0,
      "certainty": "confirmed|probable|uncertain",
      "commentary_value": "high|medium|low",
      "needs_image_review": true,
      "image_review_reason": "为什么需要或不需要回看图片",
      "review_timestamp": "00:00:00",
      "source_segments": ["S0001"],
      "text_evidence": ["引用观察文本中的证据，不要编造"],
      "script_hint": "如果写解说，可怎么讲"
    }}
  ],
  "notes": "整体判断备注"
}}"""

    def _build_text_agent_prompt_v3(self, chunk: dict[str, Any]) -> str:
        return f"""你将看到连续约 12 分钟的足球比赛视觉 narrative。你的任务是基于 narrative 做 V3 事项定位。

本场比赛固定信息：
- 比赛双方固定为：德国 vs 库拉索。
- CURAÇAO、CURACAO、Curaçao、库拉索都指库拉索。
- 禁止输出哥伦比亚、委内瑞拉、美国、巴拉圭等非本场球队名。
- V3 不追踪球员身份、姓名、号码和场上位置。不要输出人名、球衣号码、前锋/后卫/门将/队长等身份标签。
- 最多写到球队层级，例如“德国队球员”“库拉索球员”；换人也只记录某队出现换人，不记录上下场球员姓名。

V3 只允许输出这 10 类事项：
{", ".join(EVENT_TYPES_V3)}

事项定义：
1. goal：明确出现进球、破门、比分变化、进球庆祝或 narrative 明确描述进球。比分牌可作证据，但不是唯一硬条件。
2. penalty：点球判罚、点球主罚、点球射入或射失。点球进球可和 goal 关联，不能写成两个独立进球。
3. shot_chance：有解说价值的射门、门将扑救、明显威胁球。普通推进和普通传中不记。
4. corner：明确角球判罚、角球准备或角球开出。
5. free_kick：明确任意球判罚、定位球准备或任意球开出。
6. foul_card_dispute：明确犯规、黄牌、红牌、裁判介入、球员抗议或判罚争议。
7. offside：画面、字幕或 narrative 明确提到越位。
8. substitution：换人牌、换人字幕或 narrative 明确换人；只记录哪队换人，不记录上下场球员姓名。
9. celebration：进球后或重大节点后的庆祝。能关联主事件时必须写 linked_event_hint，不能当成新进球。
10. half_full_time：半场结束、全场结束、哨响、退场、比分牌确认等。

判断规则：
1. 不要输出 replay、attack_highlight、dead_ball、crowd 等 V2/泛化类型。回放、字幕、比分牌、庆祝、裁判手势只能作为 evidence。
2. 不要因为缺少某一种证据就否定明显事项；如果明显但细节不完整，可输出 probable 或 uncertain。
3. 同一事项在 narrative 中多次出现时合并为一条，保留最接近实际发生的 video_timestamp。
4. 如果事件关键但 narrative 含糊、前后冲突、或时间点不稳，needs_image_review=true，review_timestamp 使用最需要回看的视频时间。
5. 如果 narrative 已经足够明确，可 needs_image_review=false。
6. 每条事项必须同时给出 video_timestamp 和 match_time。match_time 优先用比分牌/字幕/narrative 中的比赛分钟；没有明确比赛时间时可以估算，并标注 match_time_source=estimated。
7. 不要把视频时间 01:42:08 直接写成第 102 分钟；比赛时间必须按上/下半场语境估算。
8. 不要从 narrative 中继承球员姓名、号码、位置或身份；如果原文出现这些内容，输出时降级成球队层级。
9. 只输出严格 JSON，不要 Markdown，不要 Thinking Process。

当前 chunk：
- chunk_id: {chunk["chunk_id"]}
- video_time_range: {chunk["start"]} - {chunk["end"]}
- segment_range: {chunk["start_segment"]} - {chunk["end_segment"]}

观察文本：
{chunk["text"]}

输出格式：
{{
  "chunk_id": "{chunk["chunk_id"]}",
  "events": [
    {{
      "video_timestamp": "00:00:00",
      "review_timestamp": "00:00:00",
      "match_time": "6'",
      "period": "pre_match|first_half|halftime|second_half|fulltime|unknown",
      "match_minute": 6,
      "stoppage_minute": 0,
      "match_time_source": "scoreboard|subtitle|narrative|estimated|unknown",
      "event_type": "goal|penalty|shot_chance|corner|free_kick|foul_card_dispute|offside|substitution|celebration|half_full_time",
      "title": "一句话标题",
      "confidence": 0.0,
      "certainty": "confirmed|probable|uncertain",
      "evidence_level": "direct_visual|text_clear|text_probable|weak",
      "needs_image_review": true,
      "image_review_reason": "为什么需要或不需要回看图片",
      "source_segments": ["S0001"],
      "evidence": ["引用 narrative 中的证据，不要编造"],
      "linked_event_hint": "如果是庆祝、点球进球或回放证据，说明关联哪个主事项；否则为空",
      "commentary_hint": "如果写解说，可怎么讲"
    }}
  ],
  "match_time_anchors": [
    {{
      "video_timestamp": "00:09:30",
      "match_time": "1'",
      "period": "first_half",
      "source": "scoreboard|subtitle|narrative|estimated"
    }}
  ],
  "notes": "整体判断备注"
}}"""

    def _collect_text_events(self, text_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for result in text_results:
            parsed = result.get("parsed")
            if isinstance(parsed, dict):
                parsed_events = parsed.get("events") or []
            elif isinstance(parsed, list):
                parsed_events = parsed
            else:
                parsed_events = []
            for event in parsed_events:
                if not isinstance(event, dict):
                    continue
                item = {
                    "event_id": f"T{len(events) + 1:04d}",
                    "chunk_id": result.get("chunk_id"),
                    "source": "narration_text_agent",
                    **event,
                }
                if self.options.schema_version == "v3":
                    video_timestamp = item.get("video_timestamp") or item.get("timestamp") or item.get("review_timestamp")
                    item["video_timestamp"] = video_timestamp
                    item["timestamp"] = video_timestamp
                    item["review_timestamp"] = item.get("review_timestamp") or video_timestamp
                    if "text_evidence" not in item and "evidence" in item:
                        item["text_evidence"] = item.get("evidence")
                    if "script_hint" not in item and "commentary_hint" in item:
                        item["script_hint"] = item.get("commentary_hint")
                item["timestamp_seconds"] = timestamp_to_seconds(
                    item.get("video_timestamp") or item.get("timestamp") or item.get("review_timestamp")
                )
                events.append(item)
        events.sort(key=lambda item: (float(item.get("timestamp_seconds") or 0.0), str(item.get("event_type", ""))))
        for idx, event in enumerate(events, start=1):
            event["event_id"] = f"T{idx:04d}"
        return events

    def _run_image_reviews(
        self,
        requests: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        all_text_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        review_items = []
        for event in requests:
            selected_frames = self._select_frames_for_review(event, frames)
            review_items.append(
                {
                    "event": event,
                    "frames": selected_frames,
                    "review_id": event["event_id"],
                    "nearby_events": self._nearby_events(event, all_text_events),
                }
            )
        return self._run_parallel(
            review_items,
            self.raw_review_dir,
            self._run_one_image_review,
            "review_id",
            {
                "stage": "image_review",
                "prompt_version": "v3" if self.options.schema_version == "v3" else "v1",
                "max_tokens": 2600,
                "temperature": self.options.temperature,
                "review_window_seconds": self.options.review_window_seconds,
                "review_max_frames": self.options.review_max_frames,
            },
        )

    def _nearby_events(self, event: dict[str, Any], all_text_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ts = timestamp_to_seconds(event.get("review_timestamp") or event.get("timestamp"))
        nearby: list[dict[str, Any]] = []
        for other in all_text_events:
            other_ts = timestamp_to_seconds(other.get("timestamp") or other.get("review_timestamp"))
            if abs(other_ts - ts) > 240:
                continue
            nearby.append(
                {
                    "event_id": other.get("event_id"),
                    "timestamp": other.get("timestamp"),
                    "event_type": other.get("event_type"),
                    "title": other.get("title"),
                    "confidence": other.get("confidence"),
                    "needs_image_review": other.get("needs_image_review"),
                    "text_evidence": other.get("text_evidence"),
                }
            )
        nearby.sort(key=lambda item: timestamp_to_seconds(item.get("timestamp")))
        return nearby[:12]

    def _select_frames_for_review(self, event: dict[str, Any], frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ts = timestamp_to_seconds(event.get("review_timestamp") or event.get("timestamp"))
        start = max(0.0, ts - self.options.review_window_seconds)
        end = ts + self.options.review_window_seconds
        selected = [
            frame
            for frame in frames
            if start <= float(frame.get("timestamp_seconds") or timestamp_to_seconds(frame.get("timestamp"))) <= end
        ]
        if not selected and frames:
            selected = sorted(
                frames,
                key=lambda frame: abs(float(frame.get("timestamp_seconds") or timestamp_to_seconds(frame.get("timestamp"))) - ts),
            )[: self.options.review_max_frames]
        if len(selected) > self.options.review_max_frames:
            selected = _downsample(selected, self.options.review_max_frames)
        return selected

    def _run_one_image_review(self, item: dict[str, Any], raw_path: Path, request_fingerprint: str) -> dict[str, Any]:
        event = item["event"]
        frames = item["frames"]
        content: list[dict[str, Any]] = [
            {"type": "text", "text": self._build_image_review_prompt(event, frames, item.get("nearby_events") or [])}
        ]
        for frame in frames:
            content.append(
                {
                    "type": "text",
                    "text": f"FRAME {frame.get('frame_index')} | timestamp={frame.get('timestamp')} | motion_score={frame.get('motion_score')}",
                }
            )
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(Path(frame["path"]))}})
        messages = [
            {
                "role": "system",
                "content": (
                    "你是足球事件证据复核 Agent。你会看到候选事件及其附近帧。"
                    "请只根据图片和给定候选文本复核，不能编造。只输出 JSON。"
                ),
            },
            {"role": "user", "content": content},
        ]
        started = time.time()
        response = self.client.chat(
            messages,
            temperature=self.options.temperature,
            max_tokens=2600,
            thinking_mode=False,
        )
        parsed, parse_error = _parse_response(response.content)
        finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
        result = {
            "review_id": item["review_id"],
            "event_id": event["event_id"],
            "ok": parse_error is None and finish_reason != "length",
            "request_fingerprint": request_fingerprint,
            "request_max_tokens": 2600,
            "prompt_version": "v3" if self.options.schema_version == "v3" else "v1",
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "frames": [
                {
                    "frame_index": frame.get("frame_index"),
                    "timestamp": frame.get("timestamp"),
                    "path": frame.get("path"),
                }
                for frame in frames
            ],
            "original_event": event,
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
        }
        write_json(raw_path, result)
        return result

    def _build_image_review_prompt(
        self,
        event: dict[str, Any],
        frames: list[dict[str, Any]],
        nearby_events: list[dict[str, Any]],
    ) -> str:
        frame_table = "\n".join(
            f"- FRAME {frame.get('frame_index')}: {frame.get('timestamp')}"
            for frame in frames
        )
        if self.options.schema_version == "v3":
            return f"""你需要复核一个由 V3 文本事项定位 Agent 提出的候选事项。

候选事项：
{json.dumps(event, ensure_ascii=False, indent=2)}

同一时间附近的其他候选事项（用于避免把同一进球的庆祝/回放证据误判成新进球）：
{json.dumps(nearby_events, ensure_ascii=False, indent=2)}

可查看帧：
{frame_table}

复核任务：
1. 判断候选事项是否被这些帧支持。图片是补证据，不是唯一裁判。
2. 如果图片明确支持事项，verdict=confirmed 或 probable。
3. 如果图片没有看到但 narrative 明确，不要轻易 rejected，优先 verdict=not_visible_in_window 或 uncertain。
4. 只有图片和 narrative 明确冲突时，才 verdict=rejected。
5. 如果事件类型或视频时间戳需要修正，请给出 corrected_video_timestamp 和 event_type。
6. V3 只允许 event_type 属于：{", ".join(EVENT_TYPES_V3)}。
7. 不要输出 replay、attack_highlight、dead_ball、crowd 等 V2/泛化类型；回放只能写入 visual_evidence 或 notes。
8. 不要识别、保留或输出球员姓名、球衣号码、前锋/后卫/门将/队长等身份标签，最多写“德国队球员”“库拉索球员”。
9. 只输出严格 JSON。

输出格式：
{{
  "event_id": "{event.get("event_id")}",
  "verdict": "confirmed|probable|uncertain|not_visible_in_window|rejected",
  "event_type": "{event.get("event_type")}",
  "confidence": 0.0,
  "visual_evidence": ["图片中实际看到的球队层级证据"],
  "missing_evidence": ["未看到但需要说明的证据"],
  "corrected_video_timestamp": "{event.get("video_timestamp") or event.get("timestamp")}",
  "corrected_title": "如需修正，给出球队层级标题；否则沿用原标题",
  "notes": "复核备注，不含球员姓名、号码或位置身份",
  "keep_for_script": true
}}"""
        return f"""你需要复核一个由文本事件定位 Agent 提出的候选事件。

候选事件：
{json.dumps(event, ensure_ascii=False, indent=2)}

同一时间附近的其他候选事件（用于避免把同一进球的回放/庆祝误判成新进球）：
{json.dumps(nearby_events, ensure_ascii=False, indent=2)}

可查看帧：
{frame_table}

复核任务：
1. 判断候选事件是否被这些帧支持。
2. 如果事件类型或时间戳需要修正，请直接给出 corrected 的结果。
3. 如果图片无法支持该事件，verdict=rejected 或 uncertain。
4. 不要因为候选文本里写了就直接确认，必须看图片证据。
5. 复核新进球时必须看比分牌和上下文：如果附近已经有同比分进球，且当前帧比分没有增加，只能修正为 replay 或同一进球庆祝，不能确认成新的 goal_or_celebration。
6. 如果画面显示球入网但同时是慢动作/多角度/比分不变/进球者字幕复现，应优先 event_type=replay。
7. 只输出严格 JSON。

输出格式：
{{
  "event_id": "{event.get("event_id")}",
  "verdict": "confirmed|corrected|rejected|uncertain",
  "timestamp": "00:00:00",
  "event_type": "{event.get("event_type")}",
  "confidence": 0.0,
  "commentary_value": "high|medium|low",
  "visual_evidence": ["图片中实际看到的证据"],
  "corrected_title": "如需修正，给出标题；否则沿用原标题",
  "correction_notes": "修正或驳回原因",
  "keep_for_script": true
}}"""

    def _run_final_consolidation(self, text_events: list[dict[str, Any]], review_results: list[dict[str, Any]]) -> dict[str, Any]:
        review_pack = []
        for result in review_results:
            parsed = result.get("parsed")
            if isinstance(parsed, dict):
                if self.options.schema_version == "v3":
                    parsed = {
                        "event_id": parsed.get("event_id"),
                        "verdict": parsed.get("verdict"),
                        "event_type": parsed.get("event_type"),
                        "confidence": parsed.get("confidence"),
                        "visual_evidence": _trim_list(parsed.get("visual_evidence"), 2, 90),
                        "missing_evidence": _trim_list(parsed.get("missing_evidence"), 2, 90),
                        "corrected_video_timestamp": parsed.get("corrected_video_timestamp"),
                        "corrected_title": _shorten(parsed.get("corrected_title"), 60),
                        "notes": _shorten(parsed.get("notes") or parsed.get("correction_notes"), 120),
                        "keep_for_script": parsed.get("keep_for_script"),
                    }
                else:
                    parsed = {
                        "event_id": parsed.get("event_id"),
                        "verdict": parsed.get("verdict"),
                        "timestamp": parsed.get("timestamp"),
                        "event_type": parsed.get("event_type"),
                        "confidence": parsed.get("confidence"),
                        "commentary_value": parsed.get("commentary_value"),
                        "visual_evidence": _trim_list(parsed.get("visual_evidence"), 2, 90),
                        "corrected_title": _shorten(parsed.get("corrected_title"), 60),
                        "correction_notes": _shorten(parsed.get("correction_notes"), 120),
                        "keep_for_script": parsed.get("keep_for_script"),
                    }
            review_pack.append(
                {
                    "event_id": result.get("event_id"),
                    "ok": result.get("ok"),
                    "parsed": parsed,
                    "frames": [
                        {"frame_index": frame.get("frame_index"), "timestamp": frame.get("timestamp")}
                        for frame in result.get("frames", [])
                    ],
                    "parse_error": result.get("parse_error"),
                }
            )
        if self.options.schema_version == "v3":
            candidate_pack = [
                {
                    "event_id": event.get("event_id"),
                    "video_timestamp": event.get("video_timestamp") or event.get("timestamp"),
                    "review_timestamp": event.get("review_timestamp"),
                    "match_time": event.get("match_time"),
                    "period": event.get("period"),
                    "match_minute": event.get("match_minute"),
                    "stoppage_minute": event.get("stoppage_minute"),
                    "match_time_source": event.get("match_time_source"),
                    "event_type": event.get("event_type"),
                    "title": _shorten(event.get("title"), 70),
                    "confidence": event.get("confidence"),
                    "certainty": event.get("certainty"),
                    "evidence_level": event.get("evidence_level"),
                    "needs_image_review": event.get("needs_image_review"),
                    "source_segments": event.get("source_segments"),
                    "evidence": _trim_list(event.get("evidence") or event.get("text_evidence"), 3, 110),
                    "linked_event_hint": _shorten(event.get("linked_event_hint"), 80),
                    "commentary_hint": _shorten(event.get("commentary_hint") or event.get("script_hint"), 90),
                }
                for event in text_events
            ]
        else:
            candidate_pack = [
                {
                    "event_id": event.get("event_id"),
                    "timestamp": event.get("timestamp"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "event_type": event.get("event_type"),
                    "title": event.get("title"),
                    "confidence": event.get("confidence"),
                    "certainty": event.get("certainty"),
                    "commentary_value": event.get("commentary_value"),
                    "needs_image_review": event.get("needs_image_review"),
                    "source_segments": event.get("source_segments"),
                    "text_evidence": _trim_list(event.get("text_evidence"), 2, 120),
                    "script_hint": _shorten(event.get("script_hint"), 80),
                }
                for event in text_events
            ]
        system_content = (
            "你是世界杯解说脚本的 V3 事项清洗总编 Agent。你需要基于文本定位结果和图片复核结果，"
            "输出 final_events_clean_v3.json。不要输出球员姓名、号码、位置或身份。只输出 JSON。"
            if self.options.schema_version == "v3"
            else (
                "你是世界杯解说脚本的总编 Agent。你需要基于文本定位结果和图片复核结果，"
                "合并重复事件，剔除证据不足事件，输出最终关键事件时间线。只输出 JSON。"
            )
        )
        messages = [
            {
                "role": "system",
                "content": system_content,
            },
            {"role": "user", "content": self._build_final_prompt(candidate_pack, review_pack)},
        ]
        final_max_tokens = self.options.final_consolidation_max_tokens
        if final_max_tokens is None:
            final_max_tokens = 14000 if self.options.schema_version == "v3" else 9000
        started = time.time()
        response = self.client.chat(
            messages,
            temperature=self.options.temperature,
            max_tokens=final_max_tokens,
            thinking_mode=False,
        )
        parsed, parse_error = _parse_response(response.content)
        finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
        result = {
            "ok": parse_error is None and finish_reason != "length",
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "request_max_tokens": final_max_tokens,
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
        }
        write_json(self.out_dir / "final_consolidation_raw.json", result)
        if isinstance(parsed, dict):
            if self.options.schema_version == "v3" and not self.options.pure_model_output:
                parsed = _sanitize_v3_final(parsed, self.options.final_max_events)
            return parsed
        return {"final_events": [], "parse_error": parse_error, "raw": response.content}

    def _build_final_prompt(self, candidate_pack: list[dict[str, Any]], review_pack: list[dict[str, Any]]) -> str:
        if self.options.schema_version == "v3":
            return f"""下面是两部分证据：
1. V3 文本事项定位 Agent 从整场视觉观察文本中提出的候选事项。
2. 对其中 needs_image_review=true 的事项进行图片回看后的复核结果。

你的任务是生成 `final_events_clean_v3.json`：
1. 只保留 V3 的 10 类事项：{", ".join(EVENT_TYPES_V3)}。
2. 合并重复事项。庆祝、回放证据、同一进球的后续字幕必须挂到主事项，默认不要把 linked celebration 单列为 final_events。
3. 点球进球可以同时体现 penalty 和 goal，但必须用 linked_event_id 关联，不能写成两个独立进球。
4. 剔除被图片复核 rejected 的事项；not_visible_in_window 或 uncertain 可以保留，但 certainty 必须如实标注。
5. 不要新增没有候选依据的事项。
6. 每条事项必须有 video_timestamp、match_time、period、event_type、title、certainty、evidence。
7. match_time 用于展示；video_timestamp 用于切片。不能把视频时间直接当比赛分钟。
8. 彻底删除或降级所有球员姓名、球衣号码、前锋/后卫/门将/中场/队长/主罚手等位置或身份信息。最多写“德国队”“库拉索队”“德国队球员”“库拉索球员”。
9. 换人事项只写某队换人，不写上下场球员姓名。
10. evidence 和 script_angle 必须短，单项不超过 50 个中文字符。
11. 最多保留 {self.options.final_max_events} 条；低价值 celebration、低价值 substitution、重复定位球优先合并或剔除。
12. 只输出严格 JSON，不要解释，不要 Markdown，不要漂亮打印，尽量单行紧凑 JSON。

候选事项：
{json.dumps(candidate_pack, ensure_ascii=False, indent=2)}

图片复核结果：
{json.dumps(review_pack, ensure_ascii=False, indent=2)}

输出格式：
{{
  "final_events": [
    {{
      "event_id": "F0001",
      "video_timestamp": "00:00:00",
      "timestamp": "00:00:00",
      "match_time": "6'",
      "period": "first_half|halftime|second_half|fulltime|unknown",
      "match_minute": 6,
      "stoppage_minute": 0,
      "match_time_source": "scoreboard|subtitle|narrative|estimated|unknown",
      "event_type": "goal|penalty|shot_chance|corner|free_kick|foul_card_dispute|offside|substitution|celebration|half_full_time",
      "title": "球队层级标题",
      "certainty": "confirmed|probable|uncertain",
      "evidence_level": "direct_visual|text_clear|text_probable|weak",
      "confidence": 0.0,
      "importance": "high|medium|low",
      "source_event_ids": ["T0001"],
      "linked_event_id": "",
      "evidence": ["短证据，不含人名号码位置"],
      "needs_more_review": false,
      "script_angle": "短解说角度，不含人名号码位置"
    }}
  ],
  "match_time_anchors": [
    {{
      "video_timestamp": "00:09:30",
      "match_time": "1'",
      "period": "first_half",
      "source": "scoreboard|subtitle|narrative|estimated"
    }}
  ],
  "rejected_event_ids": ["T0000"],
  "quality_notes": ["对本轮清洗质量的备注"]
}}"""
        return f"""下面是两部分证据：
1. 文本事件定位 Agent 从整场视觉观察文本中提出的候选事件。
2. 对其中 needs_image_review=true 的事件进行图片回看后的复核结果。

你的任务：
1. 合并重复事件。进球发生、庆祝、同一进球回放如果属于同一个大事件，通常保留主事件；replay 只有在有明显解说价值时才作为独立事件保留。
2. 剔除被图片复核 rejected 的事件；uncertain 的事件只有在解说价值高且文本证据强时才保留，并标注 needs_more_review=true。
3. 新进球必须以比分增加或明确 live play 新进球为依据。若候选事件显示“又进球”但比分仍与前一个进球后相同，应改为 replay/celebration 或合并进前一个进球，不能保留为新进球。
4. 剔除明显队名/人名冲突的低可信内容，例如德国-库拉索比赛中突然出现其他国家队名，除非证据非常明确。
5. 不要新增没有候选依据的事件。
6. 输出给后续解说脚本使用的最终关键事件时间线，要求时间戳尽量准确。
7. 最终只保留最有解说价值的关键事件，最多 {self.options.final_max_events} 条。
8. 为避免 JSON 截断，所有 evidence 和 script_angle 必须短句，单项不超过 50 个中文字符。
9. 只输出严格 JSON，不要解释，不要 Markdown，不要漂亮打印，尽量单行紧凑 JSON。

候选事件：
{json.dumps(candidate_pack, ensure_ascii=False, indent=2)}

图片复核结果：
{json.dumps(review_pack, ensure_ascii=False, indent=2)}

输出格式：
{{
  "final_events": [
    {{
      "event_id": "F0001",
      "timestamp": "00:00:00",
      "start": "00:00:00",
      "end": "00:00:00",
      "event_type": "goal_or_celebration|replay|corner|free_kick|penalty|substitution|card_scene|referee_dispute|attack_highlight|halftime|fulltime",
      "title": "一句话标题",
      "confidence": 0.0,
      "importance": "high|medium|low",
      "source_event_ids": ["T0001"],
      "evidence": ["短证据"],
      "needs_more_review": false,
      "script_angle": "短解说角度"
    }}
  ],
  "rejected_event_ids": ["T0000"],
  "quality_notes": ["对本轮定位质量的备注"]
}}"""

    def _run_parallel(
        self,
        items: list[dict[str, Any]],
        raw_dir: Path,
        worker: Callable[[dict[str, Any], Path, str], dict[str, Any]],
        id_key: str,
        fingerprint_extra: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        min_submit_interval = 60.0 / self.options.rpm_limit if self.options.rpm_limit else 0.0
        last_submit = 0.0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.options.concurrency) as executor:
            future_map = {}
            for item in items:
                item_id = str(item[id_key])
                raw_path = raw_dir / f"{item_id}.json"
                request_fingerprint = self._request_fingerprint(item, fingerprint_extra)
                if self.options.resume and raw_path.exists():
                    cached = read_json(raw_path)
                    if self._can_reuse_cached_result(cached, request_fingerprint):
                        results.append(cached)
                        continue
                if min_submit_interval > 0 and last_submit > 0:
                    wait = min_submit_interval - (time.time() - last_submit)
                    if wait > 0:
                        time.sleep(wait)
                future = executor.submit(worker, item, raw_path, request_fingerprint)
                future_map[future] = (item, raw_path)
                last_submit = time.time()

            for future in concurrent.futures.as_completed(future_map):
                item, raw_path = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    result = {
                        id_key: item.get(id_key),
                        "ok": False,
                        "request_fingerprint": self._request_fingerprint(item, fingerprint_extra),
                        "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                    }
                    write_json(raw_path, result)
                    results.append(result)
        results.sort(key=lambda item: str(item.get(id_key) or item.get("event_id") or ""))
        return results

    @staticmethod
    def _request_fingerprint(item: dict[str, Any], extra: dict[str, Any]) -> str:
        payload = {"item": item, "extra": extra}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _can_reuse_cached_result(cached: dict[str, Any], request_fingerprint: str) -> bool:
        if not cached.get("ok"):
            return False
        if cached.get("finish_reason") == "length":
            return False
        if cached.get("prompt_version") == "v3_fixed_event_set":
            parsed = cached.get("parsed")
            if not isinstance(parsed, dict) or not isinstance(parsed.get("events"), list):
                return False
        return cached.get("request_fingerprint") == request_fingerprint

    def _build_report(
        self,
        text_results: list[dict[str, Any]],
        text_events: list[dict[str, Any]],
        review_results: list[dict[str, Any]],
        final: dict[str, Any],
    ) -> str:
        final_events = final.get("final_events") if isinstance(final, dict) else []
        lines = [
            "# Event Agent Report",
            "",
            "## Run Summary",
            "",
            f"- Text chunks: {len(text_results)}",
            f"- Text chunk success: {sum(1 for item in text_results if item.get('ok'))}",
            f"- Text candidate events: {len(text_events)}",
            f"- Image review calls: {len(review_results)}",
            f"- Image review success: {sum(1 for item in review_results if item.get('ok'))}",
            f"- Final events: {len(final_events or [])}",
            "",
            "## Final Events",
            "",
        ]
        if final_events:
            lines.append("| Time | Type | Confidence | Importance | Title |")
            lines.append("|---|---|---:|---|---|")
            for event in final_events:
                lines.append(
                    f"| {event.get('timestamp')} | {event.get('event_type')} | {event.get('confidence')} | "
                    f"{event.get('importance')} | {event.get('title')} |"
                )
        else:
            lines.append("No final events.")
        lines.extend(
            [
                "",
                "## Output Files",
                "",
                "- text_chunk_plan.json",
                "- text_agent_results.json",
                "- text_agent_events.json",
                "- image_review_requests.json",
                "- image_review_results.json",
                "- final_consolidation_raw.json",
                "- final_events.json",
                "- raw_text_chunks/",
                "- raw_image_reviews/",
            ]
        )
        return "\n".join(lines)

    def _runtime_summary(
        self,
        text_results: list[dict[str, Any]],
        review_results: list[dict[str, Any]],
        final: dict[str, Any],
    ) -> dict[str, Any]:
        final_usage = {}
        final_raw = self.out_dir / "final_consolidation_raw.json"
        if final_raw.exists():
            final_usage = (read_json(final_raw).get("usage") or {})
        all_usages = [(item.get("usage") or {}) for item in [*text_results, *review_results]]
        all_usages.append(final_usage)
        return {
            "text_chunks": len(text_results),
            "text_success": sum(1 for item in text_results if item.get("ok")),
            "text_candidate_events": sum(
                len((item.get("parsed") or {}).get("events") or [])
                for item in text_results
                if isinstance(item.get("parsed"), dict)
            ),
            "image_review_calls": len(review_results),
            "image_review_success": sum(1 for item in review_results if item.get("ok")),
            "final_events": len(final.get("final_events") or []) if isinstance(final, dict) else 0,
            "prompt_tokens": sum(int(usage.get("prompt_tokens") or 0) for usage in all_usages),
            "completion_tokens": sum(int(usage.get("completion_tokens") or 0) for usage in all_usages),
            "total_tokens": sum(int(usage.get("total_tokens") or 0) for usage in all_usages),
            "concurrency": self.options.concurrency,
            "rpm_limit": self.options.rpm_limit,
        }


def _parse_response(content: str) -> tuple[Any, str | None]:
    try:
        return extract_json_object(content), None
    except Exception as exc:
        return None, str(exc)


def _downsample(items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    if len(items) <= max_items:
        return items
    if max_items <= 1:
        return [items[0]]
    step = (len(items) - 1) / (max_items - 1)
    return [items[round(idx * step)] for idx in range(max_items)]


def _sanitize_v3_final(final_doc: dict[str, Any], max_events: int | None = None) -> dict[str, Any]:
    allowed_types = set(EVENT_TYPES_V3)
    sanitized_events: list[dict[str, Any]] = []
    for event in final_doc.get("final_events") or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        if event_type not in allowed_types:
            continue
        if event_type == "celebration" and event.get("linked_event_id"):
            continue

        cleaned = dict(event)
        for key in ("title", "script_angle", "match_time", "period", "match_time_source", "evidence_level", "certainty"):
            if key in cleaned:
                cleaned[key] = _sanitize_identity_text(cleaned.get(key))

        evidence = cleaned.get("evidence")
        if isinstance(evidence, list):
            cleaned["evidence"] = [_sanitize_identity_text(item) for item in evidence[:3] if str(item).strip()]
        elif evidence:
            cleaned["evidence"] = [_sanitize_identity_text(evidence)]
        else:
            cleaned["evidence"] = ["候选事项和复核结果提供证据"]

        video_timestamp = cleaned.get("video_timestamp") or cleaned.get("timestamp") or cleaned.get("start")
        cleaned["video_timestamp"] = video_timestamp
        cleaned["timestamp"] = video_timestamp
        sanitized_events.append(cleaned)

    if max_events is not None and max_events > 0:
        sanitized_events = sanitized_events[:max_events]

    for index, event in enumerate(sanitized_events, start=1):
        event["event_id"] = f"F{index:04d}"

    final_doc = dict(final_doc)
    final_doc["final_events"] = sanitized_events
    notes = final_doc.get("quality_notes")
    if isinstance(notes, list):
        final_doc["quality_notes"] = [_sanitize_identity_text(item) for item in notes]
    return final_doc


def _sanitize_identity_text(value: Any) -> str:
    text = "" if value is None else str(value)
    player_names = [
        "穆西亚拉",
        "诺伊尔",
        "哈弗茨",
        "基米希",
        "维尔茨",
        "萨内",
        "吕迪格",
        "施洛特贝克",
        "帕夫洛维奇",
        "巴库纳",
        "洛卡迪亚",
        "方维尔",
        "奥比斯波",
        "巴佐尔",
        "弗洛拉努斯",
        "罗姆",
        "科门西亚",
        "阿德沃卡特",
    ]
    for name in player_names:
        text = text.replace(name, "球员")
    replacements = {
        "守门员": "防守方球员",
        "门将": "防守方球员",
        "前锋": "球员",
        "后卫": "球员",
        "中场": "球员",
        "队长": "球员",
        "主罚手": "球员",
        "主罚球员": "球员",
        "射手": "球员",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\d{1,2}\s*号(?:球员)?", "球员", text)
    text = re.sub(r"换下\s*球员\s*[，,]\s*换上\s*球员", "完成换人", text)
    text = re.sub(r"\(\s*\d{1,2}\s*\)", "", text)
    text = re.sub(r"\b[A-Z][a-zÀ-ÿ'’.-]+(?:\s+[A-Z][a-zÀ-ÿ'’.-]+)+\b", "球员", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _shorten(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _trim_list(value: Any, max_items: int, item_limit: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = [str(value)]
    return [_shorten(item, item_limit) for item in items[:max_items]]
