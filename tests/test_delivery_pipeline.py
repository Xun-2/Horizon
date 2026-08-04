import asyncio
from datetime import datetime, timezone
import re
from types import SimpleNamespace

from src.models import GitHubPagesConfig
from src.orchestrator import DailyDeliveryResult, HorizonOrchestrator
from src.services.github_pages import PagePublishResult
from src.services.webhook import WebhookDeliveryResult, WebhookDeliveryStatus


class FakeStorage:
    def __init__(self, events):
        self.events = events

    def save_daily_summary(self, date, markdown, language):
        self.events.append(f"save:{language}")


class FakePublisher:
    def __init__(self, events, success):
        self.events = events
        self.success = success

    async def publish(self, bundle):
        self.events.append("publish:" + ",".join(bundle.urls))
        return PagePublishResult(
            success=self.success,
            urls=bundle.urls if self.success else {},
            error_type=None if self.success else "github_failure",
        )


class FakeNotifier:
    def __init__(self, events, success):
        self.events = events
        self.success = success

    async def send_bilingual_daily_summary(self, **kwargs):
        self.events.append("notify:bilingual")
        return WebhookDeliveryResult(
            WebhookDeliveryStatus.SUCCESS
            if self.success
            else WebhookDeliveryStatus.PLATFORM_FAILURE
        )


def _orchestrator(events, *, publish_success, notify_success):
    orchestrator = object.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(
        ai=SimpleNamespace(languages=["zh", "en"]),
        email=None,
        github_pages=GitHubPagesConfig(enabled=True),
        webhook=SimpleNamespace(
            platform="pushplus",
            pushplus=SimpleNamespace(message_mode="bilingual_links"),
        ),
    )
    orchestrator.storage = FakeStorage(events)
    orchestrator.profiles = SimpleNamespace(names={})
    orchestrator.page_publisher = FakePublisher(events, publish_success)
    orchestrator.webhook_notifier = FakeNotifier(events, notify_success)
    orchestrator.email_manager = None
    orchestrator.console = SimpleNamespace(
        print=lambda message: events.append("warning")
    )
    return orchestrator


def test_bilingual_pipeline_publishes_both_languages_then_sends_once():
    events = []
    orchestrator = _orchestrator(
        events, publish_success=True, notify_success=True
    )

    result = asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-03"))

    assert result.success is True
    assert events == ["save:zh", "save:en", "publish:zh,en", "notify:bilingual"]


def test_pages_failure_skips_clawbot_and_is_not_success():
    events = []
    orchestrator = _orchestrator(
        events, publish_success=False, notify_success=True
    )

    result = asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-03"))

    assert result.success is False
    assert result.error_type == "github_failure"
    assert "notify:bilingual" not in events


def test_pushplus_failure_is_not_daily_success():
    result = asyncio.run(
        _orchestrator(
            [], publish_success=True, notify_success=False
        )._deliver_daily([], 0, "2026-08-03")
    )

    assert result.success is False
    assert result.error_type == "pushplus_failure"


def test_no_fetched_items_still_runs_empty_delivery():
    events = []
    orchestrator = object.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(email=None)
    orchestrator.email_manager = None
    orchestrator.last_fetch_report = None
    orchestrator.icons = {
        "start": "",
        "date": "",
        "fetched": "",
        "success": "",
    }
    orchestrator.console = SimpleNamespace(print=lambda message: None)
    orchestrator._determine_time_window = lambda force_hours=None: datetime(
        2026, 8, 2, tzinfo=timezone.utc
    )

    async def fetch_all_sources(since):
        return []

    async def deliver_daily(items, total_fetched, date):
        events.append((items, total_fetched, date))
        return DailyDeliveryResult(success=True, page_urls={})

    orchestrator.fetch_all_sources = fetch_all_sources
    orchestrator._deliver_daily = deliver_daily

    asyncio.run(orchestrator.run(force_hours=24))

    assert len(events) == 1
    assert events[0][0] == []
    assert events[0][1] == 0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", events[0][2])
