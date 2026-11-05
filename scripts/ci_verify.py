"""Sequential remote verification. No CLI agents or production review mutations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from backend.paths import ROOT, configure_environment, inside

OUT = inside(ROOT / "docs/ci")


def write(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    corpus = ROOT / "project-meridian_Avathon/project-meridian"
    manifest = json.loads((corpus / "dataset/manifest.json").read_text(encoding="utf-8"))
    mismatches = [a["id"] for a in manifest["assets"] if digest(inside(corpus / a["path"])) != a["sha256"]]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    forbidden = [p for p in tracked if p and any(c in {".secrets", ".runtime", ".cache", ".tmp", ".venv", ".verification", "node_modules"} for c in Path(p).parts)]
    write("audit.json", {"assets": len(manifest["assets"]), "source_mismatches": mismatches, "forbidden_tracked_paths": forbidden})
    assert not mismatches, mismatches
    assert not forbidden, forbidden


def cad():
    import cadquery as cq
    import trimesh
    from backend.app.store import Store
    # Force real generation on this disposable checkout instead of accepting a
    # cache hit as proof that the Linux CAD dependencies work.
    cache = inside(ROOT / "generated/ai_cache/artifacts/cad")
    assert cache.is_relative_to(ROOT / "generated/ai_cache/artifacts")
    if cache.exists():
        shutil.rmtree(cache)
    store = Store()
    before = {p.name: digest(p) for p in (ROOT / "decisions").glob("*.json")}
    store.rebuild_models()
    results = []
    for did in ("D-013", "D-025", "D-026"):
        part = store.models[did]
        assert part["examples"] == ["A", "B"], part
        for variant, model in part["models"].items():
            mesh = trimesh.load(inside(ROOT / "generated" / model["glb"]))
            step = inside(ROOT / "generated" / model["step"])
            shape = cq.importers.importStep(str(step)).val()
            bounds_error = max(abs(float(a) * 1000 - b) for a, b in zip(mesh.extents, model["bounds_mm"]["size"]))
            volume_error = abs(shape.Volume() - model["volume_mm3"])
            assert shape.isValid() and bounds_error < .1 and volume_error < .01
            assert "Reconstruction from 2D drawing. Not the original CAD model." in step.read_text(encoding="utf-8")
            for kind in ("glb", "step"):
                assert digest(inside(ROOT / "generated" / model[kind])) == model[kind + "_sha256"]
            results.append({"part": did, "variant": variant, "bounds_mm": model["bounds_mm"]["size"], "bounds_error_mm": bounds_error, "volume_error_mm3": volume_error})
    assert len(results) == 6
    assert before == {p.name: digest(p) for p in (ROOT / "decisions").glob("*.json")}
    write("cad.json", {"passed": True, "variants": results, "decisions_unchanged": True})


def server_check(live=False):
    import httpx
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if live:
        if not env.get("OPENAI_API_KEY"):
            raise RuntimeError("Set the repository OPENAI_API_KEY Actions secret before selecting live API checks")
        env.pop("MERIDIAN_NO_KEY", None)
    else:
        env["MERIDIAN_NO_KEY"] = "1"
        env.pop("OPENAI_API_KEY", None)
    with (OUT / ("live-server.log" if live else "browser-server.log")).open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "-m", "backend.app.main"], cwd=ROOT, env=env, stdout=log, stderr=log,
                                start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 120
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("App exited before verification; inspect the server log artifact")
                try:
                    status = httpx.get("http://127.0.0.1:8000/api/status", timeout=1)
                    if status.status_code == 200:
                        assert status.json()["chat_available"] is live
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("App startup timed out")
                time.sleep(.3)
            script = "scripts/verify_live.py" if live else "scripts/verify_browser.py"
            subprocess.run([sys.executable, script], cwd=ROOT, env=env, check=True)
            if live:
                report = json.loads((ROOT / "docs/verification/live-questions.json").read_text(encoding="utf-8"))
                assert report["summary"]["passed_scenarios"] == report["summary"]["scenarios"] == 10
        finally:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            else:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            proc.wait(timeout=15)


def main():
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["audit", "cad", "browser", "live"])
    stage = parser.parse_args().stage
    {"audit": audit, "cad": cad, "browser": server_check, "live": lambda: server_check(True)}[stage]()


if __name__ == "__main__":
    main()
