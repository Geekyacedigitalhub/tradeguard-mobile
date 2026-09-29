$ErrorActionPreference = "Stop"

$BridgeDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "TradeGuard MT5 Bridge"

$Action = New-ScheduledTaskAction -Execute "python.exe" -Argument "-u `"$BridgeDir\bridge.py`"" -WorkingDirectory $BridgeDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Force

Write-Host "TradeGuard MT5 Bridge startup task installed."
Write-Host "It will start when this Windows user logs in."
