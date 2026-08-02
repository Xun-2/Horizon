from datetime import datetime, timezone
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from src.ai.summarizer import DailySummarizer
from src.models import (
    ArtifactSource,
    ClassificationResult,
    ContentAnalysis,
    ContentArtifact,
    ContentBlock,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.services.daily_pages import DAILY_CSS, build_daily_page_bundle


def _visual_item():
    long_title = "超长 AI 模型标题" + "非常重要" * 25
    long_url = "https://example.com/" + "source" * 50
    artifacts = {
        "zh": ContentArtifact(
            language="zh",
            title=long_title,
            lead="第一句概括核心变化。第二句解释实际影响。第三句作为展开详情。",
            blocks=[ContentBlock(id="background", title="背景", content="背景内容" * 40)],
            sources=[ArtifactSource(id="source", title="原文", url=long_url)],
        ),
        "en": ContentArtifact(
            language="en",
            title="A very long AI model title " + "with concrete details " * 15,
            lead=(
                "The model changed materially. The change affects production use. "
                "Extra detail stays expanded."
            ),
            blocks=[
                ContentBlock(
                    id="background", title="Background", content="Context " * 80
                )
            ],
            sources=[ArtifactSource(id="source", title="Original", url=long_url)],
        ),
    }
    return ContentItem(
        id="rss:visual:1",
        source_type=SourceType.RSS,
        title=long_title,
        url=long_url,
        published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="general", method="source_override"
            ),
            analysis=ContentAnalysis(score=9, reason="important", summary="summary"),
            artifacts=artifacts,
        ),
    )


@pytest.fixture
def visual_items():
    return [_visual_item(), _visual_item(), _visual_item(), _visual_item()]


@pytest.mark.parametrize("width,height", [(390, 844), (430, 932), (1440, 900)])
def test_daily_page_has_no_horizontal_scroll_or_overlap(
    width, height, visual_items
):
    bundle = build_daily_page_bundle(
        visual_items,
        "2026-08-02",
        16,
        ["zh", "en"],
        DailySummarizer(),
        "https://xun-2.github.io/Horizon",
    )
    output = Path(".superpowers/daily-pages-visual")
    output.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for language in ("zh", "en"):
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(bundle.files[f"daily/2026-08-02/{language}.html"])
            page.add_style_tag(content=DAILY_CSS)
            page.locator("details summary").first.click()
            metrics = page.evaluate(
                """() => ({
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth,
                    shellWidth: document.querySelector('.page-shell').getBoundingClientRect().width,
                    targets: [...document.querySelectorAll('summary')].map((node) => node.getBoundingClientRect().height),
                    overlaps: [...document.querySelectorAll('.daily-item')].some((item) => {
                        const title = item.querySelector('h2').getBoundingClientRect();
                        const summary = item.querySelector('.scan-summary').getBoundingClientRect();
                        return title.bottom > summary.top;
                    })
                })"""
            )
            assert metrics["scrollWidth"] <= metrics["clientWidth"]
            assert metrics["shellWidth"] <= 680
            assert min(metrics["targets"]) >= 44
            assert metrics["overlaps"] is False
            page.screenshot(
                path=str(output / f"{language}-{width}x{height}.png"),
                full_page=True,
            )
            page.close()
        browser.close()


def test_empty_daily_page_visual():
    bundle = build_daily_page_bundle(
        [],
        "2026-08-02",
        0,
        ["zh", "en"],
        DailySummarizer(),
        "https://xun-2.github.io/Horizon",
    )
    expected = {
        "zh": "今天暂无达到阈值的动态",
        "en": "No updates met today's threshold",
    }
    output = Path(".superpowers/daily-pages-visual")
    output.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for language, copy in expected.items():
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(bundle.files[f"daily/2026-08-02/{language}.html"])
            page.add_style_tag(content=DAILY_CSS)
            assert page.get_by_text(copy).is_visible()
            metrics = page.evaluate(
                """() => ({
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth
                })"""
            )
            assert metrics["scrollWidth"] <= metrics["clientWidth"]
            page.screenshot(
                path=str(output / f"empty-{language}-390x844.png"),
                full_page=True,
            )
            page.close()
        browser.close()
