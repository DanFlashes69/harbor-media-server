$startupTaskName = 'Harbor NAS Localhost Proxy'
$watchdogTaskName = 'Harbor NAS Localhost Proxy Watchdog'
$supervisorPath = 'D:\harbor-media-server\scripts\nas_localhost_proxy_supervisor.py'
$startupFolder = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$startupLauncher = Join-Path $startupFolder 'Harbor NAS Localhost Proxy.vbs'
$staleLaunchers = @(
  (Join-Path $startupFolder 'Harbor NAS Localhost Proxy.cmd'),
  (Join-Path $startupFolder 'Harbor-NAS-Localhost-Proxy.cmd')
)

$tasks = @($startupTaskName, $watchdogTaskName)
foreach ($taskName in $tasks) {
  try {
    schtasks /Delete /TN $taskName /F | Out-Null
  } catch {
  }
}

$pythonwCandidates = @(
  'C:\Python314\pythonw.exe',
  'C:\Python313\pythonw.exe',
  'C:\Python312\pythonw.exe'
)

$pythonwPath = $pythonwCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonwPath) {
  $pythonwPath = 'pythonw.exe'
}

if (-not (Test-Path -LiteralPath $startupFolder)) {
  New-Item -ItemType Directory -Path $startupFolder -Force | Out-Null
}

foreach ($staleLauncher in $staleLaunchers) {
  if (Test-Path -LiteralPath $staleLauncher) {
    Remove-Item -LiteralPath $staleLauncher -Force -ErrorAction SilentlyContinue
  }
}

$runnerCommand = "`"$pythonwPath`" `"$supervisorPath`""
$escapedRunnerCommand = $runnerCommand.Replace('"', '""')
$launcherScript = @"
Set shell = CreateObject("WScript.Shell")
shell.Run "$escapedRunnerCommand", 0
"@

Set-Content -LiteralPath $startupLauncher -Value $launcherScript -Encoding ASCII

Write-Output "Installed startup launcher: $startupLauncher"
Write-Output "Removed task: $watchdogTaskName"
