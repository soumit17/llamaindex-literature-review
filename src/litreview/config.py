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
    # Tests point these at a tmp dir so the real cost ledger and corpus never see fake data.
    p2_runs_dir: Path = PROJECT_ROOT / "runs"
    p2_data_dir: Path = PROJECT_ROOT / "data"
    p2_cache_dir: Path = PROJECT_ROOT / ".cache"  # downloaded models, NLTK data
    p2_out_dir: Path = PROJECT_ROOT / "out"  # generated reviews
    p2_llm_profile: str = "dev"  # "final" makes the section writer use the Sonnet block of llm.json
    # Multiplies every retry delay; tests set 0 so retry paths run instantly.
    p2_retry_time_scale: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
