"""Static source/JSON inspection only: no product imports or runtime tests."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "testing/reports/b01/A02-contracts/2026-11-05-static.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-revision")
    parser.add_argument("--report", default=REPORT.relative_to(ROOT).as_posix())
    parser.add_argument("--history", action="store_true", help="Preserve every existing non-chat class/function")
    parser.add_argument("--observability", action="store_true", help="Preserve every existing class/helper except PrepAttempt/PrepCacheIdentity")
    args = parser.parse_args()
    report_path = (ROOT / args.report).resolve()
    if not report_path.is_relative_to(ROOT / "testing/reports"):
        raise ValueError("Static evidence belongs under testing/reports")
    paths = [ROOT / "development/backend/contracts.py", *sorted(Path(__file__).parent.glob("*.py"))]
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    fixture_root = ROOT / "testing/fixtures/contracts"
    fixtures = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(fixture_root.glob("*.json"))}
    manifest = fixtures["manifest.json"]
    declared = {"manifest.json", *(entry["file"] for entry in manifest["entries"])}
    if fixtures.keys() != declared:
        raise ValueError("Fixture JSON inventory differs from declared manifest")
    for name, value in fixtures.items():
        if not (value.get("fixture") is True and value.get("synthetic") is True and value.get("fixture_note")):
            raise ValueError("Undeclared fixture metadata: " + name)
    types = (ROOT / "development/frontend/src/contracts.ts").read_text(encoding="utf-8")
    generated, handwritten = types.split("// END GENERATED PAYLOAD TYPES\n")
    unchanged = []
    if args.base_revision:
        baseline = subprocess.run(["git", "show", args.base_revision + ":development/backend/contracts.py"],
                                  cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
        before = {item.name: ast.dump(item) for item in ast.parse(baseline).body if isinstance(item, ast.ClassDef)}
        after = {item.name: ast.dump(item) for item in ast.parse(paths[0].read_text(encoding="utf-8")).body if isinstance(item, ast.ClassDef)}
        unchanged = ["DrawingField", "DrawingNumber", "DrawingWord", "DrawingEvidence", "BOMField", "ConnectionEvidence", "BOMRow",
                     "Decision", "DecisionJournal", "ReviewActionRequest", "ReviewActionResponse", "RefreshRequest", "RefreshResult",
                     "PartRecord", "PartSummary", "FactResult", "SourceTarget", "FactSource"]
        if args.history or args.observability:
            allowed = {"PrepAttempt", "PrepCacheIdentity"} if args.observability else {"ChatRequest", "ChatResponse"}
            unchanged = sorted(set(before) - allowed)
        for name in unchanged:
            if before[name] != after[name]:
                raise ValueError("Unexpected ordinary contract declaration change: " + name)
        if args.history or args.observability:
            functions_before = {item.name: ast.dump(item) for item in ast.parse(baseline).body if isinstance(item, ast.FunctionDef)}
            functions_after = {item.name: ast.dump(item) for item in ast.parse(paths[0].read_text(encoding="utf-8")).body if isinstance(item, ast.FunctionDef)}
            if any(functions_after.get(name) != value for name, value in functions_before.items()):
                raise ValueError("Unexpected existing contract helper change")
        if args.observability:
            baseline_ts = subprocess.run(["git", "show", args.base_revision + ":development/frontend/src/contracts.ts"],
                                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
            if baseline_ts.split("// END GENERATED PAYLOAD TYPES\n")[1] != handwritten:
                raise ValueError("History/UI/Debug/service handwritten TypeScript changed")
    record = {
        "schema": "A02-static-inspection/v1",
        "command": "python -B testing/smoke/A02-contracts/inspect_static.py" + (
            " --base-revision " + args.base_revision if args.base_revision else "") + (
            " --history" if args.history else "") + (" --observability" if args.observability else "") + " --report " + args.report,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outcome": "PASS",
        "scope": "Python AST and JSON parsing/inventory/fixture declarations only; no runtime policy/schema/TS checks",
        "python_files": [path.relative_to(ROOT).as_posix() for path in paths],
        "base_revision": args.base_revision,
        "unchanged_nonprep_declarations": unchanged,
        "declared_json_examples": len(manifest["entries"]),
        "json_files_including_manifest": len(fixtures),
        "binary_assets_declared": manifest["binary_assets"],
        "typescript_generated_sha256": hashlib.sha256(generated.encode("utf-8")).hexdigest(),
        "typescript_handwritten_sha256": hashlib.sha256(handwritten.encode("utf-8")).hexdigest(),
        "contracts_python_sha256": hashlib.sha256(paths[0].read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "runtime_contract_checker": "PENDING_ROOT_ACTIONS",
        "typescript_compile_and_helpers": "PENDING_ROOT_ACTIONS",
        "real_source_validation": "NOT_PERFORMED_SYNTHETIC_ONLY",
        "live_cli_execution": "NOT_PERFORMED",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PASS static AST/JSON inspection only; {len(unchanged)} preserved declarations; {len(manifest['entries'])} synthetic examples; {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
