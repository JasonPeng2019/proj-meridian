"""Targeted model refresh regressions without importing or running a CAD engine."""
import builtins
import copy
import json

import pytest

from backend.app.store import Store
from backend.cad import builder


def known(value):
    return {"state": "known", "value": value, "method": "ai_verified", "fact_ids": ["fixture/source"]}


@pytest.fixture
def two_parts(tmp_path, monkeypatch):
    generated = tmp_path / "generated"
    models = generated / "models"
    models.mkdir(parents=True)
    monkeypatch.setattr(builder, "GENERATED", generated)
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setattr("backend.app.store.settings", lambda: {"reviewer_name": "Automated model refresh fixture"})
    original_import = builtins.__import__

    def no_cad(name, *args, **kwargs):
        if name == "cadquery" or name.startswith("cadquery."):
            pytest.fail("Targeted refresh tests must not import CAD")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cad)
    templates, records, manifest = {}, [], {}
    for did in ("D-001", "D-002"):
        templates[did] = {"part": did, "outline": {"state": "known", "type": "rectangle",
                         "length": known(20), "width": known(10)}, "thickness": known(2), "features": []}
        records.append({"id": did + "/part", "key": did, "display_name": did, "bom": [],
                        "drawing": {"id": did, "sha256": did + "-source", "fields": {}},
                        "link": {"method": "exact_match", "value": []}})
        model = {"glb": f"models/{did}_A.glb", "step": f"models/{did}_A.step"}
        for path in model.values():
            (generated / path).write_bytes(("unchanged fixture export " + path).encode())
        manifest[did] = {"examples": ["A"], "models": {"A": model}, "stale": False,
                         "template_sha256": "shipped-template", "generator_version": "flat-part-13",
                         "waiting": [], "weight_check": {"state": "Skipped"},
                         "custom_provenance": {"preserve": ["original", did]}}
    cache = generated / "ai_cache/artifacts/cad/unrelated-shipped-cache"
    cache.mkdir(parents=True)
    (cache / "manifest.json").write_text('{"original":"cache receipt"}', encoding="utf-8")
    (cache / "D-002_A.glb").write_bytes(b"immutable cached model")
    for filename, data in {"records.json": records, "ai_results.json": {"templates": templates},
                           "models/manifest.json": manifest}.items():
        (generated / filename).write_text(json.dumps(data), encoding="utf-8")
    return tmp_path, generated, templates, manifest


def artifact_snapshot(generated):
    return {str(path.relative_to(generated)): (path.read_bytes(), path.stat().st_mtime_ns)
            for folder in (generated / "models", generated / "ai_cache") for path in folder.rglob("*")
            if path.is_file() and path != generated / "models/manifest.json"}


def test_editing_one_part_only_stales_its_model_and_preserves_other_exports_and_caches(two_parts):
    root, generated, _, old = two_parts
    before = artifact_snapshot(generated)
    store = Store(root)
    store.act("D-001/template/thickness", "set_value", 3)
    manifest = json.loads((generated / "models/manifest.json").read_text(encoding="utf-8"))
    assert manifest["D-001"]["stale"] is True
    assert manifest["D-002"] == old["D-002"]
    assert store.parts["D-001"]["has_3d"] is False
    assert store.parts["D-002"]["has_3d"] is True
    assert store.parts["D-002"]["model"] == old["D-002"]
    assert artifact_snapshot(generated) == before


def test_selected_build_merges_other_manifest_entries_even_when_their_templates_are_absent(two_parts):
    _, generated, templates, old = two_parts
    before = artifact_snapshot(generated)
    result = builder.build_all({"D-001": templates["D-001"]}, part_ids=["D-001"], allow_generation=False)
    assert set(result) == {"D-001", "D-002"}
    assert result["D-001"]["stale"] is True
    assert result["D-002"] == old["D-002"]
    assert json.loads((generated / "models/manifest.json").read_text(encoding="utf-8")) == result
    assert artifact_snapshot(generated) == before


