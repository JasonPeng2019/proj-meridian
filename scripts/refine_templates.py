"""Refresh the three original templates without replacing other prep results.

Each proposal and verification runs sequentially with the local resource gate.
This writes template evidence only; production CAD regeneration runs on Actions.
"""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone

from backend.ai import pipeline, runner
from backend.paths import GENERATED, ROOT, configure_environment, inside
from scripts.expand_models import digest, raw_drawings, require_settings, sequential_readers


def main():
    configure_environment()
    require_settings()
    drawings = raw_drawings()
    source = inside(GENERATED / "ai_results.json")
    original = json.loads(source.read_text(encoding="utf-8"))
    original_digest = digest(source)
    decisions = {str(path.relative_to(ROOT)): digest(path)
                 for path in (ROOT / "decisions").glob("*.json")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = inside(runner.CACHE / "template_refinement" / stamp)
    runner.write_json(folder / "previous-output.json", original)
    results = []
    started = time.monotonic()
    with sequential_readers():
        for did in pipeline.PRIMARY_TEMPLATES:
            print("Refining " + did, flush=True)
            result = pipeline.run_retry(pipeline.execute(pipeline.template_job(drawings[did])))
            results.append(result)
            template = pipeline.assemble([result], drawings, {})["templates"][did]
            runner.write_json(folder / (did + "-template.json"), template)
            runner.write_json(folder / "checkpoint.json", {"complete": False, "results": results})
            print(json.dumps({"drawing": did, "cad_ready": template.get("cad_ready"),
                              "features": len(template.get("features", [])),
                              "features_status": template.get("features_status"),
                              "omissions": template.get("omitted_feature_notes"),
                              "states": result["states"]}), flush=True)
    assembled = pipeline.assemble(results, drawings, {})
    metrics = assembled["metrics"]
    metrics["wall_time_ms"] = round((time.monotonic() - started) * 1000)
    # Refuse to overwrite another prep process. Real user decisions may append.
    assert digest(source) == original_digest, "Prep results changed during refinement; merge checkpoint explicitly"
    assert all(inside(ROOT / name).is_file() and digest(ROOT / name) == sha
               for name, sha in decisions.items()), "Existing human decisions changed"
    output = copy.deepcopy(original)
    output.setdefault("templates", {}).update(assembled["templates"])
    output.pop("effective_metrics", None)
    full_runs = [item for item in original.get("prep_runs", []) if item.get("kind") == "full_reprepare"]
    if full_runs:
        previous = json.loads(inside(GENERATED / full_runs[-1]["receipt"].replace("\\", "/")).read_text(encoding="utf-8"))
        latest = {result["job"]["id"]: result for result in results}
        active = [latest.get(result["job"]["id"], result) for result in previous["results"]]
        output["effective_metrics"] = pipeline.assemble(active, drawings, previous["exact"])["metrics"]
        output["effective_metrics"]["scope"] = "Current original-template, scan, link and mapping fields; execution receipts remain separate in prep_runs"
    receipt = str((folder / "checkpoint.json").relative_to(GENERATED))
    output.setdefault("prep_runs", []).append({"kind": "primary_template_refinement",
        "protocol": pipeline.PROTOCOL, "receipt": receipt, "metrics": metrics})
    runner.write_json(folder / "checkpoint.json", {"complete": True, "results": results,
        "metrics": metrics, "decisions_unchanged": True})
    runner.write_json(source, output)
    runner.write_json(runner.CACHE / "artifacts/ai_results.json", output)
    print(json.dumps({"complete": True, "receipt": receipt, "metrics": metrics}), flush=True)


if __name__ == "__main__":
    main()
