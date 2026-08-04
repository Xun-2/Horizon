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
