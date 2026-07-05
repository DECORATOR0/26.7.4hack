from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
import qrcode
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web_demo"
ASSETS = WEB / "assets"
CLIPS = ASSETS / "clips"
DATA = WEB / "data"
SOURCE = ASSETS / "source_match.mp4"
ALIGNMENT_OVERRIDES_PATH = ROOT / "docs" / "web_clip_alignment_overrides_v4_5.json"
REPORT_CANDIDATES = [
    ROOT / "outputs_script_report_v4_5" / "final_report_v4_5_items.md",
    ROOT / "outputs_script_report_v4_4" / "final_report_v4_4.md",
    ROOT / "outputs_script_report_v4_3" / "final_report_v4_3.md",
    ROOT / "outputs_script_report_v4_2" / "final_report_v4_2.md",
]
REPORT_PATH = next((path for path in REPORT_CANDIDATES if path.exists()), REPORT_CANDIDATES[0])
FULL_REPORT_CANDIDATES = [
    ROOT / "outputs_script_report_v4_5" / "final_report_v4_5.md",
    ROOT / "outputs_script_report_v4_4" / "final_report_v4_4.md",
    REPORT_PATH,
]
FULL_REPORT_PATH = next((path for path in FULL_REPORT_CANDIDATES if path.exists()), REPORT_PATH)
EVENTS_CANDIDATES = [
    ROOT / "outputs_event_agent_v4_5" / "final_events_guarded_v4_5.json",
    ROOT / "outputs_event_agent_v4_4_text" / "final_events_guarded_v4.json",
    ROOT / "outputs_event_agent_v4_4" / "final_events_guarded_v4_4.json",
    ROOT / "outputs_event_agent_v4_3_2" / "final_events_guarded_v4_3_2.json",
    ROOT / "outputs_event_agent_v4_3" / "final_events_guarded_v4_3.json",
    ROOT / "outputs_event_agent_v4_2" / "final_events_guarded_v4.json",
]
EVENTS_PATH = next((path for path in EVENTS_CANDIDATES if path.exists()), EVENTS_CANDIDATES[0])
SCOREBOARD_GOAL_CANDIDATES = [
    ROOT / "outputs_event_agent_v4_5" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_5_seed" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_4_seed" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_4" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_3_2" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_3" / "scoreboard_goal_events.json",
]
SCOREBOARD_GOALS_PATH = next((path for path in SCOREBOARD_GOAL_CANDIDATES if path.exists()), SCOREBOARD_GOAL_CANDIDATES[0])
PUBLIC_URL = "http://39.105.210.249/"
VERSION_SOURCE = EVENTS_PATH.as_posix() + " " + REPORT_PATH.as_posix()
VERSION = "v4.5" if "v4_5" in VERSION_SOURCE else ("v4.3.2" if "v4_3_2" in VERSION_SOURCE else ("v4.4" if "v4_4" in VERSION_SOURCE else ("v4.3" if "v4_3" in VERSION_SOURCE else "v4.2")))
VERSION_LABEL = VERSION.upper()
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


TYPE_LABELS = {
    "goal": "进球",
    "shot_chance": "射门机会",
    "corner": "角球",
    "free_kick": "任意球",
    "foul_card_dispute": "判罚争议",
    "substitution": "换人",
}

TYPE_ORDER = [
    "goal",
    "shot_chance",
    "corner",
    "free_kick",
    "foul_card_dispute",
    "substitution",
]

WEB_RETAINED_EVENT_TYPES = set(TYPE_ORDER)
INTERNAL_COMMENTARY_TERMS = (
    "OCR",
    "ocr",
    "记分牌比分",
    "比分跳变",
    "跳变前",
    "跳变后",
    "比赛钟",
    "确认依据",
    "这个节点由",
    "该进球以",
    "scoreboard",
)


def timestamp_to_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    parts = str(value).strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(value)


def seconds_to_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}"


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-y", *args], check=True)


