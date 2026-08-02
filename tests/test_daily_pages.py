from datetime import datetime, timezone

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
from src.services.daily_pages import (
    DAILY_CSS,
    build_daily_page_bundle,
    render_index_page,
)


def _item(
    title: str = "模型 <突破>",
    url: str = "https://example.com/a?x=1&y=2",
):
    artifact = ContentArtifact(
        language="zh",
        title=title,
        lead="第一句概括。第二句说明影响。第三句只在详情中出现。",
        blocks=[
            ContentBlock(
                id="background",
                title="背景 <详情>",
                content="长期背景信息 & 后续影响",
            )
        ],
        sources=[ArtifactSource(id="s1", title="原始 <来源>", url=url)],
    )
    return ContentItem(
        id="rss:test:1",
        source_type=SourceType.RSS,
        title=title,
        url=url,
        published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="general", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8.5, reason="important", summary="summary"
            ),
            artifacts={"zh": artifact},
        ),
    )


def test_daily_bundle_uses_fixed_public_paths_and_escapes_content():
    bundle = build_daily_page_bundle(
        items=[_item()],
        date="2026-08-02",
        total_fetched=9,
        languages=["zh"],
        summarizer=DailySummarizer(),
        site_url="https://xun-2.github.io/Horizon",
    )

    html = bundle.files["daily/2026-08-02/zh.html"]
    assert bundle.urls["zh"].endswith("/daily/2026-08-02/zh.html")
    assert "模型 &lt;突破&gt;" in html
    assert "第一句概括。第二句说明影响。" in html
    assert "第三句只在详情中出现。" in html
    assert "背景 &lt;详情&gt;" in html
    assert "长期背景信息 &amp; 后续影响" in html
    assert "原始 &lt;来源&gt;" in html
    assert "<details" in html and "详情与原文" in html
    assert 'data-horizon-date="2026-08-02"' in html
    assert 'data-language="zh"' in html
    assert '<link rel="stylesheet" href="../../assets/horizon-daily.css">' in html
    assert "<script" not in html.lower()


def test_empty_daily_page_and_mobile_css_contract():
    bundle = build_daily_page_bundle(
        items=[],
        date="2026-08-02",
        total_fetched=0,
        languages=["zh", "en"],
        summarizer=DailySummarizer(),
        site_url="https://xun-2.github.io/Horizon",
    )

    assert "今天暂无达到阈值的动态" in bundle.files["daily/2026-08-02/zh.html"]
    assert "No updates met today's threshold" in bundle.files[
        "daily/2026-08-02/en.html"
    ]
    assert "max-width: 680px" in DAILY_CSS
    assert "padding-inline: 18px" in DAILY_CSS
    assert "min-height: 44px" in DAILY_CSS
    assert "overflow-wrap: anywhere" in DAILY_CSS
    assert "gradient" not in DAILY_CSS.lower()


def test_daily_page_omits_unsafe_reference_links_and_escapes_attributes():
    item = _item()
    item.processing.artifacts["zh"].sources = [
        ArtifactSource(
            id="unsafe",
            title='不安全 "来源"',
            url="https://user:pass@example.com/private",
        ),
        ArtifactSource(
            id="invalid-port",
            title="无效端口",
            url="https://example.com:bad/path",
        ),
    ]

    html = build_daily_page_bundle(
        [item],
        "2026-08-02",
        1,
        ["zh"],
        DailySummarizer(),
        "https://xun-2.github.io/Horizon",
    ).files["daily/2026-08-02/zh.html"]

    assert "不安全 &quot;来源&quot;" in html
    assert "无效端口" in html
    assert "user:pass" not in html
    assert "example.com:bad" not in html


def test_index_page_sorts_unique_dates_and_uses_root_stylesheet():
    html = render_index_page(["2026-08-01", "2026-08-02", "2026-08-01"])

    assert html.index("2026-08-02") < html.index("2026-08-01")
    assert html.count('<time datetime="2026-08-01">') == 1
    assert 'href="daily/2026-08-02/zh.html"' in html
    assert 'href="daily/2026-08-02/en.html"' in html
    assert '<link rel="stylesheet" href="assets/horizon-daily.css">' in html
