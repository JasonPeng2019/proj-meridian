"""Queue semantics must distinguish an AI answer from an unresolved input."""
import copy

import pytest

from backend.app.review_queue import classify_review


@pytest.mark.parametrize("entry", [
    {"type": "ai_interpretation", "value": 0, "method": "ai_verified", "state": "known"},
    {"type": "ai_interpretation", "value": [], "method": "ai_verified_after_retry", "state": "known"},
    {"type": "name_mapping", "value": "kind_of", "status": "pending_approval"},
    {"type": "ai_interpretation", "id": "design:D-014/part", "value": None},
    {"type": "correction", "value": "Corrected title"},
])
def test_available_ai_answers_need_oversight(entry):
    assert classify_review(entry)[0] == "human_review"


@pytest.mark.parametrize("entry", [
    {"type": "template", "value": None},
    {"type": "link", "value": []},
    {"type": "weight"},
    {"type": "ai_interpretation", "state": "unknown", "value": None},
    {"type": "ai_interpretation", "state": "options", "options": [3, 6], "method": "ai_verified"},
    {"type": "possible_reading", "selected": None},
    {"type": "name_mapping", "value": None},
    {"type": "ai_interpretation", "id": "design:D-015/part", "input_reason": "Geometry is incomplete"},
])
def test_pipeline_gaps_need_intervention(entry):
    queue, reason = classify_review(entry)
    assert queue == "human_input" and reason


@pytest.mark.parametrize("status", ["accepted", "rejected", "human_confirmed", "human_rejected", "approved", "reviewed"])
def test_recorded_human_decisions_leave_both_open_queues(status):
    assert classify_review({"type": "template", "status": status})[0] == "resolved"


@pytest.mark.parametrize("state", ["unknown", "known"])
def test_old_unavailable_disposition_does_not_approve_new_prep_value(state):
    from backend.app.store import Store
    store = Store.__new__(Store)
    target = "D-001/template/thickness"
    field = {"state": state, "value": None if state == "unknown" else 3}
    store.ai = {}
    store.fields = {target: field}
    store.owners = {}
    store._apply({"applies_to": target, "type": "defer_unsupported", "status": "accepted",
                  "by": "Meridian delegated reviewer", "at": "2026-11-05T00:00:00Z",
                  "review_kind": "delegated", "delegated_by": "Jason Peng"})
    assert (field.get("review", {}).get("status") == "deferred") is (state == "unknown")


def bound_disposition_fixture():
    from backend.app.store import Store, prediction_fingerprint

    store = Store.__new__(Store)
    target = "D-001/template/thickness"
    store.fields = {target: {"state": "unknown", "value": None, "method": "ai_unsure"}}
    store.raw_fields = copy.deepcopy(store.fields)
    store.owners = {target: {"drawing": {"id": "D-001", "sha256": "original-source"}}}
    store.ai = {"templates": {"D-001": {"cad_eligibility": {
        "state": "known", "value": {"supported": False, "reason": "Bent structural body"}}}},
        "template_routing": {"D-001": {"capabilities_sha256": "old-capabilities"}}}
    store.templates = copy.deepcopy(store.ai["templates"])
    store.events, store.changed = [], []
    event = {"decision_id": "fixture-disposition", "applies_to": target, "type": "defer_unsupported",
             "status": "accepted", "by": "Automated disposition fixture", "review_kind": "delegated",
             "delegated_by": "Jason Peng", "at": "2026-11-05T00:00:00Z", "note": "Unsupported body",
             "based_on": {"sha256": store.fingerprint(target)},
             "prediction_sha256": prediction_fingerprint(store.raw_fields[target]),
             "template_capability_sha256": store.template_capability_fingerprint(target)}
    store.events = [event]
    return store, target, event


def test_bound_unsupported_disposition_replays_only_on_the_same_raw_prediction_and_capability():
    store, target, event = bound_disposition_fixture()
    original = copy.deepcopy(event)
    store._apply(event)
    assert store.fields[target]["review"]["status"] == "deferred"
    assert store.fields[target]["state"] == "unknown" and store.fields[target]["value"] is None
    assert store.changed == [] and event == original


@pytest.mark.parametrize("change", ["capability", "body_eligibility", "prediction"])
def test_new_capability_body_assessment_or_prediction_reopens_bound_disposition(change):
    store, target, event = bound_disposition_fixture()
    original = copy.deepcopy(event)
    if change == "capability":
        store.ai["template_routing"]["D-001"]["capabilities_sha256"] = "new-capabilities"
    elif change == "body_eligibility":
        store.ai["templates"]["D-001"]["cad_eligibility"]["value"]["supported"] = True
    else:
        store.raw_fields[target].update(state="known", value=3)
        store.fields[target] = copy.deepcopy(store.raw_fields[target])
    store._apply(event)
    assert "review" not in store.fields[target]
    assert len(store.pending_changed()) == 1
    assert store.changed[0]["change_reason"]
    assert event == original
    if change != "prediction":
        assert classify_review({"type": "template", **store.fields[target]})[0] == "human_input"


def test_stale_newer_disposition_cannot_resolve_earlier_stale_receipt():
    store, target, first = bound_disposition_fixture()
    second = {**copy.deepcopy(first), "decision_id": "fixture-newer-stale", "at": "2026-11-05T01:00:00Z"}
    store.events.append(second)
    store.ai["template_routing"]["D-001"]["capabilities_sha256"] = "new-capabilities"
    store._apply(first)
    store._apply(second)
    assert len(store.pending_changed()) == 2
    fresh = {**copy.deepcopy(second), "decision_id": "fixture-fresh", "at": "2026-11-05T02:00:00Z",
             "template_capability_sha256": store.template_capability_fingerprint(target)}
    store.events.append(fresh)
    store._apply(fresh)
    assert store.pending_changed() == []
    assert store.fields[target]["review"]["status"] == "deferred"


def test_legacy_disposition_without_optional_bindings_keeps_original_replay_semantics():
    store, target, event = bound_disposition_fixture()
    event.pop("prediction_sha256")
    event.pop("template_capability_sha256")
    original = copy.deepcopy(event)
    store.ai["template_routing"]["D-001"]["capabilities_sha256"] = "new-capabilities"
    store.ai["templates"]["D-001"]["cad_eligibility"]["value"]["supported"] = True
    store._apply(event)
    assert store.fields[target]["review"]["status"] == "deferred"
    assert store.changed == [] and event == original


def test_template_capability_binding_uses_raw_assessment_and_only_the_target_route():
    store, target, _ = bound_disposition_fixture()
    original = store.template_capability_fingerprint(target)
    store.templates["D-001"]["cad_eligibility"]["value"]["supported"] = True
    store.ai["template_routing"]["D-002"] = {"capabilities_sha256": "unrelated-change"}
    assert store.template_capability_fingerprint(target) == original
    store.ai["templates"]["D-001"]["cad_eligibility"]["value"]["reason"] = "Revised source assessment"
    assert store.template_capability_fingerprint(target) != original


def test_pending_bound_disposition_is_not_replayed_or_promoted_to_a_changed_review():
    store, target, event = bound_disposition_fixture()
    event["status"] = "pending"
    store.ai["template_routing"]["D-001"]["capabilities_sha256"] = "new-capabilities"
    store._apply(event)
    assert "review" not in store.fields[target] and store.changed == []
