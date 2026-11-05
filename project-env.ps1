$MeridianRoot = $PSScriptRoot
$env:TEMP = Join-Path $MeridianRoot '.tmp'
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = Join-Path $MeridianRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $MeridianRoot '.runtime\python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $MeridianRoot '.venv'
$env:PIP_CACHE_DIR = Join-Path $MeridianRoot '.cache\pip'
$env:npm_config_cache = Join-Path $MeridianRoot '.cache\npm'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $MeridianRoot '.cache\playwright'
$env:PYTHONPYCACHEPREFIX = Join-Path $MeridianRoot '.cache\pycache'
$env:CODEX_HOME = Join-Path $MeridianRoot '.runtime\codex'
$env:CLAUDE_CONFIG_DIR = Join-Path $MeridianRoot '.runtime\claude'
$MeridianGhSource = if ($env:GH_CONFIG_DIR) { $env:GH_CONFIG_DIR } else { Join-Path $env:APPDATA 'GitHub CLI' }
$env:GH_CONFIG_DIR = Join-Path $MeridianRoot '.runtime\gh'
$env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'
$env:DISABLE_AUTOUPDATER = '1'
$env:MERIDIAN_ROOT = $MeridianRoot
foreach ($MeridianDir in @($env:TEMP, $env:UV_CACHE_DIR, $env:UV_PYTHON_INSTALL_DIR, $env:PIP_CACHE_DIR, $env:npm_config_cache, $env:PLAYWRIGHT_BROWSERS_PATH, $env:PYTHONPYCACHEPREFIX, $env:CODEX_HOME, $env:CLAUDE_CONFIG_DIR, $env:GH_CONFIG_DIR)) {
    New-Item -ItemType Directory -Force -Path $MeridianDir | Out-Null
}
foreach ($MeridianGhFile in @('hosts.yml', 'config.yml')) {
    $MeridianGhExisting = Join-Path $MeridianGhSource $MeridianGhFile
    $MeridianGhLocal = Join-Path $env:GH_CONFIG_DIR $MeridianGhFile
    if ((Test-Path -LiteralPath $MeridianGhExisting) -and -not (Test-Path -LiteralPath $MeridianGhLocal)) {
        Copy-Item -LiteralPath $MeridianGhExisting -Destination $MeridianGhLocal
    }
}
Set-Location -LiteralPath $MeridianRoot
