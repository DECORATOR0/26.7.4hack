from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io_utils import seconds_to_timestamp, timestamp_to_seconds, write_json, write_text


def parse_score(score: str | None) -> tuple[int, int]:
    if not score:
        return (0, 0)
    match = re.search(r"(\d+)\s*[-:：]\s*(\d+)", str(score))
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def fallback_events(match_info: dict[str, Any], duration_seconds: float = 0.0) -> dict[str, Any]:
    home = match_info.get("home_team", "德国")
    away = match_info.get("away_team", "库拉索")
    home_goals, away_goals = parse_score(match_info.get("expected_score", "7-1"))
    total_goals = max(1, home_goals + away_goals)
    start = 8 * 60
    end = duration_seconds - 8 * 60 if duration_seconds and duration_seconds > 30 * 60 else 88 * 60
    step = max(240.0, (end - start) / total_goals)

    events = []
    home_score = 0
    away_score = 0
    goal_plan = [home] * home_goals + [away] * away_goals
    if away_goals == 1 and len(goal_plan) > 3:
        goal_plan.insert(2, goal_plan.pop())
    for idx, team in enumerate(goal_plan, start=1):
        if team == home:
            home_score += 1
        else:
            away_score += 1
        ts = start + (idx - 1) * step
        events.append(
            {
                "event_id": f"E{idx:02d}",
                "timestamp": seconds_to_timestamp(ts),
                "minute": f"{max(1, int(ts // 60))}'",
                "event_type": "goal",
                "team": team,
                "score_after": f"{home_score}-{away_score}",
                "title": f"{team}进球，比分来到 {home_score}-{away_score}",
                "description": "自动兜底时间线：视频证据不足以确认具体动作，按题面最终比分生成低置信度进球节点，用于驱动解说脚本生成。",
                "evidence": ["fallback_from_match_info"],
                "confidence": 0.25,
            }
        )

    return {
        "match": {
            "competition": match_info.get("competition"),
            "home_team": home,
            "away_team": away,
            "final_score": match_info.get("expected_score", "7-1"),
        },
        "events": events,
        "uncertainties": [
            "未能从 ASR/OCR/视觉证据中稳定确认全部进球细节，已基于题面比分生成低置信度兜底时间线。"
        ],
    }


def normalize_events(events_data: dict[str, Any], match_info: dict[str, Any]) -> dict[str, Any]:
    events = events_data.get("events") or []
    normalized = []
    for idx, item in enumerate(events, start=1):
        timestamp = item.get("timestamp") or item.get("time") or item.get("minute") or "00:00:00"
        seconds = timestamp_to_seconds(timestamp)
        normalized.append(
            {
                "event_id": item.get("event_id") or f"E{idx:02d}",
                "timestamp": seconds_to_timestamp(seconds),
                "timestamp_seconds": round(seconds, 3),
                "minute": item.get("minute") or f"{int(seconds // 60)}'",
                "event_type": item.get("event_type") or "highlight",
                "team": item.get("team") or "unknown",
                "score_after": item.get("score_after") or "",
                "title": item.get("title") or item.get("description", "")[:30],
                "description": item.get("description") or "",
                "evidence": item.get("evidence") or [],
                "confidence": float(item.get("confidence", 0.5) or 0.5),
            }
        )
    normalized.sort(key=lambda x: x["timestamp_seconds"])
    match = events_data.get("match") or {}
    match.setdefault("competition", match_info.get("competition"))
    match.setdefault("home_team", match_info.get("home_team", "德国"))
    match.setdefault("away_team", match_info.get("away_team", "库拉索"))
    match.setdefault("final_score", match_info.get("expected_score", "7-1"))
    return {
        "match": match,
        "events": normalized,
        "uncertainties": events_data.get("uncertainties", []),
    }


