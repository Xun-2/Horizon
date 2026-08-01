"""Unit tests for daily summary rendering."""

import asyncio
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


def _run_async(coro):
    return asyncio.run(coro)


def _make_item(idx: int) -> ContentItem:
    item = ContentItem(
        id=f"rss:item-{idx}",
        source_type=SourceType.RSS,
        title=f"Important Item {idx}",
        url=f"https://example.com/items/{idx}",
        content="content",
        author="tester",
        published_at=datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc),
        profile="tech-news",
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-news", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8.0,
                reason="test",
                summary=f"Summary for item {idx}.",
                tags=["AI", "News"],
            ),
            artifacts={
                language: ContentArtifact(
                    language=language,
                    title=f"Important Item {idx}",
                    lead=f"Summary for item {idx}.",
                )
                for language in ("en", "zh")
            },
        ),
    )
    return item


def _make_friend_item(idx: int) -> ContentItem:
    item = _make_item(idx)
    item.metadata["feed_name"] = "Example Feed"
    item.processing.artifacts = {
        "en": ContentArtifact(
            language="en",
            title=f"English Item {idx}",
            blocks=[
                ContentBlock(
                    id="summary",
                    role="summary",
                    title="Summary",
                    content=(
                        f"Event {idx} happened. "
                        f"It matters to technical teams {idx}. "
                        f"A final detail for item {idx}."
                    ),
                )
            ],
        ),
        "zh": ContentArtifact(
            language="zh",
            title=f"中文条目 {idx}",
            blocks=[
                ContentBlock(
                    id="summary",
                    role="summary",
                    title="摘要",
                    content=(
                        f"事件 {idx} 已经发生。"
                        f"它会影响技术团队 {idx}。"
                        f"这是条目 {idx} 的补充细节。"
                    ),
                )
            ],
        ),
    }
    return item


def test_generate_friend_digest_features_three_and_summarizes_nine():
    items = [_make_friend_item(index) for index in range(1, 14)]

    result = DailySummarizer().generate_friend_digest(
        items,
        date="2026-07-31",
        total_fetched=30,
        language="en",
    )

    assert result.startswith("# A few AI updates worth your time today")
    assert "## 1. [English Item 1](https://example.com/items/1)" in result
    assert "**What happened:** Event 1 happened." in result
    assert (
        "**Why it matters:** It matters to technical teams 1. "
        "A final detail for item 1."
    ) in result
    assert "## A few more, in one line each" in result
    assert "4. [English Item 4](https://example.com/items/4)" in result
    assert "Event 4 happened." in result
    assert "It matters to technical teams 4." not in result
    assert "English Item 12" in result
    assert "English Item 13" not in result
    assert "⭐️" not in result
    assert result.index("English Item 1") < result.index("English Item 12")


def test_generate_friend_digest_uses_only_the_requested_language():
    item = _make_friend_item(1)

    result = DailySummarizer().generate_friend_digest(
        [item], "2026-07-31", 1, language="zh"
    )

    assert "中文条目 1" in result
    assert "事件 1 已经发生。" in result
    assert "它会影响技术团队 1。" in result
    assert "English Item" not in result
    assert "Event 1 happened." not in result


def test_generate_friend_digest_does_not_cross_language_fallback():
    item = _make_friend_item(1)
    del item.processing.artifacts["zh"]

    result = DailySummarizer().generate_friend_digest(
        [item], "2026-07-31", 1, language="zh"
    )

    assert "Important Item 1" in result
    assert "Event 1 happened." not in result
    assert "发生了什么" not in result
    assert "为什么值得看" not in result


def test_generate_friend_digest_uses_key_point_for_one_sentence():
    item = _make_friend_item(1)
    item.processing.artifacts["en"].blocks[0].content = "One supported sentence."

    result = DailySummarizer().generate_friend_digest(
        [item], "2026-07-31", 1, language="en"
    )

    assert "**Key point:** One supported sentence." in result
    assert "**Why it matters:**" not in result


