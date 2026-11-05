"""Trust and governance checks use isolated evidence, never production decisions."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.chat import collect_evidence, validate_markers
from backend.app.store import Store
from backend.app.tools import KnowledgeTools

@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.store.settings", lambda: {"reviewer_name": "Automated verification"})
    generated = tmp_path / "generated"
    generated.mkdir()
    def field(name, value, **kw):
        return {"name": name, "value": value, "original": value, "method": "parsed", "confidence": "sure", "page": 1, "box": [10, 10, 20, 8], **kw}
    row = {"name": "BOM:optics/gasket", "display_id": "BOM-001", "display_name": "Gasket", "section": "Optics", "sha256": "row-v1", "fields": {
        "material": field("BOM:optics/gasket/material", "Silicone"),
        "cost": field("BOM:optics/gasket/cost", None), "total_cost": field("BOM:optics/gasket/total_cost", None)}}
    part = {"id": "D-019/part", "key": "D-019", "display_name": "Gasket", "section": "Optical", "has_drawing": True, "has_3d": False,
        "drawing": {"id": "D-019", "sha256": "drawing-v1", "pages": 1, "page_sizes": [[100,100]], "fields": {
            "title": field("D-019/drawing/title", "Description", confidence="unsure", note="Placeholder title"),
            "material": field("D-019/drawing/material", "Silicon Rubber")}, "numbers": []}, "bom": [row], "link": {"method": "exact_match"}}
    template = {"part": "D-019", "thickness": {"state": "options", "options": [1.0, 2.0], "method": "ai_agreed", "confidence": "sure", "fact_ids": []}}
    mapping = {"name": "names/material/silicon-rubber -> silicone", "kind": "material", "left": "Silicon Rubber", "right": "Silicone", "relationship": "same", "method": "ai_agreed", "evidence": "general engineering knowledge, not the dataset"}
    for name, data in {"records.json": [part], "bom.json": [row], "ai_results.json": {"templates": {"D-019": template}, "mappings": [mapping]}}.items():
        (generated / name).write_text(json.dumps(data), encoding="utf-8")
    return Store(tmp_path)

def test_correction_requires_review_and_replays_without_erasing_original(evidence):
    target = "D-019/drawing/title"
    tools = KnowledgeTools(evidence)
    proposal = evidence.propose(target, "Silicone gasket", "The printed title is a placeholder")
    assert tools.display(target)["display"]["state"] == "undetermined"
    assert evidence.pending_corrections()
    evidence.act(proposal["decision_id"], "accept")
    assert KnowledgeTools(evidence).display(target)["display"]["value"] == "Silicone gasket"
    assert evidence.fields[target]["original"] == "Description"
    fresh = Store(evidence.root)
    assert fresh.fields[target]["value"] == "Silicone gasket"
    assert fresh.fields[target]["correction"]["by"] == "Automated verification"
    assert "Description" in (fresh.generated / "records.json").read_text()

def test_rejected_proposal_keeps_old_value_and_history(evidence):
    target = "D-019/drawing/material"
    proposal = evidence.propose(target, "Steel", "Deliberately wrong test proposal")
    evidence.act(proposal["decision_id"], "reject")
    assert evidence.fields[target]["value"] == "Silicon Rubber"
    assert not evidence.pending_corrections()
    assert any(e.get("status") == "rejected" for e in evidence.history("D-019", target))

def test_changed_evidence_reopens_only_dependent_decision(evidence):
    target = "D-019/drawing/title"
    evidence.append(target, "set_value", "Gasket")
    records = json.loads((evidence.generated / "records.json").read_text())
    records[0]["drawing"]["sha256"] = "drawing-v2"
    (evidence.generated / "records.json").write_text(json.dumps(records))
    evidence.reload()
    assert evidence.fields[target]["value"] == "Description"
    assert len(evidence.changed) == 1
    assert any(i["type"] == "source_changed" for i in evidence.review_items())
    pending = next(i for i in evidence.review_items() if i["type"] == "source_changed")
    evidence.act(pending["id"], "accept")
    assert evidence.fields[target]["value"] == "Gasket"
    assert not any(i["type"] == "source_changed" for i in evidence.review_items())
    assert evidence.changed  # Historical invalidation is still inspectable.

def test_mapping_pending_then_approved_changes_resolution(evidence):
    tools = KnowledgeTools(evidence)
    assert tools.material(evidence.part("D-019"))["display"]["state"] == "undetermined"
    mapping = evidence.mappings[0]["name"]
    evidence.act(mapping, "approve_mapping", "same")
    result = KnowledgeTools(evidence).material(evidence.part("D-019"))
    assert result["display"]["state"] == "value"
    assert len(result["sources"]) == 2
    evidence.act(mapping, "reject")
    assert KnowledgeTools(evidence).material(evidence.part("D-019"))["display"]["state"] == "undetermined"

def test_options_are_not_unknown_and_selection_is_durable(evidence):
    target = "D-019/template/thickness"
    assert KnowledgeTools(evidence).display(target)["display"] == {"state": "options", "values": [1.0,2.0]}
    # Avoid optional geometry in a trust-rule test; CAD has its own roundtrip tests.
    evidence.rebuild_models = lambda: None
    evidence.act("options:" + target, "choose_option", 2.0)
    assert KnowledgeTools(evidence).display(target)["display"]["value"] == 2.0
    assert evidence.fields[target]["options"] == [1.0,2.0]

def test_citations_need_real_returned_facts_and_attach_correct_part(evidence):
    tools = KnowledgeTools(evidence)
    ledger = {}
    collect_evidence(tools.get_facts("D-019"), ledger, tools)
    result = validate_markers("Unknown title [undetermined: D-019/drawing/title] [cite: D-019/part]", ledger, evidence)
    assert not result["warnings"]
    assert [p["key"] for p in result["parts_to_show"]] == ["D-019"]
    invalid = validate_markers("Wrong [cite: D-999/drawing/title]", ledger, evidence)
    assert invalid["warnings"] and not invalid["parts_to_show"]
    unreturned = validate_markers("Title [cite: D-019/drawing/title]", {}, evidence)
    assert any("not returned" in warning for warning in unreturned["warnings"])

def test_undetermined_consistency_and_single_match_backup(evidence):
    tools = KnowledgeTools(evidence)
    ledger = {"D-019/part": tools.display("D-019/part")}
    invalid = validate_markers("[undetermined: D-019/part]", ledger, evidence)
    assert any("has a value" in warning for warning in invalid["warnings"])
    fallback = validate_markers("No evidence was recorded for that question.", {}, evidence, ["D-019"])
    assert fallback["parts_to_show"][0]["shown_reason"]
    ambiguous = validate_markers("Which part?", {}, evidence, ["D-019", "D-013"])
    assert not ambiguous["parts_to_show"]

def test_source_ledger_keeps_each_sources_own_value(evidence):
    tools = KnowledgeTools(evidence)
    numeric = {"name": "D-019/drawing/n/270@1", "value": 270.0, "original": "270", "method": "parsed", "confidence": "sure"}
    evidence.fields[numeric["name"]] = numeric
    evidence.owners[numeric["name"]] = evidence.part("D-019")
    target = "D-019/template/thickness"
    evidence.fields[target]["fact_ids"] = [numeric["name"]]
    ledger = {}
    collect_evidence(tools.display(target), ledger, tools)
    assert ledger[numeric["name"]]["display"]["value"] == 270.0
    assert ledger[target]["display"]["state"] == "options"

def test_no_key_api_keeps_browsing_and_review_available(evidence, monkeypatch):
    import backend.app.main as main
    monkeypatch.setattr(main, "_store", evidence)
    monkeypatch.setenv("MERIDIAN_NO_KEY", "1")
    client = TestClient(main.app)
    assert client.get("/api/status").json()["chat_available"] is False
    assert client.get("/api/parts/D-019").status_code == 200
    assert client.get("/api/review").status_code == 200
    assert client.get("/api/parts/D-019/history").status_code == 200
    assert client.post("/api/chat", json={"message": "What is this?"}).status_code == 400
    assert client.get("/api/accuracy").json()["accuracy"] is None

def test_whole_design_requires_input_and_failed_weight_note(evidence):
    model_dir = evidence.generated / "models"
    model_dir.mkdir()
    (model_dir / "manifest.json").write_text(json.dumps({"D-019": {"examples": ["A"], "models": {}, "weight_check": {"state": "FAILED"}}}))
    evidence.reload()
    with pytest.raises(ValueError, match="requires a note"):
        evidence.act("design:D-019/part", "approve_design")
    evidence.act("design:D-019/part", "approve_design", note="Automated guard test, not a real design approval")
    assert evidence.part("D-019")["review_status"] == "reviewed"
    evidence.append("D-019/template/thickness", "set_value", {"state": "unknown", "value": None})
    assert evidence.part("D-019").get("design_review") is None
    with pytest.raises(ValueError, match="still need input"):
        evidence.act("design:D-019/part", "approve_design", note="Cannot override missing essential geometry")
