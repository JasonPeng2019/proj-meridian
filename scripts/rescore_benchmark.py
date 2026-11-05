"""Replay saved answers under the current rubric, without changing the capture.

The catalog oracle is rebuilt only from hash-matching original prepared inputs.
No chat calls, CAD, extraction, browser or builds are started here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.paths import ROOT, configure_environment, inside
from backend.evaluation.benchmark import compile_draft, fingerprint, judge_payload, load_judgments, report_results
from backend.evaluation.contracts import VERSION, catalog_reference, contract
from scripts.run_benchmark import jsonl, write


def sha(path: Path) -> str:
    return hashlib.sha256(inside(path).read_bytes()).hexdigest()


def reference_for_capture(manifest: dict, reference_root: Path = ROOT) -> tuple[dict, dict]:
    from backend.app.store import Store
    required = ["records.json", "bom.json", "ai_results.json", "models/manifest.json", "readme.json"]
    hashes = manifest["input_hashes"]
    checked = {}
    for relative in required:
        path = inside(reference_root / "generated" / relative)
        actual = sha(path)
        if hashes["generated"].get(relative) != actual:
            raise ValueError("Original catalog input changed: generated/" + relative)
        checked["generated/" + relative] = actual
    decisions = {p.name: sha(p) for p in (inside(reference_root / "decisions")).glob("*.json")}
    if decisions != hashes["decisions"]:
        raise ValueError("Original decision set changed; cannot reconstruct historical catalog")
    checked.update({"decisions/" + name: value for name, value in decisions.items()})
    return catalog_reference(Store(reference_root)), checked


def rescore(capture: Path, output: Path, judge_results: Path | None = None, reference_root: Path = ROOT) -> dict:
    capture, output = inside(capture), inside(output)
    if output == capture or output.is_relative_to(capture):
        raise ValueError("Revised evaluation must be separate from the immutable capture")
    fixture = json.loads((capture / "cases.json").read_text(encoding="utf-8"))
    manifest = json.loads((capture / "manifest.json").read_text(encoding="utf-8"))
    if fixture != compile_draft(capture / "benchmark_draft.md") or fixture["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("Frozen cases/draft/manifest do not agree")
    original_hashes = {name: sha(capture / name) for name in (
        "cases.json", "manifest.json", "benchmark_draft.md", "executions.jsonl", "report.json", "judge-results.jsonl")}
    references, reference_hashes = reference_for_capture(manifest, inside(reference_root))
    executions = [json.loads(line) for line in (capture / "executions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {c["id"]: c for c in fixture["cases"]}
    identities = [(e["pass"], e["case_id"]) for e in executions]
    if len(set(identities)) != len(identities) or any(p not in (1, 2) or cid not in by_id for p, cid in identities):
        raise ValueError("Duplicate or unknown execution identities")
    for execution in executions:
        if execution["question"] != by_id[execution["case_id"]]["question"]:
            raise ValueError("Captured question changed")
        execution["evaluation_reference"] = references.get(execution["case_id"], {})
    provenance = {"evaluation_version": VERSION, "capture": capture.relative_to(ROOT).as_posix(),
                  "capture_hashes": original_hashes, "reference_input_hashes": reference_hashes,
                  "evaluation_code_hashes": {name: sha(ROOT / name) for name in (
                      "backend/evaluation/benchmark.py", "backend/evaluation/contracts.py", "scripts/rescore_benchmark.py", "scripts/judge_benchmark.py")},
                  "contracts": {c["id"]: contract(c) for c in fixture["cases"]}}
    provenance["fingerprint"] = fingerprint(provenance)
    receipt = output / "evaluation.json"
    if output.exists() and (not receipt.exists() or json.loads(receipt.read_text(encoding="utf-8")) != provenance):
        raise ValueError("Output directory belongs to a different evaluation; use a new directory")
    payloads = [judge_payload(by_id[e["case_id"]], e, manifest) for e in executions]
    judgments = load_judgments(judge_results, {p["cache_key"] for p in payloads})
    report = report_results(fixture, manifest, executions, judgments)["report"]
    report["evaluation_provenance"] = provenance
    old = json.loads((capture / "report.json").read_text(encoding="utf-8"))
    old_results = {(r["pass"], r["case_id"]): r for r in old["results"]}
    report["comparison"] = [{"pass": r["pass"], "case_id": r["case_id"],
                             "original": old_results[(r["pass"], r["case_id"])]["combined"],
                             "revised": r["combined"]} for r in report["results"]]
    write(receipt, provenance)
    write(output / "reference.json", references)
    jsonl(output / "judge-inputs.jsonl", {p["cache_key"]: p for p in payloads}.values())
    write(output / "report.json", report)
    if any(sha(capture / name) != value for name, value in original_hashes.items()):
        raise RuntimeError("Original capture changed during replay")
    return report


def main():
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--judge-results")
    parser.add_argument("--reference-root", help="Optional original catalog snapshot under this repo; all inputs must match capture hashes")
    args = parser.parse_args()
    report = rescore(inside(args.capture), inside(args.output), inside(args.judge_results) if args.judge_results else None,
                     inside(args.reference_root) if args.reference_root else ROOT)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
