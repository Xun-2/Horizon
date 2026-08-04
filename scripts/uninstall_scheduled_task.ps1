[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'HorizonLocalAIRadar'

if ($WhatIfPreference) {
    [ordered]@{
        task_name = $taskName
        action = 'unregister'
    } | ConvertTo-Json -Compress
    exit 0
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task '$taskName' is not installed."
    exit 0
}

if ($PSCmdlet.ShouldProcess($taskName, 'Unregister Horizon scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Scheduled task '$taskName' removed."
}
