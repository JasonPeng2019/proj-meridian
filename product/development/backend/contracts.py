"""Frozen M02 payloads and boundaries. No I/O, chat, router, or CAD imports.

JSON uses snake_case in both languages. contracts.ts mirrors the Pydantic schema;
the focused contract checker verifies that mirror. Reserved M2/M3 shapes are contracts,
not a claim that their endpoints or behavior have been implemented.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Callable, Generic, Literal, Protocol, Sequence, TypeVar
from urllib.parse import quote, unquote

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StringConstraints,
    TypeAdapter, model_validator,
)


SCHEMA_NAME = "meridian-contracts"
RECONSTRUCTION_LABEL = "Reconstruction from 2D drawing. Not the original CAD model."
SINGLE_MODEL_LABEL = "UNVERIFIED: Sol only; Opus execution failed."  # Debug only.
PREP_PIPELINE_VERSION = "determine-verify/v1"
DEBUG_ENV = "MERIDIAN_DEBUG"  # A01 owns parsing; unset/0 disables, 1 explicitly enables.
CHAT_MODEL = "gpt-6-luna"
CHAT_CONTEXT_TURNS = 10  # Individual user/assistant messages, INCLUDING the current user message.
CONVERSATION_TITLE_LIMIT = 80  # Unicode code points after collapsing first-user-message whitespace.
ConversationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
MessageId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
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
    AI_READ = "ai_read"  # Historical only; never establishes verification.
    AI_AGREED = "ai_agreed"  # Historical blind-reader method.
    AI_AGREED_AFTER_RETRY = "ai_agreed_after_retry"  # Historical only.
    AI_VERIFIED = "ai_verified"
    AI_VERIFIED_AFTER_RETRY = "ai_verified_after_retry"
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
    href: NonEmpty  # Debug-only navigation; historical /review links cannot bypass the launch gate.


class ReaderSettings(ContractModel):
    provider: Literal["codex_cli", "claude_code"]
    model: NonEmpty
    reasoning: NonEmpty
    service_tier: NonEmpty  # Codex 'fast' is priority; Opus uses 'regular'.
    read_only: Literal[True] = True
    settings: dict[str, JsonValue] = Field(default_factory=dict)


class ObservedReaderSettings(ContractModel):
    # Only metadata actually reported by the CLI. Never fill unknowns from the
    # request: null means unreported, including per-setting null dictionary values.
    # Full observations use these same fields; missing metadata is not a failure.
    provider: Literal["codex_cli", "claude_code"] | None = None
    model: NonEmpty | None = None
    reasoning: NonEmpty | None = None
    service_tier: NonEmpty | None = None
    read_only: bool | None = None
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


def contract_digest(value: JsonValue | BaseModel) -> str:
    """SHA256 of sorted compact UTF-8 JSON; normalize models before hashing.

    This binds records; it does not prove the cited source was actually inspected.
    M08/domain validators must check original bytes and admissible references.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class PrepSourceIdentity(ContractModel):
    # Original evidence, including supplied images/rows/number inventories.
    inputs: dict[NonEmpty, SHA256] = Field(min_length=1)
    source_ids: dict[NonEmpty, NonEmpty] = Field(min_length=1)  # Stable ID -> input key.

    @model_validator(mode="after")
    def owned_references(self) -> PrepSourceIdentity:
        if not set(self.source_ids.values()) <= self.inputs.keys():
            raise ValueError("Every source ID must identify an original hashed input")
        return self


class DeterminedField(ContractModel):
    state: Literal["known", "options", "unknown", "value", "match", "no_match", "relationship"]
    value: JsonValue = None
    options: list[JsonValue] = Field(default_factory=list)
    confidence: Confidence
    source_ids: list[NonEmpty] = Field(default_factory=list)
    reason: Reason
    # Required host/domain validation, not inferred from matching strings.
    schema_valid: bool
    evidence_valid: bool
    basis: Literal["printed_alternatives"] | None = None

    @model_validator(mode="after")
    def candidate_shape(self) -> DeterminedField:
        if self.state == "options":
            if len(self.options) < 2 or self.value is not None or self.basis != "printed_alternatives":
                raise ValueError("Options require actual printed alternatives, never model disagreement")
        elif self.options or self.basis:
            raise ValueError("Only an options candidate carries alternatives")
        if self.state == "unknown" and (self.value is not None or self.confidence != Confidence.UNSURE):
            raise ValueError("Unknown candidate has no usable value and is unsure")
        if self.state not in {"options", "unknown", "no_match"} and self.value is None:
            raise ValueError("A known candidate needs an explicit value")
        return self


def usable_candidate(field: DeterminedField) -> bool:
    return (field.state != "unknown" and field.confidence == Confidence.SURE
            and field.schema_valid and field.evidence_valid and bool(field.source_ids))


class DeterminationOutput(ContractModel):
    source_sha256: SHA256  # contract_digest(PrepSourceIdentity).
    fields: dict[NonEmpty, DeterminedField] = Field(min_length=1)
    candidate_sha256: SHA256  # Hash of this object excluding candidate_sha256.

    @model_validator(mode="after")
    def bound_candidate(self) -> DeterminationOutput:
        if self.candidate_sha256 != contract_digest(self.model_dump(mode="json", exclude={"candidate_sha256"})):
            raise ValueError("Candidate digest must bind every field/state/value/reason/source reference")
        return self


class FieldVerification(ContractModel):
    verdict: Literal["verified", "disagrees", "unsure"]
    reason: Reason
    source_ids: list[NonEmpty] = Field(min_length=1)
    alternative: DeterminedField | None = None  # Feedback only, NEVER an accepted value.

    @model_validator(mode="after")
    def alternative_is_feedback(self) -> FieldVerification:
        if self.alternative is not None and self.verdict != "disagrees":
            raise ValueError("Only disagreement feedback may suggest an alternative")
        return self


