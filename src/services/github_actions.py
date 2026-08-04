"""Query and dispatch the Horizon daily GitHub Actions workflow."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
import time as time_module

import httpx

from ..url_security import safe_request


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
RequestCallable = Callable[
    [httpx.AsyncClient, str, str],
    Awaitable[httpx.Response],
]
SleepCallable = Callable[[float], Awaitable[None]]


class DailyWorkflowState(str, Enum):
    SUCCESS = "success"
    ACTIVE = "active"
    FAILED = "failed"
    MISSING = "missing"


class GitHubActionsError(RuntimeError):
    pass


class GitHubActionsClient:
    API_ROOT = "https://api.github.com"

    def __init__(
        self,
        repository: str,
        workflow: str,
        token: str,
        *,
        request: RequestCallable = safe_request,
        sleep: SleepCallable = asyncio.sleep,
        monotonic: Callable[[], float] = time_module.monotonic,
        client: httpx.AsyncClient | None = None,
    ):
        if repository != "Xun-2/Horizon":
            raise ValueError("repository must be Xun-2/Horizon")
        if workflow != "daily-summary.yml":
            raise ValueError("workflow must be daily-summary.yml")
        if not token:
            raise ValueError("HORIZON_GITHUB_TOKEN is required")
        self._repository = repository
        self._workflow = workflow
        self._token = token
        self._request = request
        self._sleep = sleep
        self._monotonic = monotonic
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Horizon-Daily-Recovery",
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _redact(self, value: str) -> str:
        redacted = value
        for secret in (f"Bearer {self._token}", self._token):
            redacted = redacted.replace(secret, "<redacted>")
        return redacted

    def _api_url(self, path: str) -> str:
        return f"{self.API_ROOT}/repos/{self._repository}/{path.lstrip('/')}"

    async def _api_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = dict(self._headers)
        headers.update(kwargs.pop("headers", {}))
        try:
            return await self._request(
                self._client,
                method,
                self._api_url(path),
                headers=headers,
                **kwargs,
            )
        except Exception as exc:
            raise GitHubActionsError(
                self._redact(f"{type(exc).__name__}: {exc}")
            ) from exc

    def _response_detail(self, response: httpx.Response) -> str:
        detail = f"GitHub HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("message"):
            detail += f": {payload['message']}"
        return self._redact(detail)

    async def daily_state(
        self,
        business_date: date,
        *,
        exclude_run_id: int | None = None,
    ) -> DailyWorkflowState:
        midnight = datetime.combine(business_date, time.min, tzinfo=BEIJING)
        created_from = midnight.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = await self._api_request(
            "GET",
            f"actions/workflows/{self._workflow}/runs",
            params={"created": f">={created_from}", "per_page": 100},
        )
        if not 200 <= response.status_code < 300:
            raise GitHubActionsError(self._response_detail(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubActionsError(
                "GitHub workflow-runs response is not JSON"
            ) from exc
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise GitHubActionsError("GitHub workflow-runs response is invalid")
        relevant = [
            run
            for run in runs
            if isinstance(run, dict)
            and (exclude_run_id is None or run.get("id") != exclude_run_id)
        ]
        if any(
            run.get("status") == "completed"
            and run.get("conclusion") == "success"
            for run in relevant
        ):
            return DailyWorkflowState.SUCCESS
        if any(run.get("status") != "completed" for run in relevant):
            return DailyWorkflowState.ACTIVE
        if relevant:
            return DailyWorkflowState.FAILED
        return DailyWorkflowState.MISSING

    async def wait_until_terminal(
        self,
        business_date: date,
        *,
        timeout_seconds: int = 1800,
        poll_interval_seconds: int = 15,
    ) -> DailyWorkflowState:
        deadline = self._monotonic() + timeout_seconds
        while True:
            state = await self.daily_state(business_date)
            if state != DailyWorkflowState.ACTIVE:
                return state
            if self._monotonic() >= deadline:
                raise GitHubActionsError(
                    "Timed out waiting for active daily workflow"
                )
            await self._sleep(poll_interval_seconds)

    async def dispatch(self, ref: str = "main") -> None:
        response = await self._api_request(
            "POST",
            f"actions/workflows/{self._workflow}/dispatches",
            json={"ref": ref},
        )
        if response.status_code != 204:
            raise GitHubActionsError(self._response_detail(response))
