"""Compile inspected-source recommendations against the finished live dataset.

This does not judge model outputs or save reviews. It rejects stale audit bindings
and requires completed geometry prep before preparing a concrete decision plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from backend.app.review_sources import source_record
from backend.app.store import Store, prediction_fingerprint
from backend.paths import ROOT, configure_environment, inside


def load(path):
    return json.loads(inside(path).read_text(encoding="utf-8-sig"))


def prepare(batch, output):
    checkpoint = load(batch / "checkpoint.json")
    if not checkpoint.get("complete"):
        raise ValueError("Finish and publish geometry prep before preparing reviews")
    followup_path = ROOT / "docs/verification/detail-followup-audit.json"
    followup = load(followup_path)
    audited = {item["drawing"] for item in followup.get("staged_templates", [])}
    reused = {item['drawing'] for item in followup.get('source_checked_reuse_dispositions', [])}
    candidates = {did for did, decision in checkpoint.get('routing', {}).items() if decision['action'] == 'detailed_candidate'}
    if audited | reused != {f"D-{i:03d}" for i in range(1, 31)} or not candidates.issubset(audited):
        raise ValueError("Source audits do not cover every fresh candidate and reused unsupported assessment")
    store = Store()
    receipt = (batch / "checkpoint.json").relative_to(ROOT / "generated").as_posix()
    if not any(run.get("receipt", '').replace('\\', '/') == receipt for run in store.ai.get("prep_runs", [])):
        raise ValueError("The finished geometry batch has not been published to the live dataset")
    baseline = load(ROOT / ".verification/oversight-review/original-prediction-bindings.json")["fields"]
    pending = {item["target"] for item in store.review_items()
               if item["review_queue"] != "resolved" and not item["id"].startswith(("design:", "weight:"))}
    operations, skipped = {}, []

    def sources(names):
        found = []
        def add(name):
            if re.fullmatch(r"D-\d{3}", name):
                name += "/drawing/source"
            if name in found:
                return
            if source_record(store, name):
                found.append(name)
                return
            dependencies = store.fields.get(name, {}).get("fact_ids", [])
            if not dependencies:
                raise ValueError("An audit source is not indexed: " + name)
            for dependency in dependencies:
                add(dependency)
        for name in names:
            add(name)
        return found

    def add(item, path, *, old=False):
        target = item["target"]
        action = item.get("action", item.get("decision", item.get("recommendation")))
        if action not in {"confirm", "reject", "approve_mapping", "defer_unsupported", "accept_link"}:
            skipped.append({"target": target, "reason": "No supported confirm/reject recommendation"})
            return
        if old and "/template/" in target and target.split('/')[0] in audited:
            return  # Fresh prep requires its own source inspection.
        if target not in pending:
            skipped.append({"target": target, "reason": "Already resolved or absent from current review queue"})
            return
        field = store.raw_fields.get(target, {})
        expected_source = item.get("based_on", item.get("source_sha256"))
        if expected_source != store.fingerprint(target):
            skipped.append({"target": target, "reason": "Source/proposal changed since audit"})
            return
        expected_prediction = item.get("prediction_sha256")
        if old:
            expected_prediction = baseline.get(target, {}).get("prediction_sha256")
        if action != "approve_mapping":
            if not expected_prediction or expected_prediction != prediction_fingerprint(field):
                skipped.append({"target": target, "reason": "AI prediction changed since audit"})
                return
            if store.fields[target].get("method") == "human_decision":
                skipped.append({"target": target, "reason": "Preserve existing human replacement"})
                return
        refs = item.get("source_fact_ids") or [item["source"]]
        refs = sources(refs)
        note = item.get("note", item.get("basis", ""))
        if not refs or not note:
            raise ValueError("An inspected recommendation lacks evidence or rationale: " + target)
        operation = {"target": target, "action": action, "based_on": expected_source,
                     "note": note, "source_fact_ids": refs,
                     "source_locations": item.get("source_locations") or [
                         {"drawing": target.split("/")[0], "image": item.get("image"),
                          "page": item.get("page"), "box": item.get("box")}],
                     "audit_receipt": {"path": str(path.relative_to(ROOT)),
                                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
        if action in {"approve_mapping", "accept_link"}:
            operation["value"] = item["value"]
        if action != 'approve_mapping':
            operation["prediction_sha256"] = expected_prediction
        if action == 'defer_unsupported':
            operation['template_capability_sha256'] = store.template_capability_fingerprint(target)
        operations[target] = operation

    for name in ("audit-01-10.json", "audit-11-20.json", "audit-21-30.json"):
        path = ROOT / ".verification/oversight-review" / name
        for item in load(path)["items"]:
            add(item, path, old=True)
    path = ROOT / "docs/verification/detail-literal-audit.json"
    for item in load(path)["items"]:
        add(item, path)
    for item in followup.get("recommendations", []) + followup.get("template_recommendations", []):
        add(item, followup_path)
    path = ROOT / "docs/verification/detail-mapping-audit.json"
    for item in load(path)["operations"]:
        add(item, path)
    path = ROOT / 'docs/verification/link-followup-audit.json'
    if path.is_file():
        for item in load(path)['operations']:
            add(item, path)
    plan = {"status": "prepared_not_applied", "revision": store.revision,
            "batch": str(batch.relative_to(ROOT)), "operations": list(operations.values()),
            "skipped": skipped, "counts": dict(Counter(op["action"] for op in operations.values()))}
    output = inside(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"plan": str(output.relative_to(ROOT)), "operations": len(operations),
                      "counts": plan["counts"], "skipped": len(skipped)}))


if __name__ == "__main__":
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(inside(args.batch), inside(args.output))
