"""Daily summary generation — pure programmatic rendering."""

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit

from ..models import ContentItem


_CJK = r"[\u4e00-\u9fff\u3400-\u4dbf]"
_ASCII = r"[A-Za-z0-9]"
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#!|])")
_MARKDOWN_BLOCK_START = re.compile(r"(?m)^( {0,3})(>|[-+] |\d+[.)] )")
_URL_SAFE_CHARS = ":/?#[]@!$&'*,;=~%+"
_FRIEND_DIGEST_LIMIT = 12
_FRIEND_DIGEST_FEATURED = 3
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？])|(?<=[.!?])(?=\s|$)")
_SENTENCE_DOT_PLACEHOLDER = "\uE000"
_COMMON_ABBREVIATION = re.compile(
    r"\b(?:(?:[A-Za-z]\.){2,}|(?:Inc|Ltd|Corp|Co)\.)",
    re.IGNORECASE,
)


def _validated_page_url(value: str, label: str) -> str:
    raw_url = value.strip()
    try:
        parsed = urlsplit(raw_url)
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} must be an absolute HTTP(S) URL") from exc
    if (
        any(ord(char) < 32 or ord(char) == 127 for char in raw_url)
        or parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{label} must be an absolute HTTP(S) URL")
    return raw_url


def _escape_markdown(value: object) -> str:
    """Render untrusted text literally while retaining its readable content."""
    escaped = html.escape(str(value), quote=True)
    escaped = _MARKDOWN_SPECIAL.sub(r"\\\1", escaped)
    return _MARKDOWN_BLOCK_START.sub(r"\1\\\2", escaped)


def _safe_url(value: object) -> Optional[str]:
    """Return an HTML/Markdown-safe HTTP(S) URL, or None for unsafe URLs."""
    raw = str(value).strip()
    if not raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        parsed.port
    except (TypeError, ValueError):
        return None
    encoded = quote(raw, safe=_URL_SAFE_CHARS)
    return html.escape(encoded, quote=True)


def _pangu(text: str) -> str:
    """Insert a space between CJK and ASCII letters/digits (Pangu spacing)."""
    text = re.sub(rf"({_CJK})({_ASCII})", r"\1 \2", text)
    text = re.sub(rf"({_ASCII})({_CJK})", r"\1 \2", text)
    return text


def _split_sentences(value: object) -> List[str]:
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    if not normalized:
        return []
    protected = _COMMON_ABBREVIATION.sub(
        lambda match: match.group(0).replace(".", _SENTENCE_DOT_PLACEHOLDER),
        normalized,
    )
    return [
        sentence.replace(_SENTENCE_DOT_PLACEHOLDER, ".").strip()
        for sentence in _SENTENCE_BOUNDARY.split(protected)
        if sentence.strip()
    ]


LABELS = {
    "en": {
        "header": "Horizon Daily",
        "source": "Source",
        "background": "Background",
        "discussion": "Discussion",
        "references": "References",
        "tags": "Tags",
        "selected_items": "From {total} items, {selected} important content pieces were selected",
        "empty_analyzed": "Analyzed {total} items, but none met the importance threshold.",
        "empty_body": (
            "No significant developments today. This might indicate:\n"
            "- A quiet day in your tracked sources\n"
            "- The AI score threshold is too high\n"
            "- Your information sources need expansion\n\n"
            "Consider:\n"
            "1. Lowering the active profile's filter threshold\n"
            "2. Adding more diverse information sources\n"
            "3. Checking if the AI model is working correctly\n"
        ),
    },
    "zh": {
        "header": "Horizon 每日速递",
        "source": "来源",
        "background": "背景",
        "discussion": "社区讨论",
        "references": "参考链接",
        "tags": "标签",
        "selected_items": "从 {total} 条内容中筛选出 {selected} 条重要资讯。",
        "empty_analyzed": "已分析 {total} 条内容，但没有达到重要性阈值的条目。",
        "empty_body": (
            "今日暂无重要动态，可能原因：\n"
            "- 今天关注的信息源较平静\n"
            "- AI 评分阈值设置过高\n"
            "- 信息源种类有待扩充\n\n"
            "建议：\n"
            "1. 降低当前 Profile 的过滤阈值\n"
            "2. 添加更多多样化的信息源\n"
            "3. 检查 AI 模型是否正常工作\n"
        ),
    },
}


FRIEND_DIGEST_LABELS = {
    "en": {
        "title": "A few AI updates worth your time today",
        "intro": (
            "I went through today's updates and picked {count}. "
            "These {featured} are worth starting with:"
        ),
        "intro_singular": (
            "I went through today's updates and picked one. "
            "This one is worth starting with:"
        ),
        "what": "What happened",
        "why": "Why it matters",
        "key": "Key point",
        "source": "Source",
        "read_more": "Read more",
        "more": "A few more, in one line each",
        "closing": "If you only read one, start with the first.",
        "empty": (
            "I didn't find an AI update worth interrupting you for today. "
            "I'll keep looking tomorrow."
        ),
    },
    "zh": {
        "title": "今天这几条 AI 动态值得看",
        "intro": "我从今天的更新里挑了 {count} 条，先看最值得关注的 {featured} 条：",
        "intro_singular": "我从今天的更新里挑了 1 条，先看这一条：",
        "what": "发生了什么",
        "why": "为什么值得看",
        "key": "重点",
        "source": "来源",
        "read_more": "查看原文",
        "more": "另外几条，一句话看完",
        "closing": "如果今天只读一条，我建议先看第 1 条。",
        "empty": "今天暂时没有筛到值得专门打扰你的 AI 动态，明天再继续看看。",
    },
}


@dataclass(frozen=True)
class SummaryItemView:
    item: ContentItem
    index: int
    global_index: int
    group_count: int
    title: str
    score: float | str
    anchor_id: str


@dataclass(frozen=True)
class SummaryGroupView:
    profile_id: str
    name: str
    items: List[SummaryItemView]


@dataclass(frozen=True)
class DailySummaryView:
    groups: List[SummaryGroupView]
    item_count: int


class DailySummarizer:
    """Generates daily Markdown summaries from pre-analyzed content items."""

    def __init__(
        self,
        profile_names: Optional[Dict[str, Dict[str, str]]] = None,
    ):
        self.profile_names = profile_names or {}

    @staticmethod
    def _profile_id(item: ContentItem) -> str:
        if item.processing:
            return item.processing.classification.profile
        return item.profile or "unclassified"

    def profile_name(self, profile_id: str, language: str) -> str:
        names = self.profile_names.get(profile_id, {})
        return names.get(
            language,
            names.get(
                "default",
                profile_id.replace("-", " ").replace("_", " ").title(),
            ),
        )

    def build_view(
        self,
        items: List[ContentItem],
        language: str,
    ) -> DailySummaryView:
        grouped_items: Dict[str, List[ContentItem]] = {}
        for item in items:
            grouped_items.setdefault(self._profile_id(item), []).append(item)

        groups = []
        global_index = 1
        for profile_id, profile_items in grouped_items.items():
            view_items = []
            for index, item in enumerate(profile_items, start=1):
                artifact = (
                    item.processing.artifacts.get(language)
                    if item.processing
                    else None
                )
                analysis = item.processing.analysis if item.processing else None
                view_items.append(
                    SummaryItemView(
                        item=item,
                        index=index,
                        global_index=global_index,
                        group_count=len(profile_items),
                        title=artifact.title if artifact else item.title,
                        score=(
                            analysis.score
                            if analysis and analysis.score is not None
                            else "?"
                        ),
                        anchor_id=self._item_anchor(profile_id, index),
                    )
                )
                global_index += 1
            groups.append(
                SummaryGroupView(
                    profile_id=profile_id,
                    name=self.profile_name(profile_id, language),
                    items=view_items,
                )
            )
        return DailySummaryView(groups=groups, item_count=len(items))

    @staticmethod
    def _item_anchor(profile_id: str, index: int) -> str:
        safe_profile_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", profile_id).strip("-")
        return f"item-{safe_profile_id or 'unclassified'}-{index}"

    async def generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary in Markdown format.

        Items are rendered in score-descending order (already sorted by orchestrator).

        Args:
            items: High-scoring content items (already enriched)
            date: Date string (YYYY-MM-DD)
            total_fetched: Total number of items fetched before filtering
            language: Output language, either "en" or "zh"

        Returns:
            str: Markdown formatted summary
        """
        labels = LABELS.get(language, LABELS["en"])

        if not items:
            return self._generate_empty_summary(date, total_fetched, labels)

        header = (
            f"# {labels['header']} - {date}\n\n"
            f"> {labels['selected_items'].format(total=total_fetched, selected=len(items))}\n\n"
            "---\n\n"
        )

        toc_sections = []
        body_sections = []
        view = self.build_view(items, language)
        for group in view.groups:
            profile_name = _escape_markdown(group.name)
            if language == "zh":
                profile_name = _pangu(profile_name)
            toc_entries = [f"**{profile_name}**"]
            for view_item in group.items:
                title = _escape_markdown(view_item.title)
                if language == "zh":
                    title = _pangu(title)
                toc_entries.append(
                    f"{view_item.index}. [{title}](#{view_item.anchor_id}) "
                    f"\u2b50\ufe0f {view_item.score}/10"
                )
            toc_sections.append("\n".join(toc_entries))
            body_sections.append(f"## {profile_name}\n\n")
            body_sections.extend(
                self._format_item(
                    view_item.item,
                    labels,
                    language,
                    view_item.index,
                    heading_level=3,
                    anchor_id=view_item.anchor_id,
                    title_override=view_item.title,
                    score_override=view_item.score,
                )
                for view_item in group.items
            )

        toc = "\n\n".join(toc_sections) + "\n\n---\n\n"
        return header + toc + "".join(body_sections)

    @staticmethod
    def _friend_source(item: ContentItem) -> str:
        metadata = item.metadata
        return str(
            metadata.get("feed_name")
            or metadata.get("repo")
            or metadata.get("source_name")
            or item.author
            or item.source_type.value
        )

    @staticmethod
    def _friend_content(item: ContentItem, language: str) -> tuple[str, List[str]]:
        artifact = item.processing.artifacts.get(language) if item.processing else None
        title = artifact.title if artifact and artifact.title else item.title
        if not artifact:
            return title, []
        body = artifact.lead.strip()
        if not body:
            body = next(
                (block.content.strip() for block in artifact.blocks if block.content.strip()),
                "",
            )
        return title, _split_sentences(body)

    def generate_friend_digest(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Render one deterministic, localized PushPlus friend digest."""
        del date, total_fetched
        labels = FRIEND_DIGEST_LABELS.get(language, FRIEND_DIGEST_LABELS["en"])
        selected = items[:_FRIEND_DIGEST_LIMIT]
        if not selected:
            return f"# {labels['title']}\n\n{labels['empty']}"

        featured_count = min(_FRIEND_DIGEST_FEATURED, len(selected))
        intro = (
            labels["intro_singular"]
            if featured_count == 1
            else labels["intro"]
        )
        lines = [
            f"# {labels['title']}",
            "",
            intro.format(
                count=len(selected),
                featured=featured_count,
            ),
        ]

        for index, item in enumerate(selected[:featured_count], start=1):
            raw_title, sentences = self._friend_content(item, language)
            title = _escape_markdown(raw_title)
            source = _escape_markdown(self._friend_source(item))
            if language == "zh":
                title = _pangu(title)
                source = _pangu(source)
            url = _safe_url(item.url)
            title_link = f"[{title}]({url})" if url else title
            lines.extend(["", f"## {index}. {title_link}"])

            escaped_sentences = [_escape_markdown(sentence) for sentence in sentences]
            if language == "zh":
                escaped_sentences = [_pangu(sentence) for sentence in escaped_sentences]
            if len(escaped_sentences) >= 2:
                lines.extend(
                    [
                        "",
                        f"**{labels['what']}:** {escaped_sentences[0]}",
                        "",
                        f"**{labels['why']}:** {' '.join(escaped_sentences[1:3])}",
                    ]
                )
            elif escaped_sentences:
                lines.extend(["", f"**{labels['key']}:** {escaped_sentences[0]}"])

            source_line = f"**{labels['source']}:** {source}"
            if url:
                source_line += f" · [{labels['read_more']}]({url})"
            lines.extend(["", source_line])

        remaining = selected[featured_count:]
        if remaining:
            lines.extend(["", f"## {labels['more']}", ""])
            for index, item in enumerate(remaining, start=featured_count + 1):
                raw_title, sentences = self._friend_content(item, language)
                title = _escape_markdown(raw_title)
                source = _escape_markdown(self._friend_source(item))
                summary = _escape_markdown(sentences[0]) if sentences else ""
                if language == "zh":
                    title = _pangu(title)
                    source = _pangu(source)
                    summary = _pangu(summary)
                url = _safe_url(item.url)
                title_link = f"[{title}]({url})" if url else title
                detail = f"：{summary}" if language == "zh" and summary else ""
                if language != "zh" and summary:
                    detail = f" — {summary}"
                lines.append(f"{index}. {title_link}{detail} · {source}")

        lines.extend(["", labels["closing"]])
        return "\n".join(lines)

    def generate_clawbot_digest(
        self,
        items: List[ContentItem],
        date: str,
        language: str,
        page_url: str | None,
    ) -> str:
        """Render one deterministic plain-text digest for ClawBot."""
        safe_page_url = (
            _validated_page_url(page_url, "page_url") if page_url else None
        )

        selected = items[:3]
        if language == "zh":
            lines = [f"早上好，这是 {date} 的 AI 日报速览。"]
            unavailable = "完整日报暂未发布，请稍后再试。"
            link_label = "完整日报"
        else:
            lines = [f"Good morning. Here is your AI briefing for {date}."]
            unavailable = "The full report is not published yet. Please try again later."
            link_label = "Full report"

        for index, item in enumerate(selected, start=1):
            title, sentences = self._friend_content(item, language)
            normalized_title = re.sub(r"\s+", " ", title).strip()
            conclusion = (
                re.sub(r"\s+", " ", sentences[0]).strip() if sentences else ""
            )
            line = f"{index}. {normalized_title}"
            if conclusion:
                line += f" - {conclusion}"
            lines.append(line)

        if not selected:
            lines.append(
                "今天暂无达到阈值的动态。"
                if language == "zh"
                else "No updates met today's threshold."
            )
        lines.append(
            f"{link_label}: {safe_page_url}" if safe_page_url else unavailable
        )
        return "\n".join(lines)

    def generate_clawbot_bilingual_digest(
        self,
        items: List[ContentItem],
        date: str,
        page_urls: Mapping[str, str],
    ) -> str:
        if not {"zh", "en"}.issubset(page_urls):
            raise ValueError("ClawBot bilingual digest requires zh and en page URLs")
        zh_url = _validated_page_url(page_urls["zh"], "zh page URL")
        en_url = _validated_page_url(page_urls["en"], "en page URL")
        lines = [f"早上好，这是 {date} 的 AI 日报速览。"]
        for index, item in enumerate(items[:3], start=1):
            title, sentences = self._friend_content(item, "zh")
            title = re.sub(r"[<\[]", "", re.sub(r"\s+", " ", title)).strip()
            conclusion = (
                re.sub(r"[<\[]", "", re.sub(r"\s+", " ", sentences[0])).strip()
                if sentences
                else ""
            )
            lines.append(f"{index}. {title}" + (f" - {conclusion}" if conclusion else ""))
        if not items:
            lines.append("今天暂无达到筛选阈值的动态。")
        lines.extend(["", f"中文完整日报: {zh_url}", f"English report: {en_url}"])
        return "\n".join(lines)

    def generate_webhook_overview(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate a compact overview for multi-message webhook delivery."""
        labels = LABELS.get(language, LABELS["en"])
        if not items:
            return self._generate_empty_summary(date, total_fetched, labels)

        if language == "zh":
            header = (
                f"# {labels['header']} - {date}\n\n"
                f"> 从 {total_fetched} 条内容中筛选出 {len(items)} 条重要资讯。\n\n"
                "下面会按内容逐条发送详情，你可以只看感兴趣的标题。\n\n"
            )
        else:
            header = (
                f"# {labels['header']} - {date}\n\n"
                f"> Selected {len(items)} important items from {total_fetched} fetched items.\n\n"
                "Details will be sent item by item so you can read only the topics you care about.\n\n"
            )

        sections = []
        view = self.build_view(items, language)
        for group in view.groups:
            profile_name = _escape_markdown(group.name)
            if language == "zh":
                profile_name = _pangu(profile_name)
            entries = [f"**{profile_name}**"]
            for view_item in group.items:
                title = _escape_markdown(view_item.title)
                if language == "zh":
                    title = _pangu(title)
                url = _safe_url(view_item.item.url)
                title_link = f"[{title}]({url})" if url else title
                entries.append(
                    f"{view_item.index}. {title_link} "
                    f"\u2b50\ufe0f {view_item.score}/10"
                )
            sections.append("\n".join(entries))

        return header + "\n\n".join(sections)

    def generate_webhook_item(
        self,
        item: ContentItem,
        language: str,
        index: int,
        total: int,
        *,
        title: Optional[str] = None,
        score: float | str | None = None,
    ) -> str:
        """Generate one item message for multi-message webhook delivery."""
        labels = LABELS.get(language, LABELS["en"])
        prefix = f"第 {index}/{total} 条\n\n" if language == "zh" else f"Item {index}/{total}\n\n"
        return prefix + self._format_item(
            item,
            labels,
            language,
            index,
            title_override=title,
            score_override=score,
        ).rstrip("-\n ")

    def _format_item(
        self,
        item: ContentItem,
        labels: dict,
        language: str,
        index: int,
        *,
        heading_level: int = 2,
        anchor_id: Optional[str] = None,
        title_override: Optional[str] = None,
        score_override: float | str | None = None,
    ) -> str:
        """Format a single ContentItem into Markdown."""
        artifact = item.processing.artifacts.get(language) if item.processing else None
        analysis = item.processing.analysis if item.processing else None
        _title = title_override or (artifact.title if artifact else item.title)
        title = _escape_markdown(_title)
        raw_url = str(item.url)
        url = _safe_url(raw_url)
        score = (
            score_override
            if score_override is not None
            else analysis.score
            if analysis and analysis.score is not None
            else "?"
        )
        meta = item.metadata

        summary = artifact.lead if artifact else analysis.summary if analysis else ""

        summary = _escape_markdown(summary)

        if language == "zh":
            title = _pangu(title)
            summary = _pangu(summary)

        # Source line with parts joined by " · ", link appended at end
        source_type = item.source_type.value
        source_parts = [_escape_markdown(source_type)]
        if meta.get("subreddit"):
            source_parts.append(_escape_markdown(f"r/{meta['subreddit']}"))
        if meta.get("feed_name"):
            source_parts.append(_escape_markdown(meta["feed_name"]))
        else:
            source_parts.append(_escape_markdown(item.author or "unknown"))
        if item.published_at:
            if language == "zh":
                source_parts.append(
                    f"{item.published_at.month}月{item.published_at.day}日 "
                    f"{item.published_at:%H:%M}"
                )
            else:
                day = item.published_at.strftime("%d").lstrip("0")
                source_parts.append(item.published_at.strftime(f"%b {day}, %H:%M"))
        source_line = " \u00b7 ".join(source_parts)  # ·

        discussion_url = meta.get("discussion_url")
        if discussion_url:
            safe_discussion_url = _safe_url(discussion_url)
            if safe_discussion_url and str(discussion_url) != raw_url:
                source_line += f' · [{labels["discussion"]}]({safe_discussion_url})'

        title_link = f"[{title}]({url})" if url else title

        lines = [
            f'<a id="{anchor_id or f"item-{index}"}"></a>',
            f"{'#' * heading_level} {title_link} \u2b50\ufe0f {score}/10",  # ⭐️
            "",
            summary,
            "",
            source_line,
        ]

        if artifact:
            for block in artifact.blocks:
                block_title = _escape_markdown(block.title)
                block_content = _escape_markdown(block.content)
                if language == "zh":
                    block_title = _pangu(block_title)
                    block_content = _pangu(block_content)
                lines.extend(
                    ["", f"{'#' * (heading_level + 1)} {block_title}", "", block_content]
                )

        sources = artifact.sources if artifact else []
        if sources:
            reference_items = []
            for source in sources:
                reference_title = html.escape(source.title, quote=True)
                reference_url = _safe_url(source.url)
                if reference_url:
                    reference_items.append(f'<li><a href="{reference_url}">{reference_title}</a></li>\n')
                else:
                    reference_items.append(f"<li>{reference_title}</li>\n")
            items_html = "".join(reference_items)
            lines += [
                "",
                f'<details><summary>{labels["references"]}</summary>\n<ul>\n{items_html}\n</ul>\n</details>',
            ]

        if analysis and analysis.tags:
            tags_str = ", ".join([f"`#{_escape_markdown(t)}`" for t in analysis.tags])
            lines.append("")
            lines.append(f"**{labels['tags']}**: {tags_str}")

        lines.append("")
        lines.append("---")

        return "\n".join(lines) + "\n\n"

    def _generate_empty_summary(self, date: str, total_fetched: int, labels: dict) -> str:
        """Generate summary when no high-scoring items were found."""
        return (
            f"# {labels['header']} - {date}\n\n"
            f"> {labels['empty_analyzed'].format(total=total_fetched)}\n\n"
            + labels["empty_body"]
        )
