#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export TMPDIR="$PWD/.tmp" TEMP="$PWD/.tmp" TMP="$PWD/.tmp"
export UV_CACHE_DIR="$PWD/.cache/uv" UV_PYTHON_INSTALL_DIR="$PWD/.runtime/python"
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
mkdir -p "$TMPDIR"
exec uv run --locked meridian "$@"
