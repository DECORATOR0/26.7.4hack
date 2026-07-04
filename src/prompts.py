from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """你是一个足球比赛视频解说 Harness 中的核心模型。
你必须遵守：
1. 只能基于输入的比赛信息、证据摘要和关键帧进行判断。
2. 不确定球员姓名时，不要编造姓名，使用“德国队前锋”“库拉索防守球员”等角色描述。
3. 必须保持比分、时间顺序、进球数量一致。
4. 输出必须满足用户要求的格式。
5. 不要输出 Thinking Process、分析过程或推理草稿。"""


def compact_json(data: Any, limit: int = 18000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"


def event_extraction_prompt(evidence: dict[str, Any]) -> str:
    return f"""请基于以下视频证据，识别世界杯比赛的关键事件并构建时间线。

目标比赛：{compact_json(evidence.get("match_info", {}), 3000)}

证据摘要：
{compact_json(evidence, 16000)}

请输出严格 JSON，不要输出 Markdown，不要输出 Thinking Process 或解释文字。格式如下：
{{
  "match": {{
    "competition": "...",
    "home_team": "...",
    "away_team": "...",
    "final_score": "7-1"
  }},
  "events": [
    {{
      "event_id": "E01",
      "timestamp": "00:12:30",
      "minute": "12'",
      "event_type": "goal|shot|save|foul|card|substitution|highlight|opening|halftime|fulltime",
      "team": "德国|库拉索|unknown",
      "score_after": "1-0",
      "title": "简短标题",
      "description": "基于证据的事件描述",
      "evidence": ["frame path or transcript/audio clue"],
      "confidence": 0.0
    }}
  ],
  "uncertainties": [
    "哪些信息证据不足"
  ]
}}

要求：
- 最终比分必须与比赛信息一致。
- 如果无法从视频证据确认具体时间，可以给出估计时间，并在 uncertainties 中说明。
- 对于德国 7:1 库拉索，至少应包含 8 个进球事件，除非证据明确不足；证据不足时用低 confidence 标记。
- 不要编造球员姓名。"""


def commentary_prompt(match_info: dict[str, Any], events: dict[str, Any]) -> str:
    return f"""请基于以下关键事件时间线，生成可交付的世界杯视频解说输出。

比赛信息：
{compact_json(match_info, 3000)}

关键事件：
{compact_json(events, 20000)}

输出 Markdown，包含以下部分：

# 世界杯视频解说脚本

## 一、文档说明
- 比赛
- 最终比分
- 生成方式说明：基于 Harness 的关键事件时间线生成

## 二、完整解说脚本（激情风格）
按照开场、上半场、下半场、赛后总结组织。每个关键事件给出时间段、情绪提示、解说台词。

## 三、关键事件时间线
用 Markdown 表格列出：序号、时间、事件类型、球队、比分、事件描述、证据/置信度。

## 四、60 秒集锦解说
适合短视频配音，节奏紧凑。

## 五、字幕/配音使用建议
说明如何配合 subtitles.srt 和 highlights.json 使用。

硬性要求：
- 不得新增 events 中不存在的进球。
- 不得编造具体球员姓名。
- 最终比分必须保持一致。
- 风格要有现场感，但不能牺牲事实一致性。"""


def fact_check_prompt(match_info: dict[str, Any], events: dict[str, Any], commentary: str) -> str:
    return f"""请审查下面的世界杯解说输出是否与关键事件一致。

比赛信息：
{compact_json(match_info, 3000)}

关键事件：
{compact_json(events, 12000)}

解说稿：
{commentary[:16000]}

请输出严格 JSON，不要输出 Markdown，不要输出 Thinking Process 或解释文字：
{{
  "passed": true,
  "issues": [
    {{
      "severity": "low|medium|high",
      "type": "score|event_order|hallucinated_player|missing_event|style|other",
      "description": "问题说明"
    }}
  ],
  "summary": "总体评价",
  "intern_s2_limitations": [
    "本任务中模型能力不足或提升空间"
  ]
}}"""
