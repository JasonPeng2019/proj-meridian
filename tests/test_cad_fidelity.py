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


def detailed_template(kind, face="x_min", through=True):
    template = {"outline": {"type": "rectangle", "length": known(40), "width": known(30)},
                "thickness": known(8), "features_complete": known(True), "features_omitted": known([])}
    if kind == "corner_chamfer":
        feature = {"kind": kind, "corners": ["x_min_y_min", "x_min_y_max", "x_max_y_min", "x_max_y_max"],
                   "x_setback": known(1), "y_setback": known(2), "fact_ids": ["D-999/drawing/source"]}
    else:
        x = -20 if face == "x_min" else 20 if face == "x_max" else 0
        y = -15 if face == "y_min" else 15 if face == "y_max" else 0
        feature = {"kind": "hole", "face": face, "x": known(x), "y": known(y), "z": known(4),
                   "diameter": known(4), "hole_type": "threaded", "thread": "M5", "through": through,
                   "fact_ids": ["D-999/drawing/source"]}
        if not through:
            feature["depth"] = known(5)
    template["features"] = [feature]
    return template


@pytest.mark.parametrize("face", ["x_min", "x_max", "y_min", "y_max"])
@pytest.mark.parametrize("through", [True, False])
def test_side_holes_have_correct_axis_depth_and_exported_geometry(face, through, tmp_path):
    pytest.importorskip("cadquery")
    template = detailed_template("hole", face, through)
    shape, waiting, omitted, labels = builder.build_shape(template)
    assert not waiting and not omitted and len(labels) == 1
    span = 40 if face.startswith("x_") else 30
    assert shape.val().Volume() == pytest.approx(40 * 30 * 8 - math.pi * 2 ** 2 * (span if through else 5))
    step, mesh = exported(shape, tmp_path)
    report = verification.verify_features(template, {}, step, mesh, {"id": "D-999", "callouts": []})
    assert report["cut_instances_checked"] == 1
    assert report["cuts"][0]["center_mm"][2] == 4
    assert report["cuts"][0]["depth_mm"] == (span if through else 5)


def test_corner_clips_have_exact_setbacks_in_step_and_glb(tmp_path):
    pytest.importorskip("cadquery")
    template = detailed_template("corner_chamfer")
    shape, waiting, omitted, labels = builder.build_shape(template)
    assert not waiting and not omitted and labels[0]["count"] == 4
    assert shape.val().Volume() == pytest.approx(40 * 30 * 8 - 4 * 1 * 2 / 2 * 8)
    step, mesh = exported(shape, tmp_path)
    report = verification.verify_features(template, {}, step, mesh, {"id": "D-999", "callouts": []})
    assert report["cut_instances_checked"] == 4 and report["probe_count"] == 84


@pytest.mark.parametrize("kind", ["hole", "corner_chamfer"])
@pytest.mark.parametrize("bad_export", ["step", "glb"])
def test_detail_probes_reject_omitted_side_bores_and_corner_clips(kind, bad_export, tmp_path):
    cq = pytest.importorskip("cadquery")
    template = detailed_template(kind)
    correct, waiting, omitted, _ = builder.build_shape(template)
    assert not waiting and not omitted
    correct_step, correct_mesh = exported(correct, tmp_path)
    wrong_step, wrong_mesh = exported(cq.Workplane("XY").rect(40, 30).extrude(8), tmp_path)
    with pytest.raises(AssertionError, match=("STEP" if bad_export == "step" else "GLB") + " feature"):
        verification.verify_features(template, {}, wrong_step if bad_export == "step" else correct_step,
                                     wrong_mesh if bad_export == "glb" else correct_mesh, {"id": "D-999", "callouts": []})


def test_side_bore_identity_includes_axis_z_and_normalizes_opposite_entries():
    template = detailed_template("hole")
    left = verification.expanded_cuts(template, 8)[0]
    right = verification.expanded_cuts(detailed_template("hole", "x_max"), 8)[0]
    vertical = verification.expanded_cuts(detailed_template("hole", "y_min"), 8)[0]
    assert verification.primary_bore_identity(left) == verification.primary_bore_identity(right)
    assert verification.primary_bore_identity(left) != verification.primary_bore_identity(vertical)
    assert verification.primary_bore_identity(left) != verification.primary_bore_identity({**left, "z": 5})


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


