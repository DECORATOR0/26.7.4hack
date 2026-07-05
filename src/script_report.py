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

        if self.options.report_version in {"v4_3_markdown", "v4_4_markdown", "v4_5_markdown", "v4_6_markdown"}:
            suffix_map = {
                "v4_3_markdown": "v4_3",
                "v4_4_markdown": "v4_4",
                "v4_5_markdown": "v4_5",
                "v4_6_markdown": "v4_6",
            }
            suffix = suffix_map[self.options.report_version]
            split_items = suffix in {"v4_5", "v4_6"}
            report_events = _v4_5_downstream_events(events) if suffix == "v4_5" else events
            if split_items:
                items_markdown = _v4_3_items_markdown(report_events, table_time_precision="10s")
                write_text(self.out_dir / f"final_report_{suffix}_items.md", items_markdown)
            markdown = _v4_3_markdown(
                report_events,
                match_info,
                suffix,
                include_front_sections=not split_items,
            )
            write_text(self.out_dir / f"final_report_{suffix}.md", markdown)
            write_json(self.out_dir / "script_report_runtime_summary.json", self._summary(None, report_events, markdown))
            return self.out_dir

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
                markdown = _enforce_v4_event_table(markdown, events)
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

    def _normalize_events(self, events_doc: Any) -> list[dict[str, Any]]:
        if isinstance(events_doc, dict):
            events = events_doc.get("final_events") or events_doc.get("events") or []
        elif isinstance(events_doc, list):
            events = events_doc
        else:
            events = []
        normalized = [dict(event) for event in events if isinstance(event, dict)]
        if self.options.report_version in {"v4_markdown", "v4_3_markdown", "v4_4_markdown", "v4_5_markdown", "v4_6_markdown"}:
            return _prepare_v4_report_events(normalized)

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
4. 解说文案按输入 events 的顺序从前往后写；输入顺序已经按视频时间校正。每个段落格式固定为：
   ## 第XX分钟：小标题
   一小段激情解说文案。
   `match_time` 已经是可直接使用的中文显示；不要改成撇号格式，不要把 `00:25` 一类比赛钟误写成第25分钟。
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
13. OCR、记分牌、比分跳变只能作为事实校验依据；解说员台词里不要出现“跳变前/跳变后/OCR/比赛钟/确认依据/由记分牌确认”等内部审计话术。
14. 不要输出额外章节，不要输出制作提示、内部备注、短视频口播版。
15. 输出必须是最终可交付 Markdown。"""

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


V4_5_DOWNSTREAM_EVENT_TYPES = {
    "goal",
    "shot_chance",
    "corner",
    "free_kick",
    "foul_card_dispute",
    "substitution",
}


def _v4_5_downstream_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if str(event.get("event_type") or "") in V4_5_DOWNSTREAM_EVENT_TYPES]


def _v4_5_delivery_event_groups(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for event in events:
        if _v4_3_filter_event(event) is None:
            continue
        if groups and (_v4_events_related(groups[-1], event) or _same_display_minute(groups[-1][-1], event)):
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def _same_display_minute(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _display_minute(left) == _display_minute(right)


def _v4_3_markdown(
    events: list[dict[str, Any]],
    match_info: dict[str, Any],
    version: str = "v4_3",
    include_front_sections: bool = True,
) -> str:
    match_name = match_info.get("match_name") or "德国 vs 库拉索"
    final_score = _v4_3_final_score(events, match_info)
    groups = _v4_5_delivery_event_groups(events) if version == "v4_5" else _v4_3_event_groups(events)
    version_label = version.upper().replace("_", ".")
    lines: list[str] = []
    if include_front_sections:
        lines.extend(_v4_3_compat_event_table(events, table_time_precision="10s" if version in {"v4_5", "v4_6"} else "display"))
        lines.extend(["", "# 解说文案", ""])
        for event in events:
            lines.extend(
                [
                    f"## {_display_minute(event)}：{_sanitize_identity_text(str(event.get('title') or '关键事件'))}",
                    _v4_3_single_event_script(event),
                    "",
                ]
            )

    lines.extend(
        [
            f"# 交付扩展脚本（{version_label} 融合版）",
            "",
            "## 文档说明",
            "",
            f"- **比赛**：{match_name}",
            f"- **进球口径**：{version_label} 的进球只采纳记分牌 OCR 比分跳变，不再把回放、庆祝或进球信息条单独升格为新进球。",
            "- **非进球事件**：射门机会、角球、任意球、判罚争议、换人沿用现有视觉事件链路，并在输出阶段做合并和降噪。",
            "- **事项表用途**：最前面的事项列表面向 Web/demo 结构化消费，只有该表的比赛时间使用 10 秒粒度；后续解说文本仍按分钟叙述。",
            "- **Web/demo 保留类型**：进球、射门机会、角球、任意球、判罚争议、换人；点球、越位、半场/全场、庆祝不进入外部事项列表。",
            "- **写作约束**：不输出具体球员姓名、号码和位置身份；OCR/记分牌/比分跳变只作为事实校验依据，不把“跳变前/跳变后/OCR/比赛钟/确认依据”等内部审计话术写进解说员台词；技术统计只基于 Harness 保留事件，不等同官方统计。",
            "- **端到端约束**：从视频帧、OCR 记分牌和模型视觉叙述自动生成 Markdown，中间不依赖人工或强模型改写最终稿。",
            "",
            "---",
            "",
            "## 第一部分：解说脚本（完整版）",
            "",
            "### 开场介绍",
            "",
            "```text",
            f"【镜头/画面提示】：全场全景，比分牌显示 {match_name}",
            "解说员：",
            f"“各位球迷朋友，欢迎来到世界杯赛场！{match_name}，哨声一响，比赛的火药味就被拉起来了。德国队想用压迫把节奏踩到底，库拉索也在等待反击和定位球的爆点。接下来每一次射门、每一次定位球、每一次比分跳动，都可能把现场彻底点燃。”",
            "```",
            "",
            "### 关键进程",
            "",
        ]
    )
    for group in groups:
        lines.extend(
            [
                f"#### {_v4_3_group_heading(group)}",
                "",
                "```text",
                f"【镜头/画面提示】：{_v4_3_group_kind(group)}画面，{_v4_3_group_title(group)}",
                "解说员：",
                f"“{_v4_3_group_script(group)}”",
                "```",
                "",
            ]
        )

    if version == "v4_5":
        lines.extend(["### 平实风格解说稿", ""])
        for group in groups:
            lines.extend(
                [
                    f"- {_v4_3_group_heading(group)}",
                    "```text",
                    "解说员：",
                    f"“{_v4_5_plain_group_script(group)}”",
                    "```",
                    "",
                ]
            )

    lines.extend(["---", "", "## 第二部分：关键事件时间轴", ""])
    lines.extend(_v4_3_public_timeline(groups))
    lines.extend(["", "---", "", "## 第三部分：多语言解说脚本", ""])
    lines.extend(_v4_3_multilingual(groups, final_score))
    lines.extend(["", "---", "", "## 第四部分：配音脚本", ""])
    lines.extend(_v4_3_voiceover(groups, final_score, version_label))
    lines.extend(["", "---", "", "## 第五部分：字幕脚本", ""])
    lines.extend(_v4_3_subtitle_blocks(events, final_score))
    lines.extend(["", "---", "", "## 第六部分：集锦讲解脚本（3分钟版）", ""])
    lines.extend(_v4_3_highlight_script(groups, final_score, version_label))
    lines.extend(["", "---", "", "## 第七部分：技术统计分析", ""])
    lines.extend(_v4_3_stats_table(events))
    lines.extend(
        [
            "",
            "> 说明：本表只统计当前 Harness 确认保留下来的关键事件，不等同于官方技术统计。",
            "",
            "---",
            "",
            "## 第八部分：内部复核备注",
            "",
            f"- 原始事件数：{len(events)}",
            f"- 融合讲解节点数：{len(groups)}",
            f"- 进球节点数：{sum(1 for event in events if event.get('event_type') == 'goal')}",
            "- 已将进球判定切换为记分牌 OCR 分数跳变硬规则。",
            "- 事项列表的比赛时间已限制为 10 秒粒度，便于 Web/demo 时间轴消费。",
            "- 普通回放、庆祝和进球信息条不再单独作为新进球依据。",
            "- 非进球事件仍需要后续结合画面继续做准确率优化。",
            "",
        ]
    )
    return "\n".join(lines)


def _v4_3_compat_event_table(events: list[dict[str, Any]], table_time_precision: str = "display") -> list[str]:
    lines = [
        "# 事项列表",
        "",
        "| 序号 | 比赛时间 | 视频时间戳 | 事项类型 | 事件标题 | 确定性 | 证据摘要 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for index, event in enumerate(events, start=1):
        evidence = event.get("evidence")
        if isinstance(evidence, list):
            evidence_text = "；".join(str(item) for item in evidence[:2])
        else:
            evidence_text = str(evidence or "")
        values = [
            str(index),
            _event_table_match_time(event, table_time_precision),
            str(event.get("video_timestamp") or event.get("timestamp") or ""),
            str(event.get("event_type") or ""),
            str(event.get("title") or ""),
            str(event.get("certainty") or event.get("status") or ""),
            evidence_text,
        ]
        lines.append("| " + " | ".join(_escape_markdown_cell(_sanitize_identity_text(value)) for value in values) + " |")
    return lines


def _v4_3_items_markdown(events: list[dict[str, Any]], table_time_precision: str = "10s") -> str:
    return "\n".join(_v4_3_compat_event_table(events, table_time_precision=table_time_precision)).rstrip() + "\n"


def _event_table_match_time(event: dict[str, Any], precision: str) -> str:
    raw = str(event.get("match_time") or "").strip()
    if precision != "10s":
        return raw
    seconds = _match_time_to_seconds(raw)
    if seconds is None:
        minute = event.get("match_minute")
        stoppage = event.get("stoppage_minute")
        try:
            base_seconds = int(minute) * 60
            if int(stoppage or 0) > 0 and int(minute) <= 90:
                base_seconds += int(stoppage) * 60
            seconds = base_seconds
        except (TypeError, ValueError):
            return raw
    rounded = int((seconds + 5) // 10 * 10)
    return _format_match_seconds(rounded, always_seconds=True)


def _v4_3_event_groups(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for event in events:
        if _v4_3_filter_event(event) is None:
            continue
        if groups and _v4_events_related(groups[-1], event):
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def _v4_3_filter_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(event.get("event_type") or "")
    if event_type == "celebration" and event.get("linked_event_id"):
        return None
    title = str(event.get("title") or "")
    description = _v4_3_description(event)
    generic = title + description
    if event_type == "shot_chance" and any(term in generic for term in ["中场组织", "普通控球", "继续进攻"]):
        return None
    return event


def _v4_3_single_event_script(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    minute = _display_minute(event)
    title = _sanitize_identity_text(str(event.get("title") or "关键事件"))
    description = _v4_5_broadcast_detail(event)
    score = str(event.get("score_after") or "")
    if event_type == "goal":
        score_text = f"，比分来到 {score}" if score else ""
        team = _v4_5_event_team_name(event)
        return f"{minute}，漂亮！球进了！{team}把这一波攻势打成了进球{score_text}！这一下把现场情绪完全点燃，比赛走势立刻有了新的重量。{description}"
    if event_type == "penalty":
        return f"{minute}，点球相关判罚出现，比赛瞬间紧张起来。{description}"
    if event_type in {"corner", "free_kick"}:
        return f"{minute}，定位球机会来了！禁区里的站位一下紧起来，下一脚处理随时可能把局面推向高潮。{description}"
    if event_type in {"foul_card_dispute", "offside"}:
        return f"{minute}，哨声响起，裁判判罚成为焦点！这次身体接触让比赛节奏被猛地拧紧。{description}"
    if event_type == "substitution":
        return f"{minute}，场边开始调整！换人信号一出现，比赛进入重新布置节奏的阶段。{description}"
    if event_type == "half_full_time":
        return f"{minute}，阶段哨响，比赛节点被定格。{description}"
    if event_type == "shot_chance":
        return f"{minute}，攻势来了！{title}。这次射门把门前警报拉响，比赛速度一下提起来。{description}"
    return f"{minute}，关键画面出现：{title}。这一下把比赛温度继续往上推。{description}"


def _v4_3_group_heading(group: list[dict[str, Any]]) -> str:
    if not group:
        return "关键事件"
    first = group[0]
    if len(group) == 1:
        return f"{_display_minute(first)}：{_sanitize_identity_text(str(first.get('title') or '关键事件'))}"
    return f"{_display_minute(first)}：{_v4_3_group_title(group)}"


def _v4_3_group_kind(group: list[dict[str, Any]]) -> str:
    kinds: list[str] = []
    for event in group:
        kind = _event_kind_cn(str(event.get("event_type") or ""))
        if kind and kind not in kinds:
            kinds.append(kind)
    return "/".join(kinds) or "关键事件"


def _v4_3_group_title(group: list[dict[str, Any]]) -> str:
    titles = [_sanitize_identity_text(str(event.get("title") or "")) for event in group if event.get("title")]
    if not titles:
        return "关键事件"
    if len(titles) == 1:
        return titles[0]
    return "，".join(titles[:3])


def _v4_3_group_script(group: list[dict[str, Any]]) -> str:
    if not group:
        return "比赛出现关键节点。"
    if len(group) == 1:
        return _v4_3_single_event_script(group[0])
    first = group[0]
    minute = _display_minute(first)
    kinds = _v4_3_group_kind(group)
    details = "；".join(_v4_5_broadcast_detail(event).rstrip("。") for event in group[:3] if _v4_5_broadcast_detail(event))
    if any(event.get("event_type") == "goal" for event in group):
        goal = next(event for event in group if event.get("event_type") == "goal")
        score = f"，比分来到 {goal.get('score_after')}" if goal.get("score_after") else ""
        team = _v4_5_event_team_name(goal)
        return f"{minute}，漂亮！球进了！{team}把这一波攻势打成了进球{score}！这一下把现场情绪完全点燃，进攻推进、门前终结和连续画面连在一起，比赛走势立刻有了新的重量。{details}。"
    if any(event.get("event_type") in {"corner", "free_kick"} for event in group):
        return f"{minute}，这一段比赛的火药味上来了！{kinds}连续出现，禁区前后的站位和落点争夺都在升温。{details}。"
    if any(event.get("event_type") == "shot_chance" for event in group):
        return f"{minute}，攻势一波接一波压上来！{kinds}连续出现，门前警报不断被拉响。{details}。"
    return f"{minute}，{kinds}连续出现，比赛节奏被这一组画面推高，现场张力继续累积。{details}。"


def _v4_5_plain_group_script(group: list[dict[str, Any]]) -> str:
    if not group:
        return "本分钟没有保留的关键事项。"
    minute = _display_minute(group[0])
    kinds = _v4_3_group_kind(group)
    details = "；".join(_v4_3_description(event).rstrip("。") for event in group[:3] if _v4_3_description(event))
    goal = next((event for event in group if event.get("event_type") == "goal"), None)
    if goal:
        score = f"，比分来到 {goal.get('score_after')}" if goal.get("score_after") else ""
        return f"{minute}，{goal.get('team') or '进攻方'}完成进球{score}。{details}。比赛走势随之改变，现场节奏被这一球带起来。"
    if any(event.get("event_type") == "free_kick" for event in group):
        return f"{minute}，场上出现任意球或相关定位球机会。{details}。双方随后围绕罚球点和禁区站位重新组织。"
    if any(event.get("event_type") == "corner" for event in group):
        return f"{minute}，场上出现角球机会。{details}。禁区内双方准备争抢第一落点。"
    if any(event.get("event_type") == "foul_card_dispute" for event in group):
        return f"{minute}，裁判对身体接触或争议动作进行处理。{details}。比赛节奏短暂停顿后继续。"
    if any(event.get("event_type") == "substitution" for event in group):
        return f"{minute}，场边出现人员调整。{details}。球队通过换人调整后续比赛节奏。"
    if any(event.get("event_type") == "shot_chance" for event in group):
        return f"{minute}，场上出现射门机会。{details}。这次进攻没有改写比分，但形成了明确威胁。"
    return f"{minute}，{kinds}出现。{details}。"


def _v4_3_public_timeline(groups: list[list[dict[str, Any]]]) -> list[str]:
    lines = [
        "| 序号 | 时间 | 事件类型 | 涉及球队 | 事件描述 |",
        "|---:|---|---|---|---|",
    ]
    for index, group in enumerate(groups, start=1):
        event = group[0]
        lines.append(
            "| "
            f"{index} | {_display_minute(event)} | {_v4_3_group_kind(group)} | {_v4_3_group_teams(group)} | "
            f"{_escape_markdown_cell(_v4_3_group_title(group) + '。' + _v4_3_group_script(group))} |"
        )
    return lines


def _v4_3_group_teams(group: list[dict[str, Any]]) -> str:
    teams = []
    for event in group:
        team = str(event.get("team") or "")
        if not team:
            title = str(event.get("title") or "")
            if "德国" in title:
                team = "德国"
            elif "库拉索" in title:
                team = "库拉索"
        if team and team not in teams:
            teams.append(team)
    return "、".join(teams) if teams else "双方"


def _v4_3_multilingual(groups: list[list[dict[str, Any]]], final_score: str) -> list[str]:
    selected = groups[:8]
    lines = ["### 中文", "", "```text", "【Opening】", "\"各位球迷朋友，德国对阵库拉索，关键片段马上开始！\""]
    for index, group in enumerate(selected, start=1):
        lines.append(f"【事件 {index} - {_display_minute(group[0])}】")
        lines.append(f"\"{_v4_3_group_script(group)}\"")
    lines.extend([f"【Closing】", f"\"终场比分定格在 {final_score}，这条时间线把关键进攻和比分变化串成完整脉络。\"", "```", ""])
    lines.extend(["### English", "", "```text", "[Opening]", '"Germany and Curacao meet in a fast, physical World Cup match."'])
    for index, group in enumerate(selected, start=1):
        minute = _display_minute(group[0]).replace("第", "").replace("分钟", "'")
        if any(event.get("event_type") == "goal" for event in group):
            goal = next(event for event in group if event.get("event_type") == "goal")
            team = "Germany" if "德国" in str(goal.get("team") or goal.get("title") or "") else "Curacao"
            lines.append(f"[Goal {index} - {minute}]")
            lines.append(f'"{team} score, {goal.get("score_after") or ""}! The match bursts back into life."')
        else:
            lines.append(f"[Event {index} - {minute}]")
            lines.append('"Another key passage raises the tempo."')
    lines.extend([f"[Closing]", f'"Final score: {final_score}."', "```", ""])
    lines.extend(["### Español", "", "```text", "[Apertura]", '"Alemania y Curazao se enfrentan en un partido intenso, con cada acción clave elevando el ritmo."'])
    for index, group in enumerate(selected, start=1):
        minute = _display_minute(group[0]).replace("第", "").replace("分钟", "'")
        if any(event.get("event_type") == "goal" for event in group):
            goal = next(event for event in group if event.get("event_type") == "goal")
            team = "Alemania" if "德国" in str(goal.get("team") or goal.get("title") or "") else "Curazao"
            lines.append(f"[Gol {index} - {minute}]")
            lines.append(f'"{team} marca, {goal.get("score_after") or ""}. El partido se enciende de inmediato."')
        else:
            lines.append(f"[Evento {index} - {minute}]")
            lines.append('"Otra acción clave acelera el ritmo del partido."')
    lines.extend([f"[Cierre]", f'"Marcador final: {final_score}."', "```", ""])
    lines.extend(["### Français", "", "```text", "[Ouverture]", '"Allemagne contre Curaçao, un match intense où chaque action clé hausse le rythme."'])
    for index, group in enumerate(selected, start=1):
        minute = _display_minute(group[0]).replace("第", "").replace("分钟", "'")
        if any(event.get("event_type") == "goal" for event in group):
            goal = next(event for event in group if event.get("event_type") == "goal")
            team = "Allemagne" if "德国" in str(goal.get("team") or goal.get("title") or "") else "Curaçao"
            lines.append(f"[But {index} - {minute}]")
            lines.append(f'"{team} marque, {goal.get("score_after") or ""}. Le match s’emballe aussitôt."')
        else:
            lines.append(f"[Action {index} - {minute}]")
            lines.append('"Une nouvelle séquence importante hausse le rythme du match."')
    lines.extend([f"[Clôture]", f'"Score final : {final_score}."', "```"])
    return lines


def _voiceover_time_range(start: int, end: int) -> str:
    return f"[{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}]"


def _v4_3_voiceover(groups: list[list[dict[str, Any]]], final_score: str, version_label: str = "V4.3") -> list[str]:
    selected = groups[:6]
    lines = ["### 60 秒精简版", "", "```text", "[00:00-00:05] 各位球迷朋友，德国对阵库拉索，关键片段马上开始！"]
    for index, group in enumerate(selected, start=1):
        start = index * 5
        end = start + 5
        lines.append(f"{_voiceover_time_range(start, end)} {_v4_3_short_line(group)}")
    close_start = (len(selected) + 1) * 5
    close_end = close_start + 5
    lines.extend([f"{_voiceover_time_range(close_start, close_end)} 终场比分 {final_score}，关键进攻脉络已经串起来。", "```", ""])
    lines.extend(["### 90 秒完整版", "", "```text", "[00:00-00:10] 各位球迷朋友，欢迎来到这段世界杯关键回合！"])
    for index, group in enumerate(selected, start=1):
        start = 10 + (index - 1) * 12
        end = start + 12
        lines.append(f"{_voiceover_time_range(start, end)} {_v4_3_group_script(group)}")
    lines.extend([f"[01:25-01:30] 比分定格在 {final_score}，这就是 {version_label} 的关键事件脉络。", "```"])
    return lines


def _v4_3_short_line(group: list[dict[str, Any]]) -> str:
    if any(event.get("event_type") == "goal" for event in group):
        goal = next(event for event in group if event.get("event_type") == "goal")
        return f"{_display_minute(goal)}，{goal.get('team') or '球队'}破门，{goal.get('score_after') or ''}！"
    return f"{_display_minute(group[0])}，{_v4_3_group_kind(group)}出现，比赛节奏继续升温！"


def _v4_3_subtitle_blocks(events: list[dict[str, Any]], final_score: str) -> list[str]:
    lines = [
        "### 5.1 详细时间轴字幕",
        "",
        "```text",
        "[00:00:00] 2026年世界杯：德国队 VS 库拉索队",
        "[00:00:05] 比赛开始，双方进入关键攻防阶段！",
    ]
    for event in events:
        timestamp = str(event.get("video_timestamp") or event.get("timestamp") or "00:00:00")
        lines.append(f"[{timestamp}] [{_event_kind_cn(str(event.get('event_type') or ''))}] {_sanitize_identity_text(str(event.get('title') or '关键事件'))}")
    lines.extend([f"[终场] 比分定格在 {final_score}", "```", "", "### 5.2 精简版字幕", "", "```text"])
    for event in events[:12]:
        lines.append(f"[{_display_minute(event)}] {_event_kind_cn(str(event.get('event_type') or ''))}：{_sanitize_identity_text(str(event.get('title') or '关键事件'))}")
    lines.append("```")
    return lines


def _v4_3_highlight_script(groups: list[list[dict[str, Any]]], final_score: str, version_label: str = "V4.3") -> list[str]:
    selected = groups[:6]
    lines = [
        "```text",
        "（背景音乐：轻快的体育音乐）",
        "",
        "【开场（0:00-0:20）】",
        f"\"各位球迷朋友，今天我们回看德国队与库拉索队这场节奏拉满的比赛。{version_label} 版本用记分牌跳变锁定进球，再把其他关键画面串成解说节点。\"",
        "",
    ]
    for index, group in enumerate(selected, start=1):
        start = 20 + (index - 1) * 25
        end = start + 25
        lines.extend([f"【事件{_cn_index(index)}（{start//60}:{start%60:02d}-{end//60}:{end%60:02d}）】", f"\"{_v4_3_group_script(group)}\"", ""])
    lines.extend(["【总结（2:45-3:00）】", f"\"终场比分 {final_score}，进球链路以 OCR 跳变为准，后续剪辑可以围绕这些确认节点展开。\"", "```"])
    return lines


def _v4_3_stats_table(events: list[dict[str, Any]]) -> list[str]:
    teams = ["德国", "库拉索"]
    stats = {team: {"goal": 0, "shot": 0, "corner": 0, "free_kick": 0, "foul": 0, "substitution": 0} for team in teams}
    for event in events:
        text = f"{event.get('team') or ''} {event.get('title') or ''} {event.get('evidence') or ''}"
        team = "库拉索" if "库拉索" in text and "德国" not in str(event.get("team") or "") else "德国" if "德国" in text else None
        if team not in stats:
            continue
        event_type = str(event.get("event_type") or "")
        if event_type == "goal":
            stats[team]["goal"] += 1
            stats[team]["shot"] += 1
        elif event_type == "shot_chance":
            stats[team]["shot"] += 1
        elif event_type == "corner":
            stats[team]["corner"] += 1
        elif event_type == "free_kick":
            stats[team]["free_kick"] += 1
        elif event_type == "foul_card_dispute":
            stats[team]["foul"] += 1
        elif event_type == "substitution":
            stats[team]["substitution"] += 1
    return [
        "| 统计指标 | 德国队 | 库拉索队 | 说明 |",
        "|---|---:|---:|---|",
        f"| 进球 | {stats['德国']['goal']}次 | {stats['库拉索']['goal']}次 | 仅按记分牌 OCR 跳变确认 |",
        f"| 射门/机会 | {stats['德国']['shot']}次 | {stats['库拉索']['shot']}次 | 包含进球和保留的射门机会 |",
        f"| 角球 | {stats['德国']['corner']}次 | {stats['库拉索']['corner']}次 | 来自视觉事件识别 |",
        f"| 任意球 | {stats['德国']['free_kick']}次 | {stats['库拉索']['free_kick']}次 | 来自视觉事件识别 |",
        f"| 犯规/争议 | {stats['德国']['foul']}次 | {stats['库拉索']['foul']}次 | 来自视觉事件识别 |",
        f"| 换人 | {stats['德国']['substitution']}次 | {stats['库拉索']['substitution']}次 | 来自视觉事件识别 |",
    ]


def _v4_3_final_score(events: list[dict[str, Any]], match_info: dict[str, Any]) -> str:
    for event in reversed(events):
        score = event.get("score_after")
        if score:
            return str(score)
    return str(match_info.get("expected_score") or "未知")


def _v4_5_event_team_name(event: dict[str, Any]) -> str:
    text = f"{event.get('team') or ''} {event.get('title') or ''} {event.get('evidence') or ''}"
    if "库拉索" in text:
        return "库拉索队"
    if "德国" in text:
        return "德国队"
    team = str(event.get("team") or "").strip()
    return team or "进攻方"


def _v4_5_broadcast_detail(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    if event_type == "goal":
        return "比分已经被记分牌锁定，现场气势被这一球彻底带起来。"
    description = _v4_3_description(event)
    if not description:
        return ""
    blocked_terms = ("OCR", "ocr", "记分牌比分", "跳变前", "跳变后", "比赛钟", "scoreboard")
    parts = [part.strip() for part in re.split(r"[；;]", description) if part.strip()]
    parts = [part for part in parts if not any(term in part for term in blocked_terms)]
    text = "；".join(parts[:2]).strip() if parts else description
    if text and not text.endswith(("。", "！", "？")):
        text += "。"
    return text


def _v4_3_description(event: dict[str, Any]) -> str:
    evidence = event.get("evidence")
    if isinstance(evidence, list) and evidence:
        text = "；".join(str(item) for item in evidence[:2])
    elif evidence:
        text = str(evidence)
    else:
        text = str(event.get("script_angle") or "")
    return _sanitize_identity_text(text).strip()


def _event_kind_cn(kind: str) -> str:
    return {
        "goal": "进球",
        "penalty": "点球",
        "shot_chance": "射门机会",
        "corner": "角球",
        "free_kick": "任意球",
        "foul_card_dispute": "犯规/争议",
        "offside": "越位",
        "substitution": "换人",
        "celebration": "庆祝",
        "half_full_time": "半场/全场",
        "fulltime": "全场",
        "foul": "犯规",
    }.get(kind, kind or "关键事件")


def _cn_index(index: int) -> str:
    digits = "零一二三四五六七八九十"
    if 0 <= index < len(digits):
        return digits[index]
    if index < 20:
        return "十" + digits[index - 10]
    return str(index)


def _prepare_v4_report_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events.sort(key=lambda event: (_event_video_seconds(event), str(event.get("event_id") or "")))
    for index, event in enumerate(events):
        ocr_match_clock = _extract_scoreboard_match_clock(event)
        if ocr_match_clock:
            event["match_time"] = _format_match_time_display(ocr_match_clock)
            event["match_time_source"] = "scoreboard_ocr"
            seconds = _match_time_to_seconds(ocr_match_clock)
            if seconds is not None:
                event["match_minute"] = seconds // 60
                event["stoppage_minute"] = 0
            continue

        if _looks_like_opening_seconds_misread(events, index):
            event["match_time"] = "第1分钟"
            event["match_minute"] = 1
            event["stoppage_minute"] = 0
            event["match_time_source"] = "corrected_scoreboard"
            continue

        raw_match_time = str(event.get("match_time") or "").strip()
        if _is_unknown_match_time(raw_match_time):
            inferred = _infer_match_time_from_neighbors(events, index)
            event["match_time"] = inferred or f"视频{event.get('video_timestamp') or event.get('timestamp') or ''}"
            event["match_time_source"] = "estimated" if inferred else "video_time"
            continue

        if _looks_like_video_timestamp_as_match_clock(event, raw_match_time):
            inferred = _infer_match_time_from_neighbors(events, index, max_distance=300, trusted_only=True)
            if inferred:
                event["match_time"] = inferred
                event["match_time_source"] = "corrected_from_scoreboard_neighbors"
                seconds = _match_time_to_seconds(inferred)
                if seconds is not None:
                    event["match_minute"] = seconds // 60
                    event["stoppage_minute"] = 0
                continue

        event["match_time"] = _format_match_time_display(raw_match_time)
    return events


def _extract_scoreboard_match_clock(event: dict[str, Any]) -> str | None:
    text_parts: list[str] = []
    for key in ("evidence", "description", "script_angle", "score_panel_summary", "visible_text"):
        value = event.get(key)
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        elif value:
            text_parts.append(str(value))
    text = " ".join(text_parts)
    if not text:
        return None
    patterns = [
        r"(?:比赛钟|比赛时间|比赛时钟|记分牌时间|比分牌时间)\s*[:：]?\s*(\d{1,3})\s*[:：]\s*([0-5]?\d)",
        r"(?:match\s*clock|game\s*clock|scoreboard\s*time)\s*[:：]?\s*(\d{1,3})\s*[:：]\s*([0-5]?\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    return None


def _event_video_seconds(event: dict[str, Any]) -> float:
    return timestamp_to_seconds(event.get("video_timestamp") or event.get("timestamp") or event.get("start"))


def _is_unknown_match_time(value: str) -> bool:
    return not value or value.lower() in {"unknown", "none", "null", "nan", "pre_match"}


def _looks_like_opening_seconds_misread(events: list[dict[str, Any]], index: int) -> bool:
    event = events[index]
    raw = str(event.get("match_time") or "").strip()
    match = re.fullmatch(r"(\d{1,2})'", raw)
    if not match:
        return False
    minute = int(match.group(1))
    if minute < 20:
        return False
    if str(event.get("period") or "") not in {"first_half", "unknown"}:
        return False
    current_video = _event_video_seconds(event)
    for later in events[index + 1 : index + 5]:
        later_raw = str(later.get("match_time") or "").strip()
        later_match = re.fullmatch(r"(\d{1,2})'", later_raw)
        if not later_match:
            continue
        later_video = _event_video_seconds(later)
        if later_video - current_video <= 180 and int(later_match.group(1)) <= 5:
            return True
    return False


def _looks_like_video_timestamp_as_match_clock(event: dict[str, Any], raw_match_time: str) -> bool:
    source = str(event.get("match_time_source") or "").lower()
    if source not in {"estimated", "narrative", "unknown", "video_time"}:
        return False
    match = re.fullmatch(r"(\d{1,3}):([0-5]\d)", raw_match_time.strip())
    if not match:
        return False
    video = str(event.get("video_timestamp") or event.get("timestamp") or "").strip()
    video_match = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):([0-5]\d)", video)
    if not video_match:
        return False
    return int(match.group(1)) == int(video_match.group(2)) and int(match.group(2)) == int(video_match.group(3))


def _infer_match_time_from_neighbors(
    events: list[dict[str, Any]],
    index: int,
    max_distance: float = 120,
    trusted_only: bool = False,
) -> str | None:
    current_video = _event_video_seconds(events[index])
    candidates: list[tuple[float, int]] = []
    for offset, other in enumerate(events):
        if offset == index:
            continue
        if trusted_only and str(other.get("match_time_source") or "").lower() not in {
            "scoreboard",
            "scoreboard_ocr",
            "corrected_scoreboard",
            "corrected_from_scoreboard_neighbors",
        }:
            continue
        match_seconds = _match_time_to_seconds(str(other.get("match_time") or ""))
        if match_seconds is None:
            continue
        video_seconds = _event_video_seconds(other)
        if abs(video_seconds - current_video) > max_distance:
            continue
        candidates.append((abs(video_seconds - current_video), int(match_seconds + current_video - video_seconds)))
    if not candidates:
        return None
    _, inferred_seconds = min(candidates, key=lambda item: item[0])
    return _format_match_seconds(max(0, inferred_seconds))


def _match_time_to_seconds(value: str) -> int | None:
    text = value.strip()
    if _is_unknown_match_time(text):
        return None
    if text.startswith("第"):
        text = text.removeprefix("第").replace("分钟", ":00").replace("分", ":").replace("秒", "")
    if re.fullmatch(r"\d{1,3}'", text):
        return int(text[:-1]) * 60
    plus_match = re.fullmatch(r"(\d{1,3})\+(\d{1,2})'?", text)
    if plus_match:
        return (int(plus_match.group(1)) + int(plus_match.group(2))) * 60
    clock_match = re.fullmatch(r"(\d{1,3}):(\d{1,2})", text)
    if clock_match:
        return int(clock_match.group(1)) * 60 + int(clock_match.group(2))
    minute_match = re.fullmatch(r"\d{1,3}", text)
    if minute_match:
        return int(text) * 60
    return None


def _format_match_time_display(value: str) -> str:
    text = value.strip()
    plus_match = re.fullmatch(r"(\d{1,3})\+(\d{1,2})'?", text)
    if plus_match:
        return f"第{plus_match.group(1)}+{plus_match.group(2)}分钟"
    if re.fullmatch(r"\d{1,3}'", text):
        return f"第{text[:-1]}分钟"
    clock_match = re.fullmatch(r"(\d{1,3}):(\d{1,2})", text)
    if clock_match:
        return _format_match_seconds(int(clock_match.group(1)) * 60 + int(clock_match.group(2)))
    if re.fullmatch(r"\d{1,3}", text):
        return f"第{text}分钟"
    return text


def _format_match_seconds(seconds: int, always_seconds: bool = False) -> str:
    minute = seconds // 60
    second = seconds % 60
    if second == 0 and not always_seconds:
        return f"第{minute}分钟"
    return f"第{minute}分{second:02d}秒"


def _enforce_v4_event_table(markdown: str, events: list[dict[str, Any]]) -> str:
    table_lines = [
        "# 事项列表",
        "",
        "| 序号 | 比赛时间 | 视频时间戳 | 事项类型 | 事件标题 | 确定性 | 证据摘要 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for index, event in enumerate(events, start=1):
        evidence = event.get("evidence")
        if isinstance(evidence, list):
            evidence_text = "；".join(str(item) for item in evidence[:2])
        else:
            evidence_text = str(evidence or "")
        values = [
            str(index),
            str(event.get("match_time") or ""),
            str(event.get("video_timestamp") or event.get("timestamp") or ""),
            str(event.get("event_type") or ""),
            str(event.get("title") or ""),
            str(event.get("certainty") or ""),
            evidence_text,
        ]
        cleaned_values = [_escape_markdown_cell(_sanitize_identity_text(value)) for value in values]
        table_lines.append("| " + " | ".join(cleaned_values) + " |")

    lines = markdown.splitlines()
    commentary_index = next((idx for idx, line in enumerate(lines) if line.strip() == "# 解说文案"), None)
    if commentary_index is None:
        return "\n".join(table_lines) + "\n\n# 解说文案\n\n" + "\n".join(lines).strip() + "\n"
    commentary_lines = lines[commentary_index:]
    return "\n".join(table_lines + [""] + commentary_lines).rstrip() + "\n"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _display_minute(event: dict[str, Any]) -> str:
    match_time = str(event.get("match_time") or "").strip()
    if match_time:
        if match_time.startswith("第"):
            if "分" in match_time and "分钟" not in match_time:
                minute = match_time.removeprefix("第").split("分", 1)[0]
                return f"第{minute}分钟"
            return match_time
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
