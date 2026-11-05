"""Remote M23 core qualification; scripted Responses, real corpus/API/built UI.

From product/testing on the queued harness-v2 Actions runner:
    uv run --project ../development --locked --extra test --extra prep python -B ci/core_flow.py

Dependencies are installed by verify.yml. No live AI, prep jobs, CAD or V1-V5
verdict is included. Existing broader M11 fixture failures remain out of scope.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "testing/reports/core-flow"
INPUTS = ROOT / "testing/runs/deterministic-inputs/inputs.json"
SUITES = ("test_core_flow.py", "test_grounded_chat.py", "test_chat_history.py",
          "test_source_runtime.py", "test_tools.py")
CORE_CASE = "test_real_part_answer_drawing_and_saved_conversation_restart"
SCOPE = "Actual corpus, scripted Responses, real API and built UI; no live Luna, CAD or V1-V5 qualification"


def save(report):
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    (REPORTS / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(command, log, timeout):
    with (REPORTS / log).open("w", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=ROOT / "testing", stdout=output, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    if result.returncode:
        print((REPORTS / log).read_text(encoding="utf-8", errors="replace")[-8000:], flush=True)
        raise RuntimeError(f"Exit {result.returncode}: {shlex.join(command)}; see {log}")


def verify_suites(report):
    cases = ET.parse(REPORTS / "core-suites.xml").findall(".//testcase")
    mandatory = [case for case in cases if case.get("name") == CORE_CASE
                 and case.get("classname", "").split(".")[-1] == "test_core_flow"]
    assert len(mandatory) == 1, "The mandatory real-corpus core-flow case did not run"
    assert cases and not any(case.find(tag) is not None for case in cases
                             for tag in ("skipped", "failure", "error")), "Core suites must pass without skips"
    report["python_cases"] = len(cases)
    report["mandatory_case"] = CORE_CASE


async def browser_case(report):
    import uvicorn
    import anyio.to_thread
    from backend import contracts as c
    from backend.app.main import create_app
    from backend.app.tools import FactTools
    from backend.loader.records import RecordRegistry
    from backend.settings import Settings, load_settings
    # Reuse the integration test's bounded client. It derives its answer from
    # actual function_call_output JSON and has no SDK/network implementation.
    from test_core_flow import ScriptedAsyncResponses

    manifest_path = ROOT / "development/inputs/project-meridian/dataset/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = RecordRegistry.from_inputs(INPUTS, manifest_path, decisions=None, records_path=None)
    tools = FactTools(registry)
    records = {record.id: record for record in registry.records}
    selected = None
    for asset in sorted(manifest["assets"], key=lambda item: item["id"]):
        if asset.get("distribution") != "clean" or not asset["id"].startswith("D-"):
            continue
        record = records.get(c.drawing_part_name(asset["id"]))
        if record is None or record.drawing is None:
            continue
        for name, fact in sorted(tools.get_facts(record.id).facts.items()):
            targets = [index for index, source in enumerate(fact.sources)
                       if source.target.kind == "drawing" and source.target.drawing_id == asset["id"]
                       and source.target.page == 1 and source.target.box is not None]
            if name != record.id and fact.part_id == record.id and fact.display.state == "value" and targets:
                selected = record, fact, targets[0]
                break
        if selected:
            break
    assert selected, "Actual extraction has no usable source-backed drawing fact"
    record, fact, source_index = selected
    assert not record.fixture and not record.synthetic and not fact.fixture and not fact.synthetic
    question = f"What is the recorded source value for {fact.fact} on part {record.id}?"
    image = INPUTS.parent / record.drawing.image
    case = dict(commit=os.environ["GITHUB_SHA"], part_id=record.id, drawing_id=record.drawing.id,
                display_name=record.display_name, fact=fact.model_dump(mode="json"), question=question,
                drawing_source_index=source_index,
                answer_prefix=f"Recorded source value: {json.dumps(fact.display.value, ensure_ascii=False)}",
                image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                geometry=record.drawing.page_geometry[0].model_dump(mode="json"))
    case_path = REPORTS / "source-case.json"
    case_path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["source_case"] = case
    runtime = Path(tempfile.mkdtemp(prefix="browser-", dir=ROOT / "testing/tmp/core-flow"))
    os.environ["MERIDIAN_CHAT_HISTORY_DIR"] = str(runtime / "history")
    data = deepcopy(load_settings().data)
    data["paths"]["frontend_dist"] = str(ROOT / "development/frontend/dist")
    data["paths"]["chat_history"] = "history"
    data["chat"]["credentials"]["secrets_dir"] = "unused-secrets"
    settings = Settings(root=runtime, data=data)
    assert not settings.chat_key_path.exists()
    provider = ScriptedAsyncResponses(record.id, fact.fact)
    app = create_app(settings, registry=registry, inputs_root=INPUTS.parent, client=provider)
    # One API worker; sync routes and tool/storage offloads each have one slot.
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    anyio.to_thread.current_default_thread_limiter().total_tokens = 1
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, workers=1,
                                          loop="asyncio", http="h11", access_log=False, log_level="warning"))
    process = None
    with socket.socket() as listener, (REPORTS / "browser-output.txt").open("w", encoding="utf-8") as output:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async def ready():
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("API server stopped before browser startup")
                    await asyncio.sleep(.05)
            await asyncio.wait_for(ready(), timeout=20)
            process = await asyncio.create_subprocess_exec(
                "node", str(ROOT / "testing/tests/core_ui.cjs"), url, str(case_path), str(REPORTS),
                cwd=ROOT / "testing", stdout=output, stderr=subprocess.STDOUT)
            if await asyncio.wait_for(process.wait(), timeout=240) != 0:
                print((REPORTS / "browser-output.txt").read_text(encoding="utf-8", errors="replace")[-8000:], file=sys.stderr)
                raise AssertionError("Browser failed; see browser-output.txt")
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            server.should_exit = True
            try:
                await asyncio.wait_for(serving, timeout=15)
            except asyncio.TimeoutError:
                server.force_exit = True
                raise
    result = json.loads((REPORTS / "browser.json").read_text(encoding="utf-8"))
    assert result["outcome"] == "PASS" and result["commit"] == os.environ["GITHUB_SHA"]
    assert len(provider.requests) == 3 and provider.observed_fact == fact
    saved = c.ConversationState.model_validate_json(
        (settings.chat_history_dir / f"conversation-{result['conversation_id']}.json").read_bytes())
    assert len(saved.detail.messages) == 2 and len(saved.ledger.entries) == 2
    assert saved.detail.messages[0].text == question
    assert saved.detail.messages[1].response.facts == {fact.fact: fact}
    report["scripted_response_calls"] = len(provider.requests)
    report["browser"] = result


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or os.environ.get("GITHUB_REF") != "refs/heads/harness-v2" or not os.environ.get("GITHUB_SHA")):
        raise SystemExit("SKIPPED: core extraction/build/browser runs only in the queued harness-v2 Linux Actions job")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (ROOT / "testing/tmp/core-flow").mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(ROOT / "development"), str(ROOT / "testing/tests")]
    os.environ.update(MERIDIAN_SECRETS_DIR=str(ROOT / "testing/tmp/core-flow/unused-secrets"), MERIDIAN_DEBUG="0",
                      MERIDIAN_CHAT_HISTORY_DIR=str(ROOT / "testing/tmp/core-flow/import-history"),
                      PYTHONPATH=str(ROOT / "development"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="",
                      PYTHONDONTWRITEBYTECODE="1")
    os.environ.pop("MERIDIAN_INPUTS_PATH", None)
    for name in list(os.environ):
        if name.upper().endswith(("API_KEY", "API_KEYS", "AUTH_TOKEN")):
            del os.environ[name]
    commands = {
        "extraction": [sys.executable, "-B", "ci/checks.py", "extract"],
        "core-suites": [sys.executable, "-B", "-m", "pytest", "-q", *[f"tests/{name}" for name in SUITES],
                        "-p", "no:cacheprovider", "--basetemp=tmp/pytest-core", "--junitxml=" + str(REPORTS / "core-suites.xml")],
        "typecheck": ["npm", "--prefix", "../development/frontend", "run", "typecheck"],
        "build": ["npm", "--prefix", "../development/frontend", "run", "build"],
        "frontend-manifest": [sys.executable, "-B", "ci/checks.py", "manifest"],
        "browser": ["node", "tests/core_ui.cjs", "<owned-loopback-API>", str(REPORTS / "source-case.json"), str(REPORTS)],
    }
    source_files = ["testing/ci/core_flow.py", "testing/tests/core_ui.cjs", "testing/ci/checks.py",
                    "development/backend/app/main.py", "development/backend/app/chat.py", "development/backend/app/tools.py",
                    "development/backend/loader/records.py", "development/backend/loader/drawings.py",
                    "development/backend/loader/bom.py", "development/backend/contracts.py",
                    *[f"testing/tests/{name}" for name in SUITES]]
    report = dict(schema="meridian-core-flow/v1", commit=os.environ["GITHUB_SHA"], run_id=os.environ.get("GITHUB_RUN_ID"),
                  run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"), branch="harness-v2", scope=SCOPE,
                  source_sha256={name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                 for name in source_files},
                  source_validation="Manifest/hash binding and actual image/tool values; extraction accuracy is not independently reviewed",
                  suites=list(SUITES), outcome="FAIL",
                  checks=[dict(name=name, command=shlex.join(command), outcome="SKIPPED", evidence="Not reached")
                          for name, command in commands.items()])
    save(report)
    for check in report["checks"]:
        name = check["name"]
        try:
            if name == "browser":
                asyncio.run(browser_case(report))
            else:
                run_command(commands[name], name + "-output.txt", timeout=600)
                if name == "extraction":
                    assert INPUTS.is_file(), "Extraction did not publish required inputs.json"
                    report["inputs_sha256"] = hashlib.sha256(INPUTS.read_bytes()).hexdigest()
                    os.environ["MERIDIAN_TEST_INPUTS_PATH"] = str(INPUTS)
                elif name == "core-suites":
                    verify_suites(report)
            check.update(outcome="PASS", evidence="browser.json" if name == "browser" else name + "-output.txt")
            print(f"PASS: {name}", flush=True)
        except Exception:
            diagnostic = traceback.format_exc()
            (REPORTS / "failure.txt").write_text(diagnostic, encoding="utf-8")
            check.update(outcome="FAIL", evidence="failure.txt")
            for remaining in report["checks"]:
                if remaining["outcome"] == "SKIPPED":
                    remaining["evidence"] = f"Prerequisite failed: {name}"
            print(diagnostic, file=sys.stderr, flush=True)
            save(report)
            return 1
        save(report)
    report["outcome"] = "PASS"
    save(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
