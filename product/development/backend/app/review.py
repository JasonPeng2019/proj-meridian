"""M16 correction proposals and explicit Debug review actions.

M03 supplies one RecordRegistry, its DecisionStore, and frozen ReviewDependencies.
Give FactTools only ``service.propose_correction``; the human appender stays on
this side of that boundary. There is no review cache or second decision journal.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from threading import RLock
import unicodedata
from uuid import uuid4

from .. import contracts as c
from ..loader.decisions import DecisionStore, JournalError
from ..loader.records import RecordRegistry, RecordsError


class ReviewError(ValueError):
    """Safe frozen API envelope for the composing router."""

    def __init__(self, code: c.ErrorCode, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        self.response = c.ErrorResponse(error=c.APIError(code=code, message=message))


def _markers(payload: c.Payload) -> dict:
    return dict(fixture=payload.fixture, synthetic=payload.synthetic,
                fixture_note=payload.fixture_note)


def _normal(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class ReviewService:
    def __init__(self, *, registry: RecordRegistry, decisions: DecisionStore,
                 dependencies: c.ReviewDependencies):
        self.registry = registry
        self.decisions = decisions
        self.dependencies = dependencies
        self._lock = RLock()

    def _rebuild(self, part_ids=None) -> list[c.PartRecord]:
        try:
            return self.dependencies.rebuild_records(part_ids)
        except (RecordsError, KeyError) as error:
            raise ReviewError(c.ErrorCode.STALE_CONFLICT,
                "Current source records could not be validated. Reload valid sources before reviewing.", 409) from error

    def _target(self, name: str):
        fields = {c.contract_digest(field): field for field in self.registry.fields_for(name)}
        owners = self.registry.part_ids_for(name)
        if not fields or not owners:
            raise ReviewError(c.ErrorCode.NOT_FOUND, "The correction target is not a source fact.", 404)
        sources = self.registry.sources_for(name)
        occurrences = {(source.target.part_id, source.target.drawing_id, source.target.row_name)
                       for source in sources if source.name == name}
        if len(fields) != 1 or len(occurrences) != sum(source.name == name for source in sources):
            raise ReviewError(c.ErrorCode.STALE_CONFLICT,
                "This source name is ambiguous; no occurrence was selected.", 409)
        field = next(iter(fields.values()))
        if not isinstance(field, (c.EvidenceField, c.DrawingNumber)):
            raise ReviewError(c.ErrorCode.UNSUPPORTED,
                "Template answers need their dedicated value/option action; this slice reviews source corrections.", 501)
        if not self.registry.hashes_for(name):
            raise ReviewError(c.ErrorCode.UNSUPPORTED, "This fact has no validated source hash binding.", 501)
        return field, owners

    def _evidence(self, owners: tuple[str, ...], name: str) -> list[c.FactSource]:
        sources = list(self.registry.sources_for(name))
        for owner in owners:
            record = self.registry.part_for(owner)
            if record is None:
                continue
            if record.drawing:
                drawing = record.drawing
                for field in [*drawing.fields.values(), *drawing.numbers]:
                    sources.extend(self.registry.sources_for(field.name))
                # Actual extracted words, grouped by page. Never substitute an
                # accepted overlay or a guessed drawing transcription here.
                for page in drawing.page_geometry:
                    words = [word.text for word in drawing.words if word.page == page.page]
                    if words:
                        page_name = f"{drawing.id}/drawing/page/{page.page}"
                        sources.append(c.FactSource(name=page_name, says=" ".join(words), method=c.Method.PARSED,
                            source_sha256=drawing.source_sha256, source_quality=drawing.source_quality,
                            target=c.SourceTarget(kind="drawing", name=page_name, part_id=owner,
                                drawing_id=drawing.id, page=page.page,
                                box=(0, 0, page.source_width, page.source_height))))
            for row in record.bom:
                sources.extend(self.registry.sources_for(row.name))
                for field in row.fields.values():
                    sources.extend(self.registry.sources_for(field.name))
        return list({c.contract_digest(source): source for source in sources}.values())

    @staticmethod
    def _check(value: c.JsonValue, sources: list[c.FactSource]) -> c.CorrectionCheck:
        needle = _normal(value) if isinstance(value, str) else ""
        groups: dict[str, list[c.StringMatchEvidence]] = {"drawing": [], "bom": []}
        seen = set()
        for source in sources:
            kind = source.target.kind
            if kind not in groups or (kind, source.name) in seen or isinstance(source.says, (dict, list)):
                continue
            seen.add((kind, source.name))
            text = source.says if isinstance(source.says, str) else None
            groups[kind].append(c.StringMatchEvidence(source_name=source.name,
                matched=bool(needle and text is not None and needle in _normal(text)), text=text))
        return c.CorrectionCheck(drawing=groups["drawing"], bom=groups["bom"],
            message="Literal string matches in original drawing text and linked BOM cells only. "
                    "A match is evidence for review, never proof of correctness or approval.")

    def _item(self, proposal: c.Decision, events: list[c.Decision]) -> c.ReviewItem:
        reviews = [event for event in events if event.status != "pending" and (
            event.supersedes == proposal.decision_id or
            event.proposal_id == (proposal.proposal_id or proposal.decision_id))]
        latest = reviews[-1] if reviews else proposal
        hashes = self.registry.hashes_for(proposal.applies_to)
        current = bool(proposal.based_on) and all(hashes.get(k) == v for k, v in proposal.based_on.items())
        owners = self.registry.part_ids_for(proposal.applies_to)
        supported = True
        try:
            self._target(proposal.applies_to)
        except ReviewError:
            supported = False
        status = latest.status if current and supported else "source_changed"
        review = None
        if latest.status != "pending":
            review = c.ReviewState(status=(c.ReviewStatus.SOURCE_CHANGED if status == "source_changed" else
                c.ReviewStatus.HUMAN_CONFIRMED if latest.status == "accepted" else c.ReviewStatus.HUMAN_REJECTED),
                by=latest.by, at=latest.at, based_on=latest.based_on, decision_id=latest.decision_id)
        return c.ReviewItem(**_markers(proposal), id=f"review/decision/{proposal.decision_id}",
            kind="correction", applies_to=proposal.applies_to,
            part_id=owners[0] if len(owners) == 1 else None, status=status,
            title=f"Correction: {proposal.applies_to.rsplit('/', 1)[-1]}",
            message=(proposal.reason or "Saved proposal awaits explicit review.") + (
                f"\nReview note: {latest.note}" if latest is not proposal and latest.note is not None else ""),
            current_value=proposal.old_value, proposed_value=proposal.value,
            sources=self._evidence(owners, proposal.applies_to), source_hashes=proposal.based_on,
            ai_answers=proposal.ai_answers, check_result=proposal.check_result, review=review,
            allowed_actions=[c.ReviewAction.ACCEPT, c.ReviewAction.REJECT] if status == "pending" else [],
            proposal_id=proposal.proposal_id or proposal.decision_id,
            created_at=proposal.at, updated_at=latest.at)

    def _items(self) -> list[c.ReviewItem]:
        # Prepared non-correction items remain inspectable. Their other M1/M2
        # transitions are outside this correction slice and are not advertised.
        items = {item.id: item.model_copy(deep=True, update={"allowed_actions": []})
                 for item in self.registry.review_items}
        for journal in self.registry.document.decision_journals:
            for proposal in journal.decisions:
                if proposal.type != c.DecisionType.CORRECTION or proposal.status != "pending":
                    continue
                item = self._item(proposal, journal.decisions)
                for key in [key for key, saved in items.items() if saved.proposal_id == item.proposal_id]:
                    del items[key]
                items[item.id] = item
        return sorted(items.values(), key=lambda item: (item.created_at, item.id), reverse=True)

    def list_review(self, request: c.ReviewListRequest | None = None) -> c.ReviewListResponse:
        request = c.ReviewListRequest.model_validate((request or c.ReviewListRequest()).model_dump())
        with self._lock:
            self._rebuild()
            result = []
            tabs = {"correction": "corrections", "link": "needs_input", "template_field": "needs_input",
                    "name_mapping": "needs_input", "scan_reading": "possible_readings"}
            for item in self._items():
                if request.status != "all" and item.status != request.status:
                    continue
                if request.part_id and request.part_id not in {item.part_id, *self.registry.part_ids_for(item.applies_to)}:
                    continue
                if request.drawing_id and not any(s.target.drawing_id == request.drawing_id for s in item.sources):
                    continue
                if request.kind and request.kind != item.kind:
                    continue
                if request.tab and request.tab != tabs.get(item.kind, "ai_interpretations"):
                    continue
                if request.method and not any(s.method == request.method for s in item.sources):
                    continue
                if request.review_status and request.review_status != (
                        item.review.status if item.review else c.ReviewStatus.NOT_REVIEWED):
                    continue
                if request.weight_state and (item.weight_check is None or item.weight_check.state != request.weight_state):
                    continue
                result.append(item)
            return result

    def propose_correction(self, request: c.ProposeCorrectionRequest) -> c.ProposeCorrectionResult:
        request = c.ProposeCorrectionRequest.model_validate(request.model_dump())
        if not request.reason.strip():
            raise ReviewError(c.ErrorCode.INVALID_REQUEST, "A correction needs a nonblank reason.")
        with self._lock:
            self._rebuild()
            field, owners = self._target(request.fact_id)
            records = [self.registry.part_for(owner) for owner in owners]
            values = self.registry.values_for(request.fact_id)
            sources = self._evidence(owners, request.fact_id)
            identifier = f"proposal-{uuid4().hex}"
            proposal = c.Decision(**_markers(records[0]), decision_id=identifier,
                applies_to=request.fact_id, type=c.DecisionType.CORRECTION,
                value=request.new_value, old_value=values[0], status="pending",
                by="Chat proposal", at=datetime.now(timezone.utc),
                based_on=self.registry.hashes_for(request.fact_id),
                ai_answers=getattr(field, "provenance", None), check_result=self._check(request.new_value, sources),
                reason=request.reason, proposal_id=identifier)
            proposal = self.decisions.append_decision(proposal)
            # The durable append is sufficient for restart recovery. Rebuilds
            # on subsequent reads also expose the proposal to records/tools.
            item = self._item(proposal, [proposal])
            return c.ProposeCorrectionResult(**_markers(proposal), item=item, decision=proposal,
                review_link=c.ReviewLink(id=item.id, href=c.review_api_path(item.id)))

    @staticmethod
    def _unbuilt(model: c.ModelStatus, reason: str) -> c.ModelStatus:
        result = model.model_copy(deep=True)
        result.message = reason
        if result.examples:
            result.state, result.stale_reason = "stale", reason
        return result

    def refresh(self, request: c.RefreshRequest) -> c.RefreshResult:
        request = c.RefreshRequest.model_validate(request.model_dump())
        with self._lock:
            records = self._rebuild(request.part_ids)
            facts, models, warnings = {}, {}, []
            for record in records:
                facts.update(self.dependencies.resolve_facts(record))
                model = record.model.model_copy(deep=True)
                if request.rebuild_models:
                    reason = None
                    if self.dependencies.rebuild_model is None:
                        reason = "Facts refreshed; CAD builder unavailable. The model was not rebuilt."
                    else:
                        template = self.dependencies.load_template(record.id)
                        if template is None:
                            reason = "Facts refreshed; no supported template is available. The model was not rebuilt."
                        else:
                            try:
                                rebuilt = self.dependencies.rebuild_model(record, template)
                                model = c.ModelStatus.model_validate(rebuilt.model_dump())
                            except Exception:
                                reason = "Facts refreshed; model rebuild failed. Previous model assets were retained."
                    if reason:
                        model = self._unbuilt(model, reason)
                        warnings.append(f"{record.id}: {reason}")
                models[record.id] = model
            return c.RefreshResult(part_ids=[record.id for record in records], facts=facts, models=models, warnings=warnings)

    def review_action(self, item_id: str, action: c.ReviewActionRequest, reviewer: str) -> c.ReviewActionResponse:
        action = c.ReviewActionRequest.model_validate(action.model_dump())
        if action.action not in {c.ReviewAction.ACCEPT, c.ReviewAction.REJECT}:
            raise ReviewError(c.ErrorCode.UNSUPPORTED, "This slice supports explicit correction accept/reject actions only.", 501)
        if not reviewer.strip():
            raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Use the reviewer name from server settings.")
        if action.value is not None or action.source_ids:
            raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Accept/reject acts on the saved proposal, without replacing its value or sources.")
        with self._lock:
            self._rebuild()
            item = next((item for item in self._items() if item.id == item_id), None)
            if item is None:
                raise ReviewError(c.ErrorCode.NOT_FOUND, "Review item not found.", 404)
            if item.status != "pending":
                raise ReviewError(c.ErrorCode.STALE_CONFLICT, "This item is no longer pending. Reload its review state.", 409)
            if action.action not in item.allowed_actions:
                raise ReviewError(c.ErrorCode.UNSUPPORTED, "This item has no correction proposal to review.", 501)
            history = self.decisions.history(item.applies_to)
            proposal = next((event for event in history if event.status == "pending" and
                             (event.proposal_id or event.decision_id) == item.proposal_id), None)
            if proposal is None:
                raise ReviewError(c.ErrorCode.STALE_CONFLICT, "The saved proposal is unavailable. Reload before reviewing.", 409)
            # One terminal ID per proposal also prevents competing service
            # instances from accepting and rejecting it in separate events.
            identifier = "review-" + hashlib.sha256(proposal.decision_id.encode("utf-8")).hexdigest()
            decision = c.Decision(**_markers(proposal), decision_id=identifier,
                applies_to=proposal.applies_to, type=proposal.type, value=proposal.value, old_value=proposal.old_value,
                status="accepted" if action.action == c.ReviewAction.ACCEPT else "rejected",
                by=reviewer, at=datetime.now(timezone.utc), based_on=proposal.based_on,
                ai_answers=proposal.ai_answers, check_result=proposal.check_result, reason=proposal.reason,
                note=action.note, proposal_id=proposal.proposal_id or proposal.decision_id, supersedes=proposal.decision_id)
            try:
                decision = self.dependencies.append_decision(decision)
            except JournalError as error:
                raise ReviewError(c.ErrorCode.STALE_CONFLICT, "The decision journal changed. Reload before retrying.", 409) from error
            except PermissionError as error:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "The configured review appender did not authorize this reviewer.", 403) from error
            owners = list(self.registry.part_ids_for(proposal.applies_to))
            try:
                refreshed = self.refresh(c.RefreshRequest(part_ids=owners, decision_ids=[decision.decision_id],
                    rebuild_models=decision.status == "accepted"))
            except Exception:
                # Do not lose or deny a durable decision when a later projection
                # fails. The next successful read/restart retries the projection.
                refreshed = c.RefreshResult(part_ids=owners, facts={}, models={}, warnings=[
                    "Decision saved, but records/facts could not be refreshed. Reload to retry; no model rebuild is confirmed."])
            return c.ReviewActionResponse(**_markers(proposal), item=self._item(proposal, [*history, decision]),
                decisions=self.decisions.history(proposal.applies_to), refresh=refreshed)


def create_review_service(*, registry: RecordRegistry, decisions: DecisionStore,
                          dependencies: c.ReviewDependencies) -> ReviewService:
    """Compose M16 without importing chat, tools, routes, or a CAD implementation."""
    return ReviewService(registry=registry, decisions=decisions, dependencies=dependencies)
