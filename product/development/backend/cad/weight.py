"""Sourced mass checks over existing model volumes; no CAD or prep execution.

All outputs are engineering Debug data. Callers retain the model independently
and may add ``weight_review_item`` to Debug/Review. Nothing here approves a
material, a reconstruction, or a drawing weight. A mass match cannot validate
feature positions. The units at this boundary are mm³ and normalized grams.

``WeightCheck.examples`` retains every computable example/candidate trial,
including failures before a BOM fallback. Its frozen row contract cannot express
a missing density/weight/volume: those omissions are explicitly in ``message``.
Skipped checks have no calculated comparison rows. No missing input becomes 0.

The integration caller supplies effective EvidenceFields and current source
hashes (including their field names). Parsed sure values are usable without
claiming review; current source-bound single-model values remain UNVERIFIED.
Mappings require actual current human confirmation, including SAME aliases.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
import json
import math
from pathlib import Path
import unicodedata
from urllib.parse import urlsplit

from backend import contracts as c

__all__ = ["load_densities", "check_weight", "weight_review_item"]

_DENSITIES = Path(__file__).with_name("densities.json")
_AI_METHODS = {c.Method.AI_VERIFIED, c.Method.AI_VERIFIED_AFTER_RETRY, c.Method.AI_SINGLE_MODEL}
_PARSED_METHODS = {c.Method.PARSED, c.Method.CLEANUP_RULE, c.Method.EXACT_MATCH}


def _key(value: str) -> str:
    # Lexical whitespace/case only; alloy/family equivalences need approval.
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _positive(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _density_index(references: Sequence[c.DensityReference]) -> dict[str, c.DensityReference]:
    result = {}
    for reference in references:
        reference = c.DensityReference.model_validate(reference.model_dump(mode="json"))
        url = urlsplit(reference.source_url)
        if (not _positive(reference.density_g_cm3) or not _key(reference.material)
                or url.scheme not in {"http", "https"} or not url.netloc
                or reference.family_mapping is not None):
            raise ValueError("Density entries need a finite positive sourced scalar, without preapproved mappings")
        key = _key(reference.material)
        if key in result:
            raise ValueError(f"Duplicate density material: {reference.material}")
        result[key] = reference
    return result


def load_densities(path: Path | None = None) -> list[c.DensityReference]:
    """Load shipped source/date-stamped references, never fetch on app launch.

    The JSON also documents unavailable broad materials and the precise basis
    of each reference. Malformed/missing artifacts raise; never use defaults.
    A custom path is an explicit integration/test input, not a lookup service.
    """
    data = json.loads((Path(path) if path is not None else _DENSITIES).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "meridian-densities/v1":
        raise ValueError("Unsupported density artifact")
    references = data.get("references")
    if not isinstance(references, list) or not references:
        raise ValueError("Density artifact needs a nonempty reference list")
    return list(_density_index([c.DensityReference.model_validate(row) for row in references]).values())


def _current_review(review: c.ReviewState | None, hashes: Mapping[str, str]) -> bool:
    return bool(review and review.status == c.ReviewStatus.HUMAN_CONFIRMED
                and review.by and review.at and review.based_on
                and all(hashes.get(name) == digest for name, digest in review.based_on.items()))


def _usable(field: c.EvidenceField | None, hashes: Mapping[str, str]) -> bool:
    if field is None or not hashes.get(field.name):
        return False
    if field.correction is not None:
        correction, review = field.correction, field.review
        return bool(_current_review(review, hashes) and review.decision_id == correction.decision_id
                    and review.by == correction.by and review.at == correction.at)
    if field.confidence != c.Confidence.SURE:
        return False
    if isinstance(field, c.DrawingField) and field.source_quality == c.SourceQuality.MISSING:
        return False
    if field.review:
        if field.review.status in {c.ReviewStatus.HUMAN_REJECTED, c.ReviewStatus.SOURCE_CHANGED}:
            return False
        if field.review.status == c.ReviewStatus.HUMAN_CONFIRMED and not _current_review(field.review, hashes):
            return False
    if field.method == c.Method.HUMAN_DECISION:
        return _current_review(field.review, hashes)
    if field.method in _AI_METHODS:
        provenance = field.provenance
        if not provenance or not all(hashes.get(k) == v for k, v in provenance.source.inputs.items()):
            return False
        result = provenance.field_results.get(field.name)
        expected = {c.Method.AI_VERIFIED: "first_pass_verified",
                    c.Method.AI_VERIFIED_AFTER_RETRY: "retry_verified",
                    c.Method.AI_SINGLE_MODEL: "unverified_fallback"}[field.method]
        return bool(result and result.status == expected and result.accepted
                    and result.accepted.value == field.value
                    and result.accepted.state in {"known", "value"})
    return field.method in _PARSED_METHODS


def _value(field: c.EvidenceField):
    return field.correction.corrected if field.correction is not None else field.value


def _single_model(field: c.EvidenceField) -> bool:
    return field.correction is None and field.method == c.Method.AI_SINGLE_MODEL


def _material_names(field: c.EvidenceField | None, hashes: Mapping[str, str], *, drawing: bool) -> list[str]:
    if not _usable(field, hashes):
        return []
    value = _value(field)
    if isinstance(value, str):
        # BOM loader already splits cells. Never infer meaning of raw prose.
        return [value.strip()] if _key(value) else []
    if not drawing and isinstance(value, list) and all(isinstance(v, str) and _key(v) for v in value):
        return list(dict.fromkeys(v.strip() for v in value))
    return []


def _resolve_density(material: str, references: Mapping[str, c.DensityReference],
                     mappings: Sequence[c.NameMapping], hashes: Mapping[str, str]) -> tuple[c.DensityReference | None, str | None]:
    direct = references.get(_key(material))
    if direct:
        return direct, None
    approved = [mapping for mapping in mappings
                if mapping.kind == "material" and _current_review(mapping.review, hashes)]
    different = {frozenset((_key(mapping.from_name), _key(mapping.to_name)))
                 for mapping in approved if mapping.relationship == c.MappingRelationship.DIFFERENT and mapping.to_name}
    no_equivalent = {_key(mapping.from_name) for mapping in approved
                     if mapping.relationship == c.MappingRelationship.NO_EQUIVALENT}
    edges: dict[str, list[tuple[str, c.NameMapping]]] = {}
    for mapping in approved:
        if (not mapping.to_name
                or mapping.relationship not in {c.MappingRelationship.SAME, c.MappingRelationship.KIND_OF}):
            continue
        start, end = _key(mapping.from_name), _key(mapping.to_name)
        if frozenset((start, end)) in different:
            continue
        edges.setdefault(start, []).append((end, mapping))
        if mapping.relationship == c.MappingRelationship.SAME:
            edges.setdefault(end, []).append((start, mapping))

    # All reachable sourced choices must agree on the reference material.
    # Ambiguous approvals never select the density that happens to match mass.
    found: dict[str, tuple[c.DensityReference, list[c.NameMapping]]] = {}
    queue = [(_key(material), [])]
    visited = set()
    for name, path in queue:
        if name in visited:
            continue
        visited.add(name)
        if name in references:
            if frozenset((_key(material), name)) not in different:
                found[name] = (references[name], path)
            continue
        if name not in no_equivalent:
            queue.extend((end, [*path, mapping]) for end, mapping in edges.get(name, []) if end not in visited)
    if len(found) > 1:
        return None, f"Ambiguous approved density mappings for {material}; no density selected."
    if not found:
        return None, f"No sourced density for {material}; no current approved mapping to a sourced reference."
    reference, path = next(iter(found.values()))
    names = " -> ".join(mapping.name for mapping in path)
    family = any(mapping.relationship == c.MappingRelationship.KIND_OF for mapping in path)
    label = "Approved family-density fallback" if family else "Approved equivalent-name density mapping"
    note = f"{label}: {material} -> {reference.material} ({names})."
    return reference.model_copy(update={"family_mapping": names}), note


def check_weight(*, examples: Sequence[c.ModelExample], drawing_weight: c.EvidenceField | None,
                 drawing_material: c.EvidenceField | None = None,
                 bom_materials: Sequence[c.EvidenceField] = (), mappings: Sequence[c.NameMapping] = (),
                 current_source_hashes: Mapping[str, str], densities: Sequence[c.DensityReference] | None = None,
                 tolerance_percent: float = 5.0) -> c.WeightCheck:
    """Compare every available example against trusted drawing/BOM candidates.

    A drawing candidate always precedes BOM alternatives. Without a usable
    drawing material, BOM alternatives form the primary candidate set (each
    recorded material is tried). Flagged requires an actual computed drawing
    mismatch before a BOM match. An uncheckable drawing material cannot become
    a silent BOM pass. Candidate order and all calculable trials are retained.
    Inputs are read only; reviews/approvals are never copied onto a new check.
    """
    if (not isinstance(tolerance_percent, (int, float)) or isinstance(tolerance_percent, bool)
            or not math.isfinite(tolerance_percent) or tolerance_percent < 0):
        raise ValueError("Weight tolerance must be finite and nonnegative")
    ids = [example.id for example in examples]
    if len(set(ids)) != len(ids):
        raise ValueError("Model example IDs must be unique")
    if not _usable(drawing_weight, current_source_hashes) or not _positive(_value(drawing_weight)):
        return c.WeightCheck(state="Skipped", tolerance_percent=tolerance_percent,
            message="Weight check skipped: no usable sure positive printed weight in normalized grams; "
                    "missing, unsure, invalid or source-changed weight is not compared.")

    recorded = Decimal(str(_value(drawing_weight)))
    references = _density_index(load_densities() if densities is None else densities)
    notes = [f"Drawing records {recorded} g."]
    if _single_model(drawing_weight):
        notes.append(f"Printed weight: {c.SINGLE_MODEL_LABEL}")
    drawing_names = _material_names(drawing_material, current_source_hashes, drawing=True)
    candidates = [("drawing", name, drawing_material) for name in drawing_names]
    seen = set()
    for field in bom_materials:
        for name in _material_names(field, current_source_hashes, drawing=False):
            if _key(name) not in seen:
                candidates.append(("bom", name, field))
                seen.add(_key(name))

    for field in [drawing_material, *bom_materials]:
        if field is not None and not _material_names(field, current_source_hashes, drawing=field is drawing_material):
            notes.append(f"Material {field.name} is missing, unsure, unresolved, source-changed or not a usable material candidate.")
    valid_examples = []
    for example in examples:
        if _positive(example.volume_mm3):
            valid_examples.append(example)
        else:
            notes.append(f"Example {example.id}: calculated mass unavailable; missing/invalid positive model volume; "
                         f"drawing records {recorded} g.")
    if not examples:
        notes.append("No model examples/volumes supplied; calculated mass unavailable.")
    if not candidates:
        notes.extend(f"Example {example.id}: calculated mass unavailable; no trusted material basis."
                     for example in examples)

    rows = []
    drawing_computable = False
    drawing_matches = False
    bom_matches = False
    matching_basis = []
    for source, material, field in candidates:
        reference, disclosure = _resolve_density(material, references, mappings, current_source_hashes)
        if disclosure:
            notes.append(disclosure)
        if reference is None:
            for example in examples:
                notes.append(f"Example {example.id}: calculated mass unavailable using {source} material {material}; "
                             f"drawing records {recorded} g; density unavailable.")
            continue
        if _single_model(field):
            notes.append(f"{source} material {material}: {c.SINGLE_MODEL_LABEL}")
        for example in valid_examples:
            mass = Decimal(str(example.volume_mm3)) * Decimal(str(reference.density_g_cm3)) / Decimal(1000)
            difference = abs(mass - recorded) / recorded * Decimal(100)
            calculated_g, difference_percent = float(mass), float(difference)
            if not math.isfinite(calculated_g) or not math.isfinite(difference_percent):
                notes.append(f"Example {example.id}: calculated mass unavailable using {source} material {material}; numeric overflow.")
                continue
            matches = difference <= Decimal(str(tolerance_percent))
            rows.append(c.ExampleWeight(example=example.id, material_source=source, material=material,
                density=reference.model_copy(deep=True), calculated_g=calculated_g, drawing_g=float(recorded),
                difference_percent=difference_percent, matches=matches))
            if source == "drawing":
                drawing_computable = True
                drawing_matches |= matches
            else:
                bom_matches |= matches
            if matches:
                matching_basis.append(f"{source} material {material}, example {example.id}")

    if drawing_matches or (not drawing_names and bom_matches):
        state = "Passed"
        message = "Weight check passed using " + "; ".join(matching_basis) + "."
    elif drawing_computable and bom_matches:
        state = "Flagged"
        message = ("Weight only matches using the parts list's material: " + "; ".join(matching_basis)
                   + ". The drawing's material or the model's size may be wrong; review required.")
    else:
        state = "FAILED"
        if not candidates:
            message = "Weight check FAILED: no trusted material candidates; calculated mass unavailable; review required."
        elif drawing_names and not drawing_computable and bom_matches:
            message = ("Weight check FAILED: BOM match found, but the trusted drawing material cannot be checked; "
                       "a drawing mismatch has not been established; review required.")
        else:
            message = "Weight check FAILED: no defensible match established with the candidate materials; review required."
    notes.append("Density data: outside source, not the dataset. A mass match does not verify feature positions. "
                 "Weight results never hide model geometry.")
    return c.WeightCheck(state=state, message=" ".join([message, *dict.fromkeys(notes)]),
                         examples=rows, tolerance_percent=tolerance_percent)


def weight_review_item(*, part_id: str, check: c.WeightCheck, source_hashes: Mapping[str, str],
                       sources: Sequence[c.FactSource] = (), at: datetime) -> c.ReviewItem | None:
    """Produce a pending Debug review item for an actual FAILED/Flagged check.

    ``at`` is the caller's actual evaluation time, not a fabricated event time.
    The integrator supplies source/model/template/material/mapping hashes for
    the evaluated inputs. A digest of the full check additionally binds its
    density source, lookup date, every mass trial, and rule/tolerance outcome.
    M16 owns action handling and approval-note enforcement; this writes nothing.
    """
    if check.state not in {"FAILED", "Flagged"}:
        return None
    if not part_id.strip() or not source_hashes:
        raise ValueError("Weight review needs its actual part and current input source hashes")
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Weight review evaluation time must include timezone")
    if check.review is not None or check.approval_note is not None:
        raise ValueError("Evaluate a fresh weight check; the checker cannot invent or migrate approvals")
    name = f"{part_id}/weight-check"
    hashes = dict(source_hashes)
    result_key = f"{name}/result"
    digest = c.contract_digest(check)
    if result_key in hashes and hashes[result_key] != digest:
        raise ValueError("Existing weight result hash does not bind this exact check")
    hashes[result_key] = digest
    return c.ReviewItem(id=name, kind="weight", applies_to=name, part_id=part_id,
        status="pending", title=f"{check.state} weight check", message=check.message,
        current_value=check.model_dump(mode="json"), source_hashes=hashes,
        sources=[source.model_copy(deep=True) for source in sources], allowed_actions=[c.ReviewAction.CONFIRM],
        created_at=at, updated_at=at, approval_note_required=check.state == "FAILED",
        weight_check=check.model_copy(deep=True))
