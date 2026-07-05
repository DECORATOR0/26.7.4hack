from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_intern_config
from .event_agent import EVENT_TYPES_V3
from .intern_client import InternClient
from .io_utils import ensure_dir, extract_json_object, read_json, write_json, write_text


IDENTITY_FIELDS = {
    "title",
    "evidence",
    "script_angle",
    "commentary_hint",
    "image_review_reason",
    "quality_notes",
}


@dataclass
class GuardrailOptions:
    events_path: Path
    out_dir: Path
    temperature: float = 0.0
    max_tokens: int = 6000
    no_model: bool = False


class V4GuardrailRunner:
    def __init__(self, options: GuardrailOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.client = InternClient(load_intern_config(), timeout=300)

    def run(self) -> Path:
        started = time.time()
        source_doc = read_json(self.options.events_path)
        events = _extract_events(source_doc)

        agent_result = None
        if not self.options.no_model and self.client.enabled():
            agent_result = self._run_guardrail_agent(source_doc, events)

        guarded_events, local_findings, local_patches = _apply_local_guardrail(events)
        guarded_doc = dict(source_doc) if isinstance(source_doc, dict) else {"source_events": source_doc}
        guarded_doc["final_events"] = guarded_events
        guarded_doc["guardrail_summary"] = {
            "version": "v4",
            "policy": "single_pass_identity_and_event_type_cleanup",
            "source_events": len(events),
            "guarded_events": len(guarded_events),
            "dropped_events": len(events) - len(guarded_events),
            "findings": len(local_findings),
            "elapsed_seconds": round(time.time() - started, 3),
        }

        write_json(self.out_dir / "final_events_guarded_v4.json", guarded_doc)
        write_json(self.out_dir / "guardrail_findings.json", {"findings": local_findings})
        write_json(self.out_dir / "guardrail_patches.json", {"patches": local_patches})
        write_json(
            self.out_dir / "guardrail_raw.json",
            {
                "agent_result": agent_result,
                "local_policy": guarded_doc["guardrail_summary"],
            },
        )
        write_text(self.out_dir / "guardrail_report.md", _build_guardrail_report(guarded_doc, local_findings))
        return self.out_dir

    def _run_guardrail_agent(self, source_doc: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = f"""你是 V4 guardrail agent。请一次性审查 final_events，不要返工，不要读取上游，不要处理比分链。

只检查三类问题：
1. 人名、号码、身份污染：球员姓名、球衣号码、前锋/后卫/门将/队长/主罚手等身份。
2. 非法 event_type：不在允许集合内的 final event。
3. 明显需要清洗的字段：title、evidence、script_angle。

允许的 event_type：
{", ".join(EVENT_TYPES_V3)}

输出严格 JSON，只包含 findings 和 patches。patches 只允许：
- replace_text：替换某个文本字段。
- drop_event：删除非法 event_type 的事项。

final_events：
{json.dumps({"final_events": events}, ensure_ascii=False, separators=(",", ":"))}

输出格式：
{{
  "findings": [
    {{
      "rule_id": "identity_contamination|illegal_event_type",
      "event_id": "F0001",
      "field": "title",
      "original_value": "原文",
      "reason": "原因",
      "action": "replace_text|drop_event"
    }}
  ],
  "patches": [
    {{
      "op": "replace_text|drop_event",
      "event_id": "F0001",
      "field": "title",
      "value": "替换后的文本",
      "reason": "原因"
    }}
  ]
}}"""
        started = time.time()
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": "你是严格的 JSON guardrail。只输出 JSON，不输出解释，不处理比分链。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=self.options.temperature,
            max_tokens=self.options.max_tokens,
            thinking_mode=False,
        )
        finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
        parsed = None
        parse_error = None
        try:
            parsed = extract_json_object(response.content, required_keys=("findings", "patches"))
        except Exception as exc:
            parse_error = str(exc)
        return {
            "ok": parse_error is None and finish_reason != "length",
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "parsed": parsed,
            "parse_error": parse_error,
            "content": response.content,
        }


def _extract_events(source_doc: Any) -> list[dict[str, Any]]:
    if isinstance(source_doc, dict):
        raw_events = source_doc.get("final_events") or source_doc.get("events") or []
    elif isinstance(source_doc, list):
        raw_events = source_doc
    else:
        raw_events = []
    return [event for event in raw_events if isinstance(event, dict)]


def _apply_local_guardrail(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    allowed_types = set(EVENT_TYPES_V3)
    guarded: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []

    for event in events:
        event_id = str(event.get("event_id") or f"event_{len(guarded) + 1}")
        event_type = str(event.get("event_type") or "")
        if event_type not in allowed_types:
            findings.append(
                {
                    "rule_id": "illegal_event_type",
                    "severity": "drop",
                    "event_id": event_id,
                    "video_timestamp": event.get("video_timestamp") or event.get("timestamp"),
                    "match_time": event.get("match_time"),
                    "field": "event_type",
                    "original_value": event_type,
                    "action": "drop_event",
                }
            )
            patches.append({"op": "drop_event", "event_id": event_id, "reason": f"illegal event_type: {event_type}"})
            continue

        cleaned = dict(event)
        for field in IDENTITY_FIELDS:
            if field not in cleaned:
                continue
            cleaned[field] = _sanitize_field_value(
                cleaned[field],
                event_id=event_id,
                field=field,
                event=event,
                findings=findings,
                patches=patches,
            )
        guarded.append(cleaned)

    for index, event in enumerate(guarded, start=1):
        event["event_id"] = f"F{index:04d}"
    return guarded, findings, patches


def _sanitize_field_value(
    value: Any,
    *,
    event_id: str,
    field: str,
    event: dict[str, Any],
    findings: list[dict[str, Any]],
    patches: list[dict[str, Any]],
) -> Any:
    if isinstance(value, str):
        cleaned = _sanitize_identity_text(value)
        if cleaned != value:
            findings.append(
                {
                    "rule_id": "identity_contamination",
                    "severity": "patch",
                    "event_id": event_id,
                    "video_timestamp": event.get("video_timestamp") or event.get("timestamp"),
                    "match_time": event.get("match_time"),
                    "field": field,
                    "original_value": value,
                    "action": "replace_text",
                }
            )
            patches.append({"op": "replace_text", "event_id": event_id, "field": field, "value": cleaned})
        return cleaned
    if isinstance(value, list):
        return [
            _sanitize_field_value(
                item,
                event_id=event_id,
                field=field,
                event=event,
                findings=findings,
                patches=patches,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _sanitize_field_value(
                item,
                event_id=event_id,
                field=f"{field}.{key}",
                event=event,
                findings=findings,
                patches=patches,
            )
            for key, item in value.items()
        }
    return value


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
        "NMECHA",
        "ADEYEMI",
        "WIRTZ",
        "MUSIALA",
        "KIMMICH",
        "SANE",
        "SANÉ",
        "Sané",
        "Sane",
        "HAVERTZ",
        "BROWN",
        "ANTON",
        "BACUNA",
        "L. Bacuna",
    ]
    for name in player_names:
        if re.search(r"[A-Za-z]", name):
            text = re.sub(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", "球员", text, flags=re.IGNORECASE)
        else:
            text = text.replace(name, "球员")

    replacements = {
        "守门员": "防守方",
        "门将": "防守方",
        "前锋": "球员",
        "后卫": "球员",
        "中场": "球员",
        "队长": "球员",
        "主罚手": "球员",
        "主罚球员": "球员",
        "射手": "球员",
        "替补球员": "球员",
        "替补": "球队人员",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"#\s*\d{1,2}\b", "球员", text)
    text = re.sub(r"\d{1,2}\s*号(?:球员)?", "球员", text)
    text = re.sub(r"\(\s*\d{1,2}\s*\)", "", text)
    text = re.sub(r"\b[A-Z][a-zÀ-ÿ'’.-]+(?:\s+[A-Z][a-zÀ-ÿ'’.-]+)+\b", "球员", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_guardrail_report(guarded_doc: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    summary = guarded_doc.get("guardrail_summary") or {}
    lines = [
        "# V4 Guardrail Report",
        "",
        f"- Source events: {summary.get('source_events')}",
        f"- Guarded events: {summary.get('guarded_events')}",
        f"- Dropped events: {summary.get('dropped_events')}",
        f"- Findings: {summary.get('findings')}",
        "",
        "| Rule | Event | Time | Field | Action | Original |",
        "|---|---|---|---|---|---|",
    ]
    for finding in findings:
        original = str(finding.get("original_value") or "").replace("|", "\\|")
        lines.append(
            "| "
            f"{finding.get('rule_id')} | {finding.get('event_id')} | "
            f"{finding.get('match_time') or finding.get('video_timestamp') or ''} | "
            f"{finding.get('field')} | {finding.get('action')} | {original} |"
        )
    lines.append("")
    return "\n".join(lines)
