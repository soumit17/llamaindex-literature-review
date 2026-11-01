"""Run by tests/test_telemetry.py in a subprocess (telemetry registers process-wide handlers):
a scripted review with tracing to the pytest tmp dir. Subprocess-safe imports only."""

import asyncio

from litreview.config import get_settings
from litreview.telemetry import setup_telemetry
from tests.review_env import run_review, scripted


async def main() -> None:
    assert "pytest" in str(get_settings().p2_runs_dir)
    setup_telemetry()
    many = {
        "sub_questions": [{"text": f"Question {i}?", "rationale": "r"} for i in range(5)],
        "scope_note": "s",
    }
    import json

    result, _, _ = await run_review(scripted(script={"[PLAN]": json.dumps(many)}))
    print(result.markdown_path)


if __name__ == "__main__":
    asyncio.run(main())
