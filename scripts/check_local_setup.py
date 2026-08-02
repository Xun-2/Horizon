"""Validate the local AI radar configuration with opt-in network probes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.client import create_ai_client  # noqa: E402
from src.environment import load_horizon_dotenv  # noqa: E402
from src.models import Config  # noqa: E402
from src.orchestrator import HorizonOrchestrator  # noqa: E402
from src.services.github_pages import GitHubPagesPublisher  # noqa: E402
from src.services.pushplus import (  # noqa: E402
    PushPlusClawBotClient,
    PushPlusDeliveryState,
)
from src.storage.manager import StorageManager  # noqa: E402


ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
FORBIDDEN_SOURCES = ("twitter", "openbb", "gdelt", "google_news")


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _required_environment(raw: dict[str, Any]) -> set[str]:
    required = {
        match.group(1)
        for value in _walk_strings(raw)
        for match in ENV_REFERENCE.finditer(value)
    }
    ai = raw.get("ai") or {}
    if ai.get("provider") != "ollama" and ai.get("api_key_env"):
        required.add(str(ai["api_key_env"]))
    webhook = raw.get("webhook") or {}
    if webhook.get("enabled") and webhook.get("url_env"):
        required.add(str(webhook["url_env"]))
    pushplus = webhook.get("pushplus") or {}
    for key in ("token_env", "secret_key_env"):
        if pushplus.get(key):
            required.add(str(pushplus[key]))
    github_pages = raw.get("github_pages") or {}
    if github_pages.get("enabled") and github_pages.get("token_env"):
        required.add(str(github_pages["token_env"]))
    return required


def _expand_environment(value: Any, environment: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return ENV_REFERENCE.sub(
            lambda match: environment.get(match.group(1), match.group(0)), value
        )
    if isinstance(value, dict):
        return {key: _expand_environment(item, environment) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_environment(item, environment) for item in value]
    return value


def _contract_issues(config: Config) -> list[str]:
    issues: list[str] = []
    if config.ai.provider.value != "openai":
        issues.append("AI provider must be openai")
    if config.ai.base_url != "https://aoligei.cc/v1":
        issues.append("AI base URL must match the approved endpoint")
    if config.ai.model != "gpt-5.6-sol":
        issues.append("AI model must be gpt-5.6-sol")
    if config.ai.api_key_env != "AOLIGEI_API_KEY":
        issues.append("AI key environment variable must be AOLIGEI_API_KEY")
    if config.ai.languages != ["zh", "en"]:
        issues.append("AI languages must be zh and en")
    if config.collection.time_window_hours != 24:
        issues.append("Collection window must be 24 hours")
    if config.filtering.focus_topics != ["AI 模型", "创新技术", "模型安全"]:
        issues.append("Focus topics must match the three approved topics")
    if config.filtering.ai_score_threshold != 6.5:
        issues.append("AI score threshold must be 6.5")
    if config.digest.max_items != 12:
        issues.append("Digest maximum must be 12 items")
    expected_groups = {"ai-models", "innovation-tech", "model-security"}
    if set(config.digest.category_groups) != expected_groups or any(
        group.limit != 4 for group in config.digest.category_groups.values()
    ):
        issues.append("Digest must limit each approved topic to 4 items")

    for source_name in FORBIDDEN_SOURCES:
        source = getattr(config.sources, source_name)
        if source is not None and source.enabled:
            issues.append(f"Forbidden source is enabled: {source_name}")
    if config.email is not None and config.email.enabled:
        issues.append("Email delivery must remain disabled")

    webhook = config.webhook
    if webhook is None or not webhook.enabled:
        issues.append("PushPlus webhook must be enabled")
    else:
        if webhook.platform != "pushplus":
            issues.append("Webhook platform must be pushplus")
        if webhook.delivery != "overview":
            issues.append("Webhook delivery must be overview")
        if webhook.pushplus is None:
            issues.append("PushPlus ClawBot configuration is required")
        else:
            if webhook.pushplus.channel != "clawbot":
                issues.append("PushPlus channel must be clawbot")
            if webhook.pushplus.template != "txt":
                issues.append("PushPlus template must be txt")

    github_pages = config.github_pages
    if github_pages is None or not github_pages.enabled:
        issues.append("GitHub Pages must be enabled")
    elif (
        github_pages.repository != "Xun-2/Horizon"
        or github_pages.branch != "gh-pages"
        or github_pages.site_url != "https://xun-2.github.io/Horizon"
    ):
        issues.append("GitHub Pages configuration must use the approved Horizon site")
    return issues


def check_offline(
    config_path: Path, environment: Mapping[str, str]
) -> tuple[Config | None, list[str]]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ["Configuration file is missing or invalid JSON"]

    missing = sorted(
        name for name in _required_environment(raw) if not environment.get(name)
    )
    if missing:
        return None, [f"Missing environment variable: {name}" for name in missing]

    try:
        config = Config.model_validate(_expand_environment(raw, environment))
    except Exception:
        return None, ["Configuration does not match the Horizon schema"]
    return config, _contract_issues(config)


def _safe_probe_error(component: str, exc: Exception) -> str:
    details = [type(exc).__name__]
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        details.append(f"HTTP {status_code}")
    return f"{component} probe failed ({', '.join(details)})"


async def _check_online(config: Config, config_path: Path) -> list[str]:
    issues: list[str] = []
    try:
        client = create_ai_client(config.ai)
        response = await client.complete(
            "Return only a JSON object with the string field status set to ok.",
            'Connectivity check. Expected JSON: {"status":"ok"}',
            max_tokens=16,
        )
        payload = json.loads(response)
        if payload.get("status") != "ok":
            issues.append("Model probe returned an unexpected response")
    except Exception as exc:
        issues.append(_safe_probe_error("Model endpoint", exc))

    try:
        storage = StorageManager(
            data_dir=str(config_path.parent), config_path=str(config_path)
        )
        orchestrator = HorizonOrchestrator(config, storage)
        await orchestrator.fetch_all_sources(orchestrator._determine_time_window())
        report = orchestrator.last_fetch_report
        if report and any(outcome.status == "failure" for outcome in report.outcomes):
            issues.append("One or more enabled source probes failed")
    except Exception as exc:
        issues.append(_safe_probe_error("Source", exc))
    return issues


async def _check_pushplus(config: Config) -> list[str]:
    try:
        report = await _build_clawbot_client(config).send_and_wait(
            "Horizon local setup test",
            "Horizon ClawBot connectivity and final-delivery check.",
        )
    except Exception as exc:
        return [_safe_probe_error("PushPlus", exc)]
    if report.state != PushPlusDeliveryState.DELIVERED:
        return [f"PushPlus delivery probe ended in state: {report.state.value}"]
    return []


def _build_page_publisher(config: Config) -> GitHubPagesPublisher:
    if config.github_pages is None:
        raise ValueError("GitHub Pages is not configured")
    return GitHubPagesPublisher(
        config.github_pages,
        os.environ.get(config.github_pages.token_env, ""),
    )


def _build_clawbot_client(config: Config) -> PushPlusClawBotClient:
    if config.webhook is None or config.webhook.pushplus is None:
        raise ValueError("PushPlus ClawBot is not configured")
    pushplus = config.webhook.pushplus
    return PushPlusClawBotClient(
        os.environ.get(config.webhook.url_env or "", ""),
        os.environ.get(pushplus.token_env, ""),
        os.environ.get(pushplus.secret_key_env, ""),
        status_timeout_seconds=pushplus.status_timeout_seconds,
        poll_interval_seconds=pushplus.poll_interval_seconds,
    )


async def _check_delivery(config: Config) -> list[str]:
    try:
        public_url = await _build_page_publisher(config).publish_health_check()
    except Exception as exc:
        return [_safe_probe_error("GitHub Pages", exc)]

    try:
        report = await _build_clawbot_client(config).send_and_wait(
            "Horizon delivery check",
            f"Horizon GitHub Pages health check: {public_url}",
        )
    except Exception as exc:
        return [_safe_probe_error("PushPlus", exc)]
    if report.state != PushPlusDeliveryState.DELIVERED:
        return [f"PushPlus delivery probe ended in state: {report.state.value}"]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "data" / "config.json")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Run local checks only")
    mode.add_argument("--online", action="store_true", help="Probe the model and sources")
    parser.add_argument(
        "--test-pushplus",
        action="store_true",
        help="Send one PushPlus test message; requires --online",
    )
    parser.add_argument(
        "--test-delivery",
        action="store_true",
        help="Publish a Pages health check and verify final ClawBot delivery; requires --online",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.test_pushplus and not args.online:
        parser.error("--test-pushplus requires --online")
    if args.test_delivery and not args.online:
        parser.error("--test-delivery requires --online")

    load_horizon_dotenv(args.env_file, override=False)
    config, issues = check_offline(args.config, os.environ)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1

    print("Offline configuration check passed")
    if not args.online:
        return 0

    online_issues = asyncio.run(_check_online(config, args.config))
    if args.test_pushplus:
        online_issues.extend(asyncio.run(_check_pushplus(config)))
    if args.test_delivery:
        online_issues.extend(asyncio.run(_check_delivery(config)))
    if online_issues:
        for issue in online_issues:
            print(f"ERROR: {issue}")
        return 1
    print("Online checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
