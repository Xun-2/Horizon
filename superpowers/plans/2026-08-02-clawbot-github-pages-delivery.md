# ClawBot GitHub Pages Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Horizon 每日中英文日报发布到 `Xun-2/Horizon` 的公开 GitHub Pages，并只通过 PushPlus 微信 ClawBot 发送纯文本速览、对应页面链接和可验证的最终投递状态。

**Architecture:** 结构化 `ContentItem` 先由纯函数渲染为移动端静态 HTML，再由独立 GitHub REST 客户端写入远端 `gh-pages`，确认公开 URL 可用后才生成 ClawBot 链接。PushPlus 专用客户端固定发送 `channel=clawbot`、`template=txt`，使用开放接口 AccessKey 检查对话令牌并轮询消息终态；编排器只负责按“本地保存 -> 页面发布 -> 消息发送”的顺序连接这些组件。

**Tech Stack:** Python 3.11+、Pydantic 2、`httpx`、现有 `safe_request`、GitHub REST API、PushPlus 消息 API/开放接口、pytest、Playwright Chromium、Windows PowerShell。

## Global Constraints

- 公开页面固定为 `https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/zh.html` 和 `https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/en.html`。
- 远端内容只通过 GitHub REST API 写 `gh-pages`；运行期不得调用 `git add`、`git commit` 或 `git push`，不得自动提交本地 `main`。
- GitHub Contents 更新必须携带当前 SHA；当天两个语言页面全部成功后才能更新首页。
- PushPlus 请求必须固定包含 `channel: "clawbot"` 和 `template: "txt"`，不得隐式回退到 `wechat`。
- 每种配置语言只发送一条纯文本消息，最多三条“标题 + 一句结论”；Pages 成功时附对应语言链接，失败时明确写“完整日报暂未发布”且不含死链接。
- PushPlus HTTP 2xx 和业务 `code=200` 只表示请求已受理；只有开放接口状态 `2` 才能记录“ClawBot 已送达”。
- PushPlus 开放接口默认关闭。真实运行前，用户必须在控制台设置 `secretKey`、安全 IP 并启用开放接口；`PUSHPLUS_TOKEN` 必须是用户 Token，不能是消息 Token。
- `HORIZON_GITHUB_TOKEN`、`PUSHPLUS_TOKEN`、`PUSHPLUS_SECRET_KEY` 和 `AOLIGEI_API_KEY` 只保存在被忽略的 `.env` 中，不得进入日志、预览、异常详情或提交历史。
- 手机页面使用 B“快速扫描”布局：正文最大宽度 `680px`、手机左右边距 `18px`、正文字号至少 `16px`、行高约 `1.65`、点击区域至少 `44px`。
- 页面为浅色单主题、深绿色单一强调色，无外部字体、图片、运行时 JavaScript、营销 Hero、嵌套卡片、渐变装饰或横向滚动。
- 单元和集成测试必须模拟所有外部接口；只有最终真实验收步骤可以写远端 Pages 或发送 ClawBot 消息。
- 当前工作区包含大量用户修改和未跟踪文件。每个提交只能使用任务中列出的精确路径，提交前必须运行 `git diff --cached --name-status`；禁止 `git add .`。

## Verified External Contracts

