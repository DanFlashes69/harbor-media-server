$runnerPath = 'D:\harbor-media-server\scripts\Run-NasLocalhostProxy.ps1'
$testPorts = @(3000, 32400, 5055, 8081)

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

$running = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*nas_localhost_proxy.py*" }

$listening = Test-ProxyListening -Ports $testPorts

if (-not $running -or -not $listening) {
  & $runnerPath
}
