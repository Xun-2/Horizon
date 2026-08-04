# GitHub Actions Cloud Daily Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the daily Horizon run to GitHub Actions while retaining one ClawBot message per successful Beijing business day and using Windows login as a cloud retry trigger.

**Architecture:** GitHub Actions is the primary scheduler and uses its own run history plus a concurrency group as the shared daily success record. Horizon gains explicit PushPlus `accepted` and `delivered` confirmation modes, publishes both language pages before sending one bilingual-links message, and returns a non-zero exit code when required delivery fails. A local recovery client queries or dispatches that same workflow instead of running the AI pipeline locally.

**Tech Stack:** Python 3.11+, Pydantic 2, httpx, pytest, PowerShell ScheduledTasks, GitHub Actions, GitHub REST API, PushPlus `/send` and Open API.

## Global Constraints

- Business dates and schedule decisions use `Asia/Shanghai`; `07:22` Beijing is cron `22 23 * * *` UTC.
- GitHub Actions sends exactly one `channel=clawbot`, `template=txt` message containing a Chinese briefing and both `zh` and `en` Pages URLs.
- Cloud confirmation is `accepted`: HTTP 2xx, PushPlus business code `200`, and a non-empty receipt. It never calls PushPlus Open API.
- Local confirmation remains `delivered` and requires `PUSHPLUS_SECRET_KEY` to verify final status `2`.
- GitHub Actions Secrets are limited to `AOLIGEI_API_KEY` and `PUSHPLUS_TOKEN`; use `${{ github.token }}` for `HORIZON_GITHUB_TOKEN` and a literal `https://www.pushplus.plus/send` URL.
- The local fine-grained PAT requires `Actions: Read and write`, `Contents: Read and write`, and `Pages: Read and write` for `Xun-2/Horizon` only.
- Delivery is at-least-once. A retry after an ambiguous PushPlus response may duplicate one message; never claim strict exactly-once behavior.
- The repository is already dirty. Never use `git add -A`, never stage unrelated paths, and run `git diff --cached --name-only` before every commit.
- Never read, print, stage, or commit `.env`, `data/config.json`, tokens, secretKey, AccessKey, or Aoligei credentials.
- All remote error text must pass existing secret-redaction boundaries before being logged or returned.

## File Map

- `src/models.py`: defines the `accepted`/`delivered` and `bilingual_links` configuration contracts.
- `src/services/pushplus.py`: sends ClawBot messages and optionally verifies final delivery.
- `src/ai/summarizer.py`: renders the single deterministic bilingual-links message.
- `src/services/webhook.py`: builds the PushPlus client and maps one bilingual message to one delivery result.
- `src/orchestrator.py`: publishes both pages, sends once, aggregates required delivery results, and raises on failure.
- `src/services/github_actions.py`: typed GitHub workflow-run query and dispatch client.
- `scripts/github_actions_recovery.py`: cross-platform guard/recovery CLI used by Actions and Windows.
- `scripts/run_cloud_recovery.ps1`: logged, locked Windows wrapper for the recovery CLI.
- `scripts/install_scheduled_task.ps1`: registers login and 07:45 cloud-recovery triggers.
- `data/config.github-actions.json`: Aoligei, bilingual Pages, and PushPlus accepted-mode cloud configuration.
- `.github/workflows/daily-summary.yml`: primary 07:22 cloud schedule, dedup guard, bounded retry, and manual dispatch.
- `tests/test_delivery_config.py`: conditional secret configuration tests.
- `tests/test_pushplus_open_api.py`: accepted and delivered client behavior.
- `tests/test_summarizer.py`: one-message bilingual rendering.
- `tests/test_webhook.py`: accepted-state mapping and one-call notification behavior.
- `tests/test_delivery_pipeline.py`: strict page-before-message result propagation.
- `tests/test_github_actions.py`: workflow-run state and dispatch client tests.
- `tests/test_github_actions_recovery.py`: guard/recovery decision tests.
- `tests/test_windows_scripts.py`: wrapper and ScheduledTasks contract tests.
- `tests/test_github_workflow.py`: parsed workflow/config contract tests.
- `docs/local-ai-radar-setup.md`: Chinese GitHub Actions secret, PAT permission, recovery, and verification guide.

---

### Task 1: PushPlus Confirmation Configuration Contract

**Files:**
- Modify: `src/models.py:456-470`
- Modify: `data/config.local.example.json`
- Modify: `scripts/check_local_setup.py:62-80,128-147,241-250`
- Modify: `tests/test_delivery_config.py`
- Modify: `tests/test_local_setup.py`

**Interfaces:**
- Consumes: existing `PushPlusClawBotConfig`, environment-name validation, and local setup raw-config scanning.
- Produces: `PushPlusClawBotConfig.confirmation: Literal["accepted", "delivered"]`, `message_mode: Literal["bilingual_links"]`, and `secret_key_env: str | None` with conditional validation.

- [ ] **Step 1: Write failing configuration tests**

Add these cases to `tests/test_delivery_config.py`:

```python
def test_clawbot_defaults_to_verified_bilingual_delivery():
    config = PushPlusClawBotConfig()

    assert config.confirmation == "delivered"
    assert config.message_mode == "bilingual_links"
    assert config.secret_key_env == "PUSHPLUS_SECRET_KEY"


def test_accepted_clawbot_mode_does_not_require_secret_environment_name():
    config = PushPlusClawBotConfig(
        confirmation="accepted",
        secret_key_env=None,
    )

    assert config.secret_key_env is None


def test_delivered_clawbot_mode_requires_secret_environment_name():
    with pytest.raises(ValidationError, match="secret_key_env"):
        PushPlusClawBotConfig(
            confirmation="delivered",
            secret_key_env=None,
        )
```

Add this case to `tests/test_local_setup.py`:

```python
def test_accepted_confirmation_does_not_require_pushplus_secret_key():
    raw = {
        "ai": {
            "provider": "openai",
            "api_key_env": "AOLIGEI_API_KEY",
        },
        "webhook": {
            "enabled": True,
            "url_env": "HORIZON_WEBHOOK_URL",
            "pushplus": {
                "confirmation": "accepted",
                "token_env": "PUSHPLUS_TOKEN",
                "secret_key_env": None,
            },
        },
        "github_pages": {
            "enabled": True,
            "token_env": "HORIZON_GITHUB_TOKEN",
        },
    }

    assert check_local_setup._required_environment(raw) == {
        "AOLIGEI_API_KEY",
        "PUSHPLUS_TOKEN",
        "HORIZON_GITHUB_TOKEN",
        "HORIZON_WEBHOOK_URL",
    }
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
uv run pytest tests/test_delivery_config.py tests/test_local_setup.py -q
```

Expected: FAIL because `confirmation` and `message_mode` do not exist and `secret_key_env` is not optional.

- [ ] **Step 3: Implement the conditional Pydantic contract**

Update `PushPlusClawBotConfig` in `src/models.py`:

```python
class PushPlusClawBotConfig(BaseModel):
    channel: Literal["clawbot"] = "clawbot"
    template: Literal["txt"] = "txt"
    confirmation: Literal["accepted", "delivered"] = "delivered"
    message_mode: Literal["bilingual_links"] = "bilingual_links"
    token_env: str = "PUSHPLUS_TOKEN"
    secret_key_env: str | None = "PUSHPLUS_SECRET_KEY"
    status_timeout_seconds: int = Field(default=90, ge=10, le=300)
    poll_interval_seconds: float = Field(default=2.0, gt=0, le=10)

    @field_validator("token_env")
    @classmethod
    def validate_token_environment_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("environment variable name is invalid")
        return value

    @field_validator("secret_key_env")
    @classmethod
    def validate_secret_environment_name(cls, value: str | None) -> str | None:
        if value is not None and not _ENV_NAME.fullmatch(value):
            raise ValueError("environment variable name is invalid")
        return value

    @model_validator(mode="after")
    def require_secret_for_delivered_confirmation(self):
        if self.confirmation == "delivered" and not self.secret_key_env:
            raise ValueError("secret_key_env is required for delivered confirmation")
        return self
```

Import `model_validator` from Pydantic if the file does not already import it.

In `scripts/check_local_setup.py`, only add `secret_key_env` to required variables when its raw value is non-empty. Build the local client with:

```python
secret_key = (
    os.environ.get(pushplus.secret_key_env, "")
    if pushplus.secret_key_env
    else None
)
return PushPlusClawBotClient(
    os.environ.get(config.webhook.url_env or "", ""),
    os.environ.get(pushplus.token_env, ""),
    secret_key,
    confirmation=pushplus.confirmation,
    status_timeout_seconds=pushplus.status_timeout_seconds,
    poll_interval_seconds=pushplus.poll_interval_seconds,
)
```

