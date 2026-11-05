"""Geometry/unit/cache smoke checks. All outputs stay in pytest's repo-local temp root."""
import copy
import builtins
import json
import math

import pytest

from backend.cad import builder


def known(value):
    return {"state":"known", "value":value, "fact_ids":["smoke/measurement"], "method":"ai_agreed", "confidence":"sure"}


def cube():
    return {"part":"D-999", "template":"flat_part", "outline":{"state":"known", "type":"rectangle", "length":known(10), "width":known(10)}, "thickness":known(10), "features":[]}


@pytest.mark.parametrize("change", [
    {"cad_ready": False, "blocking_fields": ["thickness"]},
    {"blocking_fields": ["outline_type"]},
    {"outline": {"type": "profile", "length": known(10), "width": known(10)}},
    {"cad_eligibility": known({"supported": False, "constant_thickness": False, "outline_exact": True, "essential_uncertainty": []})},
    {"cad_eligibility": {"state": "unknown", "value": None}},
    {"thickness": {"state": "unknown", "value": None}},
])
def test_essential_geometry_blocks_shipped_fallback_before_cad_import(change):
    template = {**cube(), **change}
    result = builder._build_part("D-999", template, {"models": {"A": {"glb": "old.glb"}}})
    assert not result["models"] and not result["examples"]
    assert result["waiting"]


def test_minor_feature_uncertainty_does_not_block_main_geometry():
    template = cube()
    template["cad_ready"] = True
    template["features_review"] = {"state": "unknown", "note": "Minor hole positions are not dimensioned"}
    template["features"] = [{"kind": "hole", "state": "unknown"}]
    template["cad_eligibility"] = known({"supported": True, "constant_thickness": True, "outline_exact": True, "essential_uncertainty": []})
    builder._validate_essential(template)


def test_inventory_uses_live_review_wrappers_instead_of_stale_flags():
    template = {**cube(), "features_status": "complete", "features_all_determined": True,
                "omitted_feature_notes": [], "features_complete": known(False),
                "features_omitted": known([{"description": "Four holes", "reason": "Positions undimensioned", "fact_ids": ["drawing/source"]}])}
    inventory = builder.feature_inventory(template)
    assert inventory["status"] == "partial" and not inventory["all_determined"]
    assert "Positions undimensioned" in inventory["notes"][0]
    template.update(features_status="partial", features_all_determined=False, omitted_feature_notes=["stale"],
                    features_complete=known(True), features_omitted=known([]))
    assert builder.feature_inventory(template) == {"status": "complete", "all_determined": True, "notes": []}


@pytest.mark.parametrize("old", [None, {"models": {"A": {"glb": "models/old.glb"}}, "examples": ["A"], "template_sha256": "old", "generator_version": "old"}])
def test_cache_only_never_imports_cad_even_when_installed(tmp_path, monkeypatch, old):
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name == "cadquery" or name.startswith("cadquery."):
            pytest.fail("cache-only mode must not import CAD")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(builder, "GENERATED", tmp_path)
    if old:
        (tmp_path / "models").mkdir()
        (tmp_path / "models/manifest.json").write_text(json.dumps({"D-999": old}), encoding="utf-8")
    result = builder.build_all({"D-999": cube()}, allow_generation=False)["D-999"]
    assert result["cache_only"]
    if old:
        assert result["stale"] and result["models"] == old["models"]
    else:
        assert not result["models"] and "GitHub Actions" in result["waiting"][0]


def test_cache_only_copies_verified_cache_hit_before_cad_gate(tmp_path, monkeypatch):
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name == "cadquery" or name.startswith("cadquery."):
            pytest.fail("cache hit must not import CAD")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(builder, "GENERATED", tmp_path)
    template = cube()
    densities = builder._read(builder.Path(builder.__file__).with_name("densities.json"), [])
    cache = tmp_path / "ai_cache/artifacts/cad" / builder._hash({"version": builder.VERSION, "template": template, "densities": densities})
    cache.mkdir(parents=True)
    model = {"glb": "models/D-999_A.glb", "step": "models/D-999_A.step"}
    for filename in ("D-999_A.glb", "D-999_A.step"):
        (cache / filename).write_bytes(b"cached artifact fixture")
    (cache / "manifest.json").write_text(json.dumps({"models": {"A": model}, "examples": ["A"]}), encoding="utf-8")
    result = builder.build_all({"D-999": template}, allow_generation=False)["D-999"]
    assert result["cache_hit"] and (tmp_path / model["glb"]).read_bytes() == b"cached artifact fixture"


