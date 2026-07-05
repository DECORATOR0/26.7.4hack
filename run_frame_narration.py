from __future__ import annotations

import argparse
from pathlib import Path

from src.frame_narration import FrameNarrationOptions, FrameNarrationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert sampled football frames into textual observations")
    parser.add_argument("--frame-index", required=True, help="Path to 2-second frame_index JSON")
    parser.add_argument("--out", default="outputs_frame_narration", help="Output directory")
    parser.add_argument("--goal-memory", default=None, help="Optional OCR scoreboard goal facts to inject before narration")
    parser.add_argument("--segment-seconds", type=float, default=60.0, help="Seconds per narration segment")
    parser.add_argument("--max-images", type=int, default=30, help="Max images per segment request")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent API requests")
    parser.add_argument("--rpm-limit", type=float, default=15.0, help="Throttle request starts to this RPM")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=6000, help="Max output tokens per narration segment")
    parser.add_argument("--resume", action="store_true", help="Reuse completed raw segment responses")
    parser.add_argument("--max-segments", type=int, default=None, help="Limit segments for probing")
    parser.add_argument("--no-model", action="store_true", help="Only build segment plan")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = FrameNarrationOptions(
        frame_index_path=Path(args.frame_index),
        out_dir=Path(args.out),
        goal_memory_path=Path(args.goal_memory) if args.goal_memory else None,
        segment_seconds=args.segment_seconds,
        max_images=args.max_images,
        concurrency=max(1, args.concurrency),
        rpm_limit=args.rpm_limit,
        temperature=args.temperature,
        max_tokens=max(1, args.max_tokens),
        resume=args.resume,
        max_segments=args.max_segments,
        no_model=args.no_model,
    )
    result = FrameNarrationRunner(options).run()
    print(f"Done. Frame narration outputs written to: {result}")


if __name__ == "__main__":
    main()
