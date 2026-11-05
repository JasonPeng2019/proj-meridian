"""Rebuild the three real MVP reconstructions from saved, source-bound preparation.

Run in the serial GitHub CAD slot. This never runs a reader or changes decisions.
An unavailable model is reported as unavailable and makes this command fail.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

DEVELOPMENT = Path(__file__).resolve().parents[1]
PRODUCT = DEVELOPMENT.parent
sys.path.insert(0, str(DEVELOPMENT))


def owned(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(PRODUCT.resolve()):
        raise ValueError("Source model paths must remain inside this product workspace.")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=DEVELOPMENT / "generated/inputs/inputs.json")
    parser.add_argument("--prepared", type=Path, default=DEVELOPMENT / "generated/prepared.json")
    parser.add_argument("--manifest", type=Path, default=DEVELOPMENT / "inputs/project-meridian/dataset/manifest.json")
    parser.add_argument("--records", type=Path, default=DEVELOPMENT / "generated/records.json")
    parser.add_argument("--models", type=Path, default=DEVELOPMENT / "generated/models")
    parser.add_argument("--decisions", type=Path, default=DEVELOPMENT / "decisions")
    parser.add_argument("--report", type=Path, default=PRODUCT / "testing/reports/source-models/build.json")
    args = parser.parse_args()
    paths = {key: owned(value) for key, value in vars(args).items()}
    if not paths["report"].is_relative_to((PRODUCT / "testing").resolve()):
        raise ValueError("Build reports belong under testing/.")
    protected = {paths[key] for key in ("inputs", "prepared", "manifest")}
    source_root = paths["manifest"].parent.parent
    for key in ("records", "report", "models"):
        target = paths[key]
        if (target in protected or target == paths["decisions"]
                or target.is_relative_to(paths["decisions"]) or target.is_relative_to(source_root)
                or any(path.is_relative_to(target) for path in protected)):
            raise ValueError("Model outputs must not overwrite original inputs, preparation or decision history.")
    if paths["records"] == paths["report"]:
        raise ValueError("Records and build report need distinct output files.")
    for key in ("inputs", "prepared", "manifest"):
        if not paths[key].is_file():
            raise SystemExit(f"Required saved {key} is missing; no substitute geometry was generated.")

    # Imports are intentionally inside main; importing this CLI cannot build CAD.
    from backend import contracts as c
    from backend.ai.vision_jobs import SUPPORTED_TEMPLATES
    from backend.cad.build import create_model_rebuilder
    from backend.loader.decisions import DecisionStore
    from backend.loader.records import RecordRegistry

    registry = RecordRegistry.from_paths(prepared_path=paths["prepared"], inputs_path=paths["inputs"],
        records_path=paths["records"], decisions=DecisionStore(paths["decisions"]),
        manifest_path=paths["manifest"])
    if registry.document.prepared.batch.synthetic or registry.document.prepared.batch.fixture:
        raise ValueError("Real-source model generation refuses synthetic or fixture preparation.")
    rebuild = create_model_rebuilder(paths["models"])
    results = []
    candidates = []
    for drawing_id in sorted(SUPPORTED_TEMPLATES):
        part_id = c.drawing_part_name(drawing_id)
        part = registry.part_for(part_id)
        template = registry.load_template(part_id)
        if part is None or template is None:
            results.append({"drawing_id": drawing_id, "state": "blocked",
                "message": "A current source-bound effective template is unavailable; no dimensions were guessed."})
            continue
        if part.synthetic or template.synthetic or part.fixture or template.fixture:
            raise ValueError("Real-source model generation refuses synthetic or fixture inputs.")
        candidates.append((drawing_id, part_id, part, template))
    # Preflight every source boundary before writing any of the three models.
    # Missing templates remain honest failures; no guessed replacement is built.
    for drawing_id, part_id, part, template in candidates:
        status = rebuild(part, template)
        registry.set_model_status(part_id, status)
        results.append({"drawing_id": drawing_id, "part_id": part_id,
            "source_sha256": part.drawing.source_sha256, "template_sha256": c.contract_digest(template),
            "state": status.state, "model": status.model_dump(mode="json")})
    registry.save()
    available = sum(result["state"] == "available" for result in results)
    report = {"schema": "meridian-source-model-build/v1", "at": datetime.now(timezone.utc).isoformat(),
        "commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "outcome": "PASS" if available == len(SUPPORTED_TEMPLATES) else "FAIL",
        "synthetic": False, "expected_parts": sorted(SUPPORTED_TEMPLATES), "available_parts": available,
        "fidelity_review": "Requires the planned V3 source/assignment inspection; generation alone is not semantic approval.",
        "parts": results}
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    temporary = paths["report"].with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(paths["report"])
    print(json.dumps({"outcome": report["outcome"], "available_parts": available,
                      "report": str(paths["report"].relative_to(PRODUCT))}))
    return 0 if report["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
