"""Assess additional drawings with sequential Sol proposals and Opus verification.

The default prints a plan. --execute is required for real CLI provider calls.
This prepares evidence-backed templates; CAD generation belongs on Actions.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import yaml

from backend.ai import pipeline, runner
from backend.cad.builder import Unknown, _options, _validate_essential
from backend.paths import GENERATED, ROOT, configure_environment, inside
from scripts.judge_benchmark import wait_for_headroom


EXPANSION_PROTOCOL = "flat-part-expansion-v1"
ELIGIBILITY_KEY = "cad_eligibility"
STRICT_PROMPT = """
ADDITIONAL MVP ELIGIBILITY CHECK (mandatory, independent of dimension readings):
Return the extra requested key cad_eligibility, state known, value_json an object
with EXACT keys: supported (boolean), constant_thickness (boolean), outline_exact
(boolean), reason (nonempty string), essential_uncertainty (array of strings),
omitted_minor_features (array of strings). Cite original drawing source IDs.
supported=true only when this exact part can be represented by the supported
rectangle/circle/ring outline, a single constant thickness (or explicitly printed
alternative constant thicknesses), plus the supported hole/slot cuts. The MAIN
outline must match exactly: do not substitute its bounding rectangle or circle.
Block bent, stepped, revolved, profiled, tapered, nonplanar or assembled parts and
essential notches, lobes, rounded outer corners or other contours the generator
cannot express. Do not classify an essential contour as an omitted minor detail.
Do not infer a constant thickness from an unlabeled number, another part, title,
material, stock convention, scale, pixels, or a familiar standard. Printed numbers
must be linked by the actual view/dimension leaders to the dimension claimed;
detached text and unrelated numbers are not dimension evidence. All numeric
geometry must cite exact supplied parsed drawing-number IDs; the original image
can establish their meaning, but never invent missing numbers or evidence IDs.
If dimensions are absent/unreadable, keep them unknown. Explain which essential
dimension/contour is unresolved. A certain outline and thickness can still produce
an honest partial model when minor holes/slots lack positions or dimensions:
list the omissions, retain only fully supported features, and do not guess them.
Uncertainty about a minor hole alone MUST NOT block the main constant-thickness
solid. For such partials features may be unknown with only certain features in
the array; describe every omission explicitly. The object reason must explain
the specific eligibility decision, including the main view and thickness source.
Do not consult prior AI records, fused application records, existing templates,
benchmark expectations, accepted human decisions, or any other drawings.
"""


def read_json(path):
    return json.loads(inside(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(inside(path).read_bytes()).hexdigest()


def raw_drawings():
    """Only the parser's immutable evidence, never store.records or scan merges."""
    drawings = read_json(GENERATED / "drawings.json")
    for did, drawing in drawings.items():
        if drawing.get("id") != did:
            raise ValueError("Raw drawing ID mismatch: " + did)
        for field in list(drawing.get("fields", {}).values()) + drawing.get("numbers", []) + drawing.get("callouts", []):
            if field.get("method") not in (None, "parsed") or field.get("readers") or field.get("correction"):
                raise ValueError("Expansion requires raw parsed evidence, not fused AI/human fields: " + did)
    return drawings


def expansion_job(drawing):
    job = pipeline.template_job(copy.deepcopy(drawing))
    job["id"] = f"expansion:{drawing['id']}:{EXPANSION_PROTOCOL}"
    job["keys"] = [*job["keys"], ELIGIBILITY_KEY]
    job["prompt"] += "\n" + STRICT_PROMPT
    return job