Set the local example PushPlus block explicitly to `"confirmation": "delivered"` and `"message_mode": "bilingual_links"`.

- [ ] **Step 4: Run focused tests and local configuration regression**

Run:

```powershell
uv run pytest tests/test_delivery_config.py tests/test_local_setup.py -q
uv run python scripts/check_local_setup.py --offline
```

Expected: tests PASS and local check prints `Offline configuration check passed` without displaying secret values.

- [ ] **Step 5: Commit only Task 1 paths**

```powershell
git add -- src/models.py data/config.local.example.json scripts/check_local_setup.py tests/test_delivery_config.py tests/test_local_setup.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: configure clawbot confirmation modes"
```

### Task 2: PushPlus Accepted Delivery Mode

**Files:**
- Modify: `src/services/pushplus.py:16-215`
- Modify: `tests/test_pushplus_open_api.py`
- Modify: `tests/test_pushplus.py`

**Interfaces:**
- Consumes: Task 1 `confirmation` values and optional secret key.
- Produces: `PushPlusDeliveryState.ACCEPTED` and a `PushPlusClawBotClient` constructor with `confirmation: Literal["accepted", "delivered"]`; `send_and_wait()` always returns a redacted `PushPlusDeliveryReport`.

- [ ] **Step 1: Write failing accepted-mode tests**

Add to `tests/test_pushplus_open_api.py`:

```python
def test_accepted_mode_posts_once_without_open_api_calls():
    request = ScriptedRequest(
        [httpx.Response(200, json={"code": 200, "msg": "ok", "data": "receipt-1"})]
    )
    client = PushPlusClawBotClient(
        endpoint="https://www.pushplus.plus/send",
        user_token="user-token",
        secret_key=None,
        confirmation="accepted",
        request=request,
        client=object(),
    )

    result = asyncio.run(client.send_and_wait("title", "body"))

    assert result.state == PushPlusDeliveryState.ACCEPTED
    assert result.short_code == "receipt-1"
    assert len(request.calls) == 1
    assert request.calls[0][1].endswith("/send")
    assert request.calls[0][2]["json"]["channel"] == "clawbot"
    assert request.calls[0][2]["json"]["template"] == "txt"


def test_delivered_mode_still_rejects_missing_secret_key():
    with pytest.raises(ValueError, match="secretKey"):
        PushPlusClawBotClient(
            endpoint="https://www.pushplus.plus/send",
            user_token="user-token",
            secret_key=None,
            confirmation="delivered",
        )
```

Add this failure case to the same file:

```python
def test_accepted_mode_redacts_send_business_failure():
    request = ScriptedRequest(
        [httpx.Response(200, json={"code": 500, "msg": "rejected user-token"})]
    )
    client = PushPlusClawBotClient(
        endpoint="https://www.pushplus.plus/send",
        user_token="user-token",
        secret_key=None,
        confirmation="accepted",
        request=request,
        client=object(),
    )

    result = asyncio.run(client.send_and_wait("title", "body"))

    assert result.state == PushPlusDeliveryState.API_FAILURE
    assert "user-token" not in (result.detail or "")
    assert "<redacted>" in (result.detail or "")
```

- [ ] **Step 2: Run the PushPlus tests and verify RED**

Run:

```powershell
uv run pytest tests/test_pushplus_open_api.py tests/test_pushplus.py -q
```

Expected: FAIL because the constructor always requires secretKey and there is no `ACCEPTED` state.

- [ ] **Step 3: Extract one send operation and branch only on confirmation**

Import `Literal` from `typing`, then add the enum member and use this complete constructor:

```python
class PushPlusDeliveryState(str, Enum):
    ACCEPTED = "accepted"
    INACTIVE = "inactive"
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    API_FAILURE = "api_failure"
```

```python
def __init__(
    self,
    endpoint: str,
    user_token: str,
    secret_key: str | None,
    *,
    confirmation: Literal["accepted", "delivered"] = "delivered",
    status_timeout_seconds: int = 90,
    poll_interval_seconds: float = 2.0,
    request: RequestCallable = safe_request,
    sleep: SleepCallable = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    client: httpx.AsyncClient | None = None,
):
    if not user_token:
        raise ValueError("PushPlus user token is required")
    if confirmation == "delivered" and not secret_key:
        raise ValueError("PushPlus secretKey is required for delivered confirmation")
    self._endpoint = validate_http_url(endpoint)
    self._user_token = user_token
    self._confirmation = confirmation
    self._secret_key = secret_key or ""
    self._status_timeout_seconds = status_timeout_seconds
    self._poll_interval_seconds = poll_interval_seconds
    self._request = request
    self._sleep = sleep
    self._monotonic = monotonic
    self._client = client or httpx.AsyncClient(timeout=30.0)
    self._owns_client = client is None
    self._access_key: str | None = None
    self._access_key_expires_at = 0.0
```

Extract the fixed `/send` request:

```python
async def _send_message(self, title: str, content: str) -> str:
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
    return receipt.strip()
```

Replace `send_and_wait()` with the same delivered-mode polling after an accepted-mode early return:

```python
async def send_and_wait(
    self,
    title: str,
    content: str,
) -> PushPlusDeliveryReport:
    short_code: str | None = None
    try:
        if self._confirmation == "delivered" and not await self.check_binding():
            return PushPlusDeliveryReport(
                PushPlusDeliveryState.INACTIVE,
                detail="ClawBot has no active conversation token",
            )
        short_code = await self._send_message(title, content)
        if self._confirmation == "accepted":
            return PushPlusDeliveryReport(
                PushPlusDeliveryState.ACCEPTED,
                short_code=short_code,
            )

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
                    detail=self._redact(
                        error_message or "PushPlus reported failure"
                    ),
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

Keep user token, optional secret, and AccessKey in `_redact()`.

- [ ] **Step 4: Run focused and full PushPlus tests**

Run:

```powershell
uv run pytest tests/test_pushplus_open_api.py tests/test_pushplus.py -q
```

Expected: all tests PASS; existing delivered-mode tests still observe AccessKey, binding, send, and status calls in that order.

- [ ] **Step 5: Commit only Task 2 paths**

```powershell
git add -- src/services/pushplus.py tests/test_pushplus_open_api.py tests/test_pushplus.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: accept clawbot delivery without open api"
```

### Task 3: One Bilingual ClawBot Message

**Files:**
- Modify: `src/ai/summarizer.py:455-511`
- Modify: `src/services/webhook.py:28-65,311-357,573-700,962-1040`
- Modify: `tests/test_summarizer.py`
- Modify: `tests/test_webhook.py`

**Interfaces:**
- Consumes: Task 1 `message_mode`, Task 2 accepted delivery state, existing `_friend_content()`, and validated public Pages URLs.
- Produces: `DailySummarizer.generate_clawbot_bilingual_digest(items, date, page_urls) -> str` and `WebhookNotifier.send_bilingual_daily_summary(important_items, date, summarizer, page_urls) -> WebhookDeliveryResult`.

- [ ] **Step 1: Write failing bilingual renderer tests**

Add to `tests/test_summarizer.py`:

```python
def test_bilingual_clawbot_digest_is_one_plain_text_message_with_two_links():
    summarizer = DailySummarizer()
    items = [_make_friend_item(index) for index in range(1, 6)]

    text = summarizer.generate_clawbot_bilingual_digest(
        items,
        "2026-08-03",
        {
            "zh": "https://xun-2.github.io/Horizon/daily/2026-08-03/zh.html",
            "en": "https://xun-2.github.io/Horizon/daily/2026-08-03/en.html",
        },
    )

    assert "早上好" in text
    assert text.count("https://") == 2
    assert "中文完整日报" in text
    assert "English report" in text
    assert "<" not in text
    assert "[" not in text
    assert sum(line.startswith(("1.", "2.", "3.")) for line in text.splitlines()) == 3


def test_bilingual_clawbot_digest_requires_both_public_links():
    with pytest.raises(ValueError, match="zh and en"):
        DailySummarizer().generate_clawbot_bilingual_digest(
            [],
            "2026-08-03",
            {"zh": "https://xun-2.github.io/Horizon/daily/2026-08-03/zh.html"},
        )
