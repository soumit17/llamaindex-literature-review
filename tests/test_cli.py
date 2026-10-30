from typer.testing import CliRunner

from litreview.cli import app

runner = CliRunner()


def test_hello_with_debug_steps_shows_each_step_running():
    out = runner.invoke(app, ["hello", "Ada", "--rounds", "2", "--debug-steps"]).output

    assert "Hello Ada!" in out
    assert out.count("tick     running") == 2


def test_tiny():
    assert "HELLO WORKFLOWS!" in runner.invoke(app, ["tiny"]).output


def test_smoke_refuses_without_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    result = runner.invoke(app, ["smoke"])

    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output


def test_cost_on_empty_ledger():
    assert "0 calls, $0.000000 of $10.00 cap" in runner.invoke(app, ["cost"]).output
