"""Remote-only M25 checks; all part masses/volumes/approvals below are synthetic.

No actual drawing/model is evaluated here and no source truth is established by
the controlled arithmetic cases. The density artifact is checked separately.
Run ONLY in ROOT's qualification queue, from testing/:

  ../development/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
    --basetemp=tmp/M25-pytest --junitxml=reports/ci/M25-weight.xml tests/test_weight.py

No CAD, PDF, browser, external CLI, model or network is needed by these tests.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.cad import weight  # noqa: E402

NOTE = "Invented M25 test only; not a real material determination, model mass or human approval."
AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
HUMAN = "Synthetic M25 reviewer (automated test only)"
WEIGHT = "D-901/drawing/weight"
MATERIAL = "D-901/drawing/material"
BOM = "BOM:synthetic-cell/synthetic-part/material"
HASHES = {WEIGHT: "1" * 64, MATERIAL: "1" * 64, BOM: "2" * 64, "synthetic-mapping-source": "3" * 64}


def field(name, value, **updates):
    return c.EvidenceField(name=name, original=str(value) if value is not None else None,
                           value=value, method="parsed", note=NOTE, **updates)


def example(identity="A", volume=1000):
    return c.ModelExample(id=identity, glb=f"SYNTHETIC/{identity}.glb", volume_mm3=volume)


def reference(material="Synthetic A", density=4):
    return c.DensityReference(material=material, density_g_cm3=density,
        source_url="https://example.invalid/M25-synthetic-only", retrieved_at=AT)


def check(*, mass=4, drawing="Synthetic A", bom=(), examples=None, references=None,
          drawing_field=None, **updates):
    options = dict(examples=[example()] if examples is None else examples,
        drawing_weight=field(WEIGHT, mass),
        drawing_material=drawing_field if drawing_field is not None else field(MATERIAL, drawing),
        bom_materials=[field(BOM, list(bom))] if bom else [], current_source_hashes=HASHES,
        densities=[reference(), reference("Synthetic B", 8)] if references is None else references)
    options.update(updates)
    return weight.check_weight(**options)


def review(**updates):
    values = dict(status="human_confirmed", by=HUMAN, at=AT, decision_id="synthetic-decision",
                  based_on={"synthetic-mapping-source": HASHES["synthetic-mapping-source"]})
    values.update(updates)
    return c.ReviewState(**values)


def mapping(source="Synthetic alloy", target="Synthetic A", relation="kind_of", **updates):
    values = dict(fixture=True, synthetic=True, fixture_note=NOTE,
        name=c.mapping_name("material", source, target), kind="material", from_name=source,
        to_name=target, relationship=relation, evidence="general_engineering_knowledge",
        evidence_note=NOTE, method="parsed", review=review())
    values.update(updates)
    return c.NameMapping(**values)


def ai_field(name, value, *, fallback=False, verdict="verified"):
    """Actual contract-valid in-memory fake prep receipts; NO CLI is launched."""
    source = c.PrepSourceIdentity(inputs={name: HASHES[name]}, source_ids={name: name})
    candidate_fields = {name: c.DeterminedField(state="known", value=value, confidence="sure",
        source_ids=[name], reason=NOTE, schema_valid=True, evidence_valid=True)}
    candidate = dict(source_sha256=c.contract_digest(source),
                     fields={key: v.model_dump(mode="json") for key, v in candidate_fields.items()})
    candidate["candidate_sha256"] = c.contract_digest(candidate)
    candidate = c.DeterminationOutput.model_validate(candidate)
    mode = "single_model_unverified" if fallback else "determine_verify"
    pins = {
        "determination": c.ReaderSettings(provider="codex_cli", model="gpt-6.1-sol", reasoning="max", service_tier="fast"),
        "verification": c.ReaderSettings(provider="claude_code", model="claude-opus-5-5", reasoning="xhigh", service_tier="regular"),
    }

    def cache(role):
        return c.PrepCacheIdentity(role=role, source_sha256=c.contract_digest(source),
            field_names_sha256=c.contract_digest([name]),
            candidate_sha256=candidate.candidate_sha256 if role == "verification" else None,
            feedback_sha256=None, prompt_sha256="4" * 64, output_contract_sha256="5" * 64,
            settings=pins[role], settings_basis="requested", effective_sha256=None, mode=mode)

    sol = c.DeterminationAttempt(requested=pins["determination"], effective=None, status="success",
        output=candidate, started_at=AT, finished_at=AT, cache=cache("determination"))
    output = dict(candidate_sha256=candidate.candidate_sha256, source_sha256=candidate.source_sha256,
        fields={name: dict(verdict=verdict, reason=NOTE, source_ids=[name])})
    output["verification_sha256"] = c.contract_digest(output)
    failure = c.ReaderFailure(classification="provider_error", execution_failure=True, message=NOTE,
                             troubleshooting=["Synthetic execution failure; no real provider was invoked."])
    opus = c.VerificationAttempt(requested=pins["verification"], effective=None,
        status="execution_failed" if fallback else "success", output=None if fallback else output,
        failure=failure if fallback else None, started_at=AT, finished_at=AT,
        cache=cache("verification"), candidate_sha256=candidate.candidate_sha256,
        source_sha256=candidate.source_sha256)
    outcome = "unverified_fallback" if fallback else "first_pass_verified" if verdict == "verified" else "unresolved"
    provenance = c.PrepProvenance(job="synthetic-m25", job_id="synthetic-m25", source=source,
        field_names=[name], mode=mode, outcome=outcome,
        determination_prompt_sha256="4" * 64, verification_prompt_sha256="4" * 64,
        output_contract_sha256="5" * 64,
        rounds=[c.PrepRound(round=1, determination=sol, verification=opus)])
    method = "ai_single_model" if fallback else "ai_verified" if verdict == "verified" else "unresolved"
    return c.EvidenceField(name=name, original=None, value=value if method != "unresolved" else None,
        method=method, confidence="sure" if method != "unresolved" else "unsure", provenance=provenance, note=NOTE)


def test_every_example_retains_mass_and_basis_and_any_primary_match_passes_without_selecting_geometry():
    examples = [example("A", 2000), example("B", 1000)]
    before = [e.model_dump(mode="json") for e in examples]
    result = check(examples=examples)
    assert result.state == "Passed"
    assert [(r.example, r.calculated_g, r.drawing_g, r.matches) for r in result.examples] == [
        ("A", 8, 4, False), ("B", 4, 4, True)]
    assert all(r.material_source == "drawing" and r.material == "Synthetic A" for r in result.examples)
    assert all(r.density.outside_dataset and r.density.retrieved_at == AT for r in result.examples)
    assert [e.model_dump(mode="json") for e in examples] == before
    assert result.review is None and result.approval_note is None
    assert "feature positions" in result.message and "never hide" in result.message


@pytest.mark.parametrize("volume,state,percent", [(1050, "Passed", 5), (950, "Passed", 5),
    (1050.00001, "FAILED", 5.000001), (949.99999, "FAILED", 5.000001)])
def test_five_percent_is_inclusive_and_uses_recorded_mass_denominator(volume, state, percent):
    result = check(examples=[example(volume=volume)])
    assert result.state == state
    assert result.examples[0].difference_percent == pytest.approx(percent)


def test_bom_fallback_only_flags_after_computed_drawing_failure_and_retains_both_trials():
    result = check(mass=8, bom=["Synthetic B"])
    assert result.state == "Flagged"
    assert [(r.material_source, r.calculated_g, r.matches) for r in result.examples] == [
        ("drawing", 4, False), ("bom", 8, True)]
    assert "drawing's material or the model's size" in result.message


def test_primary_drawing_match_is_not_overruled_by_bom_or_other_examples():
    result = check(bom=["Synthetic B"], examples=[example(), example("B", 3000)])
    assert result.state == "Passed" and len(result.examples) == 4


@pytest.mark.parametrize("draw_field", [None, field(MATERIAL, None), field(MATERIAL, "Synthetic A", confidence="unsure")])
def test_bom_primary_list_tries_every_material_when_drawing_missing_or_unsure(draw_field):
    result = check(mass=8, drawing_material=draw_field, bom=["Unknown formulation", "Synthetic A", "Synthetic B"])
    assert result.state == "Passed"
    assert [(r.material, r.matches) for r in result.examples] == [("Synthetic A", False), ("Synthetic B", True)]
    assert all(r.material_source == "bom" for r in result.examples)
    assert "Unknown formulation" in result.message and "density unavailable" in result.message


@pytest.mark.parametrize("mass", [None, 0, -1, True, "4", {"value": 4}, [4]])
def test_missing_invalid_or_unparsed_printed_weight_skips_without_guessing_units(mass):
    result = check(mass=mass)
    assert result.state == "Skipped" and result.examples == []
    assert result.review is None


@pytest.mark.parametrize("changes", [dict(confidence="unsure"), dict(method="unresolved"),
    dict(review=review(status="source_changed")), dict(review=review(status="human_rejected"))])
def test_unsure_unresolved_or_revoked_printed_weight_skips(changes):
    original = field(WEIGHT, 4)
    altered = original.model_copy(update=changes)
    assert check(drawing_weight=altered).state == "Skipped"


def test_missing_source_anchor_is_not_a_trusted_printed_weight():
    assert check(current_source_hashes={MATERIAL: HASHES[MATERIAL]}).state == "Skipped"


def test_no_material_and_no_candidate_match_are_failed():
    no_material = check(drawing=None)
    mismatch = check(mass=100, bom=["Synthetic B"])
    assert no_material.state == mismatch.state == "FAILED"
    assert no_material.examples == [] and "no trusted material" in no_material.message
    assert "Example A" in no_material.message and "4 g" in no_material.message
    assert len(mismatch.examples) == 2 and all(not r.matches for r in mismatch.examples)


def test_missing_drawing_density_is_not_a_proven_drawing_mismatch_or_a_silent_bom_pass():
    result = check(mass=8, drawing="Unspecified grade", bom=["Synthetic B"])
    assert result.state == "FAILED"
    assert result.examples[0].matches and result.examples[0].material_source == "bom"
    assert "density unavailable" in result.message and "mismatch has not been established" in result.message


def test_missing_density_is_never_replaced_by_an_illustrative_default():
    result = check(references=[])
    assert result.state == "FAILED" and not result.examples
    assert "No sourced density" in result.message and "Example A" in result.message


@pytest.mark.parametrize("volume", [None, 0])
def test_missing_volume_is_explicit_and_cannot_create_mass_or_hide_other_example(volume):
    result = check(examples=[example(volume=volume), example("B", 1000)])
    assert result.state == "Passed" and [r.example for r in result.examples] == ["B"]
    assert "Example A: calculated mass unavailable" in result.message
    assert "missing/invalid positive model volume" in result.message


def test_no_examples_and_duplicate_ids_are_not_a_synthetic_pass():
    assert check(examples=[]).state == "FAILED"
    with pytest.raises(ValueError, match="unique"):
        check(examples=[example(), example()])


@pytest.mark.parametrize("tolerance", [-1, float("inf"), float("nan"), True])
def test_invalid_tolerance_rejected(tolerance):
    with pytest.raises(ValueError, match="tolerance"):
        check(tolerance_percent=tolerance)


def test_approved_source_current_family_fallback_is_labeled_and_directional():
    approved = mapping()
    result = check(drawing="Synthetic alloy", mappings=[approved])
    assert result.state == "Passed"
    assert result.examples[0].density.material == "Synthetic A"
    assert result.examples[0].density.family_mapping == approved.name
    assert "Approved family-density fallback" in result.message
    reverse = check(drawing="Synthetic A", mappings=[approved], references=[reference("Synthetic alloy")])
    assert reverse.state == "FAILED" and not reverse.examples


@pytest.mark.parametrize("mapping_review", [c.ReviewState(), review(status="human_rejected"),
    review(status="source_changed"), review(based_on={}), review(based_on={"synthetic-mapping-source": "9" * 64})])
def test_unapproved_rejected_changed_or_unbound_family_mappings_are_unusable(mapping_review):
    result = check(drawing="Synthetic alloy", mappings=[mapping(review=mapping_review)])
    assert result.state == "FAILED" and not result.examples


def test_same_name_equivalence_is_symmetric_but_needs_approval():
    approved = mapping(relation="same")
    result = check(drawing="Synthetic A", references=[reference("Synthetic alloy")], mappings=[approved])
    assert result.state == "Passed" and "equivalent-name" in result.message
    pending = approved.model_copy(update={"review": c.ReviewState()})
    assert check(drawing="Synthetic A", references=[reference("Synthetic alloy")], mappings=[pending]).state == "FAILED"


def test_multiple_approved_density_targets_are_unresolved_rather_than_chosen_by_matching_mass():
    result = check(drawing="Synthetic alloy", mappings=[mapping(), mapping(target="Synthetic B")])
    assert result.state == "FAILED" and not result.examples
    assert "Ambiguous approved density mappings" in result.message


def test_mapping_cycle_terminates_and_exact_grade_density_precedes_family():
    cycle = [mapping("Synthetic alloy", "Synthetic alias", "same"),
             mapping("Synthetic alias", "Synthetic alloy", "same")]
    assert check(drawing="Synthetic alloy", mappings=cycle).state == "FAILED"
    result = check(drawing="Synthetic A", mappings=[mapping("Synthetic A", "Synthetic B")])
    assert result.state == "Passed" and result.examples[0].density.family_mapping is None


@pytest.mark.parametrize("relation", ["different", "no_equivalent"])
def test_approved_negative_relationship_cannot_be_bypassed_by_positive_mapping(relation):
    result = check(drawing="Synthetic alloy", mappings=[mapping(), mapping(relation=relation)])
    assert result.state == "FAILED" and not result.examples


@pytest.mark.parametrize("fallback", [False, True])
def test_source_bound_ai_values_work_without_fabricating_verified_or_human_review(fallback):
    result = check(drawing_weight=ai_field(WEIGHT, 4, fallback=fallback),
                   drawing_material=ai_field(MATERIAL, "Synthetic A", fallback=fallback))
    assert result.state == "Passed" and result.review is None
    assert ("UNVERIFIED" in result.message) == fallback
    changed = dict(HASHES, **{WEIGHT: "8" * 64})
    assert check(drawing_weight=ai_field(WEIGHT, 4, fallback=fallback), current_source_hashes=changed).state == "Skipped"


@pytest.mark.parametrize("verdict", ["disagrees", "unsure"])
def test_disagreement_or_unsure_candidate_is_not_accepted_as_fallback(verdict):
    unresolved = ai_field(WEIGHT, 4, verdict=verdict)
    assert check(drawing_weight=unresolved).state == "Skipped"


def test_effective_human_corrections_override_unsure_originals_without_rewriting_them():
    original = field(WEIGHT, None, confidence="unsure")
    corrected = original.model_copy(update={"review": review(), "correction": c.Correction(
        original=None, corrected=4, by=HUMAN, at=AT, decision_id="synthetic-decision")})
    material = field(MATERIAL, "Unreadable", confidence="unsure").model_copy(update={
        "review": review(), "correction": c.Correction(original="Unreadable", corrected="Synthetic A",
                                                       by=HUMAN, at=AT, decision_id="synthetic-decision")})
    before = corrected.model_dump(mode="json")
    result = check(drawing_weight=corrected, drawing_material=material)
    assert result.state == "Passed" and result.examples[0].drawing_g == 4
    assert result.examples[0].material == "Synthetic A"
    assert corrected.model_dump(mode="json") == before
    assert original.value is None and corrected.value is None
    changed = corrected.model_copy(update={"review": review(status="source_changed")})
    assert check(drawing_weight=changed).state == "Skipped"


def test_failed_and_flagged_have_pending_review_bound_to_exact_density_result_and_need_note_only_on_failure():
    source = c.FactSource(name=WEIGHT, says="4 synthetic g", method="parsed",
        target=c.SourceTarget(kind="drawing", name=WEIGHT, drawing_id="D-901", page=1),
        source_sha256=HASHES[WEIGHT])
    for result in [check(mass=100), check(mass=8, bom=["Synthetic B"])]:
        before = result.model_dump(mode="json")
        item = weight.weight_review_item(part_id="D-901/part", check=result, source_hashes=HASHES,
                                         sources=[source], at=AT)
        assert item.kind == "weight" and item.status == "pending" and item.review is None
        assert item.approval_note_required == (result.state == "FAILED")
        assert item.allowed_actions == [c.ReviewAction.CONFIRM]
        assert item.source_hashes["D-901/part/weight-check/result"] == c.contract_digest(result)
        assert item.created_at == item.updated_at == AT and item.weight_check == result
        assert item.sources == [source] and result.model_dump(mode="json") == before
        altered = result.model_copy(deep=True)
        altered.examples[0].density.retrieved_at = AT + timedelta(days=1)
        assert c.contract_digest(altered) != item.source_hashes["D-901/part/weight-check/result"]


@pytest.mark.parametrize("state", ["Passed", "Skipped"])
def test_success_and_skips_do_not_invent_review_events(state):
    result = check() if state == "Passed" else check(mass=None)
    assert weight.weight_review_item(part_id="D-901/part", check=result, source_hashes=HASHES, at=AT) is None


def test_review_rejects_unbound_inputs_naive_time_and_prior_approval_migration():
    result = check(mass=100)
    for changes in [dict(source_hashes={}), dict(at=AT.replace(tzinfo=None)),
        dict(source_hashes={"D-901/part/weight-check/result": "9" * 64}),
        dict(check=result.model_copy(update={"review": review(), "approval_note": NOTE}))]:
        options = dict(part_id="D-901/part", check=result, source_hashes=HASHES, at=AT)
        options.update(changes)
        with pytest.raises(ValueError):
            weight.weight_review_item(**options)


def test_shipped_density_artifact_has_primary_urls_dates_units_and_no_generic_stainless_guess():
    artifact = ROOT / "development/backend/cad/densities.json"
    data = json.loads(artifact.read_text(encoding="utf-8"))
    values = {r.material: r for r in weight.load_densities()}
    assert {name: r.density_g_cm3 for name, r in values.items()} == {
        "Aluminium": 2.71, "Steel": 7.85, "EN AW-5005": 2.7, "EN AW-6082": 2.7,
        "Stainless steel 304": 7.9, "Stainless steel 316L": 8.0}
    for material, ref in values.items():
        assert ref.source_url.startswith("https://") and ref.retrieved_at.date().isoformat() == data["lookup_date"]
        assert ref.outside_dataset and ref.family_mapping is None and material in data["reference_basis"]
    assert "Stainless steel" not in values
    assert any(item.get("material") == "Stainless steel" for item in data["unavailable_materials"])
    # This arithmetic fixture is not a real source-part result or benchmark mass.
    result = check(mass=2.7, drawing="EN AW-5005", references=weight.load_densities())
    assert result.state == "Passed" and result.examples[0].calculated_g == 2.7


def test_density_loading_rejects_malformed_duplicate_and_preapproved_entries_without_local_fetch():
    parent = ROOT / "testing/tmp/M25-weight"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as folder:
        path = Path(folder) / "densities.json"
        ref = reference().model_dump(mode="json")
        for value in [[], {}, dict(schema="meridian-densities/v1", references=[]),
            dict(schema="meridian-densities/v1", references=[ref, ref]),
            dict(schema="meridian-densities/v1", references=[dict(ref, source_url="file:///private/source")]),
            dict(schema="meridian-densities/v1", references=[dict(ref, family_mapping="invented approval")])]:
            path.write_text(json.dumps(value), encoding="utf-8")
            with pytest.raises(ValueError):
                weight.load_densities(path)
