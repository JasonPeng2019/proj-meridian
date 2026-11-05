"""Deterministic M14 facts for both chat and the part detail page.

``FactTools(registry).resolve_facts(record)`` is the shared display projection.
Drawing/BOM evidence stays separate in records. Only current human-approved
name mappings reconcile different names; a model never chooses a winning source.
Construction/import performs no preparation, network or credential operations.
Pass M16's frozen proposal callback to enable pending correction suggestions.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from pydantic import JsonValue

from .. import contracts as c
from ..loader.decisions import effective_value
from ..loader.records import RecordRegistry


_HISTORICAL_AI = {c.Method.AI_READ, c.Method.AI_AGREED, c.Method.AI_AGREED_AFTER_RETRY}
_COST_CAVEAT = (
    "Recorded totals in the supplied snapshot, may be out of date. "
    "Rows without usable recorded totals are excluded; the complete machine cost is undetermined."
)


def _normal(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _compact(value: str) -> str:
    return "".join(char for char in _normal(value) if char.isalnum())


def _trusted(field: c.EvidenceField) -> bool:
    return (effective_value(field) is not None and (field.correction is not None or
            (field.confidence == c.Confidence.SURE and field.method != c.Method.UNRESOLVED
             and field.method not in _HISTORICAL_AI)))


def _equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return _normal(left) == _normal(right)
    return isinstance(left, bool) == isinstance(right, bool) and left == right


def _markers(records: Sequence[c.PartRecord]) -> dict:
    declarations = {(record.fixture, record.synthetic, record.fixture_note) for record in records}
    if any(record.synthetic for record in records):
        if len(declarations) != 1:
            raise ValueError("Synthetic and real-source tool results cannot be mixed.")
        record = records[0]
        return dict(fixture=record.fixture, synthetic=record.synthetic, fixture_note=record.fixture_note)
    return {}


def _sources_unique(sources: Sequence[c.FactSource]) -> list[c.FactSource]:
    result, seen = [], set()
    for source in sources:
        fingerprint = c.contract_digest(source)
        if fingerprint not in seen:
            result.append(source.model_copy(deep=True))
            seen.add(fingerprint)
    return result


class FactTools:
    """Implement the frozen FactTools protocol over the current RecordRegistry.

    Methods return detached contract payloads. Rebuilding the injected registry
    immediately changes subsequent tool/UI results; there is no second fact cache.
    Unknown or ambiguous identities raise KeyError. An absent proposal callback
    raises NotImplementedError instead of manufacturing a pending Review item.
    """

    def __init__(self, registry: RecordRegistry, *,
                 propose_correction: c.ProposeCorrectionCallback | None = None):
        self.registry = registry
        self._propose = propose_correction

    def _part(self, identity: str) -> c.PartRecord:
        owners = self.registry.part_ids_for(identity)
        if len(owners) != 1:
            raise KeyError(f"Part identity is {'ambiguous' if owners else 'not found'}: {identity}")
        record = self.registry.part_for(owners[0])
        if record is None:
            raise KeyError(identity)
        return record

    def _summary(self, record: c.PartRecord) -> c.PartSummary:
        return c.PartSummary(**_markers([record]), id=record.id, display_name=record.display_name,
            section=record.section, has_drawing=record.has_drawing, has_3d=record.has_3d,
            examples=record.examples, thumbnail=c.image_api_path(record.id, thumb=True) if record.drawing else None,
            model_state=record.model.state, review_items=record.review_items, weight_check=record.weight_check)

    def _part_fact(self, record: c.PartRecord) -> c.FactResult:
        return c.FactResult(**_markers([record]), fact=record.id, part_id=record.id,
            display=c.ValueDisplay(value={"id": record.id, "display_name": record.display_name,
                "drawing_id": record.drawing.id if record.drawing else None,
                "bom_rows": [row.name for row in record.bom]}),
            rule="Whole-part identity from current source records.", badge="Source record",
            sources=list(self.registry.sources_for(record.id)))

    def _relation(self, left: str, right: str, kind: str) -> str | None:
        """Approved SAME edges are symmetric; KIND_OF edges stay directional."""
        start, target = _normal(left), _normal(right)
        if start == target:
            return "same"
        mappings = [mapping for mapping in self.registry.approved_mappings if mapping.kind == kind]
        for mapping in mappings:
            if (mapping.relationship == c.MappingRelationship.DIFFERENT and mapping.to_name
                    and {_normal(mapping.from_name), _normal(mapping.to_name)} == {start, target}):
                return "different"
        same, broader = defaultdict(set), defaultdict(set)
        for mapping in mappings:
            if not mapping.to_name:
                continue
            source, destination = _normal(mapping.from_name), _normal(mapping.to_name)
            if mapping.relationship == c.MappingRelationship.SAME:
                same[source].add(destination)
                same[destination].add(source)
            elif mapping.relationship == c.MappingRelationship.KIND_OF:
                broader[source].add(destination)

        def reachable(include_broader: bool) -> bool:
            pending, seen = [start], set()
            while pending:
                node = pending.pop()
                if node == target:
                    return True
                if node not in seen:
                    seen.add(node)
                    pending.extend(same[node] | (broader[node] if include_broader else set()))
            return False

        return "same" if reachable(False) else "kind_of" if reachable(True) else None

    def _mappings_sources(self, fields: Sequence[c.EvidenceField], kind: str) -> list[c.FactSource]:
        names = {_normal(value) for field in fields for value in (
            effective_value(field) if isinstance(effective_value(field), list) else [effective_value(field)])
            if isinstance(value, str)}
        sources = []
        for mapping in self.registry.approved_mappings:
            if mapping.kind != kind or not mapping.to_name:
                continue
            if _normal(mapping.from_name) in names or _normal(mapping.to_name) in names:
                sources.append(c.FactSource(name=mapping.name,
                    says={"from_name": mapping.from_name, "to_name": mapping.to_name,
                          "relationship": mapping.relationship.value, "evidence_note": mapping.evidence_note},
                    method=mapping.method, review=mapping.review, provenance=mapping.provenance,
                    target=c.SourceTarget(kind="part", name=mapping.name,
                        part_id=next(iter(self.registry.part_ids_for(fields[0].name)), None))))
        return sources

    @staticmethod
    def _conflict(fields: Sequence[c.EvidenceField], *, unmapped: bool = False) -> c.UndeterminedDisplay:
        # Original wording survives even when a cleanup rule produced a list.
        statements = [f"{field.name}: {field.original!r}" +
            (f" (effective correction: {effective_value(field)!r})" if field.correction else "") for field in fields]
        message = "; ".join(statements) + "."
        if unmapped:
            message += " These names have no approved mapping."
        return c.UndeterminedDisplay(reason=c.UndeterminedReason.UNMAPPED_NAMES if unmapped else
                                     c.UndeterminedReason.SOURCE_CONFLICT, message=message)

    def _material(self, fields: Sequence[c.EvidenceField]) -> tuple[c.FactDisplay, str]:
        listed = [field for field in fields if isinstance(effective_value(field), list)
                  and len(effective_value(field)) > 1]
        if listed:
            materials = list(effective_value(listed[0]))
            recorded_materials = list(materials)
            if any(not isinstance(value, str) for value in materials):
                return self._conflict(fields), "B3 rule 5: incompatible recorded material lists."
            for field in fields:
                value = effective_value(field)
                if isinstance(value, list) and len(value) > 1:
                    if {_normal(item) for item in value} != {_normal(item) for item in recorded_materials}:
                        return self._conflict(fields), "B3 rule 5: differing recorded material lists."
                    continue
                value = value[0] if isinstance(value, list) and value else value
                if not isinstance(value, str):
                    return self._conflict(fields), "B3 rule 5: unsupported material value."
                matches = [(index, self._relation(value, material, "material"))
                           for index, material in enumerate(materials)]
                compatible = [(index, relation) for index, relation in matches if relation in {"same", "kind_of"}]
                if not compatible:
                    return self._conflict(fields, unmapped=any(relation is None for _, relation in matches)), \
                        "B3 rule 5: drawing/source material matches none of the recorded materials."
                index, relation = compatible[0]
                if relation == "kind_of":
                    materials[index] = value
            return c.ValueDisplay(value=materials, label="Materials recorded:"), \
                "B3 rule 5: recorded list; its composition or variant meaning is unspecified."
        values = [effective_value(field) for field in fields]
        values = [value[0] if isinstance(value, list) and len(value) == 1 else value for value in values]
        return self._select(fields, values, "material")

    def _select(self, fields: Sequence[c.EvidenceField], values: Sequence[JsonValue],
                kind: str | None) -> tuple[c.FactDisplay, str]:
        if all(_equal(value, values[0]) for value in values):
            return c.ValueDisplay(value=values[0]), "B3 rule 1: sole trusted source." if len(fields) == 1 else \
                "B3 rule 2: trusted sources agree."
        if kind and all(isinstance(value, str) for value in values):
            pairs = [self._relation(left, right, kind) for left in values for right in values]
            if "different" in pairs:
                return self._conflict(fields), "B3 rule 4: approved mapping identifies a conflict."
            for candidate in values:
                relationships = [self._relation(candidate, other, kind) for other in values]
                if all(relation in {"same", "kind_of"} for relation in relationships):
                    return c.ValueDisplay(value=candidate), "B3 rule 3: approved more-specific name." if \
                        "kind_of" in relationships else "B3 rule 2: approved equivalent names."
            return self._conflict(fields, unmapped=True), "B3 rule 4: differing names lack an approved mapping."
        return self._conflict(fields), "B3 rule 4: trusted sources conflict."

    def _resolve(self, record: c.PartRecord, key: str, fields: Sequence[c.EvidenceField]) -> c.FactResult:
        sources = _sources_unique([source for field in fields for source in self.registry.sources_for(field.name)])
        if not sources:
            sources = list(self.registry.sources_for(record.id))
        trusted = [field for field in fields if _trusted(field)]
        kind = key if key in {"section", "material"} else None
        if not trusted:
            unsure = any(field.confidence == c.Confidence.UNSURE for field in fields)
            degraded = record.drawing is not None and record.drawing.degraded and all(
                source.target.kind == "drawing" for source in sources)
            reason = c.UndeterminedReason.UNREADABLE_SCAN if degraded else \
                c.UndeterminedReason.UNSURE_SOURCE if unsure else c.UndeterminedReason.MISSING
            notes = [field.note for field in fields if field.note]
            display, rule = c.UndeterminedDisplay(reason=reason, message=" ".join(dict.fromkeys(notes)) or
                "No usable value is recorded in the supplied sources."), "B3 rule 0: missing or unsure values cannot resolve a fact."
        elif key == "material":
            display, rule = self._material(trusted)
        else:
            display, rule = self._select(trusted, [effective_value(field) for field in trusted], kind)
        if kind and len(trusted) > 1:
            sources = _sources_unique(sources + self._mappings_sources(trusted, kind))
        primary = trusted[0] if trusted else fields[0]
        methods = {field.method for field in trusted}
        badge = "From PDF and parts list" if {source.target.kind for source in sources} >= {"drawing", "bom"} else \
            "From PDF" if any(source.target.kind == "drawing" for source in sources) else "From parts list"
        if any(field.correction for field in trusted):
            badge = "Human correction"
        provenance_badge = c.SINGLE_MODEL_LABEL if c.Method.AI_SINGLE_MODEL in methods else None
        snapshot = any(getattr(field, "snapshot_note", False) for field in fields)
        unit = next((getattr(field, "unit", None) or getattr(field, "currency", None)
                     for field in trusted if getattr(field, "unit", None) or getattr(field, "currency", None)), None)
        if isinstance(display, c.ValueDisplay):
            display.unit = unit
        fact = fields[0].name
        review_item = next((item for item in record.review_items if any(
            field.name in item.id for field in fields)), None)
        return c.FactResult(**_markers([record]), fact=fact, part_id=record.id, display=display,
            rule=rule, badge=badge, provenance_badge=provenance_badge, review=primary.review,
            sources=sources, snapshot_note=snapshot, review_item=review_item, correction=primary.correction)

    def resolve_facts(self, record: c.PartRecord) -> dict[str, c.FactResult]:
        """Resolve B3 rules 0–5 once for every ordinary field and saved template."""
        facts = {record.id: self._part_fact(record)}
        groups = defaultdict(list)
        if record.drawing:
            for key, field in record.drawing.fields.items():
                groups[key].append(field)
            section = self.registry.drawing_sections.get(record.drawing.id)
            if section is not None:
                groups["section"].append(c.EvidenceField(name=f"{record.drawing.id}/manifest/section",
                    original=section, value=section, method=c.Method.PARSED))
        for row in record.bom:
            for key, field in row.fields.items():
                # Notes describe their own sources; B3 explicitly does not
                # compare note text to infer or override material/geometry.
                if key == "notes":
                    facts[field.name] = self._resolve(record, key, [field])
                else:
                    groups[key].append(field)
        for key, fields in groups.items():
            fact = self._resolve(record, key, fields)
            facts[fact.fact] = fact
        for field in self.registry.template_fields(record.id):
            sources = list(self.registry.sources_for(field.name)) or list(self.registry.sources_for(record.id))
            if field.state == "known":
                display = c.ValueDisplay(value=c.template_candidate_value(field.model_dump(mode="json")["value"]),
                                         unit=field.unit)
            elif field.state == "options":
                display = c.OptionsDisplay(values=[c.template_candidate_value(option.model_dump(mode="json")["value"])
                    for option in field.options], message="Printed alternatives; see the reconstruction examples.", unit=field.unit)
            else:
                display = c.UndeterminedDisplay(reason=field.reason, message=field.message)
            facts[field.name] = c.FactResult(**_markers([record]), fact=field.name, part_id=record.id, display=display,
                rule="Saved source-backed template field; model meshes are not evidence.", badge="From saved template",
                provenance_badge=c.SINGLE_MODEL_LABEL if field.method == c.Method.AI_SINGLE_MODEL else None,
                review=field.review, sources=sources, review_item=field.review_item)
        if record.drawing and not self.registry.template_fields(record.id):
            numbers = record.drawing.numbers
            tokens = ", ".join(number.text for number in numbers)
            message = (f"The drawing shows these measurements: {tokens}. Their edge/feature meanings are not established."
                       if tokens else "No source-backed labelled dimensions have been prepared for this drawing.")
            name = f"{record.drawing.id}/drawing/dimensions"
            sources = _sources_unique([source for number in numbers for source in self.registry.sources_for(number.name)])
            if not sources:
                sources = list(self.registry.sources_for(f"{record.drawing.id}/source"))
            facts[name] = c.FactResult(**_markers([record]), fact=name, part_id=record.id,
                display=c.UndeterminedDisplay(reason=c.UndeterminedReason.UNLABELLED_MEASUREMENT,
                                               message=message), rule="B3: unlabelled numbers do not establish dimensions.",
                badge="From PDF", sources=sources)
        return facts

    def find_part(self, text: str) -> c.FindPartResult:
        query = _normal(text)
        if not query:
            raise ValueError("Part search text must not be empty.")
        compact = _compact(query)
        matches = []
        for record in self.registry.records:
            identities = [record.id] + ([record.drawing.id] if record.drawing else [])
            identities += [value for row in record.bom for value in (row.name, row.display_id, f"{row.name}/part")]
            labels = [record.display_name] + [row.display_name for row in record.bom]
            labels += [str(effective_value(field)) for row in record.bom for key, field in row.fields.items()
                       if key in {"product_name"} and _trusted(field)]
            exact_id = any(query == _normal(identity) for identity in identities)
            exact_name = any(compact == _compact(label) for label in labels)
            partial = any(compact in _compact(label) for label in labels)
            words = query.split()
            token_match = any(all(word in _normal(label) for word in words) for label in labels)
            if exact_id or exact_name or partial or token_match:
                matches.append((0 if exact_id else 1 if exact_name else 2, record))
        if any(rank == 0 for rank, _ in matches):
            matches = [(rank, record) for rank, record in matches if rank == 0]
        elif any(rank == 1 for rank, _ in matches):
            matches = [(rank, record) for rank, record in matches if rank == 1]
        records = [record for _, record in sorted(matches, key=lambda item: (item[0], item[1].id))]
        return c.FindPartResult(**_markers(records), parts=[self._summary(record) for record in records],
            facts={record.id: self._part_fact(record) for record in records},
            unique_part_id=records[0].id if len(records) == 1 else None)

    def get_facts(self, part_id: str) -> c.GetFactsResult:
        record = self._part(part_id)
        return c.GetFactsResult(**_markers([record]), part_id=record.id, facts=self.resolve_facts(record))

    def get_connections(self, part_id: str) -> c.GetConnectionsResult:
        record = self._part(part_id)
        connections, facts = [], {record.id: self._part_fact(record)}
        for row in record.bom:
            field = row.fields.get("interface_with")
            if field:
                fact = self._resolve(record, "interface_with", [field])
                facts[fact.fact] = fact
            if field is None or not _trusted(field):
                continue
            for original in row.connections:
                connection = original.model_copy(deep=True)
                owners = self.registry.part_ids_for(connection.target_row) if connection.target_row else ()
                if len(owners) == 1 and original.resolved:
                    connection.target_part = owners[0]
                    target = self._part(owners[0])
                    facts[target.id] = self._part_fact(target)
                else:
                    connection.target_part = None
                    connection.resolved = False
                connections.append(connection)
        message = "Connections recorded in the source snapshot." if connections else "No connections recorded."
        return c.GetConnectionsResult(**_markers([record]), part_id=record.id, connections=connections, facts=facts, message=message)

    def _group(self, kind: str, query: str) -> c.PartGroupResult:
        if not query.strip():
            raise ValueError("Grouping name must not be empty.")
        records, facts = [], {}
        for record in self.registry.records:
            resolved = self.resolve_facts(record)
            candidates = [fact for fact in resolved.values() if fact.fact.endswith("/" + kind)]
            matched = []
            for fact in candidates:
                if not isinstance(fact.display, c.ValueDisplay):
                    continue
                values = fact.display.value if isinstance(fact.display.value, list) else [fact.display.value]
                if any(isinstance(value, str) and self._relation(value, query, kind) in {"same", "kind_of"}
                       for value in values):
                    matched.append(fact)
            if matched:
                records.append(record)
                facts[record.id] = self._part_fact(record)
                facts.update({fact.fact: fact for fact in matched})
        return c.PartGroupResult(**_markers(records), parts=[self._summary(record) for record in records], facts=facts,
            message=f"{len(records)} part(s) recorded with {query}." if records else f"No parts resolved under {query}.")

    def parts_in_section(self, section: str) -> c.PartGroupResult:
        return self._group("section", section)

    def parts_with_material(self, material: str) -> c.PartGroupResult:
        return self._group("material", material)

    def _inventory(self):
        records = sorted(self.registry.records, key=lambda record: record.id)
        rows, row_parts, drawings = {}, defaultdict(set), {}
        for record in records:
            if record.drawing:
                drawings[record.drawing.id] = record
            for row in record.bom:
                if row.name in rows and rows[row.name] != row:
                    raise ValueError("BOM identity collisions prevent an unambiguous aggregate.")
                rows[row.name] = row
                row_parts[row.name].add(record.id)
        hashes = {identity: record.drawing.source_sha256 for identity, record in drawings.items()}
        hashes.update({name: row.source_sha256 for name, row in rows.items()})
        return records, drawings, rows, row_parts, hashes

    @staticmethod
    def _aggregate(name: str, value: JsonValue, sources: Sequence[c.FactSource], *, markers: dict,
                   snapshot: bool = False, label: str | None = None) -> c.FactResult:
        if not sources:
            raise ValueError("No source evidence is loaded for this aggregate.")
        return c.FactResult(**markers, fact=name, part_id=None, display=c.ValueDisplay(value=value, label=label),
            rule="Deterministic aggregation of actual source records.", badge="Source aggregate",
            sources=_sources_unique(sources), snapshot_note=snapshot)

    def machine_summary(self) -> c.MachineSummaryResult:
        records, drawings, rows, row_parts, hashes = self._inventory()
        markers, facts = _markers(records), {}
        drawing_groups, bom_groups = defaultdict(list), defaultdict(list)
        for identity in drawings:
            drawing_groups[self.registry.drawing_sections.get(identity)].append(identity)
        for name, row in rows.items():
            section = row.fields.get("section")
            bom_groups[effective_value(section) if section and _trusted(section) else None].append(name)

        def sections(groups, drawing: bool):
            result = []
            category = "drawings" if drawing else "bom-rows"
            for section, names in sorted(groups.items(), key=lambda item: (item[0] is None, str(item[0]))):
                members = sorted(names)
                name = f"summary/machine/{category}/section/{c.contract_digest(section)[:16]}"
                parts = sorted({drawings[identity].id for identity in members} if drawing else
                               {part for identity in members for part in row_parts[identity]})
                sources = [source for identity in members for source in self.registry.sources_for(
                    f"{identity}/manifest/section" if drawing else rows[identity].fields["section"].name)]
                if not sources and drawing:
                    sources = [source for identity in members for source in self.registry.sources_for(f"{identity}/source")]
                facts[name] = self._aggregate(name, {"section": section, "count": len(members), "member_ids": members},
                                             sources, markers=markers)
                result.append(c.SummarySection(section=section, member_ids=members, part_ids=parts,
                                               count=len(members), fact=name))
            return result

        drawing_sections, bom_sections = sections(drawing_groups, True), sections(bom_groups, False)
        drawing_sources = [source for identity in drawings for source in self.registry.sources_for(f"{identity}/source")]
        bom_sources = [source for name in rows for source in self.registry.sources_for(name)]
        for name, value, sources in (("summary/machine/drawings", len(drawings), drawing_sources),
                                     ("summary/machine/bom-rows", len(rows), bom_sources),
                                     ("summary/machine/records", len(records), drawing_sources + bom_sources)):
            if sources:
                facts[name] = self._aggregate(name, value, sources, markers=markers)
        return c.MachineSummaryResult(**markers, records_sha256=c.contract_digest(records), source_hashes=hashes,
            record_count=len(records), drawing_count=len(drawings), bom_row_count=len(rows),
            drawing_sections=drawing_sections, bom_sections=bom_sections, facts=facts)

    def cost_summary(self) -> c.CostSummaryResult:
        records, _, rows, _, hashes = self._inventory()
        total, recorded, missing, sources = Decimal("0.00"), [], defaultdict(list), []
        for name, row in sorted(rows.items()):
            cost, amount, total_field = [row.fields.get(key) for key in ("cost", "amount", "total_cost")]
            sources.extend(source for field in (cost, amount, total_field) if field
                           for source in self.registry.sources_for(field.name))
            reason = None
            if cost is None or effective_value(cost) is None:
                reason = "missing_unit_cost"
            elif amount is None or effective_value(amount) is None:
                reason = "missing_amount"
            elif row.identity_conflict or any(not _trusted(field) for field in (cost, amount)):
                reason = "unresolved"
            elif total_field is None or effective_value(total_field) is None:
                reason = "missing_total"
            elif not _trusted(total_field):
                reason = "unresolved"
            else:
                value = effective_value(total_field)
                try:
                    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                        raise InvalidOperation
                    money = Decimal(str(value))
                    if not money.is_finite() or money < 0 or money != money.quantize(Decimal("0.01")):
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    reason = "invalid_total"
            if reason:
                missing[reason].append(name)
            else:
                total += money
                recorded.append(name)
        markers, name = _markers(records), "summary/cost/recorded-total"
        fact = self._aggregate(name, {"recorded_total": format(total, ".2f"), "currency": "DKK",
            "recorded_total_count": len(recorded), "missing_total_count": sum(map(len, missing.values())),
            "caveat": _COST_CAVEAT}, sources, markers=markers, snapshot=True)
        order = ("missing_unit_cost", "missing_amount", "missing_total", "invalid_total", "unresolved")
        return c.CostSummaryResult(**markers, records_sha256=c.contract_digest(records), source_hashes=hashes,
            recorded_total=format(total, ".2f"), recorded_row_names=recorded, recorded_total_count=len(recorded),
            missing_total_count=sum(map(len, missing.values())), row_count=len(rows),
            missing_reasons=[c.MissingCostGroup(reason=reason, row_names=missing[reason], count=len(missing[reason]))
                             for reason in order if missing[reason]],
            fact=name, facts={name: fact}, caveat=_COST_CAVEAT)

    def propose_correction(self, fact_id: str, new_value: JsonValue, reason: str) -> c.ProposeCorrectionResult:
        if self._propose is None:
            raise NotImplementedError("Correction suggestions are unavailable until the Review proposal service is connected.")
        request = c.ProposeCorrectionRequest(fact_id=fact_id, new_value=new_value, reason=reason)
        return self._propose(request)


def create_fact_tools(registry: RecordRegistry, *,
                      propose_correction: c.ProposeCorrectionCallback | None = None) -> FactTools:
    """Compose the frozen fact-tool interface and its optional M16 callback."""
    return FactTools(registry, propose_correction=propose_correction)
