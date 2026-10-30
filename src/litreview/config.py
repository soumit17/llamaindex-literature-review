"""Process-wide settings, read from the environment and `.env` (see `.env.example`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    anthropic_api_key: str = ""
    p2_spend_cap_usd: float = 10.0
    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Tests point this at a tmp dir so the real cost ledger never sees fake calls.
    p2_runs_dir: Path = PROJECT_ROOT / "runs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
