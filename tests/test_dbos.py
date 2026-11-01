"""M7: the DBOS runtime around a workflow ($0, SQLite). The kill -9 behaviour is exercised by
scripts/crash_ingest.py --runtime dbos and scripts/server_restart_demo.py (real processes)."""

from litreview.config import get_settings
from litreview.durability import run_durable
from litreview.workflows.countdown import Countdown, CountdownStart, Tick


async def test_run_durable_keeps_the_run_id_only_until_success():
    run_id_file = get_settings().p2_runs_dir / "dbos_countdown_run_id"
    ticks: list[int] = []
    result = await run_durable(
        lambda rt: Countdown(runtime=rt, workflow_name="test-countdown-v1", timeout=30),
        CountdownStart(ticks=3, delay=0.01),
        run_id_file,
        on_event=lambda ev: ticks.append(ev.n) if isinstance(ev, Tick) else None,
    )
    assert result == {"ticks": 3} and ticks == [1, 2, 3]
    assert not run_id_file.exists()  # next call mints a new id instead of replaying this one
    assert (get_settings().p2_runs_dir / "dbos.sqlite").exists()  # the journal lives in runs/
