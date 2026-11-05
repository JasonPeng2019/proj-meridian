"""Remote-only independent checks reject missing, misplaced and unstepped cuts."""
import math

import pytest

from backend.cad import builder, verification


def known(value):
    return {"state": "known", "value": value, "confidence": "sure", "fact_ids": ["D-999/drawing/source"]}


@pytest.mark.parametrize("axis,expected", [("X", 0), ("horizontal", 0), ("Y", 90), ("VERTICAL", 90)])
def test_verification_axis_aliases_match_builder(axis, expected):
    assert verification.angle(axis) == builder._angle(axis, "direction") == expected
    assert verification.angle(known(axis)) == expected


def plate_and_template(profile="plain"):
    cq = pytest.importorskip("cadquery")
    feature = {"kind": "hole", "face": "top", "x": known(0), "y": known(0), "through": True,
               "diameter": known(4), "hole_type": profile}
    if profile == "counterbored":
        feature.update(counterbore_diameter=known(8), counterbore_depth=known(2))
    elif profile == "countersunk":
        feature.update(countersink_diameter=known(8), countersink_angle=known(90))
    elif profile == "slot":
        feature = {"kind": "slot", "face": "top", "x": known(0), "y": known(0), "through": False,
                   "depth": known(3), "width": known(4), "length": known(12), "direction": known(30)}
    template = {"outline": {"type": "rectangle", "length": known(40), "width": known(30)},
                "thickness": known(8), "features": [feature], "features_complete": known(True), "features_omitted": known([])}
    return cq.Workplane("XY").rect(40, 30).extrude(8), template


def exported(shape, tmp_path):
    cq = pytest.importorskip("cadquery")
    trimesh = pytest.importorskip("trimesh")
    path = tmp_path / "fixture.step"
    cq.exporters.export(shape, str(path), exportType="STEP")
    builder.export_glb(shape, tmp_path / "fixture.glb")
    mesh = trimesh.load(tmp_path / "fixture.glb", force="mesh", process=True)
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    return cq.importers.importStep(str(path)).val(), mesh


@pytest.mark.parametrize("profile", ["plain", "counterbored", "countersunk", "slot"])
def test_independent_export_probes_and_volume(profile, tmp_path):
    cq = pytest.importorskip("cadquery")
    plate, template = plate_and_template(profile)
    if profile == "slot":
        cutter = cq.Workplane("XY", origin=(0, 0, 5)).slot2D(12, 4, 30).extrude(3.01)
    else:
        cutter = cq.Workplane("XY", origin=(0, 0, -.01)).circle(2).extrude(8.02)
        if profile == "counterbored":
            cutter = cutter.union(cq.Workplane("XY", origin=(0, 0, 6)).circle(4).extrude(2.01))
        if profile == "countersunk":
            cutter = cutter.union(cq.Workplane(obj=cq.Solid.makeCone(2, 4, 2, cq.Vector(0, 0, 6))))
    step, mesh = exported(plate.cut(cutter), tmp_path)
    report = verification.verify_features(template, {}, step, mesh, {"id": "D-999", "callouts": []})
    assert report["cut_instances_checked"] == 1 and report["probe_count"] >= 11
    assert report["independent_volume_mm3"] == pytest.approx(step.Volume(), abs=.001)


@pytest.mark.parametrize("defect", ["missing", "misplaced", "blind", "missing_counterbore", "wrong_counterbore_face", "missing_countersink", "wrong_countersink_angle"])
def test_export_probes_catch_real_geometry_defects(defect, tmp_path):
    cq = pytest.importorskip("cadquery")
    plate, template = plate_and_template("counterbored" if "counterbore" in defect else "countersunk" if "countersink" in defect else "plain")
    if defect == "missing":
        wrong = plate
    elif defect == "misplaced":
        wrong = plate.cut(cq.Workplane("XY", origin=(6, 0, -.01)).circle(2).extrude(8.02))
    elif defect == "blind":
        wrong = plate.cut(cq.Workplane("XY", origin=(0, 0, 6)).circle(2).extrude(2.01))
    else:
        wrong = plate.cut(cq.Workplane("XY", origin=(0, 0, -.01)).circle(2).extrude(8.02))
        if defect == "wrong_counterbore_face":
            wrong = wrong.cut(cq.Workplane("XY", origin=(0, 0, -.01)).circle(4).extrude(2.01))
        if defect == "wrong_countersink_angle":
            height = 2 / math.tan(math.radians(60 / 2))
            wrong = wrong.cut(cq.Workplane(obj=cq.Solid.makeCone(2, 4, height, cq.Vector(0, 0, 8 - height))))
    step, mesh = exported(wrong, tmp_path)
    with pytest.raises(AssertionError, match="STEP feature"):
        verification.verify_features(template, {}, step, mesh, {"id": "D-999", "callouts": []})