def test_partial_inventory_retains_supported_cut_geometry():
    pytest.importorskip("cadquery")
    template = cube()
    template["features"] = [{"kind": "hole", "face": "top", "x": known(0), "y": known(0), "diameter": known(2), "through": True, "hole_type": "plain", "fact_ids": ["smoke/callout"]}]
    template["features_complete"] = known(False)
    template["features_omitted"] = known([{"description": "Other holes", "reason": "No XY positions", "fact_ids": ["drawing/source"]}])
    shape, waiting, omitted, labels = builder.build_shape(template)
    assert shape.val().Volume() == pytest.approx(1000 - math.pi * 10)
    assert len(labels) == 1 and "features_complete" in waiting
    assert "Other holes: No XY positions" in omitted


def test_cube_mm_step_glb_and_cached_rebuild(tmp_path, monkeypatch):
    cq = pytest.importorskip("cadquery")
    trimesh = pytest.importorskip("trimesh")
    monkeypatch.setattr(builder, "GENERATED", tmp_path)
    result = builder.build_all({"D-999":cube()})["D-999"]
    model = result["models"]["A"]
    assert model["volume_mm3"] == pytest.approx(1000)
    assert model["bounds_mm"]["size"] == pytest.approx([10,10,10])
    mesh = trimesh.load(tmp_path/model["glb"])
    assert mesh.extents == pytest.approx([.01,.01,.01])
    assert cq.importers.importStep(str(tmp_path/model["step"])).val().Volume() == pytest.approx(1000)
    assert builder.NOTICE in (tmp_path/model["step"]).read_text()
    assert "'2;1');1');" not in (tmp_path/model["step"]).read_text()
    (tmp_path/model["glb"]).unlink()
    (tmp_path/model["step"]).unlink()
    monkeypatch.setattr(builder, "build_shape", lambda *a: pytest.fail("cache must avoid CAD"))
    rebuilt = builder.build_all({"D-999":cube()})["D-999"]
    assert rebuilt["cache_hit"]
    assert (tmp_path/model["glb"]).exists()


def test_unknown_options_and_cosmetic_thread(tmp_path, monkeypatch):
    pytest.importorskip("cadquery")
    template = cube()
    template["thickness"] = {"state":"unknown"}
    monkeypatch.setattr(builder, "GENERATED", tmp_path)
    pending = builder.build_all({"D-999":template})["D-999"]
    assert pending["examples"] == []
    assert "thickness" in pending["waiting"]
    no_evidence = cube()
    no_evidence["thickness"] = {"state":"known","value":10,"method":"ai_agreed"}
    assert builder.build_all({"D-999":no_evidence})["D-999"]["examples"] == []
    template["thickness"] = {"state":"options", "options":[known(10),known(5)], "fact_ids":["smoke/thickness"]}
    template["features"] = [{"kind":"hole", "name":"M3", "face":"top", "x":known(0),"y":known(0),"diameter":known(2.5),"through":True,"hole_type":"threaded","thread":"M3","fact_ids":["smoke/hole"]}, {"kind":"hole","x":{"state":"unknown"},"fact_ids":["smoke/unknown"]}]
    result = builder.build_all({"D-999":template})["D-999"]
    assert result["examples"] == ["A","B"]
    assert len(result["omitted"]) == 1
    assert result["models"]["A"]["volume_mm3"] == pytest.approx(1000-math.pi*1.25**2*10)
    assert "Cosmetic" in result["models"]["A"]["labels"][0]["thread_representation"]


