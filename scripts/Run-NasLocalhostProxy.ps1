$scriptPath = 'D:\harbor-media-server\scripts\nas_localhost_proxy.py'
$logDir = 'D:\harbor-media-server\logs'
$stdoutLog = Join-Path $logDir 'nas_localhost_proxy.out.log'
$stderrLog = Join-Path $logDir 'nas_localhost_proxy.err.log'
$testPorts = @(3000, 32400, 5055, 8081)

if (-not (Test-Path -LiteralPath $logDir)) {
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Get-ProxyProcesses {
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*nas_localhost_proxy.py*" }
}

function Test-ProxyListening {
  param(
    [int[]]$Ports
  )

  foreach ($port in $Ports) {
    try {
      $connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction Stop
      if ($connection) {
        return $true
      }
    } catch {
    }
  }

  return $false
}

function Get-PythonExecutable {
  $candidates = @(
    'C:\Python314\pythonw.exe',
    'C:\Python313\pythonw.exe',
    'C:\Python312\pythonw.exe',
    'C:\Python314\python.exe',
    'C:\Python313\python.exe',
    'C:\Python312\python.exe'
  )

  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }

  $python = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($python) {
    return $python.Source
  }

  throw 'python.exe was not found for Harbor NAS localhost proxy startup.'
}

$running = Get-ProxyProcesses
$listening = Test-ProxyListening -Ports $testPorts

if ($running -and $listening) {
  exit 0
}

if ($running) {
  foreach ($proc in $running) {
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    } catch {
    }
  }
  Start-Sleep -Seconds 2
}

$python = Get-PythonExecutable
$arguments = "`"$scriptPath`""

if ($python -like '*pythonw.exe') {
  Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WindowStyle Hidden
} else {
  Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog
}
