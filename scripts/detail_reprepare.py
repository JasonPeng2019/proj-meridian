"""Redo source-grounded geometry prep; CLI calls only, CAD remains on Actions.

Image dimensions and templates have separate exact-proposal verification receipts.
The complete batch is staged before publishing; every prior decision stays intact.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.ai import dimensions, pipeline, runner
from backend.paths import GENERATED, ROOT, configure_environment, inside
from scripts.expand_models import assess, digest, expansion_job, raw_drawings, require_settings, sequential_readers

DETAIL_PROTOCOL = "drawing-detail-reprepare-v2"
DETAIL_PROMPT = """
DETAIL-FIDELITY PASS: inspect EVERY original view, section, detail, leader and
functional note. Enumerate through and blind holes, side-drilled holes, stepped
holes/counterbores, countersinks, recesses, slots, notches, corner chamfers,
grooves and indents before deciding which supported features to emit. Inspect
the original evidence afresh, not an earlier template or reconstruction.
Never omit an expressible fully dimensioned feature merely because the primary
outline is easy to generate. Use all relevant supplied parsed AND verified image
dimension IDs. Image-only readings remain AI evidence with their own receipts.
Check each feature's axis, opening face, size, depth, count, and complete location.
An unspecified edge break is not permission to add an arbitrary chamfer. Missing
pitch/coordinates are not permission to measure pixels or assume symmetry.
Describe EACH genuinely unsupported or undimensioned detail in features_omitted,
distinguishing a missing source dimension from a generator limitation. Preserve
all independently supported cuts. Do not label a partial reconstruction complete.
"""


def main():
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", type=Path, help="Resume this batch's staged checkpoint")
    args = parser.parse_args()
    require_settings()
    drawings = raw_drawings()
    image_ids = [did for did, drawing in sorted(drawings.items()) if drawing.get("degraded")]
    if not args.execute:
        print(json.dumps({"protocol": DETAIL_PROTOCOL, "image_dimension_jobs": image_ids,
                          "template_jobs": sorted(drawings), "reader_concurrency": 1,
                          "providers": {r: runner.reader_settings(r) for r in ("codex", "claude")}}))
        return
    baseline = {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "decisions").glob("*.json")}
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in
                     [GENERATED / "drawings.json", *[inside(GENERATED / image) for d in drawings.values() for image in d["images"]]]}
    raw_hash = digest(GENERATED / "drawings.json")
    original = json.loads((GENERATED / "ai_results.json").read_text(encoding="utf-8"))
    if args.resume:
        folder = inside(args.resume)
        checkpoint = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
        if checkpoint["protocol"] != DETAIL_PROTOCOL or checkpoint["raw_drawings_sha256"] != raw_hash:
            raise ValueError("Resume evidence/protocol changed")
        if checkpoint.get("complete"):
            raise ValueError("This batch is already complete")
        results = checkpoint["results"]
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder = inside(runner.CACHE / "detail-reprepare" / stamp)
        results = []
        runner.write_json(folder / "previous-output.json", original)
    started = time.monotonic()

    def save(complete=False, **extra):
        runner.write_json(folder / "checkpoint.json", {
            "protocol": DETAIL_PROTOCOL, "complete": complete,
            "raw_drawings_sha256": raw_hash, "source_hashes": source_hashes,
            "results": results, **extra})

    def run(job):
        existing = next((r for r in results if r["job"]["id"] == job["id"]), None)
        if existing is not None:
            if runner.fingerprint(existing["job"]) != runner.fingerprint(job):
                raise ValueError("Resume job inputs changed: " + job["id"])
            return existing
        print(f"Starting {job['id']}", flush=True)
        result = pipeline.run_retry(pipeline.execute(job))
        results.append(result)
        save()
        print(json.dumps({"job": job["id"], "states": result["states"]}), flush=True)
        return result

    save()
    with sequential_readers():
        for did in image_ids:
            run(dimensions.job(drawings[did]))
        index = pipeline.assemble(results, drawings, {}).get("dimension_evidence", {})
        augmented = {did: dimensions.attach(drawing, index.get(did)) for did, drawing in drawings.items()}
        assessments = {}
        for did, drawing in sorted(augmented.items()):
            job = expansion_job(drawing)
            job["id"] = f"detail:{did}:{DETAIL_PROTOCOL}"
            job["prompt"] += "\n" + DETAIL_PROMPT
            result = run(job)
            template, assessment, _ = assess(result, augmented)
            assessments[did] = assessment
            runner.write_json(folder / (did + "-template.json"), template)
            print(json.dumps({"drawing": did, "eligible": template["cad_ready"],
                              "cuts": len(template.get("features", [])),
                              "features_status": template.get("features_status"),
                              "omissions": template.get("omitted_feature_notes", [])}), flush=True)
    assembled = pipeline.assemble(results, augmented, {})
    output = copy.deepcopy(json.loads((GENERATED / "ai_results.json").read_text(encoding="utf-8")))
    output["dimension_evidence"] = {**output.get("dimension_evidence", {}), **index}
    output["templates"] = {**output.get("templates", {}), **assembled["templates"]}
    output["detail_assessments"] = assessments
    metrics = {**assembled["metrics"], "wall_time_ms": round((time.monotonic() - started) * 1000)}
    output.setdefault("prep_runs", []).append({"kind": DETAIL_PROTOCOL, "protocol": pipeline.PROTOCOL,
        "receipt": str((folder / "checkpoint.json").relative_to(GENERATED)), "metrics": metrics})
    output["previous_geometry_prep"] = {"receipt": str((folder / "previous-output.json").relative_to(GENERATED)),
                                        "sha256": runner.fingerprint(original)}
    for name, expected in source_hashes.items():
        if digest(inside(name)) != expected:
            raise ValueError("Original evidence changed during prep: " + name)
    if any(not inside(name).is_file() or digest(inside(name)) != expected for name, expected in baseline.items()):
        raise ValueError("A prior human decision changed during prep")
    save(complete=True, metrics=metrics, decisions_unchanged=True, assessments=assessments)
    runner.write_json(GENERATED / "ai_results.json", output)
    runner.write_json(runner.CACHE / "artifacts/ai_results.json", output)
    # Merge existing evidence only; no PDF rendering, geometry generation, or API.
    from backend.loader.records import assemble_records
    bom = json.loads((GENERATED / "bom.json").read_text(encoding="utf-8"))
    assemble_records(drawings, bom)
    runner.write_json(folder / "summary.json", {"complete": True, "protocol": DETAIL_PROTOCOL,
                      "metrics": metrics, "decisions_unchanged": True,
                      "eligible_drawings": [did for did, a in assessments.items() if a["status"] == "ready_for_cad"]})
    print(json.dumps({"complete": True, "receipt": str(folder.relative_to(ROOT)), "metrics": metrics}), flush=True)


if __name__ == "__main__":
    main()
