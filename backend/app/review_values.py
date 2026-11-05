"""Validate new reviewed inputs without changing historical decision replay."""
from __future__ import annotations

import copy
import json
import math
import re


SIZE = re.compile(r"(?:^|_)(thickness|length|width|diameter|radius|depth)$")
NUMBER = re.compile(r"(?:^|_)(thickness|length|width|diameter|radius|depth|offset|x|y|angle|count)$")


def _number(value, name, *, positive=False, integer=False):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name} must be a finite number, not text or a boolean")
    if positive and value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if integer and value != int(value):
        raise ValueError(f"{name} must be a whole number")
    return value


def _unwrap(value, name):
    if isinstance(value, dict):
        if value.get("state", "known") != "known" or value.get("confidence") == "unsure" or "value" not in value:
            raise ValueError(f"{name} must have a known value")
        return value["value"]
    return value


def _known(value, source):
    return {"state": "known", "value": value, "method": "human_decision", "fact_ids": [source]}


def _dimension(value, name, source, *, positive=True, integer=False):
    return _known(_number(_unwrap(value, name), name, positive=positive, integer=integer), source)


def _outline(value, source):
    if not isinstance(value, dict) or value.get("state", "known") != "known" or value.get("confidence") == "unsure":
        raise ValueError("Outer shape must be a known rectangle, square, circle or ring object")
    shape = _unwrap(value.get("type"), "Outer shape type")
    dimensions = {"rectangle": ("length", "width"), "square": ("side",), "circle": ("outer_diameter",), "ring": ("outer_diameter", "inner_diameter")}
    if not isinstance(shape, str) or shape not in dimensions:
        raise ValueError("Supported outer shapes are rectangle, square, circle and ring")
    unexpected = set(value) - {"state", "type", "method", "fact_ids", "fact_id", "confidence", "note", "name", *dimensions[shape]}
    if unexpected:
        raise ValueError("Unsupported outer-shape fields: " + ", ".join(sorted(unexpected)))
    result = {"state": "known", "type": "rectangle" if shape == "square" else shape, "method": "human_decision", "fact_ids": [source]}
    for key in dimensions[shape]:
        result[key] = _dimension(value.get(key), key, source)
    if shape == "square":
        side = result.pop("side")
        result.update(length=side, width=copy.deepcopy(side))
    if shape == "ring" and result["inner_diameter"]["value"] >= result["outer_diameter"]["value"]:
        raise ValueError("Inner diameter must be smaller than outer diameter")
    return result


def _angle(value, name, source):
    raw = _unwrap(value, name)
    if isinstance(raw, str) and raw.lower() in {"x", "horizontal", "y", "vertical"}:
        return _known(raw.lower(), source)
    return _dimension(value, name, source, positive=False)


def _thickness_limits(template):
    field = (template or {}).get("thickness") or {}
    values = field.get("options", []) if isinstance(field, dict) and field.get("state") == "options" else [field]
    limits = []
    for value in values:
        try:
            limits.append(_number(_unwrap(value, "Thickness"), "Thickness", positive=True))
        except ValueError:
            continue
    return limits


