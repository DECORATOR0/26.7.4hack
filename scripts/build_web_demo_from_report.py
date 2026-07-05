from __future__ import annotations

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
REPORT_CANDIDATES = [
    ROOT / "outputs_script_report_v4_4" / "final_report_v4_4.md",
    ROOT / "outputs_script_report_v4_3" / "final_report_v4_3.md",
    ROOT / "outputs_script_report_v4_2" / "final_report_v4_2.md",
]
REPORT_PATH = next((path for path in REPORT_CANDIDATES if path.exists()), REPORT_CANDIDATES[0])
EVENTS_CANDIDATES = [
    ROOT / "outputs_event_agent_v4_3_2" / "final_events_guarded_v4_3_2.json",
    ROOT / "outputs_event_agent_v4_4" / "final_events_guarded_v4_4.json",
    ROOT / "outputs_event_agent_v4_3" / "final_events_guarded_v4_3.json",
    ROOT / "outputs_event_agent_v4_2" / "final_events_guarded_v4.json",
]
EVENTS_PATH = next((path for path in EVENTS_CANDIDATES if path.exists()), EVENTS_CANDIDATES[0])
SCOREBOARD_GOAL_CANDIDATES = [
    ROOT / "outputs_event_agent_v4_3_2" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_4" / "scoreboard_goal_events.json",
    ROOT / "outputs_event_agent_v4_3" / "scoreboard_goal_events.json",
]
SCOREBOARD_GOALS_PATH = next((path for path in SCOREBOARD_GOAL_CANDIDATES if path.exists()), SCOREBOARD_GOAL_CANDIDATES[0])
PUBLIC_URL = "http://39.105.210.249/"
VERSION_SOURCE = EVENTS_PATH.as_posix() + " " + REPORT_PATH.as_posix()
VERSION = "v4.3.2" if "v4_3_2" in VERSION_SOURCE else ("v4.4" if "v4_4" in VERSION_SOURCE else ("v4.3" if "v4_3" in VERSION_SOURCE else "v4.2"))
VERSION_LABEL = VERSION.upper()
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


TYPE_LABELS = {
    "goal": "进球",
    "penalty": "点球",
    "shot_chance": "射门机会",
    "corner": "角球",
    "free_kick": "任意球",
    "foul_card_dispute": "判罚争议",
    "substitution": "换人",
    "half_full_time": "半场/全场",
    "offside": "越位",
    "celebration": "庆祝",
}

TYPE_ORDER = [
    "goal",
    "penalty",
    "shot_chance",
    "corner",
    "free_kick",
    "foul_card_dispute",
    "substitution",
    "offside",
    "half_full_time",
    "celebration",
]


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
        index = int(cells[0])
        rows.append(
            {
                "event_id": f"F{index:04d}",
                "match_time": cells[1],
                "video_timestamp": cells[2],
                "event_type": cells[3],
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
    return rows


def assert_guarded_events_match(report_events: list[dict]) -> None:
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
    if event.get("event_type") == "goal" and event.get("team") and event.get("score_after"):
        return f"{event.get('team')}队进球由记分牌比分跳变确认，比分来到 {event.get('score_after')}。"
    return event_text(event.get("script") or event.get("script_angle") or evidence_text)


def build_demo_data(events: list[dict], scoreboard_goals: list[dict]) -> dict:
    type_counts: dict[str, int] = {}
    items = []
    for event in events:
        event_type = event.get("event_type") or "unknown"
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
        index = type_counts[event_type]
        type_label = TYPE_LABELS.get(event_type, event_type)
        clip_name = f"{event['event_id']}_{event_type}.mp4"
        video_timestamp = event.get("video_timestamp") or ""
        evidence_text = event_text(event.get("evidence"))
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
                "title": display_title(event),
                "certainty": event.get("certainty") or "",
                "importance": "high" if event_type == "goal" else "medium",
                "clip": f"assets/clips/{clip_name}",
                "script": display_script(event, evidence_text),
                "evidence": evidence_text,
                "scoreAfter": event.get("score_after") or "",
                "team": event.get("team") or "",
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
    draw.text((100, 1018), f"Germany vs Curacao · Intern S2 {VERSION_LABEL} Event-to-Commentary Demo", font=small_font, fill=(198, 213, 224))
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
        f"德国 vs 库拉索 · {VERSION_LABEL} 事项解说",
        "基于 Guarded JSON 与 scoreboard goal events 生成交互式片段和一分钟演示视频",
    )
    title_card_to_video(montage_dir / "intro.png", montage_dir / "intro.mp4", 5.0)

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
        f"左侧选择事项类型与编号，右侧查看对应 10 秒片段与 {VERSION_LABEL} 解说文案",
        outro=True,
    )
    title_card_to_video(montage_dir / "outro.png", montage_dir / "outro.mp4", 5.0)
    concat_parts.append(montage_dir / "outro.mp4")

    concat_file = montage_dir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{part.as_posix()}'" for part in concat_parts), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(ASSETS / "worldcup_demo_1min.mp4")])


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Missing source video: {SOURCE}")
    if not REPORT_PATH.exists() and "v4_3_2" not in EVENTS_PATH.as_posix():
        raise FileNotFoundError(f"Missing report: {REPORT_PATH}")
    if not EVENTS_PATH.exists():
        raise FileNotFoundError(f"Missing guarded events: {EVENTS_PATH}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    for old_clip in CLIPS.glob("*.mp4"):
        old_clip.unlink()

    scoreboard_goals = load_scoreboard_goals()
    source_events = load_source_events(scoreboard_goals)
    demo_data = build_demo_data(source_events, scoreboard_goals)
    (DATA / "events.json").write_text(json.dumps(demo_data, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in demo_data["events"]:
        make_clip(item["videoTimestamp"], WEB / item["clip"])

    make_montage(demo_data["events"])
    make_qr()

    print(f"source={demo_data['generatedFrom']}")
    print(f"guarded={EVENTS_PATH.relative_to(ROOT).as_posix()}")
    print(f"scoreboard_goals={SCOREBOARD_GOALS_PATH.relative_to(ROOT).as_posix() if SCOREBOARD_GOALS_PATH.exists() else ''}")
    print(f"goal_policy={demo_data.get('goalTimestampPolicy')}")
    print(f"events={len(demo_data['events'])}")
    print(f"clips={len(list(CLIPS.glob('*.mp4')))}")
    print(f"montage={ASSETS / 'worldcup_demo_1min.mp4'}")


if __name__ == "__main__":
    main()
