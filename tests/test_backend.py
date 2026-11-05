"""Trust and governance checks use isolated evidence, never production decisions."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.chat import collect_evidence, resolve_answer_evidence
from backend.app.store import Store
from backend.app.tools import KnowledgeTools


def test_review_queues_separate_verified_mapping_from_ambiguous_geometry(evidence):
    items = evidence.review_items()
    mapping = next(i for i in items if i["type"] == "name_mapping")
    possible = [i for i in items if i.get("state") == "options" or i["type"] == "possible_reading"]
    assert mapping["review_queue"] == "human_review"
    assert possible and all(i["review_queue"] == "human_input" for i in possible)
    assert all(i["queue_reason"] for i in items)
    # In-memory replay only; no production decisions or manufactured approvals.
    evidence._apply({"applies_to": mapping["target"], "type": "name_mapping", "value": "same",
                     "status": "accepted", "by": "Automated in-memory fixture", "at": "2000-01-01T00:00:00Z"})
    assert next(i for i in evidence.review_items() if i["id"] == mapping["id"])["review_queue"] == "resolved"


def test_unsupported_disposition_preserves_unknown_geometry_and_delegated_accuracy(evidence):
    target = "D-019/template/thickness"
    evidence.fields[target].update(state="unknown", value=None)
    evidence.fields[target].pop("options", None)
    before = copy.deepcopy(evidence.fields[target])
    event = {"applies_to": target, "type": "defer_unsupported", "status": "accepted",
             "by": "Meridian delegated reviewer", "review_kind": "delegated",
             "at": "2000-01-01T00:00:00Z", "note": "Outside current template capability"}
    evidence._apply(event)
    assert evidence.fields[target]["state"] == before["state"]
    assert evidence.fields[target].get("value") == before.get("value")
    assert evidence.fields[target]["review"]["status"] == "deferred"
    assert next(i for i in evidence.review_items() if i["target"] == target)["review_queue"] == "resolved"
    evidence.events.append({**event, "type": "confirm"})
    assert evidence.accuracy()["reviewed"] == 0


def test_possible_reading_is_one_review_question_without_duplicate_ai_item(evidence):
    target = "D-019/template/thickness"
    items = [i for i in evidence.review_items() if i["target"] == target]
    assert len(items) == 1 and items[0]["type"] == "possible_reading"


def test_image_read_numbers_remain_citable_without_flooding_part_details(evidence):
    part = evidence.part("D-019")
    name = "D-019/drawing/visual-n/p1-test"
    evidence.fields[name] = {"name": name, "value": 42, "original": "42,0", "method": "ai_verified",
                             "confidence": "sure", "page": 1, "box": [10, 20, 30, 10]}
    evidence.owners[name] = part
    tools = KnowledgeTools(evidence)
    assert name not in {fact["fact"] for fact in tools.get_facts("D-019")["facts"]}
    cited = tools.display(name)
    assert cited["display"]["value"] == 42 and cited["sources"][0]["box"] == [10, 20, 30, 10]
    assert cited["badge"].startswith("AI proposal verified")


def test_live_store_reloads_the_same_append_only_decision_files(evidence, monkeypatch):
    from backend.app import main
    monkeypatch.setattr(main, "_store", evidence)
    monkeypatch.setattr(main, "_snapshot_signature", None)
    monkeypatch.setattr(main, "_snapshot_store", None)
    initial = main.get_store().revision
    # Simulate another authorized process writing to the same repository.
    other = Store(evidence.root)
    other.append("D-019/template/thickness", "confirm", by="Automated delegated fixture",
                 review_kind="delegated", delegated_by="Fixture authorization")
    live = main.get_store()
    assert live.revision != initial
    assert live.fields["D-019/template/thickness"]["review"]["display_by"] == "Fixture authorization - delegated review"
    assert live.accuracy()["reviewed"] == 0

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

def test_known_citations_attach_parts_without_changing_the_answer(evidence):
    tools = KnowledgeTools(evidence)
    ledger = {}
    collect_evidence(tools.get_facts("D-019"), ledger, tools)
    result = resolve_answer_evidence("Unknown title [undetermined: D-019/drawing/title] [cite: D-019/part]", ledger, evidence)
    assert not result["warnings"]
    assert [p["key"] for p in result["parts_to_show"]] == ["D-019"]
    invalid = resolve_answer_evidence("Wrong [cite: D-999/drawing/title]", ledger, evidence)
    assert invalid["text"] == "Wrong [cite: D-999/drawing/title]"
    assert not invalid["warnings"] and not invalid["parts_to_show"]
    unreturned = resolve_answer_evidence("Title [cite: D-019/drawing/title]", {}, evidence)
    assert unreturned["text"] == "Title [cite: D-019/drawing/title]"
    assert not unreturned["parts_to_show"]

def test_source_linking_does_not_grade_marker_kind_and_retains_single_match_backup(evidence):
    tools = KnowledgeTools(evidence)
    ledger = {"D-019/part": tools.display("D-019/part")}
    invalid = resolve_answer_evidence("[undetermined: D-019/part]", ledger, evidence)
    assert invalid["text"] == "[undetermined: D-019/part]"
    assert [p["key"] for p in invalid["parts_to_show"]] == ["D-019"]
    fallback = resolve_answer_evidence("No evidence was recorded for that question.", {}, evidence, ["D-019"])
    assert fallback["parts_to_show"][0]["shown_reason"]
    ambiguous = resolve_answer_evidence("Which part?", {}, evidence, ["D-019", "D-013"])
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


@pytest.mark.parametrize("setting,expected", [(None, False), ("0", False), ("1", True), ("true", True)])
def test_debug_ui_launch_visibility(evidence, monkeypatch, setting, expected):
    import backend.app.main as main
    monkeypatch.setattr(main, "get_store", lambda: evidence)
    monkeypatch.delenv("MERIDIAN_DEBUG_UI", raising=False)
    if setting is not None:
        monkeypatch.setenv("MERIDIAN_DEBUG_UI", setting)
    assert main.status()["debug_ui"] is expected


def test_partial_supported_features_block_whole_design_until_inventory_resolved(evidence):
    template=evidence.templates['D-019']
    template.update(feature_protocol='supported-feature-subset-v1', features_all_determined=False,
                    features_complete={'state':'known','value':False},
                    features_omitted={'state':'known','value':[{'description':'Unplaced holes'}]})
    with pytest.raises(ValueError,match='incomplete hole/slot inventory'):
        evidence.validate_design(evidence.part('D-019'),'Inspected')
    template['features_complete']={'state':'known','value':True,'method':'human_decision'}
    template['features_omitted']={'state':'known','value':[],'method':'human_decision'}
    evidence.validate_design(evidence.part('D-019'),'Inspected')


def test_mapping_receipt_refresh_preserves_real_decision_only_for_unchanged_sources(evidence):
    from backend.app.store import mapping_source_signature
    name=evidence.ai['mappings'][0]['name']
    fingerprint=evidence.fingerprint(name)
    signature=mapping_source_signature(evidence.ai['mappings'][0],{'D-019':'drawing-v1'},
        {key:value['sha256'] for key,value in evidence.rows.items()})
    evidence.act(name,'approve_mapping','kind_of')
    path=evidence.generated/'ai_results.json'
    data=json.loads(path.read_text())
    data['mappings'][0].update(method='ai_verified',readers={'new':'receipt'},
        prior_proposals=[{'sha256':fingerprint,'source_signature':signature}])
    path.write_text(json.dumps(data))
    fresh=Store(evidence.root)
    assert fresh.mappings[0]['review']['status']=='human_confirmed'
    assert fresh.mappings[0]['relationship']=='kind_of'
    records=json.loads((evidence.generated/'records.json').read_text())
    records[0]['drawing']['sha256']='changed-source'
    (evidence.generated/'records.json').write_text(json.dumps(records))
    changed=Store(evidence.root)
    assert changed.mappings[0].get('review',{}).get('status')!='human_confirmed'
    assert changed.pending_changed()


def test_delegated_dispositions_and_confirmations_have_human_review_labels(evidence):
    from backend.app.tools import badge
    target = "D-019/template/thickness"
    for kind in ("confirm", "defer_unsupported"):
        evidence._apply({"applies_to": target, "type": kind, "status": "accepted",
                         "by": "Automated delegated label fixture", "review_kind": "delegated",
                         "delegated_by": "Jason Peng", "at": "2000-01-02T00:00:00Z"})
        field = evidence.fields[target]
        assert badge(field).startswith("Human reviewed by Jason Peng on ")
        entry = next(i for i in evidence.review_items() if i["target"] == target)
        assert entry["review_label"] == "Human reviewed"
        assert entry["review_queue"] == "resolved"
    assert not evidence.part("D-019").get("design_review")


def test_authorized_review_uses_jason_identity_without_rewriting_event(evidence, monkeypatch):
    monkeypatch.setattr("backend.app.store.settings", lambda: {"reviewer_name": "Jason Peng"})
    from backend.app.review_identity import presented_review
    target = "D-019/template/thickness"
    event = {"applies_to": target, "type": "confirm", "status": "accepted",
             "by": "Meridian delegated reviewer", "review_kind": "delegated",
             "delegated_by": "Jason Peng", "at": "2000-01-02T00:00:00Z"}
    original = copy.deepcopy(event)
    evidence._apply(event)
    evidence.events.append(event)
    displayed = presented_review(event)
    assert displayed["by"] == "Jason Peng" and event == original
    fact = KnowledgeTools(evidence).display(target)
    assert fact["review"]["by"] == "Jason Peng"
    assert " - delegated review" not in fact["badge"]
    assert evidence.history("D-019", target)[-1]["by"] == "Jason Peng"
    assert evidence.accuracy()["reviewed"] == 1
    assert not evidence.part("D-019").get("design_review")
