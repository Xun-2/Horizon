"""Publish Horizon daily pages through the GitHub REST API."""

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import html
import re
import time
from urllib.parse import quote

import httpx

from ..models import GitHubPagesConfig
from ..url_security import safe_request
from .daily_pages import DAILY_CSS, DailyPageBundle, render_index_page


class PagesPermissionError(RuntimeError):
    """Raised when GitHub Pages cannot be enabled with the configured PAT."""


@dataclass(frozen=True)
class PagePublishResult:
    success: bool
    urls: Mapping[str, str]
    error_type: str | None = None
    detail: str | None = None


RequestCallable = Callable[..., Awaitable[httpx.Response]]
SleepCallable = Callable[[float], Awaitable[None]]


class GitHubPagesPublisher:
    API_ROOT = "https://api.github.com"

    def __init__(
        self,
        config: GitHubPagesConfig,
        token: str,
        *,
        request: RequestCallable = safe_request,
        sleep: SleepCallable = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        client: httpx.AsyncClient | None = None,
    ):
        if not token:
            raise ValueError(f"Missing environment variable: {config.token_env}")
        self.config = config
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
            "User-Agent": "Horizon-Daily-Publisher",
        }

    def __repr__(self) -> str:
        return f"GitHubPagesPublisher(repository={self.config.repository!r})"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def publish(self, bundle: DailyPageBundle) -> PagePublishResult:
        try:
            await self._ensure_branch()
            await self._put_file("assets/horizon-daily.css", DAILY_CSS)
            for language in ("zh", "en"):
                path = f"daily/{bundle.date}/{language}.html"
                if path not in bundle.files or language not in bundle.urls:
                    raise ValueError(f"Daily page bundle is missing language: {language}")
                await self._put_file(path, bundle.files[path])

            dates = await self._list_dates()
            index = render_index_page([*dates, bundle.date])
            await self._put_file("index.html", index)
            await self._ensure_pages_enabled()
            for language in ("zh", "en"):
                await self._wait_public_url(
                    bundle.urls[language],
                    {
                        f'data-horizon-date="{html.escape(bundle.date, quote=True)}"',
                        f'data-language="{language}"',
                    },
                )
            return PagePublishResult(success=True, urls=dict(bundle.urls))
        except PagesPermissionError as exc:
            return PagePublishResult(
                success=False,
                urls={},
                error_type="pages_not_enabled",
                detail=self._redact(str(exc)),
            )
        except Exception as exc:
            return PagePublishResult(
                success=False,
                urls={},
                error_type="github_failure",
                detail=self._redact(f"{type(exc).__name__}: {exc}"),
            )

    async def publish_health_check(self) -> str:
        await self._ensure_branch()
        content = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Horizon delivery check</title></head>"
            '<body data-horizon-health="ok"><main><h1>Horizon delivery check</h1>'
            "<p>GitHub Pages 发布链路正常。</p></main></body></html>"
        )
        await self._put_file("health/setup-check.html", content)
        await self._ensure_pages_enabled()
        url = f"{self.config.site_url}/health/setup-check.html"
        await self._wait_public_url(url, {'data-horizon-health="ok"'})
        return url

    def _redact(self, value: str) -> str:
        redacted = value
        secrets = [f"Bearer {self._token}", self._token]
        for secret in sorted(secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, "<redacted>")
        return redacted

    def _api_url(self, path: str) -> str:
        return f"{self.API_ROOT}/repos/{self.config.repository}/{path.lstrip('/')}"

    async def _api_request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        headers = dict(self._headers)
        headers.update(kwargs.pop("headers", {}))
        return await self._request(
            self._client,
            method,
            self._api_url(path),
            headers=headers,
            **kwargs,
        )

    def _response_detail(self, response: httpx.Response) -> str:
        detail = f"GitHub HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("message"):
            detail += f": {payload['message']}"
        return self._redact(detail)

    async def _ensure_branch(self) -> None:
        branch = self.config.branch
        response = await self._api_request("GET", f"git/ref/heads/{branch}")
        if 200 <= response.status_code < 300:
            return
        if response.status_code != 404:
            raise RuntimeError(self._response_detail(response))

        source = await self._api_request(
            "GET", f"git/ref/heads/{self.config.source_branch}"
        )
        if not 200 <= source.status_code < 300:
            raise RuntimeError(self._response_detail(source))
        try:
            sha = source.json()["object"]["sha"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("GitHub source branch response has no SHA") from exc
        if not isinstance(sha, str) or not sha:
            raise RuntimeError("GitHub source branch response has no SHA")

        created = await self._api_request(
            "POST",
            "git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if not 200 <= created.status_code < 300:
            raise RuntimeError(self._response_detail(created))

    async def _get_file_sha(self, path: str) -> str | None:
        encoded_path = quote(path, safe="/")
        response = await self._api_request(
            "GET",
            f"contents/{encoded_path}",
            params={"ref": self.config.branch},
        )
        if response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise RuntimeError(self._response_detail(response))
        try:
            sha = response.json().get("sha")
        except (AttributeError, ValueError) as exc:
            raise RuntimeError("GitHub Contents response is invalid") from exc
        if not isinstance(sha, str) or not sha:
            raise RuntimeError("GitHub Contents response has no SHA")
        return sha

    async def _put_file(self, path: str, content: str) -> None:
        encoded_path = quote(path, safe="/")
        for attempt in range(3):
            sha = await self._get_file_sha(path)
            payload = {
                "message": f"Publish Horizon page: {path}",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": self.config.branch,
            }
            if sha:
                payload["sha"] = sha
            response = await self._api_request(
                "PUT",
                f"contents/{encoded_path}",
                json=payload,
            )
            if 200 <= response.status_code < 300:
                return
            if response.status_code in {409, 422} and attempt < 2:
                continue
            raise RuntimeError(self._response_detail(response))
        raise RuntimeError(f"GitHub Contents update failed: {path}")

    async def _list_dates(self) -> list[str]:
        response = await self._api_request(
            "GET",
            "contents/daily",
            params={"ref": self.config.branch},
        )
        if response.status_code == 404:
            return []
        if not 200 <= response.status_code < 300:
            raise RuntimeError(self._response_detail(response))
        try:
            entries = response.json()
        except ValueError as exc:
            raise RuntimeError("GitHub daily directory response is not JSON") from exc
        if not isinstance(entries, list):
            raise RuntimeError("GitHub daily directory response is invalid")
        return [
            entry["name"]
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("name"), str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["name"])
        ]

    async def _ensure_pages_enabled(self) -> None:
        response = await self._api_request("GET", "pages")
        if 200 <= response.status_code < 300:
            return
        if response.status_code == 403:
            raise self._pages_permission_error()
        if response.status_code != 404:
            raise RuntimeError(self._response_detail(response))

        created = await self._api_request(
            "POST",
            "pages",
            json={"source": {"branch": self.config.branch, "path": "/"}},
        )
        if created.status_code == 403:
            raise self._pages_permission_error()
        if not 200 <= created.status_code < 300:
            raise RuntimeError(self._response_detail(created))

    @staticmethod
    def _pages_permission_error() -> PagesPermissionError:
        return PagesPermissionError(
            "请在仓库 Settings -> Pages 中选择 gh-pages / root"
        )

    async def _wait_public_url(
        self,
        url: str,
        required_markers: set[str],
    ) -> None:
        deadline = self._monotonic() + self.config.verify_timeout_seconds
        while True:
            response = await self._request(self._client, "GET", url)
            if response.status_code == 200 and all(
                marker in response.text for marker in required_markers
            ):
                return
            if self._monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for public GitHub Pages URL: {url}")
            await self._sleep(self.config.poll_interval_seconds)
