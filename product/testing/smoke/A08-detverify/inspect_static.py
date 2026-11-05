"""Syntax/file inventory only. Does not import or execute runner/tests/providers."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = ["development/backend/ai/runner.py", "testing/tests/test_runner_m1.py",
         "testing/fixtures/runner/scripted_cli.py", "testing/fixtures/runner/queue_probe.py",
         "testing/smoke/A08-detverify/inspect_static.py"]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--report", required=True)
args = parser.parse_args()
destination = (ROOT / args.report).resolve()
if not destination.is_relative_to(ROOT / "testing"):
    raise SystemExit("Static reports must stay under testing/.")
inventory = []
for relative in FILES:
    path = ROOT / relative
    data = path.read_bytes()
    source = data.decode("utf-8")
    tree = ast.parse(source, filename=relative)
    inventory.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
        "syntax": "PASS", "line_count": len(source.splitlines()),
        "test_functions": [node.name for node in ast.walk(tree)
                           if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]})
report = {"schema": "meridian-runner-static-inspection/v1", "outcome": "PASS",
    "inspected_at": datetime.now(timezone.utc).isoformat(),
    "scope": "AST parsing and file inventory only; no behavioral/source/provider verification",
    "runtime_tests_executed": False, "live_readers_launched": False,
    "actual_source_validation_performed": False, "files": inventory}
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"outcome": "PASS", "scope": report["scope"], "files": len(inventory),
                  "test_functions": sum(len(item["test_functions"]) for item in inventory)}))