class VerificationOutput(ContractModel):
    candidate_sha256: SHA256
    source_sha256: SHA256
    fields: dict[NonEmpty, FieldVerification] = Field(min_length=1)
    verification_sha256: SHA256

    @model_validator(mode="after")
    def bound_verdicts(self) -> VerificationOutput:
        if self.verification_sha256 != contract_digest(self.model_dump(mode="json", exclude={"verification_sha256"})):
            raise ValueError("Verification digest must bind verdicts and the exact candidate/source")
        return self


class PrepCacheIdentity(ContractModel):
    # Historical B00/dual_reader keys cannot validate as this identity.
    pipeline_version: Literal["determine-verify/v1"] = PREP_PIPELINE_VERSION
    role: Literal["determination", "verification"]
    source_sha256: SHA256
    field_names_sha256: SHA256  # Hash of the requested ordered field inventory.
    candidate_sha256: SHA256 | None  # Previous candidate for correction; current for verification.
    feedback_sha256: SHA256 | None  # Previous Opus verification for correction only.
    prompt_sha256: SHA256
    output_contract_sha256: SHA256
    settings: ReaderSettings  # Pinned REQUESTED settings, never promoted to observations.
    settings_basis: Literal["requested", "confirmed"]  # Requested includes unconfirmed/partial observations.
    effective_sha256: SHA256 | None  # contract_digest(normalized ObservedReaderSettings), or null for effective=null.
    mode: Literal["determine_verify", "single_model_unverified"]
    # Cache key is contract_digest(this object). Reusing Sol never skips a new
    # Opus launch after unverified fallback; a verifier failure is not reusable success.


def _stage_settings(settings: ReaderSettings, role: str) -> None:
    expected = ("codex_cli", "gpt-6.1-sol", "max") if role == "determination" else (
        "claude_code", "claude-opus-5-5", "xhigh")
    tiers = {"fast", "priority"} if role == "determination" else {"regular"}
    if (settings.provider, settings.model, settings.reasoning) != expected or settings.service_tier not in tiers:
        raise ValueError("Prep requires Sol max/priority determination then Opus xhigh/regular verification")
    if role == "verification" and (settings.settings.get("fastMode", False) is not False
                                   or settings.settings.get("fallbackModel", []) != []):
        raise ValueError("Opus verification cannot enable fast mode or substitute another model")


def prep_settings_basis(requested: ReaderSettings, effective: ObservedReaderSettings | None,
                        role: Literal["determination", "verification"]) -> Literal["requested", "confirmed"]:
    """Validate pinned requests and actual observations; return the cache basis.

    'confirmed' requires every core field, requested setting, and Opus fast/fallback
    policy setting to be reported. Accepted tier aliases are Opus standard/regular and Codex
    fast/priority; absent effort/sandbox/fallback stays null, never copied.
    """
    _stage_settings(requested, role)
    if effective is None:
        return "requested"
    tiers = {"fast", "priority"} if role == "determination" else {"regular", "standard"}
    for name in ("provider", "model", "reasoning", "read_only"):
        actual = getattr(effective, name)
        if actual is not None and actual != getattr(requested, name):
            raise ValueError(f"Reported prep {name} conflicts with the pinned request")
    if effective.service_tier is not None and effective.service_tier not in tiers:
        raise ValueError("Reported prep service tier conflicts with the pinned role")
    if role == "verification":
        fast_mode = effective.settings.get("fastMode")
        if ((fast_mode is not None and fast_mode is not False)
                or effective.settings.get("fallbackModel") not in (None, [])):
            raise ValueError("Reported Opus fast mode/model substitution conflicts with policy")
    if effective.settings.get("sandbox") not in (None, "read-only"):
        raise ValueError("Reported prep sandbox conflicts with the read-only request")
    for name, actual in effective.settings.items():
        if actual is not None and name in requested.settings and contract_digest(actual) != contract_digest(requested.settings[name]):
            raise ValueError(f"Reported prep setting {name} conflicts with the pinned request")
    complete = all(getattr(effective, name) is not None for name in (
        "provider", "model", "reasoning", "service_tier", "read_only"))
    setting_names = set(requested.settings) | ({"fastMode", "fallbackModel"} if role == "verification" else set())
    complete = complete and all(effective.settings.get(name) is not None for name in setting_names)
    return "confirmed" if complete else "requested"


class PrepAttempt(ContractModel):
    requested: ReaderSettings
    effective: ObservedReaderSettings | None  # Null/partial is legitimate on success; no requested-value substitution.
    status: Literal["success", "execution_failed", "invalid_output"]
    failure: ReaderFailure | None = None
    prior_failures: list[ReaderFailure] = Field(default_factory=list)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    cache: PrepCacheIdentity

    def check_attempt(self, role: str, output: BaseModel | None) -> None:
        basis = prep_settings_basis(self.requested, self.effective, role)
        if any(not failure.execution_failure for failure in self.prior_failures):
            raise ValueError("Prior failures record execution troubleshooting only; invalid output is terminal, never repaired/retried")
        effective_hash = contract_digest(self.effective) if self.effective is not None else None
        if (self.cache.role != role or self.cache.settings != self.requested
                or self.cache.settings_basis != basis or self.cache.effective_sha256 != effective_hash):
            raise ValueError("Cache must bind the requested pins, observed metadata and truthful settings basis")
        if self.finished_at < self.started_at:
            raise ValueError("Stage cannot finish before starting")
        if self.status == "success" and (output is None or self.failure):
            raise ValueError("Successful stage needs validated output and no current failure; metadata may be unreported")
        if self.status == "execution_failed":
            if output is not None or not self.failure or not self.failure.execution_failure:
                raise ValueError("Failed execution needs classified failure and no invented output")
        if self.status == "invalid_output" and (not self.failure or self.failure.execution_failure):
            raise ValueError("Invalid output must be classified separately from execution failure")