```

Add this test to `tests/test_webhook.py`, reusing its existing `_make_item` helper:

```python
def test_bilingual_clawbot_summary_sends_one_accepted_message(monkeypatch):
    class FakePushPlusClient:
        def __init__(self):
            self.calls = []

        async def send_and_wait(self, title, content):
            self.calls.append((title, content))
            return PushPlusDeliveryReport(
                state=PushPlusDeliveryState.ACCEPTED,
                short_code="receipt-1",
            )

    monkeypatch.setenv(_TEST_URL_ENV, _TEST_URL)
    client = FakePushPlusClient()
    config = WebhookConfig(
        enabled=True,
        url_env=_TEST_URL_ENV,
        delivery="overview",
        platform="pushplus",
        languages=["zh", "en"],
        pushplus=PushPlusClawBotConfig(
            confirmation="accepted",
            secret_key_env=None,
        ),
    )
    notifier = WebhookNotifier(config, pushplus_client=client)

    result = _run_async(
        notifier.send_bilingual_daily_summary(
            important_items=[_make_item()],
            date="2026-08-03",
            summarizer=DailySummarizer(),
            page_urls={
                "zh": "https://xun-2.github.io/Horizon/daily/2026-08-03/zh.html",
                "en": "https://xun-2.github.io/Horizon/daily/2026-08-03/en.html",
            },
        )
    )

    assert result.status == WebhookDeliveryStatus.SUCCESS
    assert len(client.calls) == 1
    assert client.calls[0][0] == "Horizon 2026-08-03 AI 日报"
    assert client.calls[0][1].count("https://") == 2
```

Import `PushPlusClawBotConfig`, `PushPlusDeliveryReport`, and
`PushPlusDeliveryState` in this test module.

- [ ] **Step 2: Run renderer/notifier tests and verify RED**

Run:

```powershell
uv run pytest tests/test_summarizer.py tests/test_webhook.py -q
```

Expected: FAIL because the bilingual method does not exist and accepted state is not mapped to success.

- [ ] **Step 3: Implement deterministic bilingual rendering**

Refactor existing page URL validation into a private helper used by both digest methods:

```python
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
```

Add:

```python
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
        title = re.sub(r"\s+", " ", title).strip()
        conclusion = re.sub(r"\s+", " ", sentences[0]).strip() if sentences else ""
        lines.append(f"{index}. {title}" + (f" - {conclusion}" if conclusion else ""))
    if not items:
        lines.append("今天暂无达到筛选阈值的动态。")
    lines.extend(["", f"中文完整日报: {zh_url}", f"English report: {en_url}"])
    return "\n".join(lines)
```

Import `Mapping` from `collections.abc`.

- [ ] **Step 4: Implement the one-call notifier path**

Map both accepted and delivered states to webhook success:

```python
PUSHPLUS_STATUS_MAP = {
    PushPlusDeliveryState.ACCEPTED: WebhookDeliveryStatus.SUCCESS,
    PushPlusDeliveryState.DELIVERED: WebhookDeliveryStatus.SUCCESS,
    PushPlusDeliveryState.INACTIVE: WebhookDeliveryStatus.CHANNEL_INACTIVE,
    PushPlusDeliveryState.FAILED: WebhookDeliveryStatus.DELIVERY_FAILED,
    PushPlusDeliveryState.TIMED_OUT: WebhookDeliveryStatus.DELIVERY_TIMEOUT,
    PushPlusDeliveryState.API_FAILURE: WebhookDeliveryStatus.PLATFORM_FAILURE,
}
```

Replace the PushPlus environment/client-factory block in `WebhookNotifier.__init__`
with:

```python
pushplus = config.pushplus
token = os.getenv(pushplus.token_env)
secret_key = (
    os.getenv(pushplus.secret_key_env)
    if pushplus.secret_key_env is not None
    else None
)
if not token:
    raise ValueError(f"Missing environment variable: {pushplus.token_env}")
if pushplus.confirmation == "delivered" and not secret_key:
    raise ValueError(
        f"Missing environment variable: {pushplus.secret_key_env}"
    )
self._configured_secrets.update(
    value for value in (token, secret_key) if value
)
self._pushplus_client_factory = lambda: PushPlusClawBotClient(
    endpoint=self.url or "",
    user_token=token,
    secret_key=secret_key,
    confirmation=pushplus.confirmation,
    status_timeout_seconds=pushplus.status_timeout_seconds,
    poll_interval_seconds=pushplus.poll_interval_seconds,
)
```

Add this focused method to `WebhookNotifier`:

```python
async def send_bilingual_daily_summary(
    self,
    important_items: List[ContentItem],
    date: str,
    summarizer: DailySummarizer,
    page_urls: Mapping[str, str],
) -> WebhookDeliveryResult:
    if not self.config.enabled:
        return WebhookDeliveryResult(WebhookDeliveryStatus.DISABLED)
    if self.config.platform != "pushplus" or self.config.pushplus is None:
        return WebhookDeliveryResult(
            WebhookDeliveryStatus.SKIPPED,
            detail="Bilingual links delivery requires PushPlus ClawBot",
        )
    content = summarizer.generate_clawbot_bilingual_digest(
        important_items,
        date,
        page_urls,
    )
    report = await self._send_one_pushplus(
        f"Horizon {date} AI 日报",
        content,
    )
    return self._webhook_result_from_pushplus(report)
```

Extract `_webhook_result_from_pushplus()` for the common state mapping:

```python
def _webhook_result_from_pushplus(
    self,
    report: PushPlusDeliveryReport,
) -> WebhookDeliveryResult:
    detail = self._redact_configured_secrets(report.detail or "")
    return WebhookDeliveryResult(
        status=PUSHPLUS_STATUS_MAP.get(
            report.state,
            WebhookDeliveryStatus.PLATFORM_FAILURE,
        ),
        detail=detail or None,
        error_type=report.state.value,
    )
```

Add `_send_one_pushplus()` so injected clients remain open and factory-created
clients are closed after one send:

```python
async def _send_one_pushplus(
    self,
    title: str,
    content: str,
) -> PushPlusDeliveryReport:
    delivery_client = self.pushplus_client
    owns_delivery_client = False
    if delivery_client is None and self._pushplus_client_factory is not None:
        delivery_client = self._pushplus_client_factory()
        owns_delivery_client = True
    if delivery_client is None:
        return PushPlusDeliveryReport(
            state=PushPlusDeliveryState.API_FAILURE,
            detail="PushPlus ClawBot client is not configured",
        )
    try:
        return await delivery_client.send_and_wait(title, content)
    finally:
        if owns_delivery_client:
            await delivery_client.aclose()
```

Import `Mapping` from `collections.abc` in `src/services/webhook.py` and
`PushPlusDeliveryReport` from `src.services.pushplus`. Change the existing
per-language loop to call `_webhook_result_from_pushplus()` while retaining its
one-client-per-batch ownership. The bilingual path uses `_send_one_pushplus()`
because it always sends exactly one message.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
uv run pytest tests/test_summarizer.py tests/test_webhook.py -q
```

Expected: PASS, including all legacy platform and per-language message tests.

- [ ] **Step 6: Commit only Task 3 paths**

```powershell
git add -- src/ai/summarizer.py src/services/webhook.py tests/test_summarizer.py tests/test_webhook.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: send one bilingual clawbot digest"
```

### Task 4: Strict Daily Delivery Result Propagation

**Files:**
- Modify: `src/orchestrator.py:214-405,401-470`
- Modify: `tests/test_delivery_pipeline.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: Task 3 single-message notifier and `PagePublishResult`.
- Produces: `DailyDeliveryResult`, `DailyDeliveryError`, `_deliver_daily(important_items, total_fetched, date) -> DailyDeliveryResult`, and non-zero CLI exit through the existing top-level exception handler.

- [ ] **Step 1: Replace permissive pipeline expectations with strict failing tests**

In `tests/test_delivery_pipeline.py`, import `DailyDeliveryResult`,
`WebhookDeliveryResult`, and `WebhookDeliveryStatus`. Replace `FakeNotifier` and
`_orchestrator` with:

```python
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
            pushplus=SimpleNamespace(message_mode="bilingual_links")
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
```

Then replace the permissive delivery expectations with:

```python
def test_bilingual_pipeline_publishes_both_languages_then_sends_once():
    events = []
    orchestrator = _orchestrator(events, publish_success=True, notify_success=True)

    result = asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-03"))

    assert result.success is True
    assert events == ["save:zh", "save:en", "publish:zh,en", "notify:bilingual"]


def test_pages_failure_skips_clawbot_and_is_not_success():
    events = []
    orchestrator = _orchestrator(events, publish_success=False, notify_success=True)

    result = asyncio.run(orchestrator._deliver_daily([], 0, "2026-08-03"))

    assert result.success is False
    assert result.error_type == "github_failure"
    assert "notify:bilingual" not in events


