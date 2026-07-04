from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import InternConfig


@dataclass
class InternResponse:
    content: str
    raw: dict[str, Any]


class InternClient:
    def __init__(self, config: InternConfig, timeout: int = 180) -> None:
        self.config = config
        self.timeout = timeout
        self.max_retries = 3

    def enabled(self) -> bool:
        return bool(self.config.api_key)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        thinking_mode: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> InternResponse:
        if not self.config.api_key:
            raise RuntimeError("INTERN_S2_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "thinking_mode": thinking_mode,
        }
        if tools:
            payload["tools"] = tools

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.chat_url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        started = time.time()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise RuntimeError(f"Intern-S2 HTTP {exc.code}: {err_body}") from exc
                last_error = exc
            except urllib.error.URLError as exc:
                if attempt >= self.max_retries:
                    raise RuntimeError(f"Intern-S2 request failed: {exc}") from exc
                last_error = exc
            time.sleep(min(2 ** attempt, 8))
        else:
            raise RuntimeError(f"Intern-S2 request failed after retries: {last_error}")

        raw = json.loads(body)
        try:
            content = raw["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, AttributeError) as exc:
            raise RuntimeError(f"Unexpected Intern-S2 response: {raw}") from exc
        raw["_elapsed_seconds"] = round(time.time() - started, 3)
        return InternResponse(content=content, raw=raw)
