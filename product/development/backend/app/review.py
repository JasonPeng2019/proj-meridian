"""M16 governed M1 proposals and explicit Debug review actions.

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
from ..loader.decisions import DecisionStore, JournalError, prepared_proposal_id
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
        except (RecordsError, KeyError, OSError) as error:
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

    def _link_rows(self, item: c.ReviewItem) -> list[str]:
        drawing = item.applies_to.split("/", 1)[0]
        resolution = next((link for link in self.registry.document.prepared.links if link.drawing_id == drawing), None)
        candidates = set(resolution.candidate_rows if resolution else [])
        candidates.update(source.target.row_name for source in item.sources if source.target.row_name)
        rows = self.registry.document.prepared.bom_rows
        return sorted(name for name in candidates if sum(row.name == name for row in rows) == 1
            and any(row.name == name and not row.identity_conflict and
                    str(row.fields.get("type").value).casefold() == "custom" for row in rows if row.fields.get("type")))

    def _prepared(self, item: c.ReviewItem) -> c.ReviewItem:
        result = item.model_copy(deep=True)
        original = next((saved for saved in self.registry.document.prepared.review_items if saved.id == item.id), None)
        if original is None or item.kind not in {"link", "template_field", "name_mapping", "scan_reading"}:
            result.allowed_actions = []
            return result
        target = self.registry.decision_name(item.id)
        hashes = self.registry.hashes_for(target)
        result.proposal_id = prepared_proposal_id(original)
        current = bool(original.source_hashes) and all(hashes.get(k) == v for k, v in original.source_hashes.items())
        current = current and all(source.source_sha256 is None or hashes.get(source.name) == source.source_sha256
                                  for source in original.sources)
        if not current:
            result.status, result.allowed_actions = "source_changed", []
            return result
        owners = self.registry.part_ids_for(target)
        result.sources = list({c.contract_digest(source): source for source in
            [*item.sources, *self._evidence(owners, item.applies_to)]}.values())
        actions = set(item.allowed_actions)
        if item.kind == "link":
            result.options = [{"drawing_id": item.applies_to.split("/", 1)[0], "bom_rows": [row]}
                              for row in self._link_rows(original)]
            try:
                self._link_value(original, item.proposed_value)
            except ReviewError:
                actions.discard(c.ReviewAction.ACCEPT)
        elif item.kind == "template_field":
            field = next((field for owner in owners for field in self.registry.template_fields(owner)
                          if field.name == item.applies_to), None)
            if field is None:
                actions = set()
            elif field.state == "options":
                result.options = [c.template_candidate_value(option.value) for option in field.options]
                actions &= {c.ReviewAction.REJECT, c.ReviewAction.CHOOSE_OPTION}
            else:
                actions.discard(c.ReviewAction.CHOOSE_OPTION)
                if field.state != "known":
                    reading = original.ai_answers.field_results.get(item.applies_to) if original.ai_answers else None
                    if not (reading and reading.accepted and reading.accepted.value == {"kind": "absent"}):
                        actions.discard(c.ReviewAction.ACCEPT)
        elif item.kind == "name_mapping":
            if original.mapping is None:
                actions.discard(c.ReviewAction.APPROVE_MAPPING)
                try:
                    _, to_name = self.registry.mapping_pair(original)
                    result.options = [{"relationship": relationship.value,
                        "to_name": None if relationship == c.MappingRelationship.NO_EQUIVALENT else to_name}
                        for relationship in c.MappingRelationship]
                except RecordsError:
                    actions.discard(c.ReviewAction.SET_VALUE)
            else:
                actions.discard(c.ReviewAction.SET_VALUE)
        elif item.kind == "scan_reading" and not isinstance(item.proposed_value, str):
            actions.discard(c.ReviewAction.ACCEPT)
        supported = {c.ReviewAction.ACCEPT, c.ReviewAction.REJECT, c.ReviewAction.SET_VALUE,
                     c.ReviewAction.CHOOSE_OPTION, c.ReviewAction.APPROVE_MAPPING}
        result.allowed_actions = [action for action in item.allowed_actions if action in actions & supported] if result.status == "pending" else []
        return result

    def _items(self) -> list[c.ReviewItem]:
        items = {item.id: self._prepared(item) for item in self.registry.review_items}
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
                if request.rebuild_models:
                    try:
                        self.registry.set_model_status(record.id, model)
                    except (RecordsError, OSError, ValueError):
                        models[record.id] = self._unbuilt(record.model,
                            "Facts refreshed; rebuilt model status could not be retained. No current rebuild is confirmed.")
                        warnings.append(f"{record.id}: Model status could not be retained; reload before using a rebuild.")
            return c.RefreshResult(part_ids=[record.id for record in records], facts=facts, models=models, warnings=warnings)

    def _link_value(self, item: c.ReviewItem, value: c.JsonValue) -> c.JsonValue:
        drawing = item.applies_to.split("/", 1)[0]
        if isinstance(value, dict):
            if set(value) != {"drawing_id", "bom_rows"} or value["drawing_id"] != drawing:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "A link must retain the reviewed drawing ID.")
            rows = value["bom_rows"]
        else:
            rows = value
        if (not isinstance(rows, list) or any(not isinstance(row, str) for row in rows)
                or len(rows) != len(set(rows)) or not set(rows) <= set(self._link_rows(item))):
            raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Select unique, recorded custom BOM candidates for this drawing.")
        return {"drawing_id": drawing, "bom_rows": rows}

    def _prepared_proposal(self, item: c.ReviewItem) -> c.Decision:
        original = next(saved for saved in self.registry.document.prepared.review_items if saved.id == item.id)
        target = self.registry.decision_name(item.id)
        hashes = dict(original.source_hashes)
        context = self.registry.hashes_for(target)
        for source in original.sources:
            if source.source_sha256 is not None:
                if context.get(source.name) != source.source_sha256:
                    raise ReviewError(c.ErrorCode.STALE_CONFLICT, "Reviewed source evidence changed. Reload before reviewing.", 409)
                hashes[source.name] = source.source_sha256
        kind = {"link": c.DecisionType.LINK, "name_mapping": c.DecisionType.NAME_MAPPING,
                "template_field": c.DecisionType.SET_VALUE, "scan_reading": c.DecisionType.SET_VALUE}[item.kind]
        identifier = prepared_proposal_id(original)
        return c.Decision(**_markers(self.registry.document.prepared.batch), decision_id=identifier,
            applies_to=target, type=kind, value=original.proposed_value, old_value=original.current_value,
            status="pending", by="Prepared evidence", at=original.created_at, based_on=hashes,
            ai_answers=original.ai_answers, check_result=original.check_result,
            reason=original.message, proposal_id=identifier)

    def _action_value(self, item: c.ReviewItem, proposal: c.Decision,
                      action: c.ReviewActionRequest) -> tuple[c.DecisionType, c.JsonValue]:
        if action.action in {c.ReviewAction.ACCEPT, c.ReviewAction.REJECT, c.ReviewAction.APPROVE_MAPPING}:
            if action.value is not None or action.source_ids:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "This action uses the saved value and source binding.")
        if action.action == c.ReviewAction.REJECT:
            return proposal.type, proposal.value
        if item.kind == "correction":
            return proposal.type, proposal.value
        if item.kind == "link":
            if action.source_ids:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Link values must use the recorded BOM candidates.")
            return c.DecisionType.LINK, self._link_value(item, action.value if action.action == c.ReviewAction.SET_VALUE else proposal.value)
        if item.kind == "name_mapping":
            original = next(saved for saved in self.registry.document.prepared.review_items if saved.id == item.id)
            if action.source_ids:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "A mapping retains its original evidence.")
            if action.action == c.ReviewAction.APPROVE_MAPPING and original.mapping:
                return c.DecisionType.NAME_MAPPING, {"relationship": original.mapping.relationship.value,
                                                    "to_name": original.mapping.to_name}
            try:
                _, target = self.registry.mapping_pair(original)
                value = action.value
                if (not isinstance(value, dict) or set(value) != {"relationship", "to_name"}
                        or value["relationship"] not in {relationship.value for relationship in c.MappingRelationship}
                        or value["to_name"] != (None if value["relationship"] == "no_equivalent" else target)):
                    raise ValueError("Mapping value disagrees with the recorded pair.")
                return c.DecisionType.NAME_MAPPING, value
            except (RecordsError, ValueError, TypeError) as error:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Choose a supported relationship for this recorded mapping pair.") from error
        if item.kind == "scan_reading":
            value = action.value if action.action == c.ReviewAction.SET_VALUE else proposal.value
            if not isinstance(value, str) or not value.strip() or action.source_ids:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "A scan reading needs a nonblank text value and its saved source binding.")
            return c.DecisionType.SET_VALUE, value
        if item.kind == "template_field":
            owners = self.registry.part_ids_for(item.applies_to)
            field = next(field for owner in owners for field in self.registry.template_fields(owner)
                         if field.name == item.applies_to)
            if action.action == c.ReviewAction.CHOOSE_OPTION:
                if action.source_ids or field.state != "options" or not any(
                        isinstance(option.value, bool) == isinstance(action.value, bool) and
                        c.template_candidate_value(option.value) == action.value
                        for option in field.options):
                    raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Choose an actual printed option with its retained evidence.")
                return c.DecisionType.CHOOSE_OPTION, action.value
            if action.action == c.ReviewAction.ACCEPT:
                return c.DecisionType.SET_VALUE, (c.template_candidate_value(field.value) if field.state == "known"
                                                  else proposal.value)
            value = action.value
            if action.source_ids:
                if isinstance(value, dict) and set(value) == {"value", "evidence"}:
                    raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Supply one explicit source-evidence representation.")
                record = self.registry.part_for(owners[0])
                numbers = {number.name for number in record.drawing.numbers}
                value = {"value": value, "evidence": c.ValueEvidence(
                    number_ids=[name for name in action.source_ids if name in numbers],
                    source_ids=[name for name in action.source_ids if name not in numbers]).model_dump(mode="json")}
            return c.DecisionType.SET_VALUE, value
        raise ReviewError(c.ErrorCode.UNSUPPORTED, "This item has no M1 review transition.", 501)

    def review_action(self, item_id: str, action: c.ReviewActionRequest, reviewer: str) -> c.ReviewActionResponse:
        action = c.ReviewActionRequest.model_validate(action.model_dump())
        if action.action not in {c.ReviewAction.ACCEPT, c.ReviewAction.REJECT, c.ReviewAction.SET_VALUE,
                                 c.ReviewAction.CHOOSE_OPTION, c.ReviewAction.APPROVE_MAPPING}:
            raise ReviewError(c.ErrorCode.UNSUPPORTED, "This action belongs to a later review milestone.", 501)
        if not reviewer.strip():
            raise ReviewError(c.ErrorCode.INVALID_REQUEST, "Use the reviewer name from server settings.")
        with self._lock:
            self._rebuild()
            item = next((item for item in self._items() if item.id == item_id), None)
            if item is None:
                raise ReviewError(c.ErrorCode.NOT_FOUND, "Review item not found.", 404)
            if item.status != "pending":
                raise ReviewError(c.ErrorCode.STALE_CONFLICT, "This item is no longer pending. Reload its review state.", 409)
            if action.action not in item.allowed_actions:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "This action is not available for the current item.")
            target = self.registry.decision_name(item.id)
            history = self.decisions.history(target)
            proposal = next((event for event in history if event.status == "pending" and
                             (event.proposal_id or event.decision_id) == item.proposal_id), None)
            if proposal is None:
                if not any(saved.id == item.id for saved in self.registry.document.prepared.review_items):
                    raise ReviewError(c.ErrorCode.STALE_CONFLICT, "The saved proposal is unavailable. Reload before reviewing.", 409)
                proposal = self._prepared_proposal(item)
            if any(event.status != "pending" and event.proposal_id == proposal.proposal_id for event in history):
                raise ReviewError(c.ErrorCode.STALE_CONFLICT, "This source-bound proposal was already reviewed.", 409)
            kind, value = self._action_value(item, proposal, action)
            # One terminal ID per proposal also prevents competing service
            # instances from accepting and rejecting it in separate events.
            identifier = "review-" + hashlib.sha256(proposal.decision_id.encode("utf-8")).hexdigest()
            decision = c.Decision(**_markers(proposal), decision_id=identifier,
                applies_to=proposal.applies_to, type=kind, value=value, old_value=proposal.old_value,
                status="rejected" if action.action == c.ReviewAction.REJECT else "accepted",
                by=reviewer, at=datetime.now(timezone.utc), based_on=proposal.based_on,
                ai_answers=proposal.ai_answers, check_result=proposal.check_result, reason=proposal.reason,
                note=action.note, proposal_id=proposal.proposal_id or proposal.decision_id, supersedes=proposal.decision_id)
            try:
                self.registry.validate_decision(decision)
            except (RecordsError, ValueError, TypeError) as error:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST,
                    "The value, option or cited evidence cannot apply to this source target.") from error
            owners = set(self.registry.part_ids_for(target))
            if item.kind == "link":
                record = self.registry.part_for(item.part_id)
                rows = set(record.link.bom_rows if record and record.link else [])
                if decision.status == "accepted":
                    rows.update(value["bom_rows"])
                owners.update(f"{row}/part" for row in rows)
            elif item.kind == "name_mapping":
                owners.update(owner for source in item.sources for owner in self.registry.part_ids_for(source.name))
            try:
                if not any(event.decision_id == proposal.decision_id for event in history):
                    self.decisions.append_decision(proposal)
                decision = self.dependencies.append_decision(decision)
            except JournalError as error:
                raise ReviewError(c.ErrorCode.STALE_CONFLICT, "The decision journal changed. Reload before retrying.", 409) from error
            except PermissionError as error:
                raise ReviewError(c.ErrorCode.INVALID_REQUEST, "The configured review appender did not authorize this reviewer.", 403) from error
            except OSError as error:
                raise ReviewError(c.ErrorCode.INTERNAL_ERROR,
                    "The decision result could not be confirmed. Reload the journal before retrying.", 500) from error
            owners = sorted(owners)
            try:
                refreshed = self.refresh(c.RefreshRequest(part_ids=owners, decision_ids=[decision.decision_id],
                    rebuild_models=decision.status == "accepted" and item.kind in {"correction", "template_field"}))
            except Exception:
                # Do not lose or deny a durable decision when a later projection
                # fails. The next successful read/restart retries the projection.
                refreshed = c.RefreshResult(part_ids=owners, facts={}, models={}, warnings=[
                    "Decision saved, but records/facts could not be refreshed. Reload to retry; no model rebuild is confirmed."])
            if item.kind == "correction":
                updated = self._item(proposal, [*history, decision])
            else:
                updated = next((saved for saved in self._items() if saved.id == item.id), item)
                if updated.status == "pending":
                    updated = updated.model_copy(deep=True, update={"status": decision.status, "allowed_actions": [],
                        "review": c.ReviewState(status=c.ReviewStatus.HUMAN_REJECTED if decision.status == "rejected" else
                            c.ReviewStatus.HUMAN_CONFIRMED, by=decision.by, at=decision.at,
                            based_on=decision.based_on, decision_id=decision.decision_id), "updated_at": decision.at,
                        "message": item.message + (f"\nReview note: {decision.note}" if decision.note is not None else "")})
            return c.ReviewActionResponse(**_markers(proposal), item=updated,
                decisions=self.decisions.history(proposal.applies_to), refresh=refreshed)


def create_review_service(*, registry: RecordRegistry, decisions: DecisionStore,
                          dependencies: c.ReviewDependencies) -> ReviewService:
    """Compose M16 without importing chat, tools, routes, or a CAD implementation."""
    return ReviewService(registry=registry, decisions=decisions, dependencies=dependencies)
