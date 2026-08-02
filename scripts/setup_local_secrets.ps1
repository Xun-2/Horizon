[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'

function Read-SecretText {
    param([Parameter(Mandatory = $true)][string]$Prompt)

    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "$Prompt cannot be empty."
        }
        if ($value.Contains("`r") -or $value.Contains("`n")) {
            throw "$Prompt must be a single line."
        }
        return $value
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

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

Write-Host "Local secrets saved to $envPath"
