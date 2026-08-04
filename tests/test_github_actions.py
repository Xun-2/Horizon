import asyncio
from datetime import date

import httpx
import pytest

from src.services.github_actions import (
    DailyWorkflowState,
    GitHubActionsClient,
    GitHubActionsError,
)


class ScriptedRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, client, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.request = httpx.Request(method, url)
        return response


async def _completed_sleep(seconds):
    assert seconds >= 0


def _run(run_id, *, status, conclusion):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
    }


def _client_with_responses(responses, *, token="github-token"):
    request = ScriptedRequest(responses)
    client = GitHubActionsClient(
        repository="Xun-2/Horizon",
        workflow="daily-summary.yml",
        token=token,
        request=request,
        sleep=_completed_sleep,
        monotonic=lambda: 0.0,
        client=object(),
    )
    return client, request


def _client_with_runs(runs):
    client, _ = _client_with_responses(
        [httpx.Response(200, json={"workflow_runs": runs})]
    )
    return client


def test_daily_state_prefers_success_and_excludes_current_run():
    client = _client_with_runs(
        [
            _run(100, status="in_progress", conclusion=None),
            _run(99, status="completed", conclusion="success"),
        ]
    )

    state = asyncio.run(
        client.daily_state(date(2026, 8, 3), exclude_run_id=100)
    )

    assert state == DailyWorkflowState.SUCCESS


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([_run(1, status="queued", conclusion=None)], DailyWorkflowState.ACTIVE),
        ([_run(1, status="completed", conclusion="failure")], DailyWorkflowState.FAILED),
        ([], DailyWorkflowState.MISSING),
    ],
)
def test_daily_state_classifies_runs(runs, expected):
    assert asyncio.run(_client_with_runs(runs).daily_state(date(2026, 8, 3))) == expected


def test_daily_state_queries_from_beijing_midnight():
    client, request = _client_with_responses(
        [httpx.Response(200, json={"workflow_runs": []})]
    )

    asyncio.run(client.daily_state(date(2026, 8, 3)))

    method, url, kwargs = request.calls[0]
    assert method == "GET"
    assert url.endswith(
        "/repos/Xun-2/Horizon/actions/workflows/daily-summary.yml/runs"
    )
    assert kwargs["params"]["created"] == ">=2026-08-02T16:00:00Z"


def test_dispatch_posts_main_ref_and_requires_http_204():
    client, request = _client_with_responses([httpx.Response(204)])

    asyncio.run(client.dispatch())

    method, url, kwargs = request.calls[0]
    assert method == "POST"
    assert url.endswith(
        "/repos/Xun-2/Horizon/actions/workflows/daily-summary.yml/dispatches"
    )
    assert kwargs["json"] == {"ref": "main"}


def test_github_error_redacts_configured_token():
    token = "github-token-value"
    client, _ = _client_with_responses(
        [httpx.Response(403, json={"message": f"denied {token}"})],
        token=token,
    )

    with pytest.raises(GitHubActionsError) as exc_info:
        asyncio.run(client.dispatch())

    assert token not in str(exc_info.value)
    assert "<redacted>" in str(exc_info.value)
