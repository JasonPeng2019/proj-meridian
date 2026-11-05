"""Remote-only independent checks reject missing, misplaced and unstepped cuts."""
import math

import pytest

from backend.cad import builder, verification


def known(value):
    return {"state": "known", "value": value, "confidence": "sure", "fact_ids": ["D-999/drawing/source"]}


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


@pytest.mark.parametrize("defect", ["missing", "misplaced", "blind", "missing_counterbore", "wrong_counterbore_face"])
def test_export_probes_catch_real_geometry_defects(defect, tmp_path):
    cq = pytest.importorskip("cadquery")
    plate, template = plate_and_template("counterbored" if "counterbore" in defect else "plain")
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
    step, mesh = exported(wrong, tmp_path)
    with pytest.raises(AssertionError, match="STEP feature"):
        verification.verify_features(template, {}, step, mesh, {"id": "D-999", "callouts": []})


def test_callout_gap_is_explicit_and_cannot_claim_complete():
    drawing = {"id": "D-999", "callouts": [{"name": "D-999/drawing/callout/holes", "text": "4 x 4,0 THRU ALL", "count": 4, "through": True}]}
    template = {"features_complete": known(True), "features_omitted": known([])}
    with pytest.raises(AssertionError, match="not covered"):
        verification.callout_coverage(drawing, template, [])
    template.update(features_complete=known(False), features_omitted=known([{"description": "Four holes", "reason": "No positions", "fact_ids": [drawing["callouts"][0]["name"]]}]))
    assert verification.callout_coverage(drawing, template, [])[0]["status"] == "documented_omission"


def test_feature_option_selection_is_not_overwritten_by_review_array():
    feature = {"diameter": {"state": "options", "options": [4, 5]}}
    template = {"features": [], "features_review": {"state": "known", "value": [feature]}}
    assert verification.selected_template(template, {"features.0.diameter": 5})["features"][0]["diameter"]["value"] == 5
