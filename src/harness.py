from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .config import load_intern_config
from .evidence import build_evidence, transcribe_audio
from .formatters import (
    fallback_commentary,
    fallback_events,
    local_fact_check,
    normalize_events,
    write_highlights,
    write_srt,
)
from .intern_client import InternClient
from .io_utils import ensure_dir, extract_json_object, image_to_data_url, read_json, write_json, write_text
from .prompts import SYSTEM_PROMPT, commentary_prompt, event_extraction_prompt, fact_check_prompt
from .video_tools import preprocess_video


@dataclass
class HarnessOptions:
    video_path: Path
    out_dir: Path
    match_info_path: Path | None = None
    frame_interval: float = 120.0
    max_frames: int = 48
    vision_frames: int = 8
    temperature: float = 0.3
    fast_demo: bool = False
    no_model: bool = False


class RunLogger:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, message: str) -> None:
        self.items.append(message)

    def section(self, title: str) -> None:
        self.items.append(f"\n## {title}")

    def write(self, path: Path) -> None:
        write_text(path, "# Harness Run Log\n\n" + "\n".join(f"- {item}" if not item.startswith("\n##") else item for item in self.items))


class WorldCupHarness:
    def __init__(self, options: HarnessOptions) -> None:
        self.options = options
        self.out_dir = ensure_dir(options.out_dir)
        self.logger = RunLogger()
        self.client = InternClient(load_intern_config())

    def run(self) -> Path:
        self._validate_inputs()
        match_info = self._load_match_info()
        write_json(self.out_dir / "match_info.json", match_info)

        self.logger.section("Stage 1: 视频预处理")
        artifacts = preprocess_video(
            self.options.video_path,
            self.out_dir,
            interval_seconds=self.options.frame_interval,
            max_frames=self.options.max_frames,
            vision_frames=self.options.vision_frames,
            fast_demo=self.options.fast_demo,
        )
        self.logger.add(f"视频元信息已写出：video_metadata.json，抽帧数量 {len(artifacts.frame_index)}。")
        if artifacts.audio_path:
            self.logger.add(f"音频已提取：{artifacts.audio_path}")
        for warning in artifacts.warnings:
            self.logger.add(f"预处理告警：{warning}")

        self.logger.section("Stage 2: 多模态证据提取")
        transcript = transcribe_audio(artifacts.audio_path, self.out_dir)
        if transcript.get("available"):
            self.logger.add(f"ASR 可用：{transcript.get('method')}，片段数 {len(transcript.get('segments', []))}。")
        else:
            self.logger.add(f"ASR 跳过：{transcript.get('warning')}")
        evidence = build_evidence(artifacts, transcript, match_info, self.out_dir)
        self.logger.add("证据摘要已写出：evidence.json")

        self.logger.section("Stage 3: 关键事件识别与时间线构建")
        events = self._extract_events(match_info, evidence)
        write_json(self.out_dir / "events.json", events)
        self.logger.add(f"事件时间线已写出：events.json，事件数量 {len(events.get('events', []))}。")

        self.logger.section("Stage 4: 解说脚本生成")
        commentary = self._write_commentary(match_info, events)
        write_text(self.out_dir / "commentary.md", commentary)
        self.logger.add("完整解说脚本已写出：commentary.md")

        self.logger.section("Stage 5: 校验与输出")
        fact_check = self._fact_check(match_info, events, commentary)
        write_json(self.out_dir / "fact_check.json", fact_check)
        write_srt(self.out_dir / "subtitles.srt", events)
        write_highlights(self.out_dir / "highlights.json", events)
        self.logger.add("校验结果已写出：fact_check.json")
        self.logger.add("字幕已写出：subtitles.srt")
        self.logger.add("集锦片段清单已写出：highlights.json")
        self.logger.write(self.out_dir / "run_log.md")
        return self.out_dir

    def _validate_inputs(self) -> None:
        if not self.options.video_path.exists():
            raise FileNotFoundError(f"Video not found: {self.options.video_path}")

    def _load_match_info(self) -> dict[str, Any]:
        if self.options.match_info_path:
            return read_json(self.options.match_info_path)
        default_path = Path("examples") / "match_info.germany_curacao.json"
        if default_path.exists():
            return read_json(default_path)
        return {
            "competition": "2026 年美加墨世界杯 E 组第 1 轮",
            "match_name": "德国 vs 库拉索",
            "home_team": "德国",
            "away_team": "库拉索",
            "expected_score": "7-1",
            "style": "激情、专业、克制，不编造没有证据的球员姓名。",
        }

    def _extract_events(self, match_info: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
        fallback = normalize_events(
            fallback_events(match_info, evidence.get("video_metadata", {}).get("duration_seconds", 0.0)),
            match_info,
        )
        if self.options.no_model or not self.client.enabled():
            self.logger.add("未调用模型：使用兜底事件时间线。")
            return fallback

        prompt = event_extraction_prompt(evidence)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._build_multimodal_content(prompt, evidence)},
        ]
        try:
            response = self.client.chat(
                messages,
                temperature=self.options.temperature,
                max_tokens=8000,
                thinking_mode=False,
            )
            self._write_raw_response("events_response.json", response.raw, response.content)
            parsed = extract_json_object(response.content)
            events = normalize_events(parsed, match_info)
            if self._events_scoreline_valid(match_info, events):
                return events
            self.logger.add("模型事件时间线未满足最终比分进球数量，使用兜底事件时间线。")
            return fallback
        except Exception as exc:
            self.logger.add(f"多模态事件识别失败，改用文本证据重试：{exc}")

        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = self.client.chat(
                messages,
                temperature=self.options.temperature,
                max_tokens=8000,
                thinking_mode=False,
            )
            self._write_raw_response("events_response_text_only.json", response.raw, response.content)
            parsed = extract_json_object(response.content)
            events = normalize_events(parsed, match_info)
            if self._events_scoreline_valid(match_info, events):
                return events
            self.logger.add("文本事件时间线未满足最终比分进球数量，使用兜底事件时间线。")
            return fallback
        except Exception as exc:
            self.logger.add(f"文本事件识别也失败，使用兜底事件时间线：{exc}")
            self._write_error("events_error.txt", exc)
            return fallback

    def _write_commentary(self, match_info: dict[str, Any], events: dict[str, Any]) -> str:
        fallback = fallback_commentary(match_info, events)
        if self.options.no_model or not self.client.enabled():
            self.logger.add("未调用模型：使用兜底解说稿。")
            return fallback
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": commentary_prompt(match_info, events)},
            ]
            response = self.client.chat(messages, temperature=self.options.temperature, max_tokens=8000)
            self._write_raw_response("commentary_response.json", response.raw, response.content)
            finish_reason = response.raw.get("choices", [{}])[0].get("finish_reason")
            content = response.content.strip()
            if finish_reason == "length":
                self.logger.add("模型解说输出被截断，使用兜底解说稿。")
                return fallback
            if not self._commentary_covers_events(events, content):
                self.logger.add("模型解说未覆盖全部关键事件，使用兜底解说稿。")
                return fallback
            return content or fallback
        except Exception as exc:
            self.logger.add(f"解说生成失败，使用兜底解说稿：{exc}")
            self._write_error("commentary_error.txt", exc)
            return fallback

    def _fact_check(self, match_info: dict[str, Any], events: dict[str, Any], commentary: str) -> dict[str, Any]:
        local = local_fact_check(match_info, events, commentary)
        result = {
            "local_check": local,
            "model_check": None,
            "passed": local.get("passed", False),
        }
        if self.options.no_model or not self.client.enabled():
            return result
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": fact_check_prompt(match_info, events, commentary)},
            ]
            response = self.client.chat(messages, temperature=0.1, max_tokens=4000, thinking_mode=False)
            self._write_raw_response("fact_check_response.json", response.raw, response.content)
            parsed = extract_json_object(response.content)
            result["model_check"] = parsed
            result["passed"] = bool(local.get("passed")) and bool(parsed.get("passed", False))
            return result
        except Exception as exc:
            self.logger.add(f"模型校验失败，仅保留本地校验：{exc}")
            self._write_error("fact_check_error.txt", exc)
            return result

    def _build_multimodal_content(self, prompt: str, evidence: dict[str, Any]) -> str | list[dict[str, Any]]:
        selected = evidence.get("frame_sampling", {}).get("selected_frames", [])
        image_paths = []
        for item in selected[: self.options.vision_frames]:
            path = Path(item.get("selected_path") or item.get("path") or "")
            if path.exists():
                image_paths.append(self._prepare_llm_image(path))

        if not image_paths:
            return prompt

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for idx, path in enumerate(image_paths, start=1):
            content.append({"type": "text", "text": f"关键帧 {idx}: {path.name}"})
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(path)}})
        return content

    def _prepare_llm_image(self, path: Path) -> Path:
        llm_dir = ensure_dir(self.out_dir / "frames" / "llm")
        dst = llm_dir / path.name
        if dst.exists() and self.options.fast_demo:
            return dst
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((768, 768))
            image.save(dst, format="JPEG", quality=78, optimize=True)
        return dst

    def _events_scoreline_valid(self, match_info: dict[str, Any], events: dict[str, Any]) -> bool:
        check = local_fact_check(match_info, events, str(match_info.get("expected_score", "")))
        return not any(issue.get("severity") == "high" for issue in check.get("issues", []))

    def _commentary_covers_events(self, events: dict[str, Any], commentary: str) -> bool:
        if not commentary:
            return False
        missing = []
        for event in events.get("events", []):
            if event.get("event_type") != "goal":
                continue
            minute = str(event.get("minute", "")).replace("'", "")
            score = str(event.get("score_after", ""))
            if score and score in commentary:
                continue
            if minute and minute in commentary:
                continue
            missing.append(event.get("event_id"))
        return not missing

    def _write_raw_response(self, filename: str, raw: dict[str, Any], content: str) -> None:
        raw_dir = ensure_dir(self.out_dir / "raw_model_responses")
        safe_raw = dict(raw)
        safe_raw.pop("usage", None)
        write_json(raw_dir / filename, {"raw": safe_raw, "content": content})

    def _write_error(self, filename: str, exc: Exception) -> None:
        write_text(
            self.out_dir / "raw_model_responses" / filename,
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
