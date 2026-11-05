"""Accuracy measures original proposals, without creating review receipts on disk."""
import copy
import json

import pytest

from backend.app.store import Store, mapping_source_signature, prediction_fingerprint


@pytest.fixture
def accuracy_store(monkeypatch):
    monkeypatch.setattr("backend.app.store.settings", lambda: {"reviewer_name": "Jason Peng"})
    store = Store.__new__(Store)
    drawing = {"id": "D-001", "sha256": "source-current"}
    part = {"drawing": drawing}
    store.records, store.rows = [part], {}
    store.raw_fields = {
        "D-001/drawing/material": {"value": "Steel", "method": "ai_verified"},
        "D-001/link": {"value": ["BOM:example/plate"], "method": "ai_verified"},
        "D-001/template/thickness": {"value": 2, "state": "known", "method": "ai_verified"},
        "D-001/drawing/title": {"value": "Plate", "method": "parsed"},
    }
    store.fields = copy.deepcopy(store.raw_fields)
    store.owners = {name: part for name in store.raw_fields}
    store.ai = {"mappings": [], "metrics": {"prep_sample": "independent"}}
    store.events, store.changed, store.mappings = [], [], []
    return store


def receipt(store, target, kind="confirm", **changes):
    event = {"applies_to": target, "type": kind, "status": "accepted",
             "by": "Meridian delegated reviewer", "review_kind": "delegated",
             "at": "2026-11-05T18:00:00+00:00",
             "delegated_by": "Jason Peng", "based_on": {"sha256": store.fingerprint(target)}}
    if target in store.raw_fields and kind in {"confirm", "reject"}:
        event["prediction_sha256"] = prediction_fingerprint(store.raw_fields[target])
    event.update(changes)
    return event


def test_current_authority_outcomes_are_latest_per_original_proposal(accuracy_store):
    store = accuracy_store
    scan, link, template, parsed = store.raw_fields
    store.events = [
        receipt(store, scan), receipt(store, scan, "reject"),
        receipt(store, link, by="Jason Peng", review_kind="human"),
        receipt(store, template),
        receipt(store, template, "reject", delegated_by="Someone else"),
        receipt(store, scan, by="Another person", review_kind="human"),
        receipt(store, scan, by="Automated fixture", review_kind="human"),
        receipt(store, scan, based_on={"sha256": "source-old"}),
        receipt(store, scan, based_on={}),
        receipt(store, scan, status="pending"),
        receipt(store, parsed),
    ]
    result = store.accuracy()
    assert result["jobs"] == {
        "scans": {"confirmed": 0, "rejected": 1},
        "matching": {"confirmed": 1, "rejected": 0},
        "templates": {"confirmed": 1, "rejected": 0},
        "mappings": {"confirmed": 0, "rejected": 0},
    }
    assert result["reviewed"] == 3 and result["accuracy"] == pytest.approx(2 / 3)
    assert result["delegated_reviewed"] == 2
    assert result["excluded_decisions"]["unauthorized"] == 3
    assert result["excluded_decisions"]["stale_source"] == 1
    assert result["excluded_decisions"]["unbound_source"] == 1
    assert result["excluded_decisions"]["nonfinal_outcome"] == 1
    assert result["excluded_decisions"]["not_ai"] == 1
    assert result["prep"] == store.ai["metrics"]


def test_mapping_approval_scores_the_immutable_proposed_relationship(accuracy_store):
    store = accuracy_store
    store.ai["mappings"] = [
        {"name": f"names/material/{name}", "method": "ai_verified", "relationship": "kind_of"}
        for name in ("agreed", "changed", "rejected")]
    # Replay changes the live mapping; the original prediction must stay the label basis.
    store.mappings = copy.deepcopy(store.ai["mappings"])
    store.mappings[1]["relationship"] = "same"
    agreed, changed, rejected = [mapping["name"] for mapping in store.ai["mappings"]]
    store.events = [receipt(store, agreed, "name_mapping", value={"relationship": "kind_of"}),
                    receipt(store, changed, "name_mapping", value="same"),
                    receipt(store, rejected, "name_mapping", value="kind_of", status="rejected")]
    before = copy.deepcopy((store.events, store.ai, store.mappings))
    result = store.accuracy()
    assert result["jobs"]["mappings"] == {"confirmed": 1, "rejected": 2}
    assert result["reviewed"] == 3 and result["accuracy"] == pytest.approx(1 / 3)
    assert (store.events, store.ai, store.mappings) == before


