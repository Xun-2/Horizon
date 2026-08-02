import asyncio
from datetime import datetime, timezone
import re
from types import SimpleNamespace

from src.models import GitHubPagesConfig
from src.orchestrator import HorizonOrchestrator
from src.services.github_pages import PagePublishResult


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
    def __init__(self, events):
        self.events = events

    async def send_daily_summary(self, **kwargs):
        self.events.append(f"notify:{kwargs['lang']}:{kwargs['page_url']}")
        return []


def _orchestrator(events, publish_success):
    orchestrator = object.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(
        ai=SimpleNamespace(languages=["zh", "en"]),
        email=None,
        github_pages=GitHubPagesConfig(enabled=True),
    )
    orchestrator.storage = FakeStorage(events)
    orchestrator.profiles = SimpleNamespace(names={})
    orchestrator.page_publisher = FakePublisher(events, publish_success)
    orchestrator.webhook_notifier = FakeNotifier(events)
    orchestrator.email_manager = None
    orchestrator.console = SimpleNamespace(
        print=lambda message: events.append("warning")
    )
    return orchestrator


def test_pipeline_publishes_both_languages_before_notifying():
    events = []
    orchestrator = _orchestrator(events, publish_success=True)

    asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-02"))

    assert events.index("publish:zh,en") < events.index(
        "notify:zh:https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html"
    )
    assert events.index("publish:zh,en") < events.index(
        "notify:en:https://xun-2.github.io/Horizon/daily/2026-08-02/en.html"
    )


def test_pages_failure_still_notifies_without_link():
    events = []
    orchestrator = _orchestrator(events, publish_success=False)

    asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-02"))

    assert "notify:zh:None" in events
    assert "notify:en:None" in events
    assert events.count("save:zh") == 1
    assert events.count("save:en") == 1


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

    orchestrator.fetch_all_sources = fetch_all_sources
    orchestrator._deliver_daily = deliver_daily

    asyncio.run(orchestrator.run(force_hours=24))

    assert len(events) == 1
    assert events[0][0] == []
    assert events[0][1] == 0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", events[0][2])
