"""Focused synthetic policy checks, authored for ROOT's Actions run.

No providers, app, input corpus, PDF/CAD processing, or production decisions.
"""
from __future__ import annotations

import copy
from decimal import Decimal

from pydantic import ValidationError

from development.backend import contracts as c


def rejected(factory, label: str) -> None:
    try:
        factory()
    except (ValidationError, ValueError):
        return
    raise AssertionError("Invalid policy accepted: " + label)


def dump(value) -> dict:
    return copy.deepcopy(value.model_dump(mode="json"))


def rehash(value: dict, key: str) -> None:
    value[key] = c.contract_digest({name: item for name, item in value.items() if name != key})


def mutation(record: c.PrepProvenance, change, label: str) -> None:
    data = dump(record)
    change(data)
    rejected(lambda: c.PrepProvenance.model_validate(data), label)


def check_observability(fixtures: dict) -> None:
    batch = fixtures["prep-observability.json"]
    record = batch.records[0]
    sol, opus = record.rounds[0].determination, record.rounds[0].verification
    assert sol.status == opus.status == "success"
    assert sol.effective is None and sol.failure is None and opus.failure is None
    assert opus.effective.model == "claude-opus-5-5"
    assert opus.effective.reasoning is None and opus.effective.read_only is None
    assert opus.effective.settings["fallbackModel"] is None
    assert sol.cache.settings_basis == opus.cache.settings_basis == "requested"
    assert sol.cache.effective_sha256 is None
    assert opus.cache.effective_sha256 == c.contract_digest(opus.effective)
    assert sol.cache.settings == sol.requested and opus.cache.settings == opus.requested
    assert record.mode == "determine_verify" and record.outcome == "first_pass_verified"
    assert all(field.status == "first_pass_verified" for field in record.field_results.values())
    assert batch.counts.first_pass_verified == 1
    assert batch.counts.execution_failed_attempts == batch.counts.unverified_fallback == 0
    assert c.PrepBatchResult.model_validate_json(batch.model_dump_json()) == batch
    confirmed = fixtures["prep-cases.json"].records[0].rounds[0]
    for attempt in (confirmed.determination, confirmed.verification):
        assert attempt.cache.settings_basis == "confirmed"
        assert attempt.cache.effective_sha256 == c.contract_digest(attempt.effective)

    def change_observation(data, stage, field, value):
        attempt = data["rounds"][0][stage]
        if attempt["effective"] is None:
            attempt["effective"] = c.ObservedReaderSettings().model_dump(mode="json")
        attempt["effective"][field] = value
        # Bind the changed observation so rejection cannot be explained by a stale hash.
        attempt["cache"]["effective_sha256"] = c.contract_digest(attempt["effective"])

    cases = [
        ("determination", "provider", "claude_code"), ("determination", "model", "other-model"),
        ("determination", "reasoning", "high"), ("determination", "service_tier", "regular"),
        ("determination", "read_only", False), ("determination", "settings", {"sandbox": "workspace-write"}),
        ("determination", "settings", {"image_input": False}),
        ("verification", "provider", "codex_cli"), ("verification", "model", "gpt-6.1-sol"),
        ("verification", "reasoning", "max"), ("verification", "service_tier", "fast"),
        ("verification", "read_only", False), ("verification", "settings", {"fastMode": True}),
        ("verification", "settings", {"fallbackModel": ["other-model"]}),
    ]
    for stage, field, value in cases:
        mutation(record, lambda data: change_observation(data, stage, field, value), "reported conflict: " + stage + "/" + field)
    mutation(record, lambda data: data["rounds"][0]["determination"]["cache"].update(settings_basis="confirmed"), "unknown identity promoted to confirmed")
    mutation(record, lambda data: data["rounds"][0]["verification"]["cache"].update(effective_sha256="0" * 64), "unbound partial observations")
    mutation(record, lambda data: data["rounds"][0]["determination"]["requested"].update(model="other-model"), "wrong requested model despite unknown effective")
    mutation(record, lambda data: data["rounds"][0]["determination"]["cache"]["settings"].update(reasoning="high"), "unbound requested pins")
    mutation(record, lambda data: data["rounds"][0]["verification"].update(output=None), "unknown metadata cannot excuse missing output")
    mutation(record, lambda data: data.update(mode="single_model_unverified"), "unknown metadata is not fallback")
    mutation(record, lambda data: data["rounds"][0]["verification"].update(candidate_sha256="0" * 64), "unknown metadata cannot excuse candidate mismatch")
    mutation(record, lambda data: data["source"]["inputs"].update({"synthetic-drawing": "0" * 64}), "unknown metadata cannot excuse source mismatch")
    # All-unknown observations and no observations remain distinguishable cache identities.
    partial = c.ObservedReaderSettings()
    assert partial.model_dump(mode="json") == {"provider": None, "model": None, "reasoning": None,
        "service_tier": None, "read_only": None, "settings": {}}
    changed = dump(sol.cache)
    changed["effective_sha256"] = c.contract_digest(partial)
    assert c.contract_digest(changed) != c.contract_digest(sol.cache)
    assert c.prep_settings_basis(opus.requested, c.ObservedReaderSettings(model="claude-opus-5-5", reasoning="xhigh"), "verification") == "requested"
    requested_defaults = opus.requested.model_copy(update={"settings": {}})
    no_fallback_observation = c.ObservedReaderSettings(provider="claude_code", model="claude-opus-5-5", reasoning="xhigh",
        service_tier="regular", read_only=True, settings={"fastMode": False, "fallbackModel": None})
    assert c.prep_settings_basis(requested_defaults, no_fallback_observation, "verification") == "requested"
    print("PASS synthetic observability: source-bound success with null/partial metadata, pinned requests, explicit bound cache basis and reported-conflict rejection; no CLI identity verified")