def test_holes_slots_patterns_and_weight_states():
    pytest.importorskip("cadquery")
    template = cube()
    template["outline"] = {"type":"ring","outer_diameter":known(50),"inner_diameter":known(20)}
    template["features"] = [{"kind":"hole","face":"top","x":known(0),"y":known(0),"diameter":known(2),"through":True,"hole_type":"countersunk","countersink_diameter":known(4),"countersink_angle":known(90),"pattern":{"type":"circle","count":known(4),"radius":known(17),"start_angle":known(0)},"fact_ids":["smoke/pattern"]}]
    shape, waiting, omitted, labels = builder.build_shape(template)
    assert shape.val().isValid() and not waiting and not omitted
    assert labels[0]["count"] == 4
    assert shape.val().Volume() < math.pi*(25**2-10**2)*10
    shape.val().tessellate(0.03, 0.12)
    assert builder.shape_bounds_mm(shape)["size"] == pytest.approx([50,50,10], abs=1e-6)
    rectangle = cube()
    rectangle["outline"]["length"] = known(50)
    rectangle["outline"]["width"] = known(30)
    rectangle["features"] = [{"kind":"slot","face":"bottom","x":known(-10),"y":known(0),"length":known(8),"width":known(3),"direction":"vertical","through":False,"depth":known(2),"pattern":{"type":"row","count":known(2),"spacing":known(20),"direction":"x"},"fact_ids":["smoke/slots"]}, {"kind":"hole","face":"bottom","x":known(0),"y":known(7),"diameter":known(3),"through":True,"hole_type":"counterbored","counterbore_diameter":known(6),"counterbore_depth":known(2),"fact_ids":["smoke/bore"]}]
    row_shape, waiting, omitted, row_labels = builder.build_shape(rectangle)
    assert not waiting and not omitted and row_shape.val().isValid()
    assert row_labels[0]["count"] == 2
    assert row_shape.val().Volume() < 50*30*10
    models = {"A":{"volume_mm3":1000},"B":{"volume_mm3":2000}}
    template = {"weight_on_drawing":known(2.7),"material":known("Aluminium")}
    assert builder.weight_check(template,models)["state"] == "Passed"
    template["material"] = known("Stainless steel")
    template["bom_materials"] = ["Aluminium"]
    assert builder.weight_check(template,models)["state"] == "Flagged"
    template["weight_on_drawing"] = known(100)
    assert builder.weight_check(template,models)["state"] == "FAILED"
    template["weight_on_drawing"] = {"confidence":"unsure","value":2.7}
    assert builder.weight_check(template,models)["state"] == "Skipped"
    parsed_weight = {"weight_on_drawing":{"name":"D-999/drawing/weight_g","value":2.7,"method":"parsed","confidence":"sure"},"material":known("Aluminium")}
    assert builder.weight_check(parsed_weight,models)["state"] == "Passed"


def test_sourced_full_thickness_corner_clips_preserve_exact_setbacks():
    pytest.importorskip("cadquery")
    template = cube()
    template["features"] = [{"kind": "corner_chamfer", "corners": ["x_min_y_min", "x_min_y_max", "x_max_y_min", "x_max_y_max"],
                             "x_setback": known(1), "y_setback": known(2), "fact_ids": ["smoke/corners"]}]
    shape, waiting, omitted, labels = builder.build_shape(template)
    assert not waiting and not omitted
    assert labels[0]["count"] == 4
    assert shape.val().Volume() == pytest.approx(1000 - 4 * 1 * 2 / 2 * 10)
    assert builder.shape_bounds_mm(shape)["size"] == pytest.approx([10, 10, 10])


@pytest.mark.parametrize("field,bad", [("z", None), ("x", known(0)), ("z", known(0)), ("hole_type", "counterbored")])
def test_side_holes_never_infer_missing_z_or_change_axis(field, bad):
    pytest.importorskip("cadquery")
    template = cube()
    feature = {"kind": "hole", "face": "x_min", "x": known(-5), "y": known(0), "z": known(5),
               "diameter": known(2), "hole_type": "threaded", "thread": "M3", "through": True, "fact_ids": ["smoke/side"]}
    feature[field] = bad
    template["features"] = [feature]
    shape, waiting, omitted, labels = builder.build_shape(template)
    assert shape.val().Volume() == pytest.approx(1000)
    assert waiting == ["features.0"] and len(omitted) == 1 and labels == []