def test_pushplus_failure_is_not_daily_success():
    result = asyncio.run(
        _orchestrator([], publish_success=True, notify_success=False)._deliver_daily(
            [], 0, "2026-08-03"
        )
    )

    assert result.success is False
    assert result.error_type == "pushplus_failure"
```

Update `test_no_fetched_items_still_runs_empty_delivery` so its fake delivery
returns the new result type:

```python
async def deliver_daily(items, total_fetched, date):
    events.append((items, total_fetched, date))
    return DailyDeliveryResult(success=True, page_urls={})
```

Add this concrete case to `tests/test_main.py`:

```python
def test_daily_delivery_error_exits_one_without_secret_text(monkeypatch):
    output = []

    class LoadedStorage:
        def __init__(self, data_dir, config_path):
            self.config_path = Path("data/config.json")

        def load_config(self):
            return SimpleNamespace(display=SimpleNamespace(icon_style="ascii"))

    class FailingOrchestrator:
        def __init__(self, config, storage, console):
            pass

        async def run(self, force_hours=None):
            raise DailyDeliveryError("pushplus_failure")

    monkeypatch.setattr(main_module, "StorageManager", LoadedStorage)
    monkeypatch.setattr(main_module, "HorizonOrchestrator", FailingOrchestrator)
    monkeypatch.setattr(main_module, "configure_logging", lambda console: None)
    monkeypatch.setattr(main_module, "print_banner", lambda: None)
    monkeypatch.setattr(
        main_module,
        "console",
        SimpleNamespace(
            print=lambda *args, **kwargs: output.append(" ".join(map(str, args))),
            print_exception=lambda: None,
        ),
    )
    monkeypatch.setattr("sys.argv", ["horizon"])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert "pushplus_failure" in "\n".join(output)
    assert "PUSHPLUS_SECRET_KEY" not in "\n".join(output)
```

Import `DailyDeliveryError` from `src.orchestrator` in this test module.

- [ ] **Step 2: Run pipeline and CLI tests and verify RED**

Run:

```powershell
uv run pytest tests/test_delivery_pipeline.py tests/test_main.py -q
```

Expected: FAIL because `_deliver_daily` returns `None`, still sends without links, and no delivery error type exists.

- [ ] **Step 3: Add an explicit result type and strict bilingual path**

Add near the orchestrator module's other result types:

```python
@dataclass(frozen=True)
class DailyDeliveryResult:
    success: bool
    page_urls: dict[str, str]
    notification_results: Sequence[WebhookDeliveryResult] = ()
    error_type: str | None = None


class DailyDeliveryError(RuntimeError):
    pass
```

Import `Sequence` from `collections.abc` and `WebhookDeliveryResult` alongside
`WebhookNotifier`. Import `PagePublishResult` alongside
`GitHubPagesPublisher`.

Make `_deliver_daily()` return `DailyDeliveryResult`. Initialize
`publication: PagePublishResult | None = None` before the optional Pages block.
After both summaries are saved, publish one page bundle. Set the delivery mode
with this exact condition:

```python
pushplus = (
    self.config.webhook.pushplus
    if self.webhook_notifier
    and self.config.webhook is not None
    and self.config.webhook.platform == "pushplus"
    else None
)
use_bilingual_links = (
    pushplus is not None and pushplus.message_mode == "bilingual_links"
)
```

For `use_bilingual_links`:

```python
if use_bilingual_links:
    if (
        publication is None
        or not publication.success
        or not set(languages).issubset(page_urls)
    ):
        return DailyDeliveryResult(
            success=False,
            page_urls=page_urls,
            error_type=(
                publication.error_type
                if publication is not None and publication.error_type
                else "pages_incomplete"
            ),
        )
    notification = await self.webhook_notifier.send_bilingual_daily_summary(
        important_items=important_items,
        date=date,
        summarizer=summarizer,
        page_urls=page_urls,
    )
    return DailyDeliveryResult(
        success=notification.sent,
        page_urls=page_urls,
        notification_results=(notification,),
        error_type=None if notification.sent else "pushplus_failure",
    )
```

For non-bilingual platforms, retain the existing per-language calls and collect
their typed results before returning:

```python
legacy_results: list[WebhookDeliveryResult] = []
for lang, summary in summaries.items():
    if (
        self.email_manager
        and self.config.email
        and self.config.email.enabled
    ):
        subscribers = self.storage.load_subscribers()
        subject = f"Horizon Summary ({lang.upper()}) - {date}"
        self.email_manager.send_daily_summary(summary, subject, subscribers)
    if self.webhook_notifier:
        legacy_results.extend(
            await self.webhook_notifier.send_daily_summary(
                summary=summary,
                important_items=important_items,
                all_items_count=total_fetched,
                date=date,
                lang=lang,
                summarizer=summarizer,
                page_url=page_urls.get(lang),
            )
        )
return DailyDeliveryResult(
    success=True,
    page_urls=page_urls,
    notification_results=tuple(legacy_results),
)
```

At the empty-fetch call site in `run()`, require success:

```python
delivery = await self._deliver_daily([], 0, today)
if not delivery.success:
    raise DailyDeliveryError(delivery.error_type or "daily_delivery_failed")
```

At the normal call site, require success:

```python
delivery = await self._deliver_daily(important_items, len(all_items), today)
if not delivery.success:
    raise DailyDeliveryError(delivery.error_type or "daily_delivery_failed")
```

The existing `src.main.main()` broad exception handler will then exit with code
1; do not add a second CLI error wrapper. In `HorizonOrchestrator.run()`'s
exception block, prevent a required delivery failure from attempting the legacy
failure webhook:

```python
if self.webhook_notifier and not isinstance(error, DailyDeliveryError):
    await self.webhook_notifier.send_failure(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        error_message=str(error),
    )
```

Rename the exception variable from `e` to `error` throughout that block. Other
pipeline failures retain the existing failure-notification behavior.

- [ ] **Step 4: Run pipeline, CLI, and orchestrator regressions**

Run:

```powershell
uv run pytest tests/test_delivery_pipeline.py tests/test_main.py -q
```

Expected: PASS. Pages failure never emits a ClawBot message, and a failed required delivery reaches CLI exit code 1.

- [ ] **Step 5: Commit only Task 4 paths**

```powershell
git add -- src/orchestrator.py tests/test_delivery_pipeline.py tests/test_main.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: fail incomplete daily delivery"
```

### Task 5: GitHub Actions Run-State Client and Recovery CLI

**Files:**
- Create: `src/services/github_actions.py`
- Create: `scripts/github_actions_recovery.py`
- Create: `tests/test_github_actions.py`
- Create: `tests/test_github_actions_recovery.py`

**Interfaces:**
- Consumes: GitHub REST workflow runs and dispatch endpoints, `HORIZON_GITHUB_TOKEN`, Beijing business date, and optional current run ID.
- Produces: `DailyWorkflowState`, `GitHubActionsClient.daily_state(date, exclude_run_id=None) -> DailyWorkflowState`, `wait_until_terminal(date, timeout_seconds=1800, poll_interval_seconds=15) -> DailyWorkflowState`, `dispatch(ref="main") -> None`, and CLI subcommands `guard` and `recover`.

- [ ] **Step 1: Write failing state classification tests**

Create `tests/test_github_actions.py` with the complete scripted-request helpers and core cases:

```python
import asyncio
from datetime import date

import httpx
import pytest

from src.services.github_actions import (
    DailyWorkflowState,
    GitHubActionsClient,
    GitHubActionsError,
)


class ScriptedRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, client, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.request = httpx.Request(method, url)
        return response


async def _completed_sleep(seconds):
    assert seconds >= 0


def _run(run_id, *, status, conclusion):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
    }


def _client_with_responses(responses, *, token="github-token"):
    request = ScriptedRequest(responses)
    client = GitHubActionsClient(
        repository="Xun-2/Horizon",
        workflow="daily-summary.yml",
        token=token,
        request=request,
        sleep=_completed_sleep,
        monotonic=lambda: 0.0,
        client=object(),
    )
    return client, request


def _client_with_runs(runs):
    client, _ = _client_with_responses(
        [httpx.Response(200, json={"workflow_runs": runs})]
    )
    return client


