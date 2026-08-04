# PushPlus Friend Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Horizon 在 PushPlus overview 模式下每天分别发送一条克制、自然、专业的中英文好友式 AI 资讯摘要。

**Architecture:** 在 `DailySummarizer` 中新增不访问网络的好友摘要渲染器，直接消费现有的评分排序结果和目标语言 artifact。`WebhookNotifier` 只在 `platform="pushplus"` 且 `delivery="overview"` 时选择新渲染器，其他平台、delivery 模式和完整日报保持原样。

**Tech Stack:** Python 3.11+、Pydantic、pytest、httpx、PushPlus Markdown webhook、PowerShell、uv。

## Global Constraints

- 每种启用语言只生成一条 overview；目标配置为 `webhook.languages = ["zh", "en"]`。
- 每条消息最多 12 条，其中前 3 条详细，其余最多 9 条一句话概括。
- 继续使用现有评分降序，不在好友摘要中显示分数。
- 只使用对应语言的 `ContentArtifact`；缺失时不跨语言回退。
- 不增加 Aoligei 请求，不修改分析或 enrichment 提示词，不增加第三方依赖。
- 不改变完整 Markdown 日报、邮件、飞书折叠卡片、非 PushPlus overview 或 `summary_and_items`。
- 外部标题、摘要和来源必须经过现有 Markdown 转义，链接必须经过现有 `_safe_url` 校验。
- 不输出 `.env`、Aoligei token 或 PushPlus token 的值。
- 本计划不注册 Windows 定时任务。

---

## File Structure

- Modify: `src/ai/summarizer.py` - 定义好友摘要文案、完整句拆分、目标语言内容选择、来源显示和纯 Markdown 渲染。
- Modify: `tests/test_summarizer.py` - 覆盖双语、3+9 布局、12 条上限、空内容、单句、缺失 artifact 和安全转义。
- Modify: `src/services/webhook.py` - 仅在 PushPlus overview 分支选择好友摘要和新标题。
- Modify: `tests/test_pushplus.py` - 锁定 PushPlus 路由、双语标题和非目标分支回归行为。
- Modify: `src/services/webhook_cli.py` - 为现有 webhook 预览和实发命令补齐英文 artifact，使双语验收消息都能展示完整好友摘要。
- Create: `tests/test_webhook_cli.py` - 验证 CLI 样例同时具备中英文 artifact，并能生成两种语言的好友摘要。

---

### Task 1: Pure Friend Digest Renderer

**Files:**
- Modify: `src/ai/summarizer.py:19-49`
- Modify: `src/ai/summarizer.py:286-350`
- Modify: `tests/test_summarizer.py:23-72`

**Interfaces:**
- Consumes: `List[ContentItem]`，其中输入顺序已经是评分降序；每个条目可包含 `processing.artifacts[language]`。
- Produces: `DailySummarizer.generate_friend_digest(items: List[ContentItem], date: str, total_fetched: int, language: str = "en") -> str`。
- Preserves: `_escape_markdown(value) -> str`、`_safe_url(value) -> Optional[str]`、`_pangu(text) -> str` 的现有安全语义。

- [ ] **Step 1: Add localized fixture data and the core failing layout test**

在 `tests/test_summarizer.py` 中加入独立 helper，不改变现有 `_make_item` 的断言语义：

```python
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
    assert "/10" not in result
    assert result.index("English Item 1") < result.index("English Item 12")
```

- [ ] **Step 2: Run the core test and confirm RED**

Run:

```powershell
uv run pytest tests/test_summarizer.py::test_generate_friend_digest_features_three_and_summarizes_nine -q
```

Expected: FAIL with `AttributeError: 'DailySummarizer' object has no attribute 'generate_friend_digest'`.

- [ ] **Step 3: Add localized labels and complete-sentence splitting**

在 `src/ai/summarizer.py` 的现有常量旁加入：

```python
_FRIEND_DIGEST_LIMIT = 12
_FRIEND_DIGEST_FEATURED = 3
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？])|(?<=[.!?])(?=\s|$)")

FRIEND_DIGEST_LABELS = {
    "en": {
        "title": "A few AI updates worth your time today",
        "intro": (
            "I went through today's updates and picked {count}. "
            "These {featured} are worth starting with:"
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


def _split_sentences(value: object) -> List[str]:
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    if not normalized:
        return []
    return [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY.split(normalized)
        if sentence.strip()
    ]
```

- [ ] **Step 4: Implement the minimal pure renderer**

在 `generate_webhook_overview` 前新增以下方法。来源规则保持局部、明确，不把该功能耦合到 orchestrator：

```python
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
        lines = [
            f"# {labels['title']}",
            "",
            labels["intro"].format(
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
```

- [ ] **Step 5: Run the core layout test and confirm GREEN**

Run:

```powershell
uv run pytest tests/test_summarizer.py::test_generate_friend_digest_features_three_and_summarizes_nine -q
```

Expected: `1 passed`.

