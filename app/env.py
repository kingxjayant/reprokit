"""Environment loading and configuration.

Loads a local ``.env`` if present (no third-party dependency), then exposes a
small immutable config object. Nothing here is ever echoed back to a client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Parse KEY=VALUE lines from .env into os.environ (existing vars win)."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # strip inline comments that follow an unquoted value
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    app_env: str
    base_url: str
    database_url: str
    github_token: str | None
    llm_provider: str
    openai_api_key: str | None
    llm_model: str
    retention_days: int

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"

    @property
    def use_postgres(self) -> bool:
        return bool(self.database_url)


def get_config() -> Config:
    load_dotenv()
    return Config(
        app_env=os.getenv("APP_ENV", "development"),
        base_url=os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        github_token=(os.getenv("GITHUB_TOKEN") or "").strip() or None,
        llm_provider=(os.getenv("LLM_PROVIDER") or "none").strip(),
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip() or None,
        llm_model=(os.getenv("LLM_MODEL") or "gpt-4.1-mini").strip(),
        retention_days=int(os.getenv("REPORT_RETENTION_DAYS") or "90"),
    )