def equal_diameter_source_groups():
    drawing = {"id": "D-999", "callouts": [
        {"name": "thread", "text": "8 x 4,2 THRU ALL M5 - 6H", "count": 8, "through": True, "thread": "M5", "page": 1, "box": [500, 0, 100, 18]},
        {"name": "bores-a", "text": "8 x 6,6 THRU ALL", "count": 8, "through": True, "page": 1, "box": [0, 0, 100, 18]},
        {"name": "sinks-a", "text": "13,4 X 90°", "page": 1, "box": [30, 16, 60, 18]},
        {"name": "bores-b", "text": "2 x 6,6 THRU ALL", "count": 2, "through": True, "page": 1, "box": [200, 0, 100, 18]},
        {"name": "sinks-b", "text": "14,4 X 90°", "page": 1, "box": [230, 16, 60, 18]}]}
    cuts = []
    for count, diameter, outer, face, refs, thread in (
            (8, 4.2, None, "top", ["thread"], "M5 - 6H"),
            (8, 6.6, 13.4, "top", ["bores-a", "sinks-a"], None),
            (2, 6.6, 14.4, "bottom", ["bores-b", "sinks-b"], None)):
        for _ in range(count):
            cut = {"index": len(cuts), "kind": "hole", "face": face, "through": True,
                   "diameter": diameter, "x": len(cuts) * 20, "y": 0, "fact_ids": list(refs),
                   "coordinate_evidence": {}, "thread": thread, "hole_type": "threaded" if thread else "countersunk"}
            if outer:
                cut.update(outer=outer / 2, sink_angle=90)
            cuts.append(cut)
    return drawing, {"features_complete": known(True), "features_omitted": known([])}, cuts


@pytest.mark.parametrize("step_ids_only", [False, True])
def test_equal_diameter_groups_use_exact_or_attached_source_ids(step_ids_only):
    drawing, template, cuts = equal_diameter_source_groups()
    if step_ids_only:
        for cut in cuts:
            cut["fact_ids"] = [ref for ref in cut["fact_ids"] if not ref.startswith("bores-")]
    rows = verification.callout_coverage(drawing, template, cuts)
    assert [row["built_count"] for row in rows] == [8, 8, 8, 2, 2]
    assert all(row["status"] == "covered" for row in rows)
    assert rows[2]["parent_source"] == "bores-a" and rows[4]["parent_source"] == "bores-b"


@pytest.mark.parametrize("defect", ["missing", "wrong_group", "ambiguous", "conflicting", "wrong_step"])
def test_equal_diameter_source_groups_reject_missing_wrong_or_ambiguous_assignment(defect):
    drawing, template, cuts = equal_diameter_source_groups()
    if defect == "missing":
        cuts.pop()
    elif defect == "wrong_group":
        for cut in cuts:
            if cut["diameter"] == 6.6:
                cut["fact_ids"] = ["bores-b", "sinks-b"] if cut["face"] == "top" else ["bores-a", "sinks-a"]
    elif defect == "ambiguous":
        for cut in cuts:
            if cut["diameter"] == 6.6:
                cut["fact_ids"] = ["D-999/drawing/source"]
    elif defect == "conflicting":
        cuts[8]["fact_ids"] = ["bores-a", "bores-b"]
    else:
        cuts[8]["outer"] = 14.4 / 2
    with pytest.raises(AssertionError):
        verification.callout_coverage(drawing, template, cuts)


def test_explicitly_counted_countersinks_bind_their_own_source_counts():
    drawing = {"id": "D-999", "callouts": [
        {"name": "step-a", "text": "2 x 8,0 X 90°", "count": 2},
        {"name": "step-b", "text": "3 x 10,0 X 90°", "count": 3}]}
    template = {"features_complete": known(True), "features_omitted": known([])}
    cuts = [{"index": i, "kind": "hole", "face": "top", "through": True, "diameter": 4,
             "hole_type": "countersunk", "outer": 4 if i < 2 else 5, "sink_angle": 90,
             "x": i * 20, "y": 0, "fact_ids": ["step-a" if i < 2 else "step-b"], "coordinate_evidence": {}} for i in range(5)]
    rows = verification.callout_coverage(drawing, template, cuts)
    assert [row["expected_count"] for row in rows] == [2, 3]
    assert all(row["count_scope"] == "explicit_step_count" for row in rows)
    assert [row["parent_source"] for row in rows] == ["step-a", "step-b"]
    with pytest.raises(AssertionError):
        verification.callout_coverage(drawing, template, cuts[1:])
    with pytest.raises(ValueError, match="disagrees"):
        verification.countersink_spec({"text": "2 x 8,0 X 90°", "count": 3})


@pytest.mark.parametrize("degree", ["\u00b0", "\u00c2\u00b0"])
def test_equivalent_degree_encodings_preserve_source_text(degree):
    callout = {"text": f"2 x 13,4 X 90{degree}", "count": 2}
    original = callout["text"]
    assert verification.countersink_spec(callout) == {"count": 2, "outer": 13.4, "angle": 90}
    assert callout["text"] == original


def test_mojibake_degree_lines_still_cover_both_equal_diameter_sink_groups():
    drawing, template, cuts = equal_diameter_source_groups()
    drawing["callouts"][2]["text"] = "13,4 X 90\u00c2\u00b0"
    drawing["callouts"][4]["text"] = "14,4 X 90\u00c2\u00b0"
    original = [item["text"] for item in drawing["callouts"]]
    rows = verification.callout_coverage(drawing, template, cuts)
    assert len(rows) == 5
    assert [row["built_count"] for row in rows] == [8, 8, 8, 2, 2]
    assert all(row["status"] == "covered" for row in rows)
    assert [item["text"] for item in drawing["callouts"]] == original


