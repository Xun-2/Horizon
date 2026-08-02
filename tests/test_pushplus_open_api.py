import asyncio

import httpx
import pytest

from src.services.pushplus import PushPlusClawBotClient, PushPlusDeliveryState


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


def _client(responses, clock=None):
    return PushPlusClawBotClient(
        endpoint="https://www.pushplus.plus/send",
        user_token="user-token",
        secret_key="secret-key",
        request=ScriptedRequest(responses),
        sleep=_completed_sleep,
        monotonic=clock or FakeClock([0]),
        client=object(),
    )


def test_clawbot_sends_fixed_plain_text_and_waits_for_status_two():
    request = ScriptedRequest(
        [
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": 1}}
            ),
            httpx.Response(200, json={"code": 200, "data": "receipt-1"}),
            httpx.Response(
                200,
                json={"code": 200, "data": {"status": 1, "errorMessage": ""}},
            ),
            httpx.Response(
                200,
                json={"code": 200, "data": {"status": 2, "errorMessage": ""}},
            ),
        ]
    )
    client = PushPlusClawBotClient(
        endpoint="https://www.pushplus.plus/send",
        user_token="user-token",
        secret_key="secret-key",
        request=request,
        sleep=_completed_sleep,
        monotonic=FakeClock([0, 0, 1, 2]),
        client=object(),
    )

    result = asyncio.run(client.send_and_wait("标题", "纯文本内容"))

    send_call = next(call for call in request.calls if call[1].endswith("/send"))
    assert send_call[2]["json"] == {
        "token": "user-token",
        "channel": "clawbot",
        "title": "标题",
        "content": "纯文本内容",
        "template": "txt",
    }
    assert result.state == PushPlusDeliveryState.DELIVERED
    assert result.short_code == "receipt-1"


def test_inactive_context_prevents_send():
    client = _client(
        [
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": 0}}
            ),
        ]
    )

    result = asyncio.run(client.send_and_wait("title", "content"))

    assert result.state == PushPlusDeliveryState.INACTIVE
    assert not any(call[1].endswith("/send") for call in client._request.calls)


@pytest.mark.parametrize(
    "send_payload",
    [
        {"code": 500, "msg": "rejected user-token secret-key"},
        {"code": 200, "msg": "accepted", "data": ""},
    ],
)
def test_send_rejection_or_missing_receipt_is_api_failure(send_payload):
    client = _client(
        [
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": "1"}}
            ),
            httpx.Response(200, json=send_payload),
        ]
    )

    result = asyncio.run(client.send_and_wait("title", "content"))

    assert result.state == PushPlusDeliveryState.API_FAILURE
    assert "user-token" not in (result.detail or "")
    assert "secret-key" not in (result.detail or "")


def test_status_three_is_failed_and_sanitized():
    client = _client(
        [
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": 1}}
            ),
            httpx.Response(200, json={"code": 200, "data": "receipt-3"}),
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "status": 3,
                        "errorMessage": "quota secret-key ak",
                    },
                },
            ),
        ]
    )

    result = asyncio.run(client.send_and_wait("title", "content"))

    assert result.state == PushPlusDeliveryState.FAILED
    assert result.short_code == "receipt-3"
    assert "secret-key" not in (result.detail or "")
    assert "ak" not in (result.detail or "")


def test_pending_status_times_out_without_success():
    client = _client(
        [
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": 1}}
            ),
            httpx.Response(
                200, json={"code": 200, "data": "receipt-timeout"}
            ),
            httpx.Response(
                200,
                json={"code": 200, "data": {"status": 0, "errorMessage": ""}},
            ),
            httpx.Response(
                200,
                json={"code": 200, "data": {"status": 1, "errorMessage": ""}},
            ),
        ],
        clock=FakeClock([0, 0, 0, 91]),
    )

    result = asyncio.run(client.send_and_wait("title", "content"))

    assert result.state == PushPlusDeliveryState.TIMED_OUT
    assert result.delivered is False


def test_expiring_access_key_is_refreshed_and_secrets_stay_out_of_repr():
    client = _client(
        [
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak-1", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": 1}}
            ),
            httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"accessKey": "ak-2", "expiresIn": 7200},
                },
            ),
            httpx.Response(
                200, json={"code": 200, "data": {"haveContextToken": 1}}
            ),
        ]
    )

    assert asyncio.run(client.check_binding()) is True
    client._access_key_expires_at = 0
    assert asyncio.run(client.check_binding()) is True

    access_calls = [
        call for call in client._request.calls if call[1].endswith("/getAccessKey")
    ]
    assert len(access_calls) == 2
    assert "user-token" not in repr(client)
    assert "secret-key" not in repr(client)
