from src.ai.summarizer import DailySummarizer
from src.services.webhook_cli import _make_test_items


def test_webhook_cli_samples_render_localized_friend_digests():
    items = _make_test_items()
    summarizer = DailySummarizer()

    assert all(set(item.processing.artifacts) == {"zh", "en"} for item in items)

    zh = summarizer.generate_friend_digest(
        items, "2026-07-31", len(items), language="zh"
    )
    en = summarizer.generate_friend_digest(
        items, "2026-07-31", len(items), language="en"
    )

    assert "GPT-5 发布" in zh
    assert "OpenAI 发布了 GPT-5" in zh
    assert "GPT-5 Released" in en
    assert "OpenAI released GPT-5" in en
    assert "OpenAI released GPT-5" not in zh
    assert "OpenAI 发布了 GPT-5" not in en
