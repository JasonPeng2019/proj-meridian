"""M1 append-only decision histories, independent of generated evidence.

Pass the configured ``decisions/`` directory to DecisionStore. AI/preparation
code may use append_decision, which accepts pending proposals only. Trusted
server composition supplies human_appender(settings.reviewer_name) to the frozen
ReviewDependencies.append_decision boundary; never expose that capability to
chat/prep or take its reviewer name from a request. M16 supplies the server time.

Files contain the frozen DecisionJournal/Decision payloads, grouped by stable
part name (or by mapping/passage name), with hashed filenames for portability.
Appending atomically replaces a journal with its complete retained prefix plus
one event. A directory lock serializes writers, including separate processes.
Reads always reload disk, so regeneration and other store instances see reviews.

apply_overlay attaches a frozen Correction without editing extracted value,
original, method, confidence, or AI provenance. Consumers use effective_value
for the accepted value, or latest_accepted for links/templates/mappings. Reviewed
hashes are never refreshed here. M2 evidence invalidation/reapproval is deferred.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import TypeVar

from ..contracts import (
    Correction, Decision, DecisionAppender, DecisionJournal, DecisionType,
    EvidenceField, JsonValue, ReviewState, ReviewStatus, bom_fact_name,
    bom_part_name, bom_row_name, drawing_fact_name, drawing_number_name,
    drawing_part_name, mapping_name, readme_name, template_fact_name,
    normalize_component, ReviewItem, contract_digest,
)


M1_TYPES = frozenset({
    DecisionType.CORRECTION, DecisionType.LINK, DecisionType.SET_VALUE,
    DecisionType.CHOOSE_OPTION, DecisionType.NAME_MAPPING,
})
FieldT = TypeVar("FieldT", bound=EvidenceField)


class JournalError(ValueError):
    """Invalid or conflicting history; existing decisions must not be discarded."""


def _item_id(name: str) -> str:
    """Check canonical frozen names without rewriting a caller's identity."""
    if not isinstance(name, str):
        raise JournalError("A decision needs a frozen stable name")
    parts = name.split("/")
    try:
        if parts[0].startswith("D-"):
            owner = drawing_part_name(parts[0])
            canonical = owner
            if len(parts) >= 3 and parts[1] == "template":
                # Native templates give nested scalar fields stable path names.
                canonical = "/".join([parts[0], "template", *[normalize_component(part) for part in parts[2:]]])
            elif len(parts) == 3 and parts[1] == "drawing":
                builder = drawing_fact_name if parts[1] == "drawing" else template_fact_name
                canonical = builder(parts[0], parts[2])
            elif len(parts) == 4 and parts[1:3] == ["drawing", "n"]:
                token, occurrence = parts[3].rsplit("@", 1)
                canonical = drawing_number_name(parts[0], token, int(occurrence))
        elif parts[0].startswith("BOM:") and len(parts) in {2, 3}:
            section, part = parts[0][4:], parts[1]
            owner = bom_part_name(section, part)
            canonical = (bom_row_name(section, part) if len(parts) == 2
                         else bom_fact_name(section, part, parts[2]))
        elif len(parts) == 3 and parts[0] == "names" and parts[1] in {"section", "material"}:
            source, target = parts[2].split(" -> ")
            canonical = owner = mapping_name(parts[1], source, target)
        elif len(parts) == 3 and parts[0] == "README" and re.fullmatch(r"p[1-9][0-9]*", parts[2]):
            canonical = owner = readme_name(parts[1], int(parts[2][1:]))
        else:
            raise ValueError("Unknown stable-name namespace")
        if canonical == name:
            return owner
    except (ValueError, IndexError) as error:
        raise JournalError(f"Invalid frozen stable name: {name!r}") from error
    raise JournalError(f"Noncanonical frozen stable name: {name!r}")


def _check_references(event: Decision, earlier: list[Decision]) -> None:
    if event.supersedes is not None:
        superseded = next((d for d in earlier if d.decision_id == event.supersedes), None)
        if superseded is None or superseded.applies_to != event.applies_to:
            raise JournalError("supersedes must name an earlier decision on the same stable name")
        if event.status != "pending" and superseded.status == "pending":
            if event.based_on != superseded.based_on:
                raise JournalError("A review must retain the proposal's exact evidence hashes")
    if event.proposal_id is None:
        return
    if not event.proposal_id.strip():
        raise JournalError("proposal_id cannot be blank")
    proposals = [d for d in earlier if d.status == "pending"
                 and (d.proposal_id or d.decision_id) == event.proposal_id]
    if event.status == "pending":
        if proposals:
            raise JournalError("A proposal ID already identifies a saved pending proposal")
    elif (len(proposals) != 1 or proposals[0].applies_to != event.applies_to
          or proposals[0].based_on != event.based_on):
        raise JournalError("A review must reference its saved proposal and exact evidence hashes")
    elif any(saved.status != "pending" and saved.proposal_id == event.proposal_id for saved in earlier):
        raise JournalError("This proposal already has a terminal review decision")


def prepared_proposal_id(item: ReviewItem) -> str:
    """Same immutable prepared item/source snapshot in M12 and M16, no I/O."""
    return item.proposal_id or "prepared-" + contract_digest({
        "id": item.id, "kind": item.kind, "applies_to": item.applies_to,
        "source_hashes": item.source_hashes,
    })


