"""Two sequential Actions-only benchmark passes, plus offline export/re-scoring.

run owns isolated clone servers; it never queries or reviews production state.
score and compile are lightweight and may run locally. Independent CLI judging
is deliberately outside this program and outside hosted CI.
"""
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from backend.paths import ROOT, configure_environment, inside
from backend.evaluation.benchmark import compile_draft, fingerprint, judge_payload, load_judgments, report_results
from backend.evaluation.contracts import catalog_reference

DRAFT = ROOT / "docs/Question-benchmark/benchmark_draft.md"
REVIEWER = "Automated verification"


def write(path: Path, value):
    target = inside(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def jsonl(path: Path, rows):
    target = inside(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def files_hash(folder: Path, patterns=("*",)) -> dict:
    return {str(p.relative_to(folder)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for pattern in patterns for p in sorted(folder.rglob(pattern)) if p.is_file() and "__pycache__" not in p.parts}


def frozen_inputs() -> dict:
    # Cached reader images/results are evidence inputs too; include all generated
    # data, assets and source files rather than only their index documents.
    return {"backend": files_hash(ROOT / "backend", ("*.py",)), "scripts": files_hash(ROOT / "scripts", ("*.py",)),
            "frontend_source": files_hash(ROOT / "frontend/src"), "frontend_dist": files_hash(ROOT / "frontend/dist"),
            "evidence": files_hash(ROOT / "project-meridian_Avathon/project-meridian"),
            "generated": files_hash(ROOT / "generated"), "decisions": files_hash(ROOT / "decisions", ("*.json",)),
            "settings": hashlib.sha256((ROOT / "ai_settings.yaml").read_bytes()).hexdigest(),
            "draft": hashlib.sha256(DRAFT.read_bytes()).hexdigest(),
            "lock": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def clone_environment(clone: Path) -> dict:
    env = os.environ.copy()
    for key, relative in {"TEMP": ".tmp", "TMP": ".tmp", "TMPDIR": ".tmp", "UV_CACHE_DIR": ".cache/uv",
                          "PIP_CACHE_DIR": ".cache/pip", "PYTHONPYCACHEPREFIX": ".cache/pycache",
                          "CODEX_HOME": ".runtime/codex", "CLAUDE_CONFIG_DIR": ".runtime/claude",
                          "PLAYWRIGHT_BROWSERS_PATH": ".cache/playwright"}.items():
        target = inside(clone / relative)
        target.mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    env["MERIDIAN_ROOT"] = str(clone)
    env.pop("MERIDIAN_NO_KEY", None)
    env["OMP_NUM_THREADS"] = env["OPENBLAS_NUM_THREADS"] = "1"
    return env


def copy_prepared_tree(source: Path, target: Path, clone: Path):
    source, target, clone = inside(source), inside(target), inside(clone)
    if target == clone or not target.is_relative_to(clone):
        raise ValueError("Prepared asset destination must stay inside the disposable clone")
    # A merge would retain tracked historical CAD-cache entries that the hosted
    # generator removed. Start from exactly the measured prepared tree instead.
    for path in source.rglob("*"):
        inside(path)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    if files_hash(source) != files_hash(target):
        raise RuntimeError("Prepared clone assets differ before any benchmark request")


def make_clone(clone: Path) -> dict:
    import yaml
    clone = inside(clone)
    if clone.exists():
        raise ValueError("Benchmark clone already exists; use a new output directory")
    clone.parent.mkdir(parents=True, exist_ok=True)
    # A committed implementation is mandatory: no accidentally testing stale code.
    if git("diff", "HEAD", "--", "backend", "scripts", "frontend/src", "ai_settings.yaml", "docs/Question-benchmark"):
        raise ValueError("Commit implementation/draft/settings before the hosted benchmark")
    subprocess.run(["git", "-c", "core.hooksPath=.git/hooks-disabled", "clone", "--no-hardlinks", str(ROOT), str(clone)], cwd=ROOT, check=True, capture_output=True)
    for relative in ("backend", "scripts"):
        if files_hash(clone / relative, ("*.py",)) != files_hash(ROOT / relative, ("*.py",)):
            raise ValueError("Committed clone code differs from the measured checkout")
    # Hosted build/CAD stages may have refreshed generated assets after checkout.
    # Copy those exact measured inputs, with no local extraction or CAD subprocess.
    for relative in ("generated", "frontend/dist"):
        source = inside(ROOT / relative)
        copy_prepared_tree(source, clone / relative, clone)
    for relative in ("generated/records.json", "generated/bom.json", "generated/ai_results.json", "generated/models/manifest.json", "frontend/dist/index.html"):
        if not inside(clone / relative).is_file():
            raise ValueError("Run queued build/CAD preparation before the benchmark; missing " + relative)
    config = yaml.safe_load((clone / "ai_settings.yaml").read_text(encoding="utf-8"))
    config["reviewer_name"] = REVIEWER
    (clone / "ai_settings.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    # Clean Q11 fixture baseline only: do not replay earlier title review events.
    # These are disposable cloned records; production evidence/history is untouched.
    excluded = []
    decisions = inside(clone / "decisions")
    for path in decisions.glob("*.json"):
        event = json.loads(path.read_text(encoding="utf-8"))
        if event.get("applies_to") == "D-019/drawing/title":
            excluded.append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            inside(path).unlink()
    return {"reviewer": REVIEWER, "excluded_cloned_d019_title_events": excluded,
            "settings_sha256": hashlib.sha256((clone / "ai_settings.yaml").read_bytes()).hexdigest()}


def stop(proc, log):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], cwd=ROOT, capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    proc.wait(timeout=20)
    log.close()


def start(clone: Path, base: str, logfile: Path):
    import httpx
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("--url must identify an isolated loopback HTTP server")
    # Never reuse an existing listener and accidentally benchmark/review production.
    try:
        httpx.get(base + "/api/status", timeout=1)
    except httpx.ConnectError:
        pass
    else:
        raise ValueError("Benchmark port already has a listener; select a free --url")
    log = inside(logfile).open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", parsed.hostname,
                             "--port", str(parsed.port or 80)], cwd=clone, env=clone_environment(clone), stdout=log, stderr=log,
                            start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("Isolated benchmark server exited; inspect server artifact")
            try:
                response = httpx.get(base + "/api/status", timeout=1)
                if response.status_code == 200:
                    state = response.json()
                    if state.get("reviewer_name") != REVIEWER or state.get("chat_model") != "gpt-6-luna" or not state.get("chat_available"):
                        raise RuntimeError("Expected isolated Automated verification server with live gpt-6-luna chat")
                    return proc, log, state
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        raise RuntimeError("Isolated server startup timed out")
    except BaseException:
        stop(proc, log)
        raise


def get_json(client, path):
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def preconditions(client, case: dict) -> list[dict]:
    cid = case["id"]
    result = []
    if cid in {"Q03", "Q04", "Q08"}:
        reviews = get_json(client, "/api/review")
        mappings = [r for r in reviews if r.get("type") == "name_mapping" and
                    (r.get("target") == "names/section/optical -> optics" if cid == "Q03" else r.get("kind") == "material")]
        if cid == "Q03":
            confirmed = any(r.get("status") == "human_confirmed" and r.get("value") == "same" for r in mappings)
            result.append({"name": "approved_optical_optics_mapping", "status": "met" if confirmed else "pending", "records": mappings})
        elif cid == "Q08":
            # Conservatively expose pending alloy mappings instead of pretending
            # the general aluminium search has its approved full coverage.
            relevant = [r for r in mappings if any(v in (r.get("target") or "").casefold() for v in ("alumin", "en-aw", "en aw", "6061", "6063", "7075"))]
            result.append({"name": "approved_material_mappings", "status": "met" if relevant and all(r.get("status") == "human_confirmed" for r in relevant) else "pending", "records": relevant})
    if cid == "Q08":
        links = []
        for did in ("D-016", "D-017", "D-018", "D-025"):
            record = get_json(client, "/api/parts/" + did)
            link = record.get("link") or {}
            links.append({"drawing": did, "link": link, "bom_rows": [r["name"] for r in record.get("bom", [])],
                          "deduplicated_part_key": record["key"]})
        result.append({"name": "four_flagged_drawing_links_verified", "status": "met" if all(l["link"].get("method") not in {None, "unresolved"} for l in links) else "pending", "links": links})
    if cid in {"Q11a", "Q11b"}:
        record = get_json(client, "/api/parts/D-019")
        fact = next((f for f in record["facts"] if f["fact"] == "D-019/drawing/title"), {})
        if cid == "Q11a":
            met = fact.get("display", {}).get("state") == "undetermined" and not fact.get("correction")
        else:
            met = fact.get("correction", {}).get("by") == REVIEWER
        result.append({"name": "isolated_before_correction" if cid == "Q11a" else "isolated_automated_correction_accepted", "status": "met" if met else "pending", "fact": fact})
    if cid == "Q17":
        record = get_json(client, "/api/parts/D-026")
        model = record.get("model") or {}
        result.append({"name": "actual_model_variants_and_density", "status": "met" if len(model.get("examples", [])) >= 2 and model.get("weight_check") else "pending", "model": model})
    return result


def correction_workflow(client, base: str, output: Path, case: dict) -> dict:
    from playwright.sync_api import sync_playwright
    # Replacement derives from this draft's Must include values, not a second fixture.
    replacement = next(v for v in case["must_include"] if v != "Description")
    message = f"Propose correcting D-019's drawing title to '{replacement}'. This is an automated benchmark workflow demonstration. Create a pending proposal for separate review."
    response = client.post("/api/chat", json={"message": message})
    response.raise_for_status()
    proposal_chat = response.json()
    pending = [r for r in get_json(client, "/api/review") if r["type"] == "correction" and r["target"] == "D-019/drawing/title" and r["value"] == replacement]
    if len(pending) != 1:
        raise RuntimeError("Chat did not create exactly one pending canonical title proposal")
    item = pending[0]
    if not item.get("check_result"):
        raise RuntimeError("Pending proposal lacks its evidence check")
    before = get_json(client, "/api/parts/D-019")
    fact = next(f for f in before["facts"] if f["fact"] == "D-019/drawing/title")
    if fact["display"]["state"] != "undetermined":
        raise RuntimeError("Proposal changed accepted title before review")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(base + "/review/corrections/" + item["id"])
            page.get_by_role("button", name="Accept correction", exact=True).wait_for()
            page.locator(".review-actions textarea").fill("Automated benchmark workflow verification in an isolated clone. Not Jason Peng's review or approval.")
            page.screenshot(path=str(inside(output / "q11-pending-review.png")))
            with page.expect_response(lambda r: "/api/review/" in r.url and r.request.method == "POST") as accepted:
                page.get_by_role("button", name="Accept correction", exact=True).click()
            if accepted.value.status != 200:
                raise RuntimeError("Review UI did not accept the pending correction")
            decision = accepted.value.json()
            if decision.get("decision", {}).get("by") != REVIEWER:
                raise RuntimeError("Automated workflow attributed to the wrong reviewer")
            page.screenshot(path=str(inside(output / "q11-accepted-review.png")))
        finally:
            browser.close()
    return {"purpose": "isolated automated workflow verification; not a human approval", "reviewer": REVIEWER,
            "proposal_chat": proposal_chat, "pending_item": item, "accepted": decision}


def score(output: Path, judge_results: Path | None = None):
    fixture = json.loads((output / "cases.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    derived = compile_draft(output / "benchmark_draft.md")
    if fixture != derived or fixture["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("Benchmark fixture does not match its frozen canonical draft/source hash")
    executions = [json.loads(v) for v in (output / "executions.jsonl").read_text(encoding="utf-8").splitlines() if v.strip()]
    by_id = {c["id"]: c for c in fixture["cases"]}
    identities = [(e["pass"], e["case_id"]) for e in executions]
    if len(set(identities)) != len(identities) or any(p not in (1, 2) or cid not in by_id for p, cid in identities):
        raise ValueError("Duplicate/unknown execution identities in capture")
    if any(e.get("question") != by_id[e["case_id"]]["question"] for e in executions):
        raise ValueError("Captured question differs from the canonical draft")
    payloads = [judge_payload(by_id[e["case_id"]], e, manifest) for e in executions]
    judgments = load_judgments(judge_results, {p["cache_key"] for p in payloads})
    bundle = report_results(fixture, manifest, executions, judgments)
    write(output / "report.json", bundle["report"])
    # Duplicate keys can be judged once; mapping back to both executions is exact.
    jsonl(output / "judge-inputs.jsonl", {p["cache_key"]: p for p in bundle["judge_payloads"]}.values())
    print(json.dumps(bundle["report"]["summary"], indent=2))


def run(args):
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Paid API benchmark/browser work runs only in queued GitHub-hosted Actions")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY Actions secret is required")
    import httpx
    output = inside(args.output)
    if output.exists():
        raise ValueError("Use a new benchmark output directory; reports are never overwritten by run")
    output.mkdir(parents=True)
    fixture = compile_draft(DRAFT)
    from backend.app.store import Store
    references = catalog_reference(Store())
    frozen = frozen_inputs()
    manifest = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(), "commit": git("rev-parse", "HEAD"),
                "source_sha256": fixture["source_sha256"], "code_sha256": fingerprint({k: frozen[k] for k in ("backend", "scripts", "frontend_source", "frontend_dist", "lock")}),
                "settings_sha256": frozen["settings"], "input_fingerprint": fingerprint(frozen), "input_hashes": frozen,
                "model": "gpt-6-luna", "passes": args.passes, "cases_per_pass": len(fixture["cases"]),
                "expected_executions": args.passes * len(fixture["cases"]), "status": "running", "pass_baselines": []}
    write(output / "cases.json", fixture)
    inside(output / "benchmark_draft.md").write_bytes(DRAFT.read_bytes())
    write(output / "manifest.json", manifest)
    executions = []
    clone_base = inside(ROOT / ".verification" / ("benchmark-" + output.name + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")))
    try:
        for pass_number in range(1, args.passes + 1):
            if frozen_inputs() != frozen:
                raise RuntimeError("Source/code/settings/production state changed between passes")
            pass_output = inside(output / f"pass-{pass_number}")
            pass_output.mkdir()
            clone = inside(clone_base / f"pass-{pass_number}")
            baseline = make_clone(clone)
            if manifest["pass_baselines"] and baseline != manifest["pass_baselines"][0]:
                raise RuntimeError("Isolated pass baselines differ")
            manifest["pass_baselines"].append(baseline)
            write(output / "manifest.json", manifest)
            proc, log, state = start(clone, args.url, pass_output / "server.log")
            workflow = {}
            try:
                with httpx.Client(base_url=args.url, timeout=600) as client:
                    for case in fixture["cases"]:
                        entry = {"pass": pass_number, "case_id": case["id"], "question": case["question"], "server_start_status": state}
                        entry["evaluation_reference"] = references.get(case["id"], {})
                        started = time.perf_counter()
                        try:
                            if case["id"] == "Q11b":
                                workflow = correction_workflow(client, args.url, pass_output, case)
                                write(pass_output / "q11-workflow.json", workflow)
                                entry["workflow_setup"] = {"usage": workflow["proposal_chat"].get("usage"), "latency_ms": workflow["proposal_chat"].get("latency_ms")}
                            entry["preconditions"] = preconditions(client, case)
                            if case["id"] == "Q11b":
                                entry["workflow"] = {"reviewer": REVIEWER, "purpose": workflow["purpose"], "accepted": True}
                            # No expected answer, evaluator hint or previous case session
                            # enters chat. Q11 is the sole documented correction setup.
                            response = client.post("/api/chat", json={"message": case["question"]})
                            response.raise_for_status()
                            entry["response"] = response.json()
                            if entry["response"].get("model") != "gpt-6-luna":
                                raise RuntimeError("Benchmark chat model changed")
                        except Exception as exc:
                            # Do not emit provider bodies/keys; app responses may be saved
                            # when successful, failures have only bounded exception types.
                            entry["error"] = {"type": type(exc).__name__, "message": str(exc)[:400] if not isinstance(exc, httpx.HTTPError) else "HTTP request failed; inspect isolated server artifact"}
                        entry["wall_latency_ms"] = round((time.perf_counter() - started) * 1000)
                        executions.append(entry)
                        jsonl(output / "executions.jsonl", executions)
                        write(pass_output / (case["id"] + ".json"), entry)
                        print(f"pass {pass_number} {case['id']}: {'ERROR' if entry.get('error') else 'captured'}", flush=True)
            finally:
                stop(proc, log)
            if files_hash(clone / "project-meridian_Avathon/project-meridian") != frozen["evidence"]:
                raise RuntimeError("Isolated workflow altered original evidence bytes")
            if files_hash(clone / "generated") != frozen["generated"]:
                raise RuntimeError("Isolated workflow altered generated baseline evidence")
            # Q11 workflow mutations are confined to clone. All baseline inputs
            # and production append-only decisions must still hash identically.
            if frozen_inputs() != frozen:
                raise RuntimeError("Benchmark changed production inputs or decisions")
        manifest["status"] = "executed; independent judge and human spot-check pending"
        manifest["production_evidence_and_decisions_unchanged"] = True
    except BaseException as exc:
        manifest["status"] = "incomplete"
        manifest["error_type"] = type(exc).__name__
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        write(output / "manifest.json", manifest)
        jsonl(output / "executions.jsonl", executions)
        score(output)


def main():
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("compile", help="Derive machine-readable cases from the canonical draft")
    compile_parser.add_argument("--output", required=True)
    run_parser = commands.add_parser("run", help="Actions only: isolated 42-question two-pass capture")
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--url", default="http://127.0.0.1:8002")
    run_parser.add_argument("--passes", type=int, choices=[2], default=2)
    score_parser = commands.add_parser("score", help="Offline scoring/export; never calls a provider")
    score_parser.add_argument("--output", required=True)
    score_parser.add_argument("--judge-results")
    args = parser.parse_args()
    if args.command == "compile":
        write(inside(args.output), compile_draft(DRAFT))
    elif args.command == "score":
        score(inside(args.output), inside(args.judge_results) if args.judge_results else None)
    else:
        run(args)


if __name__ == "__main__":
    main()
