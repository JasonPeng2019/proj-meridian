"""Focused remote-only M10 checks. All model answers below are synthetic scripts.

From product/testing on Actions:
../development/.venv/bin/python -B -m pytest -q -p no:cacheprovider
    --basetemp=tmp/A10-pytest --junitxml=reports/ci/A10-matching.xml tests/test_matching_m1.py
No PDF extraction, live model, production prep output or human approval is used.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

import pytest
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend.ai.matching import LINKS_REF, REGISTRY_REF, MatchingRegistry  # noqa: E402
from backend.ai.runner import CliReservation, EvidenceError, Runner  # noqa: E402
from backend.contracts import (  # noqa: E402
    BOMField, BOMRow, DeterminationOutput, DeterminedField, DrawingEvidence,
    DrawingField, Method, PageGeometry, ReviewStatus, bom_fact_name, bom_row_name,
    contract_digest, drawing_fact_name,
)


NOTE = "Invented M10 fixture, not source engineering facts, model execution or human review."
PEER = ROOT / "testing/fixtures/runner/scripted_cli.py"


def drawing(identity="D-001", filename="Bracket.pdf", title="Bracket", material="Alloy X", section="Cell"):
    source_hash = contract_digest({"synthetic": identity})
    fields = {key: DrawingField(name=drawing_fact_name(identity, key), original=value, value=value,
              method="parsed", confidence="sure" if value else "unsure", page=1,
              box=(0, 0, 20, 10), source_quality="clean")
              for key, value in {"title": title, "material": material, "notes": None}.items()}
    evidence = DrawingEvidence(id=identity, pages=1, image=f"images/{identity}/page-1.png",
        page_geometry=[PageGeometry(page=1, source_width=100, source_height=100, image_width=100, image_height=100)],
        degraded=False, source_quality="clean", source_path=f"dataset/drawings/{identity}.pdf",
        source_sha256=source_hash, fields=fields)
    asset = {"id": identity, "path": evidence.source_path, "sha256": source_hash,
             "source_path": f"SYNTHETIC/{section}/{filename}", "subsystem": section}
    return evidence, asset


def row(name="Bracket", section="Cell", datasheet="Bracket.pdf", material=None, display="BOM-001", kind="Custom"):
    values = {"name": name, "section": section, "type": kind,
              "datasheet": datasheet, "material": material if material is not None else ["Metal X"]}
    fields = {key: BOMField(name=bom_fact_name(section, name, key), value=value,
              original=", ".join(value) if isinstance(value, list) else value, method="parsed")
              for key, value in values.items()}
    return BOMRow(name=bom_row_name(section, name), display_id=display, display_name=name,
                  section=section, source_sha256=contract_digest({"synthetic": values}), fields=fields)


def registry(drawings=None, rows=None):
    supplied = drawings if drawings is not None else [drawing()]
    return MatchingRegistry([d for d, _ in supplied], rows if rows is not None else [row()],
                            {"synthetic": True, "note": NOTE, "assets": [a for _, a in supplied]})


def raw(state, value, refs, **updates):
    value = {"state": state, "value": value, "options": [], "basis": None,
             "confidence": "unsure" if state == "unknown" else "sure", "reason": NOTE, "source_ids": refs}
    value.update(updates)
    return value


def candidate(job, field):
    data = {"source_sha256": contract_digest(job.request.source),
            "fields": {job.field_name: DeterminedField(**field, schema_valid=False, evidence_valid=False).model_dump(mode="json")}}
    return DeterminationOutput(**data, candidate_sha256=contract_digest(data))


def sol(job, field):
    return {"role": "determination", "answer": {"fields": {job.field_name: field}}}


def opus(job, refs, verdict="verified", **updates):
    step = {"role": "verification", "answer": {"fields": {job.field_name: {
        "verdict": verdict, "reason": NOTE, "source_ids": refs, "alternative": None}}}}
    step.update(updates)
    return step


@pytest.fixture
def workspace():
    parent = ROOT / "testing/tmp/A10-matching"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as folder:
        yield Path(folder)


class Scripted:
    def __init__(self, workspace, job, steps):
        self.scenario = workspace / "scenario.json"
        self.scenario.write_text(json.dumps({"steps": steps, "calls": [], "active": 0}), encoding="utf-8")
        settings = yaml.safe_load((ROOT / "development/ai_settings.yaml").read_text(encoding="utf-8"))["prep"]
        self.runner = Runner(jobs={job.definition.job: job.definition}, prep_settings=settings,
            workspace_root=ROOT, runtime_root=workspace / "runtime", reserve_cli_slot=self.reserve,
            executables={cli: [sys.executable, "-B", str(PEER), "--script-role", role, "--scenario", str(self.scenario)]
                         for cli, role in (("codex", "determination"), ("claude", "verification"))},
            environment={}, min_interval_seconds=0, rate_cooldown_seconds=0, timeout_seconds=10)
        self.job = job

    @contextmanager
    def reserve(self):
        # Synthetic remote peer only; this is not a live CLI budget reservation.
        yield CliReservation(total_cli_processes=2, owner_counted=True)

    def run(self):
        return self.runner(self.job.request)

    @property
    def calls(self):
        return json.loads(self.scenario.read_text(encoding="utf-8"))["calls"]


def test_exact_filename_and_normalized_name_are_unique_without_ai():
    first, second = drawing(), drawing("D-002", "WindowFrame.PDF", title=None)
    rows = [row(), row("Window Frame", datasheet=None, display="BOM-002")]
    matches = registry([first, second], rows).exact_links()
    assert [r.state for r in matches] == ["matched", "matched"]
    assert all(r.link.method == Method.EXACT_MATCH and r.link.provenance is None for r in matches)
    assert [r.link.bom_rows for r in matches] == [[rows[0].name], [rows[1].name]]


def test_duplicate_recoater_reference_cannot_be_bypassed_by_unique_title():
    rows = [row("Recoater head", datasheet="RecoaterPlate.pdf (https://synthetic.invalid/one)"),
            row("Recoater stage plate", datasheet="RecoaterPlate.pdf (https://synthetic.invalid/two)", display="BOM-002")]
    result = registry([drawing(filename="RecoaterPlate.pdf", title="Recoater head")], rows).exact_links()[0]
    assert result.state == "ambiguous" and result.link.bom_rows == []
    assert result.candidate_rows == sorted(r.name for r in rows)


def test_duplicate_drawing_filename_name_and_stable_bom_identity_never_select():
    draws = [drawing(), drawing("D-002")]
    assert all(r.state == "ambiguous" and not r.link.bom_rows for r in registry(draws).exact_links())
    names = [row("Bracket", datasheet=None), row("Bracket", section="Other", datasheet=None, display="BOM-002")]
    assert registry(rows=names).exact_links()[0].state == "ambiguous"
    collision = [row(), row(display="BOM-002")]
    assert not registry(rows=collision).exact_links()[0].link.bom_rows
    # Excluding a corrupt identity cannot turn a shared name into a unique one.
    collision = [row(datasheet=None), row(datasheet=None, display="BOM-002"),
                 row(section="Other", datasheet=None, display="BOM-003")]
    assert registry(rows=collision).exact_links()[0].state == "ambiguous"


def test_unknown_drawing_and_manifest_mismatch_are_explicit():
    reg = registry()
    with pytest.raises(EvidenceError):
        reg.link_job("D-999")
    evidence, asset = drawing()
    asset["sha256"] = "0" * 64
    with pytest.raises(EvidenceError):
        MatchingRegistry([evidence], [row()], {"assets": [asset]})


@pytest.mark.parametrize("change", ["foreign_row", "duplicate_row", "foreign_drawing", "no_anchor", "uncited", "options"])
def test_validator_checks_actual_evidence_and_never_repairs_values(change):
    unanchored = row("Unrelated spindle", datasheet=None, display="BOM-002")
    reg = registry(rows=[row(), unanchored])
    job = reg.link_job("D-001")
    selected = row().name
    refs = ["D-001/source", row().fields["datasheet"].name]
    value = {"drawing_id": "D-001", "bom_rows": [selected]}
    field = raw("match", value, refs)
    if change == "foreign_row":
        value["bom_rows"] = ["BOM:invented/absent"]
    elif change == "duplicate_row":
        value["bom_rows"] = [selected, selected]
    elif change == "foreign_drawing":
        value["drawing_id"] = "D-999"
    elif change == "no_anchor":
        value["bom_rows"] = [unanchored.name]
        field["source_ids"] = ["D-001/source", unanchored.fields["name"].name]
    elif change == "uncited":
        field["source_ids"] = [REGISTRY_REF]
    else:
        field.update(state="options", value=None, options=[value, value], basis="printed_alternatives")
    before = candidate(job, field)
    checked = job.definition.validate_candidate(before, job.request.source)
    assert not checked.fields[job.field_name].evidence_valid
    assert checked.model_dump(exclude={"candidate_sha256", "fields"}) == before.model_dump(exclude={"candidate_sha256", "fields"})
    assert checked.fields[job.field_name].model_dump(exclude={"schema_valid", "evidence_valid"}) == before.fields[job.field_name].model_dump(exclude={"schema_valid", "evidence_valid"})


def test_runner_gets_exact_candidate_original_registry_and_explicit_verdict(workspace):
    reg = registry()
    job = reg.link_job("D-001")
    refs = ["D-001/source", row().fields["datasheet"].name]
    field = raw("match", {"drawing_id": "D-001", "bom_rows": [row().name]}, refs)
    script = Scripted(workspace, job, [sol(job, field), opus(job, refs)])
    record = script.run()
    result = reg.resolve_link("D-001", record)
    assert result.state == "matched" and result.link.method == Method.AI_VERIFIED
    assert record.field_results[job.field_name].status == "first_pass_verified"
    assert script.calls[1]["prompt"]["candidate"] == record.rounds[0].determination.output.model_dump(mode="json")
    assert script.calls[0]["prompt"]["original_evidence"] == script.calls[1]["prompt"]["original_evidence"]
    assert script.calls[1]["start"] >= script.calls[0]["end"]
    bundle = job.definition.evidence(job.request)
    bundle.check(job.request.source)
    assert bundle.inputs["registry"].value["registry_sha256"] == reg.digest


def test_one_revision_preserves_both_rounds_and_never_adopts_verifier_value(workspace):
    rows = [row("Bracket one", datasheet="Bracket.pdf"), row("Bracket two", datasheet="Bracket.pdf", display="BOM-002")]
    reg = registry(rows=rows)
    job = reg.link_job("D-001")
    refs = ["D-001/source", *(r.fields["datasheet"].name for r in rows)]
    first = raw("match", {"drawing_id": "D-001", "bom_rows": [rows[0].name]}, refs)
    revised = raw("match", {"drawing_id": "D-001", "bom_rows": [r.name for r in rows]}, refs)
    disagreement = opus(job, refs, "disagrees")
    disagreement["answer"]["fields"][job.field_name]["alternative"] = raw(
        "match", {"drawing_id": "D-001", "bom_rows": [rows[1].name]}, refs)
    script = Scripted(workspace, job, [sol(job, first), disagreement, sol(job, revised), opus(job, refs)])
    record = script.run()
    result = reg.resolve_link("D-001", record)
    assert result.link.method == Method.AI_VERIFIED_AFTER_RETRY and result.link.bom_rows == [r.name for r in rows]
    assert len(record.rounds) == 2 and len(script.calls) == 4
    assert script.calls[2]["prompt"]["verifier_feedback"] == record.rounds[0].verification.output.model_dump(mode="json")
    assert record.rounds[0].determination.output.fields[job.field_name].value == first["value"]
    review = reg.review_item(job, record, at=datetime.now(timezone.utc))
    assert review.ai_answers == record and review.status == "pending"
    assert {r.fields["datasheet"].name for r in rows} <= {s.name for s in review.sources}


@pytest.mark.parametrize("last_verdict", ["disagrees", "unsure"])
def test_persistent_disagreement_or_unsure_remains_unlinked(workspace, last_verdict):
    reg = registry()
    job = reg.link_job("D-001")
    refs = ["D-001/source", row().fields["datasheet"].name]
    field = raw("match", {"drawing_id": "D-001", "bom_rows": [row().name]}, refs)
    record = Scripted(workspace, job, [sol(job, field), opus(job, refs, "disagrees"),
                      sol(job, field), opus(job, refs, last_verdict)]).run()
    result = reg.resolve_link("D-001", record)
    assert result.state == "unresolved" and result.link.bom_rows == []
    assert result.link.method == Method.UNRESOLVED and len(result.link.provenance.rounds) == 2


def test_no_match_and_unknown_are_distinct(workspace):
    reg = registry([drawing(filename="UniqueWidget.pdf", title="Unique widget")], [row("Spindle", datasheet=None)])
    job = reg.link_job("D-001")
    refs = [REGISTRY_REF, "D-001/source"]
    field = raw("no_match", {"drawing_id": "D-001", "bom_rows": []}, refs)
    record = Scripted(workspace, job, [sol(job, field), opus(job, refs)]).run()
    result = reg.resolve_link("D-001", record)
    assert result.state == "no_match" and result.link.bom_rows == []
    unknown = candidate(job, raw("unknown", None, refs))
    assert not job.definition.validate_candidate(unknown, job.request.source).fields[job.field_name].evidence_valid


def test_execution_failure_is_unverified_and_next_launch_retries_opus(workspace):
    reg = registry()
    job = reg.link_job("D-001")
    refs = ["D-001/source", row().fields["datasheet"].name]
    field = raw("match", {"drawing_id": "D-001", "bom_rows": [row().name]}, refs)
    script = Scripted(workspace, job, [sol(job, field), opus(job, refs, action="oauth")])
    record = script.run()
    assert reg.resolve_link("D-001", record).link.method == Method.AI_SINGLE_MODEL
    assert "UNVERIFIED" in reg.review_item(job, record, at=datetime.now(timezone.utc)).message
    data = json.loads(script.scenario.read_text(encoding="utf-8"))
    data["steps"].append(opus(job, refs))
    script.scenario.write_text(json.dumps(data), encoding="utf-8")
    verified = script.run()
    assert verified.outcome == "first_pass_verified"
    assert [call["role"] for call in script.calls] == ["determination", "verification", "verification"]


def test_mapping_stage_requires_complete_current_validated_links():
    draws = [drawing(), drawing("D-002", filename="Window.pdf", title="Window")]
    rows = [row(), row("Window", datasheet="Window.pdf", display="BOM-002")]
    reg = registry(draws, rows)
    links = reg.exact_links()
    with pytest.raises(EvidenceError):
        reg.mapping_jobs(links[:1])
    forged = links[1].model_copy(deep=True)
    forged.link.bom_rows = [row().name]
    forged.state = "matched"
    with pytest.raises(EvidenceError):
        reg.mapping_jobs([links[0], forged])
    jobs = reg.mapping_jobs(links)
    assert {job.kind for job in jobs} == {"section", "material"}
    assert all(LINKS_REF in job.request.source.source_ids for job in jobs)
    changed = registry([drawing(), drawing("D-002", filename="Other.pdf", title="Other")], rows)
    with pytest.raises(EvidenceError):
        changed.mapping_jobs(links)
    unfinished = registry(draws)
    with pytest.raises(EvidenceError, match="Finish each non-exact"):
        unfinished.mapping_jobs(unfinished.exact_links())


@pytest.mark.parametrize("kind,relationship", [("section", "same"), ("material", "kind_of"),
                                              ("material", "different"), ("material", "no_equivalent")])
def test_verified_mappings_remain_unapproved_and_outside_knowledge_is_labeled(workspace, kind, relationship):
    reg = registry()
    before = reg.exact_links()[0].model_dump(mode="json")
    job = next(job for job in reg.mapping_jobs(reg.exact_links()) if job.kind == kind)
    refs = [LINKS_REF, "D-001/source", row().fields["section"].name] if kind == "section" else [
        LINKS_REF, drawing_fact_name("D-001", "material"), row().fields["material"].name]
    field = raw("relationship", {"relationship": relationship, "to_name": None if relationship == "no_equivalent" else job.to_name}, refs)
    record = Scripted(workspace, job, [sol(job, field), opus(job, refs)]).run()
    proposed = reg.resolve_mapping(job, record)
    assert proposed is not None and proposed.review.status == ReviewStatus.NOT_REVIEWED
    assert proposed.method == Method.AI_VERIFIED and proposed.review.by is None
    assert proposed.to_name == field["value"]["to_name"]
    if kind == "material":
        assert proposed.evidence == "general_engineering_knowledge"
        assert "not the dataset" in proposed.evidence_note
    review = reg.review_item(job, record, at=datetime.now(timezone.utc))
    assert review.status == "pending" and review.mapping == proposed
    assert "no effect on facts/search" in review.message
    assert reg.exact_links()[0].model_dump(mode="json") == before


def test_mapping_validator_requires_recorded_pair_and_completed_links_refs():
    reg = registry()
    job = next(job for job in reg.mapping_jobs(reg.exact_links()) if job.kind == "material")
    for value, refs in [({"relationship": "kind_of", "to_name": "Invented family"}, [LINKS_REF]),
                        ({"relationship": "kind_of", "to_name": job.to_name}, [REGISTRY_REF])]:
        output = candidate(job, raw("relationship", value, refs))
        assert not job.definition.validate_candidate(output, job.request.source).fields[job.field_name].evidence_valid


def test_unsupported_row_stays_unresolved_even_when_opus_execution_fails(workspace):
    reg = registry()
    job = reg.link_job("D-001")
    refs = ["D-001/source", row().fields["datasheet"].name]
    field = raw("match", {"drawing_id": "D-001", "bom_rows": ["BOM:invented/absent"]}, refs)
    record = Scripted(workspace, job, [sol(job, field), opus(job, refs, action="oauth")]).run()
    result = reg.resolve_link("D-001", record)
    assert result.state == "unresolved" and result.link.method == Method.UNRESOLVED
    assert record.mode == "determine_verify" and record.field_results[job.field_name].accepted is None


def test_candidate_change_invalidates_post_link_source_binding(workspace):
    rows = [row("Bracket one", datasheet="Bracket.pdf"), row("Bracket two", datasheet="Bracket.pdf", display="BOM-002")]
    reg = registry(rows=rows)
    job = reg.link_job("D-001")
    mappings = []
    for index, selected in enumerate(rows):
        folder = workspace / str(index)
        folder.mkdir()
        refs = ["D-001/source", selected.fields["datasheet"].name]
        field = raw("match", {"drawing_id": "D-001", "bom_rows": [selected.name]}, refs)
        record = Scripted(folder, job, [sol(job, field), opus(job, refs)]).run()
        links = [reg.resolve_link("D-001", record)]
        mappings.append(next(j for j in reg.mapping_jobs(links) if j.kind == "section"))
    assert mappings[0].field_name == mappings[1].field_name
    assert mappings[0].request.source != mappings[1].request.source


def test_registry_and_evidence_are_snapshots_and_noncustom_rows_are_inadmissible():
    evidence, asset = drawing()
    original = row()
    purchased = row("Bracket spare", display="BOM-002", datasheet=None, kind="Standard")
    reg = MatchingRegistry([evidence], [original, purchased], {"assets": [asset]})
    job = reg.link_job("D-001")
    evidence.fields["title"].value = "Caller mutation"
    original.display_name = "Caller mutation"
    asset["source_path"] = "Changed/filename.pdf"
    assert reg.link_job("D-001").request == job.request
    bundle = job.definition.evidence(job.request)
    bundle.inputs["registry"].value["drawings"].clear()
    job.definition.evidence(job.request).check(job.request.source)
    field = raw("match", {"drawing_id": "D-001", "bom_rows": [purchased.name]}, ["D-001/source"])
    output = job.definition.validate_candidate(candidate(job, field), job.request.source)
    assert not output.fields[job.field_name].evidence_valid


def test_changed_inputs_invalidate_retained_source_bound_link(workspace):
    reg = registry()
    job = reg.link_job("D-001")
    refs = ["D-001/source", row().fields["datasheet"].name]
    field = raw("match", {"drawing_id": "D-001", "bom_rows": [row().name]}, refs)
    record = Scripted(workspace, job, [sol(job, field), opus(job, refs)]).run()
    changed = registry(rows=[row(material=["Different recorded material"])])
    assert changed.link_job("D-001").request.source != job.request.source
    with pytest.raises(EvidenceError):
        changed.resolve_link("D-001", record)


def test_real_manifest_and_bom_duplicate_is_a_candidate_set_only():
    # Uses real recorded attachment/manifest metadata, without reading a PDF or
    # pretending the synthetic missing title is an actual extracted field.
    from backend.loader.bom import load_bom

    manifest = json.loads((ROOT / "development/inputs/project-meridian/dataset/manifest.json").read_text(encoding="utf-8"))
    asset = next(a for a in manifest["assets"] if a["id"] == "D-013")
    evidence, _ = drawing("D-013", title=None, material=None)
    evidence.source_sha256 = asset["sha256"]
    reg = MatchingRegistry([evidence], load_bom(), manifest)
    result = reg.exact_links()[0]
    assert result.state == "ambiguous" and result.link.bom_rows == []
    assert {"BOM:recoater/recoater-head", "BOM:recoater/recoater-stage-plate"} <= set(result.candidate_rows)
