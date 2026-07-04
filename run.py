from __future__ import annotations

import argparse
from pathlib import Path

from src.harness import HarnessOptions, WorldCupHarness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="World Cup commentary harness")
    parser.add_argument("--video", required=True, help="Path to input MP4 video")
    parser.add_argument("--out", default="outputs", help="Output directory")
    parser.add_argument("--match-info", default=None, help="Optional match info JSON")
    parser.add_argument("--frame-interval", type=float, default=120.0, help="Seconds between sampled frames")
    parser.add_argument("--max-frames", type=int, default=48, help="Maximum sampled frames")
    parser.add_argument("--vision-frames", type=int, default=8, help="Frames sent to Intern-S2 for vision evidence")
    parser.add_argument("--temperature", type=float, default=0.3, help="LLM temperature")
    parser.add_argument("--fast-demo", action="store_true", help="Reuse cached intermediates when possible")
    parser.add_argument("--no-model", action="store_true", help="Do not call Intern-S2; use deterministic fallback")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = HarnessOptions(
        video_path=Path(args.video),
        out_dir=Path(args.out),
        match_info_path=Path(args.match_info) if args.match_info else None,
        frame_interval=args.frame_interval,
        max_frames=args.max_frames,
        vision_frames=args.vision_frames,
        temperature=args.temperature,
        fast_demo=args.fast_demo,
        no_model=args.no_model,
    )
    harness = WorldCupHarness(options)
    result = harness.run()
    print(f"Done. Outputs written to: {result}")


if __name__ == "__main__":
    main()