def test_effective_prior_mapping_approval_does_not_score_a_new_prediction(accuracy_store):
    store = accuracy_store
    mapping = {"name": "names/material/steel", "method": "ai_verified", "relationship": "same"}
    signature = mapping_source_signature(mapping, {"D-001": "source-current"}, {})
    mapping["prior_proposals"] = [{"sha256": "old-proposal", "source_signature": signature}]
    store.ai["mappings"] = [mapping]
    store.events = [receipt(store, mapping["name"], "name_mapping", value="same",
                            based_on={"sha256": "old-proposal"})]
    result = store.accuracy()
    assert result["reviewed"] == 0 and result["accuracy"] is None
    assert result["excluded_decisions"]["prior_mapping_proposal"] == 1
    store.records[0]["drawing"]["sha256"] = "changed-source"
    result = store.accuracy()
    assert result["excluded_decisions"]["stale_source"] == 1
    assert result["excluded_decisions"]["prior_mapping_proposal"] == 0


def test_replacements_never_become_correct_ai_predictions(accuracy_store):
    store = accuracy_store
    scan, link, template, _ = store.raw_fields
    store.events = [
        receipt(store, scan), receipt(store, scan, "correction", value="Aluminium"),
        receipt(store, scan),
        receipt(store, link, "reject"), receipt(store, link, "link", value=[]),
        receipt(store, link),
        receipt(store, template, "choose_option", value=3), receipt(store, template),
        receipt(store, template, "defer_unsupported"),
    ]
    result = store.accuracy()
    assert result["reviewed"] == 1 and result["accuracy"] == 0
    assert result["jobs"]["matching"] == {"confirmed": 0, "rejected": 1}
    assert result["excluded_decisions"]["corrected_replacement"] == 4


def test_prediction_binding_excludes_old_labels_on_unchanged_pdf(accuracy_store):
    store = accuracy_store
    target = "D-001/template/thickness"
    store.events = [receipt(store, target)]
    store.raw_fields[target]["value"] = 3
    result = store.accuracy()
    assert result["reviewed"] == 0 and result["accuracy"] is None
    assert result["excluded_decisions"]["stale_prediction"] == 1
    store.events.append(receipt(store, target, "reject"))
    result = store.accuracy()
    assert result["reviewed"] == 1 and result["accuracy"] == 0


def test_source_bound_legacy_review_limit_is_explicit(accuracy_store):
    store = accuracy_store
    target = "D-001/drawing/material"
    legacy = receipt(store, target, by="Jason Peng", review_kind="human")
    legacy.pop("prediction_sha256")
    store.events = [legacy]
    result = store.accuracy()
    assert result["reviewed"] == result["legacy_prediction_unbound_reviewed"] == 1
    assert "not whole-dataset accuracy" in result["note"]


def test_append_binds_original_prediction_without_rebinding_to_replayed_value(accuracy_store, tmp_path, monkeypatch):
    store = accuracy_store
    target = "D-001/template/thickness"
    store.decisions_dir = tmp_path / "decisions"
    monkeypatch.setattr(store, "reload", lambda: None)
    store.fields[target]["value"] = 99
    event = store.append(target, "confirm", by="Automated append fixture",
                         review_kind="delegated", delegated_by="Fixture authority")
    assert event["based_on"]["sha256"] == "source-current"
    assert event["prediction_sha256"] == prediction_fingerprint(store.raw_fields[target])
    assert event["prediction_sha256"] != prediction_fingerprint(store.fields[target])
    saved = json.loads((store.decisions_dir / (event["decision_id"] + ".json")).read_text(encoding="utf-8"))
    assert saved == event


def test_changed_original_reopens_approval_even_when_pdf_is_unchanged(accuracy_store):
    store = accuracy_store
    target = "D-001/template/thickness"
    event = receipt(store, target)
    store.raw_fields[target]["value"] = 3
    store.fields = copy.deepcopy(store.raw_fields)
    store._apply(event)
    assert "review" not in store.fields[target]
    assert store.changed == [{**event, "change_reason": "AI interpretation changed since review"}]
    store._apply(receipt(store, target))
    assert store.fields[target]["review"]["status"] == "human_confirmed"


def test_reader_receipt_refresh_preserves_original_approval(accuracy_store):
    store = accuracy_store
    target = "D-001/template/thickness"
    event = receipt(store, target)
    store.raw_fields[target].update(readers={"sol": {"at": "later", "reason": "new receipt"}},
                                    note="new receipt note", method="ai_verified_after_retry")
    store.fields = copy.deepcopy(store.raw_fields)
    store._apply(event)
    assert store.changed == []
    assert store.fields[target]["review"]["status"] == "human_confirmed"
    store.events = [event]
    assert store.accuracy()["reviewed"] == 1


def test_prediction_fingerprint_preserves_geometry_and_omission_reasons():
    original = {"state": "known", "value": {"holes": [{"x": 10, "y": 20, "diameter": 3}],
                                             "omitted": [{"reason": "Unlocated slot"}]}}
    changed = copy.deepcopy(original)
    changed["value"]["holes"][0]["x"] = 11
    assert prediction_fingerprint(changed) != prediction_fingerprint(original)
    changed = copy.deepcopy(original)
    changed["value"]["omitted"][0]["reason"] = "Different unsupported feature"
    assert prediction_fingerprint(changed) != prediction_fingerprint(original)