def check_prep(fixtures: dict) -> None:
    batch = fixtures["prep-cases.json"]
    records = {record.job_id.removeprefix("synthetic-"): record for record in batch.records}
    first, retry, fallback = (records[key] for key in ("first", "retry", "fallback"))
    name = first.field_names[0]
    assert first.field_results[name].accepted.state == "options"
    assert retry.field_results[name].accepted.value == 1.75
    assert retry.rounds[0].determination.output.fields[name].value == 4.25
    assert retry.rounds[0].verification.output.fields[name].alternative.value == 1.75
    for case in ("persistent", "unsure", "invalid", "unsupported", "retry_failure"):
        assert records[case].field_results[name].status == "unresolved"
        assert records[case].field_results[name].accepted is None
    assert fallback.next_launch_attempt_opus
    assert fallback.mode == "single_model_unverified"
    assert fallback.rounds[0].verification.output is None
    assert batch.counts.model_dump() == {"count_unit": "field", "total_fields": 8, "first_pass_verified": 1,
        "retry_verified": 1, "unresolved": 5, "unverified_fallback": 1, "execution_failed_attempts": 2}
    bad_counts = dump(batch)
    bad_counts["counts"].update(first_pass_verified=2, unverified_fallback=0)
    rejected(lambda: c.PrepBatchResult.model_validate(bad_counts), "fallback counted as verified")

    mutation(first, lambda d: d.update(mode="dual_reader"), "historical blind-reader mode")
    mutation(first, lambda d: d.update(pipeline_version="B00"), "B00 capability as new sequence")
    mutation(first, lambda d: d["rounds"][0]["verification"].update(output=d["rounds"][0]["determination"]["output"]),
             "duplicate Sol answers without explicit field verdicts")
    mutation(first, lambda d: d["rounds"][0]["determination"]["output"]["fields"][name].update(options=[9, 8]),
             "candidate changed without new digest")
    mutation(first, lambda d: d["source"]["inputs"].update({"synthetic-drawing": "0" * 64}), "source changed")
    mutation(first, lambda d: d["rounds"][0]["verification"].update(candidate_sha256="0" * 64), "wrong submitted candidate")
    mutation(first, lambda d: d["rounds"][0]["verification"]["output"].update(source_sha256="0" * 64), "wrong verified source")
    mutation(first, lambda d: d["rounds"][0]["verification"]["output"]["fields"][name].update(reason="   "), "empty reason")
    mutation(first, lambda d: d["rounds"][0]["verification"]["output"]["fields"][name].update(source_ids=[]), "uncited verification")
    mutation(first, lambda d: d["rounds"][0]["verification"].update(effective=d["rounds"][0]["determination"]["effective"]), "two Sol identities")
    mutation(first, lambda d: d["rounds"][0]["verification"]["requested"].update(reasoning="high"), "wrong Opus effort")
    mutation(first, lambda d: d["rounds"][0]["verification"]["requested"]["settings"].update(fastMode=True), "Opus fast mode")
    mutation(first, lambda d: d["rounds"][0]["verification"].update(started_at="1999-01-01T00:00:00+00:00"), "parallel/blind stage ordering")
    mutation(first, lambda d: d["rounds"][0]["determination"].update(prior_failures=[{
        "classification": "output_parse", "execution_failure": False, "message": "Synthetic invalid JSON"}]), "hidden JSON repair/retry")
    mutation(first, lambda d: d["rounds"][0]["determination"]["cache"].update(prompt_sha256="0" * 64), "old prompt cache")
    mutation(first, lambda d: d["rounds"][0]["determination"]["cache"].update(field_names_sha256="0" * 64), "wrong field-inventory cache")
    mutation(first, lambda d: d["rounds"][0]["verification"]["cache"].update(pipeline_version="dual-reader/v0"), "blind cache identity")
    mutation(first, lambda d: d["field_names"].append(name), "duplicate field inventory")
    mutation(first, lambda d: d["field_names"].append("missing-field"), "unjudged field")
    mutation(first, lambda d: d["rounds"].extend(d["rounds"] * 2), "third round")
    mutation(retry, lambda d: d["rounds"][1]["determination"]["cache"].update(feedback_sha256="0" * 64), "unbound criticism")

    def verifier_mutation(data, change):
        output = data["rounds"][0]["verification"]["output"]
        change(output)
        rehash(output, "verification_sha256")
    mutation(first, lambda d: verifier_mutation(d, lambda o: o["fields"].clear()), "missing field verdict despite valid digest")
    mutation(first, lambda d: verifier_mutation(d, lambda o: o["fields"][name].update(source_ids=["invented-ref"])), "unowned verifier reference")

    def candidate_mutation(data, change):
        candidate = data["rounds"][0]["determination"]["output"]
        change(candidate["fields"][name])
        rehash(candidate, "candidate_sha256")
        opus = data["rounds"][0]["verification"]
        opus["candidate_sha256"] = opus["cache"]["candidate_sha256"] = candidate["candidate_sha256"]
        opus["output"]["candidate_sha256"] = candidate["candidate_sha256"]
        rehash(opus["output"], "verification_sha256")
        data["field_results"] = {}
    for change, label in ((lambda f: f.update(evidence_valid=False), "unsupported field verified"),
                          (lambda f: f.update(schema_valid=False), "invalid field verified"),
                          (lambda f: f.update(confidence="unsure"), "unsure candidate verified"),
                          (lambda f: f.update(source_ids=[]), "uncited candidate verified"),
                          (lambda f: f.update(source_ids=["invented-ref"]), "unowned candidate reference"),
                          (lambda f: f.update(basis=None), "disagreement manufactured into options")):
        mutation(first, lambda d: candidate_mutation(d, change), label)

    def remove_disagreement(data):
        output = data["rounds"][0]["verification"]["output"]
        output["fields"][name].update(verdict="unsure", alternative=None)
        rehash(output, "verification_sha256")
        data["rounds"][1]["determination"]["cache"]["feedback_sha256"] = output["verification_sha256"]
    mutation(retry, remove_disagreement, "retry for unsure without disagreement")
    mutation(records["persistent"], lambda d: d["field_results"][name].update(
        status="retry_verified", accepted=d["rounds"][0]["verification"]["output"]["fields"][name]["alternative"]),
        "verifier alternative directly accepted")
    mutation(fallback, lambda d: d.update(next_launch_attempt_opus=False), "sticky Sol-only cache")
    mutation(fallback, lambda d: d["rounds"][0]["verification"]["failure"].update(classification="output_schema"), "invalid output as execution failure")
    mutation(fallback, lambda d: d["rounds"][0]["verification"]["failure"].update(troubleshooting=[]), "untroubleshot fallback")
    mutation(fallback, lambda d: d["rounds"][0]["verification"].update(prior_failures=[{
        "classification": "output_schema", "execution_failure": False, "message": "Synthetic invalid output"}]), "invalid then failed execution hides invalid result")
    for case in ("persistent", "unsure", "invalid", "retry_failure"):
        def force_fallback(data):
            data.update(mode="single_model_unverified", outcome="unverified_fallback", field_results={})
            for round_ in data["rounds"]:
                for key in ("determination", "verification"):
                    round_[key]["cache"]["mode"] = "single_model_unverified"
        mutation(records[case], force_fallback, case + " cannot authorize fallback")

    # A failed determination preserves its failure and never invents an Opus run.
    failed = dump(first)
    failed.update(outcome="unresolved", field_results={})
    failed["rounds"][0]["determination"].update(status="invalid_output", output=None, failure={
        "classification": "evidence_invalid", "execution_failure": False, "message": "Synthetic unsupported determination"})
    failed["rounds"][0]["verification"] = None
    assert c.PrepProvenance.model_validate(failed).field_results[name].accepted is None

    # Only the matching Sol value may populate a source field.
    title = fallback.field_names[0]
    c.EvidenceField(name=title, original="Synthetic original", value="Synthetic revised title", method="ai_single_model", provenance=fallback)
    rejected(lambda: c.EvidenceField(name=title, original="Synthetic original", value="Opus suggestion",
             method="ai_single_model", provenance=fallback), "source value bypasses candidate")
    rejected(lambda: c.EvidenceField(name=name, original="Synthetic original", value=4.25,
             method="ai_agreed", provenance=first), "legacy agreement method")

    job = c.PrepJobRequest(job=retry.job, job_id=retry.job_id, source=retry.source, field_names=retry.field_names,
        determination_prompt_sha256=retry.determination_prompt_sha256, verification_prompt_sha256=retry.verification_prompt_sha256,
        output_contract_sha256=retry.output_contract_sha256)
    c.DeterminationRequest(job=job, round=1)
    c.DeterminationRequest(job=job, round=2, previous_candidate=retry.rounds[0].determination.output,
                           feedback=retry.rounds[0].verification.output)
    c.VerificationRequest(job=job, round=2, candidate=retry.rounds[1].determination.output)
    rejected(lambda: c.DeterminationRequest(job=job, round=2), "correction without criticism")
    check_mixed_and_domain_fields(first, retry)
    print("PASS determine/verify policy: source/candidate/role/cache binding, explicit field verdicts, bounded correction, no alternative acceptance, honest fallback/counts")


