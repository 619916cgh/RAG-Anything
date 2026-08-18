[CmdletBinding()]
param(
    [ValidateSet('up','bootstrap','query','collect','upload-diagnostic','down')][string]$Phase = 'up',
    [string]$RunDirectory = '',
    [string]$AppImage = 'raganything-staging-media-app:20260818-fix5',
    [ValidateRange(1,1)][int]$Users = 1,
    [ValidateRange(1,20)][int]$Attempts = 10
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$compose = Join-Path $root 'tests/perf/compose.query.perf.yml'
$python = Join-Path $root '.venv/Scripts/python.exe'

function Assert-RunPath([string]$Path, [bool]$MustExist) {
    $full = [IO.Path]::GetFullPath($Path)
    $relative = [IO.Path]::GetRelativePath($tempRoot, $full)
    if ($relative -eq '.' -or $relative.StartsWith('..') -or [IO.Path]::IsPathRooted($relative)) {
        throw 'RunDirectory must be a descendant of the system temporary directory.'
    }
    if ($MustExist -and -not (Test-Path -LiteralPath $full -PathType Container)) { throw 'RunDirectory does not exist.' }
    return $full
}

function New-Secret { [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant() }
function New-Password { 'P!' + (New-Secret) + 'a9' }
function Read-PerfEnv([string]$Path) {
    $values = @{}
    Get-Content -LiteralPath $Path | ForEach-Object { $key,$value = $_ -split '=',2; if ($key) { $values[$key] = $value } }
    return $values
}
function Read-Manifest([string]$Run) {
    $path = Join-Path $Run 'manifest.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'No manifest exists for this run.' }
    return Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
}
function Assert-LowResourceHost {
    $os = Get-CimInstance Win32_OperatingSystem
    $ram = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    $disk = [math]::Round((Get-PSDrive -Name C).Free / 1GB, 2)
    if ($ram -lt 2 -or $disk -lt 20) { throw "Low-resource gate failed: freeRamGiB=$ram freeDiskGiB=$disk; need >=2 GiB RAM and >=20 GiB disk." }
    $context = (docker context show).Trim()
    if ($context -ne 'desktop-linux') { throw "Refusing non-isolated Docker context '$context'." }
    docker image inspect $AppImage *> $null
    if ($LASTEXITCODE -ne 0) { throw 'AppImage must already exist locally; this profile never builds or pulls images.' }
}
function Assert-UploadHeadroom {
    $ram = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)
    if ($ram -lt 3.5) {
        throw "Upload diagnostic gate failed: freeRamGiB=$ram; need >=3.5 GiB after query-only startup before a Worker can be launched."
    }
}
function Assert-OwnedResources($Manifest) {
    $ids = @(docker ps -aq --filter "label=com.docker.compose.project=$($Manifest.project)")
    foreach ($id in $ids) {
        if (-not $id) { continue }
        $labels = docker inspect $id --format '{{json .Config.Labels}}' | ConvertFrom-Json
        if ($labels.'com.docker.compose.project' -ne $Manifest.project -or $labels.'raganything.perf.run-id' -ne $Manifest.run_id) {
            throw 'Refusing cleanup because a container ownership label does not match this manifest.'
        }
    }
}

if (-not $RunDirectory) {
    if ($Phase -ne 'up') { throw 'RunDirectory is required after the initial up phase.' }
    $RunDirectory = Join-Path $tempRoot ('raganything-perf-' + [Guid]::NewGuid().ToString('N'))
}
$run = Assert-RunPath $RunDirectory ($Phase -ne 'up')
$envFile = Join-Path $run 'compose.env'

switch ($Phase) {
    'up' {
        if (Test-Path -LiteralPath $run) { throw 'Generated run directory already exists.' }
        Assert-LowResourceHost
        New-Item -ItemType Directory -Path $run | Out-Null
        Copy-Item -LiteralPath (Join-Path $root 'tests/perf/mock_provider.py') -Destination (Join-Path $run 'mock_provider.py')
        Copy-Item -LiteralPath (Join-Path $root 'server.py') -Destination (Join-Path $run 'server.py')
        Copy-Item -LiteralPath (Join-Path $root 'raganything/runtime_metrics.py') -Destination (Join-Path $run 'runtime_metrics.py')
        $runId = [IO.Path]::GetFileName($run).Replace('raganything-perf-','')
        $project = ('ragperf-' + $runId).ToLowerInvariant()
        $port = Get-Random -Minimum 18080 -Maximum 28080
        $database = 'perf_' + $runId.Substring(0,12)
        $password = New-Secret
        @(
            "PERF_RUN_DIR=$run", "PERF_RUN_ID=$runId", "PERF_APP_IMAGE=$AppImage",
            'POSTGRES_USER=perf', "POSTGRES_PASSWORD=$password", "POSTGRES_DATABASE=$database",
            "DATABASE_URL=postgresql://perf:$password@postgres:5432/$database",
            "JWT_SECRET=$(New-Secret)", "JWT_REFRESH_SECRET=$(New-Secret)",
            'DEFAULT_ADMIN_USERNAME=perf_admin', "DEFAULT_ADMIN_PASSWORD=$(New-Password)",
            "PERF_HTTP_PORT=$port", 'PERF_EMBEDDING_DIM=1536', 'PERF_MOCK_TTFT_MS=100',
            'PERF_MOCK_TOKEN_INTERVAL_MS=20', 'PERF_MOCK_TOKEN_COUNT=16'
        ) | Set-Content -Encoding ascii -LiteralPath $envFile
        $digest = (docker image inspect $AppImage --format '{{index .RepoDigests 0}}').Trim()
        $manifest = [ordered]@{run_id=$runId; project=$project; docker_context=(docker context show).Trim(); app_image=$AppImage; image_digest=$digest; metrics_url="http://127.0.0.1:$port/metrics"; profile='ultra-low-resource-direct-query'; users=$Users; limits=@{app='1cpu/512m';postgres='0.75cpu/256m';redis='0.25cpu/96m';mock='0.25cpu/128m'}}
        $manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath (Join-Path $run 'manifest.json')
        $configPath = Join-Path $run 'compose.config.yml'
        docker compose -p $project --env-file $envFile -f $compose config | Set-Content -Encoding utf8 -LiteralPath $configPath
        if ($LASTEXITCODE -ne 0) { throw 'Compose configuration failed.' }
        $rendered = Get-Content -Raw -LiteralPath $configPath
        foreach ($forbidden in @('marker:', 'nginx:', 'container_name:', 'env_file:', 'build:')) { if ($rendered -match [regex]::Escape($forbidden)) { throw "Direct profile contains forbidden setting $forbidden" } }
        docker compose -p $project --env-file $envFile -f $compose up -d
        if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed.' }
        $deadline = (Get-Date).AddSeconds(150)
        do { try { $ready = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$port/api/ready"; if ($ready.StatusCode -eq 200) { break } } catch {}; Start-Sleep -Seconds 3 } while ((Get-Date) -lt $deadline)
        if (-not $ready -or $ready.StatusCode -ne 200) { throw 'Isolated app did not become ready before the low-resource timeout.' }
        Write-Output "run-directory=$run"
    }
    'bootstrap' {
        $manifest = Read-Manifest $run
        & $python (Join-Path $root 'scripts/bootstrap_perf_run.py') --base-url ($manifest.metrics_url -replace '/metrics$','') --run-dir $run --env-file $envFile
        if ($LASTEXITCODE -ne 0) { throw 'Bootstrap failed.' }
    }
    'query' {
        $manifest = Read-Manifest $run
        & $python (Join-Path $root 'scripts/run_perf_query_smoke.py') --base-url ($manifest.metrics_url -replace '/metrics$','') --run-dir $run --attempts $Attempts
        if ($LASTEXITCODE -ne 0) { throw 'Query smoke did not complete successfully.' }
    }
    'collect' {
        & $python (Join-Path $root 'scripts/collect_perf_resources.py') --manifest (Join-Path $run 'manifest.json') --output (Join-Path $run 'resources.jsonl') --samples 1
        if ($LASTEXITCODE -ne 0) { throw 'Resource collection failed.' }
    }
    'upload-diagnostic' {
        $manifest = Read-Manifest $run
        Assert-UploadHeadroom
        & $python (Join-Path $root 'scripts/diagnose_perf_upload.py') --base-url ($manifest.metrics_url -replace '/metrics$','') --run-dir $run
        if ($LASTEXITCODE -ne 0) { throw 'Upload terminal-state gate did not pass.' }
    }
    'down' {
        $manifest = Read-Manifest $run
        Assert-OwnedResources $manifest
        docker compose -p $manifest.project --env-file $envFile -f $compose down --volumes
        if ($LASTEXITCODE -ne 0) { throw 'Scoped Compose cleanup failed.' }
        $remaining = @(docker ps -aq --filter "label=com.docker.compose.project=$($manifest.project)")
        if ($remaining.Count -gt 0) { throw 'Compose resources remain after cleanup.' }
        @($envFile, (Join-Path $run 'credentials.json')) | ForEach-Object {
            if (Test-Path -LiteralPath $_ -PathType Leaf) { Remove-Item -LiteralPath $_ -Force }
        }
    }
}
