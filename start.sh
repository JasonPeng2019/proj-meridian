#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export TMPDIR="$PWD/.tmp" TEMP="$PWD/.tmp" TMP="$PWD/.tmp"
export UV_CACHE_DIR="$PWD/.cache/uv" UV_PYTHON_INSTALL_DIR="$PWD/.runtime/python"
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
export UV_CONCURRENT_BUILDS=1 UV_CONCURRENT_DOWNLOADS=4
mkdir -p "$TMPDIR"
if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run this launcher again.' >&2
  exit 1
fi
exec uv run --locked --no-dev meridian "$@"
