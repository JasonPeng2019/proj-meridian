"""Focused M16/M22 M1 tests for queued CI; no real human/AI/CAD actions.

Run from testing/: python -B -m pytest -q tests/test_review_m1.py
All journals, inert source bytes and generated snapshots are isolated fixtures
under testing/tmp. Automated decisions identify a synthetic reviewer only.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import UUID

import pytest

from test_source_runtime import ROOT, source_bundle, MARKERS
from backend import contracts as c
from backend.app import review as review_module
from backend.app.review import ReviewError, create_review_service
from backend.app.tools import FactTools
from backend.loader.decisions import DecisionStore
from backend.loader.records import RecordRegistry, RecordsError, read_records
from backend.ai.prepare import PreparedKnowledge


PART = "D-001/part"
FACT = "D-001/drawing/title"
HUMAN = "Synthetic reviewer (automated test only)"
OLD = "Synthetic bracket"
NEW = "Synthetic source note only."
REASON = "Synthetic proposal supported by the original notes; not an engineering approval."
AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def workspace():
    parent = ROOT / "testing/tmp/review-m1"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        yield Path(directory)


@pytest.fixture(autouse=True)
def deterministic_events(monkeypatch):
    identifiers = iter(UUID(int=index) for index in range(1, 101))
    times = iter(AT + timedelta(seconds=index) for index in range(100))

    class Clock:
        @staticmethod
        def now(zone):
            assert zone == timezone.utc
            return next(times)

    monkeypatch.setattr(review_module, "datetime", Clock)
    monkeypatch.setattr(review_module, "uuid4", lambda: next(identifiers))


def compose(registry, store):
    resolver = FactTools(registry)
    dependencies = c.ReviewDependencies(append_decision=store.human_appender(HUMAN),
        rebuild_records=registry, resolve_facts=resolver.resolve_facts,
        load_template=registry.load_template, rebuild_model=None)
    service = create_review_service(registry=registry, decisions=store, dependencies=dependencies)
    tools = FactTools(registry, propose_correction=service.propose_correction)
    return service, tools


def runtime(workspace, *, restart=False):
    if restart:
        inputs, manifest = workspace / "inputs.json", workspace / "source/dataset/manifest.json"
    else:
        inputs, manifest = source_bundle(workspace)
    store = DecisionStore(workspace / "decisions", allow_synthetic=True)
    registry = RecordRegistry.from_inputs(inputs, manifest, decisions=store,
        records_path=workspace / "generated/records.json")
    service, tools = compose(registry, store)
    return service, tools, registry, store


def title(tools):
    return tools.get_facts(PART).facts[FACT]


def propose(tools, value=NEW, reason=REASON):
    return tools.propose_correction(FACT, value, reason)


def act(service, item, action="accept", note="Synthetic explicit review note."):
    return service.review_action(item.id, c.ReviewActionRequest(action=action, note=note), HUMAN)


def update_source_bundle(workspace):
    """Simulate a validated new extraction, with genuinely different bytes."""
    manifest_path = workspace / "source/dataset/manifest.json"
    source = manifest_path.parent / "drawings/D-001.pdf"
    source.write_bytes(source.read_bytes() + b"\nSynthetic changed source revision.")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["assets"][0]["sha256"] = digest
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    input_path = workspace / "inputs.json"
    inputs = json.loads(input_path.read_text("utf-8"))
    inputs["drawings"][0]["source_sha256"] = digest
    inputs["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    input_path.write_text(json.dumps(inputs, sort_keys=True), encoding="utf-8")


def test_chat_callback_persists_pending_and_does_not_change_facts(workspace):
    service, tools, registry, store = runtime(workspace)
    input_bytes = (workspace / "inputs.json").read_bytes()
    before = title(tools).model_dump()
    proposal = propose(tools)
    assert proposal.synthetic and proposal.fixture
    assert proposal.item.status == proposal.decision.status == "pending"
    assert proposal.item.allowed_actions == [c.ReviewAction.ACCEPT, c.ReviewAction.REJECT]
    assert proposal.decision.by == "Chat proposal" and proposal.decision.at == AT
    assert proposal.decision.old_value == OLD and proposal.decision.value == NEW
    assert proposal.decision.reason == REASON and proposal.decision.note is None
    assert proposal.review_link.id == proposal.item.id
    assert proposal.review_link.href == c.review_api_path(proposal.item.id)
    assert proposal.decision.based_on == registry.hashes_for(FACT)
    assert title(tools).model_dump() == before
    assert store.latest_accepted(FACT) is None
    independent = DecisionStore(store.directory, allow_synthetic=True)
    assert independent.history(FACT) == [proposal.decision]
    assert service.list_review() == [proposal.item]
    assert title(tools).display.value == OLD and title(tools).correction is None
    assert (workspace / "inputs.json").read_bytes() == input_bytes


def test_check_uses_original_text_and_actual_linked_bom_only(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools, "  synthetic BRACKET ")
    check = proposal.item.check_result
    assert check.method == "string_match" and check.proves_correct is False
    assert any(match.matched and match.source_name == FACT and match.text == OLD for match in check.drawing)
    assert any(match.matched and match.text == OLD for match in check.bom)
    sources = proposal.item.sources
    source = next(source for source in sources if source.name == FACT)
    assert source.says == OLD and source.target.box == (10, 10, 30, 10)
    assert source.target.drawing_id == "D-001" and source.target.page == 1
    assert any(source.target.kind == "bom" and isinstance(source.says, dict) for source in sources)
    assert {match.source_name for match in check.bom} <= {source.name for source in sources}
    assert "never proof" in check.message and store.latest_accepted(FACT) is None


def test_no_match_never_approves_or_claims_correctness(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools, "Synthetic wording absent from every original cell")
    check = proposal.item.check_result
    assert check.drawing and check.bom
    assert not any(match.matched for match in [*check.drawing, *check.bom])
    assert check.proves_correct is False and proposal.item.review is None
    assert title(tools).display.value == OLD and store.latest_accepted(FACT) is None


def test_unlinked_bom_row_cannot_supply_a_correction_check_match(workspace):
    inputs, manifest = source_bundle(workspace, rows=[
        {"Name": OLD, "Part family": "Synthetic Cell", "Type": "Custom", "Datasheet": "SyntheticBracket.pdf"},
        {"Name": "Synthetic unrelated row", "Part family": "Synthetic Other", "Type": "Custom",
         "Datasheet": "Unrelated.pdf", "Material": "Synthetic unlinked-only match"},
    ])
    store = DecisionStore(workspace / "decisions", allow_synthetic=True)
    registry = RecordRegistry.from_inputs(inputs, manifest, decisions=store)
    service, tools = compose(registry, store)
    assert len(registry.records) == 2 and len(registry.part_for(PART).bom) == 1
    proposal = propose(tools, "Synthetic unlinked-only match")
    assert proposal.item.check_result.bom
    assert not any(match.matched for match in proposal.item.check_result.bom)
    assert all(source.target.row_name != "BOM:synthetic-other/synthetic-unrelated-row"
               for source in proposal.item.sources)


def test_reject_keeps_originals_reason_note_and_terminal_history(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    result = act(service, proposal.item, "reject", "Synthetic rejection: insufficient support.")
    assert result.item.status == "rejected" and result.item.allowed_actions == []
    assert result.item.review.status == c.ReviewStatus.HUMAN_REJECTED
    assert result.item.review.by == HUMAN and result.item.review.at == AT + timedelta(seconds=1)
    assert [event.status for event in result.decisions] == ["pending", "rejected"]
    assert result.decisions[1].reason == REASON
    assert result.decisions[1].note == "Synthetic rejection: insufficient support."
    assert result.decisions[1].based_on == proposal.decision.based_on
    assert result.decisions[1].supersedes == proposal.decision.decision_id
    assert result.decisions[1].check_result == proposal.decision.check_result
    assert title(tools).display.value == OLD and title(tools).correction is None
    assert not service.list_review()
    assert service.list_review(c.ReviewListRequest(status="rejected"))[0].id == proposal.item.id
    restarted, restarted_tools, _, _ = runtime(workspace, restart=True)
    item = restarted.list_review(c.ReviewListRequest(status="all"))[0]
    assert item.status == "rejected" and "Synthetic rejection" in item.message
    assert title(restarted_tools).display.value == OLD
    with pytest.raises(ReviewError) as error:
        act(restarted, item)
    assert error.value.status_code == 409
    assert len(store.history(FACT)) == 2


def test_accept_refreshes_future_facts_preserves_evidence_and_survives_restart(workspace):
    service, tools, registry, store = runtime(workspace)
    input_bytes = (workspace / "inputs.json").read_bytes()
    original = registry.part_for(PART).drawing.fields["title"].model_dump()
    proposal = propose(tools)
    result = act(service, proposal.item, note="Synthetic accepted note, not an actual human review.")
    assert result.item.status == "accepted" and result.item.allowed_actions == []
    assert result.item.review.status == c.ReviewStatus.HUMAN_CONFIRMED and result.item.review.by == HUMAN
    assert result.decisions == store.history(FACT)
    assert [event.status for event in result.decisions] == ["pending", "accepted"]
    accepted = result.decisions[-1]
    assert accepted.reason == REASON and accepted.note == "Synthetic accepted note, not an actual human review."
    assert accepted.based_on == proposal.decision.based_on and accepted.proposal_id == proposal.item.proposal_id
    assert accepted.at == AT + timedelta(seconds=1)
    assert result.refresh.part_ids == [PART] and result.refresh.facts[FACT].display.value == NEW
    assert result.refresh.models[PART].state == "missing"
    assert result.refresh.models[PART].built_at is None and not result.refresh.models[PART].examples
    assert any("builder unavailable" in warning for warning in result.refresh.warnings)
    fact = title(tools)
    assert fact.display.value == NEW and fact.correction.corrected == NEW and fact.correction.original == OLD
    assert fact.correction.by == HUMAN and fact.review.at == accepted.at
    assert any(source.name == FACT and source.says == OLD for source in fact.sources)
    field = registry.part_for(PART).drawing.fields["title"]
    assert field.original == original["original"] and field.value == original["value"]
    assert field.method == original["method"] and field.confidence == original["confidence"]
    assert read_records(workspace / "generated/records.json").decision_journals[0].decisions == result.decisions
    assert (workspace / "inputs.json").read_bytes() == input_bytes
    restarted, restarted_tools, restarted_registry, restarted_store = runtime(workspace, restart=True)
    item = restarted.list_review(c.ReviewListRequest(status="accepted"))[0]
    assert item.id == proposal.item.id and item.review.by == HUMAN
    assert "Synthetic accepted note" in item.message
    assert title(restarted_tools).display.value == NEW
    restarted_registry()
    assert title(restarted_tools).display.value == NEW
    assert restarted_store.history(FACT) == result.decisions


def test_rejecting_later_proposal_does_not_revoke_an_accepted_overlay(workspace):
    service, tools, registry, store = runtime(workspace)
    accepted = act(service, propose(tools).item)
    later = propose(tools, "Synthetic second suggestion")
    assert later.decision.old_value == NEW and title(tools).display.value == NEW
    rejected = act(service, later.item, "reject")
    assert rejected.item.status == "rejected" and title(tools).display.value == NEW
    assert store.latest_accepted(FACT).decision_id == accepted.decisions[-1].decision_id
    assert [event.status for event in store.history(FACT)] == ["pending", "accepted", "pending", "rejected"]


@pytest.mark.parametrize("accepted", [False, True])
def test_changed_source_disables_pending_or_accepted_overlay_without_rewriting_history(workspace, accepted):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    if accepted:
        act(service, proposal.item)
    saved = store.history(FACT)
    update_source_bundle(workspace)
    restarted, restarted_tools, current_registry, current_store = runtime(workspace, restart=True)
    item = restarted.list_review(c.ReviewListRequest(status="source_changed"))[0]
    assert item.id == proposal.item.id and item.status == "source_changed" and item.allowed_actions == []
    assert item.source_hashes == proposal.decision.based_on
    assert item.source_hashes != current_registry.hashes_for(FACT)
    assert current_store.history(FACT) == saved and title(restarted_tools).display.value == OLD
    if accepted:
        assert item.review.status == c.ReviewStatus.SOURCE_CHANGED and item.review.by == HUMAN
    with pytest.raises(ReviewError) as error:
        act(restarted, item)
    assert error.value.response.error.code == c.ErrorCode.STALE_CONFLICT
    assert current_store.history(FACT) == saved


def test_source_file_tampering_blocks_review_before_any_human_append(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    source = workspace / "source/dataset/drawings/D-001.pdf"
    source.write_bytes(source.read_bytes() + b"Synthetic unvalidated change")
    with pytest.raises(ReviewError) as error:
        act(service, proposal.item)
    assert error.value.status_code == 409 and str(workspace) not in str(error.value)
    assert store.history(FACT) == [proposal.decision]


@pytest.mark.parametrize("body", [
    {"action": "set_value", "value": "Synthetic bypass"},
    {"action": "confirm"}, {"action": "approve_design"},
    {"action": "accept", "value": "Synthetic replacement"},
    {"action": "accept", "source_ids": ["Unreviewed source"]},
])
def test_unsupported_or_replacement_actions_cannot_change_a_proposal(workspace, body):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    with pytest.raises(ReviewError):
        service.review_action(proposal.item.id, c.ReviewActionRequest(**body), HUMAN)
    assert store.history(FACT) == [proposal.decision] and title(tools).display.value == OLD


def test_review_needs_configured_human_capability_and_server_reviewer(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    with pytest.raises(ReviewError) as error:
        service.review_action(proposal.item.id, c.ReviewActionRequest(action="accept"), "Forged test reviewer")
    assert error.value.status_code == 403 and store.history(FACT) == [proposal.decision]
    untrusted = create_review_service(registry=registry, decisions=store,
        dependencies=replace(service.dependencies, append_decision=store.append_decision))
    with pytest.raises(ReviewError):
        act(untrusted, proposal.item)
    assert store.history(FACT) == [proposal.decision]
    assert title(tools).display.value == OLD


def test_competing_review_actions_produce_one_terminal_event(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)

    def interleaved_append(decision):
        act(service, proposal.item, "reject", "Synthetic competing rejection.")
        return store.human_appender(HUMAN)(decision)

    competing = create_review_service(registry=registry, decisions=store,
        dependencies=replace(service.dependencies, append_decision=interleaved_append))
    with pytest.raises(ReviewError) as error:
        act(competing, proposal.item)
    assert error.value.status_code == 409
    assert [event.status for event in store.history(FACT)] == ["pending", "rejected"]
    assert title(tools).display.value == OLD


def test_durable_decision_is_reported_when_projection_fails_then_recovers(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    calls = 0

    def failing_refresh(part_ids=None):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RecordsError("Synthetic post-append refresh failure")
        return registry(part_ids)

    failing = create_review_service(registry=registry, decisions=store,
        dependencies=replace(service.dependencies, rebuild_records=failing_refresh))
    result = act(failing, proposal.item)
    assert result.item.status == "accepted" and store.latest_accepted(FACT) is not None
    assert result.refresh.facts == {} and result.refresh.models == {}
    assert any("Decision saved" in warning for warning in result.refresh.warnings)
    service.list_review(c.ReviewListRequest(status="all"))
    assert title(tools).display.value == NEW and len(store.history(FACT)) == 2


def test_no_builder_preserves_existing_stale_assets_without_new_build_metadata(workspace):
    service, tools, registry, store = runtime(workspace)
    previous = registry.part_for(PART)
    previous.model = c.ModelStatus(state="stale", stale_reason="Synthetic previous template.",
        examples=[c.ModelExample(id="A", glb="synthetic-only/no-real-model.glb")], built_at=AT)
    previous.has_3d, previous.examples = True, ["A"]
    fixture_registry = RecordRegistry(registry.document.prepared, decisions=store, previous_records=[previous])
    service, tools = compose(fixture_registry, store)
    result = act(service, propose(tools).item)
    model = result.refresh.models[PART]
    assert model.state == "stale" and "builder unavailable" in model.stale_reason
    assert model.examples == previous.model.examples and model.built_at == AT
    assert model.selected_example is None and model.built_template_sha256 is None
    assert result.refresh.facts[FACT].display.value == NEW


def test_filters_and_invalid_fact_do_not_guess_or_create_decisions(workspace):
    service, tools, registry, store = runtime(workspace)
    proposal = propose(tools)
    assert service.list_review(c.ReviewListRequest(part_id=PART, drawing_id="D-001", tab="corrections",
        kind="correction", method="parsed", review_status="not_reviewed"))[0].id == proposal.item.id
    assert service.list_review(c.ReviewListRequest(part_id="D-999/part")) == []
    assert service.list_review(c.ReviewListRequest(drawing_id="D-999")) == []
    assert service.list_review(c.ReviewListRequest(tab="needs_input")) == []
    assert service.list_review(c.ReviewListRequest(weight_state="Passed")) == []
    with pytest.raises(ReviewError):
        tools.propose_correction("D-999/drawing/title", NEW, REASON)
    with pytest.raises(ReviewError):
        propose(tools, reason="   ")
    with pytest.raises(ReviewError):
        act(service, c.ReviewItem.model_validate({**proposal.item.model_dump(), "id": "absent-review-item"}))
    assert store.history(FACT) == [proposal.decision]


def prepared_runtime(workspace, monkeypatch, *, kind="options", second_part=False, restart=False):
    """Real M11 producers with a scripted in-memory transport, never a CLI."""
    if not restart:
        import test_prepare_m1 as fixtures

        class PrepClock:
            @staticmethod
            def now(zone):
                return AT - timedelta(seconds=1)

        monkeypatch.setattr(fixtures.prep, "datetime", PrepClock)
        identity = "D-001" if kind in {"link", "scan"} else "D-013"
        drawings = [fixtures.drawing(workspace, identity, scan=kind == "scan", alternatives=kind == "options")]
        if second_part:
            drawings.append(fixtures.drawing(workspace, "D-025"))
        rows = [fixtures.row()]
        if kind == "link":
            rows += [fixtures.row("Bracket variant", datasheet="Variant.pdf", display="BOM-002"),
                     fixtures.row("Unrelated", datasheet="Unrelated.pdf", display="BOM-003")]
        paths = fixtures.inputs(workspace, drawings, rows, filename="Different.pdf" if kind == "link" else "Bracket.pdf")

        def customize(request, definition, fields):
            if isinstance(request, c.DeterminationRequest) and definition.job.startswith("vision.template."):
                if kind == "options" and identity == "D-013" and request.job.job.endswith("D-013"):
                    fields.update(fixtures.printed_thickness_fields(request.job, definition))
                elif kind in {"unknown", "all_unknown"}:
                    name = f"{identity}/template/thickness"
                    if kind == "all_unknown":
                        for target in list(fields):
                            if not target.endswith("/proofs"):
                                fields[target] = fixtures.field(refs=[f"{identity}/drawing/page/1"])
                    else:
                        fields[name] = fixtures.field(refs=[f"{identity}/drawing/page/1"])
                    ledger = fields[f"{identity}/template/proofs"]["value"]["entries"]
                    ledger[:] = [] if kind == "all_unknown" else [entry for entry in ledger if entry["field"] != name]
            elif kind == "unresolved_mapping" and not isinstance(request, c.DeterminationRequest) and "/material/" in request.job.job:
                for name, verdict in list(fields.items()):
                    fields[name] = verdict.model_copy(update={"verdict": "unsure"})

        saved = fixtures.execute(workspace, fixtures.Scripted(workspace, monkeypatch, customize=customize), paths)
        payload = saved.model_dump(mode="json")
        payload["batch"].update(MARKERS)
        prepared = PreparedKnowledge.model_validate(payload)
        (workspace / "prepared.json").write_text(prepared.model_dump_json(), encoding="utf-8")
    store = DecisionStore(workspace / "decisions", allow_synthetic=True)
    registry = RecordRegistry.from_paths(prepared_path=workspace / "prepared.json", inputs_path=workspace / "inputs.json",
        records_path=workspace / "generated/records.json", decisions=store)
    service, tools = compose(registry, store)
    return service, tools, registry, store


def prepared_item(service, kind, suffix=None, *, prefix=None):
    declared = {item.id for item in service.registry.document.prepared.review_items}
    return next(item for item in service.list_review(c.ReviewListRequest(status="all"))
                if item.id in declared and item.kind == kind
                and (suffix is None or item.applies_to.endswith(suffix))
                and (prefix is None or item.applies_to.startswith(prefix)))


def submit(service, item, action, *, value=None, source_ids=(), note="Synthetic M1 action, not an actual human review."):
    body = dict(action=action, note=note, source_ids=list(source_ids))
    if action in {"set_value", "choose_option"}:
        body["value"] = value
    return service.review_action(item.id, c.ReviewActionRequest(**body), HUMAN)


@pytest.mark.parametrize("action", ["accept", "set_value", "reject"])
def test_prepared_link_actions_refresh_membership_and_preserve_provenance(workspace, monkeypatch, action):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="link")
    original_bytes = (workspace / "prepared.json").read_bytes()
    item = prepared_item(service, "link")
    before = registry.document.prepared
    rows = [option["bom_rows"][0] for option in item.options]
    assert len(rows) == 2 and store.history(PART) == []
    calls = []

    def no_geometry(*args):
        calls.append(args)
        raise AssertionError("Link actions must not rebuild unrelated geometry")

    service.dependencies = replace(service.dependencies, rebuild_model=no_geometry)
    value = {"drawing_id": "D-001", "bom_rows": [rows[1]]}
    result = submit(service, item, action, value=value)
    assert result.item.status == ("rejected" if action == "reject" else "accepted")
    assert [event.status for event in result.decisions] == ["pending", result.item.status]
    assert all(event.applies_to == PART for event in result.decisions)
    assert result.decisions[-1].by == HUMAN and result.decisions[-1].at == AT
    assert result.decisions[-1].based_on == result.decisions[0].based_on
    assert result.decisions[-1].ai_answers == item.ai_answers and not calls
    record = registry.part_for(PART)
    if action == "reject":
        assert record.bom == [] and record.link.review.status == c.ReviewStatus.HUMAN_REJECTED
    else:
        expected = [rows[1]] if action == "set_value" else item.proposed_value["bom_rows"]
        assert record.link.bom_rows == expected and [row.name for row in record.bom] == expected
        assert record.link.review.status == c.ReviewStatus.HUMAN_CONFIRMED
        assert result.refresh.part_ids == [PART]
        assert all(row.name not in expected or row_part.id == PART for row_part in registry.records for row in row_part.bom)
    assert registry.document.prepared == before
    assert (workspace / "prepared.json").read_bytes() == original_bytes
    restarted, _, again, journal = prepared_runtime(workspace, monkeypatch, restart=True)
    assert prepared_item(restarted, "link").status == result.item.status
    assert again.part_for(PART).link == record.link and journal.history(PART) == result.decisions
    with pytest.raises(ReviewError) as error:
        submit(restarted, item, "reject")
    assert error.value.status_code == 409


@pytest.mark.parametrize("value", [
    {"drawing_id": "D-999", "bom_rows": []}, {"drawing_id": "D-001", "bom_rows": [True]},
    {"drawing_id": "D-001", "bom_rows": ["BOM:cell/unrelated"]},
    {"drawing_id": "D-001", "bom_rows": ["missing"]}, "BOM:cell/bracket", 1,
])
def test_invalid_or_unrelated_link_values_never_enter_the_journal(workspace, monkeypatch, value):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="link")
    item = prepared_item(service, "link")
    before = registry.part_for(PART)
    with pytest.raises(ReviewError) as error:
        submit(service, item, "set_value", value=value)
    assert error.value.status_code == 400
    assert store.history(PART) == [] and registry.part_for(PART) == before


def test_printed_choice_rebuilds_only_affected_model_and_keeps_original_options(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, second_part=True)
    item = prepared_item(service, "template_field", "D-013/template/thickness")
    assert item.applies_to == "D-013/template/thickness" and item.options == [7, 5]
    assert item.allowed_actions == [c.ReviewAction.REJECT, c.ReviewAction.CHOOSE_OPTION]
    original = registry.document.prepared.model_dump()
    built = []
    affected = []

    def rebuild_records(part_ids=None):
        affected.append(list(part_ids) if part_ids is not None else None)
        return registry(part_ids)

    def rebuild_model(record, template):
        built.append((record.id, template.model_copy(deep=True)))
        assert template.thickness.value == 7
        return c.ModelStatus(state="available", built_at=AT,
            built_template_sha256=c.contract_digest(template), current_template_sha256=c.contract_digest(template),
            examples=[c.ModelExample(id="A", glb="synthetic-only/rebuilt.glb")])

    service.dependencies = replace(service.dependencies, rebuild_records=rebuild_records, rebuild_model=rebuild_model)
    result = submit(service, item, "choose_option", value=7)
    effective = registry.load_template("D-013/part")
    assert effective.thickness.value == 7 and effective.thickness.method == c.Method.HUMAN_DECISION
    assert effective.thickness.review.by == HUMAN and effective.thickness.evidence.number_ids == ["D-013/drawing/n/7@1"]
    assert len(built) == 1 and built[0][0] == "D-013/part" and affected[-1] == ["D-013/part"]
    assert result.refresh.facts[item.applies_to].display.value == 7
    assert tools.get_facts("D-013/part").facts[item.applies_to].display.value == 7
    assert registry.part_for("D-013/part").model == result.refresh.models["D-013/part"]
    assert registry.part_for("D-025/part").model.state == "missing"
    assert registry.document.prepared.model_dump() == original
    restarted, future_tools, again, journal = prepared_runtime(workspace, monkeypatch, restart=True)
    assert again.load_template("D-013/part").thickness.value == 7
    assert again.document.prepared.templates["D-013"].thickness.state == "options"
    assert future_tools.get_facts("D-013/part").facts[item.applies_to].display.value == 7
    assert again.part_for("D-013/part").model.state == "available"
    assert journal.history(item.applies_to) == result.decisions
    assert prepared_item(restarted, "template_field", "D-013/template/thickness").status == "accepted"


@pytest.mark.parametrize("value", [True, "7", 9, {"value": 7}])
def test_wrong_printed_option_type_or_value_is_refused(workspace, monkeypatch, value):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch)
    item = prepared_item(service, "template_field", "/thickness")
    with pytest.raises(ReviewError):
        submit(service, item, "choose_option", value=value)
    assert store.history(item.applies_to) == []
    assert registry.load_template("D-013/part").thickness.state == "options"


def test_unknown_numeric_set_value_is_evidenced_and_survives_restart(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="unknown")
    item = prepared_item(service, "template_field", "/thickness")
    original = registry.document.prepared.templates["D-013"].model_dump()
    assert registry.load_template("D-013/part").thickness.state == "unknown"
    result = submit(service, item, "set_value", value=5, source_ids=["D-013/drawing/n/5@1"])
    field = registry.load_template("D-013/part").thickness
    assert field.value == 5 and field.evidence.number_ids == ["D-013/drawing/n/5@1"]
    assert result.refresh.facts[item.applies_to].display.value == 5
    assert result.refresh.models["D-013/part"].state == "missing"
    assert any("builder unavailable" in warning for warning in result.refresh.warnings)
    assert registry.document.prepared.templates["D-013"].model_dump() == original
    _, future_tools, again, _ = prepared_runtime(workspace, monkeypatch, restart=True)
    assert future_tools.get_facts("D-013/part").facts[item.applies_to].display.value == 5
    assert again.load_template("D-013/part").thickness.review.by == HUMAN


@pytest.mark.parametrize("value,refs", [(True, ["D-013/drawing/n/5@1"]), ("5", ["D-013/drawing/n/5@1"]),
    (99, ["D-013/drawing/n/5@1"]), (5, []), (5, ["D-999/drawing/n/5@1"])])
def test_untyped_unsupported_or_foreign_numeric_evidence_is_refused(workspace, monkeypatch, value, refs):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="unknown")
    item = prepared_item(service, "template_field", "/thickness")
    with pytest.raises(ReviewError):
        submit(service, item, "set_value", value=value, source_ids=refs)
    assert store.history(item.applies_to) == []
    assert registry.load_template("D-013/part").thickness.state == "unknown"


def test_no_usable_template_can_be_filled_without_inventing_initial_geometry(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="all_unknown")
    assert registry.document.prepared.templates == {}
    template = registry.load_template("D-013/part")
    assert template.outline.state == template.thickness.state == "unknown"
    item = prepared_item(service, "template_field", "/outline")
    result = submit(service, item, "set_value", value={"type": "rectangle", "length": 12, "width": 7},
        source_ids=["D-013/drawing/page/1", "D-013/drawing/n/12@1", "D-013/drawing/n/7@1"])
    effective = registry.load_template("D-013/part")
    assert effective.outline.value.length.value == 12 and effective.outline.value.width.value == 7
    assert effective.thickness.state == "unknown" and registry.document.prepared.templates == {}
    assert result.item.status == "accepted" and result.refresh.models["D-013/part"].state == "missing"


@pytest.mark.parametrize("action", ["accept", "set_value", "reject"])
def test_scan_actions_keep_raw_original_and_rounds_and_refresh_answers(workspace, monkeypatch, action):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="scan")
    item = prepared_item(service, "scan_reading", "/title")
    original = registry.document.prepared.drawings[0].fields["title"].model_dump()
    assert original["original"] is None
    result = submit(service, item, action, value="Synthetic explicit scan reading")
    field = registry.part_for(PART).drawing.fields["title"]
    fact = tools.get_facts(PART).facts[item.applies_to]
    assert field.original is None and field.value == original["value"] and field.provenance.model_dump() == original["provenance"]
    assert registry.document.prepared.drawings[0].fields["title"].model_dump() == original
    if action == "reject":
        assert fact.display.state == "undetermined" and field.review.status == c.ReviewStatus.HUMAN_REJECTED
    else:
        assert fact.display.value == ("Synthetic explicit scan reading" if action == "set_value" else item.proposed_value)
        assert field.review.status == c.ReviewStatus.HUMAN_CONFIRMED
    assert result.decisions[-1].note and result.decisions[-1].ai_answers == item.ai_answers
    restarted, future_tools, again, _ = prepared_runtime(workspace, monkeypatch, restart=True)
    assert prepared_item(restarted, "scan_reading", "/title").status == result.item.status
    assert future_tools.get_facts(PART).facts[item.applies_to].display == fact.display


@pytest.mark.parametrize("action", ["approve_mapping", "reject"])
def test_mapping_approval_or_rejection_controls_future_resolution(workspace, monkeypatch, action):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="mapping")
    item = prepared_item(service, "name_mapping", prefix="names/material/")
    original = registry.document.prepared.model_dump()
    assert tools.get_facts("D-013/part").facts["D-013/drawing/material"].display.state == "undetermined"
    result = submit(service, item, action)
    if action == "approve_mapping":
        assert any(mapping.name == item.applies_to for mapping in registry.approved_mappings)
        assert tools.get_facts("D-013/part").facts["D-013/drawing/material"].display.value == "Alloy X"
    else:
        assert registry.approved_mappings == []
        assert tools.get_facts("D-013/part").facts["D-013/drawing/material"].display.state == "undetermined"
    assert result.decisions[-1].type == c.DecisionType.NAME_MAPPING
    assert registry.document.prepared.model_dump() == original
    restarted, future_tools, again, _ = prepared_runtime(workspace, monkeypatch, restart=True)
    assert prepared_item(restarted, "name_mapping", prefix="names/material/").status == result.item.status
    assert again.approved_mappings == registry.approved_mappings


def test_template_reject_is_unresolved_and_builder_failure_keeps_durable_choice(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch)
    thickness = prepared_item(service, "template_field", "/thickness")

    def failing_builder(*args):
        raise RuntimeError("Synthetic builder failure")

    service.dependencies = replace(service.dependencies, rebuild_model=failing_builder)
    accepted = submit(service, thickness, "choose_option", value=5)
    assert accepted.item.status == "accepted" and store.latest_accepted(thickness.applies_to)
    assert accepted.refresh.models["D-013/part"].state == "missing"
    assert any("rebuild failed" in warning for warning in accepted.refresh.warnings)
    outline = prepared_item(service, "template_field", "/outline")
    rejected = submit(service, outline, "reject")
    assert rejected.item.status == "rejected"
    assert registry.load_template("D-013/part").outline.state == "unknown"
    assert tools.get_facts("D-013/part").facts[outline.applies_to].display.state == "undetermined"
    assert registry.document.prepared.templates["D-013"].outline.state == "known"


def test_prepared_changed_source_and_append_failure_do_not_invent_approval(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch)
    item = prepared_item(service, "template_field", "/thickness")
    original = registry.load_template("D-013/part").model_dump()

    def failed_append(decision):
        raise OSError("Synthetic journal write failure")

    service.dependencies = replace(service.dependencies, append_decision=failed_append)
    with pytest.raises(ReviewError) as error:
        submit(service, item, "choose_option", value=7)
    assert error.value.status_code == 500
    assert [event.status for event in store.history(item.applies_to)] == ["pending"]
    assert registry.load_template("D-013/part").model_dump() == original
    assert prepared_item(service, "template_field", "/thickness").status == "pending"
    payload = json.loads((workspace / "prepared.json").read_text("utf-8"))
    saved_item = next(saved for saved in payload["review_items"] if saved["id"] == item.id)
    saved_item["source_hashes"]["drawing"] = "f" * 64
    (workspace / "prepared.json").write_text(json.dumps(payload), encoding="utf-8")
    restarted, future_tools, again, journal = prepared_runtime(workspace, monkeypatch, restart=True)
    changed = prepared_item(restarted, "template_field", "/thickness")
    assert changed.status == "source_changed" and changed.allowed_actions == []
    with pytest.raises(ReviewError) as error:
        submit(restarted, changed, "choose_option", value=7)
    assert error.value.status_code == 409
    assert all(event.status == "pending" for event in journal.history(item.applies_to))


def test_unresolved_mapping_accepts_only_an_explicit_recorded_relationship(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="unresolved_mapping")
    item = prepared_item(service, "name_mapping", prefix="names/material/")
    original = registry.document.prepared.model_dump()
    assert item.mapping is None and c.ReviewAction.SET_VALUE in item.allowed_actions
    for value in [{"relationship": "same", "to_name": "Unrecorded target"},
                  {"relationship": "invented", "to_name": "Metal X"}, True]:
        with pytest.raises(ReviewError):
            submit(service, item, "set_value", value=value)
        assert store.history(item.applies_to) == []
    result = submit(service, item, "set_value", value={"relationship": "same", "to_name": "Metal X"})
    assert result.item.status == "accepted"
    assert any(mapping.name == item.applies_to for mapping in registry.approved_mappings)
    assert tools.get_facts("D-013/part").facts["D-013/drawing/material"].display.value == "Alloy X"
    assert registry.document.prepared.model_dump() == original
    _, _, again, _ = prepared_runtime(workspace, monkeypatch, restart=True)
    assert again.approved_mappings == registry.approved_mappings


def test_mapping_and_scan_actions_cannot_replace_saved_values_with_wrong_types(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="scan")
    item = prepared_item(service, "scan_reading", "/title")
    for value in [True, 7, {"value": "Synthetic bypass"}, "   "]:
        with pytest.raises(ReviewError):
            submit(service, item, "set_value", value=value)
        assert store.history(item.applies_to) == []
    mapping = prepared_item(service, "name_mapping")
    with pytest.raises(ReviewError):
        service.review_action(mapping.id, c.ReviewActionRequest(action="approve_mapping",
            value={"relationship": "different", "to_name": "Unrecorded target"}), HUMAN)
    assert store.history(mapping.applies_to) == []
    with pytest.raises(ReviewError) as error:
        service.review_action("review/D-001/template/invented-target", c.ReviewActionRequest(action="set_value", value=5), HUMAN)
    assert error.value.status_code == 404


def test_current_prepared_page_bytes_are_checked_before_any_review_append(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch)
    item = prepared_item(service, "template_field", "/thickness")
    image = workspace / "images/D-013-p1.png"
    image.write_bytes(image.read_bytes() + b"Synthetic changed original page bytes")
    with pytest.raises(ReviewError) as error:
        submit(service, item, "choose_option", value=7)
    assert error.value.status_code == 409
    assert store.history(item.applies_to) == []


def test_explicit_supported_numeric_derivation_is_retained_without_executing_code(workspace, monkeypatch):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="unknown")
    item = prepared_item(service, "template_field", "/thickness")
    number = "D-013/drawing/n/5@1"
    for expression in ["n0 + 7", "__import__('os').getcwd()", "n0 / 0"]:
        with pytest.raises(ReviewError):
            submit(service, item, "set_value", value={"value": 2.5, "evidence": {
                "number_ids": [number], "derivation": {"kind": "arithmetic", "expression": expression, "inputs": [number]}}})
        assert store.history(item.applies_to) == []
    result = submit(service, item, "set_value", value={"value": 2.5, "evidence": {
        "number_ids": [number], "derivation": {"kind": "arithmetic", "expression": "n0 / 2", "inputs": [number]}}})
    field = registry.load_template("D-013/part").thickness
    assert result.item.status == "accepted" and field.value == 2.5
    assert field.evidence.derivation.expression == "n0 / 2" and field.unit == "mm"
    assert registry.document.prepared.templates["D-013"].thickness.state == "unknown"


@pytest.mark.parametrize("action", ["accept", "reject", "set_value"])
def test_prepared_feature_absence_can_be_reviewed_or_replaced_without_overwriting_candidate(workspace, monkeypatch, action):
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch)
    item = prepared_item(service, "template_field", "/feature-01")
    assert item.proposed_value == {"kind": "absent"}
    original = registry.document.prepared.model_dump()
    feature = {"kind": "hole", "hole_type": "plain", "face": "top", "through": True,
               "position": {"x": 7, "y": 7}, "diameter": 5}
    result = submit(service, item, action, value=feature,
        source_ids=["D-013/drawing/page/1", "D-013/drawing/n/7@1", "D-013/drawing/n/5@1"] if action == "set_value" else ())
    fields = {field.name: field for field in registry.template_fields("D-013/part")}
    field = fields[item.applies_to]
    if action == "accept":
        assert field.value == {"kind": "absent"} and field.review.by == HUMAN
        assert not any(field.name == item.applies_to for field in registry.load_template("D-013/part").features)
    elif action == "reject":
        assert field.state == "unknown" and field.review.status == c.ReviewStatus.HUMAN_REJECTED
    else:
        assert field.value.diameter.value == 5 and field.value.position.x.value == 7
        assert field.review.by == HUMAN
    assert result.item.status == ("rejected" if action == "reject" else "accepted")
    assert registry.document.prepared.model_dump() == original
    _, _, again, _ = prepared_runtime(workspace, monkeypatch, restart=True)
    future = {field.name: field for field in again.template_fields("D-013/part")}[item.applies_to]
    assert future.model_dump() == field.model_dump()


def test_template_snapshot_keeps_original_input_after_human_projection(workspace, monkeypatch):
    # M1 templates use clean drawings. Exercise the supported human overlay,
    # rather than asking M11 to reconstruct a degraded drawing it must refuse.
    service, tools, registry, store = prepared_runtime(workspace, monkeypatch, kind="clean_template")
    raw = c.DrawingEvidence.model_validate(json.loads((workspace / "inputs.json").read_text("utf-8"))["drawings"][0])
    proposal = tools.propose_correction("D-013/drawing/title", "SYNTHETIC reviewed title",
                                        "Synthetic explicit source-bound correction test.")
    act(service, proposal.item)
    effective_source = registry.part_for("D-013/part").drawing
    template = registry.load_template("D-013/part")
    assert c.contract_digest(raw) != c.contract_digest(effective_source)
    assert template.source_sha256 == c.contract_digest(raw)
    assert raw.source_sha256 == effective_source.source_sha256
    item = prepared_item(service, "template_field", "D-013/template/thickness")
    result = submit(service, item, "accept")
    assert result.item.status == "accepted" and registry.load_template("D-013/part").thickness.value == 5
    assert registry.document.prepared.drawings[0].model_dump() == raw.model_dump()
    assert effective_source.fields["title"].correction.corrected == "SYNTHETIC reviewed title"
