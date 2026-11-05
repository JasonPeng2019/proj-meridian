@echo off
cd /d "%~dp0"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
set "UV_CACHE_DIR=%~dp0.cache\uv"
set "UV_PYTHON_INSTALL_DIR=%~dp0.runtime\python"
set "UV_PROJECT_ENVIRONMENT=%~dp0.venv"
set "UV_CONCURRENT_BUILDS=1"
set "UV_CONCURRENT_DOWNLOADS=4"
if not exist "%TEMP%" mkdir "%TEMP%"
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run this launcher again.
  exit /b 1
)
uv run --locked --no-dev meridian %*
exit /b %errorlevel%
