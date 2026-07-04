from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class InternConfig:
    api_base: str
    api_key: str
    model: str

    @property
    def chat_url(self) -> str:
        base = self.api_base.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def load_intern_config() -> InternConfig:
    load_dotenv()
    return InternConfig(
        api_base=os.getenv("INTERN_S2_API_BASE", "https://chat.intern-ai.org.cn/api/v1"),
        api_key=os.getenv("INTERN_S2_API_KEY", ""),
        model=os.getenv("INTERN_S2_MODEL", "intern-s2-preview"),
    )

