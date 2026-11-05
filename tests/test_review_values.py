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
