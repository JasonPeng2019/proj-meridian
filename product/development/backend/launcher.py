"""Local entry point; the application server is supplied by A03 in B02."""

from __future__ import annotations

import importlib.util
import sys


def main() -> int:
    if importlib.util.find_spec("backend.app.main") is None:
        print(
            "Meridian server is not implemented yet. "
            "A03 supplies backend/app/main.py in B02.",
            file=sys.stderr,
        )
        return 1

    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000)
    return 0