@pytest.mark.parametrize("defect", ["missing_bore", "missing_countersink", "wrong_countersink_face"])
def test_glb_only_defects_are_rejected_with_a_correct_step(defect, tmp_path):
    cq = pytest.importorskip("cadquery")
    trimesh = pytest.importorskip("trimesh")
    profile = "plain" if defect == "missing_bore" else "countersunk"
    plate, template = plate_and_template(profile)
    bore = cq.Workplane("XY", origin=(0, 0, -.01)).circle(2).extrude(8.02)
    correct = plate.cut(bore)
    if profile == "countersunk":
        correct = correct.cut(cq.Workplane(obj=cq.Solid.makeCone(2, 4, 2, cq.Vector(0, 0, 6))))
    step, _ = exported(correct, tmp_path)
    wrong = plate if defect == "missing_bore" else plate.cut(bore)
    if defect == "wrong_countersink_face":
        wrong = wrong.cut(cq.Workplane(obj=cq.Solid.makeCone(4, 2, 2, cq.Vector(0, 0, 0))))
    builder.export_glb(wrong, tmp_path / "wrong.glb")
    mesh = trimesh.load(tmp_path / "wrong.glb", force="mesh", process=True)
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    with pytest.raises(AssertionError, match="GLB feature"):
        verification.verify_features(template, {}, step, mesh, {"id": "D-999", "callouts": []})


def test_callout_gap_is_explicit_and_cannot_claim_complete():
    drawing = {"id": "D-999", "callouts": [{"name": "D-999/drawing/callout/holes", "text": "4 x 4,0 THRU ALL", "count": 4, "through": True}]}
    template = {"features_complete": known(True), "features_omitted": known([])}
    with pytest.raises(AssertionError, match="not covered"):
        verification.callout_coverage(drawing, template, [])
    template.update(features_complete=known(False), features_omitted=known([{"description": "Four holes", "reason": "No positions", "fact_ids": [drawing["callouts"][0]["name"]]}]))
    assert verification.callout_coverage(drawing, template, [])[0]["status"] == "documented_omission"


def sink_group_fixture(sink_count):
    drawing = {"id": "D-999", "callouts": [
        {"name": "D-999/drawing/callout/bores", "text": "8 x 3,4 THRU ALL", "count": 8, "through": True},
        {"name": "D-999/drawing/callout/sinks", "text": "6,9 X 90°"}]}
    template = {"features_complete": known(True), "features_omitted": known([])}
    cuts = [{"index": index, "kind": "hole", "face": "top", "through": True, "diameter": 3.4,
             "hole_type": "countersunk" if index < sink_count else "plain", "outer": 3.45, "sink_angle": 90,
             "x": index * 10, "y": 0, "fact_ids": [], "coordinate_evidence": {}} for index in range(8)]
    return drawing, template, cuts


def test_every_hole_in_the_source_group_requires_its_countersink():
    drawing, template, cuts = sink_group_fixture(1)
    with pytest.raises(AssertionError, match="countersink callout omitted"):
        verification.callout_coverage(drawing, template, cuts)
    drawing, template, cuts = sink_group_fixture(8)
    row = verification.callout_coverage(drawing, template, cuts)[1]
    assert row["status"] == "covered" and row["expected_count"] == row["built_count"] == 8
    assert row["parent_source"] == drawing["callouts"][0]["name"]


def test_countersinks_at_other_bores_cannot_satisfy_the_source_group():
    drawing, template, cuts = sink_group_fixture(0)
    # Eight steps exist elsewhere, but none belongs to the source's 3.4 mm bores.
    cuts += [{**cut, "index": cut["index"] + 8, "x": cut["x"] + 100, "diameter": 2,
              "hole_type": "countersunk"} for cut in list(cuts)]
    with pytest.raises(AssertionError, match="countersink callout omitted"):
        verification.callout_coverage(drawing, template, cuts)


