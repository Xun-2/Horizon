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