@pytest.mark.parametrize("ids", [["D-001", "D-999"], ["../D-001"], "D-001", [["D-001"]]])
def test_selected_build_rejects_invalid_or_unknown_ids_before_processing_or_writing(two_parts, monkeypatch, ids):
    _, generated, templates, _ = two_parts
    before = (generated / "models/manifest.json").read_bytes()
    monkeypatch.setattr(builder, "_build_part", lambda *args, **kwargs: pytest.fail("Invalid selection reached CAD refresh"))
    with pytest.raises(ValueError):
        builder.build_all(templates, part_ids=ids, allow_generation=False)
    assert (generated / "models/manifest.json").read_bytes() == before


def test_store_rejects_unknown_refresh_ids_without_changing_models(two_parts):
    root, generated, _, _ = two_parts
    store = Store(root)
    before = (generated / "models/manifest.json").read_bytes()
    templates_before = copy.deepcopy(store.templates)
    with pytest.raises(ValueError, match="No CAD template"):
        store.rebuild_models(["D-001", "D-999"])
    assert store.templates == templates_before
    assert (generated / "models/manifest.json").read_bytes() == before


def test_full_build_without_selection_still_refreshes_every_prepared_template(two_parts, monkeypatch):
    _, _, templates, _ = two_parts
    calls = []

    def build(part_id, template, old, *, allow_generation):
        calls.append((part_id, allow_generation))
        return {"generator_version": "rebuilt-fixture", "template": template["part"]}

    monkeypatch.setattr(builder, "_build_part", build)
    result = builder.build_all()
    assert calls == [("D-001", True), ("D-002", True)]
    assert set(result) == set(templates)
    assert all(entry["generator_version"] == "rebuilt-fixture" for entry in result.values())


def test_empty_selection_is_a_noop(two_parts):
    _, generated, templates, old = two_parts
    before = (generated / "models/manifest.json").read_bytes()
    assert builder.build_all(templates, part_ids=[], allow_generation=False) == old
    assert (generated / "models/manifest.json").read_bytes() == before


def test_confirming_a_field_does_not_refresh_models(two_parts, monkeypatch):
    root, generated, _, old = two_parts
    store = Store(root)
    monkeypatch.setattr(store, "rebuild_models", lambda *args, **kwargs: pytest.fail("Confirmation refreshed CAD"))
    store.act("D-001/template/thickness", "confirm")
    assert json.loads((generated / "models/manifest.json").read_text(encoding="utf-8")) == old


@pytest.mark.parametrize("mutation", ["set_value", "choose_option", "reject", "accept_correction", "accept_changed_source"])
def test_template_mutation_routes_only_its_drawing_to_refresh(two_parts, monkeypatch, mutation):
    root, _, _, _ = two_parts
    store = Store(root)
    target = "D-001/template/thickness"
    calls = []
    monkeypatch.setattr(store, "rebuild_models", lambda part_ids=None: calls.append(part_ids))
    if mutation == "choose_option":
        store.fields[target].update(state="options", options=[2, 3])
        store.act("options:" + target, "choose_option", 3)
    elif mutation == "accept_correction":
        proposal = store.propose(target, 3, "Automated fixture correction proposal")
        store.act(proposal["decision_id"], "accept")
    elif mutation == "accept_changed_source":
        previous = store.append(target, "set_value", 3, based_on={"sha256": "older-source"})
        store.act("changed:" + previous["decision_id"], "accept")
    else:
        store.act(target, mutation, 3 if mutation == "set_value" else None)
    assert calls == [["D-001"]]


def blocked_geometry_store(two_parts, *, eligibility="supported"):
    root, generated, templates, _ = two_parts
    body = {"supported": eligibility == "supported", "constant_thickness": True,
            "outline_exact": True, "essential_uncertainty": []}
    templates["D-001"].update(cad_ready=False, blocking_fields=["thickness", "cad_eligibility"],
                              thickness={"state": "unknown", "value": None, "method": "ai_unsure"},
                              cad_eligibility=known(body) if eligibility != "unknown" else
                              {"state": "unknown", "value": None, "method": "ai_unsure"})
    (generated / "ai_results.json").write_text(json.dumps({"templates": templates}), encoding="utf-8")
    return Store(root)