def require_settings():
    settings = yaml.safe_load(inside(ROOT / "ai_settings.yaml").read_text(encoding="utf-8"))["prep"]
    expected = {"reader_a": {"model": "opus", "fast_mode": False},
                "reader_b": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh", "service_tier": "fast"}}
    if any(settings.get(reader, {}).get(key) != value for reader, fields in expected.items() for key, value in fields.items()):
        raise RuntimeError("Expansion requires Opus regular and gpt-6.1-sol xhigh priority/Fast; no substitutions")


@contextmanager
def sequential_readers():
    """Gate every provider spawn, including a bounded repair, using existing limits."""
    original = runner.run_reader
    def gated(*args, **kwargs):
        wait_for_headroom()
        return original(*args, **kwargs)
    runner.set_concurrency(1)
    runner.run_reader = gated
    try:
        yield
    finally:
        runner.run_reader = original


def assess(result, drawings):
    assembled = pipeline.assemble([result], drawings, {})
    did = result["job"]["drawing"]
    template = assembled["templates"][did]
    reasons = []
    try:
        for variant, _ in _options(template):
            _validate_essential(variant)
    except Unknown as exc:
        reasons.append(str(exc))
        template["cad_ready"] = False
        if not template.get("blocking_fields"):
            template["blocking_fields"] = [str(exc)]
    eligibility = template.get(ELIGIBILITY_KEY) or {}
    value = eligibility.get("value") or {}
    if value.get("reason"):
        reasons.append(value["reason"])
    if not template["cad_ready"]:
        for key in template.get("blocking_fields", []):
            verdict = result.get("answers", {}).get("claude", {}).get(key) or {}
            reasons.append(key + ": " + (verdict.get("reason") or "No verified source-grounded value"))
    if not reasons:
        reasons.append("Supported constant-thickness outline and essential dimensions verified from the raw drawing")
    template["expansion_protocol"] = EXPANSION_PROTOCOL
    assessment = {"drawing": did, "status": "ready_for_cad" if template["cad_ready"] else "blocked",
                  "reason": " ".join(dict.fromkeys(reasons)), "blocking_fields": template.get("blocking_fields", []),
                  "omitted_minor_features": value.get("omitted_minor_features", []),
                  "features_state": template.get("features_review", {}).get("state"),
                  "source_sha256": drawings[did].get("sha256"), "protocol": result.get("protocol"),
                  "states": result["states"], "feedback_rounds": result.get("feedback_rounds", [])}
    return template, assessment, assembled["metrics"]


def expand(force=False):
    require_settings()
    drawings = raw_drawings()
    raw_hash = digest(GENERATED / "drawings.json")
    original = read_json(GENERATED / "ai_results.json")
    existing = original.get("templates", {})
    pending = sorted(set(drawings) - set(existing))
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    journal = inside(runner.CACHE / "model_expansion" / f"{stamp}.json")
    report = {"run": stamp, "protocol": EXPANSION_PROTOCOL, "raw_drawings_sha256": raw_hash,
              "max_concurrent_readers": 1, "cad_generated_locally": False, "assessments": {}, "usage": []}
    for did in sorted(set(drawings) & set(existing)):
        report["assessments"][did] = {"drawing": did, "status": "preserved", "reason": "Existing template preserved unchanged"}
    additions = {}
    runner.bootstrap_auth()
    with sequential_readers():
        for index, did in enumerate(pending, 1):
            print(f"[{index}/{len(pending)}] {did}: Sol proposal -> Opus verification", flush=True)
            result = pipeline.run_retry(pipeline.execute(expansion_job(drawings[did]), force=force), force=force)
            template, assessment, metrics = assess(result, drawings)
            additions[did] = template
            report["assessments"][did] = assessment
            usage = [{"reader": reader, "role": response.get("role"), "cache_key": response.get("cache_key"),
                      "cache_hit": response.get("cache_hit", False), "settings": response.get("settings"),
                      "metadata": response.get("metadata"), "latency_ms": response.get("latency_ms")}
                     for round_ in result["rounds"] for reader, response in round_.items()]
            report["usage"].append({"drawing": did, "metrics": metrics, "calls": usage})
            runner.write_json(journal, {**report, "complete": False})
            print(f"{did}: {assessment['status']}: {assessment['reason']}", flush=True)
    if digest(GENERATED / "drawings.json") != raw_hash:
        raise RuntimeError("Raw evidence changed during expansion; saved receipts were not integrated")
    # Re-read immediately before append; preserve any coordinator changes and never replace templates.
    output = read_json(GENERATED / "ai_results.json")
    for did, template in additions.items():
        if did in output.setdefault("templates", {}):
            raise RuntimeError("Template added concurrently; expansion will not overwrite it: " + did)
        output["templates"][did] = template
    for did, template in existing.items():
        if output["templates"].get(did) != template:
            raise RuntimeError("Existing template changed during expansion; integration requires a fresh run")
    report["complete"] = True
    report["wall_time_ms"] = round((time.monotonic() - started) * 1000)
    report["ready_for_cad"] = [did for did, value in report["assessments"].items() if value["status"] == "ready_for_cad"]
    report["blocked"] = [did for did, value in report["assessments"].items() if value["status"] == "blocked"]
    summary = {"run": stamp, "protocol": EXPANSION_PROTOCOL, "assessed": len(pending),
               "ready_for_cad": report["ready_for_cad"], "blocked": report["blocked"],
               "wall_time_ms": report["wall_time_ms"], "usage": report["usage"]}
    if pending:
        output.setdefault("metrics", {}).setdefault("model_expansions", []).append(summary)
        runner.write_json(GENERATED / "ai_results.json", output)
        runner.write_json(runner.CACHE / "artifacts/ai_results.json", output)
    runner.write_json(journal, report)
    runner.write_json(GENERATED / "model_assessments.json", report)
    runner.write_json(runner.CACHE / "artifacts/model_assessments.json", report)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Execute paid sequential CLI proposal/verification calls and append templates")
    parser.add_argument("--force", action="store_true", help="Bypass existing provider caches (only with --execute)")
    args = parser.parse_args()
    configure_environment()
    require_settings()
    if not args.execute:
        if args.force:
            parser.error("--force requires --execute")
        drawings = raw_drawings()
        existing = read_json(GENERATED / "ai_results.json").get("templates", {})
        print(json.dumps({"execute": False, "assess": sorted(set(drawings) - set(existing)),
                          "preserve_templates": sorted(existing), "protocol": pipeline.PROTOCOL,
                          "provider_order": [runner.reader_settings("codex"), runner.reader_settings("claude")],
                          "max_concurrent_readers": 1, "maximum_feedback_rounds": 1,
                          "next": "python -m scripts.expand_models --execute"}, indent=2))
        return
    print(json.dumps(expand(args.force), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
