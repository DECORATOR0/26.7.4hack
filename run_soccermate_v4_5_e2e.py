from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from src.config import load_dotenv, load_intern_config
from src.event_agent import EventAgentOptions, EventAgentRunner
from src.frame_narration import FrameNarrationOptions, FrameNarrationRunner
from src.guardrail import GuardrailOptions, V4GuardrailRunner
from src.io_utils import read_json, write_json
from src.scoreboard_goals import ScoreboardGoalOptions, ScoreboardGoalRunner
from src.script_report import ScriptReportOptions, ScriptReportRunner
from src.visual_spotting import VisualSpottingOptions, VisualSpottingRunner


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def env_path(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path

# One-command V4.5 delivery settings. Edit these constants when the input match changes.
VIDEO_PATH = env_path("SOCCERMATE_VIDEO_PATH", "德国_库拉索.mp4")
MATCH_INFO_PATH = env_path("SOCCERMATE_MATCH_INFO_PATH", "examples/match_info.germany_curacao.json")

VISUAL_OUT = ROOT / "outputs_visual_full_safe"
BOOTSTRAP_OUT = ROOT / "outputs_soccermate_v4_5_e2e"
SCOREBOARD_SEED_OUT = ROOT / "outputs_event_agent_v4_5_seed"
FRAME_NARRATION_OUT = ROOT / "outputs_frame_narration_v4_5"
EVENT_TEXT_OUT = ROOT / "outputs_event_agent_v4_5_text"
EVENT_FINAL_OUT = ROOT / "outputs_event_agent_v4_5"
SCRIPT_REPORT_OUT = ROOT / "outputs_script_report_v4_5"
WEB_DEMO_EVENTS_PATH = ROOT / "web_demo" / "data" / "events.json"
STATUS_PATH = ROOT / "version4_5_status.json"

FRAME_INDEX_PATH = VISUAL_OUT / "frame_index_2s.json"
BOOTSTRAP_EVENTS_PATH = BOOTSTRAP_OUT / "bootstrap_empty_events.json"
SEED_GOALS_PATH = SCOREBOARD_SEED_OUT / "scoreboard_goal_events.json"
SEGMENT_DESCRIPTIONS_PATH = FRAME_NARRATION_OUT / "segment_descriptions.json"
TEXT_FINAL_EVENTS_PATH = EVENT_TEXT_OUT / "final_events.json"
TEXT_GUARDED_EVENTS_PATH = EVENT_TEXT_OUT / "final_events_guarded_v4.json"
FINAL_EVENTS_PATH = EVENT_FINAL_OUT / "final_events_guarded_v4_5.json"
ITEMS_MARKDOWN_PATH = SCRIPT_REPORT_OUT / "final_report_v4_5_items.md"
DELIVERY_MARKDOWN_PATH = SCRIPT_REPORT_OUT / "final_report_v4_5.md"

INTERN_S2_API_BASE = "https://chat.intern-ai.org.cn/api/v1"
INTERN_S2_MODEL = "intern-s2-preview"

FRAME_INTERVAL_SECONDS = env_float("SOCCERMATE_FRAME_INTERVAL_SECONDS", 2.0)
FRAME_SEGMENT_SECONDS = env_float("SOCCERMATE_FRAME_SEGMENT_SECONDS", 60.0)
FRAME_MAX_IMAGES_PER_SEGMENT = env_int("SOCCERMATE_FRAME_MAX_IMAGES", 30)
FRAME_NARRATION_CONCURRENCY = env_int("SOCCERMATE_FRAME_NARRATION_CONCURRENCY", 8)
FRAME_NARRATION_RPM_LIMIT = env_float("SOCCERMATE_FRAME_NARRATION_RPM_LIMIT", 15.0)
FRAME_NARRATION_MAX_TOKENS = env_int("SOCCERMATE_FRAME_NARRATION_MAX_TOKENS", 6000)

EVENT_CHUNK_SEGMENTS = env_int("SOCCERMATE_EVENT_CHUNK_SEGMENTS", 12)
EVENT_AGENT_CONCURRENCY = env_int("SOCCERMATE_EVENT_AGENT_CONCURRENCY", 3)
EVENT_AGENT_RPM_LIMIT = env_float("SOCCERMATE_EVENT_AGENT_RPM_LIMIT", 12.0)
EVENT_AGENT_TEXT_MAX_TOKENS = env_int("SOCCERMATE_EVENT_AGENT_TEXT_MAX_TOKENS", 10000)
EVENT_AGENT_FINAL_MAX_EVENTS = env_int("SOCCERMATE_EVENT_AGENT_FINAL_MAX_EVENTS", 80)
EVENT_AGENT_FINAL_MAX_TOKENS = env_int("SOCCERMATE_EVENT_AGENT_FINAL_MAX_TOKENS", 14000)

SCOREBOARD_COARSE_INTERVAL_SEC = env_int("SOCCERMATE_SCOREBOARD_COARSE_INTERVAL_SEC", 20)
SCOREBOARD_BATCH_SIZE = env_int("SOCCERMATE_SCOREBOARD_BATCH_SIZE", 12)
SCOREBOARD_RPM_LIMIT = env_float("SOCCERMATE_SCOREBOARD_RPM_LIMIT", 12.0)
SCOREBOARD_MIN_CONFIDENCE = env_float("SOCCERMATE_SCOREBOARD_MIN_CONFIDENCE", 0.5)
SCOREBOARD_REFINE_MAX_GAP_SEC = env_int("SOCCERMATE_SCOREBOARD_REFINE_MAX_GAP_SEC", 180)
SCOREBOARD_GOAL_POLICY = "last_before_jump"

BUILD_WEB_DATA = env_bool("SOCCERMATE_BUILD_WEB_DATA", True)
WEB_BUILD_SKIP_CLIPS = env_bool("SOCCERMATE_WEB_SKIP_CLIPS", True)
WEB_BUILD_SKIP_MONTAGE = env_bool("SOCCERMATE_WEB_SKIP_MONTAGE", True)
RESUME_CACHED_MODEL_CALLS = env_bool("SOCCERMATE_RESUME_CACHED_MODEL_CALLS", True)
REUSE_COMPLETED_STAGE_OUTPUTS = env_bool("SOCCERMATE_REUSE_COMPLETED_STAGE_OUTPUTS", True)

EXPECTED_WEB_EVENT_COUNT = 43
EXPECTED_SCOREBOARD_GOAL_COUNT = 8
EXPECTED_WEB_TYPES = {
    "corner",
    "foul_card_dispute",
    "free_kick",
    "goal",
    "shot_chance",
    "substitution",
}


def write_status(stage: str, status: str, **extra: Any) -> None:
    payload = {
        "stage": stage,
        "status": status,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "runner": "run_soccermate_v4_5_e2e.py",
        "video": str(VIDEO_PATH),
        "items_markdown": str(ITEMS_MARKDOWN_PATH),
        "delivery_markdown": str(DELIVERY_MARKDOWN_PATH),
        "web_data": str(WEB_DEMO_EVENTS_PATH),
    }
    payload.update(extra)
    write_json(STATUS_PATH, payload)


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_step(name: str, action: Callable[[], None]) -> None:
    log(f"START {name}")
    write_status(name, "running")
    started = time.time()
    try:
        action()
    except Exception as exc:
        write_status(name, "failed", error=str(exc))
        raise
    elapsed = round(time.time() - started, 3)
    write_status(name, "done", elapsed_seconds=elapsed)
    log(f"END {name} ({elapsed}s)")


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def completed(paths: list[Path]) -> bool:
    return REUSE_COMPLETED_STAGE_OUTPUTS and all(path.exists() for path in paths)


def log_reuse(stage: str, paths: list[Path]) -> None:
    joined = ", ".join(str(path.relative_to(ROOT)) for path in paths)
    log(f"REUSE {stage}: {joined}")


def configure_api() -> None:
    os.environ.setdefault("INTERN_S2_API_BASE", INTERN_S2_API_BASE)
    os.environ.setdefault("INTERN_S2_MODEL", INTERN_S2_MODEL)
    config = load_intern_config()
    if not config.api_key:
        raise RuntimeError("INTERN_S2_API_KEY is not configured. Put it in .env or the process environment.")


def prepare_bootstrap_events() -> None:
    write_json(
        BOOTSTRAP_EVENTS_PATH,
        {
            "final_events": [],
            "match_time_anchors": [],
            "quality_notes": ["bootstrap source for scoreboard OCR goal memory"],
        },
    )


def extract_or_reuse_frames() -> None:
    if completed([FRAME_INDEX_PATH]):
        log_reuse("2-second frame index", [FRAME_INDEX_PATH])
        return
    VisualSpottingRunner(
        VisualSpottingOptions(
            video_path=VIDEO_PATH,
            out_dir=VISUAL_OUT,
            interval_seconds=FRAME_INTERVAL_SECONDS,
            batch_sizes=[15],
            detectors=["core"],
            concurrency=1,
            rpm_limit=None,
            reuse_frames=True,
            no_model=True,
            temperature=0.1,
        )
    ).run()
    require_file(FRAME_INDEX_PATH, "2-second frame index")


def run_scoreboard_seed() -> None:
    if completed([SEED_GOALS_PATH]):
        log_reuse("scoreboard OCR goal memory", [SEED_GOALS_PATH])
        return
    prepare_bootstrap_events()
    ScoreboardGoalRunner(
        ScoreboardGoalOptions(
            source_events_path=BOOTSTRAP_EVENTS_PATH,
            frame_index_path=FRAME_INDEX_PATH,
            out_dir=SCOREBOARD_SEED_OUT,
            output_version="v4_5_seed",
            goal_timestamp_policy=SCOREBOARD_GOAL_POLICY,
            video_path=VIDEO_PATH,
            coarse_interval_sec=SCOREBOARD_COARSE_INTERVAL_SEC,
            batch_size=SCOREBOARD_BATCH_SIZE,
            rpm_limit=SCOREBOARD_RPM_LIMIT,
            min_confidence=SCOREBOARD_MIN_CONFIDENCE,
            refine_goal_times=True,
            refine_max_gap_sec=SCOREBOARD_REFINE_MAX_GAP_SEC,
            home_team="德国",
            away_team="库拉索",
            resume=RESUME_CACHED_MODEL_CALLS,
            no_model=False,
        )
    ).run()
    require_file(SEED_GOALS_PATH, "scoreboard OCR goal memory")


def run_frame_narration() -> None:
    if completed([SEGMENT_DESCRIPTIONS_PATH]):
        log_reuse("frame narration", [SEGMENT_DESCRIPTIONS_PATH])
        return
    FrameNarrationRunner(
        FrameNarrationOptions(
            frame_index_path=FRAME_INDEX_PATH,
            out_dir=FRAME_NARRATION_OUT,
            goal_memory_path=SEED_GOALS_PATH,
            segment_seconds=FRAME_SEGMENT_SECONDS,
            max_images=FRAME_MAX_IMAGES_PER_SEGMENT,
            concurrency=FRAME_NARRATION_CONCURRENCY,
            rpm_limit=FRAME_NARRATION_RPM_LIMIT,
            temperature=0.1,
            max_tokens=FRAME_NARRATION_MAX_TOKENS,
            resume=RESUME_CACHED_MODEL_CALLS,
            no_model=False,
        )
    ).run()
    require_file(SEGMENT_DESCRIPTIONS_PATH, "frame narration descriptions")


def run_event_agent() -> None:
    if completed([TEXT_FINAL_EVENTS_PATH]):
        log_reuse("event agent final events", [TEXT_FINAL_EVENTS_PATH])
        return
    EventAgentRunner(
        EventAgentOptions(
            descriptions_path=SEGMENT_DESCRIPTIONS_PATH,
            frame_index_path=FRAME_INDEX_PATH,
            out_dir=EVENT_TEXT_OUT,
            chunk_segments=EVENT_CHUNK_SEGMENTS,
            concurrency=EVENT_AGENT_CONCURRENCY,
            rpm_limit=EVENT_AGENT_RPM_LIMIT,
            temperature=0.1,
            text_max_tokens=EVENT_AGENT_TEXT_MAX_TOKENS,
            review_window_seconds=8.0,
            review_max_frames=9,
            goal_review_window_seconds=30.0,
            goal_review_max_frames=31,
            final_max_events=EVENT_AGENT_FINAL_MAX_EVENTS,
            final_consolidation_max_tokens=EVENT_AGENT_FINAL_MAX_TOKENS,
            schema_version="v4",
            final_only=False,
            pure_model_output=False,
            resume=RESUME_CACHED_MODEL_CALLS,
            skip_image_review=False,
            no_model=False,
        )
    ).run()
    require_file(TEXT_FINAL_EVENTS_PATH, "text event agent final events")


def run_guardrail() -> None:
    if completed([TEXT_GUARDED_EVENTS_PATH]):
        log_reuse("guarded text events", [TEXT_GUARDED_EVENTS_PATH])
        return
    V4GuardrailRunner(
        GuardrailOptions(
            events_path=TEXT_FINAL_EVENTS_PATH,
            out_dir=EVENT_TEXT_OUT,
            temperature=0.0,
            max_tokens=6000,
            no_model=False,
        )
    ).run()
    require_file(TEXT_GUARDED_EVENTS_PATH, "guarded text events")


def run_scoreboard_final_merge() -> None:
    if completed([FINAL_EVENTS_PATH]):
        log_reuse("final scoreboard merged events", [FINAL_EVENTS_PATH])
        return
    ScoreboardGoalRunner(
        ScoreboardGoalOptions(
            source_events_path=TEXT_GUARDED_EVENTS_PATH,
            frame_index_path=FRAME_INDEX_PATH,
            out_dir=EVENT_FINAL_OUT,
            precomputed_goals_path=SEED_GOALS_PATH,
            output_version="v4_5",
            goal_timestamp_policy=SCOREBOARD_GOAL_POLICY,
            video_path=VIDEO_PATH,
            home_team="德国",
            away_team="库拉索",
            resume=RESUME_CACHED_MODEL_CALLS,
            no_model=False,
        )
    ).run()
    require_file(FINAL_EVENTS_PATH, "final V4.5 guarded events")


def run_script_report() -> None:
    ScriptReportRunner(
        ScriptReportOptions(
            events_path=FINAL_EVENTS_PATH,
            out_dir=SCRIPT_REPORT_OUT,
            match_info_path=MATCH_INFO_PATH,
            temperature=0.2,
            max_tokens=10000,
            report_version="v4_5_markdown",
            pure_model_output=False,
            no_model=False,
        )
    ).run()
    require_file(ITEMS_MARKDOWN_PATH, "V4.5 item markdown")
    require_file(DELIVERY_MARKDOWN_PATH, "V4.5 delivery markdown")


def run_web_data_build() -> None:
    if not BUILD_WEB_DATA:
        return
    args = [sys.executable, str(ROOT / "scripts" / "build_web_demo_from_report.py")]
    if WEB_BUILD_SKIP_CLIPS:
        args.append("--skip-clips")
    if WEB_BUILD_SKIP_MONTAGE:
        args.append("--skip-montage")
    subprocess.run(args, cwd=ROOT, check=True)
    require_file(WEB_DEMO_EVENTS_PATH, "web demo events.json")


def count_item_markdown_rows(path: Path) -> int:
    rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and len(stripped) > 2:
            first_cell = stripped.split("|", 2)[1].strip()
            if first_cell.isdigit():
                rows += 1
    return rows


def validate_outputs() -> None:
    require_file(ITEMS_MARKDOWN_PATH, "V4.5 item markdown")
    require_file(DELIVERY_MARKDOWN_PATH, "V4.5 delivery markdown")

    item_rows = count_item_markdown_rows(ITEMS_MARKDOWN_PATH)
    if item_rows != EXPECTED_WEB_EVENT_COUNT:
        raise RuntimeError(f"Unexpected item markdown rows: {item_rows}")

    final_doc = read_json(FINAL_EVENTS_PATH)
    final_events = final_doc.get("final_events") or []
    scoreboard_goals = [event for event in final_events if event.get("event_type") == "goal"]
    if len(scoreboard_goals) != EXPECTED_SCOREBOARD_GOAL_COUNT:
        raise RuntimeError(f"Unexpected final goal count: {len(scoreboard_goals)}")

    if BUILD_WEB_DATA:
        web_data = json.loads(WEB_DEMO_EVENTS_PATH.read_text(encoding="utf-8"))
        events = web_data.get("events") or []
        event_types = {event.get("type") for event in events}
        if web_data.get("version") != "v4.5":
            raise RuntimeError(f"Unexpected web version: {web_data.get('version')}")
        if len(events) != EXPECTED_WEB_EVENT_COUNT:
            raise RuntimeError(f"Unexpected web event count: {len(events)}")
        if web_data.get("scoreboardGoalCount") != EXPECTED_SCOREBOARD_GOAL_COUNT:
            raise RuntimeError(f"Unexpected web goal count: {web_data.get('scoreboardGoalCount')}")
        if event_types != EXPECTED_WEB_TYPES:
            raise RuntimeError(f"Unexpected web event types: {sorted(event_types)}")

    write_status(
        "soccermate_v4_5_e2e",
        "done",
        item_markdown_rows=item_rows,
        final_scoreboard_goals=len(scoreboard_goals),
        web_event_count=EXPECTED_WEB_EVENT_COUNT,
    )


def main() -> None:
    os.chdir(ROOT)
    require_file(VIDEO_PATH, "source video")
    require_file(MATCH_INFO_PATH, "match info")
    configure_api()

    run_step("extract_or_reuse_2s_frames", extract_or_reuse_frames)
    run_step("scoreboard_goals_v4_5_seed", run_scoreboard_seed)
    run_step("frame_narration_v4_5_goal_memory", run_frame_narration)
    run_step("event_agent_v4_5_from_video_narrative", run_event_agent)
    run_step("guardrail_v4_5_text", run_guardrail)
    run_step("scoreboard_goal_merge_v4_5_final", run_scoreboard_final_merge)
    run_step("script_report_v4_5", run_script_report)
    run_step("web_demo_data_v4_5", run_web_data_build)
    run_step("validate_v4_5_delivery", validate_outputs)

    log("SOCCERMATE V4.5 END TO END DONE")
    log(f"items_markdown={ITEMS_MARKDOWN_PATH}")
    log(f"delivery_markdown={DELIVERY_MARKDOWN_PATH}")
    if BUILD_WEB_DATA:
        log(f"web_data={WEB_DEMO_EVENTS_PATH}")


if __name__ == "__main__":
    main()
