"""M1 decision behavior using isolated synthetic histories; no live calls.

Run from testing/: python -B -m pytest -q tests/test_decisions_m1.py
All execution data stays below testing/ even without a pytest basetemp option.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend.contracts import (  # noqa: E402
    Decision, DecisionJournal, DecisionType, DrawingField, ReviewStatus,
    bom_fact_name, drawing_fact_name, drawing_part_name, mapping_name,
    template_fact_name,
)
from backend.loader.decisions import DecisionStore, JournalError, effective_value  # noqa: E402


NAME = drawing_fact_name("D-013", "title")
HUMAN = "Synthetic human reviewer (test only)"
PROPOSER = "Synthetic AI proposer (test only)"
AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
NOTE = "Synthetic decisions for deterministic tests; no actual engineering approval."
HASHES = {"D-013": "1" * 64, "synthetic/evidence.txt": "2" * 64}


@pytest.fixture
def workspace():
    directory = ROOT / "testing/tmp/A07-decisions"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=directory) as temporary:
        yield Path(temporary)


def store_at(workspace):
    return DecisionStore(workspace / "decisions", allow_synthetic=True)


def event(identifier, *, status="pending", name=NAME, value="Synthetic revised title", **updates):
    payload = dict(
        fixture=True, synthetic=True, fixture_note=NOTE,
        decision_id=identifier, applies_to=name, type=DecisionType.CORRECTION,
        value=value, old_value="Synthetic original title", status=status,
        by=PROPOSER if status == "pending" else HUMAN, at=AT,
        based_on=dict(HASHES),
    )
    payload.update(updates)
    return Decision(**payload)


def field(value="Synthetic original title"):
    return DrawingField(
        name=NAME, original="  Synthetic original title  ", value=value,
        method="parsed", confidence="unsure", page=1, box=(1, 2, 30, 4),
        source_quality="degraded", note="Synthetic unreadable corner field",
    )


def test_contract_fixture_pending_review_persists_and_regenerated_evidence_stays_original(workspace):
    store = store_at(workspace)
    proposal = Decision.model_validate_json(
        (ROOT / "testing/fixtures/contracts/decision-pending.json").read_bytes()
    )
    store.append_decision(proposal)
    assert proposal.check_result.proves_correct is False
    assert store.latest_accepted(NAME) is None
    accepted = Decision.model_validate({
        **proposal.model_dump(mode="python"), "decision_id": "SYN-HUMAN-ACCEPT",
        "status": "accepted", "by": HUMAN, "at": AT + timedelta(minutes=1),
        "proposal_id": proposal.proposal_id, "supersedes": proposal.decision_id,
    })
    store.human_appender(HUMAN)(accepted)
    reviewed_hashes = dict(accepted.based_on)
    # Mutating caller-owned payloads or returned snapshots cannot rewrite disk.
    accepted.based_on["D-013"] = "f" * 64
    store.history(NAME)[1].value = "Mutated snapshot"
    reloaded = store_at(workspace)
    assert reloaded.history(NAME)[1].based_on == reviewed_hashes
    assert [d.status for d in reloaded.history(NAME)] == ["pending", "accepted"]

    generated = workspace / "generated"
    generated.mkdir()
    (generated / "records.json").write_text("[]", encoding="utf-8")
    (generated / "records.json").unlink()
    generated.rmdir()
    rerun = field(value="Synthetic new AI extraction")
    raw = rerun.model_dump()
    overlay = reloaded.apply_overlay(rerun)
    assert effective_value(overlay) == proposal.value
    assert overlay.value == "Synthetic new AI extraction"
    assert overlay.original == raw["original"]
    assert overlay.model_dump(exclude={"correction"}) == rerun.model_dump(exclude={"correction"})
    assert rerun.model_dump() == raw
    assert overlay.correction.original == proposal.old_value
    assert (overlay.correction.by, overlay.correction.at) == (HUMAN, AT + timedelta(minutes=1))
    assert reloaded.review_for(NAME).status == ReviewStatus.HUMAN_CONFIRMED
    assert reloaded.review_for(NAME).based_on == reviewed_hashes
    journal_path, = (workspace / "decisions").glob("*.json")
    journal = DecisionJournal.model_validate_json(journal_path.read_bytes())
    assert journal.item_id == drawing_part_name("D-013")
    assert journal.fixture and journal.synthetic
    assert journal.decisions[0] == proposal


def test_pending_rejection_and_supersession_keep_the_latest_accepted_value(workspace):
    store = store_at(workspace)
    human = store.human_appender(HUMAN)
    original = field()
    store.append_decision(event("P1", proposal_id="proposal-1"))
    assert effective_value(store.apply_overlay(original)) == original.value
    assert store.review_for(NAME) is None
    human(event("R1", status="rejected", proposal_id="proposal-1", supersedes="P1"))
    assert store.correction_for(NAME) is None
    assert store.apply_overlay(original) == original
    human(event("A1", status="accepted", value="First synthetic choice"))
    prefix = store.history(NAME)
    store.append_decision(event("P2", value="Unapproved alternative", proposal_id="proposal-2", supersedes="A1"))
    human(event("R2", status="rejected", value="Unapproved alternative", proposal_id="proposal-2", supersedes="P2"))
    assert effective_value(store.apply_overlay(original)) == "First synthetic choice"
    # Append order, not client timestamps, selects the latest accepted event.
    human(event("A2", status="accepted", value="Second synthetic choice", supersedes="A1", at=AT - timedelta(days=1)))
    history = store_at(workspace).history(NAME)
    assert history[:len(prefix)] == prefix
    assert [d.decision_id for d in history] == ["P1", "R1", "A1", "P2", "R2", "A2"]
    assert history[-1].supersedes == "A1"
    assert effective_value(store.apply_overlay(original)) == "Second synthetic choice"


def test_only_the_server_review_capability_can_append_human_actions(workspace):
    store = store_at(workspace)
    # A convincing reviewer string in an AI payload is not approval authority.
    for status in ("accepted", "rejected"):
        forged = event("forged-" + status, status=status)
        with pytest.raises(PermissionError):
            store.append_decision(forged)
        with pytest.raises(PermissionError):
            store.human_appender(HUMAN)(event("ai-" + status, status=status, by=PROPOSER))
    assert store.history(NAME) == []
    store.append_decision(event("P1"))
    with pytest.raises(ValueError):
        store.human_appender(" ")
    for kind in (DecisionType.CONFIRM, DecisionType.REJECT, DecisionType.APPROVE_DESIGN):
        with pytest.raises(JournalError, match="M1"):
            store.human_appender(HUMAN)(event("M2-" + kind, status="accepted", type=kind))
    # Payload mutations cannot bypass the frozen hash/time schema on append.
    invalid = event("invalid").model_copy(update={"based_on": {"D-013": "not-a-hash"}})
    with pytest.raises(ValueError):
        store.append_decision(invalid)
    with pytest.raises(ValueError):
        store.append_decision(event("invalid-clock").model_copy(update={"at": AT.replace(tzinfo=None)}))
    assert [d.status for d in store.history(NAME)] == ["pending"]
    assert store.latest_accepted(NAME) is None
    with pytest.raises(JournalError, match="isolated"):
        DecisionStore(workspace / "production-decisions").append_decision(event("fixture-leak"))
    with pytest.raises(JournalError, match="isolated"):
        DecisionStore(workspace / "decisions").history(NAME)


def test_hashes_and_event_ids_cannot_be_rebased_or_overwritten(workspace):
    store = store_at(workspace)
    proposal = event("P1", proposal_id="proposal-1")
    store.append_decision(proposal)
    path, = store.directory.glob("*.json")
    prefix = path.read_bytes()
    assert store.append_decision(proposal) == proposal
    assert path.read_bytes() == prefix
    with pytest.raises(JournalError, match="overwrite"):
        store.append_decision(event("P1", value="Replacement payload"))
    human = store.human_appender(HUMAN)
    changed_hashes = {**HASHES, "D-013": "3" * 64}
    with pytest.raises(JournalError, match="hashes"):
        human(event("A1", status="accepted", proposal_id="proposal-1", based_on=changed_hashes))
    with pytest.raises(JournalError, match="hashes"):
        human(event("A2", status="accepted", supersedes="P1", based_on=changed_hashes))
    with pytest.raises(JournalError, match="proposal"):
        human(event("A3", status="accepted", proposal_id="missing-proposal"))
    other = drawing_fact_name("D-013", "material")
    with pytest.raises(JournalError, match="same stable name"):
        human(event("A4", status="accepted", name=other, supersedes="P1"))
    assert path.read_bytes() == prefix
    assert store.history(NAME) == [proposal]


@pytest.mark.parametrize("name,kind,value", [
    (template_fact_name("D-025", "thickness"), DecisionType.SET_VALUE, 7.25),
    (template_fact_name("D-025", "width"), DecisionType.CHOOSE_OPTION, 19.5),
    (drawing_part_name("D-025"), DecisionType.LINK, ["BOM:synthetic-section/synthetic-part"]),
    (bom_fact_name("Synthetic Section", "Synthetic Part", "cost"), DecisionType.CORRECTION, None),
    (mapping_name("material", "Synthetic grade", "Synthetic family"), DecisionType.NAME_MAPPING, "kind_of"),
])
def test_exact_stable_names_support_each_m1_overlay_type(workspace, name, kind, value):
    store = store_at(workspace)
    pending = event("P1", name=name, type=kind, value=value, old_value="Synthetic baseline")
    store.append_decision(pending)
    assert store.latest_accepted(name) is None
    accepted = event("A1", name=name, type=kind, status="accepted", value=value, old_value="Synthetic baseline")
    store.human_appender(HUMAN)(accepted)
    assert store_at(workspace).latest_accepted(name) == accepted
    assert store.correction_for(name).corrected == value
    assert store.correction_for(name).original == "Synthetic baseline"
    if kind == DecisionType.CORRECTION:
        # An explicit human null is still an overlay, rather than no decision.
        corrected = field().model_copy(update={"name": name, "correction": store.correction_for(name)})
        assert effective_value(corrected) is None
    for invalid in ("BOM-028", "d-025/template/thickness", "D-025/drawing/Unnormalized Field", "D-025/drawing/title/../../outside"):
        with pytest.raises(JournalError):
            store.append_decision(event("invalid-name", name=invalid))


def test_durable_append_failure_preserves_prefix_and_corruption_is_explicit(workspace, monkeypatch):
    store = store_at(workspace)
    store.append_decision(event("P1"))
    path, = store.directory.glob("*.json")
    prefix = path.read_bytes()

    def unavailable_replace(source, target):
        raise OSError("Synthetic atomic-replace failure")

    with monkeypatch.context() as patch:
        patch.setattr("backend.loader.decisions.os.replace", unavailable_replace)
        with pytest.raises(OSError, match="atomic-replace"):
            store.human_appender(HUMAN)(event("A1", status="accepted"))
    assert path.read_bytes() == prefix
    assert list(store.directory.glob("*.tmp")) == []
    assert [d.decision_id for d in store_at(workspace).history(NAME)] == ["P1"]
    # Never interpret a damaged saved history as "no decisions" and regenerate.
    path.write_text('{"item_id":', encoding="utf-8")
    with pytest.raises(JournalError, match="Cannot load"):
        store_at(workspace).latest_accepted(NAME)
    with pytest.raises(JournalError, match="Cannot load"):
        store.append_decision(event("P2"))
    assert path.read_text(encoding="utf-8") == '{"item_id":'


def test_separate_writers_keep_both_events_and_unrelated_names_do_not_overlay(workspace):
    names = [NAME, drawing_fact_name("D-013", "material")]

    def append(index):
        return store_at(workspace).append_decision(event(f"P{index}", name=names[index]))

    with ThreadPoolExecutor(max_workers=2) as pool:
        written = list(pool.map(append, range(2)))
    store = store_at(workspace)
    assert {d.decision_id for d in store.journal(NAME).decisions} == {"P0", "P1"}
    store.human_appender(HUMAN)(event("A1", name=names[1], status="accepted", value={"synthetic": [1, 2]}))
    assert store.latest_accepted(NAME) is None
    assert store.latest_accepted(names[1]).value == {"synthetic": [1, 2]}
    snapshot = store.latest_accepted(names[1])
    snapshot.value["synthetic"].append(3)
    assert store.latest_accepted(names[1]).value == {"synthetic": [1, 2]}
    assert all(d.based_on == HASHES for d in written)
    # Histories are ordinary frozen JSON payloads, not a parallel event schema.
    path, = store.directory.glob("*.json")
    assert set(json.loads(path.read_bytes())) == set(DecisionJournal.model_fields)