- [ ] **Step 6: Add bilingual and degradation regression tests**

在 `tests/test_summarizer.py` 继续加入：

```python
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
```

- [ ] **Step 7: Run all friend-digest tests**

Run:

```powershell
uv run pytest tests/test_summarizer.py -k friend_digest -q
```

Expected: all six friend-digest tests PASS.

- [ ] **Step 8: Run the complete summarizer regression file**

Run:

```powershell
uv run pytest tests/test_summarizer.py tests/test_source_traceability.py -q
```

Expected: all tests PASS, including existing overview and original-source link assertions.

- [ ] **Step 9: Commit the pure renderer**

```powershell
git add -- src/ai/summarizer.py tests/test_summarizer.py
git commit -m "feat: render bilingual PushPlus friend digests"
```

---

### Task 2: PushPlus-Only Routing

**Files:**
- Modify: `src/services/webhook.py:555-575`
- Modify: `tests/test_pushplus.py:1-46`

**Interfaces:**
- Consumes: `DailySummarizer.generate_friend_digest(items, date, total_fetched, language) -> str` from Task 1.
- Produces: one overview variables dict whose `summary` is the friend digest and whose `message_title` is localized only for PushPlus overview.
- Preserves: `generate_webhook_overview` for generic overview and PushPlus `summary_and_items`.

- [ ] **Step 1: Preserve the generic overview test and add failing PushPlus routing tests**

在 `tests/test_pushplus.py` 顶部加入 `import pytest`，保留现有 generic overview test，并加入：

```python
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
```

- [ ] **Step 2: Run the routing tests and confirm RED**

Run:

```powershell
uv run pytest tests/test_pushplus.py -k "friend_digest or summary_and_items or compact_message" -q
```

Expected: the two parametrized friend-digest cases FAIL because the notifier still calls `generate_webhook_overview`; generic and `summary_and_items` cases PASS.

- [ ] **Step 3: Add the narrow platform and delivery branch**

将 `src/services/webhook.py` 中 overview 构建部分改为等价于：

```python
        delivery = getattr(self.config, "delivery", "summary")
        if delivery in {"overview", "summary_and_items"}:
            item_messages: List[dict[str, Any]] = []
            use_friend_digest = (
                self.config.platform == "pushplus" and delivery == "overview"
            )
            if use_friend_digest:
                overview = summarizer.generate_friend_digest(
                    important_items,
                    date,
                    all_items_count,
                    language=lang,
                )
                message_title = (
                    "今天这几条 AI 动态值得看"
                    if lang == "zh"
                    else "A few AI updates worth your time today"
                )
            else:
                overview = summarizer.generate_webhook_overview(
                    important_items,
                    date,
                    all_items_count,
                    language=lang,
                )
                message_title = (
                    f"Horizon {date} 总览"
                    if lang == "zh"
                    else f"Horizon {date} Overview"
                )

            overview_message = {
                **base_vars,
                "message_title": message_title,
                "message_kind": "overview",
                "summary": overview,
            }
```

保留该区块后面的 `delivery == "overview"` 提前返回、逐条消息构建和 `overview_position` 逻辑，不移动飞书分支。

- [ ] **Step 4: Run PushPlus unit tests and confirm GREEN**

Run:

```powershell
uv run pytest tests/test_pushplus.py -q
```

Expected: all PushPlus tests PASS.

- [ ] **Step 5: Run broader webhook regressions**

Run:

```powershell
uv run pytest tests/test_webhook.py tests/test_mcp_service_smoke.py -q
```

Expected: all tests PASS; generic overview、summary、summary-and-items、飞书和 MCP webhook 行为均保持原样。

- [ ] **Step 6: Commit PushPlus routing**

```powershell
git add -- src/services/webhook.py tests/test_pushplus.py
git commit -m "feat: route PushPlus overview to friend digest"
```

---

### Task 3: Bilingual Webhook Test Fixture

**Files:**
- Modify: `src/services/webhook_cli.py:25-105`
- Create: `tests/test_webhook_cli.py`

**Interfaces:**
- Consumes: `_make_test_items() -> list[ContentItem]` and `DailySummarizer.generate_friend_digest(...)`。
- Produces: every CLI sample item has both `processing.artifacts["zh"]` and `processing.artifacts["en"]`，供现有 `horizon-webhook --lang` dry-run 和实发路径使用。
- Preserves: CLI 参数、配置加载、token 读取和发送实现不变。

- [ ] **Step 1: Write the failing bilingual fixture test**

创建 `tests/test_webhook_cli.py`：

```python
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
```

- [ ] **Step 2: Run the fixture test and confirm RED**

Run:

```powershell
uv run pytest tests/test_webhook_cli.py -q
```

Expected: FAIL because current sample items contain only the `zh` artifact.

- [ ] **Step 3: Add the English artifact without changing CLI behavior**

扩展 `_sample_processing` 的签名：

