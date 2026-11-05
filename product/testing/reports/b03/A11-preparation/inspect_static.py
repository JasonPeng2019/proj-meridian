"""AST/Git inspection only. Never import product code or execute fixtures."""

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[4]
REPORT = Path(__file__).with_name("static.json")
SOURCES = ["development/backend/ai/prepare.py", "testing/tests/test_prepare_m1.py"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    files = []
    for relative in SOURCES:
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        tests = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name.startswith("test_")]
        files.append({"path": relative, "sha256": digest(path), "ast": "PASS",
                      "test_functions": tests})
    contracts = ROOT / "development/backend/contracts.py"
    vision = ROOT / "development/backend/ai/vision_jobs.py"
    native = ast.parse(contracts.read_text(encoding="utf-8"))
    image = ast.parse(vision.read_text(encoding="utf-8"))
    schema = next(n for n in image.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_FEATURE" for t in n.targets))
    schema_strings = {n.value for n in ast.walk(schema) if isinstance(n, ast.Constant)
                      and isinstance(n.value, str)}
    defaults = []
    for node in native.body:
        if isinstance(node, ast.ClassDef) and node.name in {"HoleFeature", "SlotFeature"}:
            note = next(n for n in node.body if isinstance(n, ast.AnnAssign)
                        and isinstance(n.target, ast.Name) and n.target.id == "note")
            defaults.append({"model": node.name, "line": note.lineno,
                             "note_default_is_null": isinstance(note.value, ast.Constant) and note.value.value is None})
    blocker = "note" not in schema_strings and all(item["note_default_is_null"] for item in defaults)
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, check=True,
                            text=True, capture_output=True).stdout.strip()
    tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                         text=True, capture_output=True).stdout.strip()
    whitespace = subprocess.run(["git", "diff", "--cached", "--check"], cwd=ROOT,
                                text=True, capture_output=True)
    report = {
        "schema": "meridian-preparation-static/v1", "at": datetime.now(timezone.utc).isoformat(),
        "branch": branch, "inspected_base_commit": tip, "files": files,
        "ast_outcome": "PASS", "git_staged_whitespace": {
            "command": "git diff --cached --check", "outcome": "PASS" if whitespace.returncode == 0 else "FAIL",
            "exit_code": whitespace.returncode, "output": whitespace.stdout + whitespace.stderr},
        "frozen_feature_handoff": {
            "outcome": "BLOCKED" if blocker else "SKIPPED",
            "reason": "M09 semantic feature schemas omit note; native HoleFeature/SlotFeature serialize note:null; exact candidate equality includes that default.",
            "vision_schema_line": schema.lineno, "vision_schema_has_note": "note" in schema_strings,
            "native_defaults": defaults, "contracts_sha256": digest(contracts), "vision_sha256": digest(vision),
            "required_regression": "test_known_feature_must_survive_frozen_contract_handoff",
            "runtime_reproduction": "SKIPPED; static finding only, no product imports or tests executed locally."},
        "local_tests_builds_pdf_cad_browser_live_readers": "SKIPPED",
        "product_imports": False, "generated_prep_publications": 0,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ast": report["ast_outcome"], "files": len(files),
                      "whitespace": report["git_staged_whitespace"]["outcome"],
                      "frozen_feature_handoff": report["frozen_feature_handoff"]["outcome"]}))
    return whitespace.returncode


if __name__ == "__main__":
    raise SystemExit(main())
