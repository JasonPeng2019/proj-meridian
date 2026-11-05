"""Apply evidence-backed delegated decisions with an explicit actor and audit trail.

This is separate from prep model verification and from Jason's personal reviews.
It never generates CAD locally or edits an existing decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from backend.app.review_sources import source_record
from backend.app.store import Store, prediction_fingerprint
from backend.paths import ROOT, configure_environment, inside

ACTOR = "Meridian delegated reviewer"


def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.json")}


class DelegatedStore(Store):
    context = None

    def append(self, *args, **extra):
        extra.update(by=ACTOR, review_kind="delegated", delegated_by="Jason Peng",
                     authorization="User explicitly delegated obvious source-backed input/review decisions and their accuracy outcomes on 2026-11-05.",
                     source_evidence=self.context.get("source_fact_ids", []),
                     source_locations=self.context.get("source_locations", []))
        return super().append(*args, **extra)

    def rebuild_models(self):
        # All geometry/density regeneration is queued on Actions after the batch.
        self.reload()


def run(plan_path: Path, apply=False):
    plan = json.loads(inside(plan_path).read_text(encoding="utf-8"))
    store = DelegatedStore()
    before = hashes(store.decisions_dir)
    prepared = []
    for operation in plan["operations"]:
        target, action = operation["target"], operation["action"]
        mapping = next((m for m in store.mappings if m["name"] == target), None)
        if (target not in store.fields and mapping is None or
                action not in {"set_value", "accept_link", "confirm", "reject", "approve_mapping", "defer_unsupported"}):
            raise ValueError(f"Invalid delegated operation: {target} / {action}")
        if action == "approve_mapping" and (mapping is None or operation.get("value") not in {"same", "kind_of", "different", "no_equivalent"}):
            raise ValueError("A mapping decision requires a current proposal and valid relationship")
        if mapping is not None and action != "approve_mapping":
            raise ValueError("Use approve_mapping for a name relationship")
        if action in {"confirm", "reject"} and operation.get("prediction_sha256") != prediction_fingerprint(store.raw_fields[target]):
            raise ValueError(f"AI prediction changed since audit: {target}")
        if not operation.get("note") or not operation.get("source_fact_ids"):
            raise ValueError("Every delegated operation requires evidence and a reason")
        if operation.get("based_on") != store.fingerprint(target):
            raise ValueError(f"Evidence changed since audit: {target}")
        if any(source_record(store, name) is None for name in operation["source_fact_ids"]):
            raise ValueError(f"Unindexed source citation: {target}")
        if action == "defer_unsupported" and ("/template/" not in target or store.fields[target].get("state") != "unknown"):
            raise ValueError("Only unknown unavailable template inputs can be deferred")
        if action == "accept_link" and any(name not in store.rows for name in operation["value"]):
            raise ValueError("Unknown BOM row")
        prepared.append(operation)
    saved = []
    if apply:
        for operation in prepared:
            store.context = operation
            target, action = operation["target"], operation["action"]
            note = operation["note"]
            if action == "defer_unsupported":
                event = store.append(target, action, note=note)
            elif action == "accept_link":
                event = store.append(target, "link", operation["value"], note=note)
            elif action == "approve_mapping":
                event = store.append(target, "name_mapping", operation["value"], note=note)
            else:
                event = store.append(target, action, operation.get("value"), note=note)
            saved.append(event["decision_id"])
    after = hashes(store.decisions_dir)
    assert all(after.get(name) == digest for name, digest in before.items()), "An existing decision changed"
    report = {"applied": apply, "actor": ACTOR, "personal_human_approval": False,
              "operation_count": len(prepared), "actions": dict(Counter(o["action"] for o in prepared)),
              "new_decisions": saved, "preexisting_decisions_unchanged": True, "baseline_decisions": before,
              "review_queue_counts": dict(Counter(i["review_queue"] for i in store.review_items())),
              "accuracy": store.accuracy(),
              "cad_regeneration": "queued remotely; no local geometry generation"}
    output = inside(plan_path.parent / ("applied.json" if apply else "dry-run.json"))
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"baseline_decisions", "new_decisions"}}, indent=2))


if __name__ == "__main__":
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(inside(ROOT / args.plan), args.apply)
