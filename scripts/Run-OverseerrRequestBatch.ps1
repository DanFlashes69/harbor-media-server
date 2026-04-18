$ErrorActionPreference = 'Stop'

$python = 'python'
$repoRoot = 'D:\harbor-media-server'
$workDir = Join-Path $repoRoot 'reports\overseerr-request-tool'

if (-not (Test-Path -LiteralPath $workDir)) {
    New-Item -ItemType Directory -Path $workDir | Out-Null
}

$masterJson = Join-Path $workDir 'Overseerr_ReRequest_Mega_List.json'
$masterTxt = Join-Path $workDir 'Overseerr_ReRequest_Mega_List.txt'
$cleanJson = Join-Path $workDir 'Overseerr_ReRequest_Final_Cleaned.json'
$reviewJson = Join-Path $workDir 'Overseerr_ReRequest_Final_Cleaned_overseerr_review.json'

$refreshScript = Join-Path $repoRoot 'scripts\refresh_overseerr_master_list.py'
$buildScript = Join-Path $repoRoot 'scripts\build_cleaned_rerequest_list.py'
$prepareScript = Join-Path $repoRoot 'scripts\prepare_overseerr_request_review.py'
$openScript = Join-Path $repoRoot 'scripts\open_overseerr_request_batch.py'
$pruneScript = Join-Path $repoRoot 'scripts\prune_dead_qbit_entries.py'

& $python $pruneScript
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python $refreshScript --output-json $masterJson --output-txt $masterTxt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python $buildScript --master-json $masterJson --output-json $cleanJson --output-txt (Join-Path $workDir 'Overseerr_ReRequest_Final_Cleaned.txt')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python $prepareScript $cleanJson --output-dir $workDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python $openScript $reviewJson --count 12 --min-confidence medium --include-available
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
