"""Launch the real Meridian app from already-downloaded packages, without installing.

This workspace shortcut creates no environment, watcher, browser or child process.
The ordinary packaged entry point remains backend.launcher.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=root.parent / "testing/cache/uv-preview")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if not args.inputs.is_file():
        raise SystemExit("The downloaded source extraction inputs.json is required.")
    sys.path.insert(0, str(root))
    from backend.launcher import limit_windows_process
    job_owner = limit_windows_process()
    cache = args.cache.resolve()
    archive = cache / "archive-v0"
    paths = list(archive.iterdir()) if archive.is_dir() else []
    # uv completed this wheel extraction before its cache rename failed. Reading
    # that existing package requires no installation or cache mutation.
    paths.extend(path for path in cache.glob(".tmp*") if (path / "openai").is_dir())
    sys.path[:0] = [str(path) for path in paths if path.is_dir()]
    sys.path.insert(0, str(root))
    os.environ["MERIDIAN_INPUTS_PATH"] = str(args.inputs.resolve())
    os.environ["MERIDIAN_DEBUG"] = "1" if args.debug else "0"
    try:
        import uvicorn
        from backend.app.main import app
    except ImportError as error:
        raise SystemExit("A cached runtime dependency is missing; no automatic installation was attempted.") from error
    print(f"Meridian http://127.0.0.1:{args.port} | PID {os.getpid()} | 1 process, 512 MiB, 10% CPU", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, reload=False,
                limit_concurrency=8, timeout_keep_alive=3, access_log=False)
    kernel, job = job_owner
    kernel.CloseHandle(job)


if __name__ == "__main__":
    main()
