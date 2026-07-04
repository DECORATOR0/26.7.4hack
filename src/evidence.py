from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from .io_utils import write_json, write_text
from .video_tools import VideoArtifacts


def transcribe_audio(audio_path: Path | None, out_dir: Path) -> dict[str, Any]:
    transcript_path = out_dir / "transcript.json"
    transcript_text_path = out_dir / "transcript.txt"
    if not audio_path or not audio_path.exists():
        data = {
            "available": False,
            "method": None,
            "segments": [],
            "text": "",
            "warning": "audio.wav is unavailable; install ffmpeg to enable audio extraction",
        }
        write_json(transcript_path, data)
        write_text(transcript_text_path, "")
        return data

    if importlib.util.find_spec("faster_whisper"):
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(audio_path), vad_filter=True)
            segment_list = [
                {
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "text": seg.text.strip(),
                }
                for seg in segments
            ]
            text = "\n".join(item["text"] for item in segment_list)
            data = {
                "available": True,
                "method": "faster-whisper",
                "language": getattr(info, "language", None),
                "segments": segment_list,
                "text": text,
            }
            write_json(transcript_path, data)
            write_text(transcript_text_path, text)
            return data
        except Exception as exc:
            fallback = f"faster-whisper failed: {exc}"
    elif importlib.util.find_spec("whisper"):
        try:
            import whisper

            model = whisper.load_model("small")
            result = model.transcribe(str(audio_path))
            segment_list = [
                {
                    "start": round(seg.get("start", 0.0), 3),
                    "end": round(seg.get("end", 0.0), 3),
                    "text": str(seg.get("text", "")).strip(),
                }
                for seg in result.get("segments", [])
            ]
            text = result.get("text", "")
            data = {
                "available": True,
                "method": "openai-whisper",
                "language": result.get("language"),
                "segments": segment_list,
                "text": text,
            }
            write_json(transcript_path, data)
            write_text(transcript_text_path, text)
            return data
        except Exception as exc:
            fallback = f"openai-whisper failed: {exc}"
    else:
        fallback = "whisper is not installed; ASR skipped"

    data = {
        "available": False,
        "method": None,
        "segments": [],
        "text": "",
        "warning": fallback,
    }
    write_json(transcript_path, data)
    write_text(transcript_text_path, "")
    return data


def build_evidence(
    artifacts: VideoArtifacts,
    transcript: dict[str, Any],
    match_info: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    evidence = {
        "match_info": match_info,
        "video_metadata": artifacts.metadata,
        "frame_sampling": {
            "total_sampled_frames": len(artifacts.frame_index),
            "selected_frames": artifacts.selected_frames,
            "top_motion_frames": sorted(
                artifacts.frame_index,
                key=lambda x: x.get("motion_score", 0.0),
                reverse=True,
            )[:10],
        },
        "audio": {
            "audio_path": str(artifacts.audio_path) if artifacts.audio_path else None,
            "top_audio_peaks": artifacts.audio_peaks,
        },
        "transcript": {
            "available": transcript.get("available", False),
            "method": transcript.get("method"),
            "segment_count": len(transcript.get("segments", [])),
            "text_excerpt": (transcript.get("text") or "")[:6000],
            "warning": transcript.get("warning"),
        },
        "warnings": artifacts.warnings,
    }
    write_json(out_dir / "evidence.json", evidence)
    return evidence