def test_generate_friend_digest_empty_copy_is_natural_and_not_diagnostic():
    result = DailySummarizer().generate_friend_digest(
        [], "2026-07-31", 19, language="zh"
    )

    assert "今天暂时没有筛到值得专门打扰你的 AI 动态" in result
    assert "阈值" not in result
    assert "配置" not in result


def test_generate_friend_digest_escapes_text_and_omits_unsafe_url():
    item = _make_friend_item(1)
    item.processing.artifacts["en"].title = "Model [update]"
    item.url = "javascript:alert(1)"

    result = DailySummarizer().generate_friend_digest(
        [item], "2026-07-31", 1, language="en"
    )

    assert "Model \\[update\\]" in result
    assert "javascript:" not in result


def test_generate_webhook_overview_lists_items_without_full_details():
    summarizer = DailySummarizer()
    items = [_make_item(1), _make_item(2)]

    result = summarizer.generate_webhook_overview(
        items,
        date="2026-04-25",
        total_fetched=10,
        language="en",
    )

    assert "Selected 2 important items from 10 fetched items" in result
    assert "1. [Important Item 1](https://example.com/items/1)" in result
    assert "2. [Important Item 2](https://example.com/items/2)" in result
    assert "Summary for item 1." not in result


def test_generate_webhook_item_renders_single_item_detail():
    summarizer = DailySummarizer()

    result = summarizer.generate_webhook_item(
        _make_item(1),
        language="en",
        index=1,
        total=2,
    )

    assert result.startswith("Item 1/2")
    assert "## [Important Item 1](https://example.com/items/1)" in result
    assert "Summary for item 1." in result
    assert "**Tags**: `#AI`, `#News`" in result


def test_generate_webhook_item_includes_discussion_link_when_distinct():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://news.ycombinator.com/item?id=1"

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "tester · Apr 25, 08:00 · [Discussion](https://news.ycombinator.com/item?id=1)" in result


def test_generate_webhook_item_omits_discussion_link_when_same_as_item_url():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = item.url

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "[Discussion](https://example.com/items/1)" not in result


def test_generate_webhook_item_uses_localized_discussion_label():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://www.reddit.com/r/python/comments/abc123/test/"

    result = summarizer.generate_webhook_item(
        item,
        language="zh",
        index=1,
        total=1,
    )

    assert "[社区讨论](https://www.reddit.com/r/python/comments/abc123/test/)" in result