class DeterminationAttempt(PrepAttempt):
    role: Literal["determination"] = "determination"
    output: DeterminationOutput | None

    @model_validator(mode="after")
    def truthful_determination(self) -> DeterminationAttempt:
        self.check_attempt(self.role, self.output)
        return self


class VerificationAttempt(PrepAttempt):
    role: Literal["verification"] = "verification"
    # Even failures retain the identity actually submitted for verification.
    candidate_sha256: SHA256
    source_sha256: SHA256
    output: VerificationOutput | None

    @model_validator(mode="after")
    def truthful_verification(self) -> VerificationAttempt:
        self.check_attempt(self.role, self.output)
        if (self.cache.candidate_sha256 != self.candidate_sha256
                or self.cache.source_sha256 != self.source_sha256):
            raise ValueError("Verifier cache must bind the submitted candidate and source")
        if self.output and (self.output.candidate_sha256 != self.candidate_sha256
                            or self.output.source_sha256 != self.source_sha256):
            raise ValueError("Verifier output does not describe the submitted candidate/source")
        return self


class PrepRound(ContractModel):
    round: Literal[1, 2]
    determination: DeterminationAttempt
    verification: VerificationAttempt | None  # Null ONLY if determination could not produce a candidate.


class PrepFieldResult(ContractModel):
    status: Literal["first_pass_verified", "retry_verified", "unresolved", "unverified_fallback"]
    candidate_sha256: SHA256 | None
    accepted: DeterminedField | None  # Always from Sol; unresolved has no accepted value.


class PrepProvenance(ContractModel):
    pipeline_version: Literal["determine-verify/v1"] = PREP_PIPELINE_VERSION
    job: NonEmpty
    job_id: NonEmpty
    mode: Literal["determine_verify", "single_model_unverified"]
    outcome: Literal["first_pass_verified", "retry_verified", "unverified_fallback", "unresolved"]
    rounds: list[PrepRound] = Field(min_length=1, max_length=2)
    source: PrepSourceIdentity
    field_names: list[NonEmpty] = Field(min_length=1)
    determination_prompt_sha256: SHA256
    verification_prompt_sha256: SHA256
    output_contract_sha256: SHA256
    field_results: dict[str, PrepFieldResult] = Field(default_factory=dict)  # Derived, checked if supplied.
    next_launch_attempt_opus: Literal[True] = True

    @model_validator(mode="after")
    def ordered_verification(self) -> PrepProvenance:
        if [r.round for r in self.rounds] != list(range(1, len(self.rounds) + 1)):
            raise ValueError("Preserve the initial round and at most one correction/reverification round")
        names = set(self.field_names)
        if len(names) != len(self.field_names):
            raise ValueError("Field inventory must be unique and fixed across rounds")
        source_hash = contract_digest(self.source)
        previous: PrepRound | None = None
        for round_ in self.rounds:
            sol, opus = round_.determination, round_.verification
            candidate = sol.output
            if previous:
                prior = previous.verification
                if (prior is None or prior.status != "success" or prior.output is None
                        or not any(v.verdict == "disagrees" for v in prior.output.fields.values())):
                    raise ValueError("Only explicit Opus disagreement permits one Sol reconsideration")
                if sol.started_at < prior.finished_at:
                    raise ValueError("Sol correction must follow Opus feedback")
            for attempt, prompt in ((sol, self.determination_prompt_sha256),
                                    (opus, self.verification_prompt_sha256)):
                if attempt is None:
                    continue
                cache = attempt.cache
                if (cache.source_sha256 != source_hash or cache.field_names_sha256 != contract_digest(self.field_names)
                        or cache.prompt_sha256 != prompt
                        or cache.output_contract_sha256 != self.output_contract_sha256):
                    raise ValueError("Stage cache must bind original evidence, prompt and contract")
                expected_candidate = (previous.determination.output.candidate_sha256 if previous
                                      and previous.determination.output else None) if attempt is sol else (
                                          candidate.candidate_sha256 if candidate else None)
                expected_feedback = (previous.verification.output.verification_sha256 if previous
                                     and previous.verification and previous.verification.output else None
                                     ) if attempt is sol else None
                if cache.candidate_sha256 != expected_candidate or cache.feedback_sha256 != expected_feedback:
                    raise ValueError("Stage cache must bind the candidate and correction feedback")
                if cache.mode != self.mode:
                    raise ValueError("Verified and unverified cache modes cannot be substituted")
            if candidate:
                if candidate.source_sha256 != source_hash or set(candidate.fields) != names:
                    raise ValueError("Candidate must bind exact original sources and the fixed field inventory")
                for field in candidate.fields.values():
                    if not set(field.source_ids) <= self.source.source_ids.keys():
                        raise ValueError("Candidate cites a source ID outside original evidence")
            if sol.status != "success":
                if opus is not None:
                    raise ValueError("Do not verify an unsuccessful determination")
            else:
                if opus is None or candidate is None:
                    raise ValueError("A successful determination always attempts Opus, including later launches")
                if (opus.started_at < sol.finished_at or opus.source_sha256 != source_hash
                        or opus.candidate_sha256 != candidate.candidate_sha256):
                    raise ValueError("Verification must follow and bind the exact Sol candidate/source")
                if opus.output:
                    if set(opus.output.fields) != names:
                        raise ValueError("Opus must explicitly judge every candidate field")
                    for name, verdict in opus.output.fields.items():
                        refs = verdict.source_ids + (verdict.alternative.source_ids if verdict.alternative else [])
                        if not set(refs) <= self.source.source_ids.keys():
                            raise ValueError("Verifier cites a source ID outside original evidence")
                        if verdict.verdict == "verified" and not usable_candidate(candidate.fields[name]):
                            raise ValueError("Unknown/unsure/schema-invalid/unsupported Sol fields cannot be verified")
            previous = round_
        last = self.rounds[-1]
        sol, opus = last.determination, last.verification
        fallback = (len(self.rounds) == 1 and sol.status == "success" and opus is not None
                    and opus.status == "execution_failed" and opus.failure is not None
                    and bool(opus.failure.troubleshooting)
                    and all(f.execution_failure for f in opus.prior_failures))
        results = {}
        for name in self.field_names:
            candidate = sol.output
            field = candidate.fields[name] if candidate else None
            status = "unresolved"
            if field and usable_candidate(field) and sol.status == "success":
                if opus and opus.status == "success" and opus.output and opus.output.fields[name].verdict == "verified":
                    status = "first_pass_verified" if len(self.rounds) == 1 else "retry_verified"
                    first = self.rounds[0]
                    if (len(self.rounds) == 2 and first.verification and first.verification.output
                            and first.verification.output.fields[name].verdict == "verified"
                            and first.determination.output and first.determination.output.fields[name] == field):
                        status = "first_pass_verified"
                elif fallback:
                    status = "unverified_fallback"
            results[name] = PrepFieldResult(status=status,
                candidate_sha256=candidate.candidate_sha256 if candidate else None,
                accepted=field if status != "unresolved" else None)
        if self.field_results and self.field_results != results:
            raise ValueError("Accepted fields/statuses must derive from Sol candidates and explicit Opus verdicts")
        self.field_results = results
        statuses = {r.status for r in results.values()}
        expected_mode = "single_model_unverified" if "unverified_fallback" in statuses else "determine_verify"
        expected_outcome = ("unresolved" if "unresolved" in statuses else "unverified_fallback"
                            if "unverified_fallback" in statuses else "retry_verified"
                            if "retry_verified" in statuses else "first_pass_verified")
        if self.mode != expected_mode or self.outcome != expected_outcome:
            raise ValueError("Mode/outcome must honestly reflect derived per-field results")
        return self


