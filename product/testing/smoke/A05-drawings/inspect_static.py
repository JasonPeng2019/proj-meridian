"""Bounded source/AST inspection; never import or execute the PDF extractor."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-artifacts", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    source = root / "development/backend/loader/drawings.py"
    contracts = ast.parse((root / "development/backend/contracts.py").read_text(encoding="utf-8"))
    exports = {node.name for node in contracts.body
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for node in contracts.body:
        if isinstance(node, ast.Assign):
            exports.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            exports.add(node.target.id)
    checks = []
    for path in (source, root / "testing/tests/test_drawings.py", Path(__file__)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                   and node.module == "backend.contracts" for alias in node.names]
        assert set(imports) <= exports, sorted(set(imports) - exports)
        checks.append({"path": path.relative_to(root).as_posix(), "sha256": digest(path),
                       "syntax": "PASS", "frozen_contract_imports": imports})
    corpus = root / "development/inputs/project-meridian"
    manifest = json.loads((corpus / "dataset/manifest.json").read_text(encoding="utf-8"))
    assets = {asset["id"]: asset for asset in manifest["assets"]}
    hashes = {}
    for asset in assets.values():
        actual = digest(corpus / asset["path"])
        assert actual == asset["sha256"], asset["id"]
        hashes[asset["id"]] = actual
    observations = {}
    if args.raw_artifacts:
        records = {}
        for identifier in ("D-001", "D-002", "D-003", "D-013", "D-019", "D-021", "D-026"):
            record = json.loads((args.raw_artifacts / identifier / "positioned-text.json").read_text())
            assert record["source_sha256"] == hashes[identifier]
            assert len(record["pages"]) == assets[identifier]["pages"]
            records[identifier] = record
        raw = records["D-013"]["pages"][0]["words"]
        duplicates = sum(any(w[4] == other[4] and all(abs(a - b) <= .15 for a, b in zip(w[:4], other[:4]))
                             for other in raw[:index]) for index, w in enumerate(raw))
        assert duplicates > 0
        observations["D-013"] = {"raw_words": len(raw), "coincident_duplicates": duplicates}
        placeholder = next(w for w in records["D-019"]["pages"][0]["words"] if w[4] == "Description")
        observations["D-019"] = {"verbatim_placeholder": placeholder[4], "xyxy": placeholder[:4]}
        raw = records["D-026"]["pages"][0]["words"]
        sheet = next(w for w in raw if w[4] == "Sheet")
        weight = next(w for w in raw if w[4] == "WEIGHT")
        assert min(sheet[2], weight[2]) > max(sheet[0], weight[0])
        assert min(sheet[3], weight[3]) > max(sheet[1], weight[1])
        observations["D-026"] = {"overlapping_verbatim_words": [sheet[:5], weight[:5]]}
        for identifier in ("D-001", "D-003", "D-021"):
            observations[identifier] = [{"page": p["page"], "width": p["width"],
                                         "height": p["height"], "raw_words": len(p["words"])}
                                        for p in records[identifier]["pages"]]
        assert len(observations["D-021"]) == 2
        assert len(observations["D-003"]) == 3
        assert not any(p["raw_words"] for p in observations["D-003"])
    report = root / "testing/reports/verification/A05-drawings/static.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "scope": "AST syntax/export names and unchanged source hashes; optional observations of remotely extracted words. No product/runtime validation.",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome": "PASS", "runtime_tests_executed": False,
        "checks": checks, "unchanged_manifest_asset_hashes": hashes,
        "remote_raw_artifacts": str(args.raw_artifacts) if args.raw_artifacts else None,
        "remote_source_observations": observations,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"outcome": "PASS", "static_sources": len(checks),
                      "unchanged_manifest_assets": len(hashes),
                      "runtime_tests_executed": False,
                      "report": report.relative_to(root).as_posix()}))


if __name__ == "__main__":
    main()
