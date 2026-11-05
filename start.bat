@echo off
cd /d "%~dp0"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
set "UV_CACHE_DIR=%~dp0.cache\uv"
set "UV_PYTHON_INSTALL_DIR=%~dp0.runtime\python"
set "UV_PROJECT_ENVIRONMENT=%~dp0.venv"
if not exist "%TEMP%" mkdir "%TEMP%"
uv run --locked meridian %*
