import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts import check_local_setup
from src.services.pushplus import PushPlusDeliveryReport, PushPlusDeliveryState


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_local_setup.py"
CONFIG = ROOT / "data" / "config.local.example.json"


def _environment(*, include_secrets: bool) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        not in {
            "AOLIGEI_API_KEY",
            "PUSHPLUS_TOKEN",
            "PUSHPLUS_SECRET_KEY",
            "HORIZON_GITHUB_TOKEN",
            "HORIZON_WEBHOOK_URL",
        }
    }
    if include_secrets:
        environment.update(
            {
                "AOLIGEI_API_KEY": "test-aoligei-secret",
                "PUSHPLUS_TOKEN": "test-pushplus-secret",
                "PUSHPLUS_SECRET_KEY": "test-pushplus-open-api-secret",
                "HORIZON_GITHUB_TOKEN": "test-github-secret",
                "HORIZON_WEBHOOK_URL": "https://www.pushplus.plus/send",
            }
        )
    return environment


def _run(
    *args: str,
    include_secrets: bool = True,
    env_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(CONFIG),
            "--env-file",
            str(env_file or ROOT / "tests" / "nonexistent.env"),
            *args,
        ],
        cwd=ROOT,
        env=_environment(include_secrets=include_secrets),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )


def test_local_example_passes_explicit_offline_check():
    result = _run("--offline")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Offline configuration check passed" in result.stdout
    assert "test-aoligei-secret" not in result.stdout + result.stderr
    assert "test-pushplus-secret" not in result.stdout + result.stderr


def test_default_check_is_offline():
    result = _run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Offline configuration check passed" in result.stdout
    assert "Online checks" not in result.stdout + result.stderr


def test_offline_check_loads_utf8_bom_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AOLIGEI_API_KEY=test-aoligei-secret",
                "PUSHPLUS_TOKEN=test-pushplus-secret",
                "PUSHPLUS_SECRET_KEY=test-pushplus-open-api-secret",
                "HORIZON_GITHUB_TOKEN=test-github-secret",
                "HORIZON_WEBHOOK_URL=https://www.pushplus.plus/send",
            ]
        ),
        encoding="utf-8-sig",
    )

    result = _run("--offline", include_secrets=False, env_file=env_file)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Offline configuration check passed" in result.stdout


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


def test_pushplus_test_requires_explicit_online_mode():
    result = _run("--test-pushplus")

    assert result.returncode != 0
    assert "--test-pushplus requires --online" in result.stderr


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


def test_legacy_openai_key_does_not_satisfy_aoligei_token_requirement():
    environment = _environment(include_secrets=False)
    environment.update(
        {
            "OPENAI_API_KEY": "legacy-openai-key",
            "PUSHPLUS_TOKEN": "test-pushplus-secret",
            "PUSHPLUS_SECRET_KEY": "test-pushplus-open-api-secret",
            "HORIZON_GITHUB_TOKEN": "test-github-secret",
            "HORIZON_WEBHOOK_URL": "https://www.pushplus.plus/send",
        }
    )

    config, issues = check_local_setup.check_offline(CONFIG, environment)

    assert config is None
    assert issues == ["Missing environment variable: AOLIGEI_API_KEY"]


def test_local_contract_rejects_legacy_api_key_env_name(tmp_path):
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw["ai"]["api_key_env"] = "OPENAI_API_KEY"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    environment = _environment(include_secrets=True)
    environment["OPENAI_API_KEY"] = "legacy-openai-key"

    config, issues = check_local_setup.check_offline(config_path, environment)

    assert config is not None
    assert "AI key environment variable must be AOLIGEI_API_KEY" in issues


def test_online_check_uses_orchestrator_time_window(monkeypatch):
    environment = _environment(include_secrets=True)
    config, issues = check_local_setup.check_offline(CONFIG, environment)
    assert not issues
    expected_since = object()
    observed_since = []

    class FakeClient:
        async def complete(self, system, user, max_tokens):
            if "json" not in f"{system} {user}".lower():
                raise RuntimeError("json response format requires a JSON prompt")
            return '{"status":"ok"}'

    class FakeOrchestrator:
        def __init__(self, config, storage):
            self.last_fetch_report = None

        def _determine_time_window(self):
            return expected_since

        async def fetch_all_sources(self, since):
            observed_since.append(since)
            return []

    monkeypatch.setattr(check_local_setup, "create_ai_client", lambda config: FakeClient())
    monkeypatch.setattr(check_local_setup, "HorizonOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(check_local_setup, "StorageManager", lambda **kwargs: object())

    online_issues = asyncio.run(check_local_setup._check_online(config, CONFIG))

    assert online_issues == []
    assert observed_since == [expected_since]


def test_online_check_reports_http_status_without_exception_message(monkeypatch):
    environment = _environment(include_secrets=True)
    config, issues = check_local_setup.check_offline(CONFIG, environment)
    assert not issues
    secret = "sk-secret-must-not-appear"

    class AuthenticationFailure(Exception):
        status_code = 401

    class FailingClient:
        async def complete(self, system, user, max_tokens):
            raise AuthenticationFailure(f"Invalid token: {secret}")

    class FakeOrchestrator:
        def __init__(self, config, storage):
            self.last_fetch_report = None

        def _determine_time_window(self):
            return object()

        async def fetch_all_sources(self, since):
            return []

    monkeypatch.setattr(
        check_local_setup, "create_ai_client", lambda config: FailingClient()
    )
    monkeypatch.setattr(check_local_setup, "HorizonOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(check_local_setup, "StorageManager", lambda **kwargs: object())

    online_issues = asyncio.run(check_local_setup._check_online(config, CONFIG))
    output = "\n".join(online_issues)

    assert "AuthenticationFailure" in output
    assert "HTTP 401" in output
    assert secret not in output
