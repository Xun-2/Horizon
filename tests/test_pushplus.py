import json
import os
from unittest.mock import MagicMock

import httpx
import pytest

from src.models import WebhookConfig
from src.services.webhook import (
    WebhookDeliveryStatus,
    WebhookNotifier,
)


TEST_URL_ENV = "HORIZON_TEST_PUSHPLUS_URL"
TEST_URL = "https://www.pushplus.plus/send"


def _notifier(config: WebhookConfig) -> WebhookNotifier:
    os.environ[TEST_URL_ENV] = TEST_URL
    return WebhookNotifier(config)


def test_overview_delivery_builds_one_compact_message():
    notifier = _notifier(
        WebhookConfig(enabled=True, url_env=TEST_URL_ENV, delivery="overview")
    )
    summarizer = MagicMock()
    summarizer.generate_webhook_overview.return_value = "compact overview"

    messages = notifier.build_daily_summary_messages(
        summary="full report",
        important_items=[],
        all_items_count=19,
        date="2026-07-31",
        lang="zh",
        summarizer=summarizer,
    )

    assert len(messages) == 1
    assert messages[0]["message_kind"] == "overview"
    assert messages[0]["summary"] == "compact overview"
    summarizer.generate_webhook_overview.assert_called_once_with(
        [], "2026-07-31", 19, language="zh"
    )


@pytest.mark.parametrize(
    ("language", "expected_title"),
    [
        ("zh", "今天这几条 AI 动态值得看"),
        ("en", "A few AI updates worth your time today"),
    ],
)
def test_pushplus_overview_uses_friend_digest(language, expected_title):
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            delivery="overview",
            platform="pushplus",
        )
    )
    summarizer = MagicMock()
    summarizer.generate_friend_digest.return_value = "friend digest"

    messages = notifier.build_daily_summary_messages(
        summary="full report",
        important_items=[],
        all_items_count=19,
        date="2026-07-31",
        lang=language,
        summarizer=summarizer,
    )

    assert len(messages) == 1
    assert messages[0]["message_kind"] == "overview"
    assert messages[0]["message_title"] == expected_title
    assert messages[0]["summary"] == "friend digest"
    summarizer.generate_friend_digest.assert_called_once_with(
        [], "2026-07-31", 19, language=language
    )
    summarizer.generate_webhook_overview.assert_not_called()


def test_pushplus_summary_and_items_keeps_existing_overview():
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            delivery="summary_and_items",
            platform="pushplus",
        )
    )
    summarizer = MagicMock()
    summarizer.generate_webhook_overview.return_value = "existing overview"
    summarizer.build_view.return_value.groups = []

    messages = notifier.build_daily_summary_messages(
        summary="full report",
        important_items=[],
        all_items_count=19,
        date="2026-07-31",
        lang="zh",
        summarizer=summarizer,
    )

    assert messages[0]["summary"] == "existing overview"
    summarizer.generate_webhook_overview.assert_called_once()
    summarizer.generate_friend_digest.assert_not_called()


def test_pushplus_requires_business_code_200_for_success():
    notifier = _notifier(
        WebhookConfig(enabled=True, url_env=TEST_URL_ENV, platform="pushplus")
    )

    result = notifier._handle_response_status(
        httpx.Response(200, json={"code": 200, "msg": "success"}),
        TEST_URL,
    )

    assert result.status == WebhookDeliveryStatus.SUCCESS


def test_pushplus_failure_redacts_configured_token_from_detail():
    secret = "pushplus-secret-value"
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            platform="pushplus",
            request_body={"token": secret, "content": "#{summary}"},
        )
    )

    result = notifier._handle_response_status(
        httpx.Response(
            200,
            json={"code": 500, "msg": f"invalid token {secret}"},
        ),
        TEST_URL,
    )

    assert result.status == WebhookDeliveryStatus.PLATFORM_FAILURE
    assert secret not in (result.detail or "")
    assert "<redacted>" in (result.detail or "")


def test_pushplus_failure_redacts_token_from_string_json_body():
    secret = "pushplus-string-json-secret"
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            platform="pushplus",
            request_body=json.dumps({"token": secret, "content": "#{summary}"}),
        )
    )

    result = notifier._handle_response_status(
        httpx.Response(
            200,
            json={"code": 500, "msg": f"invalid token {secret}"},
        ),
        TEST_URL,
    )

    assert secret not in (result.detail or "")
    assert "<redacted>" in (result.detail or "")


def test_pushplus_failure_redacts_sensitive_configured_header():
    secret = "pushplus-header-secret"
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            platform="pushplus",
            headers=f"Authorization: {secret}",
        )
    )

    result = notifier._handle_response_status(
        httpx.Response(
            200,
            json={"code": 500, "msg": f"invalid token {secret}"},
        ),
        TEST_URL,
    )

    assert secret not in (result.detail or "")
    assert "<redacted>" in (result.detail or "")


def test_unexpected_status_redacts_configured_secret_from_console():
    secret = "pushplus-console-secret"
    console = MagicMock()
    os.environ[TEST_URL_ENV] = TEST_URL
    notifier = WebhookNotifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            request_body=json.dumps({"token": secret}),
        ),
        console=console,
    )

    result = notifier._handle_response_status(
        httpx.Response(199, text=f"echoed token: {secret}"),
        TEST_URL,
    )

    rendered_console = " ".join(
        str(call.args) for call in console.print.call_args_list
    )
    assert secret not in (result.detail or "")
    assert secret not in rendered_console


def test_pushplus_rejects_2xx_response_without_business_code():
    notifier = _notifier(
        WebhookConfig(enabled=True, url_env=TEST_URL_ENV, platform="pushplus")
    )

    result = notifier._handle_response_status(
        httpx.Response(200, json={"msg": "missing code"}),
        TEST_URL,
    )

    assert result.status == WebhookDeliveryStatus.PLATFORM_FAILURE


def test_preview_recursively_redacts_sensitive_json_fields():
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            request_body={
                "token": "secret-token",
                "content": "safe content",
                "nested": {
                    "api_key": "secret-key",
                    "items": [
                        {"password": "secret-password", "label": "kept"}
                    ],
                },
            },
        )
    )

    preview = notifier.build_preview({})
    body = json.loads(preview["body"])

    assert body["token"] == "<redacted>"
    assert body["nested"]["api_key"] == "<redacted>"
    assert body["nested"]["items"][0]["password"] == "<redacted>"
    assert body["content"] == "safe content"
    assert body["nested"]["items"][0]["label"] == "kept"


def test_preview_redacts_sensitive_form_body():
    secret = "pushplus-form-secret"
    notifier = _notifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            request_body=f"token={secret}&content=safe",
        )
    )

    preview = notifier.build_preview({})

    assert secret not in preview["body"]
    assert "token=<redacted>" in preview["body"]
    assert "content=safe" in preview["body"]


def test_webhook_config_accepts_pushplus_overview_mode():
    config = WebhookConfig(delivery="overview", platform="pushplus")

    assert config.delivery == "overview"
    assert config.platform == "pushplus"