class DecisionStore:
    def __init__(self, directory: str | Path, *, allow_synthetic: bool = False):
        self.directory = Path(directory).resolve()
        self.allow_synthetic = allow_synthetic

    def _path(self, item_id: str) -> Path:
        return self.directory / (hashlib.sha256(item_id.encode("utf-8")).hexdigest() + ".json")

    def _check_event(self, event: Decision) -> str:
        owner = _item_id(event.applies_to)
        if event.type not in M1_TYPES:
            raise JournalError("This store implements M1 decision types only")
        if not event.by.strip() or not event.decision_id.strip():
            raise JournalError("Decisions need an actor and a nonblank decision ID")
        if event.synthetic and not self.allow_synthetic:
            raise JournalError("Synthetic decisions require an explicitly isolated test store")
        return owner

    def _load(self) -> dict[str, DecisionJournal]:
        journals: dict[str, DecisionJournal] = {}
        seen: set[str] = set()
        for path in sorted(self.directory.glob("*.json")):
            try:
                journal = DecisionJournal.model_validate_json(path.read_bytes())
                if _item_id(journal.item_id) != journal.item_id or path != self._path(journal.item_id):
                    raise JournalError("Journal identity does not match its filename/owner")
                earlier: list[Decision] = []
                for event in journal.decisions:
                    if self._check_event(event) != journal.item_id or event.synthetic != journal.synthetic:
                        raise JournalError("A journal must retain its owner and fixture markers")
                    if event.decision_id in seen:
                        raise JournalError("Duplicate decision ID in stored histories")
                    _check_references(event, earlier)
                    earlier.append(event)
                    seen.add(event.decision_id)
                journals[journal.item_id] = journal
            except (OSError, ValueError) as error:
                raise JournalError(f"Cannot load decision journal {path.name}: {error}") from error
        return journals

    @contextmanager
    def _writer(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        # Persistent lockfile: deleting it after release would let writers lock
        # different inodes. A lock is released by the OS if the writer exits.
        with (self.directory / ".journal.lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _save(self, journal: DecisionJournal) -> None:
        payload = json.dumps(journal.model_dump(mode="json"), indent=2,
                             sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        descriptor, name = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(journal.item_id))
            if os.name != "nt":
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def _append(self, decision: Decision, reviewer: str | None) -> Decision:
        # Revalidate even model_copy/assignment mutations; detach mutable values
        # and hashes before waiting for the writer lock or returning the event.
        event = Decision.model_validate(decision.model_dump(mode="python"))
        owner = self._check_event(event)
        if event.status != "pending" and (reviewer is None or event.by != reviewer):
            raise PermissionError("Accepted/rejected events require the configured human review appender")
        with self._writer():
            journals = self._load()
            for journal in journals.values():
                for saved in journal.decisions:
                    if saved.decision_id == event.decision_id:
                        if saved != event:
                            raise JournalError("A decision ID cannot overwrite a saved event")
                        return saved.model_copy(deep=True)  # Identical retries are idempotent.
            journal = journals.get(owner) or DecisionJournal(
                item_id=owner, decisions=[], fixture=event.fixture,
                synthetic=event.synthetic, fixture_note=event.fixture_note,
            )
            if journal.synthetic != event.synthetic:
                raise JournalError("Do not mix synthetic and real decisions in one journal")
            _check_references(event, journal.decisions)
            journal.decisions.append(event)
            self._save(journal)
        return event.model_copy(deep=True)

    def append_decision(self, decision: Decision) -> Decision:
        """Untrusted proposal boundary: an AI cannot grant itself human review."""
        return self._append(decision, reviewer=None)

    def human_appender(self, reviewer: str) -> DecisionAppender:
        """Trusted server-only capability matching the frozen appender signature.

        The reviewer comes from server settings; the Decision.by on a review
        must match it. This is an injection boundary, not a login/auth system.
        Historical reviewers remain intact when the configured reviewer changes.
        """
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Use the reviewer name from server settings")

        def append(decision: Decision) -> Decision:
            return self._append(decision, reviewer=reviewer)

        return append

    def journal(self, name: str) -> DecisionJournal:
        """Return the complete owning history as a freshly loaded frozen payload."""
        owner = _item_id(name)
        return self._load().get(owner) or DecisionJournal(item_id=owner, decisions=[])

    def history(self, name: str) -> list[Decision]:
        """Exact-name events in append order; timestamps never reorder decisions."""
        return [event for event in self.journal(name).decisions if event.applies_to == name]

    def latest_accepted(self, name: str) -> Decision | None:
        """Pending/rejected events never resolve or revoke a previously accepted value."""
        return next((event for event in reversed(self.history(name)) if event.status == "accepted"), None)

    def review_for(self, name: str) -> ReviewState | None:
        event = self.latest_accepted(name)
        return None if event is None else ReviewState(
            status=ReviewStatus.HUMAN_CONFIRMED, by=event.by, at=event.at,
            based_on=event.based_on, decision_id=event.decision_id,
        )

    def correction_for(self, name: str) -> Correction | None:
        event = self.latest_accepted(name)
        return None if event is None else Correction(
            original=event.old_value, corrected=event.value,
            by=event.by, at=event.at, decision_id=event.decision_id,
        )

    def apply_overlay(self, field: FieldT) -> FieldT:
        """Keep the evidence unchanged and attach only its effective correction."""
        return field.model_copy(deep=True, update={"correction": self.correction_for(field.name)})


def effective_value(field: EvidenceField) -> JsonValue:
    """Expose the overlay value separately, including an explicitly accepted null."""
    return deepcopy(field.correction.corrected if field.correction is not None else field.value)