def load_font(size: int) -> ImageFont.ImageFont:
    for font_path in [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for char in text:
        candidate = line + char
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = char
            if len(lines) >= max_lines:
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines


def _strip_quote(text: str) -> str:
    return text.strip().strip("\"“”")


def has_internal_commentary_terms(text: str) -> bool:
    return any(term in text for term in INTERNAL_COMMENTARY_TERMS)


def clean_commentary_script(text: str) -> str:
    cleaned = _strip_quote(str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("比分已经被记分牌锁定，现场气势被这一球彻底带起来。", "现场气势被这一球彻底带起来。")
    cleaned = re.sub(r"这个节点由记分牌比分跳变确认[。.!！]?", "", cleaned)
    cleaned = re.sub(r"该进球以记分牌比分跳变作为确认依据[。.!！]?", "", cleaned)
    if not has_internal_commentary_terms(cleaned):
        return cleaned

    sentences = re.findall(r"[^。！？!?]+[。！？!?]?", cleaned)
    kept = [sentence.strip() for sentence in sentences if sentence.strip() and not has_internal_commentary_terms(sentence)]
    return "".join(kept).strip()


def _extract_speaker_script(block: str) -> str:
    match = re.search(r"解说员：\s*\n[“\"](?P<script>.*?)[”\"]", block, re.S)
    if not match:
        match = re.search(r"[“\"](?P<script>.*?)[”\"]", block, re.S)
    return clean_commentary_script(match.group("script")) if match else ""


def _extract_report_blocks(text: str, start_heading: str, end_heading: str, marker_pattern: str) -> list[dict]:
    start = text.find(start_heading)
    if start < 0:
        return []
    end = text.find(end_heading, start + len(start_heading)) if end_heading else -1
    section = text[start + len(start_heading) : end if end >= 0 else len(text)]
    blocks: list[dict] = []
    for match in re.finditer(marker_pattern, section, re.M | re.S):
        heading = match.group("heading").strip()
        script = _extract_speaker_script(match.group("body"))
        if heading and script:
            blocks.append({"heading": heading, "script": script})
    return blocks


def _match_minute_number(value: str | None) -> int | None:
    match = re.search(r"第\s*(\d+)(?:\+\d+)?\s*分", str(value or ""))
    return int(match.group(1)) if match else None


def _report_block_matches(event: dict, block: dict) -> bool:
    heading = block.get("heading") or ""
    title = display_title(event)
    score = event.get("score_after") or _score_from_title(title)
    if title and title in heading:
        return True
    if event.get("event_type") == "goal" and score and score in heading:
        return True
    return False


def _map_report_blocks_to_events(events: list[dict], blocks: list[dict]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    cursor = 0
    for event in events:
        matches = [idx for idx in range(cursor, len(blocks)) if _report_block_matches(event, blocks[idx])]
        if not matches:
            matches = [idx for idx, block in enumerate(blocks) if _report_block_matches(event, block)]
        if not matches:
            continue

        event_minute = _match_minute_number(event.get("match_time"))
        minute_matches = [idx for idx in matches if _match_minute_number(blocks[idx].get("heading")) == event_minute]
        chosen = minute_matches[0] if minute_matches else matches[0]
        mapped[event["event_id"]] = blocks[chosen]["script"]
        cursor = chosen
    return mapped


def attach_full_report_scripts(events: list[dict]) -> None:
    if not FULL_REPORT_PATH.exists() or FULL_REPORT_PATH == REPORT_PATH and "items" in REPORT_PATH.stem:
        return
    text = FULL_REPORT_PATH.read_text(encoding="utf-8")
    passionate_blocks = _extract_report_blocks(
        text,
        "### 关键进程",
        "### 平实风格解说稿",
        r"^####\s+(?P<heading>.*?)\n(?P<body>.*?)(?=^####\s+|\Z)",
    )
    steady_blocks = _extract_report_blocks(
        text,
        "### 平实风格解说稿",
        "\n---",
        r"^-\s+(?P<heading>.*?)\n(?P<body>.*?)(?=^-\s+|\Z)",
    )
    passionate = _map_report_blocks_to_events(events, passionate_blocks)
    steady = _map_report_blocks_to_events(events, steady_blocks)
    for event in events:
        variants: dict[str, dict] = {}
        if passionate.get(event["event_id"]):
            variants.setdefault("zh-CN", {})["passionate"] = passionate[event["event_id"]]
            event["script"] = passionate[event["event_id"]]
        if steady.get(event["event_id"]):
            variants.setdefault("zh-CN", {})["steady"] = steady[event["event_id"]]
        if variants:
            event["script_variants"] = variants


def parse_report(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    rows: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 7 or cells[0] in {"序号", ":---"}:
            continue
        if not cells[0].isdigit():
            continue
        event_type = cells[3]
        if event_type not in WEB_RETAINED_EVENT_TYPES:
            continue
        index = len(rows) + 1
        rows.append(
            {
                "event_id": f"F{index:04d}",
                "match_time": cells[1],
                "video_timestamp": cells[2],
                "event_type": event_type,
                "title": cells[4],
                "certainty": cells[5],
                "evidence": cells[6],
            }
        )

    commentary = text.split("# 解说文案", 1)[1] if "# 解说文案" in text else ""
    blocks = re.split(r"(?m)^##\s+", commentary)
    scripts: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        parts = block.splitlines()
        body = "\n".join(line.strip() for line in parts[1:] if line.strip())
        scripts.append(body)

    for idx, row in enumerate(rows):
        row["script"] = scripts[idx] if idx < len(scripts) else row["evidence"]
    attach_full_report_scripts(rows)
    return rows


def assert_guarded_events_match(report_events: list[dict]) -> None:
    if "items" in REPORT_PATH.stem:
        return
    guarded_doc = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    guarded_events = guarded_doc.get("final_events") or []
    if len(guarded_events) != len(report_events):
        raise ValueError(f"Report events={len(report_events)} but guarded events={len(guarded_events)}")
    report_ids = [event["event_id"] for event in report_events]
    guarded_ids = [event.get("event_id") for event in guarded_events]
    if report_ids != guarded_ids:
        raise ValueError("Report event ids do not match guarded event ids")


def load_scoreboard_goals() -> list[dict]:
    if not SCOREBOARD_GOALS_PATH.exists():
        return []
    data = json.loads(SCOREBOARD_GOALS_PATH.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("scoreboard_goal_events") or data.get("events") or []


def load_clip_alignment_overrides() -> dict[str, dict]:
    if not ALIGNMENT_OVERRIDES_PATH.exists():
        return {}
    data = json.loads(ALIGNMENT_OVERRIDES_PATH.read_text(encoding="utf-8"))
    overrides = data.get("overrides") if isinstance(data, dict) else data
    if not isinstance(overrides, list):
        return {}
    return {str(item.get("event_id")): item for item in overrides if item.get("event_id")}


def apply_scoreboard_goal_overrides(events: list[dict], scoreboard_goals: list[dict]) -> list[dict]:
    if not scoreboard_goals:
        return events
    goal_by_id = {goal.get("event_id"): goal for goal in scoreboard_goals if goal.get("event_id")}
    merged: list[dict] = []
    for event in events:
        override = goal_by_id.get(event.get("event_id"))
        if override:
            updated = {**event, **override}
            merged.append(updated)
        else:
            merged.append(event)
    return merged


def load_source_events(scoreboard_goals: list[dict]) -> list[dict]:
    if "v4_3_2" in EVENTS_PATH.as_posix():
        guarded_doc = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
        guarded_events = guarded_doc.get("final_events") or []
        return apply_scoreboard_goal_overrides(guarded_events, scoreboard_goals)

    report_events = parse_report(REPORT_PATH)
    assert_guarded_events_match(report_events)
    return report_events


def event_text(value: object) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item)
    return str(value or "")


def display_title(event: dict) -> str:
    title = event.get("title") or ""
    if event.get("event_type") == "goal" and "team goal" in title and event.get("team") and event.get("score_after"):
        return f"{event.get('team')}队进球，比分变为{event.get('score_after')}"
    return title


def display_script(event: dict, evidence_text: str) -> str:
    script = clean_commentary_script(event_text(event.get("script") or event.get("script_angle") or ""))
    if script:
        return script
    if event.get("event_type") == "goal":
        return zh_goal_script(event, display_title(event), passionate=False)
    return event_text(evidence_text)


def infer_team(event: dict) -> str:
    text = f"{event.get('team') or ''} {event.get('title') or ''} {event.get('evidence') or ''}"
    if "库拉索" in text:
        return "库拉索"
    if "德国" in text:
        return "德国"
    return str(event.get("team") or "")


def zh_goal_script(event: dict, title: str, *, passionate: bool) -> str:
    match_time = event.get("match_time") or "比赛中"
    team = infer_team(event) or "进攻方"
    score = event.get("score_after") or _score_from_title(title)
    if passionate:
        return f"{match_time}，漂亮！球进了！{title}！{f'比分来到 {score}，' if score else ''}现场气势被这一球彻底带起来。"
    return f"{match_time}，{team}队完成进球{f'，比分来到 {score}' if score else ''}。比赛走势随之改变，现场节奏被这一球带起来。"


def zh_generated_script(event: dict, title: str, *, style: str) -> str:
    event_type = event.get("event_type") or ""
    match_time = event.get("match_time") or "比赛中"
    team = infer_team(event) or "场上球队"
    if event_type == "goal":
        return zh_goal_script(event, title, passionate=style == "passionate")
    if event_type == "shot_chance":
        if style == "passionate":
            return f"{match_time}，攻势来了！{title}。这次射门把比赛节奏再次推高。"
        return f"{match_time}，场上出现一次射门机会，防守方完成处理。"
    if event_type in {"corner", "free_kick"}:
        if style == "passionate":
            return f"{match_time}，定位球机会来了！{title}。禁区里的站位开始紧张起来。"
        return f"{match_time}，{team}获得定位球机会，双方开始重新布置站位。"
    if event_type == "foul_card_dispute":
        if style == "passionate":
            return f"{match_time}，裁判哨声让比赛短暂停住！{title}。"
        return f"{match_time}，裁判处理一次判罚争议，比赛节奏短暂停顿。"
    if event_type == "substitution":
        if style == "passionate":
            return f"{match_time}，场边开始调整！{title}。球队试图通过换人改变后续节奏。"
        return f"{match_time}，出现换人调整，球队为后续比赛重新安排人员。"
    return event_text(event.get("script") or title)


def localized_match_time(value: str | None, lang: str) -> str:
    text = str(value or "")
    match = re.search(r"第\s*(\d+)(?:\+\d+)?\s*分(?:钟)?(?:(\d+)\s*秒)?", text)
    if not match:
        return text if lang == "zh-CN" else text.replace("第", "").replace("分", ":").replace("秒", "")
    minute = int(match.group(1))
    second = match.group(2)
    if lang == "zh-CN":
        return text
    if second is not None:
        return f"{minute}:{int(second):02d}"
    return f"{minute}'"


def localized_team_name(team: str, lang: str) -> str:
    normalized = team or ""
    names = {
        "en": {"德国": "Germany", "库拉索": "Curacao", "": "the attacking side"},
        "es": {"德国": "Alemania", "库拉索": "Curazao", "": "el equipo atacante"},
        "fr": {"德国": "l'Allemagne", "库拉索": "Curaçao", "": "l'équipe en attaque"},
    }
    if lang == "zh-CN":
        return normalized or "进攻方"
    table = names.get(lang, names["en"])
    for key, value in table.items():
        if key and key in normalized:
            return value
    return table[""]


def localized_script(event: dict, title: str, lang: str, style: str) -> str:
    event_type = event.get("event_type") or ""
    time = localized_match_time(event.get("match_time"), lang)
    team = localized_team_name(infer_team(event), lang)
    score = event.get("score_after") or _score_from_title(title)
    lively = style == "passionate"

    if lang == "en":
        if event_type == "goal":
            return f"{time} - Goal! {team} make it {score}, and the match bursts back into life." if lively else f"{time} - {team} score{f' to make it {score}' if score else ''}. The rhythm changes immediately."
        if event_type == "shot_chance":
            return f"{time} - A shooting chance opens for {team}; the defense has to react." if lively else f"{time} - {team} create a shooting chance, but the defense deals with it."
        if event_type == "corner":
            return f"{time} - Corner for {team}; the penalty area starts to fill up." if lively else f"{time} - {team} have a corner and both sides reset their positions."
        if event_type == "free_kick":
            return f"{time} - Free kick for {team}; this set piece can shift the momentum." if lively else f"{time} - {team} have a free-kick situation and the defensive shape resets."
        if event_type == "foul_card_dispute":
            return f"{time} - The referee steps in after a contested challenge, and the tempo tightens." if lively else f"{time} - The referee handles a dispute and play pauses briefly."
        if event_type == "substitution":
            return f"{time} - Changes on the touchline as the teams try to reshape the next phase." if lively else f"{time} - A substitution sequence appears on the touchline."
        return f"{time} - A key passage raises the tempo."

    if lang == "es":
        if event_type == "goal":
            return f"{time} - ¡Gol! {team} pone el {score} y el partido se enciende." if lively else f"{time} - {team} marca{f' para el {score}' if score else ''}. El ritmo cambia de inmediato."
        if event_type == "shot_chance":
            return f"{time} - Ocasión de tiro para {team}; la defensa tiene que responder." if lively else f"{time} - {team} genera una ocasión de tiro, pero la defensa la resuelve."
        if event_type == "corner":
            return f"{time} - Córner para {team}; el área empieza a cargarse." if lively else f"{time} - {team} dispone de un córner y ambos equipos se reordenan."
        if event_type == "free_kick":
            return f"{time} - Tiro libre para {team}; la jugada puede cambiar el impulso." if lively else f"{time} - {team} tiene una acción de tiro libre y la defensa se coloca."
        if event_type == "foul_card_dispute":
            return f"{time} - El árbitro interviene tras una acción discutida y sube la tensión." if lively else f"{time} - El árbitro gestiona una disputa y el juego se pausa brevemente."
        if event_type == "substitution":
            return f"{time} - Movimiento en la banda: llegan cambios para ajustar el tramo siguiente." if lively else f"{time} - Aparece una secuencia de sustitución en la banda."
        return f"{time} - Una acción clave acelera el ritmo del partido."

    if lang == "fr":
        if event_type == "goal":
            return f"{time} - But ! {team} passe à {score} et le match s'emballe." if lively else f"{time} - {team} marque{f' pour porter le score à {score}' if score else ''}. Le rythme change aussitôt."
        if event_type == "shot_chance":
            return f"{time} - Occasion de tir pour {team}; la défense doit réagir." if lively else f"{time} - {team} se crée une occasion de tir, mais la défense s'en sort."
        if event_type == "corner":
            return f"{time} - Corner pour {team}; la surface commence à se remplir." if lively else f"{time} - {team} obtient un corner et les deux blocs se replacent."
        if event_type == "free_kick":
            return f"{time} - Coup franc pour {team}; ce ballon arrêté peut faire basculer le rythme." if lively else f"{time} - {team} obtient un coup franc et la défense se replace."
        if event_type == "foul_card_dispute":
            return f"{time} - L'arbitre intervient après une action contestée, la tension monte." if lively else f"{time} - L'arbitre gère une action litigieuse et le jeu marque une pause."
        if event_type == "substitution":
            return f"{time} - Ça bouge sur la ligne de touche, les équipes réajustent la suite." if lively else f"{time} - Une séquence de remplacement apparaît sur la ligne de touche."
        return f"{time} - Une séquence importante hausse le rythme du match."

    return zh_generated_script(event, title, style=style)


def copy_variants(event: dict, title: str, evidence_text: str) -> dict:
    zh_variants = (event.get("script_variants") or {}).get("zh-CN", {})
    passionate = clean_commentary_script(zh_variants.get("passionate") or display_script(event, evidence_text))
    steady = clean_commentary_script(zh_variants.get("steady") or "")
    if not passionate or has_internal_commentary_terms(passionate):
        passionate = zh_generated_script(event, title, style="passionate")
    if not steady or has_internal_commentary_terms(steady):
        steady = zh_generated_script(event, title, style="steady")
    return {
        "zh-CN": {
            "passionate": {"title": title, "script": passionate, "evidence": evidence_text},
            "steady": {"title": title, "script": steady, "evidence": evidence_text},
        },
        "en": {
            "passionate": {"title": title, "script": localized_script(event, title, "en", "passionate"), "evidence": evidence_text},
            "steady": {"title": title, "script": localized_script(event, title, "en", "steady"), "evidence": evidence_text},
        },
        "es": {
            "passionate": {"title": title, "script": localized_script(event, title, "es", "passionate"), "evidence": evidence_text},
            "steady": {"title": title, "script": localized_script(event, title, "es", "steady"), "evidence": evidence_text},
        },
        "fr": {
            "passionate": {"title": title, "script": localized_script(event, title, "fr", "passionate"), "evidence": evidence_text},
            "steady": {"title": title, "script": localized_script(event, title, "fr", "steady"), "evidence": evidence_text},
        },
    }


def _score_from_title(title: str) -> str:
    match = re.search(r"(\d+[-:]\d+)", title or "")
    return match.group(1).replace(":", "-") if match else ""


def build_demo_data(events: list[dict], scoreboard_goals: list[dict]) -> dict:
    alignment_overrides = load_clip_alignment_overrides()
    type_counts: dict[str, int] = {}
    items = []
    for event in events:
        event_type = event.get("event_type") or "unknown"
        if event_type not in WEB_RETAINED_EVENT_TYPES:
            continue
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
        index = type_counts[event_type]
        type_label = TYPE_LABELS.get(event_type, event_type)
        clip_name = f"{event['event_id']}_{event_type}.mp4"
        video_timestamp = event.get("video_timestamp") or ""
        original_video_timestamp = video_timestamp
        alignment_override = alignment_overrides.get(event["event_id"])
        if alignment_override and alignment_override.get("aligned_video_timestamp"):
            video_timestamp = str(alignment_override["aligned_video_timestamp"])
        evidence_text = event_text(event.get("evidence"))
        title = display_title(event)
        items.append(
            {
                "id": event["event_id"],
                "type": event_type,
                "typeLabel": type_label,
                "smallLabel": f"{type_label}{index}",
                "matchTime": event.get("match_time") or "",
                "videoTimestamp": video_timestamp,
                "clipStart": seconds_to_timestamp(timestamp_to_seconds(video_timestamp) - 5),
                "clipEnd": seconds_to_timestamp(timestamp_to_seconds(video_timestamp) + 5),
                "originalVideoTimestamp": original_video_timestamp,
                "clipAlignment": {
                    "applied": bool(alignment_override),
                    "deltaSeconds": round(timestamp_to_seconds(video_timestamp) - timestamp_to_seconds(original_video_timestamp), 3) if alignment_override else 0,
                    "note": alignment_override.get("note", "") if alignment_override else "",
                },
                "title": title,
                "certainty": event.get("certainty") or "",
                "importance": "high" if event_type == "goal" else "medium",
                "clip": f"assets/clips/{clip_name}",
                "script": display_script(event, evidence_text),
                "evidence": evidence_text,
                "copyVariants": copy_variants(event, title, evidence_text),
                "scoreAfter": event.get("score_after") or _score_from_title(title),
                "team": infer_team(event),
                "goalTimestampPolicy": event.get("goal_timestamp_policy") or "",
            }
        )

    categories = []
    known_types = TYPE_ORDER + sorted({item["type"] for item in items} - set(TYPE_ORDER))
    for event_type in known_types:
        children = [item for item in items if item["type"] == event_type]
        if children:
            categories.append({"type": event_type, "label": TYPE_LABELS.get(event_type, event_type), "items": children})

    goal_policy = scoreboard_goals[0].get("goal_timestamp_policy") if scoreboard_goals else ""

    return {
        "generatedFrom": EVENTS_PATH.relative_to(ROOT).as_posix() if "v4_3_2" in EVENTS_PATH.as_posix() else REPORT_PATH.relative_to(ROOT).as_posix(),
        "commentaryReportFrom": FULL_REPORT_PATH.relative_to(ROOT).as_posix() if FULL_REPORT_PATH.exists() else "",
        "guardedEventsFrom": EVENTS_PATH.relative_to(ROOT).as_posix(),
        "scoreboardGoalEventsFrom": SCOREBOARD_GOALS_PATH.relative_to(ROOT).as_posix() if SCOREBOARD_GOALS_PATH.exists() else "",
        "version": VERSION,
        "versionLabel": VERSION_LABEL,
        "versionBadge": f"{VERSION_LABEL} · OCR8",
        "goalTimestampPolicy": goal_policy,
        "scoreboardGoalCount": len(scoreboard_goals),
        "publicUrl": PUBLIC_URL,
        "clipWindowSeconds": 10,
        "categories": categories,
        "events": items,
    }


def make_clip(video_timestamp: str, output_path: Path, duration: float = 10.0) -> None:
    center = timestamp_to_seconds(video_timestamp)
    start = max(0.0, center - duration / 2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(SOURCE),
            "-t",
            f"{duration:.3f}",
            "-vf",
            "scale=-2:720,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "27",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def escape_drawtext(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def make_montage_clip(event: dict, clip_path: Path, duration: float = 8.0) -> None:
    center = timestamp_to_seconds(event.get("videoTimestamp"))
    start = max(0.0, center - duration / 2)
    title = f"{event.get('matchTime') or ''}  {event.get('title') or ''}"
    line = event.get("script") or event.get("evidence") or ""
    font = "C\\:/Windows/Fonts/msyh.ttc"
    text = escape_drawtext(f"{title} · {line}")[:92]
    vf = (
        "scale=-2:720,"
        "drawbox=x=0:y=560:w=iw:h=160:color=black@0.58:t=fill,"
        f"drawtext=fontfile='{font}':text='{text}':x=42:y=590:"
        "fontsize=28:fontcolor=white:line_spacing=8:box=0"
    )
    run_ffmpeg(
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(SOURCE),
            "-t",
            f"{duration:.3f}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(clip_path),
        ]
    )


def create_title_card(path: Path, title: str, subtitle: str, *, outro: bool = False) -> None:
    hero = Image.open(ASSETS / "hero-worldcup.png").convert("RGB").resize((1920, 1080))
    overlay = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, 1920, 1080), fill=(0, 0, 0, 92 if not outro else 120))
    draw.rectangle((0, 746, 1920, 1080), fill=(0, 0, 0, 156))
    hero = Image.alpha_composite(hero.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(hero)
    title_font = load_font(74)
    sub_font = load_font(36)
    small_font = load_font(26)
    draw.text((92, 778), title, font=title_font, fill=(255, 255, 255))
    y = 892
    for line in fit_text(draw, subtitle, sub_font, 1400, 2):
        draw.text((98, y), line, font=sub_font, fill=(232, 238, 244))
        y += 48
    draw.text((100, 1018), f"Germany vs Curacao · {VERSION_LABEL} Match Review Demo", font=small_font, fill=(198, 213, 224))
    path.parent.mkdir(parents=True, exist_ok=True)
    hero.convert("RGB").save(path, quality=92)


def title_card_to_video(image_path: Path, output_path: Path, duration: float) -> None:
    run_ffmpeg(
        [
            "-loop",
            "1",
            "-t",
            f"{duration:.2f}",
            "-i",
            str(image_path),
            "-f",
            "lavfi",
            "-t",
            f"{duration:.2f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            "scale=1280:720,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "24",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            str(output_path),
        ]
    )


def make_qr() -> None:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(PUBLIC_URL)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(ASSETS / "site-qr.png")


def make_montage(events: list[dict]) -> None:
    montage_dir = ASSETS / "montage"
    montage_dir.mkdir(parents=True, exist_ok=True)
    create_title_card(
        montage_dir / "intro.png",
        f"德国 vs 库拉索 · {VERSION_LABEL} 事项回看",
        "自动串联关键片段，快速查看进球和主要机会",
    )
    title_card_to_video(montage_dir / "intro.png", montage_dir / "intro.mp4", 2.0)

    goals = [event for event in events if event["type"] == "goal"]
    selected = goals[:6] if len(goals) >= 6 else events[:6]
    concat_parts = [montage_dir / "intro.mp4"]
    for idx, event in enumerate(selected, start=1):
        clip_path = montage_dir / f"montage_{idx:02d}_{event['id']}.mp4"
        make_montage_clip(event, clip_path, duration=8.0)
        concat_parts.append(clip_path)

    create_title_card(
        montage_dir / "outro.png",
        "交互式事项回看",
        f"43 个事项、43 个回看片段、8 个进球，可直接点选播放",
        outro=True,
    )
    title_card_to_video(montage_dir / "outro.png", montage_dir / "outro.mp4", 2.0)
    concat_parts.append(montage_dir / "outro.mp4")

    concat_file = montage_dir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{part.as_posix()}'" for part in concat_parts), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(ASSETS / "worldcup_demo_1min.mp4")])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static web demo from the retained V4.5 item markdown.")
    parser.add_argument("--skip-clips", action="store_true", help="Only write web_demo/data/events.json and QR assets.")
    parser.add_argument("--skip-montage", action="store_true", help="Do not rebuild assets/worldcup_demo_1min.mp4.")
    args = parser.parse_args()

    requires_source_video = not args.skip_clips or not args.skip_montage
    if requires_source_video and not SOURCE.exists():
        raise FileNotFoundError(f"Missing source video: {SOURCE}")
    if not REPORT_PATH.exists() and "v4_3_2" not in EVENTS_PATH.as_posix():
        raise FileNotFoundError(f"Missing report: {REPORT_PATH}")
    if not EVENTS_PATH.exists():
        raise FileNotFoundError(f"Missing guarded events: {EVENTS_PATH}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    if not args.skip_clips:
        for old_clip in CLIPS.glob("*.mp4"):
            old_clip.unlink()

    scoreboard_goals = load_scoreboard_goals()
    source_events = load_source_events(scoreboard_goals)
    demo_data = build_demo_data(source_events, scoreboard_goals)
    (DATA / "events.json").write_text(json.dumps(demo_data, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_clips:
        for item in demo_data["events"]:
            make_clip(item["videoTimestamp"], WEB / item["clip"])

    if not args.skip_montage:
        make_montage(demo_data["events"])
    make_qr()

    print(f"source={demo_data['generatedFrom']}")
    print(f"guarded={EVENTS_PATH.relative_to(ROOT).as_posix()}")
    print(f"scoreboard_goals={SCOREBOARD_GOALS_PATH.relative_to(ROOT).as_posix() if SCOREBOARD_GOALS_PATH.exists() else ''}")
    print(f"goal_policy={demo_data.get('goalTimestampPolicy')}")
    print(f"events={len(demo_data['events'])}")
    print(f"clips={len(list(CLIPS.glob('*.mp4')))}")
    print(f"montage={'skipped' if args.skip_montage else ASSETS / 'worldcup_demo_1min.mp4'}")


if __name__ == "__main__":
    main()