def test_daily_state_prefers_success_and_excludes_current_run():
    client = _client_with_runs(
        [
            _run(100, status="in_progress", conclusion=None),
            _run(99, status="completed", conclusion="success"),
        ]
    )

    state = asyncio.run(
        client.daily_state(date(2026, 8, 3), exclude_run_id=100)
    )

    assert state == DailyWorkflowState.SUCCESS


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([_run(1, status="queued", conclusion=None)], DailyWorkflowState.ACTIVE),
        ([_run(1, status="completed", conclusion="failure")], DailyWorkflowState.FAILED),
        ([], DailyWorkflowState.MISSING),
    ],
)
def test_daily_state_classifies_runs(runs, expected):
    assert asyncio.run(_client_with_runs(runs).daily_state(date(2026, 8, 3))) == expected


def test_daily_state_queries_from_beijing_midnight():
    client, request = _client_with_responses(
        [httpx.Response(200, json={"workflow_runs": []})]
    )

    asyncio.run(client.daily_state(date(2026, 8, 3)))

    method, url, kwargs = request.calls[0]
    assert method == "GET"
    assert url.endswith(
        "/repos/Xun-2/Horizon/actions/workflows/daily-summary.yml/runs"
    )
    assert kwargs["params"]["created"] == ">=2026-08-02T16:00:00Z"


def test_dispatch_posts_main_ref_and_requires_http_204():
    client, request = _client_with_responses([httpx.Response(204)])

    asyncio.run(client.dispatch())

    method, url, kwargs = request.calls[0]
    assert method == "POST"
    assert url.endswith(
        "/repos/Xun-2/Horizon/actions/workflows/daily-summary.yml/dispatches"
    )
    assert kwargs["json"] == {"ref": "main"}


def test_github_error_redacts_configured_token():
    token = "github-token-value"
    client, _ = _client_with_responses(
        [httpx.Response(403, json={"message": f"denied {token}"})],
        token=token,
    )

    with pytest.raises(GitHubActionsError) as exc_info:
        asyncio.run(client.dispatch())

    assert token not in str(exc_info.value)
    assert "<redacted>" in str(exc_info.value)
```

- [ ] **Step 2: Write failing CLI decision tests**

Create `tests/test_github_actions_recovery.py` with a fake typed client and every recovery branch:

```python
from src.services.github_actions import DailyWorkflowState, GitHubActionsError
from scripts import github_actions_recovery as recovery


class FakeClient:
    def __init__(
        self,
        state,
        *,
        terminal_state=DailyWorkflowState.SUCCESS,
        error=None,
    ):
        self.state = state
        self.terminal_state = terminal_state
        self.error = error
        self.daily_calls = []
        self.wait_calls = []
        self.dispatch_calls = []
        self.closed = False

    async def daily_state(self, business_date, *, exclude_run_id=None):
        self.daily_calls.append((business_date, exclude_run_id))
        if self.error is not None:
            raise self.error
        return self.state

    async def wait_until_terminal(
        self,
        business_date,
        *,
        timeout_seconds=1800,
        poll_interval_seconds=15,
    ):
        self.wait_calls.append((business_date, timeout_seconds, poll_interval_seconds))
        return self.terminal_state

    async def dispatch(self, ref="main"):
        self.dispatch_calls.append(ref)

    async def aclose(self):
        self.closed = True


def _install_client(monkeypatch, client):
    monkeypatch.setattr(recovery, "_build_client", lambda: client)


def test_guard_skips_when_today_already_succeeded(monkeypatch, capsys):
    client = FakeClient(DailyWorkflowState.SUCCESS)
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["guard", "--date", "2026-08-03", "--exclude-run-id", "12"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "skip"
    assert client.daily_calls[0][1] == 12
    assert client.closed is True


def test_guard_runs_when_today_has_no_success(monkeypatch, capsys):
    client = FakeClient(DailyWorkflowState.MISSING)
    _install_client(monkeypatch, client)

    exit_code = recovery.main(["guard", "--date", "2026-08-03"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "run"


def test_recover_before_0722_is_noop(monkeypatch, capsys):
    monkeypatch.setattr(
        recovery,
        "_build_client",
        lambda: (_ for _ in ()).throw(AssertionError("client should not be built")),
    )

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T07:10:00+08:00"]
    )

    assert exit_code == 0
    assert '"action": "before_schedule"' in capsys.readouterr().out


def test_recover_successful_day_is_noop(monkeypatch, capsys):
    client = FakeClient(DailyWorkflowState.SUCCESS)
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T08:00:00+08:00"]
    )

    assert exit_code == 0
    assert client.dispatch_calls == []
    assert '"action": "already_successful"' in capsys.readouterr().out


def test_recover_waits_for_active_success(monkeypatch, capsys):
    client = FakeClient(
        DailyWorkflowState.ACTIVE,
        terminal_state=DailyWorkflowState.SUCCESS,
    )
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        [
            "recover",
            "--now",
            "2026-08-03T08:00:00+08:00",
            "--wait-timeout-seconds",
            "60",
        ]
    )

    assert exit_code == 0
    assert client.wait_calls[0][1] == 60
    assert client.dispatch_calls == []
    assert '"action": "active_success"' in capsys.readouterr().out


def test_recover_dispatches_after_active_failure(monkeypatch, capsys):
    client = FakeClient(
        DailyWorkflowState.ACTIVE,
        terminal_state=DailyWorkflowState.FAILED,
    )
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T08:00:00+08:00"]
    )

    assert exit_code == 0
    assert client.dispatch_calls == ["main"]
    assert '"action": "dispatched"' in capsys.readouterr().out


def test_recover_dispatches_failed_or_missing_day(monkeypatch, capsys):
    for state in (DailyWorkflowState.FAILED, DailyWorkflowState.MISSING):
        client = FakeClient(state)
        _install_client(monkeypatch, client)

        exit_code = recovery.main(
            ["recover", "--now", "2026-08-03T08:00:00+08:00"]
        )

        assert exit_code == 0
        assert client.dispatch_calls == ["main"]
        assert '"action": "dispatched"' in capsys.readouterr().out


