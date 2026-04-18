[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$ManifestRoot = 'D:\harbor-media-server\synology-parity',
    [switch]$IncludeDownloads,
    [int]$TimestampToleranceSeconds = 2,
    [bool]$IgnoreTimestamps = $true
)

$ErrorActionPreference = 'Stop'
$baseManifestRoot = $ManifestRoot
$runId = '{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $PID
$ManifestRoot = Join-Path $baseManifestRoot $runId
New-Item -ItemType Directory -Force -Path $ManifestRoot | Out-Null

function New-Manifest {
    param(
        [string]$RootPath,
        [string]$OutputPath
    )

    $resolved = Resolve-Path -LiteralPath $RootPath
    $root = $resolved.ProviderPath.TrimEnd('\', '/')
    $rootWithSeparator = $root + [System.IO.Path]::DirectorySeparatorChar
    $files = Get-ChildItem -LiteralPath $root -Recurse -Force -File -ErrorAction SilentlyContinue |
        Sort-Object FullName |
        ForEach-Object {
            $fullName = $_.FullName
            if ($fullName.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
                $relativePath = $fullName.Substring($rootWithSeparator.Length)
            }
            elseif ($fullName.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
                $relativePath = $fullName.Substring($root.Length).TrimStart('\', '/')
            }
            else {
                $relativePath = Split-Path -Leaf $fullName
            }

            [pscustomobject]@{
                RelativePath = $relativePath
                Length = $_.Length
                LastWriteUtc = $_.LastWriteTimeUtc.ToString('o')
            }
        }

    $files | ConvertTo-Json -Depth 5 | Set-Content -Path $OutputPath -Encoding UTF8
    return $files
}

function Compare-Manifests {
    param(
        [string]$Name,
        [object[]]$SourceManifest,
        [object[]]$DestManifest,
        [int]$TimestampToleranceSeconds,
        [bool]$IgnoreTimestamps
    )

    $sourceMap = @{}
    foreach ($item in $SourceManifest) {
        $sourceMap[$item.RelativePath] = $item
    }

    $destMap = @{}
    foreach ($item in $DestManifest) {
        $destMap[$item.RelativePath] = $item
    }

    $missing = @()
    $mismatch = @()

    foreach ($key in $sourceMap.Keys) {
        if (-not $destMap.ContainsKey($key)) {
            $missing += $key
            continue
        }

        $src = $sourceMap[$key]
        $dst = $destMap[$key]
        $timestampMismatch = $false
        if (-not $IgnoreTimestamps) {
            try {
                $srcTime = [datetime]::Parse($src.LastWriteUtc)
                $dstTime = [datetime]::Parse($dst.LastWriteUtc)
                $timestampMismatch = [math]::Abs(($srcTime - $dstTime).TotalSeconds) -gt $TimestampToleranceSeconds
            }
            catch {
                $timestampMismatch = $src.LastWriteUtc -ne $dst.LastWriteUtc
            }
        }

        if ($src.Length -ne $dst.Length -or $timestampMismatch) {
            $mismatch += [pscustomobject]@{
                RelativePath = $key
                SourceLength = $src.Length
                DestLength = $dst.Length
                SourceLastWriteUtc = $src.LastWriteUtc
                DestLastWriteUtc = $dst.LastWriteUtc
            }
        }
    }

    $extra = @()
    foreach ($key in $destMap.Keys) {
        if (-not $sourceMap.ContainsKey($key)) {
            $extra += $key
        }
    }

    [pscustomobject]@{
        Name = $Name
        SourceCount = $sourceMap.Count
        DestCount = $destMap.Count
        MissingCount = $missing.Count
        MismatchCount = $mismatch.Count
        ExtraCount = $extra.Count
        Missing = $missing | Sort-Object | Select-Object -First 25
        Mismatch = $mismatch | Select-Object -First 25
        Extra = $extra | Sort-Object | Select-Object -First 25
    }
}

$pairs = @(
    @{ name = 'movies'; src = 'D:\NAS\media\movies'; dst = "\\$NasHost\media\movies" },
    @{ name = 'tv'; src = 'D:\NAS\media\tv'; dst = "\\$NasHost\media\tv" },
    @{ name = 'music'; src = 'D:\NAS\media\music'; dst = "\\$NasHost\media\music" },
    @{ name = 'photos'; src = 'D:\NAS\photos'; dst = "\\$NasHost\photos" }
)

if ($IncludeDownloads) {
    $pairs += @{ name = 'downloads'; src = 'D:\NAS\downloads'; dst = "\\$NasHost\downloads" }
}

$report = foreach ($pair in $pairs) {
    $srcManifestPath = Join-Path $ManifestRoot ("{0}-source.json" -f $pair.name)
    $dstManifestPath = Join-Path $ManifestRoot ("{0}-dest.json" -f $pair.name)

    $srcManifest = New-Manifest -RootPath $pair.src -OutputPath $srcManifestPath
    $dstManifest = New-Manifest -RootPath $pair.dst -OutputPath $dstManifestPath
    Compare-Manifests -Name $pair.name -SourceManifest $srcManifest -DestManifest $dstManifest -TimestampToleranceSeconds $TimestampToleranceSeconds -IgnoreTimestamps $IgnoreTimestamps
}

$reportPath = Join-Path $ManifestRoot 'parity-report.json'
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
$report

