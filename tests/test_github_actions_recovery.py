import importlib
import sys

import pytest

from src.services.github_actions import DailyWorkflowState, GitHubActionsError
from scripts import github_actions_recovery as recovery


@pytest.fixture(autouse=True)
def _do_not_load_real_dotenv(monkeypatch):
    monkeypatch.setattr(recovery, "load_dotenv", lambda **kwargs: False)


def test_recovery_script_does_not_depend_on_untracked_environment_module(
    monkeypatch,
):
    monkeypatch.setitem(sys.modules, "src.environment", None)

    importlib.reload(recovery)


class FakeClient:
    def __init__(
        self,
        state,
        *,
        terminal_state=DailyWorkflowState.SUCCESS,
        error=None,
    ):
        self.state = state
        self.terminal_state = terminal_state
        self.error = error
        self.daily_calls = []
        self.wait_calls = []
        self.dispatch_calls = []
        self.closed = False

    async def daily_state(self, business_date, *, exclude_run_id=None):
        self.daily_calls.append((business_date, exclude_run_id))
        if self.error is not None:
            raise self.error
        return self.state

    async def wait_until_terminal(
        self,
        business_date,
        *,
        timeout_seconds=1800,
        poll_interval_seconds=15,
    ):
        self.wait_calls.append((business_date, timeout_seconds, poll_interval_seconds))
        return self.terminal_state

    async def dispatch(self, ref="main"):
        self.dispatch_calls.append(ref)

    async def aclose(self):
        self.closed = True


def _install_client(monkeypatch, client):
    monkeypatch.setattr(recovery, "_build_client", lambda: client)


def test_guard_skips_when_today_already_succeeded(monkeypatch, capsys):
    client = FakeClient(DailyWorkflowState.SUCCESS)
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["guard", "--date", "2026-08-03", "--exclude-run-id", "12"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "skip"
    assert client.daily_calls[0][1] == 12
    assert client.closed is True


def test_guard_runs_when_today_has_no_success(monkeypatch, capsys):
    client = FakeClient(DailyWorkflowState.MISSING)
    _install_client(monkeypatch, client)

    exit_code = recovery.main(["guard", "--date", "2026-08-03"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "run"


def test_recover_before_0722_is_noop(monkeypatch, capsys):
    monkeypatch.setattr(
        recovery,
        "_build_client",
        lambda: (_ for _ in ()).throw(AssertionError("client should not be built")),
    )

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T07:10:00+08:00"]
    )

    assert exit_code == 0
    assert '"action": "before_schedule"' in capsys.readouterr().out


def test_recover_successful_day_is_noop(monkeypatch, capsys):
    client = FakeClient(DailyWorkflowState.SUCCESS)
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T08:00:00+08:00"]
    )

    assert exit_code == 0
    assert client.dispatch_calls == []
    assert '"action": "already_successful"' in capsys.readouterr().out


def test_recover_waits_for_active_success(monkeypatch, capsys):
    client = FakeClient(
        DailyWorkflowState.ACTIVE,
        terminal_state=DailyWorkflowState.SUCCESS,
    )
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        [
            "recover",
            "--now",
            "2026-08-03T08:00:00+08:00",
            "--wait-timeout-seconds",
            "60",
        ]
    )

    assert exit_code == 0
    assert client.wait_calls[0][1] == 60
    assert client.dispatch_calls == []
    assert '"action": "active_success"' in capsys.readouterr().out


def test_recover_dispatches_after_active_failure(monkeypatch, capsys):
    client = FakeClient(
        DailyWorkflowState.ACTIVE,
        terminal_state=DailyWorkflowState.FAILED,
    )
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T08:00:00+08:00"]
    )

    assert exit_code == 0
    assert client.dispatch_calls == ["main"]
    assert '"action": "dispatched"' in capsys.readouterr().out


def test_recover_dispatches_failed_or_missing_day(monkeypatch, capsys):
    for state in (DailyWorkflowState.FAILED, DailyWorkflowState.MISSING):
        client = FakeClient(state)
        _install_client(monkeypatch, client)

        exit_code = recovery.main(
            ["recover", "--now", "2026-08-03T08:00:00+08:00"]
        )

        assert exit_code == 0
        assert client.dispatch_calls == ["main"]
        assert '"action": "dispatched"' in capsys.readouterr().out


def test_recover_api_failure_is_redacted(monkeypatch, capsys):
    token = "local-github-token"
    monkeypatch.setenv("HORIZON_GITHUB_TOKEN", token)
    client = FakeClient(
        DailyWorkflowState.MISSING,
        error=GitHubActionsError(f"remote echoed {token}"),
    )
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T08:00:00+08:00"]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert token not in output.out + output.err
    assert "<redacted>" in output.err
