"""Pure HTML rendering for public Horizon daily pages."""

from dataclasses import dataclass
import html
import re
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from ..ai.summarizer import DailySummarizer
from ..models import ContentArtifact, ContentItem


DAILY_CSS = """
:root { color-scheme: light; --ink: #18231d; --muted: #617068; --line: #d8dfda; --accent: #176b45; --paper: #ffffff; }
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
body { margin: 0; font-size: 16px; line-height: 1.65; letter-spacing: 0; }
a { color: var(--accent); text-underline-offset: 0.18em; overflow-wrap: anywhere; }
.page-shell { width: 100%; max-width: 680px; margin-inline: auto; padding-inline: 18px; }
.site-header { padding-block: 28px 20px; border-bottom: 1px solid var(--line); }
.brand { margin: 0; color: var(--accent); font-size: 0.875rem; font-weight: 700; }
.site-header h1 { margin: 6px 0 0; font-size: 1.75rem; line-height: 1.25; }
.daily-meta { margin: 10px 0 0; color: var(--muted); }
.daily-item { display: grid; grid-template-columns: 2.25rem minmax(0, 1fr); gap: 14px; padding-block: 22px; border-bottom: 1px solid var(--line); }
.daily-number { color: var(--accent); font-variant-numeric: tabular-nums; font-weight: 700; }
.daily-content { min-width: 0; }
.daily-content h2 { margin: 0; font-size: 1.125rem; line-height: 1.4; overflow-wrap: anywhere; }
.scan-summary { margin: 10px 0 0; color: var(--muted); }
details { margin-top: 12px; }
summary { display: flex; align-items: center; min-height: 44px; color: var(--accent); cursor: pointer; font-weight: 650; }
.details-body { padding-bottom: 4px; overflow-wrap: anywhere; }
.details-body h3 { margin: 18px 0 4px; font-size: 1rem; }
.details-body p { margin: 6px 0; }
.details-body ul { margin: 8px 0 0; padding-left: 1.25rem; }
.language-switch { display: flex; gap: 14px; align-items: center; min-height: 44px; }
.empty-state { padding-block: 32px; color: var(--muted); }
.daily-index ol { margin: 0; padding: 0; list-style: none; }
.daily-index li { display: flex; justify-content: space-between; gap: 18px; padding-block: 16px; border-bottom: 1px solid var(--line); }
.daily-index li span { display: flex; gap: 14px; }
@media (max-width: 360px) { .daily-item { grid-template-columns: 1.8rem minmax(0, 1fr); gap: 10px; } }
""".strip()


@dataclass(frozen=True)
class DailyPageBundle:
    date: str
    files: Mapping[str, str]
    urls: Mapping[str, str]


def render_daily_page(
    items: Sequence[ContentItem],
    date: str,
    total_fetched: int,
    language: str,
    summarizer: DailySummarizer,
) -> str:
    view = summarizer.build_view(list(items), language)
    rendered_items = []
    for group in view.groups:
        for view_item in group.items:
            rendered_items.append(
                _render_item(view_item.item, view_item.global_index, language)
            )
    body = "".join(rendered_items) or _render_empty(language)
    alternate = "en" if language == "zh" else "zh"
    return _document(
        language=language,
        title="Horizon Daily",
        body=body,
        header=_render_header(
            date,
            view.item_count,
            total_fetched,
            language,
            alternate,
        ),
        stylesheet_href="../../assets/horizon-daily.css",
    )


def render_index_page(dates: Sequence[str]) -> str:
    safe_dates = {
        date for date in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
    }
    rows = "".join(
        f'<li><time datetime="{html.escape(date, quote=True)}">'
        f"{html.escape(date)}</time>"
        f'<span><a href="daily/{date}/zh.html">中文</a>'
        f'<a href="daily/{date}/en.html">English</a></span></li>'
        for date in sorted(safe_dates, reverse=True)
    )
    return _document(
        language="zh",
        title="Horizon Daily",
        header=(
            '<header class="site-header"><p class="brand">Horizon Daily</p>'
            "<h1>每日 AI 情报</h1></header>"
        ),
        body=f'<main class="daily-index"><ol>{rows}</ol></main>',
        stylesheet_href="assets/horizon-daily.css",
    )