def check_mixed_and_domain_fields(first: c.PrepProvenance, retry: c.PrepProvenance) -> None:
    data = dump(retry)
    name, secondary = first.field_names[0], "D-013/template/secondary"
    data.update(field_names=[name, secondary], field_results={})
    unchanged = copy.deepcopy(data["rounds"][0]["determination"]["output"]["fields"][name])
    for index, round_ in enumerate(data["rounds"]):
        sol, opus = round_["determination"], round_["verification"]
        sol["output"]["fields"][secondary] = unchanged
        rehash(sol["output"], "candidate_sha256")
        opus["candidate_sha256"] = opus["cache"]["candidate_sha256"] = sol["output"]["candidate_sha256"]
        opus["output"]["candidate_sha256"] = sol["output"]["candidate_sha256"]
        opus["output"]["fields"][secondary] = {"verdict": "verified", "reason": "Synthetic unchanged field checked again",
            "source_ids": unchanged["source_ids"], "alternative": None}
        rehash(opus["output"], "verification_sha256")
        for attempt in (sol, opus):
            attempt["cache"]["field_names_sha256"] = c.contract_digest(data["field_names"])
        if index:
            prior = data["rounds"][0]
            sol["cache"]["candidate_sha256"] = prior["determination"]["output"]["candidate_sha256"]
            sol["cache"]["feedback_sha256"] = prior["verification"]["output"]["verification_sha256"]
    mixed = c.PrepProvenance.model_validate(data)
    counts = c.prep_counts([mixed])
    assert (counts.first_pass_verified, counts.retry_verified, counts.total_fields) == (1, 1, 2)

    def retarget(new_name: str, state: str, value: dict) -> c.PrepProvenance:
        data = dump(first)
        data.update(field_names=[new_name], field_results={})
        sol, opus = data["rounds"][0]["determination"], data["rounds"][0]["verification"]
        field = copy.deepcopy(sol["output"]["fields"][name])
        field.update(state=state, value=value, options=[], basis=None)
        sol["output"]["fields"] = {new_name: field}
        rehash(sol["output"], "candidate_sha256")
        verdict = opus["output"]["fields"][name]
        opus["output"].update(fields={new_name: verdict}, candidate_sha256=sol["output"]["candidate_sha256"])
        rehash(opus["output"], "verification_sha256")
        opus["candidate_sha256"] = opus["cache"]["candidate_sha256"] = sol["output"]["candidate_sha256"]
        for attempt in (sol, opus):
            attempt["cache"]["field_names_sha256"] = c.contract_digest([new_name])
        return c.PrepProvenance.model_validate(data)

    link_name = "D-013/link"
    row_name = c.bom_row_name("Synthetic", "Fixture")
    link_prep = retarget(link_name, "match", {"drawing_id": "D-013", "bom_rows": [row_name]})
    c.LinkInfo(method="ai_verified", drawing_id="D-013", bom_rows=[row_name], prep_field_name=link_name, provenance=link_prep)
    rejected(lambda: c.LinkInfo(method="ai_verified", drawing_id="D-013", bom_rows=["invented-row"],
             prep_field_name=link_name, provenance=link_prep), "link bypasses accepted candidate")
    mapping_name = c.mapping_name("material", "Synthetic Q", "Synthetic metal")
    mapping_prep = retarget(mapping_name, "relationship", {"relationship": "kind_of", "to_name": "Synthetic metal"})
    mapping = dict(name=mapping_name, kind="material", from_name="Synthetic Q", to_name="Synthetic metal",
        relationship="kind_of", evidence="general_engineering_knowledge", evidence_note="Synthetic outside-dataset example",
        method="ai_verified", provenance=mapping_prep)
    assert c.NameMapping(**mapping).review.status == c.ReviewStatus.NOT_REVIEWED
    rejected(lambda: c.NameMapping(**{**mapping, "relationship": "same"}), "mapping bypasses accepted candidate")
    # Nested provenance is deliberately outside the geometric candidate value.
    template = c.KnownNumberField(name="D-013/template/length", value=7, evidence={"number_ids": ["synthetic-number"]}, method="parsed")
    assert c.template_candidate_value({"type": "rectangle", "length": template.model_dump(mode="json")}) == {"type": "rectangle", "length": 7}


