from __future__ import annotations

import argparse
from pathlib import Path

from src.scoreboard_goals import ScoreboardGoalOptions, ScoreboardGoalRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V4.3 hard goal events from scoreboard OCR score jumps")
    parser.add_argument("--source-events", required=True, help="Path to V4/V4.2 guarded final events JSON")
    parser.add_argument("--frame-index", required=True, help="Path to frame_index JSON for scoreboard crop extraction")
    parser.add_argument("--out", default="outputs_event_agent_v4_3", help="Output directory")
    parser.add_argument("--precomputed-goals", default=None, help="Use an existing scoreboard_goal_events.json and skip OCR")
    parser.add_argument("--precomputed-readings", default=None, help="Use an existing scoreboard_readings_merged.json and skip OCR")
    parser.add_argument("--output-version", default="v4_3", help="Suffix for final_events_guarded_<version>.json")
    parser.add_argument(
        "--goal-timestamp-policy",
        choices=["first_after_jump", "last_before_jump"],
        default="first_after_jump",
        help="Choose whether a goal is anchored to the first new-score reading or the last old-score reading",
    )
    parser.add_argument("--video", default=None, help="Optional source video path for 1-second goal refinement")
    parser.add_argument("--coarse-interval-sec", type=int, default=20, help="Coarse scoreboard OCR sampling interval")
    parser.add_argument("--batch-size", type=int, default=12, help="Images per scoreboard OCR request")
    parser.add_argument("--rpm-limit", type=float, default=12.0, help="Throttle OCR request starts")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum OCR confidence for score jumps")
    parser.add_argument("--no-refine-goal-times", action="store_true", help="Disable 1-second local refinement")
    parser.add_argument("--refine-max-gap-sec", type=int, default=180, help="Maximum coarse score-jump gap to refine")
    parser.add_argument("--home-team", default="德国")
    parser.add_argument("--away-team", default="库拉索")
    parser.add_argument("--resume", action="store_true", help="Reuse cached OCR batch results")
    parser.add_argument("--no-model", action="store_true", help="Do not call Intern-S2; useful for dry runs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = ScoreboardGoalOptions(
        source_events_path=Path(args.source_events),
        frame_index_path=Path(args.frame_index),
        out_dir=Path(args.out),
        precomputed_goals_path=Path(args.precomputed_goals) if args.precomputed_goals else None,
        precomputed_readings_path=Path(args.precomputed_readings) if args.precomputed_readings else None,
        output_version=args.output_version,
        goal_timestamp_policy=args.goal_timestamp_policy,
        video_path=Path(args.video) if args.video else None,
        coarse_interval_sec=max(1, args.coarse_interval_sec),
        batch_size=max(1, args.batch_size),
        rpm_limit=args.rpm_limit,
        min_confidence=max(0.0, min(1.0, args.min_confidence)),
        refine_goal_times=not args.no_refine_goal_times,
        refine_max_gap_sec=max(1, args.refine_max_gap_sec),
        home_team=args.home_team,
        away_team=args.away_team,
        resume=args.resume,
        no_model=args.no_model,
    )
    result = ScoreboardGoalRunner(options).run()
    print(f"Done. V4.3 scoreboard goal outputs written to: {result}")


if __name__ == "__main__":
    main()
