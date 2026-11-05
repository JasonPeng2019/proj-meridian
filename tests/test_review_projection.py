"""Review lists carry source locators rather than repeated full drawing receipts."""
import copy
import json

from backend.app.store import Store
from backend.app.review_sources import review_sources, source_record


def projection_store():
    store = Store.__new__(Store)
    raw_receipt = "retained original verifier transcript " * 4000
    reader = {"codex": {"role": "proposer", "protocol": "proposal-verification-v1", "rounds": [
        {"valid": True, "validation_passed": True, "requested": True,
         "answer": {"key": "length", "state": "known", "value_json": "42", "reason": "Printed dimension",
                    "fact_ids": ["D-001/drawing/n/42@1"]},
         "feedback": [{"previous_proposal": raw_receipt}], "metadata": {"original": raw_receipt}},
        {"requested": False, "answer": None, "feedback": raw_receipt}]}}
    printed = {"name": "D-001/drawing/n/42@1", "value": 42, "original": "42,0", "page": 1,
               "box": [10, 20, 30, 5], "method": "parsed"}
    row = {"name": "BOM:box/door", "display_id": "BOM-001", "display_name": "Door",
           "fields": {"material": {"name": "BOM:box/door/material", "original": "Alu", "value": "Aluminium", "readers": reader}}}
    part = {"id": "D-001/part", "key": "D-001", "display_name": "Door", "has_3d": False, "bom": [row],
            "drawing": {"id": "D-001", "source_path": "evidence/door.pdf", "source_filename": "door.pdf",
                        "pages": 2, "page_sizes": [[100, 200], [200, 300]], "degraded": True,
                        "numbers": [printed], "dimension_evidence": {"raw_receipts": raw_receipt},
                        "fields": {"notes": {"original": "Original notes", "readers": reader}}}}
    fields = {printed["name"]: printed}
    for index in range(32):
        target = f"D-001/template/length-{index}"
        fields[target] = {"name": target, "value": 42, "method": "ai_verified", "state": "known",
                          "fact_ids": [printed["name"]], "readers": reader}
    store.fields = fields
    store.raw_fields = copy.deepcopy(fields)
    store.owners = {name: part for name in fields}
    store.records, store.parts = [part], {part["key"]: part}
    store.rows = {row["name"]: row}
    store.events, store.changed, store.mappings = [], [], []
    return store, part, reader


def test_review_payload_does_not_repeat_whole_drawing_or_hidden_raw_reader_records():
    store, part, reader = projection_store()
    original = copy.deepcopy((part, store.fields))
    items = store.review_items()
    payload = json.dumps(items)
    assert len(items) == 32
    assert len(json.dumps(part["drawing"])) > 250_000
    assert len(payload) < 100_000
    assert "retained original verifier transcript" not in payload
    first = items[0]
    assert first["evidence"]["drawing"] == {
        "id": "D-001", "pages": 2, "page_sizes": [[100, 200], [200, 300]],
        "source_path": "evidence/door.pdf", "source_filename": "door.pdf", "degraded": True}
    assert first["readers"]["codex"]["rounds"][0]["answer"] == reader["codex"]["rounds"][0]["answer"]
    assert len(first["readers"]["codex"]["rounds"]) == 1
    assert (part, store.fields) == original


def test_projected_review_retains_source_regions_bom_values_and_full_on_demand_receipts():
    store, part, _ = projection_store()
    item = store.review_items()[0]
    assert [ref["name"] for ref in item["source_refs"]] == ["D-001/drawing/n/42@1", "D-001/drawing/source"]
    assert item["source_refs"][0]["box"] == [10, 20, 30, 5]
    assert item["source_refs"][0]["page"] == 1
    material = item["evidence"]["bom"][0]["fields"]["material"]
    assert material["original"] == "Alu" and material["value"] == "Aluminium"
    assert "readers" not in material
    detail = source_record(store, "BOM:box/door/material", detail=True)
    assert detail["row"]["fields"]["material"]["readers"] == part["bom"][0]["fields"]["material"]["readers"]
    assert part["drawing"]["dimension_evidence"]["raw_receipts"]
    assert store.fields[item["target"]]["readers"]["codex"]["rounds"][0]["feedback"]


def test_part_filter_prevents_unrelated_evidence_projection_and_preserves_global_equivalence(monkeypatch):
    store, _, _ = projection_store()
    other = {"key": "D-002", "id": "D-002/part", "has_3d": False, "drawing": {"id": "D-002"}, "bom": []}
    target = "D-002/template/thickness"
    store.fields[target] = {"name": target, "value": 3, "method": "ai_verified", "state": "known"}
    store.raw_fields[target] = copy.deepcopy(store.fields[target])
    store.owners[target] = other
    store.records.append(other)
    store.parts["D-002"] = other
    global_items = store.review_items()
    original = store.evidence_for
    projected = []

    def evidence_for(name):
        assert not name.startswith("D-001/")
        projected.append(name)
        return original(name)

    monkeypatch.setattr(store, "evidence_for", evidence_for)
    selected = store.review_items(part_key="D-002")
    assert selected == [item for item in global_items if item.get("part_key") == "D-002"]
    assert projected == [target]


def test_source_reference_cache_reuses_resolved_locators_without_dropping_recursive_citations(monkeypatch):
    from backend.app import review_sources as module

    store, _, _ = projection_store()
    original = module.source_record
    calls = []

    def record(store, name, **kwargs):
        calls.append(name)
        return original(store, name, **kwargs)

    monkeypatch.setattr(module, "source_record", record)
    cache = {}
    first = review_sources(store, {"id": "one", "target": "D-001/template/length-0"}, cache=cache)
    second = review_sources(store, {"id": "two", "target": "D-001/template/length-1"}, cache=cache)
    assert first == second
    assert calls.count("D-001/drawing/n/42@1") == 1
    assert calls.count("D-001/drawing/source") == 1