- PushPlus 发送接口：`POST https://www.pushplus.plus/send`。成功响应 `data` 是消息流水号，并不代表已送达。
- PushPlus AccessKey：`POST https://www.pushplus.plus/api/common/openApi/getAccessKey`，JSON 为用户 Token 和独立 `secretKey`；返回的 `accessKey` 有效期由 `expiresIn` 给出，当前文档示例为 7200 秒。
- ClawBot 绑定状态：`GET https://www.pushplus.plus/api/open/clawBot/botInfo`，请求头 `access-key`；`data.haveContextToken == 1` 才表示当前有对话令牌。
- 消息最终状态：`GET https://www.pushplus.plus/api/open/message/sendMessageResult?shortCode=...`，请求头 `access-key`；`status` 映射为 `0=未投递`、`1=发送中`、`2=已发送`、`3=发送失败`。
- 官方依据：[消息接口文档](https://www.pushplus.plus/doc/guide/api.html)、[开放接口文档](https://www.pushplus.plus/doc/guide/openApi.html)、[ClawBot 渠道说明](https://www.pushplus.plus/doc/channel/clawbot.html)。

## File Map

- `src/models.py`: 增加 GitHub Pages 和 PushPlus ClawBot 的强类型配置合同。
- `src/services/daily_pages.py`: 纯函数 HTML/CSS 渲染，不做网络或文件写入。
- `src/services/github_pages.py`: 创建远端分支、Contents API 更新、Pages 启用和公开 URL 验证。
- `src/services/pushplus.py`: 固定 ClawBot 请求、AccessKey 生命周期、绑定检查和最终状态轮询。
- `src/ai/summarizer.py`: 生成最多三条的纯文本 ClawBot 速览。
- `src/services/webhook.py`: 保留通用 Webhook 行为，并把已配置的 PushPlus ClawBot 调用委托给专用客户端。
- `src/orchestrator.py`: 调整为先完成双语页面发布，再按语言发送消息。
- `scripts/check_local_setup.py`: 离线合同检查、Pages/ClawBot 联网检查和真实交付探针。
- `scripts/setup_local_secrets.ps1`: 安全写入四种密钥和固定 PushPlus URL。
- `.env.example`, `data/config.local.example.json`, `docs/local-ai-radar-setup.md`: 中文安装合同和无密钥示例。
- `tests/test_delivery_config.py`, `tests/test_daily_pages.py`, `tests/test_github_pages.py`, `tests/test_pushplus_open_api.py`, `tests/test_delivery_pipeline.py`, `tests/test_daily_pages_visual.py`: 新增分层回归与视觉验收。

---

### Task 1: Delivery Configuration Contracts

**Files:**
- Modify: `src/models.py:453-628`
- Create: `tests/test_delivery_config.py`
- Modify: `data/config.local.example.json`

**Interfaces:**
- Produces: `PushPlusClawBotConfig`, `GitHubPagesConfig`, `WebhookConfig.pushplus`, `Config.github_pages`。
- Consumers: Tasks 3-7 use these exact model names and field names.

- [ ] **Step 1: Write failing model tests**

```python
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from src.models import Config, GitHubPagesConfig, PushPlusClawBotConfig


@pytest.fixture
def valid_config_dict():
    path = Path(__file__).resolve().parents[1] / "data" / "config.local.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_clawbot_contract_has_fixed_channel_template_and_env_names():
    config = PushPlusClawBotConfig()
    assert config.channel == "clawbot"
    assert config.template == "txt"
    assert config.token_env == "PUSHPLUS_TOKEN"
    assert config.secret_key_env == "PUSHPLUS_SECRET_KEY"
    assert config.status_timeout_seconds == 90
    assert config.poll_interval_seconds == 2.0


@pytest.mark.parametrize("field", ["channel", "template"])
def test_clawbot_contract_rejects_fallback_values(field):
    value = {"channel": "wechat", "template": "markdown"}[field]
    with pytest.raises(ValidationError):
        PushPlusClawBotConfig(**{field: value})


def test_pages_contract_rejects_other_repository():
    with pytest.raises(ValidationError, match="Xun-2/Horizon"):
        GitHubPagesConfig(repository="someone/else")


def test_main_config_accepts_delivery_blocks(valid_config_dict):
    valid_config_dict["webhook"]["pushplus"] = {}
    valid_config_dict["github_pages"] = {
        "enabled": True,
        "repository": "Xun-2/Horizon",
        "site_url": "https://xun-2.github.io/Horizon",
    }
    config = Config.model_validate(valid_config_dict)
    assert config.webhook.pushplus.channel == "clawbot"
    assert config.github_pages.branch == "gh-pages"
```

The fixture intentionally loads the secret-free local example and never reads ignored `data/config.json`.

- [ ] **Step 2: Run the tests and verify the new types are missing**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_delivery_config.py`

Expected: FAIL during import because `GitHubPagesConfig` and `PushPlusClawBotConfig` do not exist.

- [ ] **Step 3: Add the exact configuration models**

Add before `WebhookConfig` in `src/models.py`:

```python
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PushPlusClawBotConfig(BaseModel):
    channel: Literal["clawbot"] = "clawbot"
    template: Literal["txt"] = "txt"
    token_env: str = "PUSHPLUS_TOKEN"
    secret_key_env: str = "PUSHPLUS_SECRET_KEY"
    status_timeout_seconds: int = Field(default=90, ge=10, le=300)
    poll_interval_seconds: float = Field(default=2.0, gt=0, le=10)

    @field_validator("token_env", "secret_key_env")
    @classmethod
    def validate_environment_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("environment variable name is invalid")
        return value


class GitHubPagesConfig(BaseModel):
    enabled: bool = False
    repository: str = "Xun-2/Horizon"
    source_branch: str = "main"
    branch: str = "gh-pages"
    token_env: str = "HORIZON_GITHUB_TOKEN"
    site_url: str = "https://xun-2.github.io/Horizon"
    verify_timeout_seconds: int = Field(default=120, ge=10, le=300)
    poll_interval_seconds: float = Field(default=2.0, gt=0, le=10)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if value != "Xun-2/Horizon":
            raise ValueError("repository must be Xun-2/Horizon")
        return value

    @field_validator("source_branch", "branch")
    @classmethod
    def validate_branch(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", value) or ".." in value:
            raise ValueError("branch name is invalid")
        return value

    @field_validator("token_env")
    @classmethod
    def validate_token_environment(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("environment variable name is invalid")
        return value

    @field_validator("site_url")
    @classmethod
    def validate_site_url(cls, value: str) -> str:
        if value.rstrip("/") != "https://xun-2.github.io/Horizon":
            raise ValueError("site_url must be the approved public Horizon URL")
        return value.rstrip("/")
```

Add `pushplus: Optional[PushPlusClawBotConfig] = None` to `WebhookConfig`, and `github_pages: Optional[GitHubPagesConfig] = None` to `Config`.

- [ ] **Step 4: Migrate the local example contract without adding secrets**

In `data/config.local.example.json`, replace the PushPlus `request_body` block with:

```json
"pushplus": {
  "channel": "clawbot",
  "template": "txt",
  "token_env": "PUSHPLUS_TOKEN",
  "secret_key_env": "PUSHPLUS_SECRET_KEY",
  "status_timeout_seconds": 90,
  "poll_interval_seconds": 2.0
}
```

Add this top-level block:

```json
"github_pages": {
  "enabled": true,
  "repository": "Xun-2/Horizon",
  "source_branch": "main",
  "branch": "gh-pages",
  "token_env": "HORIZON_GITHUB_TOKEN",
  "site_url": "https://xun-2.github.io/Horizon",
  "verify_timeout_seconds": 120,
  "poll_interval_seconds": 2.0
}
```

Keep `url_env: "HORIZON_WEBHOOK_URL"`, `platform: "pushplus"`, `delivery: "overview"`, and `languages: ["zh", "en"]`.

- [ ] **Step 5: Run the focused tests**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_delivery_config.py tests/test_profiles.py tests/test_pushplus.py`

Expected: PASS.

- [ ] **Step 6: Commit only the configuration contract**

```powershell
git add -- src/models.py tests/test_delivery_config.py data/config.local.example.json
git diff --cached --name-status
git commit -m "feat: define ClawBot Pages delivery config"
```

Expected staged paths: exactly the three paths above.

### Task 2: Mobile Daily Page Renderer

**Files:**
- Create: `src/services/daily_pages.py`
- Create: `tests/test_daily_pages.py`

**Interfaces:**
- Produces: `DailyPageBundle`, `render_daily_page(...)`, `render_index_page(...)`, `build_daily_page_bundle(...)`, `DAILY_CSS`.
- Consumes: `ContentItem`, `ContentArtifact`, and `DailySummarizer.build_view(...)`.
- Task 3 receives a `DailyPageBundle` without reading Markdown or local files.

- [ ] **Step 1: Write failing renderer tests**

Create localized fixtures using the real models:

```python
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
from src.services.daily_pages import DAILY_CSS, build_daily_page_bundle


def _item(title: str = "模型 <突破>", url: str = "https://example.com/a?x=1&y=2"):
    artifact = ContentArtifact(
        language="zh",
        title=title,
        lead="第一句概括。第二句说明影响。第三句只在详情中出现。",
        blocks=[ContentBlock(id="background", title="背景", content="长期背景信息")],
        sources=[ArtifactSource(id="s1", title="原始来源", url=url)],
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
    assert "<details" in html and "详情与原文" in html
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
    assert "No updates met today's threshold" in bundle.files["daily/2026-08-02/en.html"]
    assert "max-width: 680px" in DAILY_CSS
    assert "padding-inline: 18px" in DAILY_CSS
    assert "min-height: 44px" in DAILY_CSS
    assert "overflow-wrap: anywhere" in DAILY_CSS
```

- [ ] **Step 2: Run tests and verify the renderer module is missing**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_daily_pages.py`

Expected: FAIL with `ModuleNotFoundError: src.services.daily_pages`.

- [ ] **Step 3: Implement the pure page bundle and safe rendering helpers**

Use these exact public types and signatures:

```python
from dataclasses import dataclass
import html
import re
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from ..ai.summarizer import DailySummarizer
from ..models import ContentArtifact, ContentItem


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
        header=_render_header(date, view.item_count, total_fetched, language, alternate),
        stylesheet_href="../../assets/horizon-daily.css",
    )


def render_index_page(dates: Sequence[str]) -> str:
    rows = "".join(
        f'<li><time datetime="{html.escape(date)}">{html.escape(date)}</time>'
        f'<span><a href="daily/{date}/zh.html">中文</a>'
        f'<a href="daily/{date}/en.html">English</a></span></li>'
        for date in sorted(set(dates), reverse=True)
    )
    return _document(
        language="zh",
        title="Horizon Daily",
        header='<header class="site-header"><p class="brand">Horizon Daily</p>'
        '<h1>每日 AI 情报</h1></header>',
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
```

Private helpers must apply `html.escape(..., quote=True)` to every title, block, source label and attribute. `_safe_href` must accept only absolute `http`/`https` URLs with a hostname and return `None` for control characters, embedded credentials, invalid ports or other schemes. `_render_item` must use a two-column grid, two-digit global index, exactly the first two lead sentences as scan text, and put the complete lead, every artifact block and safe reference link inside native `<details>`.

- [ ] **Step 4: Add the exact layout invariants to `DAILY_CSS`**

The stylesheet must contain these declarations, with no gradients or card backgrounds:

```css
:root { color-scheme: light; --ink: #18231d; --muted: #617068; --line: #d8dfda; --accent: #176b45; --paper: #ffffff; }
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
body { margin: 0; font-size: 16px; line-height: 1.65; letter-spacing: 0; }
a { color: var(--accent); text-underline-offset: 0.18em; overflow-wrap: anywhere; }
.page-shell { width: 100%; max-width: 680px; margin-inline: auto; padding-inline: 18px; }
.site-header { padding-block: 28px 20px; border-bottom: 1px solid var(--line); }
.brand { margin: 0; color: var(--accent); font-size: 0.875rem; font-weight: 700; }
.site-header h1 { margin: 6px 0 0; font-size: 1.75rem; line-height: 1.25; }
.daily-item { display: grid; grid-template-columns: 2.25rem minmax(0, 1fr); gap: 14px; padding-block: 22px; border-bottom: 1px solid var(--line); }
.daily-number { color: var(--accent); font-variant-numeric: tabular-nums; font-weight: 700; }
.daily-content { min-width: 0; }
.daily-content h2 { margin: 0; font-size: 1.125rem; line-height: 1.4; overflow-wrap: anywhere; }
.scan-summary { margin: 10px 0 0; color: var(--muted); }
details { margin-top: 12px; }
summary { display: flex; align-items: center; min-height: 44px; color: var(--accent); cursor: pointer; font-weight: 650; }
.details-body { padding-bottom: 4px; overflow-wrap: anywhere; }
.language-switch { display: flex; gap: 14px; align-items: center; min-height: 44px; }
.daily-index ol { margin: 0; padding: 0; list-style: none; }
.daily-index li { display: flex; justify-content: space-between; gap: 18px; padding-block: 16px; border-bottom: 1px solid var(--line); }
.daily-index li span { display: flex; gap: 14px; }
@media (max-width: 360px) { .daily-item { grid-template-columns: 1.8rem minmax(0, 1fr); gap: 10px; } }
```

`_document(language, title, header, body, stylesheet_href)` must use the provided safe relative stylesheet path. It must include UTF-8, viewport metadata, escaped title, and `lang="zh-CN"` or `lang="en"`.

- [ ] **Step 5: Run renderer tests**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_daily_pages.py tests/test_summarizer.py`

Expected: PASS.

- [ ] **Step 6: Commit the renderer**

```powershell
git add -- src/services/daily_pages.py tests/test_daily_pages.py
git diff --cached --name-status
git commit -m "feat: render mobile daily pages"
```

### Task 3: GitHub Pages REST Publisher

**Files:**
- Create: `src/services/github_pages.py`
- Create: `tests/test_github_pages.py`

**Interfaces:**
- Consumes: `GitHubPagesConfig` and `DailyPageBundle`.
- Produces: `PagePublishResult(success, urls, error_type, detail)`, `PagesPermissionError`, `GitHubPagesPublisher.publish(bundle)`, and `publish_health_check()`.
- Network seam: constructor accepts `request=safe_request` and `sleep=asyncio.sleep` so tests never use DNS or real GitHub.

- [ ] **Step 1: Write failing API-order and SHA tests**

```python
import asyncio
import base64
import httpx
import pytest

from src.models import GitHubPagesConfig
from src.services.daily_pages import DailyPageBundle
from src.services.github_pages import GitHubPagesPublisher, PagesPermissionError


class ScriptedRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, client, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.request = httpx.Request(method, url)
        return response


class FakeClock:
    def __init__(self, values):
        self.values = list(values)
        self.last = self.values[-1]

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


async def _completed_sleep(seconds):
    assert seconds >= 0


def _publisher(request, *, monotonic=None):
    return GitHubPagesPublisher(
        GitHubPagesConfig(enabled=True),
        token="github-secret",
        request=request,
        sleep=_completed_sleep,
        monotonic=monotonic or FakeClock([0]),
        client=object(),
    )


def test_publish_uses_sha_and_updates_index_last():
    request = ScriptedRequest([
        httpx.Response(200, json={"ref": "refs/heads/gh-pages"}),
        httpx.Response(200, json={"sha": "old-css"}),
        httpx.Response(200, json={"content": {"sha": "new-css"}}),
        httpx.Response(200, json={"sha": "old-zh"}),
        httpx.Response(200, json={"content": {"sha": "new-zh"}}),
        httpx.Response(404),
        httpx.Response(201, json={"content": {"sha": "new-en"}}),
        httpx.Response(200, json=[{"name": "2026-08-01"}, {"name": "2026-08-02"}]),
        httpx.Response(404),
        httpx.Response(201, json={"content": {"sha": "new-index"}}),
        httpx.Response(200, json={"html_url": "https://xun-2.github.io/Horizon"}),
        httpx.Response(200, text='<html data-horizon-date="2026-08-02" data-language="zh"></html>'),
        httpx.Response(200, text='<html data-horizon-date="2026-08-02" data-language="en"></html>'),
    ])
    publisher = GitHubPagesPublisher(
        GitHubPagesConfig(enabled=True),
        token="github-secret",
        request=request,
        sleep=_completed_sleep,
        client=object(),
    )
    bundle = DailyPageBundle(
        date="2026-08-02",
        files={
            "daily/2026-08-02/zh.html": "zh",
            "daily/2026-08-02/en.html": "en",
        },
        urls={
            "zh": "https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html",
            "en": "https://xun-2.github.io/Horizon/daily/2026-08-02/en.html",
        },
    )
    result = asyncio.run(publisher.publish(bundle))
    assert result.success is True
    put_calls = [call for call in request.calls if call[0] == "PUT"]
    assert put_calls[-1][1].endswith("/contents/index.html")
    first_payload = put_calls[0][2]["json"]
    assert first_payload["sha"] == "old-css"
    assert base64.b64decode(first_payload["content"]).decode("utf-8")


def test_missing_branch_is_created_from_remote_main_sha():
    request = ScriptedRequest([
        httpx.Response(404),
        httpx.Response(200, json={"object": {"sha": "main-sha"}}),
        httpx.Response(201, json={"ref": "refs/heads/gh-pages"}),
    ])
    asyncio.run(_publisher(request)._ensure_branch())
    create_call = request.calls[-1]
    assert create_call[0] == "POST"
    assert create_call[2]["json"] == {
        "ref": "refs/heads/gh-pages",
        "sha": "main-sha",
    }


def test_sha_conflict_refetches_before_retry():
    request = ScriptedRequest([
        httpx.Response(200, json={"sha": "stale-sha"}),
        httpx.Response(409, json={"message": "conflict"}),
        httpx.Response(200, json={"sha": "fresh-sha"}),
        httpx.Response(200, json={"content": {"sha": "written"}}),
    ])
    asyncio.run(_publisher(request)._put_file("daily/2026-08-02/zh.html", "zh"))
    put_calls = [call for call in request.calls if call[0] == "PUT"]
    assert [call[2]["json"]["sha"] for call in put_calls] == [
        "stale-sha",
        "fresh-sha",
    ]


def test_pages_403_is_sanitized_and_actionable():
    request = ScriptedRequest([
        httpx.Response(403, json={"message": "denied github-secret"}),
    ])
    with pytest.raises(PagesPermissionError) as caught:
        asyncio.run(_publisher(request)._ensure_pages_enabled())
    detail = str(caught.value)
    assert "Settings -> Pages" in detail
    assert "gh-pages / root" in detail
    assert "github-secret" not in detail


def test_public_url_timeout_is_bounded():
    request = ScriptedRequest([
        httpx.Response(404),
        httpx.Response(404),
    ])
    publisher = _publisher(request, monotonic=FakeClock([0, 0, 121]))
    with pytest.raises(TimeoutError):
        asyncio.run(
            publisher._wait_public_url(
                "https://xun-2.github.io/Horizon/health/setup-check.html",
                {'data-horizon-health="ok"'},
            )
        )


async def _unexpected_request(client, method, url, **kwargs):
    raise AssertionError(f"unexpected network request: {method} {url}")


class ControlledPublisher(GitHubPagesPublisher):
    def __init__(self, fail_path=None):
        super().__init__(
            GitHubPagesConfig(enabled=True),
            token="github-secret",
            request=_unexpected_request,
            sleep=_completed_sleep,
            monotonic=FakeClock([0]),
            client=object(),
        )
        self.fail_path = fail_path
        self.uploaded = []

    async def _ensure_branch(self):
        return None

    async def _put_file(self, path, content):
        if path == self.fail_path:
            raise RuntimeError("controlled upload failure")
        self.uploaded.append(path)

    async def _list_dates(self):
        return ["2026-08-02"]

    async def _ensure_pages_enabled(self):
        return None

    async def _wait_public_url(self, url, required_markers):
        return None


def _bundle():
    return DailyPageBundle(
        date="2026-08-02",
        files={
            "daily/2026-08-02/zh.html": "zh",
            "daily/2026-08-02/en.html": "en",
        },
        urls={
            "zh": "https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html",
            "en": "https://xun-2.github.io/Horizon/daily/2026-08-02/en.html",
        },
    )


def test_language_write_failure_skips_index():
    publisher = ControlledPublisher(fail_path="daily/2026-08-02/en.html")
    result = asyncio.run(publisher.publish(_bundle()))
    assert result.success is False
    assert "index.html" not in publisher.uploaded


def test_health_check_does_not_touch_index():
    publisher = ControlledPublisher()
    url = asyncio.run(publisher.publish_health_check())
    assert url.endswith("/health/setup-check.html")
    assert publisher.uploaded == ["health/setup-check.html"]
```

- [ ] **Step 2: Run tests and verify the publisher module is missing**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_github_pages.py`

Expected: FAIL with `ModuleNotFoundError: src.services.github_pages`.

- [ ] **Step 3: Implement the result type and request boundary**

```python
import time


class PagesPermissionError(RuntimeError):
    """Raised when GitHub Pages cannot be enabled with the configured PAT."""


@dataclass(frozen=True)
class PagePublishResult:
    success: bool
    urls: Mapping[str, str]
    error_type: str | None = None
    detail: str | None = None


RequestCallable = Callable[..., Awaitable[httpx.Response]]
SleepCallable = Callable[[float], Awaitable[None]]


class GitHubPagesPublisher:
    API_ROOT = "https://api.github.com"

    def __init__(
        self,
        config: GitHubPagesConfig,
        token: str,
        *,
        request: RequestCallable = safe_request,
        sleep: SleepCallable = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        client: httpx.AsyncClient | None = None,
    ):
        if not token:
            raise ValueError(f"Missing environment variable: {config.token_env}")
        self.config = config
        self._token = token
        self._request = request
        self._sleep = sleep
        self._monotonic = monotonic
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Horizon-Daily-Publisher",
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
```

All exception and response detail paths must call a private `_redact` that replaces both the token and `Authorization` value. Never include response headers in the result.

- [ ] **Step 4: Implement branch creation, Contents updates and Pages enablement**

Use these exact endpoints and behavior:

```text
GET  /repos/Xun-2/Horizon/git/ref/heads/gh-pages
GET  /repos/Xun-2/Horizon/git/ref/heads/main          # only when gh-pages is 404
POST /repos/Xun-2/Horizon/git/refs                    # refs/heads/gh-pages from main SHA
GET  /repos/Xun-2/Horizon/contents/{path}?ref=gh-pages
PUT  /repos/Xun-2/Horizon/contents/{path}             # message, base64 content, branch, optional sha
GET  /repos/Xun-2/Horizon/contents/daily?ref=gh-pages # build date index
GET  /repos/Xun-2/Horizon/pages
POST /repos/Xun-2/Horizon/pages                       # {"source":{"branch":"gh-pages","path":"/"}}
```

`_put_file(path, content)` must GET the current file first, include its SHA when present, and retry at most two times on `409` or `422` after refetching the SHA. Upload order inside `publish` must be:

1. `assets/horizon-daily.css`
2. `daily/YYYY-MM-DD/zh.html`
3. `daily/YYYY-MM-DD/en.html`
4. list `daily/` and render `index.html`
5. `index.html`
6. ensure Pages is enabled
7. poll both public language URLs for HTTP 200 and exact `data-horizon-date`/`data-language` markers

Do not send the index PUT if either language page failed. A Pages API `403` after successful content upload must return `success=False`, `error_type="pages_not_enabled"`, and the Chinese instruction `请在仓库 Settings -> Pages 中选择 gh-pages / root`.

Implement the health probe as a separate idempotent method so it cannot alter the daily index:

```python
async def publish_health_check(self) -> str:
    await self._ensure_branch()
    content = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Horizon delivery check</title></head>'
        '<body data-horizon-health="ok"><main><h1>Horizon delivery check</h1>'
        '<p>GitHub Pages 发布链路正常。</p></main></body></html>'
    )
    await self._put_file("health/setup-check.html", content)
    await self._ensure_pages_enabled()
    url = f"{self.config.site_url}/health/setup-check.html"
    await self._wait_public_url(url, {'data-horizon-health="ok"'})
    return url
```

`_wait_public_url` accepts a URL and a set of required literal markers, and uses the configured deadline/poll interval. The health method must never list `daily/` or write `index.html`.

- [ ] **Step 5: Run the publisher tests**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_github_pages.py tests/test_url_security.py`

Expected: PASS.

- [ ] **Step 6: Commit the publisher**

```powershell
git add -- src/services/github_pages.py tests/test_github_pages.py
git diff --cached --name-status
git commit -m "feat: publish daily pages through GitHub API"
```

### Task 4: PushPlus ClawBot Open API Client

**Files:**
- Create: `src/services/pushplus.py`
- Create: `tests/test_pushplus_open_api.py`

**Interfaces:**
- Produces: `PushPlusDeliveryState`, `PushPlusDeliveryReport`, `PushPlusClawBotClient.send_and_wait(title, content)` and `check_binding()`.
- Consumes: PushPlus endpoint, user Token, `secretKey`, timeout and polling interval.
- Task 5 maps `PushPlusDeliveryReport` to the existing generic `WebhookDeliveryResult`.

- [ ] **Step 1: Write failing end-state tests with a scripted request**

```python
import asyncio
import httpx
import pytest

from src.services.pushplus import PushPlusClawBotClient, PushPlusDeliveryState


class ScriptedRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, client, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.request = httpx.Request(method, url)
        return response


class FakeClock:
    def __init__(self, values):
        self.values = list(values)
        self.last = self.values[-1]

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


async def _completed_sleep(seconds):
    assert seconds >= 0


def test_clawbot_sends_fixed_plain_text_and_waits_for_status_two():
    request = ScriptedRequest([
        httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak", "expiresIn": 7200}}),
        httpx.Response(200, json={"code": 200, "data": {"haveContextToken": 1}}),
        httpx.Response(200, json={"code": 200, "data": "receipt-1"}),
        httpx.Response(200, json={"code": 200, "data": {"status": 1, "errorMessage": ""}}),
        httpx.Response(200, json={"code": 200, "data": {"status": 2, "errorMessage": ""}}),
    ])
    client = PushPlusClawBotClient(
        endpoint="https://www.pushplus.plus/send",
        user_token="user-token",
        secret_key="secret-key",
        request=request,
        sleep=_completed_sleep,
        monotonic=FakeClock([0, 0, 1, 2]),
        client=object(),
    )
    result = asyncio.run(client.send_and_wait("标题", "纯文本内容"))
    send_call = next(call for call in request.calls if call[1].endswith("/send"))
    assert send_call[2]["json"] == {
        "token": "user-token",
        "channel": "clawbot",
        "title": "标题",
        "content": "纯文本内容",
        "template": "txt",
    }
    assert result.state == PushPlusDeliveryState.DELIVERED
    assert result.short_code == "receipt-1"


def _client(responses, clock=None):
    return PushPlusClawBotClient(
        endpoint="https://www.pushplus.plus/send",
        user_token="user-token",
        secret_key="secret-key",
        request=ScriptedRequest(responses),
        sleep=_completed_sleep,
        monotonic=clock or FakeClock([0]),
        client=object(),
    )


def test_inactive_context_prevents_send():
    client = _client([
        httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak", "expiresIn": 7200}}),
        httpx.Response(200, json={"code": 200, "data": {"haveContextToken": 0}}),
    ])
    result = asyncio.run(client.send_and_wait("title", "content"))
    assert result.state == PushPlusDeliveryState.INACTIVE
    assert not any(call[1].endswith("/send") for call in client._request.calls)


@pytest.mark.parametrize(
    "send_payload",
    [
        {"code": 500, "msg": "rejected user-token secret-key"},
        {"code": 200, "msg": "accepted", "data": ""},
    ],
)
def test_send_rejection_or_missing_receipt_is_api_failure(send_payload):
    client = _client([
        httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak", "expiresIn": 7200}}),
        httpx.Response(200, json={"code": 200, "data": {"haveContextToken": "1"}}),
        httpx.Response(200, json=send_payload),
    ])
    result = asyncio.run(client.send_and_wait("title", "content"))
    assert result.state == PushPlusDeliveryState.API_FAILURE
    assert "user-token" not in (result.detail or "")
    assert "secret-key" not in (result.detail or "")


def test_status_three_is_failed_and_sanitized():
    client = _client([
        httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak", "expiresIn": 7200}}),
        httpx.Response(200, json={"code": 200, "data": {"haveContextToken": 1}}),
        httpx.Response(200, json={"code": 200, "data": "receipt-3"}),
        httpx.Response(200, json={"code": 200, "data": {"status": 3, "errorMessage": "quota secret-key ak"}}),
    ])
    result = asyncio.run(client.send_and_wait("title", "content"))
    assert result.state == PushPlusDeliveryState.FAILED
    assert result.short_code == "receipt-3"
    assert "secret-key" not in (result.detail or "")
    assert "ak" not in (result.detail or "")


def test_pending_status_times_out_without_success():
    client = _client(
        [
            httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak", "expiresIn": 7200}}),
            httpx.Response(200, json={"code": 200, "data": {"haveContextToken": 1}}),
            httpx.Response(200, json={"code": 200, "data": "receipt-timeout"}),
            httpx.Response(200, json={"code": 200, "data": {"status": 0, "errorMessage": ""}}),
            httpx.Response(200, json={"code": 200, "data": {"status": 1, "errorMessage": ""}}),
        ],
        clock=FakeClock([0, 0, 0, 91]),
    )
    result = asyncio.run(client.send_and_wait("title", "content"))
    assert result.state == PushPlusDeliveryState.TIMED_OUT
    assert result.delivered is False


def test_expiring_access_key_is_refreshed_and_secrets_stay_out_of_repr():
    client = _client([
        httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak-1", "expiresIn": 7200}}),
        httpx.Response(200, json={"code": 200, "data": {"haveContextToken": 1}}),
        httpx.Response(200, json={"code": 200, "data": {"accessKey": "ak-2", "expiresIn": 7200}}),
        httpx.Response(200, json={"code": 200, "data": {"haveContextToken": 1}}),
    ])
    assert asyncio.run(client.check_binding()) is True
    client._access_key_expires_at = 0
    assert asyncio.run(client.check_binding()) is True
    access_calls = [call for call in client._request.calls if call[1].endswith("/getAccessKey")]
    assert len(access_calls) == 2
    assert "user-token" not in repr(client)
    assert "secret-key" not in repr(client)
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_pushplus_open_api.py`

Expected: FAIL with `ModuleNotFoundError: src.services.pushplus`.

- [ ] **Step 3: Implement the explicit delivery states and report**

```python
class PushPlusProtocolError(RuntimeError):
    """Raised when PushPlus returns an invalid or unsuccessful API payload."""


class PushPlusDeliveryState(str, Enum):
    INACTIVE = "inactive"
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    API_FAILURE = "api_failure"


@dataclass(frozen=True)
class PushPlusDeliveryReport:
    state: PushPlusDeliveryState
    short_code: str | None = None
    detail: str | None = None

    @property
    def delivered(self) -> bool:
        return self.state == PushPlusDeliveryState.DELIVERED
```

The client constructor must store all secrets in private attributes, exclude them from repr, and accept `request`, `sleep`, and `monotonic` injection points.

- [ ] **Step 4: Implement AccessKey, binding and final-status calls**

Use this exact request and terminal-state structure:

```python
class PushPlusClawBotClient:
    OPEN_API_ROOT = "https://www.pushplus.plus"

    def __init__(
        self,
        endpoint: str,
        user_token: str,
        secret_key: str,
        *,
        status_timeout_seconds: int = 90,
        poll_interval_seconds: float = 2.0,
        request=safe_request,
        sleep=asyncio.sleep,
        monotonic=time.monotonic,
        client: httpx.AsyncClient | None = None,
    ):
        self._endpoint = validate_http_url(endpoint)
        self._user_token = user_token
        self._secret_key = secret_key
        self._status_timeout_seconds = status_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._request = request
        self._sleep = sleep
        self._monotonic = monotonic
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._access_key: str | None = None
        self._access_key_expires_at = 0.0

    def __repr__(self) -> str:
        return f"PushPlusClawBotClient(endpoint={self._endpoint!r})"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _redact(self, value: str) -> str:
        redacted = value
        secrets = [self._user_token, self._secret_key, self._access_key or ""]
        for secret in sorted((item for item in secrets if item), key=len, reverse=True):
            redacted = redacted.replace(secret, "<redacted>")
        return redacted

    def _payload(self, response: httpx.Response) -> dict:
        if not 200 <= response.status_code < 300:
            raise PushPlusProtocolError(f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise PushPlusProtocolError("PushPlus response is not JSON") from exc
        if not isinstance(payload, dict) or payload.get("code") != 200:
            message = payload.get("msg") if isinstance(payload, dict) else "invalid payload"
            raise PushPlusProtocolError(self._redact(str(message)))
        return payload

    async def _get_access_key(self) -> str:
        response = await self._request(
            self._client,
            "POST",
            f"{self.OPEN_API_ROOT}/api/common/openApi/getAccessKey",
            json={"token": self._user_token, "secretKey": self._secret_key},
        )
        payload = self._payload(response)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("accessKey"), str):
            raise PushPlusProtocolError("AccessKey response is invalid")
        expires_in = int(data.get("expiresIn", 0))
        self._access_key = data["accessKey"]
        self._access_key_expires_at = self._monotonic() + expires_in
        return self._access_key

    async def _open_api_get(self, path: str, **kwargs) -> dict:
        if (
            self._access_key is None
            or self._access_key_expires_at - self._monotonic() <= 300
        ):
            await self._get_access_key()
        response = await self._request(
            self._client,
            "GET",
            f"{self.OPEN_API_ROOT}{path}",
            headers={"access-key": self._access_key},
            **kwargs,
        )
        return self._payload(response)

    async def check_binding(self) -> bool:
        payload = await self._open_api_get("/api/open/clawBot/botInfo")
        data = payload.get("data")
        return isinstance(data, dict) and data.get("haveContextToken") in {1, "1"}

    async def _delivery_status(self, short_code: str) -> tuple[int, str]:
        payload = await self._open_api_get(
            "/api/open/message/sendMessageResult",
            params={"shortCode": short_code},
        )
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("status") not in {0, 1, 2, 3}:
            raise PushPlusProtocolError("Delivery status response is invalid")
        return int(data["status"]), str(data.get("errorMessage") or "")

    async def send_and_wait(self, title: str, content: str) -> PushPlusDeliveryReport:
        short_code: str | None = None
        try:
            if not await self.check_binding():
                return PushPlusDeliveryReport(
                    PushPlusDeliveryState.INACTIVE,
                    detail="ClawBot has no active conversation token",
                )
            response = await self._request(
                self._client,
                "POST",
                self._endpoint,
                json={
                    "token": self._user_token,
                    "channel": "clawbot",
                    "title": title,
                    "content": content,
                    "template": "txt",
                },
            )
            payload = self._payload(response)
            receipt = payload.get("data")
            if not isinstance(receipt, str) or not receipt.strip():
                raise PushPlusProtocolError("PushPlus response has no message receipt")
            short_code = receipt.strip()
            deadline = self._monotonic() + self._status_timeout_seconds
            while True:
                status, error_message = await self._delivery_status(short_code)
                if status == 2:
                    return PushPlusDeliveryReport(
                        PushPlusDeliveryState.DELIVERED,
                        short_code=short_code,
                    )
                if status == 3:
                    return PushPlusDeliveryReport(
                        PushPlusDeliveryState.FAILED,
                        short_code=short_code,
                        detail=self._redact(error_message or "PushPlus reported failure"),
                    )
                if self._monotonic() >= deadline:
                    return PushPlusDeliveryReport(
                        PushPlusDeliveryState.TIMED_OUT,
                        short_code=short_code,
                        detail="Timed out waiting for final ClawBot delivery",
                    )
                await self._sleep(self._poll_interval_seconds)
        except Exception as exc:
            return PushPlusDeliveryReport(
                PushPlusDeliveryState.API_FAILURE,
                short_code=short_code,
                detail=self._redact(f"{type(exc).__name__}: {exc}"),
            )
```

The notifier must close its owned PushPlus client at process shutdown or use an async context boundary; tests must call `aclose()` when they create a real `httpx.AsyncClient`. No code path may substitute `wechat`.

- [ ] **Step 5: Run PushPlus Open API tests**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_pushplus_open_api.py tests/test_url_security.py`

Expected: PASS.

- [ ] **Step 6: Commit the PushPlus client**

```powershell
git add -- src/services/pushplus.py tests/test_pushplus_open_api.py
git diff --cached --name-status
git commit -m "feat: verify ClawBot final delivery"
```

### Task 5: Plain-Text Digest and Webhook Delegation

**Files:**
- Modify: `src/ai/summarizer.py:116-453`
- Modify: `src/services/webhook.py:24-948`
- Modify: `tests/test_summarizer.py`
- Modify: `tests/test_pushplus.py`

**Interfaces:**
- Produces: `DailySummarizer.generate_clawbot_digest(items, date, language, page_url)`.
- Changes: `WebhookNotifier.send_daily_summary(..., page_url: str | None = None) -> list[WebhookDeliveryResult]`.
- Consumes: injected `PushPlusClawBotClient`; generic webhook platforms keep their existing behavior.

- [ ] **Step 1: Write failing digest and delegation tests**

```python
def test_clawbot_digest_is_plain_text_with_three_items_and_page_link():
    items = [_make_friend_item(index) for index in range(1, 6)]
    text = DailySummarizer().generate_clawbot_digest(
        items,
        "2026-08-02",
        language="zh",
        page_url="https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html",
    )
    assert text.count("\n1. ") == 1
    assert "\n2. " in text and "\n3. " in text
    assert "\n4. " not in text
    assert "https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html" in text
    assert all(marker not in text for marker in ("# ", "**", "[", "]("))


def test_clawbot_digest_without_page_reports_publish_failure():
    text = DailySummarizer().generate_clawbot_digest(
        [_make_friend_item(1)], "2026-08-02", language="zh", page_url=None
    )
    assert "完整日报暂未发布" in text
    assert "http" not in text
```

Add these imports and tests to `tests/test_pushplus.py`:

```python
import asyncio

from src.models import PushPlusClawBotConfig
from src.services.pushplus import (
    PushPlusDeliveryReport,
    PushPlusDeliveryState,
)


class FakeClawBotClient:
    def __init__(self, state):
        self.state = state
        self.calls = []

    async def send_and_wait(self, title, content):
        self.calls.append((title, content))
        return PushPlusDeliveryReport(state=self.state, short_code="receipt")


@pytest.mark.parametrize(
    ("provider_state", "webhook_state"),
    [
        (PushPlusDeliveryState.DELIVERED, WebhookDeliveryStatus.SUCCESS),
        (PushPlusDeliveryState.INACTIVE, WebhookDeliveryStatus.CHANNEL_INACTIVE),
        (PushPlusDeliveryState.FAILED, WebhookDeliveryStatus.DELIVERY_FAILED),
        (PushPlusDeliveryState.TIMED_OUT, WebhookDeliveryStatus.DELIVERY_TIMEOUT),
    ],
)
def test_clawbot_final_state_controls_webhook_success(
    provider_state, webhook_state, monkeypatch
):
    monkeypatch.setenv(TEST_URL_ENV, TEST_URL)
    fake = FakeClawBotClient(provider_state)
    notifier = WebhookNotifier(
        WebhookConfig(
            enabled=True,
            url_env=TEST_URL_ENV,
            delivery="overview",
            platform="pushplus",
            pushplus=PushPlusClawBotConfig(),
        ),
        pushplus_client=fake,
    )
    summarizer = MagicMock()
    summarizer.generate_clawbot_digest.return_value = "plain digest"
    results = asyncio.run(
        notifier.send_daily_summary(
            summary="markdown summary",
            important_items=[],
            all_items_count=0,
            date="2026-08-02",
            lang="zh",
            summarizer=summarizer,
            page_url="https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html",
        )
    )
    assert results[0].status == webhook_state
    assert results[0].sent is (provider_state == PushPlusDeliveryState.DELIVERED)
    assert fake.calls == [("今天这几条 AI 动态值得看", "plain digest")]
```

- [ ] **Step 2: Run focused tests and verify the new method/signature fail**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_summarizer.py tests/test_pushplus.py`

Expected: FAIL because `generate_clawbot_digest` and `page_url` are not implemented.

- [ ] **Step 3: Implement the deterministic plain-text digest**

```python
def generate_clawbot_digest(
    self,
    items: List[ContentItem],
    date: str,
    language: str,
    page_url: str | None,
) -> str:
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
        conclusion = sentences[0] if sentences else ""
        line = f"{index}. {re.sub(r'\s+', ' ', title).strip()}"
        if conclusion:
            line += f" - {re.sub(r'\s+', ' ', conclusion).strip()}"
        lines.append(line)
    if not selected:
        lines.append(
            "今天暂无达到阈值的动态。"
            if language == "zh"
            else "No updates met today's threshold."
        )
    lines.append(f"{link_label}: {page_url}" if page_url else unavailable)
    return "\n".join(lines)
```

Strip all CR/LF from item-derived titles/conclusions before joining, reject a non-HTTP(S) `page_url`, and do not call Markdown escaping because the output is literal plain text.

- [ ] **Step 4: Delegate configured PushPlus delivery and preserve generic platforms**

Extend `WebhookDeliveryStatus` with `DELIVERY_FAILED`, `DELIVERY_TIMEOUT`, and `CHANNEL_INACTIVE`. Add optional `pushplus_client` injection to `WebhookNotifier.__init__`. When `config.platform == "pushplus"` and `config.pushplus` exists, construct the client from the configured environment variable names and the validated endpoint; do not render `request_body` for this branch.

Add `page_url` to `build_daily_summary_messages` and `send_daily_summary`. For the ClawBot overview branch call `generate_clawbot_digest`; for all other branches keep existing methods. `send_daily_summary` must return every result instead of discarding it.

Map results exactly:

```python
PUSHPLUS_STATUS_MAP = {
    PushPlusDeliveryState.DELIVERED: WebhookDeliveryStatus.SUCCESS,
    PushPlusDeliveryState.INACTIVE: WebhookDeliveryStatus.CHANNEL_INACTIVE,
    PushPlusDeliveryState.FAILED: WebhookDeliveryStatus.DELIVERY_FAILED,
    PushPlusDeliveryState.TIMED_OUT: WebhookDeliveryStatus.DELIVERY_TIMEOUT,
    PushPlusDeliveryState.API_FAILURE: WebhookDeliveryStatus.PLATFORM_FAILURE,
}
```

`WebhookDeliveryResult.sent` remains true only for `SUCCESS`. Console output must say `ClawBot 已送达` only for `SUCCESS`; accepted receipts and pending states must not use success wording.

- [ ] **Step 5: Run notifier and summarizer regressions**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_pushplus.py tests/test_summarizer.py tests/test_webhook.py tests/test_webhook_cli.py`

Expected: PASS.

- [ ] **Step 6: Commit the notifier integration**

```powershell
git add -- src/ai/summarizer.py src/services/webhook.py tests/test_summarizer.py tests/test_pushplus.py
git diff --cached --name-status
git commit -m "feat: send linked ClawBot text digests"
```

### Task 6: Orchestrate Pages Before ClawBot

**Files:**
- Modify: `src/orchestrator.py:206-441`
- Create: `tests/test_delivery_pipeline.py`

**Interfaces:**
- Consumes: `GitHubPagesPublisher`, `build_daily_page_bundle`, and `WebhookNotifier.send_daily_summary(..., page_url=...)`.
- Produces: `_deliver_daily(important_items, total_fetched, date)` with one publication attempt and one final ClawBot delivery attempt per configured language.
- Failure contract: local Markdown always remains saved; Pages failure yields `page_url=None`; ClawBot failure never removes a published page.

- [ ] **Step 1: Write failing pipeline-order tests**

Test the delivery boundary directly with self-contained fakes:

```python
import asyncio
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
    orchestrator.console = SimpleNamespace(print=lambda message: events.append("warning"))
    return orchestrator


def test_pipeline_publishes_both_languages_before_notifying():
    events = []
    orchestrator = _orchestrator(events, publish_success=True)
    asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-02"))
    assert events.index("publish:zh,en") < events.index("notify:zh:https://xun-2.github.io/Horizon/daily/2026-08-02/zh.html")
    assert events.index("publish:zh,en") < events.index("notify:en:https://xun-2.github.io/Horizon/daily/2026-08-02/en.html")


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
    orchestrator._determine_time_window = lambda force_hours=None: object()

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
```

These tests do not construct network clients, patch `git`, send PushPlus, or write outside the fake storage.

- [ ] **Step 2: Run the integration test and verify the current per-language order fails**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_delivery_pipeline.py`

Expected: FAIL because `_deliver_daily` does not exist.

- [ ] **Step 3: Refactor the run sequence without changing collection/AI behavior**

Add optional constructor injection:

```python
def __init__(
    self,
    config: Config,
    storage: StorageManager,
    console: Optional[Console] = None,
    profiles: Optional[ProfileRegistry] = None,
    page_publisher: Optional[GitHubPagesPublisher] = None,
):
```

When `config.github_pages.enabled`, construct the default publisher with `os.environ[config.github_pages.token_env]`. Extract this exact method and call it from `run` immediately after enrichment:

```python
async def _deliver_daily(
    self,
    important_items: List[ContentItem],
    total_fetched: int,
    date: str,
) -> None:
    summaries: Dict[str, str] = {}
    summarizer = DailySummarizer(profile_names=self.profiles.names)
    for lang in self.config.ai.languages:
        summary = await summarizer.generate_summary(
            important_items, date, total_fetched, language=lang
        )
        summaries[lang] = summary
        self.storage.save_daily_summary(date, summary, language=lang)

    page_urls: Dict[str, str] = {}
    if self.page_publisher:
        bundle = build_daily_page_bundle(
            important_items,
            date,
            total_fetched,
            self.config.ai.languages,
            summarizer,
            self.config.github_pages.site_url,
        )
        publication = await self.page_publisher.publish(bundle)
        if publication.success:
            page_urls.update(publication.urls)
        else:
            self.console.print(
                f"[yellow]完整日报暂未发布: {publication.error_type}[/yellow]"
            )

    for lang, summary in summaries.items():
        if self.email_manager and self.config.email and self.config.email.enabled:
            subscribers = self.storage.load_subscribers()
            subject = f"Horizon Summary ({lang.upper()}) - {date}"
            self.email_manager.send_daily_summary(summary, subject, subscribers)
        if self.webhook_notifier:
            await self.webhook_notifier.send_daily_summary(
                summary=summary,
                important_items=important_items,
                all_items_count=total_fetched,
                date=date,
                lang=lang,
                summarizer=summarizer,
                page_url=page_urls.get(lang),
            )
```

In `run`, replace the old summary/copy/email/webhook loop with `await self._deliver_daily(important_items, len(all_items), today)`. Move `today` calculation before the current `if not all_items` branch. When no items were fetched but `last_fetch_report.all_failed` is false, call `await self._deliver_daily([], 0, today)`, print the normal completion line, and return; only the existing all-sources-failed branch raises. Do not delete `data/summaries/*.md`. Remove only the obsolete runtime block that writes ignored `docs/_posts/*.md`; do not delete any existing user post.

- [ ] **Step 4: Run pipeline and existing orchestrator tests**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_delivery_pipeline.py tests/test_main.py tests/test_fetch_reporting.py tests/test_balanced_digest.py`

Expected: PASS.

- [ ] **Step 5: Commit the pipeline wiring**

```powershell
git add -- src/orchestrator.py tests/test_delivery_pipeline.py
git diff --cached --name-status
git commit -m "feat: publish pages before ClawBot delivery"
```

### Task 7: Chinese Setup, Secret Migration, and Delivery Probes

**Files:**
- Modify: `.env.example`
- Modify: `scripts/setup_local_secrets.ps1`
- Modify: `scripts/check_local_setup.py`
- Modify: `docs/local-ai-radar-setup.md`
- Modify: `tests/test_local_setup.py`
- Modify: `tests/test_windows_scripts.py`

**Interfaces:**
- Produces: `.env` keys `AOLIGEI_API_KEY`, `PUSHPLUS_TOKEN`, `PUSHPLUS_SECRET_KEY`, `HORIZON_GITHUB_TOKEN`, and fixed `HORIZON_WEBHOOK_URL`.
- Produces CLI modes: `--offline`, `--online`, existing `--test-pushplus`, and new `--test-delivery`.
- `--test-delivery` sequence is Pages health page -> public HTTP 200 -> ClawBot text with link -> final status.

- [ ] **Step 1: Extend failing environment and script tests**

Update `_environment` in `tests/test_local_setup.py` to remove/add all four secret names. Add assertions:

```python
from src.services.pushplus import PushPlusDeliveryReport, PushPlusDeliveryState


def test_missing_delivery_secrets_reports_names_only():
    result = _run("--offline", include_secrets=False)
    output = result.stdout + result.stderr
    assert result.returncode == 1
    for name in (
        "AOLIGEI_API_KEY",
        "PUSHPLUS_TOKEN",
        "PUSHPLUS_SECRET_KEY",
        "HORIZON_GITHUB_TOKEN",
    ):
        assert name in output
    assert "test-pushplus-secret" not in output
    assert "test-github-secret" not in output


def test_delivery_probe_requires_online_mode():
    result = _run("--test-delivery")
    assert result.returncode != 0
    assert "--test-delivery requires --online" in result.stderr


def test_delivery_probe_publishes_before_clawbot_and_requires_final_state(monkeypatch):
    environment = _environment(include_secrets=True)
    config, issues = check_local_setup.check_offline(CONFIG, environment)
    assert not issues
    events = []

    class FakePublisher:
        async def publish_health_check(self):
            events.append("pages")
            return "https://xun-2.github.io/Horizon/health/setup-check.html"

    class FakeClawBot:
        async def send_and_wait(self, title, content):
            events.append(f"clawbot:{content}")
            return PushPlusDeliveryReport(
                state=PushPlusDeliveryState.DELIVERED,
                short_code="receipt",
            )

    monkeypatch.setattr(
        check_local_setup,
        "_build_page_publisher",
        lambda config: FakePublisher(),
    )
    monkeypatch.setattr(
        check_local_setup,
        "_build_clawbot_client",
        lambda config: FakeClawBot(),
    )
    probe_issues = asyncio.run(check_local_setup._check_delivery(config))
    assert probe_issues == []
    assert events[0] == "pages"
    assert events[1].startswith("clawbot:")
    assert "health/setup-check.html" in events[1]
```

Extend the PowerShell test helper queue to provide Aoligei Token, PushPlus user Token, PushPlus secretKey and GitHub PAT. Assert the written `.env` contains all names and none of the secret values appear in stdout/stderr.

- [ ] **Step 2: Run the setup tests and verify missing-key failures**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_local_setup.py tests/test_windows_scripts.py`

Expected: FAIL because the scripts do not know `PUSHPLUS_SECRET_KEY`, `HORIZON_GITHUB_TOKEN`, or `--test-delivery`.

- [ ] **Step 3: Update secure secret collection**

In `scripts/setup_local_secrets.ps1`, call `Read-SecretText` four times and write exactly:

```powershell
$aoligeiKey = Read-SecretText 'Aoligei New API Token (AOLIGEI_API_KEY)'
$pushPlusToken = Read-SecretText 'PushPlus user token (PUSHPLUS_TOKEN)'
$pushPlusSecret = Read-SecretText 'PushPlus Open API secretKey (PUSHPLUS_SECRET_KEY)'
$githubToken = Read-SecretText 'GitHub fine-grained PAT (HORIZON_GITHUB_TOKEN)'
try {
    $lines = @(
        "AOLIGEI_API_KEY=$aoligeiKey"
        "PUSHPLUS_TOKEN=$pushPlusToken"
        "PUSHPLUS_SECRET_KEY=$pushPlusSecret"
        "HORIZON_GITHUB_TOKEN=$githubToken"
        'HORIZON_WEBHOOK_URL=https://www.pushplus.plus/send'
    )
    Set-Content -LiteralPath $envPath -Value $lines -Encoding utf8
}
finally {
    $aoligeiKey = $null
    $pushPlusToken = $null
    $pushPlusSecret = $null
    $githubToken = $null
}
```

Do not accept command-line secret arguments and do not echo any value.

- [ ] **Step 4: Extend offline and online contract checks**

`_required_environment` must include `config.github_pages.token_env` and the two `config.webhook.pushplus` env names. `_contract_issues` must require:

```text
webhook.platform == "pushplus"
webhook.delivery == "overview"
webhook.pushplus.channel == "clawbot"
webhook.pushplus.template == "txt"
github_pages.enabled == true
github_pages.repository == "Xun-2/Horizon"
github_pages.branch == "gh-pages"
github_pages.site_url == "https://xun-2.github.io/Horizon"
```

Add `_build_page_publisher(config)` and `_build_clawbot_client(config)` factory helpers for test injection. `_check_pushplus` performs binding/final-delivery reporting. `_check_delivery` must call `GitHubPagesPublisher.publish_health_check()`, pass its returned public URL to one `PushPlusClawBotClient.send_and_wait(...)` call, and require `PushPlusDeliveryState.DELIVERED`. Every caught exception must go through `_safe_probe_error` so no secret or complete authenticated URL is printed.

Add parser behavior:

```python
parser.add_argument(
    "--test-delivery",
    action="store_true",
    help="Publish a Pages health check and verify final ClawBot delivery; requires --online",
)
```

Both `--test-pushplus` and `--test-delivery` require `--online`. The first tests only binding/send/final status; the second verifies the complete ordered chain.

- [ ] **Step 5: Write Chinese installation instructions**

Update `docs/local-ai-radar-setup.md` with these explicit steps:

1. PushPlus 控制台完成 ClawBot 扫码绑定，主动发送一条消息并确认“已激活”。
2. 在开发设置中启用开放接口、设置至少 32 位随机 `secretKey`、把当前执行机公网 IP 加入安全 IP；用户 Token 与 `secretKey` 分开保存。
3. 细粒度 GitHub PAT 只授权 `Xun-2/Horizon`，至少授予 `Contents: Read and write`；自动启用 Pages 需要 `Pages: Read and write`。
4. 不在聊天、截图或 Git 提交中粘贴任何 Token。
5. 运行 `scripts/setup_local_secrets.ps1`，然后运行离线检查。
6. 运行 `uv run python scripts/check_local_setup.py --online --test-delivery` 完成真实 Pages/ClawBot 验收。
7. 每下发 10 次或每隔 24 小时，主动与 ClawBot 对话一次；Horizon 只检测，不能绕过该限制。
8. Pages 自动启用返回权限错误时，到 `Settings -> Pages` 手动选择 `gh-pages / root` 后重试。

Update `.env.example` with variable names and placeholder descriptions only; do not put syntactically valid-looking production secrets in the example.

- [ ] **Step 6: Run setup and contract tests**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_local_setup.py tests/test_windows_scripts.py tests/test_delivery_config.py`

Expected: PASS.

- [ ] **Step 7: Commit only setup-related paths**

```powershell
git add -- .env.example scripts/setup_local_secrets.ps1 scripts/check_local_setup.py docs/local-ai-radar-setup.md tests/test_local_setup.py tests/test_windows_scripts.py
git diff --cached --name-status
git commit -m "docs: add Chinese ClawBot Pages setup"
```

### Task 8: Automated, Visual, and Security Verification

**Files:**
- Create: `tests/test_daily_pages_visual.py`
- Modify: code/tests from Tasks 1-7 only when a verification failure proves a defect.
- Write runtime artifacts only under: `.superpowers/daily-pages-visual/`

**Interfaces:**
- Consumes: pure renderer and CSS.
- Produces: assertions plus screenshots for `390x844`, `430x932`, and `1440x900` in Chinese, English, empty, and long-content cases.

- [ ] **Step 1: Add the Playwright visual contract**

```python
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
            lead="The model changed materially. The change affects production use. Extra detail stays expanded.",
            blocks=[ContentBlock(id="background", title="Background", content="Context " * 80)],
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
```

The fixture above covers a 200-character title, a 300-character unbroken URL and expanded `<details>`; the second test covers both localized empty states.

- [ ] **Step 2: Install the existing Playwright optional dependency and browser**

```powershell
uv sync --extra dev --extra twitter
uv run playwright install chromium
```

Expected: Chromium installs successfully. This uses the repository's existing `twitter` optional dependency and does not add a second Playwright version.

- [ ] **Step 3: Run focused and full automated tests**

```powershell
$env:PYTHONUTF8 = '1'
uv run python -m pytest -p no:cacheprovider -q tests/test_delivery_config.py tests/test_daily_pages.py tests/test_github_pages.py tests/test_pushplus_open_api.py tests/test_pushplus.py tests/test_delivery_pipeline.py tests/test_local_setup.py tests/test_windows_scripts.py
uv run python -m pytest -p no:cacheprovider -q
```

Expected: both commands exit `0` with no failures.

- [ ] **Step 4: Run visual checks and inspect every screenshot**

Run: `uv run python -m pytest -p no:cacheprovider -q tests/test_daily_pages_visual.py`

Expected: PASS and PNG files under `.superpowers/daily-pages-visual/`. Inspect all screenshots at original resolution; confirm the brand/date/list is visible, next content is hinted below the first viewport, no text overlaps, details controls are tappable, and the page does not become card-heavy or one-color decoration.

- [ ] **Step 5: Run security and repository-boundary checks**

```powershell
git check-ignore -q -- .env
git check-ignore -q -- data/config.json
$leakedNames = Get-ChildItem -LiteralPath logs -Filter '*.log' -File | Select-String -Pattern 'HORIZON_GITHUB_TOKEN=|PUSHPLUS_SECRET_KEY=|PUSHPLUS_TOKEN='
if ($leakedNames) { throw "Sensitive environment variable names found in runtime logs" }
git diff --check
git status --short
```

Expected: ignored-file check exits `0`; logs contain no secret assignments; `git diff --check` exits `0`; `git status` shows only intended feature changes plus the user's pre-existing unrelated changes. The command never reads or prints `.env` contents.

- [ ] **Step 6: Commit the visual test after it passes**

```powershell
git add -- tests/test_daily_pages_visual.py
git diff --cached --name-status
git commit -m "test: verify mobile daily page layout"
```

Do not add `.superpowers/daily-pages-visual/*.png` to Git.

### Task 9: Real GitHub Pages and ClawBot Acceptance

**Files:**
- Local-only modify: `.env`
- Local-only modify: `data/config.json`
- Remote write: `Xun-2/Horizon` branch `gh-pages`
- External send: one PushPlus ClawBot test message, followed by the next scheduled daily messages.

**Interfaces:**
- Consumes: valid local secrets, enabled PushPlus Open API, activated ClawBot, GitHub PAT.
- Produces: public HTTP 200 pages and PushPlus final state `2` for the ClawBot receipt.

- [ ] **Step 1: Revoke the API key previously exposed in chat**

In the Aoligei console, revoke the previously shared key and create a new API Token. Enter it only through `scripts/setup_local_secrets.ps1`; do not paste it into chat or terminal history.

- [ ] **Step 2: Configure PushPlus and GitHub outside the repository**

In PushPlus, verify ClawBot binding, active conversation token, enabled Open API, secretKey and current public IP allowlist. In GitHub, create or rotate a fine-grained PAT limited to `Xun-2/Horizon` with `Contents: Read and write` and `Pages: Read and write`.

- [ ] **Step 3: Populate local secrets and migrate local config**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_local_secrets.ps1
uv run python scripts/check_local_setup.py --offline
```

Before the offline command, read the existing ignored `data/config.json` and apply only the Task 1 `webhook.pushplus` and top-level `github_pages` blocks with `apply_patch`; remove the obsolete PushPlus `request_body` field, but preserve every source, AI, filtering and digest setting. Do not copy over or replace the whole file. Expected: `Offline configuration check passed`; `data/config.json` must not be staged.

- [ ] **Step 4: Run the ordered real delivery probe**

Run: `uv run python scripts/check_local_setup.py --online --test-delivery`

Expected order in sanitized output:

```text
Offline configuration check passed
GitHub Pages test page is public
ClawBot request accepted
ClawBot 已送达
Online checks passed
```

Any `403`, missing AccessKey, `haveContextToken=0`, status `3`, timeout or public URL failure is a failed acceptance. Do not reinterpret `code=200` as final success.

- [ ] **Step 5: Verify public daily pages and phone behavior**

After one real Horizon run, open:

```text
https://xun-2.github.io/Horizon/
https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/zh.html
https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/en.html
```

Confirm HTTP 200, correct date/language markers, mobile layout in the WeChat embedded browser, and one Chinese plus one English ClawBot private message. Each message must be plain text, list at most three items, and open the matching language URL.

- [ ] **Step 6: Verify the installed schedule still owns daily execution**

```powershell
Get-ScheduledTask -TaskName 'HorizonLocalAIRadar' | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName 'HorizonLocalAIRadar' | Select-Object LastRunTime,LastTaskResult,NextRunTime
```

Expected: task state is `Ready`, `LastTaskResult` is `0` after the next run, and the next run remains daily at 07:22 China Standard Time. The runner log must record final ClawBot delivery state without credentials.

- [ ] **Step 7: Final repository verification**

```powershell
git diff --cached --name-status
git status --short
git log -8 --oneline
```

Expected: staging area is empty; feature commits are present; `.env` and `data/config.json` remain ignored; no unrelated user changes were committed or reverted.
