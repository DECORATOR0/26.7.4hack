from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_intern_config
from .guardrail import _sanitize_identity_text
from .intern_client import InternClient
from .io_utils import ensure_dir, extract_json_object, read_json, timestamp_to_seconds, write_json, write_text


@dataclass
class ScriptReportOptions:
    events_path: Path
    out_dir: Path
    match_info_path: Path | None = None
    temperature: float = 0.2
    max_tokens: int = 10000
    report_version: str = "v2"
    pure_model_output: bool = False
    no_model: bool = False


class ScriptReportRunner:
    def __init__(self, options: ScriptReportOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.client = InternClient(load_intern_config(), timeout=300)

    def run(self) -> Path:
        events_doc = read_json(self.options.events_path)
        events = self._normalize_events(events_doc)
        match_info = self._load_match_info()

        if self.options.no_model:
            if self.options.report_version in {"v3", "v3_markdown", "v4_markdown"}:
                report_json = self._fallback_v3_json(events)
                suffix = "v4" if self.options.report_version == "v4_markdown" else "v3"
                write_json(self.out_dir / f"final_report_{suffix}.json", report_json)
                markdown = self._v3_markdown(report_json)
                write_text(self.out_dir / f"final_report_{suffix}.md", markdown)
            else:
                markdown = self._fallback_markdown(events, match_info)
                write_text(self.out_dir / "commentary_report.md", markdown)
            write_json(self.out_dir / "script_report_runtime_summary.json", self._summary(None, events, markdown))
            return self.out_dir

        prompt = self._build_prompt(events, match_info)
        system_content = (
            "你是世界杯比赛集锦解说脚本编辑。你只基于 final_events_guarded_v4 写最终交付 Markdown，"
            "事项必须全量列出；解说文案要把有关联事项自然粘合，不要硬凑无关事项。输出必须是 Markdown。"
            if self.options.report_version == "v4_markdown"
            else (
            "你是世界杯比赛集锦解说脚本编辑。你只基于 final_events_clean_v3 写最终交付 Markdown，"
            "不能新增事实，不能输出推理过程。输出必须是 Markdown。"
            if self.options.report_version == "v3_markdown"
            else (
            "你是世界杯比赛集锦解说脚本编辑。你只基于 final_events_clean_v3 写稿，"
            "不能新增事实，不能输出球员姓名、号码、位置或身份。只输出严格 JSON。"
            if self.options.report_version == "v3"
            else (
                "你是世界杯比赛集锦解说脚本编辑。你只基于给定关键事件写稿，"
                "不能编造没有证据的球员、比分、判罚或技术指标。输出 Markdown。"
            )
            )
            )
        )
        messages = [
            {
                "role": "system",
                "content": system_content,
            },
            {"role": "user", "content": prompt},
        ]
        started = time.time()
        response = self.client.chat(
            messages,
            temperature=self.options.temperature,
            max_tokens=self.options.max_tokens,
            thinking_mode=False,
        )
        finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
        raw = {
            "ok": bool(response.content.strip()) and finish_reason != "length",
            "elapsed_seconds": round(time.time() - started, 3),
            "usage": response.raw.get("usage"),
            "finish_reason": finish_reason,
            "request_max_tokens": self.options.max_tokens,
            "temperature": self.options.temperature,
            "content": response.content,
        }
        write_json(self.out_dir / "script_report_raw.json", raw)
        if self.options.report_version in {"v3_markdown", "v4_markdown"}:
            markdown = response.content.strip() + "\n"
            if self.options.report_version == "v4_markdown":
                markdown = "\n".join(_sanitize_identity_text(line) for line in markdown.splitlines()) + "\n"
            suffix = "v4" if self.options.report_version == "v4_markdown" else "v3"
            write_text(self.out_dir / f"final_report_{suffix}.md", markdown)
        elif self.options.report_version == "v3":
            try:
                report_json = extract_json_object(response.content)
                if not isinstance(report_json, dict):
                    raise ValueError("V3 report response is not a JSON object")
                if not self.options.pure_model_output:
                    report_json = self._sanitize_v3_report(report_json)
                write_json(self.out_dir / "final_report_v3.json", report_json)
                markdown = self._v3_markdown(report_json)
                write_text(self.out_dir / "final_report_v3.md", markdown)
                raw["ok"] = raw["ok"] and finish_reason != "length"
            except Exception as exc:
                report_json = {"event_table": [], "passionate_commentary": "", "parse_error": str(exc)}
                write_json(self.out_dir / "final_report_v3.json", report_json)
                markdown = response.content.strip() + "\n"
                write_text(self.out_dir / "final_report_v3.md", markdown)
                raw["ok"] = False
                raw["parse_error"] = str(exc)
        else:
            markdown = response.content.strip() + "\n"
            write_text(self.out_dir / "commentary_report.md", markdown)
        write_json(self.out_dir / "script_report_raw.json", raw)
        write_json(self.out_dir / "script_report_runtime_summary.json", self._summary(raw, events, markdown))
        return self.out_dir

    def _load_match_info(self) -> dict[str, Any]:
        if self.options.match_info_path and self.options.match_info_path.exists():
            data = read_json(self.options.match_info_path)
            return data if isinstance(data, dict) else {}
        return {}

    @staticmethod
    def _normalize_events(events_doc: Any) -> list[dict[str, Any]]:
        if isinstance(events_doc, dict):
            events = events_doc.get("final_events") or events_doc.get("events") or []
        elif isinstance(events_doc, list):
            events = events_doc
        else:
            events = []
        normalized = [event for event in events if isinstance(event, dict)]
        period_order = {
            "pre_match": 0,
            "first_half": 1,
            "halftime": 2,
            "second_half": 3,
            "fulltime": 4,
            "unknown": 5,
        }
        normalized.sort(
            key=lambda event: (
                period_order.get(str(event.get("period") or "unknown"), 5),
                int(event.get("match_minute") or 0),
                int(event.get("stoppage_minute") or 0),
                str(event.get("video_timestamp") or event.get("timestamp") or event.get("start") or ""),
            )
        )
        return normalized

    def _build_prompt(self, events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
        if self.options.report_version == "v4_markdown":
            return self._build_prompt_v4_markdown(events, match_info)
        if self.options.report_version == "v3_markdown":
            return self._build_prompt_v3_markdown(events, match_info)
        if self.options.report_version == "v3":
            return self._build_prompt_v3(events, match_info)
        return self._build_prompt_v2(events, match_info)

    def _build_prompt_v2(self, events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
        compact_events = [
            {
                "event_id": event.get("event_id"),
                "timestamp": event.get("timestamp"),
                "start": event.get("start"),
                "end": event.get("end"),
                "event_type": event.get("event_type"),
                "title": event.get("title"),
                "confidence": event.get("confidence"),
                "importance": event.get("importance"),
                "evidence": event.get("evidence"),
                "needs_more_review": event.get("needs_more_review"),
                "script_angle": event.get("script_angle"),
            }
            for event in events
        ]
        return f"""请根据给定的比赛信息和关键事件，生成一份可直接给队友查看的中文解说脚本 Markdown。

比赛信息：
{json.dumps(match_info, ensure_ascii=False, indent=2)}

关键事件：
{json.dumps(compact_events, ensure_ascii=False, indent=2)}

输出要求：
1. 输出 Markdown，不要 JSON，不要解释生成过程。
2. 风格参考“专业解说脚本与结构化输出文档”，但不要照搬模板里的虚构技术指标。
3. 必须严格基于关键事件；没有证据的球员名、比分、射门方式、助攻者、牌色、判罚原因都不要编。
4. 如果同一进球附近有 replay/celebration，写脚本时要合并成一个叙事段，不要写成重复进球。
5. 如果事件 `needs_more_review=true` 或 confidence 低，要在内部备注里标注“需复核”，正文不要把它写死成确定事实。
6. 队名固定为德国 vs 库拉索。禁止输出哥伦比亚、委内瑞拉、美国、巴拉圭等非本场球队名，除非原事件证据明确就是模板示例，但这里不应出现。
7. 语言要有现场感，但不要过度夸张；宁可写“德国队球员”也不要乱猜名字。

输出结构必须包含：

# 2026年世界杯：德国 vs 库拉索 解说脚本与关键事件报告

## 文档说明
- 比赛
- 事件来源
- 生成版本说明
- 风险提示

## 第一部分：解说脚本（完整版）
按时间线写成可朗读脚本。至少包含：
- 开场介绍
- 上半场关键进程
- 下半场关键进程
- 赛后总结

每个关键段落格式：
### 时间点：标题
```text
【镜头/画面提示】
解说员：
"..."
```

## 第二部分：关键事件时间轴
用 Markdown 表格输出：序号、时间、事件类型、标题、重要性、可信度、解说价值、证据摘要。

## 第三部分：短视频口播版
生成 60-90 秒中文口播稿，适合集锦视频。

## 第四部分：分镜与制作提示
按时间线列出可用于剪辑的画面点，包括进球、回放、庆祝、争议、换人、全场结束。

## 第五部分：内部复核备注
只列需要复核或可能重复的事件，不要过长。"""

    def _build_prompt_v3_markdown(self, events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
        compact_events = [
            {
                "event_id": event.get("event_id"),
                "match_time": event.get("match_time"),
                "video_timestamp": event.get("video_timestamp") or event.get("timestamp"),
                "period": event.get("period"),
                "event_type": event.get("event_type"),
                "title": event.get("title"),
                "certainty": event.get("certainty"),
                "evidence_level": event.get("evidence_level"),
                "confidence": event.get("confidence"),
                "importance": event.get("importance"),
                "evidence": event.get("evidence"),
                "needs_more_review": event.get("needs_more_review"),
                "script_angle": event.get("script_angle"),
                "linked_event_id": event.get("linked_event_id"),
            }
            for event in events
        ]
        return f"""请只基于给定比赛信息和 V3 final events 生成最终交付 Markdown。

比赛信息：
{json.dumps(match_info, ensure_ascii=False, indent=2)}

V3 final events：
{json.dumps(compact_events, ensure_ascii=False, indent=2)}

输出要求：
1. 只输出 Markdown，不要 JSON，不要解释生成过程。
2. Markdown 只能包含两个一级标题，顺序固定：
   # 事项事件表格
   # 激情版解说文稿
3. 第一部分必须是表格，列固定为：序号、比赛时间、视频时间戳、事项类型、事件标题、确定性、证据摘要。
4. 第二部分是按比赛时间从前往后推进的中文解说文稿，必须覆盖表格里的每一条事项。
5. 只能基于输入 events 写，不要新增没有证据的事实。
6. replay/celebration 如果和主进球有关，叙事里要自然合并，不能写成重复进球。
7. 如果事项 certainty=probable 或 uncertain，文稿中用“疑似”“可能”“从画面看”等稳妥措辞。
8. 队名固定为德国 vs 库拉索；禁止出现其他国家队名。
9. 不要输出额外章节，不要输出制作提示、内部备注、短视频口播版。
10. 输出必须是最终可交付 Markdown。"""

    def _build_prompt_v4_markdown(self, events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
        compact_events = [
            {
                "event_id": event.get("event_id"),
                "match_time": event.get("match_time"),
                "video_timestamp": event.get("video_timestamp") or event.get("timestamp"),
                "period": event.get("period"),
                "event_type": event.get("event_type"),
                "title": event.get("title"),
                "certainty": event.get("certainty"),
                "evidence_level": event.get("evidence_level"),
                "confidence": event.get("confidence"),
                "importance": event.get("importance"),
                "evidence": event.get("evidence"),
                "needs_more_review": event.get("needs_more_review"),
                "script_angle": event.get("script_angle"),
                "linked_event_id": event.get("linked_event_id"),
                "source_event_ids": event.get("source_event_ids"),
            }
            for event in events
        ]
        commentary_groups = self._build_v4_commentary_groups(compact_events)
        return f"""请只基于给定比赛信息和 final_events_guarded_v4 生成最终交付 Markdown。

比赛信息：
{json.dumps(match_info, ensure_ascii=False, indent=2)}

final_events_guarded_v4：
{json.dumps(compact_events, ensure_ascii=False, indent=2)}

解说分组 commentary_groups：
{json.dumps(commentary_groups, ensure_ascii=False, indent=2)}

输出要求：
1. 只输出 Markdown，不要 JSON，不要解释生成过程。
2. Markdown 只能包含两个一级标题，顺序固定：
   # 事项列表
   # 解说文案
3. 事项列表必须把输入里的每一条 event 全部列出来，不能漏。用 Markdown 表格，列固定为：序号、比赛时间、视频时间戳、事项类型、事件标题、确定性、证据摘要。
4. 解说文案按比赛时间从前往后写。每个段落格式固定为：
   ## 第XX分钟：小标题
   一小段激情解说文案。
   例如 `6'` 写成 `第6分钟`，`45+5'` 写成 `第45+5分钟`；如果 match_time 不清楚，就用视频时间写 `视频00:14:12`。
5. 解说文案必须严格按 commentary_groups 输出：一个 group 只写一个 `## 第XX分钟：小标题` 段落，组内多个 event 必须粘合到同一段。
6. 有明确关联的事项要粘合成同一个解说段，例如：
   - `linked_event_id` 指向同一主事项。
   - 点球判罚和紧接着的点球射门/进球。
   - 任意球或角球和紧接着由它直接产生的射门/进球。
   - 同一进球后的庆祝或回放证据。
7. 没有关联的事项不要硬凑；相邻但不是同一动作链的事项必须分段写。
8. 解说文案风格参考高燃解说稿：有现场感、节奏感，一段即可，不要写成长篇分析。
9. 只能基于输入 events 写，不要新增没有证据的事实；不能新增比分、球员姓名、号码、身份、技术指标、判罚原因。
10. 严禁出现身份词：门将、守门员、前锋、后卫、中场、队长、主罚手、替补球员；用“防守方”“球员”“球队人员”这类泛称替代。
11. 如果事项 certainty=probable 或 uncertain，文稿中用“疑似”“可能”“从画面看”等稳妥措辞。
12. 队名固定为德国 vs 库拉索；禁止出现其他国家队名。
13. 不要输出额外章节，不要输出制作提示、内部备注、短视频口播版。
14. 输出必须是最终可交付 Markdown。"""

    @staticmethod
    def _build_v4_commentary_groups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for event in events:
            if groups and _v4_events_related(groups[-1]["events"], event):
                groups[-1]["events"].append(event)
                groups[-1]["event_ids"].append(event.get("event_id"))
                groups[-1]["titles"].append(event.get("title"))
                continue
            groups.append(
                {
                    "group_id": f"G{len(groups) + 1:04d}",
                    "heading_time": _display_minute(event),
                    "event_ids": [event.get("event_id")],
                    "titles": [event.get("title")],
                    "events": [event],
                }
            )
        return [
            {
                "group_id": group["group_id"],
                "heading_time": group["heading_time"],
                "event_ids": group["event_ids"],
                "title_hint": " / ".join(str(title) for title in group["titles"] if title),
                "events": [
                    {
                        "event_id": item.get("event_id"),
                        "match_time": item.get("match_time"),
                        "event_type": item.get("event_type"),
                        "title": item.get("title"),
                        "certainty": item.get("certainty"),
                    }
                    for item in group["events"]
                ],
            }
            for group in groups
        ]

    def _build_prompt_v3(self, events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
        compact_events = [
            {
                "event_id": event.get("event_id"),
                "match_time": event.get("match_time"),
                "video_timestamp": event.get("video_timestamp") or event.get("timestamp"),
                "period": event.get("period"),
                "event_type": event.get("event_type"),
                "title": event.get("title"),
                "certainty": event.get("certainty"),
                "evidence_level": event.get("evidence_level"),
                "confidence": event.get("confidence"),
                "importance": event.get("importance"),
                "evidence": event.get("evidence"),
                "needs_more_review": event.get("needs_more_review"),
                "script_angle": event.get("script_angle"),
            }
            for event in events
        ]
        return f"""请只基于给定比赛信息和 final_events_clean_v3 生成 V3 最终报告 JSON。

比赛信息：
{json.dumps(match_info, ensure_ascii=False, indent=2)}

final_events_clean_v3：
{json.dumps(compact_events, ensure_ascii=False, indent=2)}

输出要求：
1. 只输出严格 JSON，不要 Markdown，不要解释生成过程。
2. JSON 只包含两个顶级字段：event_table 和 passionate_commentary。
3. event_table 必须覆盖输入里的每一条事项，顺序按比赛时间推进。
4. passionate_commentary 必须覆盖 event_table 里的每一条事项，但可以把庆祝、回放证据和主事项合并成自然叙事。
5. 可以有现场感和激情表达，但不能新增事实。
6. 禁止输出球员姓名、球衣号码、前锋/后卫/门将/队长等位置或身份；最多写“德国队”“库拉索队”“德国队球员”“库拉索球员”。
7. 禁止新增比分、技术指标、射门方式、助攻者、牌色、判罚原因。
8. 如果某条事项 certainty=probable 或 uncertain，解说里用更稳妥的措辞，不要写死成确定事实。
9. 队名固定为德国 vs 库拉索，禁止出现其他国家队名。

输出格式：
{{
  "event_table": [
    {{
      "index": 1,
      "match_time": "6'",
      "video_timestamp": "00:14:12",
      "event_type": "goal",
      "title": "德国队首开记录",
      "certainty": "probable",
      "evidence_summary": "narrative 明确描述破门和庆祝"
    }}
  ],
  "passionate_commentary": "第6分钟，德国队终于撕开局面！这次禁区附近的进攻让比赛节奏瞬间被点燃……"
}}"""

    @staticmethod
    def _fallback_v3_json(events: list[dict[str, Any]]) -> dict[str, Any]:
        event_table = []
        for index, event in enumerate(events, 1):
            evidence = event.get("evidence")
            if isinstance(evidence, list):
                evidence_summary = "；".join(str(item) for item in evidence[:2])
            else:
                evidence_summary = str(evidence or "")
            event_table.append(
                {
                    "index": index,
                    "match_time": event.get("match_time") or "",
                    "video_timestamp": event.get("video_timestamp") or event.get("timestamp") or "",
                    "event_type": event.get("event_type") or "",
                    "title": event.get("title") or "",
                    "certainty": event.get("certainty") or "",
                    "evidence_summary": evidence_summary,
                }
            )
        commentary_parts = [
            f"{item.get('match_time') or item.get('video_timestamp')}，{item.get('title')}。"
            for item in event_table
            if item.get("title")
        ]
        return ScriptReportRunner._sanitize_v3_report(
            {"event_table": event_table, "passionate_commentary": "".join(commentary_parts)}
        )

    @staticmethod
    def _sanitize_v3_report(report_json: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(report_json)
        table = []
        for item in cleaned.get("event_table") or []:
            if not isinstance(item, dict):
                continue
            table.append({key: _sanitize_report_identity_text(value) for key, value in item.items()})
        cleaned["event_table"] = table
        cleaned["passionate_commentary"] = _sanitize_report_identity_text(cleaned.get("passionate_commentary") or "")
        return cleaned

    @staticmethod
    def _v3_markdown(report_json: dict[str, Any]) -> str:
        event_table = report_json.get("event_table") or []
        lines = [
            "# 事项事件表格",
            "",
            "| 序号 | 比赛时间 | 视频时间戳 | 事项类型 | 事件标题 | 确定性 | 证据摘要 |",
            "|---:|---|---|---|---|---|---|",
        ]
        for index, item in enumerate(event_table, 1):
            if not isinstance(item, dict):
                continue
            lines.append(
                "| "
                f"{item.get('index') or index} | {item.get('match_time') or ''} | "
                f"{item.get('video_timestamp') or ''} | {item.get('event_type') or ''} | "
                f"{item.get('title') or ''} | {item.get('certainty') or ''} | "
                f"{item.get('evidence_summary') or ''} |"
            )
        lines.extend(["", "# 激情版解说文稿", "", str(report_json.get("passionate_commentary") or "").strip(), ""])
        return "\n".join(lines)

    @staticmethod
    def _fallback_markdown(events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
        match_name = match_info.get("match_name") or "德国 vs 库拉索"
        lines = [
            f"# 2026年世界杯：{match_name} 解说脚本与关键事件报告",
            "",
            "## 文档说明",
            "",
            f"- 比赛：{match_name}",
            "- 事件来源：final_events.json",
            "- 生成版本：fallback，无模型润色",
            "",
            "## 第一部分：解说脚本（简版）",
            "",
        ]
        for event in events:
            lines.extend(
                [
                    f"### {event.get('timestamp') or event.get('start')}：{event.get('title')}",
                    "",
                    "```text",
                    "【镜头提示】",
                    f"{event.get('evidence') or '根据关键事件证据切入相关画面。'}",
                    "",
                    "解说员：",
                    f"\"{event.get('script_angle') or event.get('title') or '比赛出现关键事件。'}\"",
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "## 第二部分：关键事件时间轴",
                "",
                "| 序号 | 时间 | 事件类型 | 标题 | 重要性 | 可信度 | 证据摘要 |",
                "|---:|---|---|---|---|---:|---|",
            ]
        )
        for index, event in enumerate(events, 1):
            lines.append(
                "| "
                f"{index} | {event.get('timestamp') or event.get('start')} | {event.get('event_type')} | "
                f"{event.get('title')} | {event.get('importance')} | {event.get('confidence')} | "
                f"{event.get('evidence')} |"
            )
        lines.extend(["", "## 第三部分：短视频口播版", "", "本场比赛关键事件密集，德国队多次通过进攻和定位球制造威胁。完整口播稿需要模型润色生成。"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _summary(raw: dict[str, Any] | None, events: list[dict[str, Any]], markdown: str) -> dict[str, Any]:
        usage = (raw or {}).get("usage") or {}
        return {
            "events": len(events),
            "ok": True if raw is None else raw.get("ok"),
            "finish_reason": None if raw is None else raw.get("finish_reason"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "markdown_chars": len(markdown),
        }


def _v4_events_related(group_events: list[dict[str, Any]], event: dict[str, Any]) -> bool:
    if not group_events:
        return False
    previous = group_events[-1]
    current_type = str(event.get("event_type") or "")
    previous_type = str(previous.get("event_type") or "")
    group_ids = {str(item.get("event_id") or "") for item in group_events}
    linked_event_id = str(event.get("linked_event_id") or "")
    if linked_event_id and linked_event_id in group_ids:
        return True

    current_seconds = timestamp_to_seconds(event.get("video_timestamp") or event.get("timestamp"))
    previous_seconds = timestamp_to_seconds(previous.get("video_timestamp") or previous.get("timestamp"))
    close = abs(current_seconds - previous_seconds) <= 120
    same_match_time = bool(event.get("match_time")) and event.get("match_time") == previous.get("match_time")

    if current_type == "celebration" and close and any(item.get("event_type") == "goal" for item in group_events):
        return True
    if previous_type == "celebration" and close and current_type == "goal":
        return True
    if same_match_time and {current_type, previous_type} & {"goal", "celebration"}:
        return True
    if previous_type in {"corner", "free_kick", "penalty"} and current_type in {"shot_chance", "goal", "celebration"} and close:
        return True
    if previous_type == "goal" and current_type == "celebration" and close:
        return True
    if previous_type == "substitution" and current_type == "substitution" and close and same_match_time:
        return True
    return False


def _display_minute(event: dict[str, Any]) -> str:
    match_time = str(event.get("match_time") or "").strip()
    if match_time:
        text = match_time.replace("'", "").strip()
        if ":" in text:
            text = text.split(":", 1)[0]
        return f"第{text}分钟"
    video_time = event.get("video_timestamp") or event.get("timestamp") or ""
    return f"视频{video_time}"


def _sanitize_report_identity_text(value: Any) -> str:
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
