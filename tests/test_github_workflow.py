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