class PrepCounts(ContractModel):
    count_unit: Literal["field"] = "field"
    total_fields: int = Field(ge=0)
    first_pass_verified: int = Field(ge=0)
    retry_verified: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    unverified_fallback: int = Field(ge=0)  # Never in either verified numerator.
    execution_failed_attempts: int = Field(ge=0)  # Orthogonal diagnostic, not a field bucket.

    @model_validator(mode="after")
    def exhaustive_counts(self) -> PrepCounts:
        if self.total_fields != self.first_pass_verified + self.retry_verified + self.unresolved + self.unverified_fallback:
            raise ValueError("Every field belongs to exactly one outcome bucket")
        return self


def prep_counts(records: Sequence[PrepProvenance]) -> PrepCounts:
    counts = dict.fromkeys(("first_pass_verified", "retry_verified", "unresolved", "unverified_fallback"), 0)
    failures = 0
    for record in records:
        for field in record.field_results.values():
            counts[field.status] += 1
        failures += sum(attempt.status == "execution_failed" for round_ in record.rounds
                        for attempt in (round_.determination, round_.verification) if attempt is not None)
    return PrepCounts(total_fields=sum(counts.values()), execution_failed_attempts=failures, **counts)


class PrepBatchResult(Payload):
    records: list[PrepProvenance]
    counts: PrepCounts

    @model_validator(mode="after")
    def actual_counts(self) -> PrepBatchResult:
        if self.counts != prep_counts(self.records):
            raise ValueError("Counts must derive from retained preparation records")
        return self


def _accepted_ai_field(method: Method, name: str, provenance: PrepProvenance | None) -> DeterminedField | None:
    expected = {Method.AI_VERIFIED: "first_pass_verified", Method.AI_VERIFIED_AFTER_RETRY: "retry_verified",
                Method.AI_SINGLE_MODEL: "unverified_fallback"}
    if method in {Method.AI_READ, Method.AI_AGREED, Method.AI_AGREED_AFTER_RETRY}:
        raise ValueError("Historical blind-reader methods cannot establish current prep acceptance")
    if method not in expected:
        return None
    result = provenance.field_results.get(name) if provenance else None
    if result is None or result.status != expected[method] or result.accepted is None:
        raise ValueError("AI method needs this exact field's derived verification/fallback result")
    return result.accepted


class CustomerReviewStatus(StrEnum):
    HUMAN_REVIEWED = "Human reviewed"
    AI_REVIEWED = "AI reviewed"
    UNAVAILABLE = "Unavailable"


