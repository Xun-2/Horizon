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
