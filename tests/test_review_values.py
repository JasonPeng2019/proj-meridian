"""Typed review input checks; fixtures do not author real human decisions."""
import copy

import pytest

from backend.app.review_values import validate_review_value
from backend.app.store import Store


def validate(tail, value, current=None, template=None):
    return validate_review_value("D-TEST/template/" + tail, value, {"value": current}, template)


@pytest.mark.parametrize("value", ["4.5", True, None, float("inf"), float("nan"), 0, -1])
def test_sizes_require_actual_positive_finite_numbers(value):
    with pytest.raises(ValueError):
        validate("thickness", value)


@pytest.mark.parametrize("field", ["thickness", "length", "width", "outer_diameter", "inner_diameter", "outline/length", "outline/width"])
def test_scalar_template_alternatives_are_distinct_positive_values_without_selection(field):
    original = {"state": "options", "options": [6, 3]}
    result = validate_review_value("D-TEST/template/" + field, original, {"value": 4}, strict_options=True)
    assert result == {"state": "options", "options": [3, 6]}
    assert original == {"state": "options", "options": [6, 3]}


@pytest.mark.parametrize("value", [
    {"state": "options", "options": [3]}, {"state": "options", "options": [3, 6, 9]},
    {"state": "options", "options": [3, 3.0]}, {"state": "options", "options": [3, -6]},
    {"state": "options", "options": [0, 6]}, {"state": "options", "options": [3, True]},
    {"state": "options", "options": [3, "6"]}, {"state": "options", "options": [3, [6]]},
    {"state": "options", "options": [3, {"value": 6}]},
    {"state": "options", "options": [3, float("inf")]},
    {"state": "options", "options": [3, 6], "selected": 3},
    {"state": "options", "options": [3, 6], "value": 3},
    {"state": "options", "options": [3, 6], "bounds": [3, 6]},
    [3, 6],
])
def test_new_formatter_alternatives_reject_invalid_shapes_values_and_fake_selection(value):
    with pytest.raises(ValueError):
        validate_review_value("D-TEST/template/thickness", value, {"value": 4}, strict_options=True)


@pytest.mark.parametrize("target,current", [
    ("D-TEST/drawing/material", "Steel"), ("D-TEST/link", []),
    ("D-TEST/template/features_complete", True), ("D-TEST/template/count", 2),
    ("D-TEST/template/features/0/diameter", 3), ("D-TEST/template/outline", {}),
    ("D-TEST/template/features_review", []),
])
def test_alternatives_do_not_expand_to_text_links_booleans_or_structured_geometry(target, current):
    with pytest.raises(ValueError):
        validate_review_value(target, {"state": "options", "options": [3, 6]}, {"value": current}, strict_options=True)


@pytest.mark.parametrize("choices", [[3], [3, 6], [3, 6, 9], [3, 6, 9, 12]])
def test_legacy_thickness_api_keeps_one_to_four_alternatives(choices):
    assert validate("thickness", {"state": "options", "options": choices}) == {"state": "options", "options": choices}


def test_legacy_thickness_api_preserves_known_wrapped_readings():
    value = {"state": "options", "options": [{"state": "known", "value": 3}, {"state": "known", "value": 6}]}
    assert validate("thickness", value) == value


def test_signed_coordinates_counts_and_booleans():
    assert validate("x", -12.5) == -12.5
    assert validate("offset", 0) == 0
    assert validate("count", 4) == 4
    assert validate("features_complete", False) is False
    for field, value in [("count", 1.5), ("count", 0), ("features_complete", "false"), ("features_complete", 0)]:
        with pytest.raises(ValueError):
            validate(field, value)


def test_generic_value_types_and_plain_text():
    assert validate("material", ["Steel"], ["Aluminium"]) == ["Steel"]
    assert validate("settings", {"key": "value"}, {}) == {"key": "value"}
    assert validate("note", 'The source says "A".') == 'The source says "A".'
    for field, value, current in [("material", "Steel", []), ("settings", [], {}), ("note", {}, None), ("note", "  ", None)]:
        with pytest.raises(ValueError):
            validate(field, value, current)


def test_outline_is_canonical_and_sourced_without_eligibility_changes():
    template = {"cad_ready": False, "blocking_fields": ["profile"], "cad_eligibility": {"state": "unknown"}}
    before = copy.deepcopy(template)
    result = validate("outline", {"state": "known", "type": "rectangle", "length": {"state": "known", "value": 40}, "width": 20}, template=template)
    assert result["length"] == {"state": "known", "value": 40, "method": "human_decision", "fact_ids": ["D-TEST/drawing/source"]}
    assert result["type"] == "rectangle" and result["width"]["value"] == 20
    assert template == before
    square = validate("outline", {"type": "square", "side": 12})
    assert square["type"] == "rectangle" and square["length"] == square["width"]
    assert validate("outline", {"type": "circle", "outer_diameter": 40})["outer_diameter"]["value"] == 40
    assert validate("outline", {"type": "ring", "outer_diameter": 40, "inner_diameter": 20})["type"] == "ring"