def check_summaries(fixtures: dict) -> None:
    records = fixtures["summary-inputs.json"].records
    machine, cost = fixtures["machine-summary.json"], fixtures["cost-summary.json"]
    snapshot = c.contract_digest([record.model_dump(mode="json") for record in sorted(records, key=lambda r: r.id)])
    rows = {row.name: row for record in records for row in record.bom}
    drawings = {record.drawing.id: record.drawing for record in records if record.drawing}
    assert machine.records_sha256 == cost.records_sha256 == snapshot
    assert machine.record_count == len(records)
    assert machine.drawing_count == len(drawings)
    assert machine.bom_row_count == cost.row_count == len(rows)
    assert {name for section in machine.drawing_sections for name in section.member_ids} == drawings.keys()
    assert {name for section in machine.bom_sections for name in section.member_ids} == rows.keys()
    sources = {**{key: value.source_sha256 for key, value in drawings.items()}, **{key: value.source_sha256 for key, value in rows.items()}}
    assert machine.source_hashes == cost.source_hashes == sources
    recorded = {name: row.fields["total_cost"].value for name, row in rows.items() if row.fields["total_cost"].value is not None}
    actual_total = sum((Decimal(str(value)) for value in recorded.values()), Decimal(0))
    assert cost.recorded_total == format(actual_total.quantize(Decimal("0.01")), ".2f")
    assert set(cost.recorded_row_names) == recorded.keys()
    assert cost.recorded_total_count == len(recorded)
    assert cost.missing_total_count == len(rows) - len(recorded)
    for group in cost.missing_reasons:
        for name in group.row_names:
            assert rows[name].fields["total_cost"].value is None
            if group.reason == "missing_unit_cost":
                assert rows[name].fields["cost"].value is None
    assert cost.snapshot_note and cost.caveat and cost.facts[cost.fact].snapshot_note
    bad = dump(cost)
    bad["recorded_total"] = 0.3
    rejected(lambda: c.CostSummaryResult.model_validate(bad), "binary float money")
    bad = dump(cost)
    bad["recorded_row_names"].append(bad["recorded_row_names"][0])
    rejected(lambda: c.CostSummaryResult.model_validate(bad), "duplicate linked row counted twice")
    bad = dump(machine)
    bad["drawing_count"] += 1
    rejected(lambda: c.MachineSummaryResult.model_validate(bad), "fabricated section count")
    bad = dump(machine)
    bad["facts"].clear()
    rejected(lambda: c.MachineSummaryResult.model_validate(bad), "uncited aggregation")
    print("PASS summary contracts: snapshot and counts/Decimal totals independently derived from synthetic records; missing reasons, source citations and partition guards")