def test_feature_option_selection_is_not_overwritten_by_review_array():
    feature = {"diameter": {"state": "options", "options": [4, 5]}}
    template = {"features": [], "features_review": {"state": "known", "value": [feature]}}
    assert verification.selected_template(template, {"features.0.diameter": 5})["features"][0]["diameter"]["value"] == 5


def conflicting_counterbore():
    return {"kind": "hole", "face": "top", "x": known(0), "y": known(0), "through": True,
            "diameter": known(5.3), "hole_type": "counterbored", "counterbore_diameter": known(8),
            "counterbore_depth": known(15.4), "fact_ids": ["D-999/drawing/source"],
            "pattern": {"type": "circle", "count": known(3), "radius": known(15), "start_angle": known(0)}}


def test_step_fallback_requires_explicit_flag_and_sourced_reason():
    feature = conflicting_counterbore()
    with pytest.raises(ValueError, match="without fallback authorization"):
        verification.expanded_cuts({"features": [feature]}, 15)
    feature["allow_primary_hole_without_unresolved_step"] = True
    with pytest.raises(ValueError, match="authorization"):
        verification.expanded_cuts({"features": [feature]}, 15)
    feature["step_conflict_reason"] = "Printed depth 15.4 exceeds the printed 15 mm alternative"
    cuts = verification.expanded_cuts({"features": [feature]}, 15)
    assert len(cuts) == 3 and all(cut["hole_type"] == "plain" and cut["step_omitted"] for cut in cuts)
    assert all(cut["requested_step"]["step_depth"] == 15.4 for cut in cuts)
    assert all(cut["hole_type"] == "counterbored" and "step_omitted" not in cut
               for cut in verification.expanded_cuts({"features": [feature]}, 25))
    for thickness in (15, 25):
        scope = verification.source_inventory_scope(verification.expanded_cuts({"features": [feature]}, thickness), [])
        assert scope["independently_proves_all_drawing_features"] is False
        assert scope["counterbore_step_source_coverage"] == "not_parsed"
        assert scope["counterbore_feature_indices"] == [0]


def test_two_thickness_variants_retain_bores_and_only_omit_conflicting_step(tmp_path, monkeypatch):
    cq = pytest.importorskip("cadquery")
    trimesh = pytest.importorskip("trimesh")
    feature = {**conflicting_counterbore(), "allow_primary_hole_without_unresolved_step": True,
               "step_conflict_reason": "The drawing explicitly prints 15.4 depth and alternative plate thicknesses 15/25"}
    template = {"part": "D-999", "outline": {"type": "circle", "outer_diameter": known(50)},
                "thickness": {"state": "options", "options": [known(15), known(25)]},
                "features": [feature], "features_complete": known(False),
                "features_omitted": known([{"description": "Counterbore for 15 mm example", "reason": "Depth 15.4 exceeds thickness", "fact_ids": ["D-999/drawing/source"]}])}
    monkeypatch.setattr(builder, "GENERATED", tmp_path)
    part = builder.build_all({"D-999": template})["D-999"]
    assert part["examples"] == ["A", "B"]
    drawing = {"id": "D-999", "callouts": [{"name": "D-999/drawing/callout/1", "text": "3 x 5,3 THRU ALL", "count": 3, "through": True}]}
    for example, thickness in (("A", 15), ("B", 25)):
        model = part["models"][example]
        mesh = trimesh.load(tmp_path / model["glb"], force="mesh", process=True)
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        step = cq.importers.importStep(str(tmp_path / model["step"])).val()
        report = verification.verify_features(template, model, step, mesh, drawing)
        expected = math.pi * 25 ** 2 * thickness - 3 * math.pi * (5.3 / 2) ** 2 * thickness
        if example == "B":
            expected -= 3 * math.pi * (4 ** 2 - (5.3 / 2) ** 2) * 15.4
        assert model["volume_mm3"] == pytest.approx(expected, abs=.01)
        assert report["cut_instances_checked"] == 3
        assert bool(report["variant_step_omissions"]) is (example == "A")
        assert model["labels"][0]["hole_type"] == ("plain" if example == "A" else "counterbored")
        assert bool(model["labels"][0]["step_omitted"]) is (example == "A")
