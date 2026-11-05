"""Cumulative deterministic V1/V2 checks; exit 0 is software evidence only.

From development/: uv run python scripts/check_milestone.py V1 (or V2..V5).
ROOT dispatches this on Actions with test/prep extras, plus cad for V2 onward.
Missing/failed required checks exit 1; skipped/pending required software exits 2.
Live, human, visual, semantic and benchmark evidence stays explicitly pending.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
TESTING = ROOT / "testing"
GATES = ("V1", "V2", "V3", "V4", "V5")


@dataclass(frozen=True)
class Check:
    name: str
    gate: str
    paths: tuple[str, ...]
    pytest: bool = True
    remote_only: bool = False


# The PLAN behavior table supplies the expectations. These existing suites own
# the detailed matrices; the gate suites add only the missing integration paths.
CHECKS = (
    Check("launch", "V1", ("testing/reports/b00/A01-scaffold/smoke_checks.py",), pytest=False),
    Check("contracts", "V1", ("testing/smoke/A02-contracts/check_contracts.py",), pytest=False),
    Check("knowledge", "V1", tuple("testing/tests/" + name + ".py" for name in (
        "test_drawings", "test_bom_m1", "test_decisions_m1", "test_runner_m1",
        "test_vision_jobs_m1", "test_matching_m1", "test_prepare_m1",
        "test_source_runtime", "test_source_assets", "test_server", "test_knowledge"))),
    Check("core", "V2", tuple("testing/tests/" + name + ".py" for name in (
        "test_tools", "test_chat_history", "test_grounded_chat", "test_review_m1", "test_core"))),
    Check("geometry", "V2", ("testing/tests/test_cad_build.py",), remote_only=True),
)
FUTURE = {
    "V3": "testing/frontend/mvp.spec.ts",
    "V4": "testing/tests/test_review_trust.py",
    "V5": "testing/frontend/polish.spec.ts",
}


def pytest_result(path: Path, suites: tuple[str, ...], exit_code: int) -> dict:
    """Read standard pytest JUnit evidence, including skips and empty suites."""
    try:
        cases = list(ET.parse(path).iter("testcase"))
    except (OSError, ET.ParseError):
        return {"outcome": "FAIL", "reason": "Pytest did not produce readable JUnit evidence."}
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    seen = set()
    for case in cases:
        seen.update(case.get("classname", "").split("."))
        kind = ("failed" if case.find("failure") is not None or case.find("error") is not None
                else "skipped" if case.find("skipped") is not None else "passed")
        counts[kind] += 1
    missing = [suite for suite in suites if Path(suite).stem not in seen]
    if exit_code not in {0, 5} or counts["failed"]:
        outcome, reason = "FAIL", "Pytest failed; inspect the saved log and JUnit report."
    elif exit_code == 5 or not cases or missing:
        outcome, reason = "MISSING", "A required suite collected no attributable test cases."
    elif counts["skipped"]:
        outcome, reason = "SKIPPED", "Required cases were skipped/xfail; software qualification is incomplete."
    else:
        outcome, reason = "PASS", "Every required suite collected cases and all cases passed."
    return {"outcome": outcome, "reason": reason, "counts": counts, "missing_suites": missing}


def run_check(check: Check, directory: Path) -> dict:
    result = {"name": check.name, "gate": check.gate, "kind": "software", "required": True,
              "suites": list(check.paths)}
    junit = directory / (check.name + ".xml")
    log = directory / (check.name + ".txt")
    command = [sys.executable, "-B"]
    if check.pytest:
        command += ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "xfail_strict=true",
                    "--basetemp=" + str(TESTING / "tmp/milestones" / check.name),
                    "--junitxml=" + str(junit)]
    command += [str(ROOT / path) for path in check.paths]
    result.update(command=command, cwd=str(TESTING))
    missing = [path for path in check.paths if not (ROOT / path).is_file()]
    if missing:
        return {**result, "outcome": "MISSING", "reason": "Required suite/script files are absent.",
                "missing_suites": missing}
    if check.remote_only and os.environ.get("GITHUB_ACTIONS") != "true":
        return {**result, "outcome": "SKIPPED", "reason": "CAD checks run only in ROOT's remote Actions slot."}
    # Never consume a previous invocation's JUnit file after an interrupted run.
    junit.unlink(missing_ok=True)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    # Deterministic suites need no application/provider credentials. Explicit
    # test fakes are supplied inside their isolated fixtures, never inherited.
    for key in tuple(environment):
        if any(token in key.upper() for token in ("API_KEY", "TOKEN", "SECRET", "AUTHORIZATION")):
            environment.pop(key)
    for key in ("MERIDIAN_INPUTS_PATH", "MERIDIAN_TEST_INPUTS_PATH", "MERIDIAN_CHAT_HISTORY_DIR",
                "MERIDIAN_SECRETS_DIR", "MERIDIAN_DEBUG"):
        environment.pop(key, None)
    if check.remote_only:
        environment["MERIDIAN_REQUIRE_CAD"] = "1"
    try:
        completed = subprocess.run(command, cwd=TESTING, env=environment, capture_output=True,
                                   text=True, timeout=900)
        log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        result.update(exit_code=completed.returncode, log=str(log))
        if check.pytest:
            result.update(pytest_result(junit, check.paths, completed.returncode), junit=str(junit))
        else:
            result.update(outcome="PASS" if completed.returncode == 0 else "FAIL",
                          reason="Required script exit status; inspect saved output.")
    except subprocess.TimeoutExpired as error:
        output = b"".join(part if isinstance(part, bytes) else (part or "").encode()
                          for part in (error.stdout, error.stderr))
        log.write_bytes(output)
        result.update(outcome="FAIL", reason="Required check exceeded 900 seconds.", log=str(log))
    except OSError as error:
        result.update(outcome="FAIL", reason="Could not execute required check: " + type(error).__name__)
    return result


def pending_evidence(gate: str) -> list[dict]:
    items = [
        ("live_readers", "live", "Actual source-bound Sol/Opus execution, accuracy and real prep counts."),
        ("source_spot_check", "human", "Independent raw-evidence/human checks; synthetic reviews give no credit."),
        ("three_model_fidelity", "source", "Three actual source-derived reconstructions and all-view fidelity."),
        ("visual_and_fresh_clone", "visual", "Actual drawing/3D demos, saved outputs and fresh-clone launch."),
        ("live_luna", "live", "Actual Luna answers and measured usage; scripted Responses give no live credit."),
        ("final20_benchmark", "benchmark", "Unimplemented M23 benchmark slice; two runs, scoring and usage."),
    ]
    if GATES.index(gate) >= GATES.index("V3"):
        items.append(("V3_semantic", "semantic", "Scheduled full M1 assignment review of the exact candidate."))
    if GATES.index(gate) >= GATES.index("V4"):
        items.append(("V4_semantic", "semantic", "Scheduled M2 trust delta review of the exact candidate."))
    return [{"name": name, "kind": kind, "required": False, "required_for_release": True,
             "outcome": "PENDING", "reason": reason}
            for name, kind, reason in items]


def qualify(gate: str, directory: Path) -> tuple[dict, int]:
    directory.mkdir(parents=True, exist_ok=True)
    index = GATES.index(gate)
    checks = [run_check(check, directory) for check in CHECKS if GATES.index(check.gate) <= index]
    for future, suite in FUTURE.items():
        checks.append({"name": future + "_software", "gate": future, "kind": "software",
                       "required": GATES.index(future) <= index, "outcome": "PENDING", "suites": [suite],
                       "reason": "This runner slice has not implemented this checkpoint; file presence gives no credit.",
                       "suite_present": (ROOT / suite).is_file()})
    required = [check["outcome"] for check in checks if check["required"]]
    if any(outcome in {"FAIL", "MISSING"} for outcome in required):
        software, code = "FAIL", 1
    elif any(outcome != "PASS" for outcome in required):
        software, code = "BLOCKED", 2
    else:
        software, code = "PASS", 0
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    report = {"schema": "meridian-milestone/v1", "gate": gate, "commit": commit,
              "github_sha": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
              "completed_at": datetime.now(timezone.utc).isoformat(), "software_outcome": software,
              "outcome": "FAIL" if software == "FAIL" else "PENDING", "exit_code": code,
              "exit_policy": "Only required software determines exit status; pending release evidence prevents a full gate PASS.",
              "scope": "Cumulative V1/V2 deterministic software only; no full MVP, release or source-fidelity claim.",
              "checks": checks + pending_evidence(gate)}
    return report, code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=GATES)
    parser.add_argument("--report", type=Path, help="JSON report path inside testing/ (default reports/verification/<gate>.json)")
    args = parser.parse_args(argv)
    path = (args.report or TESTING / "reports/verification" / (args.gate + ".json")).resolve()
    if not path.is_relative_to(TESTING.resolve()):
        parser.error("Report and check evidence must stay under testing/.")
    report, code = qualify(args.gate, path.parent / (path.stem + "-checks"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for check in report["checks"]:
        print(f"{check['outcome']}: {check['name']} — {check['reason']}")
    print(f"{args.gate} software: {report['software_outcome']}; full evidence: {report['outcome']}; report: {path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
