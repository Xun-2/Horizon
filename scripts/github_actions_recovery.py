"""Guard or recover the Horizon daily GitHub Actions workflow."""

import argparse
import asyncio
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    load_dotenv(
        dotenv_path=ROOT / ".env",
        override=False,
        encoding="utf-8-sig",
    )
    try:
        args = _parser().parse_args(argv)
        return asyncio.run(async_main(args))
    except (Exception, KeyboardInterrupt) as exc:
        print(_redact(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
