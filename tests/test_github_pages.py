import asyncio
import base64

import httpx
import pytest

from src.models import GitHubPagesConfig
from src.services.daily_pages import DailyPageBundle
from src.services.github_pages import GitHubPagesPublisher, PagesPermissionError


class ScriptedRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, client, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.request = httpx.Request(method, url)
        return response


class FakeClock:
    def __init__(self, values):
        self.values = list(values)
        self.last = self.values[-1]

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


async def _completed_sleep(seconds):
    assert seconds >= 0


def _publisher(request, *, monotonic=None):
    return GitHubPagesPublisher(
        GitHubPagesConfig(enabled=True),
        token="github-secret",
        request=request,
        sleep=_completed_sleep,
        monotonic=monotonic or FakeClock([0]),
        client=object(),
    )


def _bundle():
    return DailyPageBundle(
        date="2026-08-02",
        files={
            "daily/2026-08-02/zh.html": "zh",
            "daily/2026-08-02/en.html": "en",
        },
        urls={
            "zh": "https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html",
            "en": "https://xun-2.github.io/Horizon/daily/2026-08-02/en.html",
        },
    )


def test_publish_uses_sha_and_updates_index_last():
    request = ScriptedRequest(
        [
            httpx.Response(200, json={"ref": "refs/heads/gh-pages"}),
            httpx.Response(200, json={"sha": "old-css"}),
            httpx.Response(200, json={"content": {"sha": "new-css"}}),
            httpx.Response(200, json={"sha": "old-zh"}),
            httpx.Response(200, json={"content": {"sha": "new-zh"}}),
            httpx.Response(404),
            httpx.Response(201, json={"content": {"sha": "new-en"}}),
            httpx.Response(
                200, json=[{"name": "2026-08-01"}, {"name": "2026-08-02"}]
            ),
            httpx.Response(404),
            httpx.Response(201, json={"content": {"sha": "new-index"}}),
            httpx.Response(200, json={"html_url": "https://xun-2.github.io/Horizon"}),
            httpx.Response(
                200,
                text='<html data-horizon-date="2026-08-02" data-language="zh"></html>',
            ),
            httpx.Response(
                200,
                text='<html data-horizon-date="2026-08-02" data-language="en"></html>',
            ),
        ]
    )
    publisher = _publisher(request)

    result = asyncio.run(publisher.publish(_bundle()))

    assert result.success is True
    put_calls = [call for call in request.calls if call[0] == "PUT"]
    assert put_calls[-1][1].endswith("/contents/index.html")
    first_payload = put_calls[0][2]["json"]
    assert first_payload["sha"] == "old-css"
    assert base64.b64decode(first_payload["content"]).decode("utf-8")


def test_missing_branch_is_created_from_remote_main_sha():
    request = ScriptedRequest(
        [
            httpx.Response(404),
            httpx.Response(200, json={"object": {"sha": "main-sha"}}),
            httpx.Response(201, json={"ref": "refs/heads/gh-pages"}),
        ]
    )

    asyncio.run(_publisher(request)._ensure_branch())

    create_call = request.calls[-1]
    assert create_call[0] == "POST"
    assert create_call[2]["json"] == {
        "ref": "refs/heads/gh-pages",
        "sha": "main-sha",
    }


def test_sha_conflict_refetches_before_retry():
    request = ScriptedRequest(
        [
            httpx.Response(200, json={"sha": "stale-sha"}),
            httpx.Response(409, json={"message": "conflict"}),
            httpx.Response(200, json={"sha": "fresh-sha"}),
            httpx.Response(200, json={"content": {"sha": "written"}}),
        ]
    )

    asyncio.run(_publisher(request)._put_file("daily/2026-08-02/zh.html", "zh"))

    put_calls = [call for call in request.calls if call[0] == "PUT"]
    assert [call[2]["json"]["sha"] for call in put_calls] == [
        "stale-sha",
        "fresh-sha",
    ]


def test_pages_403_is_sanitized_and_actionable():
    request = ScriptedRequest(
        [httpx.Response(403, json={"message": "denied github-secret"})]
    )

    with pytest.raises(PagesPermissionError) as caught:
        asyncio.run(_publisher(request)._ensure_pages_enabled())

    detail = str(caught.value)
    assert "Settings -> Pages" in detail
    assert "gh-pages / root" in detail
    assert "github-secret" not in detail


def test_public_url_timeout_is_bounded():
    request = ScriptedRequest([httpx.Response(404), httpx.Response(404)])
    publisher = _publisher(request, monotonic=FakeClock([0, 0, 121]))

    with pytest.raises(TimeoutError):
        asyncio.run(
            publisher._wait_public_url(
                "https://xun-2.github.io/Horizon/health/setup-check.html",
                {'data-horizon-health="ok"'},
            )
        )


async def _unexpected_request(client, method, url, **kwargs):
    raise AssertionError(f"unexpected network request: {method} {url}")


class ControlledPublisher(GitHubPagesPublisher):
    def __init__(self, fail_path=None):
        super().__init__(
            GitHubPagesConfig(enabled=True),
            token="github-secret",
            request=_unexpected_request,
            sleep=_completed_sleep,
            monotonic=FakeClock([0]),
            client=object(),
        )
        self.fail_path = fail_path
        self.uploaded = []

    async def _ensure_branch(self):
        return None

    async def _put_file(self, path, content):
        if path == self.fail_path:
            raise RuntimeError("controlled upload failure")
        self.uploaded.append(path)

    async def _list_dates(self):
        return ["2026-08-02"]

    async def _ensure_pages_enabled(self):
        return None

    async def _wait_public_url(self, url, required_markers):
        return None


def test_language_write_failure_skips_index():
    publisher = ControlledPublisher(fail_path="daily/2026-08-02/en.html")

    result = asyncio.run(publisher.publish(_bundle()))

    assert result.success is False
    assert "index.html" not in publisher.uploaded


def test_health_check_does_not_touch_index():
    publisher = ControlledPublisher()

    url = asyncio.run(publisher.publish_health_check())

    assert url.endswith("/health/setup-check.html")
    assert publisher.uploaded == ["health/setup-check.html"]


def test_missing_token_reports_only_environment_variable_name():
    with pytest.raises(ValueError) as caught:
        GitHubPagesPublisher(GitHubPagesConfig(enabled=True), token="")

    assert "HORIZON_GITHUB_TOKEN" in str(caught.value)
