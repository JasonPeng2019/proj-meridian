"""Fresh runtime, offline regeneration and correction UI in an isolated clone.

Run after committing the implementation. The only review this script accepts is
labelled Automated verification, in .verification/release-clone, never production.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from playwright.sync_api import sync_playwright

from backend.paths import ROOT, configure_environment, inside

OUT = inside(ROOT / "docs/verification")
CLONE = inside(ROOT / (".verification/release-clone-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")))
BASE = "http://127.0.0.1:8001"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed: {args[0]} ({result.returncode})\n{result.stderr[-3000:]}")
    return result.stdout.strip()


def clone_environment():
    env = os.environ.copy()
    for name, rel in {"TEMP": ".tmp", "TMP": ".tmp", "TMPDIR": ".tmp", "UV_PROJECT_ENVIRONMENT": ".venv",
                      "PYTHONPYCACHEPREFIX": ".cache/pycache", "CODEX_HOME": ".runtime/codex", "CLAUDE_CONFIG_DIR": ".runtime/claude"}.items():
        target = inside(CLONE / rel)
        target.mkdir(parents=True, exist_ok=True)
        env[name] = str(target)
    env["MERIDIAN_ROOT"] = str(CLONE)
    env["UV_CACHE_DIR"] = str(inside(ROOT / ".cache/uv"))
    env["MERIDIAN_NO_KEY"] = "1"
    env.pop("OPENAI_API_KEY", None)
    env.pop("VIRTUAL_ENV", None)
    return env


def start(env, label):
    log = inside(OUT / f"release-{label}.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(["uv", "run", "--locked", "meridian", "--port", "8001"], cwd=CLONE, env=env,
                            stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            start_new_session=os.name != "nt")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log.close()
            raise RuntimeError(f"Clone server exited. See release-{label}.log")
        try:
            response = httpx.get(BASE + "/api/status", timeout=1)
            if response.status_code == 200:
                return proc, log
        except httpx.HTTPError:
            pass
        time.sleep(.3)
    stop(proc, log)
    raise RuntimeError("Clone server startup timed out")


def stop(proc, log):
    # uv launches a child server; terminate the isolated process tree on Windows.
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    proc.wait(timeout=15)
    log.close()


def inspect(client):
    status = client.get("/api/status").json()
    manifest = json.loads((CLONE / "generated/models/manifest.json").read_text(encoding="utf-8"))
    model_ids = sorted(did for did, part in manifest.items() if part.get("models"))
    assert {"D-013", "D-025", "D-026"}.issubset(model_ids)
    assert status["drawings"] == 30 and status["models"] == len(model_ids) and status["parts"] == 215
    assert not status["chat_available"]
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 400
    assert client.get("/api/review").status_code == 200
    part = client.get("/api/parts/D-013").json()
    thickness = next(f for f in part["facts"] if f["fact"] == "D-013/template/thickness")
    assert thickness["display"] == {"state": "options", "values": [3.0, 6.0]}
    assert thickness["correction"]["by"] == "Jason Peng"
    assets = []
    for did in model_ids:
        record = client.get("/api/parts/" + did).json()
        assert record["has_3d"] and record["model"]["examples"]
        assert record["model"]["models"] == manifest[did]["models"]
        if did in ("D-013", "D-025", "D-026"):
            assert record["model"]["examples"] == ["A", "B"]
        for variant, model in record["model"]["models"].items():
            for kind in ("glb", "step"):
                response = client.get("/generated/" + model[kind])
                response.raise_for_status()
                assert hashlib.sha256(response.content).hexdigest() == model[kind + "_sha256"]
                assets.append(model[kind])
    for path in ("/part/D-013/3d?example=B", "/part/bom/box/m5-nut-for-2020-not-5mm/detail", "/review/needs-input", "/readme"):
        assert client.get(path).status_code == 200
    assert client.get("/api/parts/D-003/image?page=3").headers["content-type"] == "image/png"
    assert client.get("/api/parts/D-013/image?thumb=1").headers["content-type"] == "image/png"
    assert client.get("/api/parts/D-013/crop", params={"fact": "D-013/drawing/material"}).headers["content-type"] == "image/png"
    return {"status": status, "model_ids_checked": model_ids, "asset_hashes_checked": len(assets), "d013_decision_replayed": True}


def correction_demo(env, report):
    config_path = inside(CLONE / "ai_settings.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["reviewer_name"] = "Automated verification"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    key_path = inside(ROOT / ".codex/.secrets/OpenAI_API_Keys.txt")
    supplied = os.environ.get("OPENAI_API_KEY", "").strip()
    keys = [supplied] if supplied else re.findall(r"sk-[A-Za-z0-9_-]+", key_path.read_text(encoding="utf-8-sig")) if key_path.exists() else []
    assert len(keys) == 1, "A single local key is required for live chat verification"
    env = env.copy()
    env.pop("MERIDIAN_NO_KEY", None)
    env["OPENAI_API_KEY"] = keys[0]
    env["MERIDIAN_DEBUG_UI"] = "1"  # Isolated engineering history demonstration.
    proc, log = start(env, "correction-demo")
    saved = {"purpose": "Automated workflow verification in an isolated clone; not a human approval", "reviewer": "Automated verification"}
    question = "What is the title recorded for D-019? Show the original title and explain any uncertainty."
    sheet = CLONE / "project-meridian_Avathon/project-meridian/dataset/drawings/D-019.pdf"
    sheet_hash = digest(sheet)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
            page = browser.new_page(viewport={"width": 1600, "height": 1050})
            errors, failures = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: failures.append({"status": r.status, "url": r.url}) if r.status >= 400 else None)
            page.goto(BASE + "/chat")
            def send(message):
                box = page.locator(".composer textarea")
                box.fill(message)
                with page.expect_response(lambda r: r.url.endswith("/api/chat") and r.request.method == "POST", timeout=180000) as response:
                    box.press("Enter")
                result = response.value.json()
                assert response.value.status == 200, result
                page.locator(".thinking").wait_for(state="hidden")
                page.wait_for_timeout(300)
                return result
            saved["question"] = question
            saved["before"] = send(question)
            page.screenshot(path=str(OUT / "correction-before.png"))
            assert saved["before"]["facts"]["D-019/drawing/title"]["display"]["state"] == "undetermined"
            saved["proposal_chat"] = send("Propose correcting D-019's drawing title to 'Optics Silicone Gasket'. This is an automated workflow demonstration. Create a pending proposal for separate review.")
            with httpx.Client(base_url=BASE, timeout=30) as client:
                pending = next(i for i in client.get("/api/review").json() if i["type"] == "correction" and i["target"] == "D-019/drawing/title")
                assert client.get("/api/parts/D-019").json()["drawing"]["fields"]["title"]["value"] == "Description"
                saved["pending_item"] = pending
            page.goto(BASE + "/review/corrections/" + pending["id"])
            page.get_by_role("button", name="Accept correction", exact=True).wait_for()
            page.locator(".review-actions textarea").fill("Automated workflow test in isolated clone. Demonstrates acceptance and history; not Jason's human review.")
            page.screenshot(path=str(OUT / "correction-pending-review.png"))
            with page.expect_response(lambda r: "/api/review/" in r.url and r.request.method == "POST") as accepted:
                page.get_by_role("button", name="Accept correction", exact=True).click()
            assert accepted.value.status == 200
            saved["accepted"] = accepted.value.json()
            assert saved["accepted"]["decision"]["by"] == "Automated verification"
            page.goto(BASE + "/chat")
            saved["after"] = send(question)
            page.screenshot(path=str(OUT / "correction-after.png"))
            fact = saved["after"]["facts"]["D-019/drawing/title"]
            assert fact["display"]["value"] == "Optics Silicone Gasket"
            assert fact["correction"]["original"] == "Description"
            assert "Automated verification" in saved["after"]["text"] and "Description" in saved["after"]["text"]
            page.goto(BASE + "/part/D-019/history")
            page.get_by_text("Automated verification", exact=False).first.wait_for()
            page.screenshot(path=str(OUT / "correction-history.png"))
            assert not errors, errors
            assert not failures, failures
            browser.close()
        with httpx.Client(base_url=BASE) as client:
            saved["history"] = client.get("/api/parts/D-019/history?fact=D-019/drawing/title").json()
            assert client.get("/api/accuracy").json()["accuracy"] is None
        saved["original_pdf_unchanged"] = digest(sheet) == sheet_hash
        raw = json.loads((CLONE / "generated/drawings.json").read_text(encoding="utf-8"))
        saved["raw_title_unchanged"] = raw["D-019"]["fields"]["title"]["value"] == "Description"
        assert saved["original_pdf_unchanged"] and saved["raw_title_unchanged"]
        report["correction_ui"] = {"passed": True, "reviewer": "Automated verification", "production_d019_unchanged": True, "browser_errors": []}
    finally:
        (OUT / "correction-demo.json").write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
        stop(proc, log)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-live", action="store_true", help="Verify release without a paid API correction demonstration")
    args = parser.parse_args()
    configure_environment()
    OUT.mkdir(parents=True, exist_ok=True)
    assert not CLONE.exists(), "Use a new isolated target; existing verification data is never deleted automatically"
    CLONE.parent.mkdir(parents=True, exist_ok=True)
    report = {"at": datetime.now(timezone.utc).isoformat(), "source_commit": run(["git", "rev-parse", "HEAD"], ROOT, os.environ.copy())}
    corpus = ROOT / "project-meridian_Avathon/project-meridian"
    manifest = json.loads((corpus / "dataset/manifest.json").read_text(encoding="utf-8"))
    matches = [digest(corpus / a["path"]) == a["sha256"] for a in manifest["assets"]]
    assert all(matches)
    report["source_manifest_hashes"] = {"passed": sum(matches), "total": len(matches)}
    source_before = {str(p.relative_to(corpus)): digest(p) for p in corpus.rglob("*") if p.is_file() and "__MACOSX" not in p.parts}
    decisions_before = {p.name: digest(p) for p in (ROOT / "decisions").glob("*.json")}
    run(["git", "-c", "core.hooksPath=.git/hooks-disabled", "clone", "--no-hardlinks", str(ROOT), str(CLONE)], ROOT, os.environ.copy())
    env = clone_environment()
    run(["uv", "sync", "--locked", "--no-dev"], CLONE, env)
    absent = run(["uv", "run", "--locked", "python", "-c", "import importlib.util,json;print(json.dumps({n:importlib.util.find_spec(n) is None for n in ['cadquery','pytest','playwright']}))"], CLONE, env)
    report["optional_dependencies_absent"] = json.loads(absent)
    assert all(report["optional_dependencies_absent"].values())
    assert not (CLONE / "frontend/node_modules").exists() and not (CLONE / ".codex/.secrets").exists()
    proc, log = start(env, "fresh")
    try:
        with httpx.Client(base_url=BASE, timeout=60) as client:
            report["fresh_runtime"] = inspect(client)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(BASE + "/chat")
            page.wait_for_function("document.querySelector('.composer textarea')?.disabled === true")
            assert page.locator(".composer textarea").is_disabled()
            page.screenshot(path=str(OUT / "fresh-no-key.png"))
            browser.close()
    finally:
        stop(proc, log)
    generated = inside(CLONE / "generated")
    for child in generated.iterdir():
        if child.name == "ai_cache":
            continue
        resolved = inside(child.resolve())
        assert resolved.is_relative_to(generated) and resolved != generated
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    before = time.monotonic()
    proc, log = start(env, "regenerated")
    try:
        with httpx.Client(base_url=BASE, timeout=60) as client:
            report["regenerated_runtime"] = inspect(client)
        report["regeneration_seconds"] = round(time.monotonic() - before, 3)
        assert len(list((generated / "images").glob("*-p*.png"))) == 33
    finally:
        stop(proc, log)
    if args.skip_live:
        report["correction_ui"] = {"skipped": True, "reason": "Live API checks are opt-in; isolated governance tests still run in pytest."}
    else:
        correction_demo(env, report)
    source_after = {str(p.relative_to(corpus)): digest(p) for p in corpus.rglob("*") if p.is_file() and "__MACOSX" not in p.parts}
    assert source_before == source_after
    assert decisions_before == {p.name: digest(p) for p in (ROOT / "decisions").glob("*.json")}
    report["production_evidence_and_decisions_unchanged"] = True
    report["passed"] = True
    (OUT / "release-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