def customer_review_status(*, usable: bool, current_source_hashes: dict[str, str],
                           review: ReviewState | None = None, provenance: PrepProvenance | None = None,
                           field_name: str | None = None) -> CustomerReviewStatus:
    """Review label only; parsed values can remain usable without claiming review.

    Callers supply current source hashes from records, never a UI-selected label.
    Human rejection/source-changed history and Sol-only fallback do not confer review.
    """
    if not usable or not current_source_hashes:
        return CustomerReviewStatus.UNAVAILABLE
    if (review and review.status == ReviewStatus.HUMAN_CONFIRMED and review.by and review.at
            and review.based_on and all(current_source_hashes.get(k) == v for k, v in review.based_on.items())):
        return CustomerReviewStatus.HUMAN_REVIEWED
    if provenance and all(current_source_hashes.get(k) == v for k, v in provenance.source.inputs.items()):
        fields = ([provenance.field_results[field_name]] if field_name in provenance.field_results else []
                  ) if field_name is not None else list(provenance.field_results.values())
        if fields and all(f.status in {"first_pass_verified", "retry_verified"} for f in fields):
            return CustomerReviewStatus.AI_REVIEWED
    return CustomerReviewStatus.UNAVAILABLE


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
        field = _accepted_ai_field(self.method, self.name, self.provenance)
        if field and (field.value != self.value or field.state not in {"known", "value"}):
            raise ValueError("Evidence value must be the exact accepted Sol field, never an Opus alternative")
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
    prep_field_name: str | None = None  # Required for an AI link; exact/human links stay compatible.

    @model_validator(mode="after")
    def accepted_candidate(self) -> LinkInfo:
        field = _accepted_ai_field(self.method, self.prep_field_name or "", self.provenance)
        if field and (field.state not in {"match", "no_match"}
                      or field.value != {"drawing_id": self.drawing_id, "bom_rows": self.bom_rows}):
            raise ValueError("AI link must use Sol's accepted drawing_id/bom_rows candidate, never verifier feedback")
        return self


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
    # Every mapping, even exact/AI-verified, is unusable until human_confirmed.

    @model_validator(mode="after")
    def accepted_candidate(self) -> NameMapping:
        field = _accepted_ai_field(self.method, self.name, self.provenance)
        if field and (field.state != "relationship" or field.value != {
            "relationship": self.relationship.value, "to_name": self.to_name,
        }):
            raise ValueError("AI mapping must use Sol's accepted relationship/to_name candidate")
        return self


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
    badge: NonEmpty  # Engineering provenance, Debug only; citations remain customer-visible.
    provenance_badge: str | None = None  # Fallback details belong inside optional Debug.
    review: ReviewState | None = None  # Null for rule-based/human values.
    sources: list[FactSource] = Field(min_length=1)
    snapshot_note: bool = False
    review_item: ReviewLink | None = None  # Actual review actions/queues are Debug only.
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