def build_daily_page_bundle(
    items: Sequence[ContentItem],
    date: str,
    total_fetched: int,
    languages: Sequence[str],
    summarizer: DailySummarizer,
    site_url: str,
) -> DailyPageBundle:
    root = site_url.rstrip("/")
    files = {
        f"daily/{date}/{language}.html": render_daily_page(
            items, date, total_fetched, language, summarizer
        )
        for language in languages
    }
    urls = {
        language: f"{root}/daily/{date}/{language}.html"
        for language in languages
    }
    return DailyPageBundle(date=date, files=files, urls=urls)


def _render_header(
    date: str,
    item_count: int,
    total_fetched: int,
    language: str,
    alternate: str,
) -> str:
    escaped_date = html.escape(date, quote=True)
    escaped_language = html.escape(language, quote=True)
    if language == "zh":
        heading = "每日 AI 情报"
        meta = f"{escaped_date} · 从 {total_fetched} 条更新中精选 {item_count} 条"
        alternate_label = "English"
    else:
        heading = "Daily AI briefing"
        meta = f"{escaped_date} · {item_count} selected from {total_fetched} updates"
        alternate_label = "中文"
    return (
        f'<header class="site-header" data-horizon-date="{escaped_date}" '
        f'data-language="{escaped_language}">'
        '<p class="brand">Horizon Daily</p>'
        f"<h1>{heading}</h1>"
        f'<p class="daily-meta">{meta}</p>'
        '<nav class="language-switch" aria-label="Language">'
        f'<a href="{alternate}.html">{alternate_label}</a></nav></header>'
    )


def _render_item(item: ContentItem, global_index: int, language: str) -> str:
    artifact = _artifact(item, language)
    title = artifact.title if artifact and artifact.title else item.title
    lead = _lead(item, artifact)
    sentences = _sentences(lead)
    scan_text = " ".join(sentences[:2]) or lead
    details = []
    if lead:
        details.append(f"<p>{html.escape(lead)}</p>")
    if artifact:
        for block in artifact.blocks:
            details.append(
                f"<section><h3>{html.escape(block.title)}</h3>"
                f"<p>{html.escape(block.content)}</p></section>"
            )
        references = []
        for source in artifact.sources:
            label = html.escape(source.title)
            href = _safe_href(source.url)
            if href:
                references.append(
                    f'<li><a href="{html.escape(href, quote=True)}" '
                    f'rel="noopener noreferrer">{label}</a></li>'
                )
            else:
                references.append(f"<li>{label}</li>")
        if references:
            source_title = "原文" if language == "zh" else "Sources"
            details.append(f"<section><h3>{source_title}</h3><ul>{''.join(references)}</ul></section>")
    details_label = "详情与原文" if language == "zh" else "Details and sources"
    return (
        '<article class="daily-item">'
        f'<div class="daily-number">{global_index:02d}</div>'
        '<div class="daily-content">'
        f"<h2>{html.escape(title)}</h2>"
        f'<p class="scan-summary">{html.escape(scan_text)}</p>'
        f"<details><summary>{details_label}</summary>"
        f'<div class="details-body">{"".join(details)}</div></details>'
        "</div></article>"
    )


def _artifact(item: ContentItem, language: str) -> ContentArtifact | None:
    if not item.processing:
        return None
    return item.processing.artifacts.get(language)


def _lead(item: ContentItem, artifact: ContentArtifact | None) -> str:
    if artifact:
        if artifact.lead.strip():
            return artifact.lead.strip()
        for block in artifact.blocks:
            if block.content.strip():
                return block.content.strip()
    if item.processing and item.processing.analysis:
        return item.processing.analysis.summary.strip()
    return (item.content or "").strip()


def _sentences(value: str) -> list[str]:
    if not value:
        return []
    matches = re.findall(r".+?(?:[。！？!?]|\.(?=\s|$))|.+$", value, re.DOTALL)
    return [re.sub(r"\s+", " ", match).strip() for match in matches if match.strip()]


def _safe_href(value: str) -> str | None:
    raw = value.strip()
    if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return raw


def _render_empty(language: str) -> str:
    copy = (
        "今天暂无达到阈值的动态"
        if language == "zh"
        else "No updates met today's threshold"
    )
    return f'<main class="empty-state"><p>{copy}</p></main>'


def _document(
    language: str,
    title: str,
    header: str,
    body: str,
    stylesheet_href: str,
) -> str:
    lang = "zh-CN" if language == "zh" else "en"
    return (
        "<!doctype html>"
        f'<html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        f'<link rel="stylesheet" href="{html.escape(stylesheet_href, quote=True)}">'
        f'</head><body><div class="page-shell">{header}{body}</div></body></html>'
    )