@pytest.mark.parametrize("value", [
    "rectangle", {"type": "bent"}, {"type": "rectangle", "length": 40},
    {"state": "unknown", "type": "circle", "outer_diameter": 10},
    {"type": "circle", "outer_diameter": "40"},
    {"type": "rectangle", "length": True, "width": 20},
    {"type": "ring", "outer_diameter": 40, "inner_diameter": 40},
    {"type": "circle", "outer_diameter": 40, "thickness": 4},
])
def test_malformed_outlines_are_rejected(value):
    with pytest.raises(ValueError):
        validate("outline", value)


def hole(**changes):
    return {"kind": "hole", "face": "top", "x": 0, "y": 0, "diameter": 4.5, "through": True, "hole_type": "plain", **changes}


def test_features_are_sourced_and_supported_slot_direction_is_preserved():
    result = validate("features_review", [hole(), {"kind": "slot", "face": "bottom", "x": -2, "y": 3, "length": 10, "width": 4, "direction": "horizontal", "through": False, "depth": 2}], template={"thickness": {"state": "known", "value": 4}})
    assert result[0]["x"]["value"] == 0
    assert result[0]["diameter"]["method"] == "human_decision"
    assert result[1]["direction"]["value"] == "horizontal"
    assert result[0]["fact_ids"] == ["D-TEST/drawing/source"]
    assert validate("features_review", []) == []


def test_known_kind_wrapper_is_normalized_for_builder():
    result = validate("features_review", [hole(kind={"state": "known", "value": "hole"})])
    assert result[0]["kind"] == "hole"
    with pytest.raises(ValueError):
        validate("features_review", [hole(kind={"state": "unknown", "value": "hole"})])


@pytest.mark.parametrize("feature", [
    hole(face="left"), hole(kind="pocket"), hole(x=None), hole(x="1"), hole(through="true"),
    hole(diameter=-1), hole(hole_type="unknown"), hole(through=False),
    hole(hole_type="counterbored", counterbore_diameter=3, counterbore_depth=1),
    hole(hole_type="countersunk", countersink_diameter=8, countersink_angle=180),
    hole(pattern={"type": "row", "count": 1.5, "spacing": 4, "direction": 0}),
    {"kind": "slot", "face": "top", "x": 0, "y": 0, "through": True, "length": 2, "width": 4, "direction": 0},
])
def test_bad_or_unsupported_features_are_rejected(feature):
    with pytest.raises(ValueError):
        validate("features_review", [feature])


def test_blind_and_step_depth_cannot_exceed_known_thickness():
    template = {"thickness": {"state": "known", "value": 2}}
    with pytest.raises(ValueError):
        validate("features_review", [hole(through=False, depth=3)], template=template)
    with pytest.raises(ValueError):
        validate("features_review", [hole(hole_type="counterbored", counterbore_diameter=8, counterbore_depth=3)], template=template)


def rectangular_template(thickness=4):
    return {"outline": {"state": "known", "type": "rectangle", "length": {"state": "known", "value": 40}, "width": 20},
            "thickness": {"state": "known", "value": thickness}}


@pytest.mark.parametrize("face,x,y,span", [("x_min", -20, 0, 40), ("x_max", 20, 0, 40),
                                          ("y_min", 0, -10, 20), ("y_max", 0, 10, 20)])
def test_side_holes_preserve_global_entry_and_limit_depth_by_body_span(face, x, y, span):
    template = rectangular_template()
    original = hole(face=face, x=x, y=y, z=2, through=False, depth=span)
    before = copy.deepcopy(original)
    result = validate("features_review", [original], template=template)[0]
    assert result["depth"]["value"] == span > 4
    assert result["z"] == {"state": "known", "value": 2, "method": "human_decision", "fact_ids": ["D-TEST/drawing/source"]}
    assert result["x"]["value"] == x and result["y"]["value"] == y and original == before
    with pytest.raises(ValueError, match="body span"):
        validate("features_review", [{**original, "depth": span + 1}], template=template)


@pytest.mark.parametrize("changes", [
    {"x": -19}, {"y": 10}, {"z": None}, {"z": 0}, {"z": 4}, {"z": "2"},
    {"hole_type": "counterbored"}, {"hole_type": "threaded"}, {"pattern": None}, {"kind": "slot"},
])
def test_invalid_side_holes_need_clarification(changes):
    feature = hole(face="x_min", x=-20, y=0, z=2)
    with pytest.raises(ValueError):
        validate("features_review", [{**feature, **changes}], template=rectangular_template())


