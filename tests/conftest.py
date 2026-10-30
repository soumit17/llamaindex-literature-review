"""$0 test guards (spec §16.1): no network, no real model, no writes to the real cost ledger.

Network is blocked by pytest-socket (see `addopts` in pyproject.toml).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest

# Set before any litreview import so Settings never sees the developer's real key or ledger.
os.environ["ANTHROPIC_API_KEY"] = "sk-test-dummy"
os.environ.pop("P2_RUNS_DIR", None)
os.environ.pop("P2_DATA_DIR", None)
os.environ["P2_RETRY_TIME_SCALE"] = "0"

from llama_index.core import Settings  # noqa: E402
from llama_index.core.embeddings import MockEmbedding  # noqa: E402
from llama_index.core.llms import MockLLM  # noqa: E402
from workflows.resource import ResourceManager  # noqa: E402

from litreview.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("P2_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("P2_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    Settings.llm = MockLLM(max_tokens=64)
    Settings.embed_model = MockEmbedding(embed_dim=384)
    yield
    get_settings.cache_clear()


async def override_resources(overrides: dict[Callable[..., Any], Any]) -> ResourceManager:
    """Build a ResourceManager with fakes pre-seeded under each factory's name.

    Pass it as `MyWorkflow(resource_manager=...)`. The framework looks a cached resource up by its
    factory's `__qualname__` before calling the factory, so the real factory never runs.
    """
    manager = ResourceManager()
    for factory, fake in overrides.items():
        await manager.set(factory.__qualname__, fake)
    return manager
