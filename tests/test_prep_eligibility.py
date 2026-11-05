"""Pure eligibility routing checks: no CLI readers, provider calls or decisions."""
import copy
import json

import pytest

from backend.ai import eligibility


def fixture(supported=False, reason="Original views show essential bent flanges that a flat rectangular extrusion cannot reproduce."):
    drawing = {"id": "D-TEST", "sha256": "a" * 64}
    value = {"supported": supported, "constant_thickness": True, "outline_exact": supported,
             "reason": reason, "essential_uncertainty": [], "omitted_minor_features": []}
    bound = "b" * 64
    proposal = {"key": "cad_eligibility", "state": "known", "value_json": json.dumps(value)}
    verification = {"key": "cad_eligibility", "decision": "accept", "fact_ids": ["D-TEST/drawing/source"]}
    field = {"state": "known", "value": value, "method": "ai_verified", "readers": {
        "codex": {"role": "proposer", "protocol": "proposal-verification-v1", "rounds": [
            {"valid": True, "validation_passed": True, "proposal_fingerprint": bound,
             "settings": {"model": "gpt-6.1-sol"}, "answer": proposal}]},
        "claude": {"role": "verifier", "protocol": "proposal-verification-v1", "rounds": [
            {"valid": True, "validation_passed": True, "proposal_fingerprint": bound,
             "response_proposal_fingerprint": bound, "settings": {"model": "opus"}, "answer": verification}]}}}
    return drawing, {"source_sha256": drawing["sha256"], "cad_ready": False, "cad_eligibility": field}


def rebind(template):
    field = template["cad_eligibility"]
    field["readers"]["codex"]["rounds"][0]["answer"]["value_json"] = json.dumps(field["value"])


def test_source_unchanged_unsupported_shape_reuses_original_receipts_with_explicit_bootstrap():
    drawing, template = fixture()
    before = copy.deepcopy(template)
    result = eligibility.route(drawing, template)
    assert result["action"] == "reuse_unsupported"
    assert result["source_sha256"] == drawing["sha256"]
    assert result["capabilities_sha256"] == eligibility.CAPABILITIES_SHA256
    assert result["receipt"]["kind"] == "legacy_verified_assessment_bootstrap"
    assert result["receipt"]["fresh_verification"] is False
    assert result["assessment"] == template["cad_eligibility"] and template == before
    cached = eligibility.route(drawing, template, cached_screen=result)
    assert cached["action"] == "reuse_unsupported"
    assert cached["receipt"]["kind"] == "cached_verified_assessment_reuse"
    assert cached["assessment"]["readers"] == template["cad_eligibility"]["readers"]


def test_supported_assessments_and_primary_supported_templates_always_receive_detail():
    drawing, template = fixture(supported=True)
    assert eligibility.route(drawing, template)["action"] == "detailed_candidate"
    template.pop("cad_eligibility")
    template.update(cad_ready=True, outline={"state": "known", "type": "rectangle", "length": 20, "width": 10},
                    thickness={"state": "options", "options": [2, 3]})
    assert eligibility.route(drawing, template)["action"] == "detailed_candidate"


def test_changed_source_or_relevant_capabilities_require_new_screen():
    drawing, template = fixture()
    assert eligibility.route({**drawing, "sha256": "c" * 64}, template)["action"] == "screen_required"
    changed = {**eligibility.CAPABILITIES, "outlines": [*eligibility.CAPABILITIES["outlines"], "obround"]}
    assert eligibility.route(drawing, template, capabilities=changed)["action"] == "screen_required"
    cached = {**template, "capabilities_sha256": "d" * 64}
    assert eligibility.route(drawing, template, cached_screen=cached)["action"] == "screen_required"
    assert eligibility.route({"id": "D-TEST"}, template)["action"] == "screen_required"


@pytest.mark.parametrize("mutation", [
    {"state": "unknown"}, {"method": "ai_agreed"}, {"method": "human_decision"}, {"readers": {}},
    {"value": None},
])
def test_unknown_missing_or_unverified_assessments_do_not_skip_screen(mutation):
    drawing, template = fixture()
    template["cad_eligibility"].update(mutation)
    assert eligibility.route(drawing, template)["action"] == "screen_required"
    assert eligibility.route(drawing, None)["action"] == "screen_required"


@pytest.mark.parametrize("reason", [
    "The parsed drawing-number IDs are absent, so exact numeric geometry cannot be populated.",
    "Hole coordinates and pitch are missing; the constant rectangular base cannot be dimensioned reliably.",
    "The thickness is unknown because the printed number has no indexed source citation.",
    "The views do not establish bent flanges, and the body thickness remains unreadable.",
    "There are no rounded outer corners shown; only the hole coordinates remain unresolved.",
])
def test_unresolved_numeric_inputs_and_negated_shape_claims_never_become_unsupported_geometry(reason):
    drawing, template = fixture(reason=reason)
    template["cad_eligibility"]["value"]["constant_thickness"] = False
    rebind(template)
    assert eligibility.route(drawing, template)["action"] == "screen_required"


@pytest.mark.parametrize("reason", [
    "The main view shows essential rounded outer corners outside the supported base outlines.",
    "The main view explicitly calls out an outer-corner radius that the base outlines cannot reproduce.",
    "Section A-A establishes an essential annular O-ring groove producing a stepped profile.",
    "The main face is an obround contour, so its bounding rectangle cannot reproduce the body.",
    "The essential three-lobed outer profile exceeds the supported rectangle/circle/ring outlines.",
    "The side view establishes a stepped, revolved sleeve rather than a constant ring extrusion.",
])
def test_positive_essential_body_exclusions_allow_source_bound_reuse(reason):
    drawing, template = fixture(reason=reason)
    assert eligibility.route(drawing, template)["action"] == "reuse_unsupported"


def test_unsupported_flag_and_false_readiness_alone_are_not_a_shape_assessment():
    drawing, template = fixture()
    template["cad_eligibility"]["value"].update(outline_exact=True, constant_thickness=True)
    rebind(template)
    assert eligibility.route(drawing, template)["action"] == "screen_required"
    del template["cad_eligibility"]
    assert eligibility.route(drawing, template)["action"] == "screen_required"


def test_verification_must_bind_the_exact_original_proposal():
    drawing, template = fixture()
    template["cad_eligibility"]["readers"]["claude"]["rounds"][0]["response_proposal_fingerprint"] = "e" * 64
    assert eligibility.route(drawing, template)["action"] == "screen_required"
    drawing, template = fixture()
    template["cad_eligibility"]["value"]["reason"] = "Views show a new unsupported nonplanar body absent from the verified proposal."
    assert eligibility.route(drawing, template)["action"] == "screen_required"
