@echo off
setlocal
pushd "%~dp0"
call uv run meridian %*
set "meridian_exit=%errorlevel%"
popd
exit /b %meridian_exit%
