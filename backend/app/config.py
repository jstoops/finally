"""Environment configuration (PLAN §5).

Local dev loads `<repo>/.env` with python-dotenv; variables already set in the
environment win. In Docker there is no `.env` file and compose injects them.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

DEFAULT_DB_PATH = REPO_DIR / "db" / "finally.db"
DEFAULT_STATIC_DIR = BACKEND_DIR / "static"


def load_env() -> None:
    """Load `<repo>/.env` if it exists, without overriding existing variables."""
    env_file = REPO_DIR / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def get_db_path() -> str:
    """SQLite file path: `DB_PATH`, or `<repo>/db/finally.db`."""
    return _env("DB_PATH") or str(DEFAULT_DB_PATH)


def get_static_dir() -> str:
    """Static frontend directory: `STATIC_DIR`, or `backend/static`."""
    return _env("STATIC_DIR") or str(DEFAULT_STATIC_DIR)


def llm_mock_enabled() -> bool:
    """True when `LLM_MOCK=true` (case-insensitive)."""
    return _env("LLM_MOCK").lower() == "true"


def openrouter_api_key() -> str | None:
    """The OpenRouter API key, or None if unset or blank."""
    return _env("OPENROUTER_API_KEY") or None