def test_generate_summary_zh_uses_localized_selection_header_and_numeric_date():
    summarizer = DailySummarizer()
    item = _make_item(1)

    result = _run_async(
        summarizer.generate_summary(
            [item],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 从 10 条内容中筛选出 1 条重要资讯。" in result
    assert "rss · tester · 4月25日 08:00" in result
    assert "From 10 items" not in result
    assert "Apr 25, 08:00" not in result


def test_generate_summary_groups_items_by_profile_with_heading_hierarchy():
    news = _make_item(1)
    blog = _make_item(2)
    blog.profile = "tech-blog"
    blog.processing.classification.profile = "tech-blog"
    summarizer = DailySummarizer(
        profile_names={
            "tech-news": {"default": "Technology News", "zh": "科技新闻"},
            "tech-blog": {"default": "Technology Blog", "zh": "科技博客"},
        }
    )

    result = _run_async(
        summarizer.generate_summary(
            [news, blog],
            date="2026-04-25",
            total_fetched=2,
            language="en",
        )
    )

    assert result.count("# Horizon Daily") == 1
    assert "## Technology News" in result
    assert "## Technology Blog" in result
    assert "### [Important Item 1]" in result
    assert "### [Important Item 2]" in result


def test_generate_summary_renumbers_interleaved_profiles_and_localizes_headings():
    first_news = _make_item(1)
    blog = _make_item(2)
    second_news = _make_item(3)
    blog.profile = "tech-blog"
    blog.processing.classification.profile = "tech-blog"
    summarizer = DailySummarizer(
        profile_names={
            "tech-news": {"default": "Technology News", "zh": "科技新闻"},
            "tech-blog": {"default": "Technology Blog", "zh": "科技博客"},
        }
    )

    result = _run_async(
        summarizer.generate_summary(
            [first_news, blog, second_news],
            date="2026-04-25",
            total_fetched=3,
            language="zh",
        )
    )

    assert "## 科技新闻" in result
    assert "## 科技博客" in result
    assert "1. [Important Item 1](#item-tech-news-1)" in result
    assert "2. [Important Item 3](#item-tech-news-2)" in result
    assert "1. [Important Item 2](#item-tech-blog-1)" in result
    assert result.index("2. [Important Item 3]") < result.index("1. [Important Item 2]")
    assert '<a id="item-tech-news-1"></a>' in result
    assert '<a id="item-tech-blog-1"></a>' in result


def test_generate_empty_summary_zh_uses_localized_analyzed_line():
    summarizer = DailySummarizer()

    result = _run_async(
        summarizer.generate_summary(
            [],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 已分析 10 条内容，但没有达到重要性阈值的条目。" in result
    assert "Analyzed 10 items" not in result


def test_generate_summary_escapes_untrusted_text_in_all_output_contexts():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.title = '<script>alert("title")</script> [click](javascript:alert(1))'
    item.processing.analysis.summary = '<img src=x onerror="alert(1)"> **summary**'
    item.author = '<svg onload="alert(1)">'
    item.processing.analysis.tags = ['tag`](javascript:alert(1))']
    item.processing.artifacts["en"] = ContentArtifact(
        language="en",
        title=item.title,
        lead='<img src=x onerror="alert(1)"> **summary**',
        blocks=[
            ContentBlock(
                id="background",
                title="Background",
                content='<iframe src="data:text/html,bad"></iframe>',
            ),
            ContentBlock(
                id="community_discussion",
                title="Discussion",
                content="[bad](data:text/html,bad)",
            ),
        ],
        sources=[
            ArtifactSource(
                id="ref-1",
                title='<img src=x onerror="alert(1)">',
                url="https://example.com/ref",
            )
        ],
    )
    item.metadata.update(
        {
            "feed_name": '<b onclick="alert(1)">feed</b>',
        }
    )

    result = _run_async(summarizer.generate_summary([item], "2026-04-25", 1))

    assert "<script>" not in result
    assert "<img src=x" not in result
    assert "<iframe" not in result
    assert "<b onclick" not in result
    assert "](javascript:" not in result
    assert "](data:text/html" not in result
    assert "&lt;script&gt;" in result
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in result


def test_generate_summary_rejects_unsafe_urls_and_quote_injection():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = 'javascript:alert("discussion")'
    item.processing.artifacts["en"].sources = [
        ArtifactSource(
            id="quoted",
            title='Quoted "><script>alert(1)</script>',
            url='https://example.com/\" onmouseover=\"alert(1)',
        ),
        ArtifactSource(id="js", title="JavaScript", url="javascript:alert(1)"),
        ArtifactSource(
            id="data",
            title="Data",
            url="data:text/html,<script>alert(1)</script>",
        ),
    ]

    result = _run_async(summarizer.generate_summary([item], "2026-04-25", 1))

    assert 'href="https://example.com/%22%20onmouseover=%22alert%281%29"' in result
    assert '<li>JavaScript</li>' in result
    assert '<li>Data</li>' in result
    assert 'href="javascript:' not in result
    assert 'href="data:' not in result
    assert '<script>' not in result


def test_generate_summary_preserves_normal_http_links():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://example.com/discuss?id=1#comments"
    item.processing.artifacts["en"].sources = [
        ArtifactSource(
            id="useful",
            title="Useful reference",
            url="https://docs.example.com/path?q=one&lang=en",
        )
    ]

    result = _run_async(summarizer.generate_summary([item], "2026-04-25", 1))

    assert "[Important Item 1](https://example.com/items/1)" in result
    assert "[Discussion](https://example.com/discuss?id=1#comments)" in result
    assert 'href="https://docs.example.com/path?q=one&amp;lang=en"' in result
