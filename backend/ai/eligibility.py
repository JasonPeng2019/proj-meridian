"""Pure routing gate before paid image transcription and detailed CAD prep.

Reusing an unsupported base-body assessment does not approve a drawing, convert
legacy receipts into fresh verification, or decide unresolved numeric geometry.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

PROTOCOL = "base-body-eligibility-routing-v1"
CAPABILITIES = {
    "contract": "mvp-flat-base-body-v1",
    "outlines": ["rectangle", "circle", "ring"],
    "body": "single planar constant-thickness extrusion; explicitly printed thickness alternatives allowed",
    "exact_main_outline": True,
    "bounding_shape_substitution": False,
    "unsupported_essential_geometry": ["bends", "nonplanar or assembled bodies", "stepped or revolved bodies",
                                       "custom rounded, lobed, obround or angled outer contours", "essential grooves"],
    "minor_cut_changes_do_not_expand_base_body_contract": True,
    "minor_detail_allowance": "Small undimensioned straight corner clips and edge breaks may be explicitly omitted from an otherwise established rectangular main body; never discard essential functional contours.",
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


CAPABILITIES_SHA256 = fingerprint(CAPABILITIES)
VERIFICATION_PROTOCOL = "proposal-verification-v1"
VERIFIED_METHODS = {"ai_verified", "ai_verified_after_retry"}
SHA = re.compile(r"[0-9a-f]{64}")
STRUCTURAL_PATTERNS = (
    r"\bbent\b.{0,35}\b(?:flanges?|walls?|bracket|sheets?|part|body|tabs?)\b",
    r"\bnon[- ]?planar\b.{0,45}\b(?:body|bodies|bracket|part|plate|assembly|outlet)\b",
    r"\b(?:stepped|revolved)(?:[/, -]+(?:stepped|revolved))?\b.{0,35}\b(?:body|profile|section|shaft|sleeve|seat)\b",
    r"\brounded\b.{0,30}\bouter\b.{0,15}\b(?:corners?|contour|profile)\b",
    r"\bouter[- ]corner\s+radii?\w*\b",
    r"\b(?:three[- ]lobed|lobed|obround)\b",
    r"\bl[- ]shaped\s+(?:profile|outline|body)\b",
    r"\bhollow\s+(?:canister|enclosure)\b",
    r"\b(?:curved|angled|notched|sloping)\b.{0,25}\bouter\s+(?:contour|profile|outline)\b",
    r"\b(?:welded|formed)\b.{0,35}\bassembly\b",
    r"\bessential\b.{0,35}\b(?:o[- ]ring|annular)\s+groove\b",
)


def _structural_basis(reason: str) -> list[str]:
    """Conservatively recognize positive body/contour exclusions, not missing data.

    A nonmatching explanation goes to a new qualitative screen. The gate never
    interprets drawing pixels or upgrades a numeric uncertainty to an exclusion.
    """
    matches = []
    for sentence in re.split(r"[.;\n]", reason.lower()):
        for pattern in STRUCTURAL_PATTERNS:
            for match in re.finditer(pattern, sentence):
                before = sentence[max(0, match.start() - 65):match.start()]
                if re.search(r"\b(?:no|not|without|absent|unknown|uncertain|unresolved|cannot determine)\b[^,;]*$", before):
                    continue
                matches.append(match.group())
    return sorted(set(matches))


def _verified(field: dict, did: str) -> bool:
    if (not isinstance(field, dict) or field.get("state") != "known" or
            field.get("method") not in VERIFIED_METHODS or not isinstance(field.get("value"), dict)):
        return False
    readers = field.get("readers") or {}
    proposer, verifier = readers.get("codex", {}), readers.get("claude", {})
    if (proposer.get("role") != "proposer" or verifier.get("role") != "verifier" or
            proposer.get("protocol") != VERIFICATION_PROTOCOL or verifier.get("protocol") != VERIFICATION_PROTOCOL):
        return False
    for check in reversed(verifier.get("rounds", [])):
        answer = check.get("answer") or {}
        bound = check.get("proposal_fingerprint")
        if (check.get("valid") is not True or check.get("validation_passed") is not True or
                not isinstance(bound, str) or not SHA.fullmatch(bound) or
                check.get("response_proposal_fingerprint") != bound or
                answer.get("key") != "cad_eligibility" or answer.get("decision") != "accept" or
                check.get("settings", {}).get("model") != "opus" or
                not any(ref == did or ref.startswith(did + "/drawing/") for ref in answer.get("fact_ids", []) if isinstance(ref, str))):
            continue
        for proposal in reversed(proposer.get("rounds", [])):
            proposed = proposal.get("answer") or {}
            if (proposal.get("valid") is not True or proposal.get("validation_passed") is not True or
                    proposal.get("proposal_fingerprint") != bound or proposed.get("key") != "cad_eligibility" or
                    proposed.get("state") != "known" or proposal.get("settings", {}).get("model") != "gpt-6.1-sol"):
                continue
            try:
                if json.loads(proposed["value_json"]) == field["value"]:
                    return True
            except (KeyError, TypeError, ValueError):
                continue
    return False


def _positive(value) -> bool:
    if isinstance(value, dict):
        if value.get("state", "known") != "known" or value.get("confidence") == "unsure":
            return False
        value = value.get("value")
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _supported_template(template: dict) -> bool:
    """Legacy primary templates can be detail candidates without an eligibility field."""
    if template.get("cad_ready") is not True:
        return False
    outline = template.get("outline") or {}
    if outline.get("state", "known") != "known":
        return False
    keys = {"rectangle": ("length", "width"), "circle": ("outer_diameter",), "ring": ("outer_diameter", "inner_diameter")}.get(outline.get("type"))
    if not keys or not all(_positive(outline.get(key)) for key in keys):
        return False
    thickness = template.get("thickness")
    return (isinstance(thickness, dict) and thickness.get("state") == "options" and
            bool(thickness.get("options")) and all(_positive(value) for value in thickness["options"])) or _positive(thickness)


def route(drawing: dict, template: dict | None, cached_screen: dict | None = None,
          capabilities: dict = CAPABILITIES) -> dict:
    """Return detailed_candidate/reuse_unsupported/screen_required without I/O.

    A cached screen contains source_sha256, capabilities_sha256 and either
    cad_eligibility or assessment (the original resolved field with readers).
    Legacy templates may omit capabilities_sha256 only under this exact default
    base-body contract; their unchanged verification is explicitly bootstrapped.
    """
    sha = drawing.get("sha256")
    capabilities_sha = fingerprint(capabilities)
    decision = {"protocol": PROTOCOL, "drawing": drawing.get("id"), "source_sha256": sha,
                "capabilities_sha256": capabilities_sha}

    def emit(action, reason, **extra):
        return {**decision, "action": action, "reason": reason, **copy.deepcopy(extra)}

    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        return emit("screen_required", "Original PDF SHA-256 is missing or invalid.")
    prior = cached_screen if cached_screen is not None else (template or {})
    if prior.get("source_sha256") != sha:
        return emit("screen_required", "No prior assessment is bound to this exact original PDF SHA-256.")
    bound_capabilities = prior.get("capabilities_sha256")
    legacy = bound_capabilities is None
    if (not legacy and bound_capabilities != capabilities_sha) or (legacy and capabilities_sha != CAPABILITIES_SHA256):
        return emit("screen_required", "Base-body capability contract changed or lacks a compatible legacy binding.")
    field = prior.get("cad_eligibility") or prior.get("assessment")
    if isinstance(field, dict) and _verified(field, drawing["id"]):
        assessment = field["value"]
        reason = assessment.get("reason")
        if assessment.get("supported") is True:
            return emit("detailed_candidate", "Verified supported-base candidate requires detailed feature preparation.", assessment=field)
        if (assessment.get("supported") is False and
                (assessment.get("outline_exact") is False or assessment.get("constant_thickness") is False) and
                isinstance(reason, str) and len(reason.strip()) >= 30):
            structural = _structural_basis(reason)
            if structural:
                return emit("reuse_unsupported", reason, assessment=field,
                            receipt={"kind": "legacy_verified_assessment_bootstrap" if legacy else "cached_verified_assessment_reuse",
                                     "fresh_verification": False, "source_sha256": sha,
                                     "capabilities_sha256": capabilities_sha,
                                     "original_method": field["method"], "structural_basis": structural,
                                     "assessment_sha256": fingerprint(field),
                                     "original_receipts_sha256": fingerprint(field["readers"])})
        return emit("screen_required", "Prior assessment does not establish an essential unsupported base body independently of unresolved dimensions.", assessment=field)
    if cached_screen is None and field is None and _supported_template(prior):
        return emit("detailed_candidate", "Source-unchanged supported flat template requires detailed feature preparation.",
                    receipt={"kind": "existing_supported_template", "fresh_verification": False})
    return emit("screen_required", "Missing, unknown or unverified source-bound base-body assessment.")
