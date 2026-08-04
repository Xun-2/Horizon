from pathlib import Path
from types import SimpleNamespace

import pytest

from src import main as main_module
from src.orchestrator import DailyDeliveryError


def test_missing_custom_config_reports_requested_path(monkeypatch, tmp_path):
    config_path = tmp_path / "custom" / "horizon.json"

    class MissingConfigStorage:
        def __init__(self, data_dir, config_path):
            self.config_path = Path(config_path)

        def load_config(self):
            raise FileNotFoundError

    output = []
    monkeypatch.setattr(main_module, "StorageManager", MissingConfigStorage)
    monkeypatch.setattr(main_module, "configure_logging", lambda console: None)
    monkeypatch.setattr(
        main_module,
        "console",
        SimpleNamespace(
            print=lambda *args, **kwargs: output.append(" ".join(map(str, args)))
        ),
    )
    monkeypatch.setattr("sys.argv", ["horizon", "--config", str(config_path)])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    rendered = "\n".join(output)
    assert exc_info.value.code == 1
    assert str(config_path) in rendered
    assert "horizon-wizard" not in rendered


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
