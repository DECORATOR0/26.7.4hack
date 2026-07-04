from __future__ import annotations

import argparse
from pathlib import Path

from src.visual_spotting import VisualSpottingOptions, VisualSpottingRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visual event spotting experiment")
    parser.add_argument("--video", required=True, help="Path to input MP4")
    parser.add_argument("--out", default="outputs_visual", help="Output directory")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between frames")
    parser.add_argument("--start-second", type=float, default=0.0, help="Start extracting frames from this second")
    parser.add_argument("--end-second", type=float, default=None, help="Stop extracting frames at this second")
    parser.add_argument("--batch-sizes", default="15,30,60", help="Comma-separated image batch sizes")
    parser.add_argument("--detectors", default="core", help="multi,core,all or comma-separated detector names")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent API requests")
    parser.add_argument("--rpm-limit", type=float, default=None, help="Throttle request starts to this RPM")
    parser.add_argument("--max-frames", type=int, default=None, help="Limit extracted frames for experiments")
    parser.add_argument("--max-batches-per-size", type=int, default=None, help="Limit batches per batch size")
    parser.add_argument("--reuse-frames", action="store_true", help="Reuse existing frame index and images")
    parser.add_argument("--no-model", action="store_true", help="Only extract frames and build batches")
    parser.add_argument("--temperature", type=float, default=0.1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_sizes = [int(x.strip()) for x in args.batch_sizes.split(",") if x.strip()]
    detectors = [x.strip() for x in args.detectors.split(",") if x.strip()]
    options = VisualSpottingOptions(
        video_path=Path(args.video),
        out_dir=Path(args.out),
        interval_seconds=args.interval,
        start_second=args.start_second,
        end_second=args.end_second,
        batch_sizes=batch_sizes,
        detectors=detectors,
        concurrency=max(1, args.concurrency),
        rpm_limit=args.rpm_limit,
        max_frames=args.max_frames,
        max_batches_per_size=args.max_batches_per_size,
        reuse_frames=args.reuse_frames,
        no_model=args.no_model,
        temperature=args.temperature,
    )
    result = VisualSpottingRunner(options).run()
    print(f"Done. Visual spotting outputs written to: {result}")


if __name__ == "__main__":
    main()
