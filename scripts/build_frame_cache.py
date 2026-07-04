from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import imageio_ffmpeg


def seconds_to_timestamp(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02}:{m:02}:{s:02}"


def find_video(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    videos = sorted(Path.cwd().glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    if not videos:
        raise FileNotFoundError("No .mp4 file found in current directory")
    return videos[0]


def probe_video(video: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    duration = frame_count / fps if fps > 0 else 0.0
    return {
        "video_path": str(video),
        "fps": round(float(fps), 3),
        "frame_count": int(frame_count),
        "width": width,
        "height": height,
        "duration_seconds": round(duration, 3),
        "duration": seconds_to_timestamp(duration),
    }


def build_cache(video: Path, out_root: Path, interval: int, force: bool) -> dict[str, Any]:
    label = f"{interval}s"
    out_dir = out_root / label
    frames_dir = out_dir / "frames"
    frame_index_path = out_dir / "frame_index.json"
    benchmark_path = out_dir / "benchmark.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(frames_dir.glob("frame_*.jpg"))
    if existing and frame_index_path.exists() and not force:
        frame_index = json.loads(frame_index_path.read_text(encoding="utf-8"))
        total_bytes = sum(p.stat().st_size for p in existing)
        return {
            "interval_seconds": interval,
            "out_dir": str(out_dir),
            "frames_dir": str(frames_dir),
            "frame_index": str(frame_index_path),
            "frame_count": len(frame_index),
            "elapsed_seconds": 0.0,
            "used_existing": True,
            "total_jpeg_bytes": total_bytes,
            "total_jpeg_mb": round(total_bytes / 1024 / 1024, 2),
            "avg_jpeg_kb": round(total_bytes / max(1, len(frame_index)) / 1024, 2),
        }

    if force:
        for file in frames_dir.glob("frame_*.jpg"):
            file.unlink()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    output_pattern = str(frames_dir / "frame_%05d.jpg")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps=1/{interval},scale=768:-2",
        "-q:v",
        "4",
        output_pattern,
    ]
    started = time.time()
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.time() - started
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    frame_index = []
    for idx, path in enumerate(frames, start=1):
        second = (idx - 1) * interval
        frame_index.append(
            {
                "frame_index": idx,
                "timestamp": seconds_to_timestamp(second),
                "timestamp_seconds": second,
                "path": str(path),
                "jpeg_bytes": path.stat().st_size,
            }
        )
    frame_index_path.write_text(json.dumps(frame_index, ensure_ascii=False, indent=2), encoding="utf-8")
    total_bytes = sum(item["jpeg_bytes"] for item in frame_index)
    result = {
        "interval_seconds": interval,
        "out_dir": str(out_dir),
        "frames_dir": str(frames_dir),
        "frame_index": str(frame_index_path),
        "frame_count": len(frame_index),
        "elapsed_seconds": round(elapsed, 3),
        "used_existing": False,
        "frames_per_second_extraction": round(len(frame_index) / elapsed, 3) if elapsed else None,
        "total_jpeg_bytes": total_bytes,
        "total_jpeg_mb": round(total_bytes / 1024 / 1024, 2),
        "avg_jpeg_kb": round(total_bytes / max(1, len(frame_index)) / 1024, 2),
    }
    benchmark_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline frame caches with ffmpeg")
    parser.add_argument("--video", default=None)
    parser.add_argument("--out", default="cache_frames")
    parser.add_argument("--intervals", default="1,2,5,10")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    video = find_video(args.video)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    metadata = probe_video(video)
    intervals = [int(x.strip()) for x in args.intervals.split(",") if x.strip()]
    results = []
    for interval in intervals:
        result = build_cache(video, out_root, interval, args.force)
        print(json.dumps(result, ensure_ascii=False))
        results.append(result)
        (out_root / "frame_cache_benchmark.json").write_text(
            json.dumps({"video_metadata": metadata, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