def _features(value, source, template):
    if not isinstance(value, list):
        raise ValueError("Reviewed holes and slots must be a JSON array")
    result = []
    thicknesses = _thickness_limits(template)
    for index, original in enumerate(value):
        name = f"Feature {index + 1}"
        if not isinstance(original, dict):
            raise ValueError(f"{name} must be an object")
        feature = copy.deepcopy(original)
        if feature.get("state", "known") != "known" or feature.get("confidence") == "unsure":
            raise ValueError(f"{name} must be known; retain unresolved features in omissions")
        kind = feature.get("kind")
        if kind not in ("hole", "slot"):
            raise ValueError(f"{name}: supported kinds are hole and slot")
        face = _unwrap(feature.get("face"), f"{name} face")
        if face not in ("top", "bottom"):
            raise ValueError(f"{name}: supported faces are top and bottom")
        feature["face"] = face
        through = _unwrap(feature.get("through"), f"{name} through")
        if type(through) is not bool:
            raise ValueError(f"{name} through must be true or false")
        feature["through"] = through
        for key in ("x", "y"):
            feature[key] = _dimension(feature.get(key), f"{name} {key} (source position)", source, positive=False)
        depth = None
        if not through or "depth" in feature:
            feature["depth"] = _dimension(feature.get("depth"), f"{name} depth", source)
            depth = feature["depth"]["value"]
            if not through and thicknesses and any(depth > thickness + 1e-6 for thickness in thicknesses):
                raise ValueError(f"{name} depth exceeds a supported plate thickness")
        if kind == "slot":
            if feature.get("allow_primary_hole_without_unresolved_step"):
                raise ValueError(f"{name} primary-hole fallback only applies to holes")
            for key in ("length", "width"):
                feature[key] = _dimension(feature.get(key), f"{name} {key}", source)
            if feature["length"]["value"] < feature["width"]["value"]:
                raise ValueError(f"{name} slot length must be at least its width")
            feature["direction"] = _angle(feature.get("direction", feature.get("angle")), f"{name} direction", source)
            feature.pop("angle", None)
        else:
            feature["diameter"] = _dimension(feature.get("diameter"), f"{name} diameter", source)
            hole_type = _unwrap(feature.get("hole_type"), f"{name} hole_type")
            if hole_type not in ("plain", "threaded", "counterbored", "countersunk"):
                raise ValueError(f"{name} hole_type must be plain, threaded, counterbored or countersunk")
            feature["hole_type"] = hole_type
            fallback = feature.get("allow_primary_hole_without_unresolved_step", False)
            if type(fallback) is not bool:
                raise ValueError(f"{name} primary-hole fallback must be boolean")
            if fallback and (not through or hole_type not in ("counterbored", "countersunk") or not isinstance(feature.get("step_conflict_reason"), str) or not feature["step_conflict_reason"].strip()):
                raise ValueError(f"{name} primary-hole fallback needs a through stepped hole and a sourced conflict reason")
            if hole_type in ("counterbored", "countersunk"):
                prefix = "counterbore" if hole_type == "counterbored" else "countersink"
                diameter_key = prefix + "_diameter"
                feature[diameter_key] = _dimension(feature.get(diameter_key), f"{name} {diameter_key}", source)
                if feature[diameter_key]["value"] <= feature["diameter"]["value"]:
                    raise ValueError(f"{name} stepped diameter must exceed the primary diameter")
                if hole_type == "counterbored":
                    feature["counterbore_depth"] = _dimension(feature.get("counterbore_depth"), f"{name} counterbore_depth", source)
                    step_depth = feature["counterbore_depth"]["value"]
                else:
                    feature["countersink_angle"] = _dimension(feature.get("countersink_angle"), f"{name} countersink_angle", source)
                    angle = feature["countersink_angle"]["value"]
                    if angle >= 180:
                        raise ValueError(f"{name} countersink angle must be below 180 degrees")
                    step_depth = (feature[diameter_key]["value"] - feature["diameter"]["value"]) / 2 / math.tan(math.radians(angle / 2))
                available = thicknesses if through else ([depth] if depth is not None else [])
                if not fallback and any(step_depth > limit for limit in available):
                    raise ValueError(f"{name} step exceeds the available cut depth")
        pattern = feature.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, dict) or pattern.get("type") not in ("row", "circle"):
                raise ValueError(f"{name} pattern must be row or circle")
            pattern["count"] = _dimension(pattern.get("count"), f"{name} pattern count", source, integer=True)
            if pattern["count"]["value"] > 1000:
                raise ValueError(f"{name} pattern count cannot exceed 1000")
            if pattern["type"] == "row":
                pattern["spacing"] = _dimension(pattern.get("spacing"), f"{name} pattern spacing", source)
                pattern["direction"] = _angle(pattern.get("direction"), f"{name} pattern direction", source)
            else:
                pattern["radius"] = _dimension(pattern.get("radius"), f"{name} pattern radius", source)
                pattern["start_angle"] = _dimension(pattern.get("start_angle"), f"{name} pattern start_angle", source, positive=False)
        feature.update(state="known", method="human_decision", fact_ids=[source])
        result.append(feature)
    return result


def validate_review_value(target, value, current_field, template=None):
    """Return a safe typed set_value payload; never called when replaying history."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Reviewed values must contain finite JSON values") from None
    tail = target.rsplit("/", 1)[-1]
    source = target.split("/", 1)[0] + "/drawing/source"
    current = current_field.get("value")
    if target.endswith("/template/outline"):
        return _outline(value, source)
    if tail == "features_review":
        return _features(value, source, template)
    # Legacy API clients can still submit reviewed thickness alternatives.
    if tail == "thickness" and isinstance(value, dict) and value.get("state") == "options":
        choices = value.get("options")
        if not isinstance(choices, list) or not choices or len(choices) > 4:
            raise ValueError("Thickness options must contain one to four positive numbers")
        result = copy.deepcopy(value)
        for choice in choices:
            _number(_unwrap(choice, "Thickness option"), "Thickness option", positive=True)
        return result
    if type(current) is bool or tail == "features_complete":
        if type(value) is not bool:
            raise ValueError("Choose true or false")
    elif type(current) in (int, float) or NUMBER.search(tail):
        _number(value, tail, positive=bool(SIZE.search(tail)) or tail.endswith("count"), integer=tail.endswith("count"))
    elif isinstance(current, list):
        if not isinstance(value, list):
            raise ValueError("Enter a JSON array")
    elif isinstance(current, dict):
        if not isinstance(value, dict):
            raise ValueError("Enter a JSON object")
    elif not isinstance(value, str) or not value.strip():
        raise ValueError("Enter non-empty plain text")
    return copy.deepcopy(value)
