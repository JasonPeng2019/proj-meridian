"""Focused M16 correction tests for queued CI; no real human/AI/CAD actions.

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

from test_source_runtime import ROOT, source_bundle
from backend import contracts as c
from backend.app import review as review_module
from backend.app.review import ReviewError, create_review_service
from backend.app.tools import FactTools
from backend.loader.decisions import DecisionStore
from backend.loader.records import RecordRegistry, RecordsError, read_records


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
