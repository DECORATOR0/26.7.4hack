from __future__ import annotations

import base64
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def seconds_to_timestamp(seconds: float, srt: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - int(seconds)) * 1000)
    if srt:
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
    return f"{hours:02}:{minutes:02}:{secs:02}"


def timestamp_to_seconds(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    if text.isdigit():
        return float(text)
    parts = re.split(r"[:,]", text)
    try:
        if len(parts) >= 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return 0.0
    minute_match = re.search(r"(\d+)", text)
    if minute_match:
        return float(minute_match.group(1)) * 60
    return 0.0


def image_to_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    if suffix == "jpg":
        suffix = "jpeg"
    return f"data:image/{suffix};base64,{data}"


def extract_json_object(text: str, required_keys: Iterable[str] | None = None) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    required = tuple(required_keys or ())

    for candidate in _json_text_candidates(cleaned):
        for variant in _json_repair_variants(candidate):
            try:
                value = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if _has_required_keys(value, required):
                return value

    fenced = re.findall(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    for candidate in reversed(fenced):
        for variant in _json_repair_variants(candidate.strip()):
            try:
                value = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if _has_required_keys(value, required):
                return value

    decoder = json.JSONDecoder()
    parsed_values = []
    for idx, char in enumerate(cleaned):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[idx:])
            if _has_required_keys(value, required):
                parsed_values.append(value)
        except json.JSONDecodeError:
            continue
    if parsed_values:
        return parsed_values[-1]

    candidates = []
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        start = cleaned.find(open_char)
        end = cleaned.rfind(close_char)
        if start >= 0 and end > start:
            candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        for variant in _json_repair_variants(candidate):
            try:
                value = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if _has_required_keys(value, required):
                return value
    if required:
        raise ValueError(f"Model response does not contain valid JSON with required keys: {', '.join(required)}")
    raise ValueError("Model response does not contain valid JSON")


def _has_required_keys(value: Any, required_keys: tuple[str, ...]) -> bool:
    if not required_keys:
        return True
    return isinstance(value, dict) and all(key in value for key in required_keys)


def _json_text_candidates(text: str) -> list[str]:
    candidates = [text]
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        start = text.find(open_char)
        end = text.rfind(close_char)
        if start >= 0:
            if end > start:
                candidates.append(text[start : end + 1])
            else:
                candidates.append(text[start:])
    return list(dict.fromkeys(candidate.strip() for candidate in candidates if candidate.strip()))


def _json_repair_variants(text: str) -> list[str]:
    variants = [text]
    repaired = _repair_json_text(text)
    if repaired != text:
        variants.append(repaired)
    return variants


def _repair_json_text(text: str) -> str:
    repaired = text.strip().lstrip("\ufeff")
    repaired = _normalize_json_structure_chars(repaired)
    repaired = _escape_newlines_inside_strings(repaired)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = _close_unfinished_json(repaired)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _normalize_json_structure_chars(text: str) -> str:
    output: list[str] = []
    in_string = False
    escape = False
    outside_map = {
        "：": ":",
        "，": ",",
        "｛": "{",
        "｝": "}",
        "［": "[",
        "］": "]",
        "＂": '"',
        "“": '"',
        "”": '"',
    }
    for char in text:
        if in_string:
            output.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        char = outside_map.get(char, char)
        output.append(char)
        if char == '"':
            in_string = True
            escape = False
    return "".join(output)


def _escape_newlines_inside_strings(text: str) -> str:
    output: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if in_string and char in "\r\n":
            output.append("\\n")
            continue
        output.append(char)
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            escape = False
    return "".join(output)


def _close_unfinished_json(text: str) -> str:
    output: list[str] = []
    stack: list[str] = []
    in_string = False
    escape = False
    for char in text:
        output.append(char)
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            escape = False
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if stack and stack[-1] == char:
                stack.pop()
    if in_string:
        output.append('"')
    output.extend(reversed(stack))
    return "".join(output)