def template_candidate_value(value: JsonValue | BaseModel) -> JsonValue:
    """Semantic geometry for Sol's candidate, before attaching provenance/review.

    Nested known template fields become their values; options/unknown retain
    their state. This avoids recursively including a field's own provenance in
    its candidate digest. Numeric units are the FlatTemplate's frozen mm frame.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        return [template_candidate_value(item) for item in value]
    if isinstance(value, dict):
        if {"name", "method", "state"} <= value.keys():
            if value["state"] == "known":
                return template_candidate_value(value["value"])
            if value["state"] == "options":
                return {"state": "options", "options": [template_candidate_value(o["value"]) for o in value["options"]]}
            if value["state"] == "unknown":
                return {"state": "unknown"}
        return {key: template_candidate_value(item) for key, item in value.items()}
    return value


def _canonical_feature_notes(value: JsonValue) -> JsonValue:
    """Treat an absent optional feature note like its native null default.

    Retain every geometry value and every non-null note. This affects only
    representation equality; the original candidate and its digest are kept.
    """
    if isinstance(value, list):
        return [_canonical_feature_notes(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_feature_notes(item) for key, item in value.items()
                if not (key == "note" and item is None and value.get("kind") in {"hole", "slot"})}
    return value


class TemplateFieldBase(ContractModel):
    name: NonEmpty
    method: Method
    confidence: Confidence = Confidence.SURE
    review: ReviewState | None = None
    review_item: ReviewLink | None = None
    provenance: PrepProvenance | None = None
    essential: bool = False

    @model_validator(mode="after")
    def exact_candidate_field(self) -> TemplateFieldBase:
        field = _accepted_ai_field(self.method, self.name, self.provenance)
        if field:
            value = self.model_dump(mode="json")
            options = [o["value"] for o in value.get("options", [])]
            if (field.state != value.get("state")
                    or _canonical_feature_notes(field.value) != _canonical_feature_notes(template_candidate_value(value.get("value")))
                    or _canonical_feature_notes(field.options) != _canonical_feature_notes([template_candidate_value(option) for option in options])):
                raise ValueError("Template value/state/options must come from the accepted Sol candidate")
        return self


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
    # Options are printed alternatives; verifier disagreement remains unknown.


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
    filled_by: Literal["determine_verify", "single_model_unverified", "human"]
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
        if self.filled_by != "human":
            if (self.provenance is None or self.provenance.mode != self.filled_by
                    or self.source_sha256 not in self.provenance.source.inputs.values()):
                raise ValueError("Template filled_by/source must match its actual preparation provenance")
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
    # Compatibility input ONLY. M03/M15 ignore it for context and authorization;
    # the selected server-owned conversation is the sole source of prior turns.
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)
    conversation_id: ConversationId | None = None  # None -> create a new conversation, never reuse a global thread.


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
    conversation_id: ConversationId | None = None  # Required by the saved-message envelope; optional for old fixtures.
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


class ConversationSummary(ContractModel):
    # Server generates opaque, path-safe IDs and stamps aware UTC times. List order:
    # updated_at descending, then conversation_id ascending for equal timestamps.
    conversation_id: ConversationId
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CONVERSATION_TITLE_LIMIT)]
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def chronological(self) -> ConversationSummary:
        if self.updated_at < self.created_at:
            raise ValueError("Conversation update cannot precede creation")
        return self


class SavedUserMessage(ContractModel):
    id: MessageId
    role: Literal["user"]
    text: NonEmpty
    created_at: AwareDatetime


class SavedAssistantMessage(ContractModel):
    id: MessageId
    role: Literal["assistant"]
    # Preserve the complete reply: raw text, facts/sources, markers, attachments,
    # warnings and observations. Rendering history does not call tools or Luna.
    response: ChatResponse
    created_at: AwareDatetime


SavedChatMessage = Annotated[SavedUserMessage | SavedAssistantMessage, Field(discriminator="role")]


class ConversationListRequest(ContractModel):
    pass


class ConversationCreateRequest(Payload):
    # Empty body (fixture metadata excepted): no client ID, title, messages or ledger.
    # New chat starts empty with title "New chat"; the first user message sets
    # the title by collapsing whitespace and taking its first 80 code points.
    # M15 generates the title without a model and keeps it on later sends.
    pass


class ConversationRequest(ContractModel):
    conversation_id: ConversationId  # Decoded path ID; unknown IDs are not_found, never auto-created.


class ConversationListResponse(Payload):
    conversations: list[ConversationSummary]

    @model_validator(mode="after")
    def ordered(self) -> ConversationListResponse:
        ids = [item.conversation_id for item in self.conversations]
        ordered = sorted(self.conversations, key=lambda item: item.conversation_id)
        ordered.sort(key=lambda item: item.updated_at, reverse=True)
        if len(set(ids)) != len(ids) or self.conversations != ordered:
            raise ValueError("Conversation list needs unique IDs in updated-time order")
        return self


class ConversationDetail(Payload):
    conversation: ConversationSummary
    messages: list[SavedChatMessage]  # ALL saved messages; no model-window limit or client ledger.

    @model_validator(mode="after")
    def saved_messages(self) -> ConversationDetail:
        ids = [message.id for message in self.messages]
        times = [self.conversation.created_at, *(message.created_at for message in self.messages), self.conversation.updated_at]
        if len(set(ids)) != len(ids) or times != sorted(times):
            raise ValueError("Saved messages need unique stable IDs and chronological server timestamps")
        if any(isinstance(message, SavedAssistantMessage)
               and message.response.conversation_id != self.conversation.conversation_id for message in self.messages):
            raise ValueError("Saved assistant replies must belong to this conversation")
        return self


class ConversationSendRequest(Payload):
    # Preserve the full user text, rejecting empty/whitespace-only input. No client
    # history, facts, messages, tool results or ledger accepted.
    message: Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class ConversationSendResponse(Payload):
    conversation: ConversationSummary
    messages: tuple[SavedUserMessage, SavedAssistantMessage]  # Exactly the two committed messages, full reply included.

    @model_validator(mode="after")
    def committed_pair(self) -> ConversationSendResponse:
        ConversationDetail(conversation=self.conversation, messages=list(self.messages))
        return self


class ConversationContext(Payload):
    # SERVER ONLY: M15 projects the selected saved messages + current user message,
    # takes the last 10 individual messages, and passes ONLY these turns to Luna
    # (alongside system instructions/current tool exchange). No provider session
    # or previous_response_id may reintroduce older/another thread's context.
    conversation_id: ConversationId
    turns: list[ChatTurn] = Field(min_length=1, max_length=CHAT_CONTEXT_TURNS)

    @model_validator(mode="after")
    def current_user(self) -> ConversationContext:
        if self.turns[-1].role != "user":
            raise ValueError("Model context includes the current user message as its last turn")
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
    debug_enabled: bool = False  # A01 launch setting -> A03 status -> A04/all component props.

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


class SummarySection(ContractModel):
    # Drawing section and BOM section inventories remain separate; no implicit mapping approval.
    section: NonEmpty | None
    member_ids: list[NonEmpty]  # Drawing IDs OR stable BOM row names, according to containing list.
    part_ids: list[NonEmpty]
    count: int = Field(ge=0)
    fact: NonEmpty

    @model_validator(mode="after")
    def actual_members(self) -> SummarySection:
        if self.count != len(set(self.member_ids)) or len(self.member_ids) != self.count:
            raise ValueError("Section counts must count unique actual source members")
        if len(self.part_ids) != len(set(self.part_ids)):
            raise ValueError("Section part IDs must be unique")
        return self


class SummaryInput(Payload):
    records: list[PartRecord]  # Snapshot supplied by the records loader, never expected-answer data.


class MachineSummaryResult(Payload):
    # M14 derives this snapshot from current PartRecords, never benchmark expectations.
    records_sha256: SHA256  # contract_digest(records sorted by id, model_dump(mode='json')).
    source_hashes: dict[NonEmpty, SHA256]
    record_count: int = Field(ge=0)
    drawing_count: int = Field(ge=0)
    bom_row_count: int = Field(ge=0)
    drawing_sections: list[SummarySection]  # Include section=null for unsectioned sources.
    bom_sections: list[SummarySection]
    facts: dict[str, FactResult]  # Aggregates are returned as citable facts with actual sources.

    @model_validator(mode="after")
    def source_counts(self) -> MachineSummaryResult:
        for sections, count in ((self.drawing_sections, self.drawing_count), (self.bom_sections, self.bom_row_count)):
            ids = [name for section in sections for name in section.member_ids]
            if len(ids) != count or len(set(ids)) != count:
                raise ValueError("Summary sections must partition actual sources without duplicate linked rows")
            if any(section.fact not in self.facts for section in sections):
                raise ValueError("Each section summary needs its returned citation fact")
        if any(name != fact.fact for name, fact in self.facts.items()):
            raise ValueError("Summary fact map keys must equal stable fact names")
        return self


MoneyDKK = Annotated[str, StringConstraints(pattern=r"^(0|[1-9]\d*)\.\d{2}$")]


class MissingCostGroup(ContractModel):
    reason: Literal["missing_unit_cost", "missing_amount", "missing_total", "invalid_total", "unresolved"]
    row_names: list[NonEmpty]
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def actual_rows(self) -> MissingCostGroup:
        if self.count != len(set(self.row_names)) or self.count != len(self.row_names):
            raise ValueError("Missing-cost counts must count actual unique rows")
        return self


class CostSummaryResult(Payload):
    records_sha256: SHA256  # Same record snapshot convention as MachineSummaryResult.
    source_hashes: dict[NonEmpty, SHA256]
    currency: Literal["DKK"] = "DKK"
    recorded_total: MoneyDKK  # Decimal/integer-ore arithmetic; JSON string avoids binary rounding.
    recorded_row_names: list[NonEmpty]
    recorded_total_count: int = Field(ge=0)
    missing_total_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    missing_reasons: list[MissingCostGroup]  # Exclusive primary reason, ordered by the literal above.
    fact: NonEmpty
    facts: dict[str, FactResult]
    snapshot_note: Literal[True] = True
    caveat: NonEmpty  # Recorded snapshot only; missing totals never imply zero/free/current pricing.

    @model_validator(mode="after")
    def exhaustive_rows(self) -> CostSummaryResult:
        missing = [name for group in self.missing_reasons for name in group.row_names]
        all_rows = self.recorded_row_names + missing
        if (self.recorded_total_count != len(self.recorded_row_names)
                or self.missing_total_count != len(missing)
                or self.row_count != self.recorded_total_count + self.missing_total_count
                or len(set(all_rows)) != len(all_rows)):
            raise ValueError("Recorded and missing-cost rows must partition actual BOM rows exactly once")
        if self.fact not in self.facts or any(name != fact.fact for name, fact in self.facts.items()):
            raise ValueError("Cost summary needs its returned source-backed citation fact")
        return self


ChatToolResult = (FindPartResult | GetFactsResult | GetConnectionsResult | PartGroupResult
                  | MachineSummaryResult | CostSummaryResult | ProposeCorrectionResult)


class ToolLedgerEntry(ContractModel):
    # SERVER ONLY: record successful actual tool returns, never client/model claims.
    # The result retains the full returned facts/sources/parts. Only facts actually
    # returned by these calls authorize citations; saved assistant text does not.
    call_id: NonEmpty
    user_message_id: MessageId
    tool_name: Literal["find_part", "get_facts", "get_connections", "parts_in_section", "parts_with_material",
                       "machine_summary", "cost_summary", "propose_correction"]
    arguments: dict[str, JsonValue]
    result: ChatToolResult

    @model_validator(mode="after")
    def actual_result_type(self) -> ToolLedgerEntry:
        expected = {"find_part": FindPartResult, "get_facts": GetFactsResult, "get_connections": GetConnectionsResult,
                    "parts_in_section": PartGroupResult, "parts_with_material": PartGroupResult,
                    "machine_summary": MachineSummaryResult, "cost_summary": CostSummaryResult,
                    "propose_correction": ProposeCorrectionResult}[self.tool_name]
        if not isinstance(self.result, expected):
            raise ValueError("Ledger result must match its actual tool")
        facts = getattr(self.result, "facts", {})
        if any(name != fact.fact for name, fact in facts.items()):
            raise ValueError("Tool ledger fact keys must equal stable fact names")
        return self


class ConversationLedger(ContractModel):
    conversation_id: ConversationId
    entries: list[ToolLedgerEntry] = Field(default_factory=list)  # Full per-thread log, independent of last10 context.
    # M15 rebuilds the selected thread's fact index from these trusted returns in
    # order (latest returned value per name). Never merge a global/other ledger;
    # current-turn unique-match attachment fallback resets on every send.

    @model_validator(mode="after")
    def unique_calls(self) -> ConversationLedger:
        if len({entry.call_id for entry in self.entries}) != len(self.entries):
            raise ValueError("Tool call IDs must be unique within the owning thread")
        return self


class ConversationState(Payload):
    # SERVER-OWNED DISK SHAPE, never an API request/response. M15 alone reads/writes
    # this JSON under A01's ignored development/chat_history directory. No DB.
    # Save full history + ledger atomically; serialize read/append/tool/save for
    # each thread. Never truncate disk history to the provider window. Corrupt
    # history is an error, not an empty thread to overwrite. No API key for reads
    # or empty-thread creation. Provider/key failures are ErrorResponse, never a
    # fabricated successful reply; retain already saved messages/tool results.
    schema_version: Literal["chat-history/v1"] = "chat-history/v1"
    detail: ConversationDetail
    ledger: ConversationLedger

    @model_validator(mode="after")
    def owning_thread(self) -> ConversationState:
        if self.detail.conversation.conversation_id != self.ledger.conversation_id:
            raise ValueError("Conversation history and ledger must have the same owner")
        users = {message.id for message in self.detail.messages if message.role == "user"}
        if any(entry.user_message_id not in users for entry in self.ledger.entries):
            raise ValueError("Each tool call must belong to a saved user message in this thread")
        return self


class PrepJobRequest(Payload):
    pipeline_version: Literal["determine-verify/v1"] = PREP_PIPELINE_VERSION
    job: NonEmpty
    job_id: NonEmpty
    source: PrepSourceIdentity
    field_names: list[NonEmpty] = Field(min_length=1)
    determination_prompt_sha256: SHA256
    verification_prompt_sha256: SHA256
    output_contract_sha256: SHA256

    @model_validator(mode="after")
    def unique_inventory(self) -> PrepJobRequest:
        if len(self.field_names) != len(set(self.field_names)):
            raise ValueError("Job field inventory must be unique")
        return self


class DeterminationRequest(ContractModel):
    job: PrepJobRequest
    round: Literal[1, 2]
    previous_candidate: DeterminationOutput | None = None
    feedback: VerificationOutput | None = None

    @model_validator(mode="after")
    def correction_feedback(self) -> DeterminationRequest:
        if self.round == 1:
            if self.previous_candidate or self.feedback:
                raise ValueError("First determination has original evidence, without invented feedback")
        elif (self.previous_candidate is None or self.feedback is None
              or self.feedback.candidate_sha256 != self.previous_candidate.candidate_sha256
              or self.previous_candidate.source_sha256 != contract_digest(self.job.source)
              or self.feedback.source_sha256 != contract_digest(self.job.source)
              or set(self.previous_candidate.fields) != set(self.job.field_names)
              or set(self.feedback.fields) != set(self.job.field_names)
              or not any(v.verdict == "disagrees" for v in self.feedback.fields.values())):
            raise ValueError("Correction needs the previous exact candidate and actual Opus disagreement")
        return self


class VerificationRequest(ContractModel):
    job: PrepJobRequest  # Original evidence identity; M08 supplies the actual original attachments.
    round: Literal[1, 2]
    candidate: DeterminationOutput  # Exact Sol output, not a new blind prompt.

    @model_validator(mode="after")
    def exact_source(self) -> VerificationRequest:
        if (self.candidate.source_sha256 != contract_digest(self.job.source)
                or set(self.candidate.fields) != set(self.job.field_names)):
            raise ValueError("Verification input must bind the job's source and field inventory")
        return self


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
    Endpoint("GET", "/api/conversations", "ConversationListRequest", "ConversationListResponse", "M1"),
    Endpoint("POST", "/api/conversations", "ConversationCreateRequest", "ConversationDetail", "M1"),
    Endpoint("GET", "/api/conversations/{conversation_id}", "ConversationRequest", "ConversationDetail", "M1"),
    Endpoint("POST", "/api/conversations/{conversation_id}/messages", "ConversationSendRequest", "ConversationSendResponse", "M1"),
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
    def machine_summary(self) -> MachineSummaryResult: ...
    def cost_summary(self) -> CostSummaryResult: ...
    def propose_correction(self, fact_id: str, new_value: JsonValue, reason: str) -> ProposeCorrectionResult: ...


class ConversationService(Protocol):
    # M03 injects this one M15 service, not a second route-owned/global ledger.
    # List/create/read require no provider/key. Missing thread -> not_found;
    # send key/provider/validation failures use the existing APIError codes.
    def list_conversations(self, request: ConversationListRequest) -> ConversationListResponse: ...
    def create_conversation(self, request: ConversationCreateRequest) -> ConversationDetail: ...
    def read_conversation(self, request: ConversationRequest) -> ConversationDetail: ...
    async def send(self, request: ConversationRequest, body: ConversationSendRequest) -> ConversationSendResponse: ...


class ConversationServiceFactory(Protocol):
    # M15 exports create_chat_service with this signature in backend/app/chat.py.
    # M03 supplies A01's resolved path, M14 tools, and the server-only OpenAI
    # Responses client (None without a key). No SDK import in contracts.
    # Compatibility POST /api/chat: create if ID is None, otherwise read that ID;
    # ignore client history, delegate send, return messages[1].response.
    def __call__(self, *, history_dir: Path, tools: FactTools, client: object | None) -> ConversationService: ...


class PrepRunner(Protocol):
    # M08 owns one serial job/queue, CLI execution, bounded retry, cache and next-launch Opus retry.
    def __call__(self, request: PrepJobRequest) -> PrepProvenance: ...


class Determiner(Protocol):
    def __call__(self, request: DeterminationRequest) -> DeterminationAttempt: ...


class Verifier(Protocol):
    def __call__(self, request: VerificationRequest) -> VerificationAttempt: ...


class CandidateValidator(Protocol):
    # M09/M10 inspect actual evidence and return field validation; structure/hashes
    # alone cannot establish source truth. Never change values to repair bad JSON.
    def __call__(self, candidate: DeterminationOutput, source: PrepSourceIdentity) -> DeterminationOutput: ...


class MachineSummarizer(Protocol):
    def __call__(self, records: Sequence[PartRecord]) -> MachineSummaryResult: ...


class CostSummarizer(Protocol):
    def __call__(self, records: Sequence[PartRecord]) -> CostSummaryResult: ...


# The checker uses this finite inventory to verify the TS mirror and fixtures.
# Generic specializations are included through each concrete model's JSON schema.
CONTRACT_MODELS = {
    name: value for name, value in tuple(globals().items())
    if isinstance(value, type) and issubclass(value, ContractModel)
    and value not in {ContractModel, Payload, PrepAttempt, TemplateFieldBase, KnownField, OptionsField, TemplateOption}
    and "[" not in name
}
CONTRACT_ALIASES = {
    "Box": Box, "Point": Point, "Vector3": Vector3,
    "FactDisplay": FactDisplay, "NumericField": NumericField, "IntegerField": IntegerField,
    "TextField": TextField, "Outline": Outline, "OutlineField": OutlineField,
    "Pattern": Pattern, "Face": Face, "Feature": Feature, "FeatureField": FeatureField,
    "PartsResponse": PartsResponse, "ReviewListResponse": ReviewListResponse,
    "CustomerReviewStatus": CustomerReviewStatus, "MoneyDKK": MoneyDKK,
    "ConversationId": ConversationId, "MessageId": MessageId,
    "SavedChatMessage": SavedChatMessage, "ChatToolResult": ChatToolResult,
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