def review_cases(fixtures: dict) -> list[dict]:
    records = {record.job_id.removeprefix("synthetic-"): record for record in fixtures["prep-cases.json"].records}
    first, retry, fallback = (records[key] for key in ("first", "retry", "fallback"))
    sources = first.source.inputs
    review = {"status": "human_confirmed", "by": "Synthetic reviewer only", "at": "2000-01-01T00:00:00+00:00", "based_on": sources}
    baseline = {"usable": True, "current_source_hashes": sources}
    cases = [
        ({**baseline}, "Unavailable"),
        ({**baseline, "provenance": dump(first)}, "AI reviewed"),
        ({**baseline, "provenance": dump(retry)}, "AI reviewed"),
        ({**baseline, "provenance": dump(fallback)}, "Unavailable"),
        ({**baseline, "provenance": dump(records["persistent"])}, "Unavailable"),
        ({**baseline, "review": review}, "Human reviewed"),
        ({**baseline, "review": {**review, "status": "human_rejected"}}, "Unavailable"),
        ({**baseline, "review": {**review, "status": "source_changed"}}, "Unavailable"),
        ({**baseline, "review": {**review, "based_on": {}}}, "Unavailable"),
        ({**baseline, "review": review, "usable": False}, "Unavailable"),
        ({**baseline, "provenance": dump(first), "usable": False}, "Unavailable"),
        ({**baseline, "provenance": dump(first), "field_name": "uncited-field"}, "Unavailable"),
        ({**baseline, "provenance": dump(first), "current_source_hashes": {}}, "Unavailable"),
        ({**baseline, "review": review, "current_source_hashes": {"synthetic-drawing": "0" * 64}}, "Unavailable"),
        ({**baseline, "provenance": dump(first), "current_source_hashes": {"synthetic-drawing": "0" * 64}}, "Unavailable"),
    ]
    result = []
    for data, expected in cases:
        typed = dict(data)
        if data.get("review"):
            typed["review"] = c.ReviewState.model_validate(data["review"])
        if data.get("provenance"):
            typed["provenance"] = c.PrepProvenance.model_validate(data["provenance"])
        assert c.customer_review_status(**typed).value == expected
        result.append({"input": data, "expected": expected})
    assert {status.value for status in c.CustomerReviewStatus} == {"Human reviewed", "AI reviewed", "Unavailable"}
    assert fixtures["status-configured.json"].debug_enabled is False
    assert fixtures["status-missing-key.json"].debug_enabled is False
    assert fixtures["status-debug-enabled.json"].debug_enabled is True
    print("PASS customer status: three honest labels, current source checks, no fallback/parsed review claims; Debug defaults hidden")
    return result
