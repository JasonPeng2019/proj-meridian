"""Redo source-grounded geometry prep; CLI calls only, CAD remains on Actions.

Image dimensions and templates have separate exact-proposal verification receipts.
The complete batch is staged before publishing; every prior decision stays intact.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.ai import dimensions, eligibility, pipeline, runner
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


def screen_job(drawing):
    """Qualitative body screening precedes numeric extraction for new evidence."""
    did = drawing['id']
    return {"id": f"screen:{did}:{eligibility.PROTOCOL}", "kind": "template", "drawing": did,
            "keys": ["cad_eligibility"], "numbers": {}, "sources": sorted(pipeline.source_ids(drawing)),
            "images": [str(inside(GENERATED / image)) for image in drawing['images']],
            "prompt": pipeline.BASE_PROMPT + "\nQUALITATIVE TEMPLATE CAPABILITY SCREEN ONLY.\n"
            "Inspect the original drawing views. Do not transcribe numeric dimensions, locate holes, "
            "or extract a complete feature list. Decide only whether the essential body fits the "
            "provided reusable base-body contract. Missing numeric evidence or hole positions alone "
            "does not make a body structurally unsupported; uncertain body shape stays unknown. "
            "Never substitute a bounding rectangle/circle for a formed or custom-profiled body. "
            "Return only cad_eligibility: known object with exactly supported, constant_thickness, "
            "outline_exact (booleans), reason (source-specific structural explanation), "
            "essential_uncertainty and omitted_minor_features (string arrays). supported=true "
            "requires a certain compatible base shape, constant extrusion and empty essential_uncertainty. "
            "This is routing, not a complete reconstruction or human approval. Cite original source IDs.\n" +
            runner.json_text({"drawing": did, "source_ids": sorted(pipeline.source_ids(drawing)),
                              "capabilities": eligibility.CAPABILITIES,
                              "notes": drawing.get('fields', {}).get('notes')})}


def route_drawings(drawings, original):
    return {did: eligibility.route(drawing, original.get('templates', {}).get(did),
                                  original.get('template_routing', {}).get(did))
            for did, drawing in sorted(drawings.items())}


def main():
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", type=Path, help="Resume this batch's staged checkpoint")
    args = parser.parse_args()
    require_settings()
    drawings = raw_drawings()
    original = json.loads((GENERATED / "ai_results.json").read_text(encoding="utf-8"))
    routing = route_drawings(drawings, original)
    # D-017's fused 4x1,0 corner note is visible but absent from the
    # deterministic numeric index. It needs the same verified image pass.
    image_ids = [did for did, drawing in sorted(drawings.items())
                 if routing[did]['action'] != 'reuse_unsupported' and (drawing.get("degraded") or did == "D-017")]
    if not args.execute:
        print(json.dumps({"protocol": DETAIL_PROTOCOL, "image_dimension_jobs": image_ids,
                          "template_jobs": [did for did in drawings if routing[did]['action'] == 'detailed_candidate'],
                          "routing": routing, "reader_concurrency": 1,
                          "providers": {r: runner.reader_settings(r) for r in ("codex", "claude")}}))
        return
    baseline = {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "decisions").glob("*.json")}
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in
                     [GENERATED / "drawings.json", *[inside(GENERATED / image) for d in drawings.values() for image in d["images"]]]}
    raw_hash = digest(GENERATED / "drawings.json")
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
            "results": results, "routing": routing, **extra})

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
        for did, decision in list(routing.items()):
            if decision['action'] != 'screen_required':
                continue
            result = run(screen_job(drawings[did]))
            field = pipeline.resolved(result, 'cad_eligibility')
            routing[did] = eligibility.route(drawings[did], original.get('templates', {}).get(did), {
                'source_sha256': drawings[did]['sha256'],
                'capabilities_sha256': eligibility.CAPABILITIES_SHA256, 'cad_eligibility': field})
            if routing[did]['action'] == 'screen_required':
                routing[did]['reason'] = 'Qualitative screen remains unresolved; detailed geometry is deferred. ' + routing[did]['reason']
        save()
        image_ids = [did for did, drawing in sorted(drawings.items())
                     if routing[did]['action'] == 'detailed_candidate' and (drawing.get('degraded') or did == 'D-017')]
        for did in image_ids:
            for job in dimensions.jobs(drawings[did]):
                run(job)
        ordinary_results = [result for result in results if not result['job']['id'].startswith('screen:')]
        index = pipeline.assemble(ordinary_results, drawings, {}).get("dimension_evidence", {})
        augmented = {did: dimensions.attach(drawing, index.get(did)) for did, drawing in drawings.items()}
        assessments = {}
        for did, drawing in sorted(augmented.items()):
            existing = next((r for r in results if r['job']['id'] == f'detail:{did}:{DETAIL_PROTOCOL}'), None)
            if routing[did]['action'] != 'detailed_candidate' and existing is None:
                assessments[did] = {'drawing': did, 'status': 'blocked' if routing[did]['action'] == 'reuse_unsupported' else 'screen_unresolved',
                                    'reason': routing[did]['reason'], 'source_sha256': drawing['sha256'],
                                    'fresh_detailed_extraction': False, 'routing': routing[did]}
                print(json.dumps({'drawing': did, 'routing': routing[did]['action'], 'detail_skipped': True}), flush=True)
                continue
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
    assembled = pipeline.assemble([r for r in results if not r['job']['id'].startswith('screen:')], augmented, {})
    output = copy.deepcopy(json.loads((GENERATED / "ai_results.json").read_text(encoding="utf-8")))
    output["dimension_evidence"] = {**output.get("dimension_evidence", {}), **index}
    output["templates"] = {**output.get("templates", {}), **assembled["templates"]}
    output['template_routing'] = routing
    for did, decision in routing.items():
        if did not in assembled['templates'] and decision.get('assessment'):
            template = output['templates'].setdefault(did, {'part': did, 'template': 'flat_part',
                'outline': {'state': 'unknown'}, 'thickness': {'state': 'unknown'}, 'features': [],
                'source_sha256': drawings[did]['sha256']})
            template['cad_eligibility'] = copy.deepcopy(decision['assessment'])
            template['cad_ready'] = False
            template['blocking_fields'] = list(dict.fromkeys([*template.get('blocking_fields', []), 'cad_eligibility']))
    output["detail_assessments"] = assessments
    metrics = {**assembled["metrics"], "wall_time_ms": round((time.monotonic() - started) * 1000)}
    output.setdefault("prep_runs", []).append({"kind": DETAIL_PROTOCOL, "protocol": pipeline.PROTOCOL,
        "receipt": (folder / "checkpoint.json").relative_to(GENERATED).as_posix(), "metrics": metrics})
    output["previous_geometry_prep"] = {"receipt": (folder / "previous-output.json").relative_to(GENERATED).as_posix(),
                                        "sha256": runner.fingerprint(original)}
    for name, expected in source_hashes.items():
        if digest(inside(name)) != expected:
            raise ValueError("Original evidence changed during prep: " + name)
    if any(not inside(name).is_file() or digest(inside(name)) != expected for name, expected in baseline.items()):
        raise ValueError("A prior human decision changed during prep")
    # Stage a candidate. Never replace live data or invalidate working meshes
    # before the remote CAD and browser checks have produced a matching release.
    candidate = inside(folder / 'candidate/generated')
    runner.write_json(candidate / 'ai_results.json', output)
    from backend.loader.records import assemble_records
    bom = json.loads((GENERATED / "bom.json").read_text(encoding="utf-8"))
    for name in ('bom.json', 'drawings.json', 'readme.json'):
        if (GENERATED / name).is_file():
            shutil.copyfile(GENERATED / name, candidate / name)
    assemble_records(drawings, bom, output=candidate)
    save(complete=True, published=False, candidate=candidate.relative_to(ROOT).as_posix(),
         candidate_sha256=digest(candidate / 'ai_results.json'), metrics=metrics,
         decisions_unchanged=True, assessments=assessments)
    runner.write_json(folder / "summary.json", {"complete": True, "protocol": DETAIL_PROTOCOL,
                      "metrics": metrics, "decisions_unchanged": True,
                      "eligible_drawings": [did for did, a in assessments.items() if a["status"] == "ready_for_cad"]})
    print(json.dumps({"complete": True, "receipt": str(folder.relative_to(ROOT)), "metrics": metrics}), flush=True)


if __name__ == "__main__":
    main()