def test_human_thickness_alternatives_clear_stale_readiness_only_after_effective_replay(two_parts):
    store = blocked_geometry_store(two_parts)
    _, generated, _, _ = two_parts
    source_bytes = (generated / "ai_results.json").read_bytes()
    untouched = copy.deepcopy(store.templates["D-002"])
    original_raw = copy.deepcopy(store.raw_fields["D-001/template/thickness"])
    event = store.append("D-001/template/thickness", "set_value", {"state": "options", "options": [3, 6]})
    effective = store.templates["D-001"]
    assert effective["cad_ready"] is True and effective["blocking_fields"] == []
    variants = list(builder._options(effective))
    assert [variant["thickness"]["value"] for variant, _ in variants] == [3, 6]
    for variant, _ in variants:
        builder._validate_essential(variant)
    assert effective["thickness"]["state"] == "options" and "selected" not in effective["thickness"]
    assert store.templates["D-002"] == untouched
    assert store.raw_fields["D-001/template/thickness"] == original_raw
    assert store.ai["templates"]["D-001"]["thickness"]["state"] == "unknown"
    assert (generated / "ai_results.json").read_bytes() == source_bytes
    assert store.events == [event]
    restarted = Store(store.root)
    assert restarted.templates["D-001"]["cad_ready"] is True
    assert restarted.templates["D-002"] == untouched


@pytest.mark.parametrize("eligibility", ["unknown", "unsupported"])
def test_human_thickness_cannot_override_unknown_or_unsupported_body_assessment(two_parts, eligibility):
    store = blocked_geometry_store(two_parts, eligibility=eligibility)
    store.append("D-001/template/thickness", "set_value", {"state": "options", "options": [3, 6]})
    effective = store.templates["D-001"]
    assert effective["cad_ready"] is False and effective["blocking_fields"]
    assert "cad_eligibility" in effective["blocking_fields"][0] if eligibility == "unknown" else "unsupported" in effective["blocking_fields"][0]


def test_later_rejection_is_applied_before_readiness_reconciliation(two_parts):
    store = blocked_geometry_store(two_parts)
    target = "D-001/template/thickness"
    accepted = store.append(target, "set_value", {"state": "options", "options": [3, 6]})
    rejected = store.append(target, "reject")
    effective = store.templates["D-001"]
    assert effective["thickness"]["state"] == "unknown"
    assert effective["cad_ready"] is False and "thickness" in effective["blocking_fields"][0]
    assert store.events == [accepted, rejected]


def test_readiness_never_treats_reviewed_bounds_as_a_single_dimension(two_parts):
    store = blocked_geometry_store(two_parts)
    store.append("D-001/template/thickness", "set_value", {"state": "bounds", "lower": 3, "upper": 6})
    effective = store.templates["D-001"]
    assert effective["cad_ready"] is False and "bounds" in effective["blocking_fields"][0]
    assert "value" not in effective["thickness"]


def test_missing_outline_blocks_even_when_human_thickness_is_supplied(two_parts):
    store = blocked_geometry_store(two_parts)
    _, generated, _, _ = two_parts
    raw = json.loads((generated / "ai_results.json").read_text(encoding="utf-8"))
    raw["templates"]["D-001"]["outline"] = {"state": "unknown"}
    (generated / "ai_results.json").write_text(json.dumps(raw), encoding="utf-8")
    store.reload()
    store.append("D-001/template/thickness", "set_value", {"state": "options", "options": [3, 6]})
    assert store.templates["D-001"]["cad_ready"] is False
    assert store.templates["D-001"]["blocking_fields"] == ["outline"]


def test_readiness_leaves_unedited_blocked_and_already_ready_metadata_unchanged(two_parts):
    store = blocked_geometry_store(two_parts)
    blocked = copy.deepcopy(store.templates["D-001"])
    ready = store.templates["D-002"]
    ready.update(cad_ready=True, blocking_fields=[], custom_readiness_receipt="preserve")
    ready["thickness"].update(method="human_decision", correction={"original": 1, "corrected": 2})
    ready_before = copy.deepcopy(ready)
    store._refresh_reviewed_readiness()
    assert store.templates["D-001"] == blocked
    assert store.templates["D-002"] == ready_before
