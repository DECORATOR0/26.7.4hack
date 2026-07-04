from __future__ import annotations

import argparse
from pathlib import Path

from src.event_agent import EventAgentOptions, EventAgentRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Locate football events from model-written frame narration")
    parser.add_argument("--descriptions", required=True, help="Path to segment_descriptions.json")
    parser.add_argument("--frame-index", required=True, help="Path to frame_index_2s.json")
    parser.add_argument("--out", default="outputs_event_agent", help="Output directory")
    parser.add_argument("--chunk-segments", type=int, default=12, help="Narration segments per text-agent request")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent API requests")
    parser.add_argument("--rpm-limit", type=float, default=12.0, help="Throttle request starts to this RPM")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--text-max-tokens", type=int, default=10000, help="Max output tokens per text-agent chunk")
    parser.add_argument("--review-window-seconds", type=float, default=8.0, help="Image review window around event timestamp")
    parser.add_argument("--review-max-frames", type=int, default=9, help="Max frames per image review")
    parser.add_argument("--max-chunks", type=int, default=None, help="Probe only the first N text chunks")
    parser.add_argument("--max-reviews", type=int, default=None, help="Cap image review calls for probing")
    parser.add_argument("--final-max-events", type=int, default=30, help="Max final events requested from final editor agent")
    parser.add_argument("--final-consolidation-max-tokens", type=int, default=None, help="Max output tokens for final consolidation")
    parser.add_argument("--schema-version", choices=["v2", "v3"], default="v2", help="Event schema/prompt version")
    parser.add_argument("--final-only", action="store_true", help="Only rerun final consolidation from cached text/review outputs")
    parser.add_argument("--pure-model-output", action="store_true", help="Write model outputs without local V3 content cleanup")
    parser.add_argument("--resume", action="store_true", help="Reuse completed raw text/review responses")
    parser.add_argument("--skip-image-review", action="store_true", help="Only run text agent and final consolidation")
    parser.add_argument("--no-model", action="store_true", help="Only build text chunk plan")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = EventAgentOptions(
        descriptions_path=Path(args.descriptions),
        frame_index_path=Path(args.frame_index),
        out_dir=Path(args.out),
        chunk_segments=max(1, args.chunk_segments),
        concurrency=max(1, args.concurrency),
        rpm_limit=args.rpm_limit,
        temperature=args.temperature,
        text_max_tokens=max(1, args.text_max_tokens),
        review_window_seconds=max(0.0, args.review_window_seconds),
        review_max_frames=max(1, args.review_max_frames),
        max_chunks=args.max_chunks,
        max_reviews=args.max_reviews,
        final_max_events=max(1, args.final_max_events),
        final_consolidation_max_tokens=args.final_consolidation_max_tokens,
        schema_version=args.schema_version,
        final_only=args.final_only,
        pure_model_output=args.pure_model_output,
        resume=args.resume,
        skip_image_review=args.skip_image_review,
        no_model=args.no_model,
    )
    result = EventAgentRunner(options).run()
    print(f"Done. Event agent outputs written to: {result}")


if __name__ == "__main__":
    main()