```python
def _sample_processing(
    score: float,
    summary: str,
    tags: list[str],
    title_en: str,
    title_zh: str,
    lead_zh: str,
) -> ProcessingResult:
```

两个 `_sample_processing` 调用分别改为：

```python
            processing=_sample_processing(
                score=9.0,
                summary="OpenAI released GPT-5 featuring multimodal capabilities and improved reasoning.",
                tags=["ai", "llm", "openai"],
                title_en="GPT-5 Released with Multimodal Capabilities",
                title_zh="GPT-5 发布：多模态能力大幅提升",
                lead_zh="OpenAI 发布了 GPT-5，具备多模态能力和更强的推理能力。",
            ),
```

```python
            processing=_sample_processing(
                score=7.5,
                summary="Linux kernel 7.0 released with performance gains and new hardware support.",
                tags=["linux", "kernel", "performance"],
                title_en="New Linux Kernel 7.0 Released",
                title_zh="Linux 内核 7.0 发布",
                lead_zh="Linux 内核 7.0 发布，带来显著性能提升和新硬件支持。",
            ),
```

将 artifacts 改为同时包含：

```python
        artifacts={
            "en": ContentArtifact(
                language="en",
                title=title_en,
                blocks=[
                    ContentBlock(
                        id="summary",
                        role="summary",
                        title="Summary",
                        content=summary,
                    )
                ],
            ),
            "zh": ContentArtifact(
                language="zh",
                title=title_zh,
                blocks=[
                    ContentBlock(
                        id="summary",
                        role="summary",
                        title="摘要",
                        content=lead_zh,
                    )
                ],
            ),
        },
```

不改变 `_run_test`、`main`、环境变量或请求构建代码。

- [ ] **Step 4: Run CLI and renderer tests**

Run:

```powershell
uv run pytest tests/test_webhook_cli.py tests/test_summarizer.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Preview both language payloads without sending**

Run:

```powershell
uv run horizon-webhook --lang zh --dry-run
uv run horizon-webhook --lang en --dry-run
```

Expected: each command renders exactly one `overview` message; output title and body use only the requested language; preview redacts configured token fields.

- [ ] **Step 6: Commit the bilingual test fixture**

```powershell
git add -- src/services/webhook_cli.py tests/test_webhook_cli.py
git commit -m "test: add bilingual friend digest webhook samples"
```

---

### Task 4: Full Verification and Real PushPlus Delivery

**Files:**
- Verify only: `src/ai/summarizer.py`
- Verify only: `src/services/webhook.py`
- Verify only: `src/services/webhook_cli.py`
- Verify only: `data/config.json`
- Verify only: `.env`

**Interfaces:**
- Consumes: the renderer, PushPlus routing and bilingual CLI fixtures completed in Tasks 1-3.
- Produces: automated regression evidence, online endpoint evidence and two real daily messages returned successfully by PushPlus.

- [ ] **Step 1: Run all focused tests together**

Run:

```powershell
uv run pytest tests/test_summarizer.py tests/test_source_traceability.py tests/test_pushplus.py tests/test_webhook_cli.py tests/test_webhook.py tests/test_mcp_service_smoke.py -q
```

Expected: all focused and adjacent regression tests PASS.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
uv run pytest -q
```

Expected: the complete suite reports zero failures.

- [ ] **Step 3: Run the offline secret and configuration check**

Run:

```powershell
uv run python scripts/check_local_setup.py --offline
```

Expected: `Offline configuration check passed`. The command must not print any token value.

- [ ] **Step 4: Probe Aoligei, sources and PushPlus transport**

Run:

```powershell
uv run python scripts/check_local_setup.py --online --test-pushplus
```

Expected: `Offline configuration check passed`, successful source fetches, a successful PushPlus HTTP/business response, and `Online checks passed`.

- [ ] **Step 5: Send one localized sample message per language**

Run:

```powershell
uv run horizon-webhook --lang zh
uv run horizon-webhook --lang en
```

Expected: each command logs one successful PushPlus send. The received messages have the approved titles, do not show scores, and do not contain “下面会逐条发送详情”.

- [ ] **Step 6: Execute one real 24-hour Horizon run**

Run:

```powershell
uv run horizon --hours 24
```

Expected: Aoligei produces both localized artifacts, Horizon sends exactly one Chinese and one English PushPlus overview, and each PushPlus response has HTTP success with business code `200`.

- [ ] **Step 7: Inspect the final working tree without changing unrelated files**

Run:

```powershell
git status --short
git diff --check
```

Expected: no whitespace errors; only task-owned files differ from their pre-task state. Existing unrelated user changes remain untouched.

---

## Completion Criteria

- All Task 1-3 commits contain only their listed files.
- All focused tests and the full suite pass.
- Online setup check succeeds without revealing secrets.
- PushPlus accepts one Chinese and one English friend digest in both sample and real daily paths.
- Generic overview, PushPlus `summary_and_items`, complete reports and other webhook platforms retain their previous behavior.
- No scheduled task is created or modified.
