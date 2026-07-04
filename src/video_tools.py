from __future__ import annotations

import math
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .io_utils import ensure_dir, seconds_to_timestamp, write_json


@dataclass
class VideoArtifacts:
    metadata: dict[str, Any]
    frame_index: list[dict[str, Any]]
    selected_frames: list[dict[str, Any]]
    audio_path: Path | None
    audio_peaks: list[dict[str, Any]]
    warnings: list[str]


def probe_video(video_path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frame_count / fps if fps > 0 else 0.0
    cap.release()
    return {
        "video_path": str(video_path),
        "file_size_bytes": video_path.stat().st_size,
        "fps": round(float(fps), 3),
        "frame_count": int(frame_count),
        "width": width,
        "height": height,
        "duration_seconds": round(duration, 3),
        "duration": seconds_to_timestamp(duration),
    }


def _sample_seconds(duration: float, interval: float, max_frames: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    interval = max(1.0, interval)
    seconds = list(np.arange(0, duration, interval))
    if not seconds or seconds[-1] < duration - 10:
        seconds.append(max(0.0, duration - 1.0))
    if len(seconds) <= max_frames:
        return [float(x) for x in seconds]
    indices = np.linspace(0, len(seconds) - 1, max_frames)
    return [float(seconds[int(round(i))]) for i in indices]


def sample_frames(
    video_path: Path,
    frames_dir: Path,
    *,
    interval_seconds: float = 120.0,
    max_frames: int = 48,
    jpeg_quality: int = 82,
) -> list[dict[str, Any]]:
    ensure_dir(frames_dir)
    metadata = probe_video(video_path)
    duration = float(metadata.get("duration_seconds") or 0.0)
    seconds_list = _sample_seconds(duration, interval_seconds, max_frames)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    frame_index: list[dict[str, Any]] = []
    previous_gray = None
    for idx, second in enumerate(seconds_list, start=1):
        cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        timestamp = seconds_to_timestamp(second).replace(":", "-")
        name = f"frame_{idx:04d}_{timestamp}.jpg"
        path = frames_dir / name
        cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        thumb = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        motion_score = 0.0
        if previous_gray is not None:
            diff = cv2.absdiff(thumb, previous_gray)
            motion_score = float(np.mean(diff))
        previous_gray = thumb

        brightness = float(np.mean(gray))
        frame_index.append(
            {
                "index": idx,
                "timestamp_seconds": round(second, 3),
                "timestamp": seconds_to_timestamp(second),
                "path": str(path),
                "motion_score": round(motion_score, 3),
                "brightness": round(brightness, 3),
            }
        )
    cap.release()
    return frame_index


def select_frames(
    frame_index: list[dict[str, Any]],
    selected_dir: Path,
    *,
    max_selected: int = 8,
) -> list[dict[str, Any]]:
    ensure_dir(selected_dir)
    if not frame_index:
        return []

    selected: dict[str, dict[str, Any]] = {}
    sorted_by_motion = sorted(frame_index, key=lambda x: x.get("motion_score", 0.0), reverse=True)
    for item in sorted_by_motion[: max(1, max_selected // 2)]:
        selected[item["path"]] = item

    if len(frame_index) > 1:
        for pos in np.linspace(0, len(frame_index) - 1, max_selected):
            item = frame_index[int(round(pos))]
            selected[item["path"]] = item

    result: list[dict[str, Any]] = []
    for item in list(selected.values())[:max_selected]:
        src = Path(item["path"])
        dst = selected_dir / src.name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        copied = dict(item)
        copied["selected_path"] = str(dst)
        result.append(copied)
    result.sort(key=lambda x: x.get("timestamp_seconds", 0.0))
    return result


def extract_audio(video_path: Path, audio_path: Path) -> tuple[Path | None, str | None]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    if not ffmpeg:
        return None, "ffmpeg not found; audio extraction skipped"
    ensure_dir(audio_path.parent)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(audio_path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if proc.returncode != 0:
        return None, f"ffmpeg audio extraction failed: {proc.stderr[-1000:]}"
    return audio_path, None


def analyze_audio_peaks(audio_path: Path | None, *, window_seconds: float = 2.0, top_k: int = 20) -> list[dict[str, Any]]:
    if not audio_path or not audio_path.exists():
        return []
    peaks: list[dict[str, Any]] = []
    try:
        with wave.open(str(audio_path), "rb") as wav:
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            channels = wav.getnchannels()
            frames_per_window = max(1, int(sample_rate * window_seconds))
            idx = 0
            while True:
                frames = wav.readframes(frames_per_window)
                if not frames:
                    break
                if sample_width != 2:
                    idx += 1
                    continue
                data = np.frombuffer(frames, dtype=np.int16)
                if channels > 1:
                    data = data.reshape(-1, channels).mean(axis=1)
                rms = math.sqrt(float(np.mean(np.square(data.astype(np.float64))))) if data.size else 0.0
                peaks.append(
                    {
                        "timestamp_seconds": round(idx * window_seconds, 3),
                        "timestamp": seconds_to_timestamp(idx * window_seconds),
                        "rms": round(rms, 3),
                    }
                )
                idx += 1
    except Exception:
        return []
    peaks.sort(key=lambda x: x["rms"], reverse=True)
    return peaks[:top_k]


def preprocess_video(
    video_path: Path,
    out_dir: Path,
    *,
    interval_seconds: float,
    max_frames: int,
    vision_frames: int,
    fast_demo: bool,
) -> VideoArtifacts:
    warnings: list[str] = []
    metadata_path = out_dir / "video_metadata.json"
    frame_index_path = out_dir / "frame_index.json"
    selected_path = out_dir / "selected_frames.json"
    audio_peaks_path = out_dir / "audio_peaks.json"
    audio_path = out_dir / "audio.wav"

    if fast_demo and metadata_path.exists() and frame_index_path.exists() and selected_path.exists():
        metadata = write_or_read_json(metadata_path)
        frame_index = write_or_read_json(frame_index_path)
        selected_frames = write_or_read_json(selected_path)
    else:
        metadata = probe_video(video_path)
        write_json(metadata_path, metadata)
        frame_index = sample_frames(
            video_path,
            out_dir / "frames" / "raw",
            interval_seconds=interval_seconds,
            max_frames=max_frames,
        )
        write_json(frame_index_path, frame_index)
        selected_frames = select_frames(frame_index, out_dir / "frames" / "selected", max_selected=vision_frames)
        write_json(selected_path, selected_frames)

    existing_audio = audio_path if audio_path.exists() else None
    if fast_demo and existing_audio:
        extracted_audio = existing_audio
    else:
        extracted_audio, warning = extract_audio(video_path, audio_path)
        if warning:
            warnings.append(warning)

    if fast_demo and audio_peaks_path.exists():
        audio_peaks = write_or_read_json(audio_peaks_path)
    else:
        audio_peaks = analyze_audio_peaks(extracted_audio)
        write_json(audio_peaks_path, audio_peaks)

    return VideoArtifacts(
        metadata=metadata,
        frame_index=frame_index,
        selected_frames=selected_frames,
        audio_path=extracted_audio,
        audio_peaks=audio_peaks,
        warnings=warnings,
    )


def write_or_read_json(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