def local_fact_check(match_info: dict[str, Any], events_data: dict[str, Any], commentary: str) -> dict[str, Any]:
    issues = []
    expected_home, expected_away = parse_score(match_info.get("expected_score", "7-1"))
    goal_events = [e for e in events_data.get("events", []) if e.get("event_type") == "goal"]
    home = match_info.get("home_team", "德国")
    away = match_info.get("away_team", "库拉索")
    home_goals = sum(1 for e in goal_events if e.get("team") == home)
    away_goals = sum(1 for e in goal_events if e.get("team") == away)
    if home_goals != expected_home or away_goals != expected_away:
        issues.append(
            {
                "severity": "high",
                "type": "score",
                "description": f"进球事件数量为 {home_goals}-{away_goals}，期望 {expected_home}-{expected_away}。",
            }
        )
    timestamps = [e.get("timestamp_seconds", 0.0) for e in events_data.get("events", [])]
    if timestamps != sorted(timestamps):
        issues.append(
            {
                "severity": "medium",
                "type": "event_order",
                "description": "事件时间线不是递增顺序。",
            }
        )
    expected_score = match_info.get("expected_score", "7-1")
    if expected_score not in commentary and expected_score.replace("-", ":") not in commentary:
        issues.append(
            {
                "severity": "medium",
                "type": "score",
                "description": "解说稿中没有明确出现最终比分。",
            }
        )
    return {
        "passed": not any(item["severity"] == "high" for item in issues),
        "issues": issues,
    }


def write_srt(path: Path, events_data: dict[str, Any]) -> None:
    entries = []
    events = events_data.get("events", [])
    for idx, event in enumerate(events, start=1):
        start = timestamp_to_seconds(event.get("timestamp")) - 4
        end = start + 8
        text = event.get("title") or event.get("description") or "关键事件"
        score = event.get("score_after")
        if score:
            text = f"{text}（比分 {score}）"
        entries.append(
            f"{idx}\n{seconds_to_timestamp(start, srt=True)} --> {seconds_to_timestamp(end, srt=True)}\n{text}\n"
        )
    write_text(path, "\n".join(entries))


def write_highlights(path: Path, events_data: dict[str, Any]) -> None:
    highlights = []
    for event in events_data.get("events", []):
        if event.get("event_type") not in {"goal", "shot", "save", "highlight"}:
            continue
        center = timestamp_to_seconds(event.get("timestamp"))
        highlights.append(
            {
                "event_id": event.get("event_id"),
                "start": seconds_to_timestamp(max(0, center - 25)),
                "end": seconds_to_timestamp(center + 35),
                "title": event.get("title"),
                "commentary_hint": event.get("description"),
                "confidence": event.get("confidence"),
            }
        )
    write_json(path, highlights)


def fallback_commentary(match_info: dict[str, Any], events_data: dict[str, Any]) -> str:
    home = match_info.get("home_team", "德国")
    away = match_info.get("away_team", "库拉索")
    score = match_info.get("expected_score", "7-1")
    lines = [
        "# 世界杯视频解说脚本",
        "",
        "## 一、文档说明",
        f"- 比赛：{match_info.get('competition', '')}，{home} vs {away}",
        f"- 最终比分：{home} {score} {away}",
        "- 生成方式说明：由 Harness 基于关键事件时间线自动生成。",
        "",
        "## 二、完整解说脚本（激情风格）",
        "",
        f"各位球迷朋友，欢迎来到这场{match_info.get('competition', '世界杯比赛')}的解说现场！{home}迎战{away}，这是一场节奏鲜明、攻势不断的比赛。",
        "",
    ]
    for event in events_data.get("events", []):
        lines.extend(
            [
                f"### {event.get('minute', '')} {event.get('title', '关键事件')}",
                "",
                f"比赛来到 {event.get('minute', '')}，{event.get('description', '')} 当前比分 {event.get('score_after', '')}。这一刻彻底点燃了比赛节奏，也为后续走势埋下伏笔。",
                "",
            ]
        )
    lines.extend(
        [
            "## 三、关键事件时间线",
            "",
            "| 序号 | 时间 | 类型 | 球队 | 比分 | 描述 | 置信度 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for idx, event in enumerate(events_data.get("events", []), start=1):
        lines.append(
            f"| {idx} | {event.get('timestamp')} | {event.get('event_type')} | {event.get('team')} | {event.get('score_after')} | {event.get('description')} | {event.get('confidence')} |"
        )
    lines.extend(
        [
            "",
            "## 四、60 秒集锦解说",
            "",
            f"{home}用一场 {score} 的胜利展示了强大的进攻火力。多个进球节点串联起比赛主线，{away}虽然努力寻找机会，但最终未能阻挡对手扩大比分。",
            "",
            "## 五、字幕/配音使用建议",
            "",
            "可将 `subtitles.srt` 挂载到原视频或集锦片段；`highlights.json` 可作为剪辑起止时间参考。",
        ]
    )
    return "\n".join(lines)

