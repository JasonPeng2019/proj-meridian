"""Install a verified harness-v2 frontend artifact; never build on this computer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "JasonPeng2019/proj-meridian"
BRANCH = "harness-v2"


def fetch(run_id: int):
    run = json.loads(subprocess.check_output([
        "gh", "run", "view", str(run_id), "--repo", REPOSITORY,
        "--json", "headSha,headBranch,conclusion"], text=True))
    if run["headBranch"] != BRANCH or run["conclusion"] != "success":
        raise RuntimeError("Require a successful harness-v2 checks run")
    stage = ROOT / "testing/runs/frontend-downloads" / (str(run_id) + "-" + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    subprocess.run(["gh", "run", "download", str(run_id), "--repo", REPOSITORY,
        "--name", "harness-v2-frontend-" + run["headSha"], "--dir", str(stage)], check=True)
    manifest = json.loads((stage / "testing/reports/ci/frontend-build.json").read_text())
    spec = importlib.util.spec_from_file_location("ci_source_hash", ROOT / "testing/ci/checks.py")
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    if manifest["commit"] != run["headSha"] or manifest["source_sha256"] != checks.source_hash():
        raise RuntimeError("Remote artifact does not match this frontend source")
    dist = stage / "development/frontend/dist"
    actual = {p.relative_to(dist).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(dist.rglob("*")) if p.is_file()}
    if actual != manifest["files"] or not (dist / "index.html").is_file():
        raise RuntimeError("Frontend artifact hashes differ")
    target = ROOT / "development/frontend/dist"
    backup = ROOT / "development/.runtime/frontend-backups" / uuid.uuid4().hex
    assert all(p.resolve().is_relative_to(ROOT.resolve()) for p in (dist, target, backup))
    backup.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.rename(backup)
    try:
        shutil.copytree(dist, target)
    except BaseException:
        if target.exists():
            assert target.resolve().is_relative_to(ROOT.resolve())
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)
        raise
    receipt = ROOT / "testing/reports/ci/frontend-installed.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({**manifest, "installed_from_run": run_id,
                                  "local_build_started": False}, indent=2) + "\n")
    print(f"Installed verified harness-v2 frontend from run {run_id}; no local build started.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, required=True)
    fetch(parser.parse_args().run)
