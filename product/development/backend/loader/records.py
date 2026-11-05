"""Deterministic M12 records and citation registry; no extraction or model calls.

Runtime composition::

    registry = RecordRegistry.from_paths(
        prepared_path=generated / "prepared.json", inputs_path=generated / "inputs.json",
        records_path=generated / "records.json", decisions=DecisionStore(decisions_dir),
    )
    records = registry()  # frozen RecordsRebuilder; rereads saved prep/decisions
    template = registry.load_template("D-013/part")

``registry`` is the RecordsRebuilder injected into ReviewDependencies. M14 reads
``records``, ``sources_for``, ``fields_for``, ``part_ids_for``, ``hashes_for`` and
``approved_mappings``; it still owns fact resolution/B3 rules. Inject
``registry.load_template`` as the frozen TemplateLoader for BOTH fact and CAD
consumers. It returns the effective FlatTemplate, including nested human
overlays; a PartRecord.template is a reference to this registry entry, not a
second template file. ``template_fields`` enumerates that same effective tree.

records.json is a versioned RecordsDocument, not an undocumented array. It keeps
the exact typed PreparedKnowledge, effective records/templates/mappings, Debug
review items, and a snapshot of relevant M07 histories. DecisionStore outside
generated/ remains the authority on every rebuild. ``read_records`` reads a
validated snapshot without invoking prep, CAD, a CLI, or a network service.

All original source fields/boxes/rounds survive in ``prepared``. Corrections on
record evidence use M07's Correction/effective_value convention. A rejected
prepared interpretation is unresolved in the effective projection, with its
original value/provenance retained. Template decisions materialize a separate
effective tree. A scalar set_value retains its existing
ValueEvidence; a previously unevidenced numeric field needs the explicit
{"value": ..., "evidence": ValueEvidence} decision value. choose_option uses
only the chosen printed option's evidence. Unsupported overlays remain in
history and overlay_issues rather than becoming invented dimensions.

M11 template source_sha256 identifies the canonical DrawingEvidence snapshot;
the PDF byte hash stays on DrawingEvidence. Saved template page hashes are
checked against the supplied deterministic input root before reads/reviews.
validate_decision performs a dry projection before append. set_model_status
retains actual injected builder results or honest stale/missing metadata.

Link decisions use the drawing's canonical /part name (M07's accepted key),
with a list of BOM row names or {"drawing_id": ..., "bom_rows": [...]}.
``decision_name`` translates a matching ReviewItem's /link target accordingly.
Mappings accept a relationship string or {"relationship": ..., "to_name": ...};
only an accepted, current NAME_MAPPING decision makes one usable. Decisions
with changed/missing reviewed hashes do not apply, and retain SOURCE_CHANGED
attribution. No old accepted event is substituted for a newer stale event.

Duplicate stable names use multimaps. ``part_for`` refuses multiple owners;
``fields_for``/``sources_for`` return every occurrence. BOM citations keep their
original row/field names while targeting linked drawing parts. Later M2/M3
PartRecord members pass through ``previous_records`` without replacing source
evidence. Runtime paths must resolve inside this checkout's development/testing.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from ..ai.prepare import PreparedKnowledge, load_prepared
from ..ai.matching import MatchingRegistry
from ..contracts import (
    BOMRow, Confidence, ContractModel, Correction, Decision, DecisionJournal,
    DecisionType, DrawingEvidence, DrawingNumber, EvidenceField, FactSource,
    FlatTemplate, LinkInfo, MappingRelationship, Method, ModelStatus, NameMapping,
    PartRecord, ReviewAction, ReviewItem, ReviewLink, ReviewState, ReviewStatus,
    SourceTarget, TemplateFieldBase, ValueEvidence, contract_digest,
    PrepBatchResult, drawing_part_name, prep_counts, review_api_path,
    UnknownField, KnownField, template_candidate_value, normalize_component,
)
from .bom import load_bom
from .drawings import page_image_path
from .decisions import DecisionStore, effective_value, prepared_proposal_id


WORKSPACE = Path(__file__).resolve().parents[3]
_FIELD_METADATA = {"review", "review_item", "provenance", "evidence"}
_PART_ADDITIONS = ("weight_check", "callouts", "crops", "readme_passages", "installed_in")
_ACCEPTED_LINK_METHODS = {
    Method.EXACT_MATCH, Method.AI_VERIFIED, Method.AI_VERIFIED_AFTER_RETRY,
    Method.AI_SINGLE_MODEL,
}


class RecordsError(ValueError):
    """Invalid input or overlay; never silently choose a replacement source."""


class AmbiguousIdentityError(RecordsError):
    """A stable citation has several owners; inspect part_ids_for/sources_for."""


class OverlayIssue(ContractModel):
    name: str
    decision_id: str | None = None
    code: Literal["source_changed", "ambiguous_identity", "invalid_overlay", "missing_target"]
    message: str


class RecordsDocument(ContractModel):
    schema_version: Literal["meridian-records/v1"] = "meridian-records/v1"
    prepared: PreparedKnowledge
    records: list[PartRecord]
    templates: dict[str, FlatTemplate]
    mappings: list[NameMapping]
    review_items: list[ReviewItem]
    decision_journals: list[DecisionJournal]
    overlay_issues: list[OverlayIssue] = Field(default_factory=list)


def _runtime_path(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not any(resolved.is_relative_to(WORKSPACE / folder) for folder in ("development", "testing")):
        raise RecordsError("Records runtime paths must remain inside development/ or testing/.")
    return resolved


def _validated(model: BaseModel):
    # model_copy and mutable attributes do not run Pydantic validators.
    return type(model).model_validate(model.model_dump(mode="python"))


def iter_template_fields(value: BaseModel | Sequence | Mapping) -> Iterator[TemplateFieldBase]:
    """Visit outer and nested geometry fields, including position/pattern fields."""
    if isinstance(value, TemplateFieldBase):
        yield value
    if isinstance(value, BaseModel):
        for key in type(value).model_fields:
            if key not in _FIELD_METADATA:
                child = getattr(value, key)
                if isinstance(child, (BaseModel, list, dict)):
                    yield from iter_template_fields(child)
    elif isinstance(value, Mapping):
        for child in value.values():
            if isinstance(child, (BaseModel, list, dict)):
                yield from iter_template_fields(child)
    else:
        for child in value:
            if isinstance(child, (BaseModel, list, dict)):
                yield from iter_template_fields(child)


def _review(event: Decision, current: bool) -> ReviewState:
    return ReviewState(status=(ReviewStatus.HUMAN_REJECTED if event.status == "rejected" else
                              ReviewStatus.HUMAN_CONFIRMED) if current else ReviewStatus.SOURCE_CHANGED,
                       by=event.by, at=event.at, based_on=event.based_on, decision_id=event.decision_id)


def _text(field: EvidenceField | None) -> str | None:
    if field is None or (field.correction is None and
                         (field.confidence != Confidence.SURE or field.method == Method.UNRESOLVED)):
        return None
    value = effective_value(field)
    return value if isinstance(value, str) and value.strip() else None


def _unique(values: Sequence[str | None]) -> str | None:
    present = set(values)
    return next(iter(present)) if len(present) == 1 and None not in present else None


def _same(left: JsonValue, right: JsonValue) -> bool:
    # Python considers True == 1, but an option cannot change its value type.
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return isinstance(left, bool) == isinstance(right, bool) and left == right


def _numeric_proof(value: float, evidence: ValueEvidence, drawing: DrawingEvidence) -> None:
    """Validate explicit human numeric evidence without executing expressions."""
    numbers = {number.name: number for number in drawing.numbers if number.confidence == Confidence.SURE}
    if evidence.derivation is None:
        if (len(evidence.number_ids) != 1 or evidence.number_ids[0] not in numbers
                or not math.isclose(numbers[evidence.number_ids[0]].value, value, rel_tol=1e-12, abs_tol=1e-9)):
            raise RecordsError("A numeric value must equal its cited printed number or a supported derivation.")
        return
    proof = evidence.derivation
    if (set(proof.inputs) != set(evidence.number_ids) or len(proof.inputs) != len(set(proof.inputs))
            or not set(proof.inputs) <= numbers.keys() or len(proof.expression) > 512):
        raise RecordsError("A derivation must retain its exact current printed numeric inputs.")
    if proof.kind == "pattern" and proof.pattern_fact not in {
            f"{drawing.id}/drawing/page/{page.page}" for page in drawing.page_geometry}:
        raise RecordsError("A pattern derivation must cite the original drawing page.")
    try:
        tree = ast.parse(proof.expression, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise RecordsError("Invalid numeric derivation.") from error
    if len(list(ast.walk(tree))) > 64:
        raise RecordsError("Derivation is too complex.")
    used = set()

    def visit(node, depth=0):
        if depth > 12:
            raise RecordsError("Derivation is too deep.")
        if isinstance(node, ast.Name) and node.id.startswith("n") and node.id[1:].isdigit():
            index = int(node.id[1:])
            used.add(index)
            return numbers[proof.inputs[index]].value
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value in (
                {0, 2, 90, 180, 360} if proof.kind == "pattern" else {2}):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = visit(node.operand, depth + 1)
            return -result if isinstance(node.op, ast.USub) else result
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise RecordsError("Unsupported derivation operation.")

    try:
        computed = visit(tree.body)
        if used != set(range(len(proof.inputs))) or not math.isfinite(computed) or not math.isclose(
                computed, value, rel_tol=1e-12, abs_tol=1e-9):
            raise RecordsError("The numeric value does not follow from the cited derivation.")
    except (IndexError, ArithmeticError, RecursionError) as error:
        raise RecordsError("Invalid numeric derivation.") from error


def _replace_field(node: JsonValue, name: str, replacement: dict) -> bool:
    if isinstance(node, dict):
        if node.get("name") == name and "state" in node:
            node.clear()
            node.update(deepcopy(replacement))
            return True
        changed = False
        for key, child in node.items():
            if key not in _FIELD_METADATA and isinstance(child, (dict, list)):
                changed = _replace_field(child, name, replacement) or changed
        if changed and "name" in node and "state" in node:
            # An outer AI candidate containing a human-edited child is no
            # longer that exact AI candidate. Its original lives in prepared.
            node["method"] = Method.HUMAN_DECISION.value
            node["provenance"] = None
            node["review"] = None
        return changed
    if isinstance(node, list):
        changed = False
        for child in node:
            changed = _replace_field(child, name, replacement) or changed
        return changed
    return False


def read_records(path: str | Path) -> RecordsDocument:
    """Validate a generated snapshot; no filesystem writes or preparation calls."""
    document = RecordsDocument.model_validate_json(_runtime_path(path).read_bytes())
    if len({record.id for record in document.records}) != len(document.records):
        raise RecordsError("Generated part IDs collide.")
    return document


class RecordRegistry:
    """Single records/rebuild/source interface; returned payloads are detached.

    Construct from an already validated PreparedKnowledge or use from_paths.
    Construction assembles in memory. Calling the instance rebuilds ALL indexes
    and the complete output atomically, returning only requested part records.
    Targeted calls never truncate records.json or invoke a model builder.
    """

    def __init__(self, prepared: PreparedKnowledge, *, decisions: DecisionStore | None = None,
                 records_path: str | Path | None = None,
                 previous_records: Sequence[PartRecord] = (),
                 previous_templates: Mapping[str, FlatTemplate] | None = None,
                 original_drawings: Sequence[DrawingEvidence] | None = None):
        self._prepared = _validated(prepared)
        self._original_drawings = {drawing.id: _validated(drawing) for drawing in (
            original_drawings if original_drawings is not None else [drawing for drawing in prepared.drawings
                if not any(field.provenance for field in drawing.fields.values())])}
        self._decisions = decisions
        if decisions is not None:
            _runtime_path(decisions.directory)
        self._records_path = _runtime_path(records_path) if records_path is not None else None
        self._prepared_path: Path | None = None
        self._inputs_path: Path | None = None
        self._source_checks: dict[Path, str] = {}
        self._manifest_sections: dict[str, str] = {}
        self._manifest_sha256: str | None = None
        self._previous = [_validated(record) for record in previous_records]
        self._check_output_path()
        self._document = self._assemble(self._prepared, self._previous, previous_templates or {})
        self._index()

    @classmethod
    def from_paths(cls, *, prepared_path: str | Path, inputs_path: str | Path,
                   records_path: str | Path, decisions: DecisionStore | None = None) -> RecordRegistry:
        """CLI-free saved prep loading, bound to exact deterministic input bytes.

        No alternate prep JSON layout is accepted. Existing records contribute
        only model metadata and declared later-loader additions, never sources.
        """
        prep_path, input_path, output_path = map(_runtime_path, (prepared_path, inputs_path, records_path))
        if output_path in {prep_path, input_path}:
            raise RecordsError("Records output must not overwrite prepared or deterministic inputs.")
        prepared = load_prepared(prep_path)
        cls._check_input(prepared, input_path)
        inputs = json.loads(input_path.read_bytes())
        originals = [DrawingEvidence.model_validate(value) for value in inputs["drawings"]]
        if len({drawing.id for drawing in originals}) != len(originals):
            raise RecordsError("Original deterministic drawing identities collide.")
        original_by_id = {drawing.id: drawing for drawing in originals}
        if (set(original_by_id) != {drawing.id for drawing in prepared.drawings} or any(
                drawing.source_sha256 != original_by_id[drawing.id].source_sha256
                or drawing.source_path != original_by_id[drawing.id].source_path
                or drawing.numbers != original_by_id[drawing.id].numbers
                or drawing.page_geometry != original_by_id[drawing.id].page_geometry for drawing in prepared.drawings)
                or [BOMRow.model_validate(value) for value in inputs["bom"]] != prepared.bom_rows):
            raise RecordsError("Prepared records differ from the original deterministic source identities.")
        previous = read_records(output_path) if output_path.exists() else None
        registry = cls(prepared, decisions=decisions, records_path=output_path,
                       previous_records=previous.records if previous else [],
                       previous_templates=previous.templates if previous else {}, original_drawings=originals)
        registry._prepared_path, registry._inputs_path = prep_path, input_path
        for drawing in prepared.drawings:
            original = input_path.parent / drawing.source_path
            if original.is_file():
                registry._source_checks[_runtime_path(original)] = drawing.source_sha256
            template_job = next((record for record in prepared.batch.records
                                 if record.job == f"vision.template.{drawing.id}"), None)
            if template_job:
                for page in drawing.page_geometry:
                    expected = template_job.source.inputs.get(f"page:{page.page}")
                    if expected:
                        registry._source_checks[_runtime_path(input_path.parent / page_image_path(drawing.id, page.page))] = expected
        registry._check_source_files()
        return registry

    @classmethod
    def from_inputs(cls, inputs_path: str | Path, manifest_path: str | Path,
                    decisions: DecisionStore | None = None,
                    records_path: str | Path | None = None) -> RecordRegistry:
        """Load original extracted evidence without executing any AI preparation.

        This is the normal source-only startup when no prepared.json exists.
        Only MatchingRegistry's unique exact links attach BOM rows. Ambiguous
        candidates stay in the saved link inventory without being selected.
        Empty batch records/counts mean that no AI jobs have run, not that
        every source field was verified. Original scans remain unreadable.
        """
        input_path, manifest_path = map(_runtime_path, (inputs_path, manifest_path))

        def parse(raw: bytes):
            def unique(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise RecordsError("Source JSON contains a duplicate key.")
                    result[key] = value
                return result

            def invalid(value):
                raise RecordsError("Source JSON contains a nonfinite value.")

            return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)

        input_bytes, manifest_bytes = input_path.read_bytes(), manifest_path.read_bytes()
        payload, manifest = parse(input_bytes), parse(manifest_bytes)
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        if (not isinstance(payload, dict) or payload.get("schema") != "meridian-deterministic-inputs/v1"
                or payload.get("manifest_sha256") != manifest_digest or not isinstance(manifest, dict)):
            raise RecordsError("Deterministic inputs do not bind the original manifest bytes.")
        drawings = [DrawingEvidence.model_validate(value) for value in payload["drawings"]]
        rows = [BOMRow.model_validate(value) for value in payload["bom"]]
        for drawing in drawings:
            if any(field.method not in {Method.PARSED, Method.UNRESOLVED}
                   or field.provenance is not None or field.correction is not None
                   or (field.review and field.review.status != ReviewStatus.NOT_REVIEWED)
                   for field in drawing.fields.values()):
                raise RecordsError("Source-only startup requires original deterministic drawing fields.")
        for row in rows:
            if any(field.method not in {Method.PARSED, Method.CLEANUP_RULE, Method.UNRESOLVED}
                   or field.provenance is not None or field.correction is not None
                   or (field.review and field.review.status != ReviewStatus.NOT_REVIEWED)
                   for field in row.fields.values()):
                raise RecordsError("Source-only startup requires original deterministic BOM fields.")

        # Manifest paths are relative to the supplied project-meridian directory.
        source_root = manifest_path.parent.parent
        checks = {manifest_path: manifest_digest}
        assets = manifest.get("assets", [])
        drawing_assets = [asset for asset in assets if isinstance(asset, dict)
                          and asset.get("media_type") == "application/pdf"]
        if {asset.get("id") for asset in drawing_assets} != {drawing.id for drawing in drawings}:
            raise RecordsError("Deterministic drawing inventory differs from the original manifest.")
        for drawing in drawings:
            path = (source_root / drawing.source_path).resolve()
            if not path.is_relative_to(source_root) or hashlib.sha256(path.read_bytes()).hexdigest() != drawing.source_sha256:
                raise RecordsError("An original drawing no longer matches its extracted source hash.")
            checks[path] = drawing.source_sha256
        bom_assets = [asset for asset in assets if isinstance(asset, dict) and asset.get("id") == "OPENLPBF-BOM"]
        if len(bom_assets) != 1:
            raise RecordsError("The original BOM manifest entry is missing or ambiguous.")
        bom_asset = bom_assets[0]
        bom_path = (source_root / bom_asset["path"]).resolve()
        if not bom_path.is_relative_to(source_root) or hashlib.sha256(bom_path.read_bytes()).hexdigest() != bom_asset["sha256"]:
            raise RecordsError("The original BOM does not match its manifest hash.")
        if load_bom(bom_path) != rows:
            raise RecordsError("Extracted BOM evidence differs from the original source rows.")
        checks[bom_path] = bom_asset["sha256"]
        links = MatchingRegistry(drawings, rows, manifest).exact_links()
        for result in links:
            if result.state != "matched":
                # No preparation/review item was produced in this read-only path.
                result.link.review_item = None
        markers = {key: payload[key] for key in ("fixture", "synthetic", "fixture_note") if key in payload}
        prepared = PreparedKnowledge(source_only=True, input_sha256=hashlib.sha256(input_bytes).hexdigest(),
            drawings=drawings, bom_rows=rows, links=links, mappings=[], templates={}, review_items=[],
            batch=PrepBatchResult(**markers, records=[], counts=prep_counts([])))
        output = _runtime_path(records_path) if records_path is not None else None
        if output in {input_path, *checks}:
            raise RecordsError("Records output must not overwrite original source evidence.")
        previous = read_records(output) if output and output.exists() else None
        registry = cls(prepared, decisions=decisions, records_path=output,
                       previous_records=previous.records if previous else [],
                       previous_templates=previous.templates if previous else {})
        registry._inputs_path, registry._source_checks = input_path, checks
        registry._manifest_sections = {asset["id"]: asset["subsystem"] for asset in drawing_assets}
        registry._manifest_sha256 = manifest_digest
        registry._index()
        registry._check_source_files()
        return registry

    def _check_source_files(self) -> None:
        for path, expected in self._source_checks.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RecordsError("Original source evidence changed; extract and rebuild from current inputs.")

    @staticmethod
    def _check_input(prepared: PreparedKnowledge, path: Path) -> None:
        if hashlib.sha256(path.read_bytes()).hexdigest() != prepared.input_sha256:
            raise RecordsError("Saved preparation does not bind these deterministic input JSON bytes.")

    def _check_output_path(self) -> None:
        if self._records_path is None:
            return
        output = _runtime_path(self._records_path)
        if output in {self._prepared_path, self._inputs_path}:
            raise RecordsError("Records output must not overwrite prepared or deterministic inputs.")
        protected = [WORKSPACE / "development/inputs"]
        if self._decisions is not None:
            protected.append(self._decisions.directory)
        if any(output == path or output.is_relative_to(path) for path in protected):
            raise RecordsError("Records output cannot overwrite source inputs or decision journals.")

    @property
    def document(self) -> RecordsDocument:
        return self._document.model_copy(deep=True)

    @property
    def records(self) -> list[PartRecord]:
        return [record.model_copy(deep=True) for record in self._document.records]

    @property
    def review_items(self) -> list[ReviewItem]:
        """Engineering Debug queue, never an ordinary customer status."""
        return deepcopy(self._document.review_items)

    @property
    def approved_mappings(self) -> list[NameMapping]:
        return [mapping.model_copy(deep=True) for mapping in self._document.mappings
                if mapping.review.status == ReviewStatus.HUMAN_CONFIRMED
                and mapping.review.decision_id in self._applied]

    @property
    def drawing_sections(self) -> dict[str, str]:
        """Original manifest subsystem names, separate from BOM section names."""
        return dict(self._manifest_sections)

    def __call__(self, part_ids: Sequence[str] | None = None) -> list[PartRecord]:
        # Assemble/validate before replacing either the disk or in-memory state.
        prepared = load_prepared(self._prepared_path) if self._prepared_path else _validated(self._prepared)
        if self._inputs_path is not None:
            self._check_input(prepared, self._inputs_path)
        self._check_source_files()
        staged = object.__new__(RecordRegistry)
        staged._decisions = self._decisions
        staged._original_drawings = self._original_drawings
        staged._manifest_sections = self._manifest_sections
        staged._manifest_sha256 = self._manifest_sha256
        candidate = staged._assemble(prepared, self._document.records, self._document.templates)
        staged._document = candidate
        staged._index()
        requested = None
        if part_ids is not None:
            requested = set()
            for name in part_ids:
                owners = staged.part_ids_for(name)
                if not owners:
                    raise KeyError(name)
                requested.update(owners)
        if self._records_path is not None:
            self._check_output_path()
            self._check_source_files()
            self._save(candidate, self._records_path)
        self.__dict__.update(staged.__dict__)
        self._prepared = prepared
        return [record for record in self.records if requested is None or record.id in requested]

    def save(self) -> None:
        """Write the complete current snapshot to the configured records path."""
        if self._records_path is None:
            raise RecordsError("No records output path was configured.")
        if self._inputs_path is not None:
            self._check_input(self._prepared, self._inputs_path)
        self._check_source_files()
        self._check_output_path()
        self._save(self._document, self._records_path)

    @staticmethod
    def _save(document: RecordsDocument, path: Path) -> None:
        path = _runtime_path(path)
        payload = json.dumps(document.model_dump(mode="json"), sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(prefix=".records-", suffix=".tmp", dir=path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def part_ids_for(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(self._owners.get(name, ())))

    def part_for(self, name: str) -> PartRecord | None:
        owners = self.part_ids_for(name)
        if len(owners) > 1:
            raise AmbiguousIdentityError(f"{name!r} belongs to several parts: {owners}")
        return self._parts[owners[0]].model_copy(deep=True) if owners else None

    def sources_for(self, name: str) -> tuple[FactSource, ...]:
        return tuple(source.model_copy(deep=True) for source in self._sources.get(name, ()))

    def fields_for(self, name: str) -> tuple[EvidenceField | DrawingNumber | TemplateFieldBase, ...]:
        """Every occurrence, preserving collisions instead of selecting a value."""
        return tuple(field.model_copy(deep=True) for field in self._fields.get(name, ()))

    def values_for(self, name: str) -> tuple[JsonValue, ...]:
        """Effective source values, without resolving conflicts between sources.

        Numeric tokens remain unchanged in DrawingEvidence. An explicit human
        correction of one is available here and in correction_for/history;
        it never rewrites the printed number supporting a template.
        """
        correction = self.correction_for(name)
        values = []
        for field in self._fields.get(name, ()):
            if isinstance(field, EvidenceField):
                values.append(effective_value(field))
            elif isinstance(field, DrawingNumber):
                values.append(correction.corrected if correction else field.value)
            elif field.state == "options":
                values.append([option.model_dump(mode="json")["value"] for option in field.options])
            else:
                values.append(field.model_dump(mode="json").get("value"))
        return tuple(deepcopy(values))

    def correction_for(self, name: str) -> Correction | None:
        event = next((event for event in reversed(self._events[name])
                      if event.status == "accepted"), None)
        if event is None or event.decision_id not in self._applied or event.type not in {
                DecisionType.CORRECTION, DecisionType.SET_VALUE}:
            return None
        return Correction(original=event.old_value, corrected=event.value,
                          by=event.by, at=event.at, decision_id=event.decision_id)

    def hashes_for(self, name: str) -> dict[str, str]:
        """Current source fingerprints scoped to this fact/link/mapping's inputs."""
        return dict(self._hashes.get(name, {}))

    def load_template(self, part_id: str) -> FlatTemplate | None:
        record = self.part_for(part_id)
        template = self._document.templates.get(record.drawing.id) if record and record.drawing else None
        return template.model_copy(deep=True) if template else None

    def template_fields(self, part_id: str) -> tuple[TemplateFieldBase, ...]:
        template = self.load_template(part_id)
        if template is None:
            return ()
        fields = list(iter_template_fields(template))
        names = {field.name for field in fields}
        for item in self._document.prepared.review_items:
            if (item.kind != "template_field" or item.applies_to in names or not item.ai_answers
                    or not item.applies_to.startswith(f"{template.part}/template/feature-")):
                continue
            result = item.ai_answers.field_results.get(item.applies_to)
            candidate = result.accepted if result else None
            if candidate is None or candidate.value != {"kind": "absent"}:
                continue
            event = self._accepted(item.applies_to, {DecisionType.SET_VALUE, DecisionType.CHOOSE_OPTION})
            method = (Method.HUMAN_DECISION if event else {"first_pass_verified": Method.AI_VERIFIED,
                "retry_verified": Method.AI_VERIFIED_AFTER_RETRY, "unverified_fallback": Method.AI_SINGLE_MODEL}.get(result.status))
            if method is not None:
                fields.append(KnownField[dict](name=item.applies_to, method=method, value={"kind": "absent"},
                    evidence=ValueEvidence(source_ids=candidate.source_ids), provenance=item.ai_answers,
                    review=_review(event, True) if event else None))
        return tuple(fields)

    def validate_decision(self, decision: Decision) -> None:
        """Dry projection before journal append; no files, models or saved events."""
        staged = object.__new__(RecordRegistry)
        staged._decisions = self._decisions
        staged._original_drawings = self._original_drawings
        staged._manifest_sections, staged._manifest_sha256 = self._manifest_sections, self._manifest_sha256
        staged._preview_decisions = [decision.model_copy(deep=True)]
        staged._assemble(self._prepared, self._document.records, self._document.templates)
        issues = [issue for issue in staged._issues if issue.decision_id == decision.decision_id]
        if decision.status == "rejected" and not (decision.proposal_id or "").startswith("prepared-"):
            context = staged._hashes.get(decision.applies_to, {})
            if not issues and decision.based_on and all(context.get(key) == value for key, value in decision.based_on.items()):
                return  # Rejecting a suggestion is intentionally a projection no-op.
        if issues or decision.decision_id not in staged._applied:
            raise RecordsError(issues[0].message if issues else "This decision cannot apply to its declared source target.")

    def set_model_status(self, part_id: str, model: ModelStatus) -> None:
        """Retain callback/no-builder results in the same records projection."""
        record = self.part_for(part_id)
        if record is None or record.id != part_id:
            raise RecordsError("Model status needs an existing canonical part.")
        status = _validated(model)
        template = self.load_template(part_id)
        current = contract_digest(template) if template else None
        if status.state == "available" and (current is None or status.built_template_sha256 != current):
            raise RecordsError("A rebuilt model must identify its actual effective template digest.")
        status.current_template_sha256 = current
        record.model, record.has_3d = status, status.state in {"available", "stale"}
        record.examples = [example.id for example in status.examples]
        candidate = self._document.model_copy(deep=True)
        candidate.records = [record if saved.id == part_id else saved for saved in candidate.records]
        candidate = _validated(candidate)
        if self._records_path is not None:
            self._check_output_path()
            self._check_source_files()
            if self._inputs_path is not None:
                self._check_input(self._prepared, self._inputs_path)
            self._save(candidate, self._records_path)
        self._document = candidate
        self._index()

    def decision_name(self, item_id: str) -> str:
        item = next((item for item in self._document.review_items if item.id == item_id), None)
        if item is None:
            raise KeyError(item_id)
        return self._decision_name(item)

    def mapping_pair(self, item: ReviewItem) -> tuple[str, str]:
        """Recover both recorded labels, never invent them from normalized IDs."""
        parts = item.applies_to.split("/")
        if len(parts) != 3 or parts[0] != "names" or parts[1] not in {"section", "material"}:
            raise RecordsError("Unknown mapping target.")
        pair = parts[2].split(" -> ")
        if len(pair) != 2:
            raise RecordsError("Mapping target must retain its recorded pair.")
        referenced = {source.name for source in item.sources}
        fields = [field for drawing in self._prepared.drawings for field in drawing.fields.values()]
        fields += [field for row in self._prepared.bom_rows for field in row.fields.values()]
        labels = set()
        for field in fields:
            if field.name in referenced:
                values = field.value if isinstance(field.value, list) else [field.value]
                labels.update(value for value in values if isinstance(value, str) and value.strip())
        resolved = [{label for label in labels if normalize_component(label) == token} for token in pair]
        if any(len(values) != 1 for values in resolved):
            raise RecordsError("Mapping labels are missing or ambiguous in the recorded evidence.")
        return next(iter(resolved[0])), next(iter(resolved[1]))

    @staticmethod
    def _decision_name(item: ReviewItem) -> str:
        return item.part_id if item.kind == "link" and item.part_id else item.applies_to

    def _issue(self, name: str, code: str, message: str, event: Decision | None = None) -> None:
        issue = OverlayIssue(name=name, decision_id=event.decision_id if event else None,
                             code=code, message=message)
        if issue not in self._issues:
            self._issues.append(issue)

    def _hash_contexts(self, prepared: PreparedKnowledge) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._anchors: dict[str, set[str]] = {}
        self._ambiguous: set[str] = set()
        rows = Counter(row.name for row in prepared.bom_rows)
        for drawing in prepared.drawings:
            counts = Counter(field.name for field in [*drawing.fields.values(), *drawing.numbers])
            self._ambiguous.update(name for name, count in counts.items() if count > 1)
            hashes = {drawing.id: drawing.source_sha256, f"{drawing.id}/source": drawing.source_sha256,
                      drawing.source_path: drawing.source_sha256}
            hashes.update({field.name: drawing.source_sha256 for field in
                           [*drawing.fields.values(), *drawing.numbers]})
            page_names = [f"{drawing.id}/drawing/page/{page.page}" for page in drawing.page_geometry]
            hashes.update({name: drawing.source_sha256 for name in page_names})
            for name in [drawing.id, drawing_part_name(drawing.id), f"{drawing.id}/source",
                         f"{drawing.id}/link", *[f.name for f in drawing.fields.values()],
                         *[number.name for number in drawing.numbers], *page_names]:
                self._hashes[name] = dict(hashes)
                self._anchors[name] = set(hashes)
            for field in drawing.fields.values():
                if field.provenance:
                    self._hashes[field.name].update(field.provenance.source.inputs)
                    self._anchors[field.name].update(field.provenance.source.inputs)
        self._row_hashes = {}
        for row in prepared.bom_rows:
            counts = Counter(field.name for field in row.fields.values())
            self._ambiguous.update(name for name, count in counts.items() if count > 1)
            if rows[row.name] > 1 or row.identity_conflict:
                self._ambiguous.update([row.name, f"{row.name}/part", *[f.name for f in row.fields.values()]])
                continue
            hashes = {row.name: row.source_sha256, f"{row.name}/part": row.source_sha256,
                      **{field.name: row.source_sha256 for field in row.fields.values()}}
            self._row_hashes[row.name] = hashes
            for name in hashes:
                self._hashes[name] = dict(hashes)
                self._anchors[name] = set(hashes)
            for field in row.fields.values():
                if field.provenance:
                    self._hashes[field.name].update(field.provenance.source.inputs)
                    self._anchors[field.name].update(field.provenance.source.inputs)
        for drawing in prepared.drawings:
            target = drawing_part_name(drawing.id)
            context = self._hashes[target]
            for hashes in self._row_hashes.values():
                context.update(hashes)
        for result in prepared.links:
            target = drawing_part_name(result.drawing_id)
            context = self._hashes[target]
            if result.link.provenance:
                context.update(result.link.provenance.source.inputs)
                self._anchors[target].update(result.link.provenance.source.inputs)
            self._hashes[f"{result.drawing_id}/link"] = dict(context)
            self._anchors[f"{result.drawing_id}/link"] = set(self._anchors[target])
        for identity, template in self._base_templates.items():
            hashes = dict(self._hashes[identity])
            if template.provenance:
                hashes.update(template.provenance.source.inputs)
            for field in iter_template_fields(template):
                self._hashes[field.name] = {**hashes, **(field.provenance.source.inputs if field.provenance else {})}
                self._anchors[field.name] = set(self._hashes[field.name])
        for mapping in self._base_mappings:
            self._hashes[mapping.name] = dict(mapping.provenance.source.inputs) if mapping.provenance else {}
            self._anchors[mapping.name] = set(self._hashes[mapping.name])
        for item in prepared.review_items:
            target = self._decision_name(item)
            if item.kind == "template_field" and target not in self._hashes:
                identity = target.split("/", 1)[0]
                if identity in self._drawings and item.ai_answers:
                    self._hashes[target] = {**self._hashes[identity], **item.ai_answers.source.inputs}
                    self._anchors[target] = set(self._hashes[target])
            # Non-AI mapping fixtures can cite real drawing/row identities;
            # never accept an unknown hash merely because a review item says it.
            if item.kind == "name_mapping" and not self._hashes.get(target):
                self._hashes[target] = dict(item.ai_answers.source.inputs) if item.ai_answers else {}
                self._anchors[target] = set(self._hashes[target])
                available = {key: value for context in self._hashes.values() for key, value in context.items()
                             if key in item.source_hashes and value == item.source_hashes[key]}
                self._hashes[target].update(available)
                self._anchors[target].update(available)
            if target in self._hashes:
                # Bind review snapshots to current original source identities,
                # not only to hashes copied from their saved AI provenance.
                for source in item.sources:
                    context = self._hashes.get(source.name, {})
                    digest = context.get(source.name)
                    if digest is not None:
                        self._hashes[target][source.name] = digest
                        self._anchors[target].add(source.name)

    def _histories(self, prepared: PreparedKnowledge) -> list[DecisionJournal]:
        owners = {drawing_part_name(drawing.id) for drawing in prepared.drawings}
        owners.update(f"{row.name}/part" for row in prepared.bom_rows)
        owners.update(mapping.name for mapping in prepared.mappings)
        owners.update(item.applies_to for item in prepared.review_items if item.kind == "name_mapping")
        journals = [self._decisions.journal(owner) for owner in sorted(owners)] if self._decisions else []
        self._events = defaultdict(list)
        for journal in journals:
            for event in journal.decisions:
                if event.synthetic and not prepared.batch.synthetic:
                    raise RecordsError("Synthetic decisions cannot enter a real-source records rebuild.")
                self._events[event.applies_to].append(event)
        return [journal for journal in journals if journal.decisions]

    def _current_review(self, name: str, types: set[DecisionType]) -> Decision | None:
        # Rejected correction suggestions do not revoke a prior correction.
        # Rejecting an actual prepared interpretation does make it unresolved.
        event = next((event for event in reversed(self._events[name]) if event.status == "accepted" or (
            event.status == "rejected" and (event.proposal_id or "").startswith("prepared-"))), None)
        if event is None:
            return None
        if event.status == "rejected" and DecisionType.CORRECTION in types:
            context = self._hashes.get(name, {})
            replacement = next((saved for saved in reversed(self._events[name]) if saved.status == "accepted"
                and saved.type == DecisionType.CORRECTION and saved.proposal_id != event.proposal_id
                and all(context.get(key) == value for key, value in saved.based_on.items())), None)
            if replacement is not None:
                self._applied.add(event.decision_id)  # Review rejects the AI, not its explicit human replacement.
                event = replacement
        if event.type not in types:
            self._issue(name, "invalid_overlay", "Accepted event has the wrong decision type for this target.", event)
            return None
        if name in self._ambiguous:
            self._issue(name, "ambiguous_identity", "Stable source name collides; no occurrence was selected.", event)
            return None
        context = self._hashes.get(name, {})
        if (not set(event.based_on).intersection(self._anchors.get(name, set()))
                or any(context.get(key) != value for key, value in event.based_on.items())):
            self._issue(name, "source_changed", "Reviewed source hashes are missing or changed; reapproval is required.", event)
            return None
        return event

    def _accepted(self, name: str, types: set[DecisionType]) -> Decision | None:
        event = self._current_review(name, types)
        return event if event is not None and event.status == "accepted" else None

    def _overlay_field(self, field: EvidenceField) -> EvidenceField:
        # Work from an M07 journal snapshot so one rebuild cannot mix decisions
        # observed before and after a concurrent human append.
        result = field.model_copy(deep=True, update={"correction": None})
        event = self._current_review(field.name, {DecisionType.CORRECTION, DecisionType.SET_VALUE})
        latest = next((e for e in reversed(self._events[field.name]) if e.status == "accepted"), None)
        if event is not None and event.status == "rejected":
            result.method, result.confidence = Method.UNRESOLVED, Confidence.UNSURE
            result.review = _review(event, True)
            self._applied.add(event.decision_id)
        elif event is not None:
            result.correction = Correction(original=event.old_value, corrected=event.value,
                                           by=event.by, at=event.at, decision_id=event.decision_id)
            result.review = _review(event, True)
            self._applied.add(event.decision_id)
        elif latest and any(issue.decision_id == latest.decision_id and issue.code == "source_changed"
                            for issue in self._issues):
            result.review = _review(latest, False)
        return result

    def _choice(self, template: FlatTemplate, field: TemplateFieldBase, event: Decision):
        choices = [option for option in getattr(field, "options", [])
                   if _same(template_candidate_value(option.value), event.value)]
        if len(choices) == 1:
            return choices[0].value, choices[0].evidence
        # A source-current human choice survives later AI known/unknown states.
        # Only this exact accepted event may reuse its earlier effective proof.
        previous = self._previous_templates.get(template.part)
        if previous and previous.source_sha256 == template.source_sha256:
            prior = next((f for f in iter_template_fields(previous) if f.name == field.name), None)
            if (prior is not None and prior.state == "known" and prior.review
                    and prior.review.decision_id == event.decision_id and _same(prior.value, event.value)):
                return prior.value, prior.evidence
        # Generated output can be deleted. An actual saved proposal may retain
        # the original, accepted options and their numeric source references.
        result = event.ai_answers.field_results.get(field.name) if event.ai_answers else None
        candidate = result.accepted if result else None
        if candidate and candidate.state == "options" and any(_same(value, event.value) for value in candidate.options):
            numbers = [number for number in self._drawings[template.part].numbers
                       if number.name in candidate.source_ids and number.confidence == Confidence.SURE
                       and _same(number.value, event.value)]
            if len(numbers) == 1:
                return event.value, ValueEvidence(number_ids=[numbers[0].name])
        raise RecordsError("choose_option must select an actual printed option retained with this decision.")

    def _human_template_value(self, value, field, evidence, event):
        """Attach source-backed wrappers to semantic outline/feature input."""
        numeric = {"length", "width", "diameter", "inner_diameter", "outer_diameter", "x", "y", "depth",
            "thread_depth", "countersink_diameter", "countersink_angle_deg", "counterbore_diameter",
            "counterbore_depth", "spacing", "direction_deg", "radius", "start_angle_deg", "count", "angles_deg"}
        drawing = self._drawings[field.name.split("/", 1)[0]]
        numbers = {number.name: number for number in drawing.numbers if number.confidence == Confidence.SURE}

        def convert(node, path="", key=""):
            if isinstance(node, dict):
                if {"name", "method", "state"} <= node.keys():
                    raise RecordsError("Use semantic values and cited sources; nested field identities are server-owned.")
                if node == {"state": "unknown"}:
                    return UnknownField(name=field.name + path, method=Method.UNRESOLVED,
                        reason="pending_input", message="Left unresolved by explicit review.").model_dump(mode="json")
                return {name: convert(child, path + "/" + name, name) for name, child in node.items()}
            if isinstance(node, list):
                return [convert(child, path + f"/{index}", key) for index, child in enumerate(node)]
            if node is not None and (key in numeric or key == "thread_size"):
                if key in numeric:
                    if type(node) not in {int, float}:
                        raise RecordsError("Numeric template inputs must be numbers, not strings or booleans.")
                    refs = [name for name in evidence.number_ids if name in numbers and _same(numbers[name].value, node)]
                    if len(refs) != 1:
                        raise RecordsError("Each numeric input must identify one matching printed number.")
                    proof = ValueEvidence(number_ids=refs)
                else:
                    proof = ValueEvidence(source_ids=evidence.source_ids)
                return dict(name=field.name + path, state="known", method=Method.HUMAN_DECISION.value,
                    confidence="sure", value=node, evidence=proof.model_dump(mode="json"),
                    review=_review(event, True).model_dump(mode="json"),
                    unit="count" if key == "count" else "deg" if key.endswith("_deg") else
                         None if key == "thread_size" else "mm")
            return node

        return convert(value)

    def _effective_template(self, template: FlatTemplate) -> FlatTemplate:
        effective = template.model_copy(deep=True)
        for item in self._prepared.review_items:
            if (item.kind != "template_field" or not item.applies_to.startswith(f"{template.part}/template/feature-")
                    or not item.ai_answers):
                continue
            event = self._current_review(item.applies_to, {DecisionType.SET_VALUE, DecisionType.CHOOSE_OPTION})
            if event is None:
                continue
            value = event.value["value"] if isinstance(event.value, dict) and set(event.value) == {"value", "evidence"} else event.value
            if event.status == "accepted" and value == {"kind": "absent"}:
                candidate = item.ai_answers.field_results.get(item.applies_to)
                if candidate and candidate.accepted and candidate.accepted.value == {"kind": "absent"}:
                    effective.features = [field for field in effective.features if field.name != item.applies_to]
                    self._applied.add(event.decision_id)
                    continue
            if not any(field.name == item.applies_to for field in effective.features):
                effective.features.append(UnknownField(name=item.applies_to, method=Method.UNRESOLVED,
                    reason="pending_input", message="Review of the prepared feature interpretation.", provenance=item.ai_answers))
        visited = set()
        while True:
            field = next((f for f in iter_template_fields(effective) if f.name not in visited), None)
            if field is None:
                return effective
            visited.add(field.name)
            event = self._current_review(field.name, {DecisionType.SET_VALUE, DecisionType.CHOOSE_OPTION, DecisionType.CORRECTION})
            if event is None:
                continue
            try:
                if event.status == "rejected":
                    replacement = UnknownField(name=field.name, method=Method.UNRESOLVED,
                        reason="pending_input", message="Prepared interpretation was explicitly rejected.",
                        review=_review(event, True), provenance=field.provenance,
                        review_item=field.review_item, essential=field.essential,
                        evidence=getattr(field, "evidence", ValueEvidence())).model_dump(mode="json")
                    payload = effective.model_dump(mode="json")
                    _replace_field(payload, field.name, replacement)
                    payload["filled_by"] = "human"
                    effective = FlatTemplate.model_validate(payload)
                    self._applied.add(event.decision_id)
                    continue
                replacement = field.model_dump(mode="json")
                if event.type == DecisionType.CHOOSE_OPTION:
                    value, evidence = self._choice(template, field, event)
                else:
                    value = event.value
                    evidence = getattr(field, "evidence", ValueEvidence())
                    previous = self._previous_templates.get(template.part)
                    if previous and previous.source_sha256 == template.source_sha256:
                        prior = next((f for f in iter_template_fields(previous) if f.name == field.name), None)
                        if (prior and prior.state == "known" and prior.review
                                and prior.review.decision_id == event.decision_id):
                            evidence = prior.evidence
                    if isinstance(value, dict) and set(value) == {"value", "evidence"}:
                        evidence = ValueEvidence.model_validate(value["evidence"])
                        value = value["value"]
                    value = (field.value if getattr(field, "state", None) == "known" and
                             _same(template_candidate_value(field.value), value) else
                             self._human_template_value(value, field, evidence, event))
                if isinstance(value, BaseModel):
                    value = value.model_dump(mode="json")
                for key in ("reason", "message", "options", "basis"):
                    replacement.pop(key, None)
                replacement.update(state="known", confidence="sure", method=Method.HUMAN_DECISION.value,
                                   value=value, evidence=evidence.model_dump(mode="json"),
                                   review=_review(event, True).model_dump(mode="json"))
                if "unit" not in replacement and type(value) in {int, float}:
                    suffix = field.name.rsplit("/", 1)[-1]
                    replacement["unit"] = "g" if suffix == "weight-on-drawing" else "count" if suffix == "count" else (
                        "deg" if suffix.endswith("_deg") else "mm")
                payload = effective.model_dump(mode="json")
                _replace_field(payload, field.name, replacement)
                payload["filled_by"] = "human"
                candidate = FlatTemplate.model_validate_json(json.dumps(payload, allow_nan=False), strict=True)
                self._validate_template(candidate, self._drawings[template.part], self._original_drawings.get(template.part))
                effective = candidate
                self._applied.add(event.decision_id)
            except (ValueError, TypeError) as error:
                self._issue(field.name, "invalid_overlay", str(error), event)

    @staticmethod
    def _validate_template(template: FlatTemplate, drawing: DrawingEvidence,
                           original: DrawingEvidence | None = None) -> None:
        # M11 binds the full DrawingEvidence JSON supplied to the template job.
        # The PDF hash remains separately intact on DrawingEvidence itself.
        if template.provenance and original is None and any(field.provenance for field in drawing.fields.values()):
            raise RecordsError("Original deterministic drawing input is required to validate this template snapshot.")
        if original is not None and (original.id != drawing.id or original.source_sha256 != drawing.source_sha256
                                     or original.numbers != drawing.numbers or original.page_geometry != drawing.page_geometry):
            raise RecordsError("Prepared drawing identity differs from its original deterministic input.")
        expected = contract_digest(original or drawing) if template.provenance else drawing.source_sha256
        if template.part != drawing.id or template.source_sha256 != expected:
            raise RecordsError("Template is not bound to its drawing's current source hash.")
        fields = list(iter_template_fields(template))
        names = [field.name for field in fields]
        if len(names) != len(set(names)) or any(not name.startswith(f"{drawing.id}/template/") for name in names):
            raise RecordsError("Template fields require unique names in their drawing's namespace.")
        numbers = {number.name for number in drawing.numbers}
        sources = numbers | {field.name for field in drawing.fields.values()} | {f"{drawing.id}/source"}
        sources.update(f"{drawing.id}/drawing/page/{page.page}" for page in drawing.page_geometry)
        if template.provenance:
            sources.update(template.provenance.source.source_ids)
        for field in fields:
            evidence_items = ([field.evidence] if hasattr(field, "evidence") else [])
            evidence_items += [option.evidence for option in getattr(field, "options", [])]
            for evidence in evidence_items:
                if not set(evidence.number_ids) <= numbers or not set(evidence.source_ids) <= sources:
                    raise RecordsError("Template evidence references a fact outside its drawing.")
                if evidence.derivation and not set(evidence.derivation.inputs) <= sources | set(names):
                    raise RecordsError("Template derivation references a missing source or template field.")
                if (evidence.derivation and evidence.derivation.pattern_fact
                        and evidence.derivation.pattern_fact not in sources | set(names)):
                    raise RecordsError("Template pattern references a missing source or template field.")
            if getattr(field, "state", None) == "known" and type(field.value) in {int, float}:
                _numeric_proof(field.value, field.evidence, drawing)
            for option in getattr(field, "options", []):
                if type(option.value) in {int, float}:
                    _numeric_proof(option.value, option.evidence, drawing)

    def _effective_link(self, drawing: DrawingEvidence, result) -> LinkInfo | None:
        link = result.link.model_copy(deep=True) if result else None
        if result:
            if link.drawing_id != drawing.id:
                raise RecordsError("Link resolution disagrees with its drawing identity.")
            if result.state == "matched":
                if not link.bom_rows or link.method not in _ACCEPTED_LINK_METHODS:
                    raise RecordsError("A matched prep link needs actual accepted rows and a supported method.")
                if link.method == Method.EXACT_MATCH and len(link.bom_rows) != 1:
                    raise RecordsError("An exact filename/name match must select one unique row.")
                self._validate_rows(link.bom_rows)
            elif link.bom_rows:
                raise RecordsError("Unresolved/no-match link states cannot silently attach candidate rows.")
        name = drawing_part_name(drawing.id)
        event = self._current_review(name, {DecisionType.LINK})
        if event is not None and event.status == "rejected":
            link = LinkInfo(method=Method.UNRESOLVED, drawing_id=drawing.id, bom_rows=[],
                basis="Prepared link was explicitly rejected.", review=_review(event, True),
                provenance=link.provenance if link else None,
                prep_field_name=link.prep_field_name if link else None)
            self._applied.add(event.decision_id)
        elif event is not None:
            try:
                rows = event.value
                if isinstance(rows, dict):
                    if set(rows) != {"drawing_id", "bom_rows"} or rows["drawing_id"] != drawing.id:
                        raise RecordsError("A link decision must retain this drawing ID.")
                    rows = rows["bom_rows"]
                self._validate_rows(rows)
                link = LinkInfo(method=Method.HUMAN_DECISION, drawing_id=drawing.id, bom_rows=rows,
                                basis=event.reason or event.note, review=_review(event, True),
                                review_item=link.review_item if link else None,
                                provenance=link.provenance if link else None,
                                prep_field_name=link.prep_field_name if link else None)
                self._applied.add(event.decision_id)
            except (ValueError, TypeError) as error:
                self._issue(name, "invalid_overlay", str(error), event)
        return link

    def _validate_rows(self, rows: JsonValue) -> None:
        if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
            raise RecordsError("A link value must be a list of stable BOM row names.")
        if len(rows) != len(set(rows)):
            raise RecordsError("A link cannot repeat a BOM row.")
        if any(row not in self._rows or len(self._rows[row]) != 1 or row in self._ambiguous for row in rows):
            raise RecordsError("A link names a missing or ambiguous BOM row; no row was selected.")

    def _effective_mapping(self, mapping: NameMapping) -> NameMapping:
        result = mapping.model_copy(deep=True, update={"review": ReviewState()})
        event = self._current_review(mapping.name, {DecisionType.NAME_MAPPING})
        if event is not None and event.status == "rejected":
            result.review = _review(event, True)
            self._applied.add(event.decision_id)
        elif event is not None:
            try:
                value = event.value
                relationship = value.get("relationship") if isinstance(value, dict) else value
                target = value.get("to_name") if isinstance(value, dict) else mapping.to_name
                if isinstance(value, dict) and set(value) != {"relationship", "to_name"}:
                    raise RecordsError("A mapping decision needs relationship and to_name.")
                relationship = MappingRelationship(relationship)
                if relationship == MappingRelationship.NO_EQUIVALENT:
                    target = None
                elif not isinstance(target, str) or not target.strip():
                    raise RecordsError("A mapping relationship needs its recorded target name.")
                elif target != mapping.to_name:
                    raise RecordsError("A mapping decision cannot silently select a different mapping target.")
                result = _validated(result.model_copy(update={"relationship": relationship, "to_name": target,
                    "method": Method.HUMAN_DECISION, "review": _review(event, True)}))
                self._applied.add(event.decision_id)
            except (ValueError, TypeError) as error:
                self._issue(mapping.name, "invalid_overlay", str(error), event)
        else:
            latest = next((e for e in reversed(self._events[mapping.name]) if e.status == "accepted"), None)
            if latest and any(i.decision_id == latest.decision_id and i.code == "source_changed" for i in self._issues):
                result.review = _review(latest, False)
        return result

    @staticmethod
    def _model(previous: PartRecord | None, template: FlatTemplate | None) -> ModelStatus:
        digest = contract_digest(template) if template else None
        model = previous.model.model_copy(deep=True) if previous else ModelStatus(
            state="missing", message="No saved reconstruction is available.")
        model.current_template_sha256 = digest
        if model.state in {"available", "stale"} and (digest is None or model.built_template_sha256 != digest):
            model.state = "stale"
            model.stale_reason = ("No effective saved template is available." if digest is None else
                                  "The saved reconstruction does not match the effective template.")
        return _validated(model)

    @staticmethod
    def _template_candidates(prepared: PreparedKnowledge, originals: Mapping[str, DrawingEvidence]) -> dict[str, FlatTemplate]:
        result = {name: template.model_copy(deep=True) for name, template in prepared.templates.items()}
        # A job with no usable geometry still needs a way for a person to fill
        # its declared fields. The skeleton contains unknowns, never dimensions.
        for drawing in prepared.drawings:
            items = [item for item in prepared.review_items if item.kind == "template_field"
                     and item.applies_to.startswith(f"{drawing.id}/template/") and item.ai_answers]
            if drawing.id in result or not items:
                continue
            record = items[0].ai_answers
            names = {item.applies_to for item in items}
            if not {f"{drawing.id}/template/outline", f"{drawing.id}/template/thickness"} <= names:
                continue
            original = originals.get(drawing.id)
            if original is None or record.source.inputs.get("drawing") != contract_digest(original):
                continue

            def unknown(suffix, essential=False):
                return UnknownField(name=f"{drawing.id}/template/{suffix}", method=Method.UNRESOLVED,
                    reason="pending_input", message="No usable prepared value; awaiting explicit review.",
                    essential=essential, provenance=record)

            result[drawing.id] = FlatTemplate(**RecordRegistry._fixture_markers(prepared.batch),
                part=drawing.id, filled_by=record.mode, provenance=record,
                source_sha256=record.source.inputs["drawing"], outline=unknown("outline", True),
                thickness=unknown("thickness", True),
                material=unknown("material") if f"{drawing.id}/template/material" in names else None,
                weight_on_drawing=unknown("weight-on-drawing") if f"{drawing.id}/template/weight-on-drawing" in names else None,
                features=[unknown(name.rsplit("/", 1)[-1]) for name in sorted(names)
                          if name.rsplit("/", 1)[-1].startswith("feature-")])
        return result

    def _assemble(self, prepared: PreparedKnowledge, previous_records: Sequence[PartRecord],
                  previous_templates: Mapping[str, FlatTemplate]) -> RecordsDocument:
        self._issues, self._applied = [], set()
        self._building_batch = prepared.batch
        self._prepared = prepared
        self._base_templates = self._template_candidates(prepared, self._original_drawings)
        self._base_mappings = prepared.mappings
        self._previous_templates = {identity: _validated(template) for identity, template in previous_templates.items()}
        self._drawings = {drawing.id: drawing for drawing in prepared.drawings}
        if len(self._drawings) != len(prepared.drawings):
            raise RecordsError("Duplicate drawing IDs cannot be overwritten.")
        self._rows = defaultdict(list)
        for row in prepared.bom_rows:
            self._rows[row.name].append(row)
        resolutions = {result.drawing_id: result for result in prepared.links}
        if len(resolutions) != len(prepared.links) or resolutions.keys() - self._drawings.keys():
            raise RecordsError("Prep links repeat or name a missing drawing.")
        if prepared.templates.keys() - self._drawings.keys():
            raise RecordsError("Saved template names a missing drawing.")
        previous = {record.id: _validated(record) for record in previous_records}
        if len(previous) != len(previous_records):
            raise RecordsError("Previous part IDs collide.")
        if any(record.synthetic != prepared.batch.synthetic for record in previous.values()):
            raise RecordsError("Synthetic and real-source records cannot enrich each other.")
        if not prepared.batch.synthetic and any(payload.synthetic for payload in [
                *prepared.templates.values(), *prepared.mappings, *prepared.review_items]):
            raise RecordsError("Synthetic prep payloads cannot enter a real-source records rebuild.")
        self._hash_contexts(prepared)
        journals = self._histories(prepared)
        for event in getattr(self, "_preview_decisions", []):
            self._events[event.applies_to].append(event)
        for drawing in prepared.drawings:
            for number in drawing.numbers:
                event = self._accepted(number.name, {DecisionType.CORRECTION, DecisionType.SET_VALUE})
                if event:
                    self._applied.add(event.decision_id)
        for identity, template in self._base_templates.items():
            self._validate_template(template, self._drawings[identity], self._original_drawings.get(identity))
        templates = {identity: self._effective_template(template)
                     for identity, template in sorted(self._base_templates.items())}
        self._current_templates = templates
        mappings = [self._effective_mapping(mapping) for mapping in sorted(prepared.mappings, key=lambda m: m.name)]
        for item in prepared.review_items:
            if item.kind != "name_mapping" or any(mapping.name == item.applies_to for mapping in mappings):
                continue
            event = self._current_review(item.applies_to, {DecisionType.NAME_MAPPING})
            if event is None:
                continue
            if event.status == "rejected":
                self._applied.add(event.decision_id)
                continue
            try:
                source, target = self.mapping_pair(item)
                value = event.value
                if (not isinstance(value, dict) or set(value) != {"relationship", "to_name"}
                        or value["to_name"] != (None if value["relationship"] == "no_equivalent" else target)):
                    raise RecordsError("A mapping value must retain the recorded target and a supported relationship.")
                mapping = NameMapping(**self._fixture_markers(prepared.batch), name=item.applies_to,
                    kind=item.applies_to.split("/")[1], from_name=source, to_name=value["to_name"],
                    relationship=value["relationship"], method=Method.UNRESOLVED, provenance=item.ai_answers,
                    evidence="general_engineering_knowledge" if "/material/" in item.applies_to else "dataset",
                    evidence_note=item.message)
                mappings.append(self._effective_mapping(mapping))
            except (ValueError, TypeError) as error:
                self._issue(item.applies_to, "invalid_overlay", str(error), event)
        if len({mapping.name for mapping in mappings}) != len(mappings):
            raise RecordsError("Saved mapping names collide.")
        rows = {name: [row.model_copy(deep=True, update={
                    "identity_conflict": row.identity_conflict or len(group) > 1,
                    "fields": {key: self._overlay_field(field) for key, field in row.fields.items()}})
                      for row in group] for name, group in self._rows.items()}
        records, linked = [], set()
        for identity, drawing in sorted(self._drawings.items()):
            effective_drawing = drawing.model_copy(deep=True, update={
                "fields": {key: self._overlay_field(field) for key, field in drawing.fields.items()}})
            link = self._effective_link(drawing, resolutions.get(identity))
            attached = [rows[name][0] for name in sorted(link.bom_rows)] if link else []
            linked.update(row.name for row in attached)
            name = drawing_part_name(identity)
            records.append(self._record(name, effective_drawing, attached, link, templates.get(identity), previous.get(name)))
        for name, group in sorted(rows.items()):
            if name not in linked:
                identity = f"{name}/part"
                records.append(self._record(identity, None, group, None, None, previous.get(identity)))
        items = self._review_queue(prepared, records, mappings)
        by_part = defaultdict(dict)
        for item in items:
            related = {item.part_id} | {source.target.part_id for source in item.sources}
            for part_id in related - {None}:
                by_part[part_id][item.id] = ReviewLink(id=item.id, href=review_api_path(item.id))
        for record in records:
            refs = {ref.id: ref for ref in record.review_items}
            refs.update(by_part[record.id])
            if record.link and record.link.review_item:
                refs[record.link.review_item.id] = record.link.review_item
            if record.drawing and record.drawing.id in templates:
                refs.update({field.review_item.id: field.review_item for field in
                             iter_template_fields(templates[record.drawing.id]) if field.review_item})
            record.review_items = [refs[key] for key in sorted(refs)]
        known = set(self._hashes) | {record.id for record in records}
        for journal in journals:
            for event in journal.decisions:
                if event.applies_to not in known:
                    self._issue(event.applies_to, "missing_target", "Decision target is absent from current source evidence.", event)
        return RecordsDocument(prepared=prepared.model_copy(deep=True), records=records,
                               templates=templates, mappings=mappings, review_items=items,
                               decision_journals=journals, overlay_issues=self._issues)

    def _record(self, identity: str, drawing: DrawingEvidence | None, rows: list[BOMRow],
                link: LinkInfo | None, template: FlatTemplate | None, previous: PartRecord | None) -> PartRecord:
        model = self._model(previous, template)
        section = _unique([_text(row.fields.get("section")) if "section" in row.fields else row.section for row in rows])
        display = (_text(drawing.fields.get("title")) or drawing.id) if drawing else (
            _unique([_text(row.fields.get("name")) if "name" in row.fields else row.display_name for row in rows]) or identity)
        metadata = {key: deepcopy(getattr(previous, key)) for key in _PART_ADDITIONS} if previous else {}
        markers = self._fixture_markers(previous)
        # PreparedKnowledge is internal ContractModel; its batch and templates
        # retain the explicit fixture declaration used by isolated software tests.
        if self._building_synthetic:
            markers = self._fixture_markers(self._building_batch)
        return PartRecord(**markers, id=identity, display_name=display, section=section,
                          has_drawing=drawing is not None, has_3d=model.state in {"available", "stale"},
                          examples=[example.id for example in model.examples], drawing=drawing, bom=deepcopy(rows),
                          link=link, template=f"records:templates/{drawing.id}" if template and drawing else None,
                          model=model, review_items=deepcopy(previous.review_items) if previous else [], **metadata)

    @staticmethod
    def _fixture_markers(payload) -> dict:
        return ({"fixture": payload.fixture, "synthetic": payload.synthetic, "fixture_note": payload.fixture_note}
                if payload is not None else {})

    @property
    def _building_synthetic(self) -> bool:
        return self._building_batch.synthetic

    def _review_queue(self, prepared: PreparedKnowledge, records: list[PartRecord],
                      mappings: list[NameMapping]) -> list[ReviewItem]:
        owners = defaultdict(set)
        evidence = defaultdict(list)
        for record in records:
            owners[record.id].add(record.id)
            if record.drawing:
                for field in record.drawing.fields.values():
                    owners[field.name].add(record.id)
                    evidence[field.name].append(self._field_source(field, record.id, drawing=record.drawing))
                for number in record.drawing.numbers:
                    owners[number.name].add(record.id)
            if record.drawing and record.drawing.id in self._current_templates:
                for field in iter_template_fields(self._current_templates[record.drawing.id]):
                    owners[field.name].add(record.id)
            for row in record.bom:
                for name in [row.name, f"{row.name}/part", *[field.name for field in row.fields.values()]]:
                    owners[name].add(record.id)
                for field in row.fields.values():
                    evidence[field.name].append(self._field_source(field, record.id, row=row))
        items = {}
        for original in prepared.review_items:
            if original.id in items:
                raise RecordsError("Saved review item IDs collide.")
            item = original.model_copy(deep=True)
            if self._building_synthetic:
                item = item.model_copy(update=self._fixture_markers(self._building_batch))
            target = self._decision_name(item)
            item.proposal_id = prepared_proposal_id(original)
            context = self._hashes.get(target, {})
            source_current = bool(original.source_hashes) and all(
                context.get(key) == digest for key, digest in original.source_hashes.items()) and all(
                source.source_sha256 is None or context.get(source.name) == source.source_sha256
                for source in original.sources)
            if not source_current:
                item.status = "source_changed"
            event = next((e for e in reversed(self._events[target]) if e.status in {"accepted", "rejected"}
                          and (e.proposal_id is None or e.proposal_id == item.proposal_id)), None)
            if event:
                current = (source_current and bool(set(event.based_on).intersection(self._anchors.get(target, set())))
                           and all(self._hashes.get(target, {}).get(k) == v for k, v in event.based_on.items()))
                if not current or event.status == "rejected" or event.decision_id in self._applied:
                    item.status = event.status if current else "source_changed"
                    item.review = _review(event, current)
                    if current and event.status == "rejected":
                        item.review.status = ReviewStatus.HUMAN_REJECTED
                    item.updated_at = event.at
                    item.current_value = deepcopy(event.old_value)
                    item.proposed_value = deepcopy(template_candidate_value(event.value["value"]) if
                        isinstance(event.value, dict) and set(event.value) == {"value", "evidence"} else event.value)
                    item.ai_answers = deepcopy(event.ai_answers)
                    if event.note is not None:
                        item.message += f"\nReview note: {event.note}"
            mapped = next((mapping for mapping in mappings if mapping.name == item.applies_to), None)
            if mapped:
                item.mapping = mapped.model_copy(deep=True)
            if item.status != "pending":
                item.allowed_actions = []
            if item.part_id is None and len(owners[target]) == 1:
                item.part_id = next(iter(owners[target]))
            for source in item.sources:
                if len(owners[source.name]) == 1:
                    source.target.part_id = next(iter(owners[source.name]))
            items[item.id] = item
        for target, events in sorted(self._events.items()):
            for event in events:
                if event.status != "pending" or any(e.status != "pending" and
                        (e.supersedes == event.decision_id or e.proposal_id == (event.proposal_id or event.decision_id))
                        for e in events):
                    continue
                if any(item.proposal_id == (event.proposal_id or event.decision_id) for item in items.values()):
                    continue
                kind = ("link" if event.type == DecisionType.LINK else "name_mapping" if
                        event.type == DecisionType.NAME_MAPPING else "template_field" if "/template/" in target else "correction")
                identity = f"review/decision/{event.decision_id}"
                items[identity] = ReviewItem(**self._fixture_markers(event), id=identity, kind=kind,
                    applies_to=target, part_id=next(iter(owners[target])) if len(owners[target]) == 1 else None,
                    status="pending", title="Saved proposal", message=event.reason or event.note or "Saved proposal awaits review.",
                    current_value=event.old_value, proposed_value=event.value, source_hashes=event.based_on,
                    ai_answers=event.ai_answers, check_result=event.check_result,
                    sources=deepcopy(evidence[target]),
                    allowed_actions=[ReviewAction.ACCEPT, ReviewAction.REJECT],
                    proposal_id=event.proposal_id or event.decision_id, created_at=event.at, updated_at=event.at)
        return [items[key] for key in sorted(items)]

    def _index(self) -> None:
        self._parts = {record.id: record for record in self._document.records}
        self._owners, self._sources, self._fields = defaultdict(set), defaultdict(list), defaultdict(list)
        for record in self._document.records:
            drawing = record.drawing
            self._add_source(record.id, FactSource(name=record.id,
                says={"drawing_id": drawing.id if drawing else None, "bom_rows": [row.name for row in record.bom]},
                method=record.link.method if record.link else Method.PARSED,
                source_sha256=drawing.source_sha256 if drawing else (
                    record.bom[0].source_sha256 if len(record.bom) == 1 else None),
                target=SourceTarget(kind="part", name=record.id, part_id=record.id,
                                    drawing_id=drawing.id if drawing else None)))
            if drawing:
                if drawing.id in self._manifest_sections:
                    name = f"{drawing.id}/manifest/section"
                    self._add_source(name, FactSource(name=name, says=self._manifest_sections[drawing.id],
                        method=Method.PARSED, source_sha256=self._manifest_sha256,
                        target=SourceTarget(kind="drawing", name=name, part_id=record.id, drawing_id=drawing.id)))
                self._owners[drawing.id].add(record.id)
                self._owners[f"{drawing.id}/link"].add(record.id)
                source_name = f"{drawing.id}/source"
                self._add_source(source_name, FactSource(name=source_name,
                    says={"source_path": drawing.source_path, "source_sha256": drawing.source_sha256},
                    method=Method.PARSED, source_sha256=drawing.source_sha256,
                    target=SourceTarget(kind="drawing", name=source_name, part_id=record.id, drawing_id=drawing.id)))
                for page in drawing.page_geometry:
                    name = f"{drawing.id}/drawing/page/{page.page}"
                    self._add_source(name, FactSource(name=name, says=page.model_dump(mode="json"),
                        method=Method.PARSED, source_sha256=drawing.source_sha256, source_quality=drawing.source_quality,
                        target=SourceTarget(kind="drawing", name=name, part_id=record.id, drawing_id=drawing.id,
                                            page=page.page, box=(0, 0, page.source_width, page.source_height))))
                for field in drawing.fields.values():
                    self._evidence_source(field, record.id, drawing=drawing)
                for number in drawing.numbers:
                    self._fields[number.name].append(number)
                    self._add_source(number.name, FactSource(name=number.name, says=number.text, method=Method.PARSED,
                        confidence=number.confidence, source_quality=drawing.source_quality,
                        source_sha256=drawing.source_sha256,
                        target=SourceTarget(kind="drawing", name=number.name, part_id=record.id,
                                            drawing_id=drawing.id, page=number.page, box=number.box)))
            for row in record.bom:
                self._owners[f"{row.name}/part"].add(record.id)
                if f"{row.name}/part" != record.id:
                    alias = f"{row.name}/part"
                    self._add_source(alias, FactSource(name=alias, says={"row_name": row.name},
                        method=record.link.method, source_sha256=row.source_sha256,
                        target=SourceTarget(kind="part", name=alias, part_id=record.id, row_name=row.name,
                                            drawing_id=drawing.id if drawing else None)))
                self._add_source(row.name, FactSource(name=row.name,
                    says={key: field.original for key, field in row.fields.items()}, method=Method.PARSED,
                    source_sha256=row.source_sha256,
                    target=SourceTarget(kind="bom", name=row.name, part_id=record.id, row_name=row.name)))
                for field in row.fields.values():
                    self._evidence_source(field, record.id, row=row)
            for passage in record.readme_passages or []:
                self._add_source(passage.name, FactSource(name=passage.name, says=passage.text,
                    method=Method.PARSED, source_sha256=passage.source_sha256,
                    target=SourceTarget(kind="readme", name=passage.name)))
            for callout in record.callouts or []:
                self._add_source(callout.name, FactSource(name=callout.name, says=callout.text,
                    method=Method.PARSED, source_sha256=drawing.source_sha256 if drawing else None,
                    target=callout.target.model_copy(deep=True)))
        for identity, template in self._document.templates.items():
            self._owners[f"records:templates/{identity}"].add(drawing_part_name(identity))
            originals = {field.name: field for field in iter_template_fields(self._base_templates[identity])}
            for field in iter_template_fields(template):
                self._fields[field.name].append(field)
                original = originals.get(field.name, field)
                self._add_source(field.name, FactSource(name=field.name, says=original.model_dump(mode="json"),
                    method=field.method, confidence=field.confidence, review=field.review,
                    provenance=original.provenance, source_sha256=template.source_sha256,
                    target=SourceTarget(kind="template", name=field.name,
                                        part_id=drawing_part_name(identity), drawing_id=identity)))
        for template in self._document.templates.values():
            for field in iter_template_fields(template):
                evidence = ([field.evidence] if hasattr(field, "evidence") else [])
                evidence += [option.evidence for option in getattr(field, "options", [])]
                references = set()
                for proof in evidence:
                    references.update(proof.number_ids + proof.source_ids)
                    if proof.derivation:
                        references.update(proof.derivation.inputs)
                        if proof.derivation.pattern_fact:
                            references.add(proof.derivation.pattern_fact)
                for reference in sorted(references - {field.name}):
                    # Only existing source targets supply highlights. No box is
                    # invented for an opaque preparation/group reference.
                    self._sources[field.name].extend(source.model_copy(deep=True)
                                                     for source in list(self._sources.get(reference, ())))
        for identity, template in self._document.templates.items():
            actual = {field.name for field in iter_template_fields(template)}
            for field in self.template_fields(drawing_part_name(identity)):
                if field.name in actual:
                    continue
                self._fields[field.name].append(field)
                self._add_source(field.name, FactSource(name=field.name, says=field.value, method=field.method,
                    review=field.review, provenance=field.provenance,
                    source_sha256=self._drawings[identity].source_sha256,
                    target=SourceTarget(kind="template", name=field.name, part_id=drawing_part_name(identity), drawing_id=identity)))

    def _add_source(self, key: str, source: FactSource) -> None:
        self._sources[key].append(source)
        if source.target.part_id:
            self._owners[key].add(source.target.part_id)

    def _evidence_source(self, field: EvidenceField, part_id: str, *,
                         drawing: DrawingEvidence | None = None, row: BOMRow | None = None) -> None:
        self._fields[field.name].append(field)
        self._add_source(field.name, self._field_source(field, part_id, drawing=drawing, row=row))

    @staticmethod
    def _field_source(field: EvidenceField, part_id: str, *,
                      drawing: DrawingEvidence | None = None, row: BOMRow | None = None) -> FactSource:
        target = SourceTarget(kind="drawing" if drawing else "bom", name=field.name, part_id=part_id,
                              drawing_id=drawing.id if drawing else None, row_name=row.name if row else None,
                              page=field.page if drawing else None, box=field.box if drawing else None)
        return FactSource(name=field.name, says=field.original, method=field.method,
            confidence=field.confidence, note=field.note, review=field.review, provenance=field.provenance,
            source_sha256=drawing.source_sha256 if drawing else row.source_sha256,
            source_quality=field.source_quality if drawing else None, target=target)
