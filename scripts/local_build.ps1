param(
    [ValidateSet('frontend')][string]$Target = 'frontend',
    [ValidateRange(1, 60)][int]$WaitMinutes = 10
)
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'project-env.ps1')
$MeridianBuildRoot = (Resolve-Path -LiteralPath $MeridianRoot).Path
$MeridianLockPath = Join-Path $MeridianBuildRoot '.runtime\local-build.lock'
$MeridianLock = $null
$MeridianDeadline = (Get-Date).AddMinutes($WaitMinutes)
$MeridianNextNotice = Get-Date
try {
    while ($null -eq $MeridianLock) {
        if ((Get-Date) -ge $MeridianDeadline) { throw 'Local build queue timed out; no build started.' }
        try {
            $MeridianLock = [System.IO.File]::Open($MeridianLockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch [System.IO.IOException] {
            if ((Get-Date) -ge $MeridianNextNotice) {
                Write-Host 'Queued: another local heavy task holds the build lock.'
                $MeridianNextNotice = (Get-Date).AddSeconds(15)
            }
            Start-Sleep -Seconds 2
        }
    }
    $MeridianStableSamples = 0
    while ($MeridianStableSamples -lt 2) {
        if ((Get-Date) -ge $MeridianDeadline) { throw 'Waiting for RAM/CPU headroom timed out; no build started.' }
        $MeridianOS = Get-CimInstance Win32_OperatingSystem
        $MeridianCPU = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
        $MeridianFreeMB = [math]::Floor($MeridianOS.FreePhysicalMemory / 1024)
        if ($null -eq $MeridianCPU.Average) { throw 'Cannot measure CPU load; refusing to guess that a local build is safe.' }
        $MeridianLoad = [math]::Round($MeridianCPU.Average)
        if ($MeridianFreeMB -ge 3072 -and $MeridianLoad -le 70) {
            $MeridianStableSamples++
        } else {
            $MeridianStableSamples = 0
        }
        if ((Get-Date) -ge $MeridianNextNotice) {
            Write-Host "Resource gate: $MeridianFreeMB MB free RAM, $MeridianLoad% CPU; need >=3072 MB and <=70% CPU."
            $MeridianNextNotice = (Get-Date).AddSeconds(15)
        }
        if ($MeridianStableSamples -lt 2) { Start-Sleep -Seconds 3 }
    }
    $env:NODE_OPTIONS = '--max-old-space-size=1536'
    $env:GOMAXPROCS = '2'
    $env:OMP_NUM_THREADS = '1'
    $env:OPENBLAS_NUM_THREADS = '1'
    Write-Host "Starting one local frontend build: Node heap <=1536 MB; esbuild <=2 Go threads. Other task threads may still use memory."
    if (-not (Test-Path -LiteralPath (Join-Path $MeridianBuildRoot 'frontend\node_modules'))) {
        & npm.cmd --prefix frontend ci --maxsockets=2
        if ($LASTEXITCODE -ne 0) { throw "Dependency install failed ($LASTEXITCODE)." }
    }
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed ($LASTEXITCODE)." }
} finally {
    if ($null -ne $MeridianLock) { $MeridianLock.Dispose() }
}