@pytest.mark.parametrize("text", ["13,4 X 90A\u00b0", "13,4 X 90\u00c3\u00b0", "13,4 X 90\u00c2",
                                 "unrelated 13,4 X 90\u00c2\u00b0", "2.5 x 13,4 X 90\u00c2\u00b0"])
def test_malformed_or_unrelated_degree_text_is_not_a_countersink(text):
    assert verification.countersink_spec({"text": text}) is None


def two_sided_step_fixture():
    drawing = {"id": "D-999", "callouts": [
        {"name": "plain", "text": "6 x 3,0 THRU ALL", "count": 6, "through": True, "page": 1, "box": [400, 0, 100, 18]},
        {"name": "primary", "text": "3 x 4,0 THRU ALL", "count": 3, "through": True, "page": 1, "box": [0, 0, 100, 18]},
        {"name": "sink", "text": "8,0 X 90°", "page": 1, "box": [30, 16, 60, 18]}]}
    template = {"features_complete": known(True), "features_omitted": known([]),
                "outline": {"type": "rectangle", "length": known(150), "width": known(80)}}
    cuts = [{"index": i, "kind": "hole", "face": "top", "through": True, "diameter": 3,
             "hole_type": "plain", "depth": 8, "radius": 1.5, "x": i * 10 - 25, "y": 20,
             "fact_ids": ["plain"], "coordinate_evidence": {}} for i in range(6)]
    for i in range(3):
        shared = {"kind": "hole", "through": True, "diameter": 4, "depth": 8,
                  "x": i * 20 - 20, "y": -10, "coordinate_evidence": {}}
        cuts.append({**shared, "index": 6 + i, "face": "top", "hole_type": "countersunk", "outer": 4,
                     "radius": 4, "sink_angle": 90, "step_depth": 2, "fact_ids": ["primary", "sink"]})
        cuts.append({**shared, "index": 9 + i, "face": "bottom", "hole_type": "counterbored", "outer": 5,
                     "radius": 5, "step_depth": 2, "fact_ids": ["D-999/drawing/source"]})
    return drawing, template, cuts


def test_two_face_steps_share_a_primary_through_bore_but_not_a_step_count():
    drawing, template, cuts = two_sided_step_fixture()
    rows = verification.callout_coverage(drawing, template, cuts)
    assert [row["built_count"] for row in rows] == [6, 3, 3]
    assert rows[1]["operation_count"] == 6
    assert all(row["status"] == "covered" for row in rows)
    # Coincident operations require union probes, never double-subtracted primary volume.
    assert verification.analytic_volume(template, cuts, 8) is None


@pytest.mark.parametrize("defect", ["missing_bore", "misplaced_opposite_bore", "extra_bore", "missing_sink", "extra_opposite_sink"])
def test_two_sided_step_inventory_rejects_wrong_primary_or_face_specific_counts(defect):
    drawing, template, cuts = two_sided_step_fixture()
    if defect == "missing_bore":
        cuts = [cut for cut in cuts if not (cut["diameter"] == 4 and cut["x"] == 20)]
    elif defect == "misplaced_opposite_bore":
        next(cut for cut in cuts if cut["hole_type"] == "counterbored")["x"] += 1
    elif defect == "extra_bore":
        cuts.append({**cuts[-1], "x": 60})
    elif defect == "missing_sink":
        cuts = [cut for cut in cuts if not (cut["hole_type"] == "countersunk" and cut["x"] == 20)]
    else:
        sink = next(cut for cut in cuts if cut["hole_type"] == "countersunk")
        cuts.append({**sink, "face": "bottom"})
    with pytest.raises(AssertionError):
        verification.callout_coverage(drawing, template, cuts)


def test_opposite_blind_holes_remain_distinct_primary_instances():
    drawing = {"id": "D-999", "callouts": [{"name": "blind", "text": "2 x 4,0", "count": 2}]}
    template = {"features_complete": known(True), "features_omitted": known([])}
    cuts = [{"index": i, "kind": "hole", "face": face, "through": False, "depth": 3, "diameter": 4,
             "hole_type": "plain", "x": 0, "y": 0, "fact_ids": ["blind"], "coordinate_evidence": {}}
            for i, face in enumerate(("top", "bottom"))]
    assert verification.callout_coverage(drawing, template, cuts)[0]["built_count"] == 2
    for cut in cuts:
        cut["through"] = True
    with pytest.raises(AssertionError):
        verification.callout_coverage(drawing, template, cuts)


def test_same_face_blind_depth_operations_cannot_satisfy_a_two_hole_count():
    drawing = {"id": "D-999", "callouts": [{"name": "blind", "text": "2 x 4,0", "count": 2}]}
    template = {"features_complete": known(True), "features_omitted": known([])}
    cuts = [{"index": i, "kind": "hole", "face": "top", "through": False, "depth": depth, "diameter": 4,
             "hole_type": "plain", "x": 0, "y": 0, "fact_ids": ["blind"], "coordinate_evidence": {}}
            for i, depth in enumerate((3, 4))]
    assert verification.primary_bore_identity(cuts[0]) == verification.primary_bore_identity(cuts[1])
    with pytest.raises(AssertionError):
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
