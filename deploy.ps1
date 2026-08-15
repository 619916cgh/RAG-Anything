[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$Commit,

    [string]$Config = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Native {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed with exit code $LASTEXITCODE."
    }
}

function Assert-SafeConfigValue {
    param([string]$Name, [string]$Value, [string]$Pattern)
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -notmatch $Pattern) {
        throw "Configuration value '$Name' is missing or unsafe."
    }
}

function Get-RelativePayloadPath {
    param([string]$Root, [string]$FullName)
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $resolved = [IO.Path]::GetFullPath($FullName)
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Payload path escaped staging root: $resolved"
    }
    return $resolved.Substring($prefix.Length).Replace('\', '/')
}

$scriptRoot = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
    Split-Path -Parent $MyInvocation.MyCommand.Definition
} else {
    $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($Config)) {
    $Config = Join-Path $scriptRoot 'deploy\fast-release\deploy.config.psd1'
}
$repoRoot = (Resolve-Path $scriptRoot).Path
Push-Location $repoRoot
$stagingRoot = $null
try {
    if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
        throw "Missing ignored deployment configuration: $Config. Copy deploy.config.example.psd1 first."
    }
    $settings = Import-PowerShellDataFile -LiteralPath $Config
    $policyPath = Join-Path $repoRoot 'deploy\fast-release\policy.json'
    $policy = Get-Content -Raw -LiteralPath $policyPath | ConvertFrom-Json

    $resolvedCommit = (& git rev-parse --verify "$Commit`^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedCommit -notmatch '^[0-9a-f]{40}$') {
        throw "Commit does not resolve to a Git commit: $Commit"
    }
    $baseline = [string]$settings.EligibilityBaselineCommit
    if ($baseline -notmatch '^[0-9a-f]{40}$') {
        throw 'EligibilityBaselineCommit must be a full 40-character SHA.'
    }
    & git cat-file -e "$baseline`^{commit}"
    if ($LASTEXITCODE -ne 0) { throw "Baseline commit is unavailable locally: $baseline" }
    & git merge-base --is-ancestor $baseline $resolvedCommit
    if ($LASTEXITCODE -ne 0) { throw 'Candidate commit must descend from EligibilityBaselineCommit.' }

    $changedPaths = @(& git diff --name-only --diff-filter=ACMRTUXB "$baseline..$resolvedCommit") |
        ForEach-Object { $_.Trim().Replace('\', '/') } | Where-Object { $_ }
    $disallowed = @()
    foreach ($path in $changedPaths) {
        foreach ($pattern in $policy.disallowedCandidatePatterns) {
            if ($path -match $pattern) { $disallowed += $path; break }
        }
    }
    if ($disallowed.Count -gt 0) {
        throw "Fast release rejected. Controlled base or migration release required for:`n$($disallowed -join "`n")"
    }

    Assert-SafeConfigValue Host ([string]$settings.Host) '^[A-Za-z0-9._-]+$'
    Assert-SafeConfigValue User ([string]$settings.User) '^[A-Za-z0-9._-]+$'
    Assert-SafeConfigValue ProjectDirectory ([string]$settings.ProjectDirectory) '^/[A-Za-z0-9._/-]+$'
    Assert-SafeConfigValue RemoteReleaseRoot ([string]$settings.RemoteReleaseRoot) '^/[A-Za-z0-9._/-]+$'
    Assert-SafeConfigValue AppRuntimeImage ([string]$settings.AppRuntimeImage) '^[A-Za-z0-9._:/@+-]+$'
    Assert-SafeConfigValue NginxRuntimeImage ([string]$settings.NginxRuntimeImage) '^[A-Za-z0-9._:/@+-]+$'
    if ([string]$settings.AppRuntimeImageId -notmatch '^sha256:[0-9a-f]{64}$' -or
        [string]$settings.NginxRuntimeImageId -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'Both expected runtime image IDs must be full sha256 identifiers.'
    }
    if (-not (Test-Path -LiteralPath ([string]$settings.IdentityFile) -PathType Leaf)) {
        throw 'IdentityFile does not exist. Password-based fast release is intentionally unsupported.'
    }

    $stagingRoot = Join-Path ([IO.Path]::GetTempPath()) ("rag-fast-{0}-{1}" -f $resolvedCommit.Substring(0, 12), [guid]::NewGuid().ToString('N'))
    $payloadRoot = Join-Path $stagingRoot 'payload'
    New-Item -ItemType Directory -Path $payloadRoot | Out-Null
    $sourceTar = Join-Path $stagingRoot 'source.tar'
    Invoke-Native { git archive --format=tar --output=$sourceTar $resolvedCommit }
    Invoke-Native { tar -xf $sourceTar -C $payloadRoot }

    Push-Location (Join-Path $payloadRoot 'frontend')
    try {
        Invoke-Native { npm ci --ignore-scripts }
        Invoke-Native { npm run build }
    }
    finally { Pop-Location }
    $nodeModules = Join-Path $payloadRoot 'frontend\node_modules'
    if (Test-Path -LiteralPath $nodeModules) {
        $resolvedNodeModules = (Resolve-Path -LiteralPath $nodeModules).Path
        if (-not $resolvedNodeModules.StartsWith($stagingRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to remove node_modules outside the release staging directory.'
        }
        Remove-Item -LiteralPath $resolvedNodeModules -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath (Join-Path $payloadRoot 'frontend\dist\index.html'))) {
        throw 'Frontend build did not produce frontend/dist/index.html.'
    }

    $payloadViolations = @()
    Get-ChildItem -LiteralPath $payloadRoot -Recurse -Force | ForEach-Object {
        $relative = Get-RelativePayloadPath $payloadRoot $_.FullName
        foreach ($pattern in $policy.forbiddenPayloadPatterns) {
            if ($relative -match $pattern) { $payloadViolations += $relative; break }
        }
    }
    if ($payloadViolations.Count -gt 0) {
        throw "Forbidden paths found in release payload:`n$($payloadViolations -join "`n")"
    }

    $payloadArchive = Join-Path $stagingRoot ("rag-fast-{0}.tar.gz" -f $resolvedCommit)
    Invoke-Native { tar -czf $payloadArchive -C $stagingRoot payload }
    $payloadSha = (Get-FileHash -LiteralPath $payloadArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifestPath = Join-Path $stagingRoot 'release-manifest.json'
    [ordered]@{
        commit_sha          = $resolvedCommit
        payload_sha256      = $payloadSha
        baseline_commit     = $baseline
        app_runtime_image   = [string]$settings.AppRuntimeImage
        app_runtime_id      = [string]$settings.AppRuntimeImageId
        nginx_runtime_image = [string]$settings.NginxRuntimeImage
        nginx_runtime_id    = [string]$settings.NginxRuntimeImageId
        created_utc         = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $controlArchive = Join-Path $stagingRoot 'release-control.tar'
    Invoke-Native { git archive --format=tar --output=$controlArchive $baseline deploy/fast-release/remote-release.sh }
    $controlRoot = Join-Path $stagingRoot 'control'
    New-Item -ItemType Directory -Path $controlRoot | Out-Null
    Invoke-Native { tar -xf $controlArchive -C $controlRoot }
    $remoteScriptLocal = Join-Path $controlRoot 'deploy\fast-release\remote-release.sh'

    $target = "{0}@{1}" -f [string]$settings.User, [string]$settings.Host
    $sshCommon = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4', '-i', [string]$settings.IdentityFile)
    $remotePrefix = "/tmp/rag-fast-$resolvedCommit"
    Invoke-Native { scp @sshCommon -P ([int]$settings.Port) $payloadArchive "${target}:$remotePrefix.tar.gz" }
    Invoke-Native { scp @sshCommon -P ([int]$settings.Port) $manifestPath "${target}:$remotePrefix.manifest.json" }
    Invoke-Native { scp @sshCommon -P ([int]$settings.Port) $remoteScriptLocal "${target}:$remotePrefix.sh" }

    $remoteArgs = @(
        $resolvedCommit, "$remotePrefix.tar.gz", $payloadSha,
        [string]$settings.ProjectDirectory, [string]$settings.RemoteReleaseRoot,
        [string]$settings.AppRuntimeImage, [string]$settings.AppRuntimeImageId,
        [string]$settings.NginxRuntimeImage, [string]$settings.NginxRuntimeImageId,
        [int]$settings.MinimumFreeGB, [int]$settings.HealthWindowSeconds,
        [int]$settings.HealthIntervalSeconds, "$remotePrefix.manifest.json"
    )
    $remoteCommand = "chmod 700 $remotePrefix.sh && $remotePrefix.sh " + ($remoteArgs -join ' ')
    Invoke-Native { ssh @sshCommon -p ([int]$settings.Port) $target $remoteCommand }

    $manifestDirectory = Join-Path $repoRoot 'deploy\fast-release\manifests'
    New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null
    $finalManifest = Join-Path $manifestDirectory ("release-manifest-{0}.json" -f $resolvedCommit.Substring(0, 12))
    Invoke-Native { scp @sshCommon -P ([int]$settings.Port) "${target}:$([string]$settings.RemoteReleaseRoot)/$resolvedCommit/release-manifest.json" $finalManifest }
    Write-Host "Fast release accepted. Manifest: $finalManifest"
}
finally {
    Pop-Location
    if ($stagingRoot -and (Test-Path -LiteralPath $stagingRoot)) {
        $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        $resolvedStage = [IO.Path]::GetFullPath($stagingRoot)
        if ($resolvedStage.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedStage).StartsWith('rag-fast-')) {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }
}
