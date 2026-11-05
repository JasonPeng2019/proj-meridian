"""Build provenance on Actions; download verified static assets without Node locally."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from backend.paths import ROOT, configure_environment, inside

REPO = "JasonPeng2019/proj-meridian"
SOURCES = ["frontend/src", "frontend/public", "frontend/components.json", "frontend/jsconfig.json", "frontend/index.html", "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.js"]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def source_hash():
    return hashlib.sha256(git("ls-tree", "-r", "HEAD", "--", *SOURCES)).hexdigest()


def hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def manifest():
    dist = inside(ROOT / "frontend/dist")
    assert (dist / "index.html").is_file()
    data = {"schema_version": 1, "commit": git("rev-parse", "HEAD").decode().strip(), "source_sha256": source_hash(),
            "run_id": os.environ.get("GITHUB_RUN_ID"), "files": hashes(dist)}
    path = inside(ROOT / "docs/ci/frontend-build.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fetch(run_id):
    if git("diff", "HEAD", "--", *SOURCES).strip():
        raise RuntimeError("Commit frontend changes before downloading a matching build")
    result = subprocess.run(["gh", "run", "view", str(run_id), "--repo", REPO, "--json", "conclusion,headSha"], cwd=ROOT, capture_output=True, text=True, check=True)
    run = json.loads(result.stdout)
    if run["conclusion"] != "success":
        raise RuntimeError("Download only a successful checks run")
    stage = inside(ROOT / ".tmp" / ("frontend-" + uuid.uuid4().hex))
    stage.mkdir(parents=True)
    artifact = "meridian-frontend-" + run["headSha"]
    subprocess.run(["gh", "run", "download", str(run_id), "--repo", REPO, "--name", artifact, "--dir", str(stage)], cwd=ROOT, check=True)
    data = json.loads((stage / "docs/ci/frontend-build.json").read_text(encoding="utf-8"))
    if data["commit"] != run["headSha"] or data["source_sha256"] != source_hash():
        raise RuntimeError("Remote bundle does not match this frontend source")
    dist = inside(stage / "frontend/dist")
    for path in dist.rglob("*"):
        inside(path)
    if hashes(dist) != data["files"] or not (dist / "index.html").is_file():
        raise RuntimeError("Frontend artifact hashes do not match")
    target = inside(ROOT / "frontend/dist")
    backup = inside(ROOT / ".runtime" / ("frontend-backup-" + uuid.uuid4().hex))
    backup.parent.mkdir(parents=True, exist_ok=True)
    # All resolved move targets remain inside this repo; retain a rollback copy.
    assert dist.is_relative_to(ROOT) and target.is_relative_to(ROOT) and backup.is_relative_to(ROOT)
    if target.exists():
        target.rename(backup)
    try:
        dist.rename(target)
    except BaseException:
        if backup.exists():
            backup.rename(target)
        raise
    receipt = inside(ROOT / ".runtime/frontend-installed.json")
    receipt.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Installed matching remote frontend from Actions run {run_id}; no Node/build process started locally.")


def main():
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest")
    download = commands.add_parser("fetch")
    download.add_argument("--run", type=int, required=True)
    args = parser.parse_args()
    manifest() if args.command == "manifest" else fetch(args.run)


if __name__ == "__main__":
    main()