def test_recover_api_failure_is_redacted(monkeypatch, capsys):
    token = "local-github-token"
    monkeypatch.setenv("HORIZON_GITHUB_TOKEN", token)
    client = FakeClient(
        DailyWorkflowState.MISSING,
        error=GitHubActionsError(f"remote echoed {token}"),
    )
    _install_client(monkeypatch, client)

    exit_code = recovery.main(
        ["recover", "--now", "2026-08-03T08:00:00+08:00"]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert token not in output.out + output.err
    assert "<redacted>" in output.err
```

- [ ] **Step 3: Run new tests and verify RED**

Run:

```powershell
uv run pytest tests/test_github_actions.py tests/test_github_actions_recovery.py -q
```

Expected: collection FAIL because both new modules are absent.

- [ ] **Step 4: Implement the typed GitHub Actions client**

Create `src/services/github_actions.py` with this complete implementation:

```python
"""Query and dispatch the Horizon daily GitHub Actions workflow."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
import time as time_module

import httpx

from ..url_security import safe_request


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
RequestCallable = Callable[
    [httpx.AsyncClient, str, str],
    Awaitable[httpx.Response],
]
SleepCallable = Callable[[float], Awaitable[None]]


class DailyWorkflowState(str, Enum):
    SUCCESS = "success"
    ACTIVE = "active"
    FAILED = "failed"
    MISSING = "missing"


class GitHubActionsError(RuntimeError):
    pass


class GitHubActionsClient:
    API_ROOT = "https://api.github.com"

    def __init__(
        self,
        repository: str,
        workflow: str,
        token: str,
        *,
        request: RequestCallable = safe_request,
        sleep: SleepCallable = asyncio.sleep,
        monotonic: Callable[[], float] = time_module.monotonic,
        client: httpx.AsyncClient | None = None,
    ):
        if repository != "Xun-2/Horizon":
            raise ValueError("repository must be Xun-2/Horizon")
        if workflow != "daily-summary.yml":
            raise ValueError("workflow must be daily-summary.yml")
        if not token:
            raise ValueError("HORIZON_GITHUB_TOKEN is required")
        self._repository = repository
        self._workflow = workflow
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
            "User-Agent": "Horizon-Daily-Recovery",
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _redact(self, value: str) -> str:
        redacted = value
        for secret in (f"Bearer {self._token}", self._token):
            redacted = redacted.replace(secret, "<redacted>")
        return redacted

    def _api_url(self, path: str) -> str:
        return f"{self.API_ROOT}/repos/{self._repository}/{path.lstrip('/')}"

    async def _api_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = dict(self._headers)
        headers.update(kwargs.pop("headers", {}))
        try:
            return await self._request(
                self._client,
                method,
                self._api_url(path),
                headers=headers,
                **kwargs,
            )
        except Exception as exc:
            raise GitHubActionsError(
                self._redact(f"{type(exc).__name__}: {exc}")
            ) from exc

    def _response_detail(self, response: httpx.Response) -> str:
        detail = f"GitHub HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("message"):
            detail += f": {payload['message']}"
        return self._redact(detail)

    async def daily_state(
        self,
        business_date: date,
        *,
        exclude_run_id: int | None = None,
    ) -> DailyWorkflowState:
        midnight = datetime.combine(business_date, time.min, tzinfo=BEIJING)
        created_from = midnight.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = await self._api_request(
            "GET",
            f"actions/workflows/{self._workflow}/runs",
            params={"created": f">={created_from}", "per_page": 100},
        )
        if not 200 <= response.status_code < 300:
            raise GitHubActionsError(self._response_detail(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubActionsError("GitHub workflow-runs response is not JSON") from exc
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise GitHubActionsError("GitHub workflow-runs response is invalid")
        relevant = [
            run
            for run in runs
            if isinstance(run, dict)
            and (exclude_run_id is None or run.get("id") != exclude_run_id)
        ]
        if any(
            run.get("status") == "completed" and run.get("conclusion") == "success"
            for run in relevant
        ):
            return DailyWorkflowState.SUCCESS
        if any(run.get("status") != "completed" for run in relevant):
            return DailyWorkflowState.ACTIVE
        if relevant:
            return DailyWorkflowState.FAILED
        return DailyWorkflowState.MISSING

    async def wait_until_terminal(
        self,
        business_date: date,
        *,
        timeout_seconds: int = 1800,
        poll_interval_seconds: int = 15,
    ) -> DailyWorkflowState:
        deadline = self._monotonic() + timeout_seconds
        while True:
            state = await self.daily_state(business_date)
            if state != DailyWorkflowState.ACTIVE:
                return state
            if self._monotonic() >= deadline:
                raise GitHubActionsError(
                    "Timed out waiting for active daily workflow"
                )
            await self._sleep(poll_interval_seconds)

    async def dispatch(self, ref: str = "main") -> None:
        response = await self._api_request(
            "POST",
            f"actions/workflows/{self._workflow}/dispatches",
            json={"ref": ref},
        )
        if response.status_code != 204:
            raise GitHubActionsError(self._response_detail(response))
```

- [ ] **Step 5: Implement the guard/recovery CLI**

Create `scripts/github_actions_recovery.py` with this implementation. It uses a
fixed UTC+08:00 offset because China has no daylight-saving transition:

```python
"""Guard or recover the Horizon daily GitHub Actions workflow."""

import argparse
import asyncio
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.environment import load_horizon_dotenv  # noqa: E402
from src.services.github_actions import (  # noqa: E402
    DailyWorkflowState,
    GitHubActionsClient,
)


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
SCHEDULE_TIME = time(7, 22)
TOKEN_ENV = "HORIZON_GITHUB_TOKEN"


def _build_client() -> GitHubActionsClient:
    return GitHubActionsClient(
        repository="Xun-2/Horizon",
        workflow="daily-summary.yml",
        token=os.environ.get(TOKEN_ENV, ""),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    guard = subparsers.add_parser("guard")
    guard.add_argument("--date", required=True)
    guard.add_argument("--exclude-run-id", type=int)

    recover = subparsers.add_parser("recover")
    recover.add_argument("--now")
    recover.add_argument("--wait-timeout-seconds", type=int, default=1800)
    return parser


def _beijing_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(BEIJING)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a UTC offset")
    return parsed.astimezone(BEIJING)


def _print_action(action: str) -> None:
    print(json.dumps({"action": action}, ensure_ascii=False, sort_keys=True))


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "recover":
        now = _beijing_now(args.now)
        if now.timetz().replace(tzinfo=None) < SCHEDULE_TIME:
            _print_action("before_schedule")
            return 0
        business_date = now.date()
    else:
        business_date = date.fromisoformat(args.date)

    client = _build_client()
    try:
        if args.command == "guard":
            state = await client.daily_state(
                business_date,
                exclude_run_id=args.exclude_run_id,
            )
            print("skip" if state == DailyWorkflowState.SUCCESS else "run")
            return 0

        state = await client.daily_state(business_date)
        if state == DailyWorkflowState.SUCCESS:
            _print_action("already_successful")
            return 0
        if state == DailyWorkflowState.ACTIVE:
            state = await client.wait_until_terminal(
                business_date,
                timeout_seconds=args.wait_timeout_seconds,
            )
            if state == DailyWorkflowState.SUCCESS:
                _print_action("active_success")
                return 0
        await client.dispatch("main")
        _print_action("dispatched")
        return 0
    finally:
        await client.aclose()


def _redact(value: str) -> str:
    token = os.environ.get(TOKEN_ENV, "")
    return value.replace(token, "<redacted>") if token else value


def main(argv=None) -> int:
    load_horizon_dotenv()
    try:
        args = _parser().parse_args(argv)
        return asyncio.run(async_main(args))
    except (Exception, KeyboardInterrupt) as exc:
        print(_redact(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`guard` prints only `run` or `skip`. `recover` prints one JSON object whose
`action` is `before_schedule`, `already_successful`, `active_success`, or
`dispatched`; it never serializes request headers or environment values.

- [ ] **Step 6: Run new tests**

Run:

```powershell
uv run pytest tests/test_github_actions.py tests/test_github_actions_recovery.py -q
```

Expected: all new tests PASS.

- [ ] **Step 7: Commit only Task 5 paths**

```powershell
git add -- src/services/github_actions.py scripts/github_actions_recovery.py tests/test_github_actions.py tests/test_github_actions_recovery.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: recover daily workflow through github actions"
```

### Task 6: Windows Login Recovery Task

**Files:**
- Create: `scripts/run_cloud_recovery.ps1`
- Modify: `scripts/install_scheduled_task.ps1`
- Modify: `tests/test_windows_scripts.py`

**Interfaces:**
- Consumes: Task 5 `scripts/github_actions_recovery.py recover` and existing repo-local uv cache/logging pattern.
- Produces: a locked recovery wrapper and `HorizonLocalAIRadar` with AtLogOn plus daily 07:45 triggers.

- [ ] **Step 1: Write failing PowerShell contract tests**

Add the recovery constant/helpers and runner tests to
`tests/test_windows_scripts.py`. Replace the existing
`test_installer_whatif_reports_full_daily_contract_without_registration` test
with the cloud-recovery contract test shown at the end of this block:

```python
RECOVERY_RUNNER = ROOT / "scripts" / "run_cloud_recovery.ps1"


def _new_recovery_logs(before: set[Path]) -> set[Path]:
    log_dir = ROOT / "logs"
    after = set(log_dir.glob("cloud-recovery-*.log")) if log_dir.exists() else set()
    return after - before


def _fake_uv_capture(tmp_path: Path) -> Path:
    fake_uv = tmp_path / "fake-uv.ps1"
    fake_uv.write_text(
        """
$payload = [ordered]@{
    working_directory = (Get-Location).Path
    uv_cache_dir = $env:UV_CACHE_DIR
    arguments = @($args)
}
$payload | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:HORIZON_TEST_CAPTURE -Encoding utf8
exit 0
""".strip(),
        encoding="utf-8",
    )
    return fake_uv


def test_recovery_runner_uses_repo_cache_and_recover_command(tmp_path):
    capture = tmp_path / "capture.json"
    fake_uv = _fake_uv_capture(tmp_path)
    log_dir = ROOT / "logs"
    before = (
        set(log_dir.glob("cloud-recovery-*.log")) if log_dir.exists() else set()
    )
    result = _powershell(
        RECOVERY_RUNNER,
        "-UvExecutable",
        str(fake_uv),
        env=dict(os.environ, HORIZON_TEST_CAPTURE=str(capture)),
    )

    created_logs = _new_recovery_logs(before)
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(capture.read_text(encoding="utf-8-sig"))
        assert Path(payload["working_directory"]) == ROOT
        assert Path(payload["uv_cache_dir"]) == ROOT / ".uv" / "cache"
        assert payload["arguments"] == [
            "run",
            "python",
            "scripts/github_actions_recovery.py",
            "recover",
        ]
        assert len(created_logs) == 1
    finally:
        for path in created_logs:
            path.unlink(missing_ok=True)


def test_recovery_runner_exclusive_lock_rejects_second_instance(tmp_path):
    started = tmp_path / "started"
    release = tmp_path / "release"
    fake_uv = tmp_path / "blocking-uv.ps1"
    fake_uv.write_text(
        """
Set-Content -LiteralPath $env:HORIZON_TEST_STARTED -Value started
while (-not (Test-Path -LiteralPath $env:HORIZON_TEST_RELEASE)) {
    Start-Sleep -Milliseconds 50
}
exit 0
""".strip(),
        encoding="utf-8",
    )
    environment = dict(
        os.environ,
        HORIZON_TEST_STARTED=str(started),
        HORIZON_TEST_RELEASE=str(release),
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RECOVERY_RUNNER),
        "-UvExecutable",
        str(fake_uv),
    ]
    log_dir = ROOT / "logs"
    before = (
        set(log_dir.glob("cloud-recovery-*.log")) if log_dir.exists() else set()
    )
    first = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists(), "first recovery runner did not reach fake uv"

        second = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        assert second.returncode == 3
        assert "already running" in second.stderr.lower()
    finally:
        release.write_text("release", encoding="utf-8")
        first.communicate(timeout=10)
        for path in _new_recovery_logs(before):
            path.unlink(missing_ok=True)
        (ROOT / "logs" / "cloud-recovery.lock").unlink(missing_ok=True)


def test_installer_whatif_reports_cloud_recovery_triggers():
    result = _powershell(INSTALLER, "-WhatIf")
    assert result.returncode == 0, result.stdout + result.stderr
    contract = json.loads(result.stdout.strip())

    assert contract["action_script"].endswith("run_cloud_recovery.ps1")
    assert contract["triggers"] == ["at logon", "daily 07:45"]
    assert contract["multiple_instances"] == "IgnoreNew"
```

- [ ] **Step 2: Run Windows script tests and verify RED**

Run:

```powershell
uv run pytest tests/test_windows_scripts.py -q
```

Expected: FAIL because the recovery wrapper is absent and the installer still points at `run_horizon.ps1` with one 07:22 trigger.

- [ ] **Step 3: Create the recovery wrapper**

Create `scripts/run_cloud_recovery.ps1` with the full locked runner:

```powershell
[CmdletBinding()]
param(
    [string]$UvExecutable = 'uv'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot 'logs'
$lockPath = Join-Path $logDir 'cloud-recovery.lock'
$uvCacheDir = Join-Path $repoRoot '.uv\cache'

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
New-Item -ItemType Directory -Path $uvCacheDir -Force | Out-Null

try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
}
catch [System.IO.IOException] {
    [Console]::Error.WriteLine('Cloud recovery is already running; this invocation was skipped.')
    exit 3
}

$logPath = Join-Path $logDir ("cloud-recovery-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$previousCache = $env:UV_CACHE_DIR
$locationPushed = $false
try {
    $env:UV_CACHE_DIR = $uvCacheDir
    Push-Location -LiteralPath $repoRoot
    $locationPushed = $true

    "[{0}] Cloud recovery started" -f (Get-Date -Format 'o') |
        Out-File -LiteralPath $logPath -Encoding utf8
    $uvCommand = (Get-Command $UvExecutable -ErrorAction Stop).Source
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $uvCommand run python scripts/github_actions_recovery.py recover 2>&1 |
            ForEach-Object {
                $line = if ($_ -is [System.Management.Automation.ErrorRecord]) {
                    $_.Exception.Message
                }
                else {
                    $_.ToString()
                }
                $line | Out-File -LiteralPath $logPath -Encoding utf8 -Append
            }
        $processExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($null -eq $processExitCode) {
        $processExitCode = 0
    }
    "[{0}] Cloud recovery finished with exit code {1}" -f (
        Get-Date -Format 'o'
    ), $processExitCode | Out-File -LiteralPath $logPath -Encoding utf8 -Append
    exit $processExitCode
}
catch {
    "[{0}] Cloud recovery failed: {1}" -f (
        Get-Date -Format 'o'
    ), $_.Exception.GetType().Name | Out-File -LiteralPath $logPath -Encoding utf8 -Append
    [Console]::Error.WriteLine('Cloud recovery failed. See the timestamped log for details.')
    exit 1
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
    if ($null -eq $previousCache) {
        Remove-Item Env:UV_CACHE_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:UV_CACHE_DIR = $previousCache
    }
    $lockStream.Dispose()
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
```

- [ ] **Step 4: Change the ScheduledTasks registration contract**

Replace `scripts/install_scheduled_task.ps1` with:

```powershell
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$ConfirmCloudWorkflowReady
)

$ErrorActionPreference = 'Stop'
$taskName = 'HorizonLocalAIRadar'
$repoRoot = Split-Path -Parent $PSScriptRoot
$runnerPath = Join-Path $PSScriptRoot 'run_cloud_recovery.ps1'
$requiredTimeZone = 'China Standard Time'

if ((Get-TimeZone).Id -ne $requiredTimeZone) {
    throw "Task installation requires Windows time zone '$requiredTimeZone'."
}

$contract = [ordered]@{
    task_name = $taskName
    action = 'register'
    action_script = $runnerPath
    triggers = @('at logon', 'daily 07:45')
    time_zone = $requiredTimeZone
    start_when_available = $true
    wake_to_run = $true
    multiple_instances = 'IgnoreNew'
    execution_time_limit = 'PT2H'
    working_directory = $repoRoot
}

if ($WhatIfPreference) {
    $contract | ConvertTo-Json -Compress
    exit 0
}

if (-not $ConfirmCloudWorkflowReady) {
    throw 'Confirm the GitHub workflow and PAT are configured, then rerun with -ConfirmCloudWorkflowReady.'
}

$powerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`""
$action = New-ScheduledTaskAction `
    -Execute $powerShellPath `
    -Argument $arguments `
    -WorkingDirectory $repoRoot
$userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$fallbackTrigger = New-ScheduledTaskTrigger -Daily -At '07:45'
$triggers = @($logonTrigger, $fallbackTrigger)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

if ($PSCmdlet.ShouldProcess($taskName, 'Register Horizon cloud recovery task')) {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description 'Horizon cloud daily recovery' `
        -Force | Out-Null
    Write-Host "Scheduled task '$taskName' registered."
}
```

- [ ] **Step 5: Run Windows tests**

Run:

```powershell
uv run pytest tests/test_windows_scripts.py -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -WhatIf
```

Expected: PASS; WhatIf JSON names `run_cloud_recovery.ps1`, `at logon`, and `daily 07:45`.

- [ ] **Step 6: Commit only Task 6 paths**

```powershell
git add -- scripts/run_cloud_recovery.ps1 scripts/install_scheduled_task.ps1 tests/test_windows_scripts.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: retry cloud daily run after windows login"
```

### Task 7: GitHub Actions Cloud Configuration and Workflow

**Files:**
- Create: `data/config.github-actions.json`
- Create: `.github/workflows/daily-summary.yml`
- Delete: `.github/workflows/daily-summary.yml.disabled`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/test_github_workflow.py`

**Interfaces:**
- Consumes: Task 1 cloud config contract, Task 4 strict CLI exit, and Task 5 `guard` command.
- Produces: default-branch schedule/manual workflow with dedup, bounded retry, minimal permissions, and allowed secrets only.

- [ ] **Step 1: Add failing structured workflow/config tests**

Add `pyyaml>=6.0.2` to the `dev` optional dependencies and run `uv lock`. Create `tests/test_github_workflow.py`:

```python
import json
from pathlib import Path
import re

import yaml

from src.models import Config


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-summary.yml"
CONFIG = ROOT / "data" / "config.github-actions.json"


def _workflow():
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_cloud_config_uses_aoligei_pages_and_accepted_clawbot():
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    config = Config.model_validate(raw)

    assert config.ai.base_url == "https://aoligei.cc/v1"
    assert config.ai.api_key_env == "AOLIGEI_API_KEY"
    assert config.ai.languages == ["zh", "en"]
    assert config.github_pages.repository == "Xun-2/Horizon"
    assert config.webhook.pushplus.confirmation == "accepted"
    assert config.webhook.pushplus.secret_key_env is None


def test_workflow_schedule_permissions_concurrency_and_dispatch():
    workflow = _workflow()

    assert workflow["on"]["schedule"] == [{"cron": "22 23 * * *"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["concurrency"] == {
        "group": "horizon-daily",
        "cancel-in-progress": "false",
    }
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pages": "write",
    }


def test_workflow_references_only_allowed_long_lived_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) == {
        "AOLIGEI_API_KEY",
        "PUSHPLUS_TOKEN",
    }
    assert "github.token" in text
    assert "PUSHPLUS_SECRET_KEY" not in text
    assert "DEEPSEEK_API_KEY" not in text
    assert text.count("uv run horizon") == 1
    assert "sleep 120" in text
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```powershell
uv run pytest tests/test_github_workflow.py -q
```

Expected: FAIL because the active workflow and cloud config do not exist.

- [ ] **Step 3: Create the cloud config**

Copy `data/config.local.example.json` to `data/config.github-actions.json`, then make these exact delivery changes:

```json
"webhook": {
  "enabled": true,
  "url_env": "HORIZON_WEBHOOK_URL",
  "delivery": "overview",
  "overview_position": "first",
  "platform": "pushplus",
  "layout": "markdown",
  "fallback_layout": "markdown",
  "languages": ["zh", "en"],
  "pushplus": {
    "channel": "clawbot",
    "template": "txt",
    "confirmation": "accepted",
    "message_mode": "bilingual_links",
    "token_env": "PUSHPLUS_TOKEN",
    "secret_key_env": null,
    "status_timeout_seconds": 90,
    "poll_interval_seconds": 2.0
  },
  "headers": ""
}
```

Keep the current approved Aoligei endpoint/model, allowed information sources, focus topics, dual languages, and exact `Xun-2/Horizon` Pages block from the local example.

- [ ] **Step 4: Replace the disabled workflow with the active workflow**

Create `.github/workflows/daily-summary.yml` and remove the `.disabled` file. The workflow must contain this control flow:

```yaml
name: Daily Horizon Summary
run-name: Horizon daily ${{ github.event_name }} #${{ github.run_number }}

on:
  schedule:
    - cron: '22 23 * * *'
  workflow_dispatch:

permissions:
  actions: read
  contents: write
  pages: write

concurrency:
  group: horizon-daily
  cancel-in-progress: false

jobs:
  daily-summary:
    runs-on: ubuntu-latest
    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
      AOLIGEI_API_KEY: ${{ secrets.AOLIGEI_API_KEY }}
      PUSHPLUS_TOKEN: ${{ secrets.PUSHPLUS_TOKEN }}
      HORIZON_GITHUB_TOKEN: ${{ github.token }}
      HORIZON_WEBHOOK_URL: https://www.pushplus.plus/send
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: astral-sh/setup-uv@v6
        with:
          version: '0.11.26'
      - run: uv sync --extra dev
      - id: date
        shell: bash
        run: echo "value=$(TZ=Asia/Shanghai date +%F)" >> "$GITHUB_OUTPUT"
      - id: guard
        shell: bash
        run: |
          decision="$(uv run python scripts/github_actions_recovery.py guard --date '${{ steps.date.outputs.value }}' --exclude-run-id '${{ github.run_id }}')"
          echo "decision=$decision" >> "$GITHUB_OUTPUT"
      - name: Run Horizon with one bounded retry
        if: steps.guard.outputs.decision == 'run'
        shell: bash
        run: |
          for attempt in 1 2; do
            if uv run horizon --hours 24 --config data/config.github-actions.json; then
              exit 0
            fi
            if [ "$attempt" -eq 1 ]; then
              sleep 120
            fi
          done
          exit 1
```

Do not add `peaceiris/actions-gh-pages`; the Horizon `GitHubPagesPublisher` is the single Pages publisher.

- [ ] **Step 5: Run workflow/config contract tests**

Run:

```powershell
uv run pytest tests/test_github_workflow.py tests/test_delivery_config.py -q
```

Expected: PASS and YAML is structurally parsed, not checked by string matching alone.

- [ ] **Step 6: Commit only Task 7 paths**

```powershell
git add -- data/config.github-actions.json .github/workflows/daily-summary.yml .github/workflows/daily-summary.yml.disabled pyproject.toml uv.lock tests/test_github_workflow.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: run horizon daily in github actions"
```

### Task 8: Chinese Setup Guide, Regression Verification, and Real Rollout

**Files:**
- Modify: `docs/local-ai-radar-setup.md`
- Modify: `.env.example` only if comments are needed; never add a cloud secret value.
- Test: all tests under `tests/`

**Interfaces:**
- Consumes: Tasks 1-7 and the approved design document.
- Produces: Chinese operator steps, full local test evidence, one real cloud dispatch, one dedup dispatch, and a re-registered Windows recovery task.

- [ ] **Step 1: Add Chinese cloud setup and recovery instructions**

Document these exact user actions in `docs/local-ai-radar-setup.md`:

1. GitHub repository `Settings -> Secrets and variables -> Actions`.
2. Create repository secrets `AOLIGEI_API_KEY` and `PUSHPLUS_TOKEN`; never add `PUSHPLUS_SECRET_KEY`.
3. Edit the fine-grained PAT for `Xun-2/Horizon` and add `Actions: Read and write` while retaining Contents and Pages write permissions.
4. Explain that GitHub Actions confirms PushPlus acceptance, while local `--test-delivery` verifies final state `2`.
5. Explain the 07:22 cloud schedule, 07:45 Windows fallback, login behavior, and at-least-once duplicate edge case.
6. Show the recovery task reinstall command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -ConfirmCloudWorkflowReady
```

7. Show where to inspect Actions runs, Pages URLs, `logs/cloud-recovery-*.log`, and the Windows task state.

- [ ] **Step 2: Run focused security and contract suites**

Run:

```powershell
uv run pytest tests/test_delivery_config.py tests/test_pushplus_open_api.py tests/test_summarizer.py tests/test_webhook.py tests/test_delivery_pipeline.py tests/test_github_actions.py tests/test_github_actions_recovery.py tests/test_windows_scripts.py tests/test_github_workflow.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 3: Run the full regression suite**

Run:

```powershell
uv run pytest -q
```

Expected: exit code 0 with no failed tests.

- [ ] **Step 4: Run offline local validation and repository safety checks**

Run:

```powershell
uv run python scripts/check_local_setup.py --offline
git check-ignore -v .env data/config.json
git diff --check
git grep -n -E 'AOLIGEI_API_KEY=.+|PUSHPLUS_TOKEN=.+|PUSHPLUS_SECRET_KEY=.+|HORIZON_GITHUB_TOKEN=.+' -- ':!*.example' ':!tests/**'
```

Expected: offline validation passes; both local secret files are ignored; diff check passes; secret assignment scan returns no real assignments.

- [ ] **Step 5: Commit documentation only**

```powershell
git add -- docs/local-ai-radar-setup.md .env.example
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: explain cloud daily recovery setup"
```

If `.env.example` did not need a comment change, omit it from `git add`.

- [ ] **Step 6: Configure GitHub without exposing secrets**

In the GitHub web UI, add the two Actions repository secrets using hidden browser fields. Edit the existing local PAT permissions in the GitHub UI. Do not paste values into chat, command arguments, screenshots, logs, or tracked files.

- [ ] **Step 7: Integrate the implementation to default branch**

After all commits and tests pass, use `superpowers:finishing-a-development-branch`. Merge or create a PR into `main`, then push `main` to `Xun-2/Horizon`; scheduled workflows only run from the default branch.

- [ ] **Step 8: Trigger the first real cloud run and monitor it**

Trigger `Daily Horizon Summary` with `workflow_dispatch`. Wait for completion and verify:

```text
workflow conclusion: success
zh page: HTTP 200
en page: HTTP 200
PushPlus: HTTP 200 with non-empty receipt
WeChat: exactly one ClawBot message containing both links
```

Do not claim final state `2` for this cloud run.

- [ ] **Step 9: Trigger a same-day dedup run**

Trigger `workflow_dispatch` again on the same Beijing date. Verify the guard outputs `skip`, the Horizon step is skipped, and no second WeChat message arrives.

- [ ] **Step 10: Verify local final delivery and reinstall recovery task**

Run the local final-state probe while the current public IP is still in PushPlus safe IP:

```powershell
uv run python scripts/check_local_setup.py --online --test-delivery
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -ConfirmCloudWorkflowReady
```

Expected local probe lines:

```text
Offline configuration check passed
GitHub Pages test page is public
ClawBot request accepted
ClawBot 已送达
Online checks passed
```

Then query `HorizonLocalAIRadar` and verify it is enabled with AtLogOn and daily 07:45 triggers, and its action points to `scripts/run_cloud_recovery.ps1`.

- [ ] **Step 11: Final repository review**

Run:

```powershell
git status --short
git log --oneline -12
```

Confirm every implementation commit contains only its listed task paths. Preserve all unrelated pre-existing working-tree changes.
