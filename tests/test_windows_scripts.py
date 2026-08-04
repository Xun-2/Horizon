import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_horizon.ps1"
RECOVERY_RUNNER = ROOT / "scripts" / "run_cloud_recovery.ps1"
INSTALLER = ROOT / "scripts" / "install_scheduled_task.ps1"
UNINSTALLER = ROOT / "scripts" / "uninstall_scheduled_task.ps1"
SECRET_SETUP = ROOT / "scripts" / "setup_local_secrets.ps1"


def _powershell(script: Path, *args: str, env=None, timeout=20):
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *args,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def _new_logs(before: set[Path]) -> set[Path]:
    log_dir = ROOT / "logs"
    after = set(log_dir.glob("horizon-*.log")) if log_dir.exists() else set()
    return after - before


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


def _copy_secret_setup(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy2(SECRET_SETUP, scripts_dir / SECRET_SETUP.name)
    return scripts_dir / SECRET_SETUP.name


def _run_secret_setup(
    tmp_path: Path,
    *,
    aoligei_token: str,
    pushplus_token: str,
    pushplus_secret: str = "valid-pushplus-open-api-secret",
    github_token: str = "valid-github-token",
) -> subprocess.CompletedProcess[str]:
    setup_script = _copy_secret_setup(tmp_path)
    environment = dict(
        os.environ,
        HORIZON_TEST_AOLIGEI_TOKEN=aoligei_token,
        HORIZON_TEST_PUSHPLUS_TOKEN=pushplus_token,
        HORIZON_TEST_PUSHPLUS_SECRET=pushplus_secret,
        HORIZON_TEST_GITHUB_TOKEN=github_token,
        HORIZON_TEST_SETUP_SCRIPT=str(setup_script),
    )
    command = """
$global:SecretResponses = [Collections.Generic.Queue[string]]::new()
$global:SecretResponses.Enqueue($env:HORIZON_TEST_AOLIGEI_TOKEN)
$global:SecretResponses.Enqueue($env:HORIZON_TEST_PUSHPLUS_TOKEN)
$global:SecretResponses.Enqueue($env:HORIZON_TEST_PUSHPLUS_SECRET)
$global:SecretResponses.Enqueue($env:HORIZON_TEST_GITHUB_TOKEN)
function global:Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    $value = $global:SecretResponses.Dequeue()
    if (-not $AsSecureString) {
        return $value
    }
    if ($value.Length -eq 0) {
        return [Security.SecureString]::new()
    }
    return ConvertTo-SecureString $value -AsPlainText -Force
}
& $env:HORIZON_TEST_SETUP_SCRIPT
""".strip()
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )


def test_secret_setup_rejects_empty_aoligei_token_without_writing_env(tmp_path):
    result = _run_secret_setup(
        tmp_path,
        aoligei_token="",
        pushplus_token="valid-pushplus-token",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "AOLIGEI_API_KEY" in output
    assert "empty" in output.lower()
    assert not (tmp_path / ".env").exists()


def test_secret_setup_rejects_line_breaks_without_echoing_value(tmp_path):
    result = _run_secret_setup(
        tmp_path,
        aoligei_token="first-secret-line\nsecond-secret-line",
        pushplus_token="valid-pushplus-token",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "AOLIGEI_API_KEY" in output
    assert "single line" in output.lower()
    assert "first-secret-line" not in output
    assert "second-secret-line" not in output
    assert not (tmp_path / ".env").exists()


def test_secret_setup_writes_all_delivery_keys_without_echoing_values(tmp_path):
    result = _run_secret_setup(
        tmp_path,
        aoligei_token="test-aoligei-secret",
        pushplus_token="test-pushplus-token",
        pushplus_secret="test-pushplus-secret-key",
        github_token="test-github-secret",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    env_text = (tmp_path / ".env").read_text(encoding="utf-8-sig")
    for name in (
        "AOLIGEI_API_KEY",
        "PUSHPLUS_TOKEN",
        "PUSHPLUS_SECRET_KEY",
        "HORIZON_GITHUB_TOKEN",
        "HORIZON_WEBHOOK_URL",
    ):
        assert f"{name}=" in env_text
    for value in (
        "test-aoligei-secret",
        "test-pushplus-token",
        "test-pushplus-secret-key",
        "test-github-secret",
    ):
        assert value not in output


def test_runner_uses_repo_working_directory_cache_and_expected_command(tmp_path):
    capture = tmp_path / "capture.json"
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
    environment = dict(os.environ, HORIZON_TEST_CAPTURE=str(capture))
    log_dir = ROOT / "logs"
    before = set(log_dir.glob("horizon-*.log")) if log_dir.exists() else set()

    result = _powershell(RUNNER, "-UvExecutable", str(fake_uv), env=environment)
    created_logs = _new_logs(before)
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(capture.read_text(encoding="utf-8-sig"))
        assert Path(payload["working_directory"]) == ROOT
        assert Path(payload["uv_cache_dir"]) == ROOT / ".uv" / "cache"
        assert payload["arguments"] == ["run", "horizon", "--hours", "24"]
        assert len(created_logs) == 1
    finally:
        for path in created_logs:
            path.unlink(missing_ok=True)


def test_runner_preserves_success_when_command_writes_to_stderr(tmp_path):
    fake_uv_script = tmp_path / "fake_uv.py"
    fake_uv_script.write_text(
        """
from rich.console import Console

console = Console(stderr=True)
console.print("normal progress")
console.print()
""".strip(),
        encoding="utf-8",
    )


    fake_uv = tmp_path / "fake-uv.cmd"
    fake_uv.write_text(
        f'@echo off\n"{sys.executable}" "{fake_uv_script}" %*\nexit /b %errorlevel%\n',
        encoding="utf-8",
    )
    log_dir = ROOT / "logs"
    before = set(log_dir.glob("horizon-*.log")) if log_dir.exists() else set()

    result = _powershell(RUNNER, "-UvExecutable", str(fake_uv))
    created_logs = _new_logs(before)
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(created_logs) == 1
        log_text = next(iter(created_logs)).read_text(encoding="utf-8-sig")
        assert "normal progress" in log_text
        assert "System.Management.Automation.RemoteException" not in log_text
        assert "finished with exit code 0" in log_text
    finally:
        for path in created_logs:
            path.unlink(missing_ok=True)


def test_runner_exclusive_lock_rejects_second_instance(tmp_path):
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
        str(RUNNER),
        "-UvExecutable",
        str(fake_uv),
    ]
    log_dir = ROOT / "logs"
    before = set(log_dir.glob("horizon-*.log")) if log_dir.exists() else set()
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
        assert started.exists(), "first runner did not reach the fake uv command"

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
        for path in _new_logs(before):
            path.unlink(missing_ok=True)
        (ROOT / "logs" / "horizon.lock").unlink(missing_ok=True)


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


def test_uninstaller_whatif_only_reports_exact_task():
    result = _powershell(UNINSTALLER, "-WhatIf")

    assert result.returncode == 0, result.stdout + result.stderr
    contract = json.loads(result.stdout.strip())
    assert contract == {
        "task_name": "HorizonLocalAIRadar",
        "action": "unregister",
    }