def test_side_holes_require_established_body_and_every_thickness_variant():
    feature = hole(face="x_min", x=-20, y=0, z=2, hole_type="threaded", thread="M6")
    assert validate("features_review", [feature], template=rectangular_template())[0]["thread"] == "M6"
    for template in (None, {"outline": {"type": "circle", "outer_diameter": 40}, "thickness": 4},
                     {**rectangular_template(), "thickness": {"state": "unknown", "value": None}},
                     {**rectangular_template(), "thickness": {"state": "options", "options": [2, 4]}},
                     {**rectangular_template(), "thickness": {"state": "options", "options": [4, {"state": "unknown", "value": 8}]}}):
        with pytest.raises(ValueError):
            validate("features_review", [feature], template=template)


def corner_clip(**changes):
    return {"kind": "corner_chamfer", "corners": ["x_min_y_min", "x_max_y_max"],
            "x_setback": 1, "y_setback": 2, **changes}


def test_corner_clips_use_explicit_corner_subset_and_sourced_positive_setbacks():
    original = corner_clip()
    before = copy.deepcopy(original)
    feature = validate("features_review", [original], template=rectangular_template())[0]
    assert feature["corners"] == ["x_min_y_min", "x_max_y_max"]
    assert feature["x_setback"]["value"] == 1 and feature["y_setback"]["value"] == 2
    assert feature["x_setback"]["fact_ids"] == feature["fact_ids"] == ["D-TEST/drawing/source"]
    assert "face" not in feature and "through" not in feature and original == before


@pytest.mark.parametrize("changes", [
    {"corners": []}, {"corners": ["top_left"]}, {"corners": ["x_min_y_min"] * 2},
    {"x_setback": 0}, {"x_setback": 20}, {"y_setback": 10}, {"y_setback": None},
    {"x_setback": {"state": "unknown", "value": 1}}, {"face": "top"}, {"through": True},
    {"depth": 1}, {"x": 0}, {"pattern": {}},
])
def test_corner_clips_reject_missing_or_incompatible_geometry(changes):
    with pytest.raises(ValueError):
        validate("features_review", [corner_clip(**changes)], template=rectangular_template())


def test_thickness_alternatives_keep_options_state_and_input_untouched():
    value = {"state": "options", "options": [2, {"state": "known", "value": 4}], "note": "Source readings"}
    before = copy.deepcopy(value)
    assert validate("thickness", value) == value
    assert value == before
    with pytest.raises(ValueError):
        validate("thickness", {"state": "options", "options": [True]})


def isolated_store(field, target="D-TEST/template/thickness"):
    store = Store.__new__(Store)
    store.fields = {target: field}
    store.owners = {}
    store.templates = {}
    store.ai = {}
    store.changed = []
    store.revision = "fixture"
    store.review_items = lambda: [{"id": target, "target": target, "type": "template"}]
    return store, target


def test_invalid_set_value_never_reaches_append():
    store, target = isolated_store({"state": "unknown"})
    store.append = lambda *args, **kwargs: pytest.fail("Invalid input reached append")
    with pytest.raises(ValueError):
        store.act(target, "set_value", "4 mm")


def test_choose_option_is_unchanged_and_unvalidated_as_a_new_value():
    store, target = isolated_store({"state": "options", "options": [2, 4]})
    appended = []
    store.append = lambda *args, **kwargs: appended.append(args) or {"fixture": True}
    store.rebuild_models = lambda: None
    store.act(target, "choose_option", 4)
    assert appended == [(target, "choose_option", 4)]
    assert store.fields[target]["state"] == "options"


def test_delegated_confirm_does_not_relabel_prior_personal_correction():
    store, target = isolated_store({"state": "unknown", "value": None})
    store._apply({"applies_to": target, "type": "set_value", "value": 4, "status": "accepted", "by": "Jason Peng", "at": "2000-01-01T00:00:00Z"})
    correction = copy.deepcopy(store.fields[target]["correction"])
    store._apply({"applies_to": target, "type": "confirm", "status": "accepted", "by": "Automated fixture inspector", "at": "2000-01-02T00:00:00Z", "review_kind": "delegated", "delegated_by": "Jason Peng"})
    assert store.fields[target]["correction"] == correction
    assert "review_kind" not in store.fields[target]["correction"]
    assert store.fields[target]["review"]["by"] == "Automated fixture inspector"
    assert store.fields[target]["review"]["display_by"] == "Jason Peng - delegated review"
