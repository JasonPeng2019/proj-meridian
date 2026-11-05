"""Frozen M02 payloads and boundaries. No I/O, chat, router, or CAD imports.

JSON uses snake_case in both languages. contracts.ts mirrors the Pydantic schema;
the focused B00 checker verifies that mirror. Reserved M2/M3 shapes are contracts,
not a claim that their endpoints or behavior have been implemented.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Callable, Generic, Literal, Protocol, Sequence, TypeVar
from urllib.parse import quote, unquote

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StringConstraints,
    TypeAdapter, model_validator,
)


SCHEMA_NAME = "meridian-contracts"
RECONSTRUCTION_LABEL = "Reconstruction from 2D drawing. Not the original CAD model."
SINGLE_MODEL_LABEL = "Single-model fallback: Sol only; Opus output unavailable."
CHAT_MODEL = "gpt-6-luna"
NonEmpty = Annotated[str, StringConstraints(min_length=1)]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]
Box = tuple[float, float, NonNegative, NonNegative]  # x/y may lie outside a clipped viewport.
Point = tuple[float, float]
Vector3 = tuple[float, float, float]


def normalize_component(value: str) -> str:
    # One rule for ALL descriptive components: NFKC, lowercase, ASCII a-z/0-9/_/-;
    # replace other runs with '-', collapse '-', trim. Preserve D-/BOM: namespaces.
    # Collisions (including duplicate BOM names) must be flagged, never auto-suffixed.
    result = re.sub(r"[^a-z0-9_-]+", "-", unicodedata.normalize("NFKC", value).lower())
    result = re.sub(r"-+", "-", result).strip("-")
    if not result:
        raise ValueError("Stable-name component has no usable characters")
    return result


def drawing_id(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"D-\d{3}", value):
        raise ValueError("Drawing ID must be D- followed by three digits")
    return value


def drawing_fact_name(drawing: str, field: str) -> str:
    return f"{drawing_id(drawing)}/drawing/{normalize_component(field)}"


def template_fact_name(drawing: str, field: str) -> str:
    return f"{drawing_id(drawing)}/template/{normalize_component(field)}"


def drawing_part_name(drawing: str) -> str:
    return f"{drawing_id(drawing)}/part"


def drawing_number_name(drawing: str, token: str, occurrence: int) -> str:
    # Occurrences are 1-based in deterministic page/box reading order, after dedup.
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 1:
        raise ValueError("Number occurrence must be positive")
    return f"{drawing_id(drawing)}/drawing/n/{normalize_component(token)}@{occurrence}"


def bom_row_name(section: str, name: str) -> str:
    return f"BOM:{normalize_component(section)}/{normalize_component(name)}"


def bom_fact_name(section: str, name: str, field: str) -> str:
    return f"{bom_row_name(section, name)}/{normalize_component(field)}"


def bom_part_name(section: str, name: str) -> str:
    return f"{bom_row_name(section, name)}/part"


def mapping_name(kind: Literal["section", "material"], source: str, target: str) -> str:
    return f"names/{kind}/{normalize_component(source)} -> {normalize_component(target)}"


def readme_name(section: str, paragraph: int) -> str:
    if not isinstance(paragraph, int) or isinstance(paragraph, bool) or paragraph < 1:
        raise ValueError("Paragraph index must be positive")
    return f"README/{normalize_component(section)}/p{paragraph}"


def encode_id(value: str) -> str:
    # Encode the ENTIRE stable name as one RFC3986 segment, including '/' and ':'.
    # Server routes with IDs need a path converter; register /image,/history,/crop
    # suffix routes before the generic part route. Framework-decoded IDs are final:
    # never unquote again (literal '%2F' must survive as literal text).
    return quote(value, safe="", encoding="utf-8", errors="strict")


def decode_id(segment: str) -> str:
    if "/" in segment or re.search(r"%(?![0-9a-fA-F]{2})", segment):
        raise ValueError("Expected a single percent-encoded ID segment")
    return unquote(segment, encoding="utf-8", errors="strict")


def part_api_path(part_id: str) -> str:
    return f"/api/parts/{encode_id(part_id)}"


def image_api_path(part_id: str, page: int = 1, thumb: bool = False) -> str:
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("Page numbers are 1-based")
    return f"{part_api_path(part_id)}/image?page={page}&thumb={int(thumb)}"


def review_api_path(item_id: str) -> str:
    return f"/api/review/{encode_id(item_id)}"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Payload(ContractModel):
    # Fixture metadata travels with payloads and must never imply real evidence.
    fixture: bool = False
    synthetic: bool = False
    fixture_note: str | None = None

    @model_validator(mode="after")
    def declared_fixture(self) -> Payload:
        if self.fixture or self.synthetic:
            if not (self.fixture and self.synthetic and self.fixture_note and self.fixture_note.strip()):
                raise ValueError("Synthetic fixtures need both markers and a short note")
        return self


class PageGeometry(ContractModel):
    page: int = Field(ge=1)
    source_width: Positive
    source_height: Positive
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)


def _box_transform(box: Sequence[float], page: PageGeometry, zoom: float,
                   offset: Point, inverse: bool) -> Box:
    if len(box) != 4 or not all(math.isfinite(v) for v in (*box, zoom, *offset)):
        raise ValueError("Box, zoom, and offset must be finite")
    if zoom <= 0 or box[2] < 0 or box[3] < 0:
        raise ValueError("Zoom must be positive; box sizes cannot be negative")
    sx = page.image_width / page.source_width * zoom
    sy = page.image_height / page.source_height * zoom
    x, y, width, height = box
    if inverse:
        return ((x - offset[0]) / sx, (y - offset[1]) / sy, width / sx, height / sy)
    return (x * sx + offset[0], y * sy + offset[1], width * sx, height * sy)


def source_box_to_pixels(box: Box, page: PageGeometry, zoom: float = 1,
                         offset: Point = (0, 0)) -> Box:
    # Pages are 1-based. Box=[x,y,width,height], top-left origin, x right/y down.
    # Extractors first apply PDF crop/rotation to the saved page coordinate frame.
    # Source units are PDF points (or explicit scan units), NEVER assumed pixels.
    # Actual raster width/height determine both scales; zoom multiplies them.
    # Output is rendered-image/CSS pixels; offset handles padding/letterboxing.
    return _box_transform(box, page, zoom, offset, False)


def pixel_box_to_source(box: Box, page: PageGeometry, zoom: float = 1,
                         offset: Point = (0, 0)) -> Box:
    return _box_transform(box, page, zoom, offset, True)


class Method(StrEnum):
    PARSED = "parsed"
    CLEANUP_RULE = "cleanup_rule"
    EXACT_MATCH = "exact_match"
    AI_READ = "ai_read"
    AI_AGREED = "ai_agreed"
    AI_AGREED_AFTER_RETRY = "ai_agreed_after_retry"
    AI_SINGLE_MODEL = "ai_single_model"
    HUMAN_DECISION = "human_decision"
    UNRESOLVED = "unresolved"


class Confidence(StrEnum):
    SURE = "sure"
    UNSURE = "unsure"


class SourceQuality(StrEnum):
    CLEAN = "clean"
    DEGRADED = "degraded"
    MISSING = "missing"


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    HUMAN_CONFIRMED = "human_confirmed"
    HUMAN_REJECTED = "human_rejected"
    SOURCE_CHANGED = "source_changed"  # Reserved M2: historical approval is retained.


class ReviewState(ContractModel):
    status: ReviewStatus = ReviewStatus.NOT_REVIEWED
    by: NonEmpty | None = None
    at: AwareDatetime | None = None
    based_on: dict[str, SHA256] = Field(default_factory=dict)
    decision_id: str | None = None

    @model_validator(mode="after")
    def attribution(self) -> ReviewState:
        if self.status != ReviewStatus.NOT_REVIEWED and not (self.by and self.at):
            raise ValueError("Reviewed/source-changed state retains reviewer and time")
        return self


class ReviewLink(ContractModel):
    id: NonEmpty
    href: NonEmpty


class ReaderSettings(ContractModel):
    provider: Literal["codex_cli", "claude_code"]
    model: NonEmpty
    reasoning: NonEmpty
    service_tier: NonEmpty  # Codex 'fast' is priority; Opus uses 'regular'.
    read_only: Literal[True] = True
    settings: dict[str, JsonValue] = Field(default_factory=dict)


class FailureClass(StrEnum):
    OAUTH = "oauth"
    USAGE_LIMIT = "usage_limit"
    RATE_LIMIT = "rate_limit"
    INVOCATION = "invocation"
    MISSING_CLI = "missing_cli"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROVIDER_ERROR = "provider_error"
    OUTPUT_PARSE = "output_parse"
    OUTPUT_SCHEMA = "output_schema"
    EVIDENCE_INVALID = "evidence_invalid"
    UNKNOWN_EXECUTION = "unknown_execution"


class ReaderFailure(ContractModel):
    classification: FailureClass
    execution_failure: bool
    message: NonEmpty  # Redacted diagnostic, never credentials or raw CLI auth.
    exit_code: int | None = None
    retryable: bool = False
    troubleshooting: list[str] = Field(default_factory=list)
    diagnostic_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def failure_kind(self) -> ReaderFailure:
        invalid = self.classification in {
            FailureClass.OUTPUT_PARSE, FailureClass.OUTPUT_SCHEMA, FailureClass.EVIDENCE_INVALID,
        }
        if invalid and self.execution_failure:
            raise ValueError("Invalid/unsure answers cannot authorize single-model fallback")
        return self


class ReaderAnswer(ContractModel):
    state: Literal["known", "options", "unknown", "value", "match", "no_match", "relationship"]
    value: JsonValue = None
    options: list[JsonValue] = Field(default_factory=list)
    confidence: Confidence
    source_ids: list[str] = Field(default_factory=list)
    reason: NonEmpty
    schema_valid: bool = True
    evidence_valid: bool = True


class ReaderOutput(ContractModel):
    answers: dict[str, ReaderAnswer]
    output_sha256: SHA256


class ReaderAttempt(ContractModel):
    requested: ReaderSettings
    effective: ReaderSettings | None  # Null means the CLI never confirmed an identity.
    status: Literal["success", "execution_failed", "invalid_output"]
    output: ReaderOutput | None  # Missing Opus is ALWAYS null, never a second Sol answer.
    failure: ReaderFailure | None = None
    prior_failures: list[ReaderFailure] = Field(default_factory=list)
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def truthful_output(self) -> ReaderAttempt:
        if self.status == "success" and (self.output is None or self.effective is None or self.failure):
            raise ValueError("Successful reader needs actual identity/output and no current failure")
        if self.status == "execution_failed":
            if self.output is not None or not self.failure or not self.failure.execution_failure:
                raise ValueError("Failed execution needs classified failure and no invented output")
        if self.status == "invalid_output" and (not self.failure or self.failure.execution_failure):
            raise ValueError("Invalid output must be classified separately from execution failure")
        return self


class PrepRound(ContractModel):
    round: Literal[1, 2]
    sol: ReaderAttempt
    opus: ReaderAttempt


class PrepProvenance(ContractModel):
    job: NonEmpty
    job_id: NonEmpty
    mode: Literal["dual_reader", "single_model"]
    outcome: Literal["agreed", "agreed_after_retry", "single_model_fallback", "unresolved"]
    rounds: list[PrepRound] = Field(min_length=1, max_length=2)
    inputs: dict[str, SHA256]
    prompt_sha256: SHA256
    output_contract_sha256: SHA256
    cache_key: SHA256  # Hash inputs, prompts, contracts, actual settings, and mode.
    next_launch_attempt_opus: Literal[True] = True

    @model_validator(mode="after")
    def independent_readers(self) -> PrepProvenance:
        if [r.round for r in self.rounds] != list(range(1, len(self.rounds) + 1)):
            raise ValueError("Preserve the initial round and at most one mutual-feedback round")
        for round_ in self.rounds:
            for attempt, provider, model in (
                (round_.sol, "codex_cli", "gpt-6.1-sol"),
                (round_.opus, "claude_code", "claude-opus-5-5"),
            ):
                if (attempt.requested.provider, attempt.requested.model) != (provider, model):
                    raise ValueError("Each launch must request the independent Sol/Opus pair")
        last = self.rounds[-1]
        if self.mode == "single_model":
            if (self.outcome != "single_model_fallback" or len(self.rounds) != 1
                    or last.sol.status != "success" or last.opus.status != "execution_failed"):
                raise ValueError("Sol-only fallback requires an actual failed Opus execution")
            assert last.sol.output is not None
            if not last.sol.output.answers or not all(
                a.confidence == Confidence.SURE and a.schema_valid and a.evidence_valid
                and a.state != "unknown" for a in last.sol.output.answers.values()
            ):
                raise ValueError("Fallback accepts only sure, valid, source-validated Sol answers")
        elif self.outcome == "single_model_fallback":
            raise ValueError("Fallback must not be counted as dual-reader agreement")
        if self.outcome in {"agreed", "agreed_after_retry", "single_model_fallback"}:
            sol = last.sol.effective
            if sol is None or (sol.provider, sol.model) != ("codex_cli", "gpt-6.1-sol"):
                raise ValueError("Accepted output must retain the actual Sol identity")
        if self.outcome in {"agreed", "agreed_after_retry"}:
            opus = last.opus.effective
            if (last.sol.status != "success" or last.opus.status != "success" or opus is None
                    or (opus.provider, opus.model) != ("claude_code", "claude-opus-5-5")):
                raise ValueError("Independent agreement needs two actual different readers")
            if (self.outcome == "agreed_after_retry") != (len(self.rounds) == 2):
                raise ValueError("Retry agreement must retain both rounds")
        return self


class PrepCounts(ContractModel):
    dual_reader_items: int = Field(ge=0)
    agreed: int = Field(ge=0)
    agreed_after_retry: int = Field(ge=0)
    dual_reader_unresolved: int = Field(ge=0)
    single_model_fallback: int = Field(ge=0)  # Outside BOTH dual agreement numerator/denominator.
    execution_failed: int = Field(ge=0)


class Correction(ContractModel):
    original: JsonValue
    corrected: JsonValue
    by: NonEmpty
    at: AwareDatetime
    decision_id: NonEmpty


class EvidenceField(ContractModel):
    name: NonEmpty
    original: str | None
    value: JsonValue
    confidence: Confidence = Confidence.SURE
    method: Method
    note: str | None = None
    review: ReviewState | None = None
    provenance: PrepProvenance | None = None
    correction: Correction | None = None  # Overlay; original is never replaced.

    @model_validator(mode="after")
    def ai_provenance(self) -> EvidenceField:
        if self.method == Method.AI_SINGLE_MODEL:
            if self.provenance is None or self.provenance.mode != "single_model":
                raise ValueError("Single-model method needs explicit fallback provenance")
        if self.method in {Method.AI_READ, Method.AI_AGREED, Method.AI_AGREED_AFTER_RETRY}:
            if self.provenance is None or self.provenance.mode != "dual_reader":
                raise ValueError("Dual-reader method needs independent-reader provenance")
        return self


class DrawingField(EvidenceField):
    page: int = Field(ge=1)
    box: Box
    source_quality: SourceQuality


class DrawingNumber(ContractModel):
    name: NonEmpty
    text: NonEmpty
    value: float
    page: int = Field(ge=1)
    box: Box
    unit: str | None = None
    confidence: Confidence = Confidence.SURE
    method: Literal["parsed"] = "parsed"


class DrawingWord(ContractModel):
    text: NonEmpty
    page: int = Field(ge=1)
    box: Box


class DrawingEvidence(ContractModel):
    id: NonEmpty
    pages: int = Field(ge=1)
    image: NonEmpty  # First page asset; page_geometry covers every page.
    page_geometry: list[PageGeometry] = Field(min_length=1)
    degraded: bool
    source_quality: SourceQuality
    source_path: NonEmpty
    source_sha256: SHA256
    fields: dict[str, DrawingField]
    numbers: list[DrawingNumber] = Field(default_factory=list)
    words: list[DrawingWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def owned_pages(self) -> DrawingEvidence:
        drawing_id(self.id)
        if sorted(p.page for p in self.page_geometry) != list(range(1, self.pages + 1)):
            raise ValueError("Each drawing page needs exactly one geometry entry")
        for field in [*self.fields.values(), *self.numbers, *self.words]:
            if field.page > self.pages:
                raise ValueError("Evidence references a page outside its drawing")
        if any(not f.name.startswith(f"{self.id}/drawing/")
               for f in [*self.fields.values(), *self.numbers]):
            raise ValueError("Drawing facts retain their own source namespace")
        return self


class BOMField(EvidenceField):
    cleanup: list[str] = Field(default_factory=list)
    snapshot_note: bool = False
    currency: Literal["DKK"] | None = None
    unit: str | None = None


class ConnectionEvidence(ContractModel):
    name: NonEmpty  # Stable name of the 'Interface with' evidence cell.
    original: NonEmpty
    target_name: NonEmpty
    target_row: str | None = None
    target_part: str | None = None
    resolved: bool
    note: str | None = None


class BOMRow(ContractModel):
    name: NonEmpty  # BOM:<normalized-section>/<normalized-name>; no trailing /part.
    display_id: NonEmpty  # BOM-xxx is a display ID only, never a decision key.
    display_name: NonEmpty
    section: NonEmpty
    source_sha256: SHA256
    fields: dict[str, BOMField]
    connections: list[ConnectionEvidence] = Field(default_factory=list)
    identity_conflict: bool = False
    snapshot_note: bool = True

    @model_validator(mode="after")
    def owned_fields(self) -> BOMRow:
        if not self.name.startswith("BOM:") or any(
            not f.name.startswith(f"{self.name}/") for f in self.fields.values()
        ):
            raise ValueError("BOM evidence retains its own source namespace")
        return self


class LinkInfo(ContractModel):
    method: Method
    drawing_id: str | None
    bom_rows: list[str]
    basis: str | None = None
    review: ReviewState | None = None
    review_item: ReviewLink | None = None
    provenance: PrepProvenance | None = None


class MappingRelationship(StrEnum):
    SAME = "same"
    KIND_OF = "kind_of"  # Direction is from_name -> to_name (specific -> family).
    DIFFERENT = "different"
    NO_EQUIVALENT = "no_equivalent"


class NameMapping(Payload):
    name: NonEmpty
    kind: Literal["section", "material"]
    from_name: NonEmpty
    to_name: str | None
    relationship: MappingRelationship
    evidence: Literal["dataset", "general_engineering_knowledge"]
    evidence_note: NonEmpty
    method: Method
    review: ReviewState = Field(default_factory=ReviewState)
    review_item: ReviewLink | None = None
    provenance: PrepProvenance | None = None
    # Every mapping, even exact/AI-agreed, is unusable until human_confirmed.


class SourceTarget(ContractModel):
    kind: Literal["drawing", "bom", "template", "part", "readme"]
    name: NonEmpty
    part_id: str | None = None  # README has no owning part.
    drawing_id: str | None = None
    row_name: str | None = None
    page: int | None = Field(default=None, ge=1)
    box: Box | None = None


class CropReference(ContractModel):  # Reserved M3; PNG, using the same source box.
    url: NonEmpty
    target: SourceTarget
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class FactSource(ContractModel):
    name: NonEmpty
    says: JsonValue  # Verbatim original, including unsure/garbled text and null.
    method: Method
    target: SourceTarget
    source_sha256: SHA256 | None = None
    confidence: Confidence = Confidence.SURE
    source_quality: SourceQuality | None = None
    note: str | None = None
    review: ReviewState | None = None
    provenance: PrepProvenance | None = None
    crop: CropReference | None = None


class ValueDisplay(ContractModel):
    state: Literal["value"] = "value"
    value: JsonValue
    label: str | None = None  # E.g. 'Materials recorded:', never a manufacturing claim.
    unit: str | None = None


class OptionsDisplay(ContractModel):
    state: Literal["options"] = "options"
    values: list[JsonValue] = Field(min_length=2)
    message: NonEmpty
    unit: str | None = None


class UndeterminedReason(StrEnum):
    MISSING = "missing"
    UNREADABLE_SCAN = "unreadable_scan"
    UNSURE_SOURCE = "unsure_source"
    UNLABELLED_MEASUREMENT = "unlabelled_measurement"
    SOURCE_CONFLICT = "source_conflict"
    UNMAPPED_NAMES = "unmapped_names"
    UNLINKED = "unlinked"
    MODEL_DISAGREEMENT = "model_disagreement"
    MODEL_UNSURE = "model_unsure"
    INVALID_AI_ANSWER = "invalid_ai_answer"
    PENDING_INPUT = "pending_input"
    SOURCE_CHANGED = "source_changed"
    UNSUPPORTED_QUESTION = "unsupported_question"


class UndeterminedDisplay(ContractModel):
    state: Literal["undetermined"] = "undetermined"
    reason: UndeterminedReason
    message: NonEmpty


FactDisplay = Annotated[ValueDisplay | OptionsDisplay | UndeterminedDisplay, Field(discriminator="state")]


class FactResult(Payload):
    fact: NonEmpty
    part_id: str | None
    display: FactDisplay
    rule: NonEmpty
    badge: NonEmpty  # Human-readable provenance; separate from 'Undetermined'.
    provenance_badge: str | None = None  # Single-model fallback is always disclosed.
    review: ReviewState | None = None  # Null for rule-based/human values.
    sources: list[FactSource] = Field(min_length=1)
    snapshot_note: bool = False
    review_item: ReviewLink | None = None  # Only an actual item permits 'Waiting for review'.
    correction: Correction | None = None


class Derivation(ContractModel):
    kind: Literal["arithmetic", "pattern"]
    expression: NonEmpty  # Explanation, not executable code.
    inputs: list[NonEmpty] = Field(min_length=1)
    pattern_fact: str | None = None


class ValueEvidence(ContractModel):
    number_ids: list[NonEmpty] = Field(default_factory=list)
    source_ids: list[NonEmpty] = Field(default_factory=list)
    derivation: Derivation | None = None


class TemplateFieldBase(ContractModel):
    name: NonEmpty
    method: Method
    confidence: Confidence = Confidence.SURE
    review: ReviewState | None = None
    review_item: ReviewLink | None = None
    provenance: PrepProvenance | None = None
    essential: bool = False


T = TypeVar("T")


class KnownField(TemplateFieldBase, Generic[T]):
    state: Literal["known"] = "known"
    confidence: Literal["sure"] = "sure"
    value: T
    evidence: ValueEvidence
    unit: str | None = None

    @model_validator(mode="after")
    def numeric_evidence(self) -> KnownField[T]:
        if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
            if not (self.evidence.number_ids or self.evidence.derivation):
                raise ValueError("Numeric template fields need number IDs or a supported derivation")
        return self


class TemplateOption(ContractModel, Generic[T]):
    value: T
    evidence: ValueEvidence
    label: str | None = None

    @model_validator(mode="after")
    def printed_number(self) -> TemplateOption[T]:
        if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
            if not self.evidence.number_ids:
                raise ValueError("Each numeric option must cite its own printed number")
        return self


class OptionsField(TemplateFieldBase, Generic[T]):
    state: Literal["options"] = "options"
    confidence: Literal["sure"] = "sure"
    options: list[TemplateOption[T]] = Field(min_length=2)
    basis: Literal["printed_alternatives"] = "printed_alternatives"
    unit: str | None = None
    # Options are printed alternatives; disagreement between readers is unknown.


class UnknownField(TemplateFieldBase):
    state: Literal["unknown"] = "unknown"
    confidence: Literal["unsure"] = "unsure"
    reason: UndeterminedReason
    message: NonEmpty
    evidence: ValueEvidence = Field(default_factory=ValueEvidence)


class KnownNumberField(KnownField[float]):
    pass


class OptionsNumberField(OptionsField[float]):
    pass


class KnownIntegerField(KnownField[int]):
    pass


class OptionsIntegerField(OptionsField[int]):
    pass


class KnownTextField(KnownField[str]):
    pass


class OptionsTextField(OptionsField[str]):
    pass


NumericField = Annotated[KnownNumberField | OptionsNumberField | UnknownField, Field(discriminator="state")]
IntegerField = Annotated[KnownIntegerField | OptionsIntegerField | UnknownField, Field(discriminator="state")]
TextField = Annotated[KnownTextField | OptionsTextField | UnknownField, Field(discriminator="state")]


class RectangleOutline(ContractModel):
    type: Literal["rectangle"] = "rectangle"
    length: NumericField
    width: NumericField


class CircleOutline(ContractModel):
    type: Literal["circle"] = "circle"
    diameter: NumericField


class RingOutline(ContractModel):
    type: Literal["ring"] = "ring"
    outer_diameter: NumericField
    inner_diameter: NumericField


Outline = Annotated[RectangleOutline | CircleOutline | RingOutline, Field(discriminator="type")]


class KnownOutlineField(KnownField[Outline]):
    pass


OutlineField = Annotated[KnownOutlineField | UnknownField, Field(discriminator="state")]


class FeaturePosition(ContractModel):
    # CAD frame in mm: rectangle lower-left, round part center; x right, y up.
    # This CAD frame is distinct from the image frame (y down).
    x: NumericField
    y: NumericField


class RowPattern(ContractModel):
    type: Literal["row"] = "row"
    count: IntegerField
    spacing: NumericField
    direction_deg: NumericField


class CirclePattern(ContractModel):
    type: Literal["circle"] = "circle"
    count: IntegerField
    radius: NumericField
    start_angle_deg: NumericField
    evenly_spaced: bool = True
    angles_deg: list[NumericField] | None = None


Pattern = Annotated[RowPattern | CirclePattern, Field(discriminator="type")]
Face = Literal["top", "bottom", "front", "back", "left", "right", "outer", "inner"]


class HoleFeature(ContractModel):
    kind: Literal["hole"] = "hole"
    hole_type: Literal["plain", "threaded", "countersunk", "counterbored"]
    face: Face
    position: FeaturePosition
    diameter: NumericField
    through: bool
    depth: NumericField | None = None
    thread_size: TextField | None = None
    thread_depth: NumericField | None = None
    countersink_diameter: NumericField | None = None
    countersink_angle_deg: NumericField | None = None
    counterbore_diameter: NumericField | None = None
    counterbore_depth: NumericField | None = None
    pattern: Pattern | None = None
    note: str | None = None

    @model_validator(mode="after")
    def feature_dimensions(self) -> HoleFeature:
        required = {
            "plain": (), "threaded": ("thread_size",),
            "countersunk": ("countersink_diameter", "countersink_angle_deg"),
            "counterbored": ("counterbore_diameter", "counterbore_depth"),
        }[self.hole_type]
        if any(getattr(self, field) is None for field in required) or (not self.through and self.depth is None):
            raise ValueError("Hole dimensions must be explicit; use unknown fields when unreadable")
        return self


class SlotFeature(ContractModel):
    kind: Literal["slot"] = "slot"
    face: Face
    position: FeaturePosition
    width: NumericField
    length: NumericField
    direction_deg: NumericField
    through: bool
    depth: NumericField | None = None
    pattern: Pattern | None = None
    note: str | None = None

    @model_validator(mode="after")
    def slot_depth(self) -> SlotFeature:
        if not self.through and self.depth is None:
            raise ValueError("A blind slot needs a depth (possibly unknown)")
        return self


Feature = Annotated[HoleFeature | SlotFeature, Field(discriminator="kind")]


class KnownFeatureField(KnownField[Feature]):
    pass


FeatureField = Annotated[KnownFeatureField | UnknownField, Field(discriminator="state")]


class FlatTemplate(Payload):
    part: NonEmpty  # Drawing ID, e.g. D-013, not its /part stable name.
    template: Literal["flat_part"] = "flat_part"
    units: Literal["mm"] = "mm"
    filled_by: Literal["two_models", "single_model", "human"]
    source_sha256: SHA256
    review: ReviewState = Field(default_factory=ReviewState)
    provenance: PrepProvenance | None = None
    outline: OutlineField
    thickness: NumericField
    features: list[FeatureField] = Field(default_factory=list)
    material: TextField | None = None
    weight_on_drawing: NumericField | None = None  # Unit g, when recorded.
    finish_notes: list[str] = Field(default_factory=list)
    # No grid/mirror/pocket/custom outline or round template in this MVP subset.

    @model_validator(mode="after")
    def template_provenance(self) -> FlatTemplate:
        drawing_id(self.part)
        if self.filled_by in {"two_models", "single_model"}:
            expected = "dual_reader" if self.filled_by == "two_models" else "single_model"
            if self.provenance is None or self.provenance.mode != expected:
                raise ValueError("Template filled_by must match its actual reader provenance")
        return self


class OmittedDetail(ContractModel):
    name: NonEmpty
    reason: NonEmpty
    source_ids: list[str] = Field(default_factory=list)
    review_item: ReviewLink | None = None


class ModelExample(ContractModel):
    id: Literal["A", "B", "C", "D"]
    glb: NonEmpty
    choices: dict[str, JsonValue] = Field(default_factory=dict)
    possible_reading: bool = True
    source_ids: list[str] = Field(default_factory=list)
    step: str | None = None  # Reserved M3; reconstruction-labeled download.
    volume_mm3: float | None = Field(default=None, ge=0)  # Reserved M2.


class DensityReference(ContractModel):  # Reserved M2: no density guesses.
    material: NonEmpty
    density_g_cm3: Positive
    source_url: NonEmpty
    retrieved_at: AwareDatetime
    outside_dataset: Literal[True] = True
    family_mapping: str | None = None


class ExampleWeight(ContractModel):
    example: Literal["A", "B", "C", "D"]
    material_source: Literal["drawing", "bom"]
    material: NonEmpty
    density: DensityReference
    calculated_g: NonNegative
    drawing_g: Positive
    difference_percent: NonNegative
    matches: bool


class WeightCheck(ContractModel):  # Reserved M2; never controls model visibility.
    state: Literal["Passed", "Flagged", "FAILED", "Skipped"]
    message: NonEmpty
    examples: list[ExampleWeight] = Field(default_factory=list)
    tolerance_percent: float = Field(default=5, ge=0)
    review: ReviewState | None = None
    approval_note: str | None = None


class ModelStatus(ContractModel):
    state: Literal["available", "stale", "blocked", "unsupported", "missing"]
    examples: list[ModelExample] = Field(default_factory=list, max_length=4)
    selected_example: Literal["A", "B", "C", "D"] | None = None  # Human choice only.
    reconstruction_label: Literal["Reconstruction from 2D drawing. Not the original CAD model."] = RECONSTRUCTION_LABEL
    review: ReviewState = Field(default_factory=ReviewState)
    provenance: PrepProvenance | None = None
    human_input_fields: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    omitted_details: list[OmittedDetail] = Field(default_factory=list)
    message: str | None = None
    stale_reason: str | None = None
    built_at: AwareDatetime | None = None
    built_template_sha256: SHA256 | None = None
    current_template_sha256: SHA256 | None = None
    overall_size_mm: Vector3 | None = None  # Reserved M3.
    section_view_available: bool | None = None  # Reserved M3, hollow view only.

    @model_validator(mode="after")
    def available_assets(self) -> ModelStatus:
        ids = [example.id for example in self.examples]
        if len(ids) != len(set(ids)) or (self.selected_example and self.selected_example not in ids):
            raise ValueError("Model examples must be unique and contain any human-selected example")
        if self.state in {"available", "stale"} and not self.examples:
            raise ValueError("Available/stale model must identify viewable GLBs")
        if self.state not in {"available", "stale"} and self.examples:
            raise ValueError("Unavailable model cannot advertise viewable GLBs")
        if self.state == "stale" and not self.stale_reason:
            raise ValueError("Stale model must explain why it is out of date")
        return self


class Callout(ContractModel):  # Reserved M3, self-describing level-1 evidence only.
    name: NonEmpty
    kind: Literal["hole", "thread", "countersink", "counterbore", "slot", "tolerance", "note"]
    text: NonEmpty
    target: SourceTarget
    values: dict[str, JsonValue]
    number_ids: list[str]
    method: Literal["parsed"] = "parsed"


class ReadmePassage(Payload):  # Reserved M3; upstream machine README, not app README.
    name: NonEmpty
    section: NonEmpty
    paragraph: int = Field(ge=1)
    text: NonEmpty
    source_sha256: SHA256
    method: Literal["parsed"] = "parsed"
    snapshot_note: bool = True
    missing_images: list[str] = Field(default_factory=list)
    mentions_unavailable_native_cad: bool = False


class InstalledIn(ContractModel):  # Reserved M3; no diagram-derived invented links.
    section: str | None
    connections: list[ConnectionEvidence]
    note: str | None = None


class PartRecord(Payload):
    id: NonEmpty
    display_name: NonEmpty
    section: str | None
    has_drawing: bool
    has_3d: bool
    examples: list[Literal["A", "B", "C", "D"]]
    drawing: DrawingEvidence | None
    bom: list[BOMRow]
    link: LinkInfo | None
    template: str | None  # Asset reference, not a second copy of the template.
    model: ModelStatus
    review_items: list[ReviewLink] = Field(default_factory=list)
    weight_check: WeightCheck | None = None  # Reserved M2.
    callouts: list[Callout] | None = None  # Reserved M3.
    crops: list[CropReference] | None = None  # Reserved M3.
    readme_passages: list[ReadmePassage] | None = None  # Reserved M3.
    installed_in: InstalledIn | None = None  # Reserved M3.
    # No merged drawing/BOM engineering field is stored here. FactResult is the
    # effective projection; unsure evidence and originals remain inspectable.

    @model_validator(mode="after")
    def record_identity(self) -> PartRecord:
        if self.has_drawing != (self.drawing is not None):
            raise ValueError("has_drawing must match drawing evidence")
        if self.drawing and self.id != drawing_part_name(self.drawing.id):
            raise ValueError("Drawing record must use its stable /part name")
        if not self.drawing and (not self.bom or self.id != f"{self.bom[0].name}/part"):
            raise ValueError("BOM-only record must use its stable /part name")
        if self.has_3d != (self.model.state in {"available", "stale"}):
            raise ValueError("has_3d must reflect viewable model assets, including stale ones")
        if self.examples != [example.id for example in self.model.examples]:
            raise ValueError("Record example summary must match model metadata")
        return self


class PartSummary(Payload):
    id: NonEmpty
    display_name: NonEmpty
    section: str | None
    has_drawing: bool
    has_3d: bool
    examples: list[Literal["A", "B", "C", "D"]]
    thumbnail: str | None = None
    model_state: Literal["available", "stale", "blocked", "unsupported", "missing"]
    review_items: list[ReviewLink] = Field(default_factory=list)
    weight_check: WeightCheck | None = None


class PartDetailResponse(PartRecord):
    facts: dict[str, FactResult]  # Map keys are stable names, including whole-part facts.


class StringMatchEvidence(ContractModel):
    source_name: NonEmpty
    matched: bool
    text: str | None


class CorrectionCheck(ContractModel):
    method: Literal["string_match"] = "string_match"
    drawing: list[StringMatchEvidence]
    bom: list[StringMatchEvidence]
    message: NonEmpty
    proves_correct: Literal[False] = False  # A match is evidence, never approval.


class DecisionType(StrEnum):
    CORRECTION = "correction"
    LINK = "link"
    SET_VALUE = "set_value"
    CHOOSE_OPTION = "choose_option"
    NAME_MAPPING = "name_mapping"
    CONFIRM = "confirm"  # Reserved M2.
    REJECT = "reject"  # Reserved M2.
    APPROVE_DESIGN = "approve_design"  # Reserved M2.


class Decision(Payload):
    # Append-only event: pending proposal and later review are separate records.
    # Latest applicable ACCEPTED event overlays evidence; pending/rejected do not.
    # Keep reviewed hashes unchanged when source changes; append a new decision.
    decision_id: NonEmpty
    applies_to: NonEmpty
    type: DecisionType
    value: JsonValue
    old_value: JsonValue = None
    status: Literal["pending", "accepted", "rejected"]
    by: NonEmpty  # Reviewer for accepted/rejected, proposer for pending.
    at: AwareDatetime
    based_on: dict[str, SHA256] = Field(min_length=1)  # Source stable name/path -> exact reviewed hash.
    ai_answers: PrepProvenance | None = None
    check_result: CorrectionCheck | None = None
    reason: str | None = None
    note: str | None = None
    proposal_id: str | None = None
    supersedes: str | None = None


class DecisionJournal(Payload):
    item_id: NonEmpty
    decisions: list[Decision]


class ReviewAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    SET_VALUE = "set_value"
    CHOOSE_OPTION = "choose_option"
    APPROVE_MAPPING = "approve_mapping"
    CONFIRM = "confirm"  # Reserved M2; M1 must not advertise it as available.
    APPROVE_DESIGN = "approve_design"  # Reserved M2; one part, never bulk approval.


class ReviewItem(Payload):
    id: NonEmpty
    kind: Literal["correction", "link", "template_field", "name_mapping", "scan_reading", "ai_label", "whole_design", "weight"]
    applies_to: NonEmpty
    part_id: str | None
    status: Literal["pending", "accepted", "rejected", "resolved", "source_changed"]
    title: NonEmpty
    message: NonEmpty
    current_value: JsonValue = None
    proposed_value: JsonValue = None
    options: list[JsonValue] = Field(default_factory=list)
    sources: list[FactSource] = Field(default_factory=list)
    source_hashes: dict[str, SHA256]
    ai_answers: PrepProvenance | None = None
    mapping: NameMapping | None = None
    check_result: CorrectionCheck | None = None
    review: ReviewState | None = None
    allowed_actions: list[ReviewAction]
    proposal_id: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    blocking_fields: list[str] | None = None  # Reserved M2 approval eligibility.
    approval_note_required: bool | None = None  # Reserved M2 FAILED-weight rule.
    weight_check: WeightCheck | None = None


class ReviewActionRequest(Payload):
    # This is the POST BODY, not its response. Reviewer/time come from the server
    # setting/clock, never from chat or a user-supplied reviewer field.
    action: ReviewAction
    value: JsonValue = None
    note: str | None = None
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_value(self) -> ReviewActionRequest:
        if self.action in {ReviewAction.SET_VALUE, ReviewAction.CHOOSE_OPTION} and "value" not in self.model_fields_set:
            raise ValueError("set_value/choose_option need an explicit value")
        return self


class RefreshRequest(ContractModel):
    part_ids: list[NonEmpty]
    decision_ids: list[NonEmpty]
    rebuild_models: bool = True


class RefreshResult(ContractModel):
    part_ids: list[str]
    facts: dict[str, FactResult]
    models: dict[str, ModelStatus]
    warnings: list[str] = Field(default_factory=list)


class ReviewActionResponse(Payload):
    item: ReviewItem  # Updated item/result, NEVER an echoed action request.
    decisions: list[Decision]
    refresh: RefreshResult


class ProposeCorrectionRequest(ContractModel):
    fact_id: NonEmpty
    new_value: JsonValue
    reason: NonEmpty


class ProposeCorrectionResult(Payload):
    item: ReviewItem
    decision: Decision
    review_link: ReviewLink

    @model_validator(mode="after")
    def proposal_only(self) -> ProposeCorrectionResult:
        if self.item.status != "pending" or self.decision.status != "pending":
            raise ValueError("Chat proposal callback cannot approve a decision")
        return self


class WarningCode(StrEnum):
    INVALID_CITATION = "invalid_citation"
    INVALID_UNDETERMINED = "invalid_undetermined"
    UNSUPPORTED_VALUE = "unsupported_value"
    UNCITED_ANSWER = "uncited_answer"
    MALFORMED_MARKER = "malformed_marker"
    SINGLE_MODEL = "single_model"
    STALE_MODEL = "stale_model"


class ChatWarning(ContractModel):
    code: WarningCode
    message: NonEmpty
    names: list[str] = Field(default_factory=list)
    marker: str | None = None


class ChatMarker(ContractModel):
    # Raw grammar: [cite: name1, name2] or [undetermined: name]. Names are NOT URL
    # encoded here. Offsets are Unicode code points in raw response text (TS:
    # Array.from(text)), half-open [start,end); not UTF-16 code units.
    kind: Literal["cite", "undetermined"]
    names: list[NonEmpty] = Field(min_length=1)
    raw: NonEmpty
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    valid: bool
    error: WarningCode | None = None

    @model_validator(mode="after")
    def marker_span(self) -> ChatMarker:
        if self.end <= self.start or (self.kind == "undetermined" and len(self.names) != 1):
            raise ValueError("Marker needs a nonempty span; Undetermined names exactly one fact")
        if self.valid == (self.error is not None):
            raise ValueError("Only invalid markers carry an error")
        return self


class PartAttachment(ContractModel):
    id: NonEmpty
    display_name: NonEmpty
    thumbnail: str | None
    has_drawing: bool
    has_3d: bool
    examples: list[Literal["A", "B", "C", "D"]]
    model_state: Literal["available", "stale", "blocked", "unsupported", "missing"]
    reason: Literal["citation", "single_match"]
    explanation: str | None = None
    highlights: list[SourceTarget] = Field(default_factory=list)
    drawing_url: str | None = None
    model_urls: dict[str, str] = Field(default_factory=dict)


class ChatTurn(ContractModel):
    role: Literal["user", "assistant"]
    text: NonEmpty


class ChatRequest(Payload):
    message: NonEmpty
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)
    conversation_id: str | None = None


class ChatObservation(ContractModel):
    provider: Literal["openai"] = "openai"
    model: Literal["gpt-6-luna"] = CHAT_MODEL
    latency_ms: NonNegative | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: NonNegative | None = None  # Null means unavailable, never invented.


class ChatResponse(Payload):
    text: NonEmpty
    facts: dict[str, FactResult]
    parts_to_show: list[PartAttachment]
    warnings: list[ChatWarning]
    markers: list[ChatMarker] = Field(default_factory=list)
    attachment_layout: Literal["none", "cards", "list"]
    conversation_id: str | None = None
    observation: ChatObservation | None = None

    @model_validator(mode="after")
    def attachments(self) -> ChatResponse:
        count = len(self.parts_to_show)
        expected = "none" if count == 0 else "cards" if count <= 3 else "list"
        if self.attachment_layout != expected or len({p.id for p in self.parts_to_show}) != count:
            raise ValueError("Attachments are unique, citation-ordered; cards for 1-3, list for 4+")
        if any(key != fact.fact for key, fact in self.facts.items()):
            raise ValueError("Fact map keys must equal their stable fact names")
        return self


class StatusRequest(ContractModel):
    pass


class StatusResponse(Payload):
    chat_available: bool
    chat_state: Literal["configured", "missing_key"]
    message: NonEmpty
    chat_provider: Literal["openai"] = "openai"
    chat_model: Literal["gpt-6-luna"] = CHAT_MODEL
    cad_available: bool | None = None

    @model_validator(mode="after")
    def configured(self) -> StatusResponse:
        if self.chat_available != (self.chat_state == "configured"):
            raise ValueError("Chat availability must reflect configured/missing-key state")
        return self


class ErrorCode(StrEnum):
    MISSING_KEY = "missing_key"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_ERROR = "provider_error"
    PREP_FAILED = "prep_failed"
    MODEL_UNAVAILABLE = "model_unavailable"
    STALE_CONFLICT = "stale_conflict"
    UNSUPPORTED = "unsupported"
    INTERNAL_ERROR = "internal_error"


class APIError(ContractModel):
    code: ErrorCode
    message: NonEmpty
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)  # Safe structured data only.


class ErrorResponse(Payload):
    error: APIError  # All non-2xx JSON responses use this envelope, including 422.


class PartsRequest(ContractModel):
    q: str = ""
    section: str | None = None  # Reserved M3 filters.
    material: str | None = None
    has_3d: bool | None = None
    review_status: ReviewStatus | None = None


class PartRequest(ContractModel):
    id: NonEmpty  # Decoded stable part ID, not a display ID or a drawing shorthand.


class ImageRequest(PartRequest):
    page: int = Field(default=1, ge=1)
    thumb: Literal[0, 1] = 0


class ModelRequest(ContractModel):
    drawing_id: Annotated[str, StringConstraints(pattern=r"^D-\d{3}$")]
    example: Literal["A", "B", "C", "D"]


class ReviewListRequest(ContractModel):
    status: Literal["pending", "accepted", "rejected", "resolved", "source_changed", "all"] = "pending"
    part_id: str | None = None
    tab: Literal["corrections", "needs_input", "ai_interpretations", "possible_readings"] | None = None
    drawing_id: str | None = None
    kind: str | None = None
    method: Method | None = None
    review_status: ReviewStatus | None = None
    weight_state: Literal["Passed", "Flagged", "FAILED", "Skipped"] | None = None


class ReviewItemRequest(ContractModel):
    item_id: NonEmpty


class HistoryRequest(PartRequest):
    fact: str | None = None  # Reserved M2 fact history filter.


class HistoryEvent(ContractModel):
    id: NonEmpty
    applies_to: NonEmpty
    kind: Literal["extracted", "cleanup", "ai_result", "decision", "source_changed", "model_rebuilt"]
    at: AwareDatetime
    message: NonEmpty
    value: JsonValue = None
    decision: Decision | None = None
    source_hashes: dict[str, SHA256] = Field(default_factory=dict)
    superseded: bool = False


class HistoryResponse(Payload):  # Reserved M2.
    part_id: NonEmpty
    events: list[HistoryEvent]


class AccuracyRequest(ContractModel):
    job: str | None = None


class JobAccuracy(ContractModel):
    job: NonEmpty
    confirmed: int = Field(ge=0)
    rejected: int = Field(ge=0)
    checked: int = Field(ge=0)  # Denominator is checked items, not all AI outputs.
    total_items: int = Field(ge=0)
    accuracy: float | None = Field(default=None, ge=0, le=1)
    # Consumers deduplicate per-item confirmations from whole-design approvals.


class AccuracyResponse(Payload):  # Reserved M2.
    jobs: list[JobAccuracy]


class CropRequest(PartRequest):  # Reserved M3.
    fact: NonEmpty


class ReadmeRequest(ContractModel):  # Reserved M3.
    q: str = ""


class ReadmeResponse(Payload):
    passages: list[ReadmePassage]


class FindPartRequest(ContractModel):
    text: NonEmpty


class FindPartResult(Payload):
    parts: list[PartSummary]
    facts: dict[str, FactResult]  # Whole-part entries authorize whole-part citations.
    unique_part_id: str | None = None  # Only this turn's unique match enables fallback.


class GetFactsRequest(ContractModel):
    part_id: NonEmpty


class GetFactsResult(Payload):
    part_id: NonEmpty
    facts: dict[str, FactResult]


class GetConnectionsResult(Payload):
    part_id: NonEmpty
    connections: list[ConnectionEvidence]
    facts: dict[str, FactResult]
    message: str = "No connections recorded."


class PartsInSectionRequest(ContractModel):
    section: NonEmpty


class PartsWithMaterialRequest(ContractModel):
    material: NonEmpty


class PartGroupResult(Payload):
    parts: list[PartSummary]
    facts: dict[str, FactResult]
    message: NonEmpty


# Wire aliases: list endpoints return JSON arrays, not invented wrapper objects.
PartsResponse = list[PartSummary]
ReviewListResponse = list[ReviewItem]
BinaryResponse = bytes  # PNG / GLB / STEP bytes; errors still use ErrorResponse JSON.


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    request: str
    response: str
    milestone: Literal["M1", "M2", "M3"]
    media_type: str = "application/json"


API_ENDPOINTS = (
    Endpoint("GET", "/api/status", "StatusRequest", "StatusResponse", "M1"),
    Endpoint("GET", "/api/parts", "PartsRequest", "PartsResponse", "M1"),
    Endpoint("GET", "/api/parts/{id}", "PartRequest", "PartDetailResponse", "M1"),
    Endpoint("GET", "/api/parts/{id}/image", "ImageRequest", "BinaryResponse", "M1", "image/png"),
    Endpoint("GET", "/api/models/{drawing_id}_{example}.glb", "ModelRequest", "BinaryResponse", "M1", "model/gltf-binary"),
    Endpoint("POST", "/api/chat", "ChatRequest", "ChatResponse", "M1"),
    Endpoint("GET", "/api/review", "ReviewListRequest", "ReviewListResponse", "M1"),
    Endpoint("POST", "/api/review/{item_id}", "ReviewActionRequest", "ReviewActionResponse", "M1"),
    Endpoint("GET", "/api/parts/{id}/history", "HistoryRequest", "HistoryResponse", "M2"),
    Endpoint("GET", "/api/accuracy", "AccuracyRequest", "AccuracyResponse", "M2"),
    Endpoint("GET", "/api/parts/{id}/crop", "CropRequest", "BinaryResponse", "M3", "image/png"),
    Endpoint("GET", "/api/models/{drawing_id}_{example}.step", "ModelRequest", "BinaryResponse", "M3", "model/step"),
    Endpoint("GET", "/api/readme", "ReadmeRequest", "ReadmeResponse", "M3"),
)


class ProposeCorrectionCallback(Protocol):
    def __call__(self, request: ProposeCorrectionRequest) -> ProposeCorrectionResult: ...


class RefreshCallback(Protocol):
    def __call__(self, request: RefreshRequest) -> RefreshResult: ...


class ReviewActionHandler(Protocol):
    def __call__(self, item_id: str, action: ReviewActionRequest, reviewer: str) -> ReviewActionResponse: ...


class RecordsRebuilder(Protocol):
    def __call__(self, part_ids: Sequence[str] | None = None) -> list[PartRecord]: ...


class ModelRebuilder(Protocol):
    def __call__(self, record: PartRecord, template: FlatTemplate) -> ModelStatus: ...


DecisionAppender = Callable[[Decision], Decision]
FactResolver = Callable[[PartRecord], dict[str, FactResult]]
TemplateLoader = Callable[[str], FlatTemplate | None]


@dataclass(frozen=True)
class ReviewDependencies:
    # M03 composes these direct A07/A12/A13 functions into M16. M14 receives ONLY
    # M16's ProposeCorrectionCallback. M16 never imports chat/tools/router modules.
    append_decision: DecisionAppender
    rebuild_records: RecordsRebuilder
    resolve_facts: FactResolver
    load_template: TemplateLoader
    rebuild_model: ModelRebuilder | None  # None -> refreshed facts + stale model.


class FactTools(Protocol):
    def find_part(self, text: str) -> FindPartResult: ...
    def get_facts(self, part_id: str) -> GetFactsResult: ...
    def get_connections(self, part_id: str) -> GetConnectionsResult: ...
    def parts_in_section(self, section: str) -> PartGroupResult: ...
    def parts_with_material(self, material: str) -> PartGroupResult: ...
    def propose_correction(self, fact_id: str, new_value: JsonValue, reason: str) -> ProposeCorrectionResult: ...


# The checker uses this finite inventory to verify the TS mirror and fixtures.
# Generic specializations are included through each concrete model's JSON schema.
CONTRACT_MODELS = {
    name: value for name, value in tuple(globals().items())
    if isinstance(value, type) and issubclass(value, ContractModel)
    and value not in {ContractModel, Payload, TemplateFieldBase, KnownField, OptionsField, TemplateOption}
    and "[" not in name
}
CONTRACT_ALIASES = {
    "Box": Box, "Point": Point, "Vector3": Vector3,
    "FactDisplay": FactDisplay, "NumericField": NumericField, "IntegerField": IntegerField,
    "TextField": TextField, "Outline": Outline, "OutlineField": OutlineField,
    "Pattern": Pattern, "Face": Face, "Feature": Feature, "FeatureField": FeatureField,
    "PartsResponse": PartsResponse, "ReviewListResponse": ReviewListResponse,
}


def contract_json_schema() -> dict[str, JsonValue]:
    """Concrete inventory for schema/TS comparison; no files or application state."""
    definitions = {}
    for name, model in {**CONTRACT_MODELS, **CONTRACT_ALIASES}.items():
        schema = TypeAdapter(model).json_schema(ref_template="#/$defs/{model}")
        definitions.update(schema.pop("$defs", {}))
        if schema != {"$ref": f"#/$defs/{name}"}:
            definitions[name] = schema
    # Pydantic v2 may describe JsonValue as {} (any JSON). Spell out that exact
    # recursive JSON domain for the TS mirror; Python runtime still uses JsonValue.
    definitions["JsonValue"] = {"anyOf": [
        {"type": "null"}, {"type": "boolean"}, {"type": "number"}, {"type": "string"},
        {"type": "array", "items": {"$ref": "#/$defs/JsonValue"}},
        {"type": "object", "additionalProperties": {"$ref": "#/$defs/JsonValue"}},
    ]}
    return {"title": SCHEMA_NAME, "$defs": definitions}
