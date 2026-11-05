/** Frozen M02 payload mirror of backend/contracts.py.
 * Schema-derived section verified by testing/smoke/A02-contracts/check_contracts.py.
 * Defaulted Python fields are optional on input; model_dump emits them.
 * Python validates runtime constraints (hashes, dates, evidence and provenance).
 * Dates are timezone-aware ISO strings; numbers are finite.
 * M2/M3 shapes reserve interfaces only, not implemented behavior.
 */

export type APIError = {
  "code": ErrorCode;
  "message": string;
  "retryable"?: boolean;
  "details"?: { [key: string]: JsonValue };
};

export type AccuracyRequest = {
  "job"?: string | null;
};

export type AccuracyResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "jobs": Array<JobAccuracy>;
};

export type BOMField = {
  "name": string;
  "original": string | null;
  "value": JsonValue;
  "confidence"?: Confidence;
  "method": Method;
  "note"?: string | null;
  "review"?: ReviewState | null;
  "provenance"?: PrepProvenance | null;
  "correction"?: Correction | null;
  "cleanup"?: Array<string>;
  "snapshot_note"?: boolean;
  "currency"?: "DKK" | null;
  "unit"?: string | null;
};

export type BOMRow = {
  "name": string;
  "display_id": string;
  "display_name": string;
  "section": string;
  "source_sha256": string;
  "fields": { [key: string]: BOMField };
  "connections"?: Array<ConnectionEvidence>;
  "identity_conflict"?: boolean;
  "snapshot_note"?: boolean;
};

export type Box = [number, number, number, number];

export type Callout = {
  "name": string;
  "kind": "hole" | "thread" | "countersink" | "counterbore" | "slot" | "tolerance" | "note";
  "text": string;
  "target": SourceTarget;
  "values": { [key: string]: JsonValue };
  "number_ids": Array<string>;
  "method"?: "parsed";
};

export type ChatMarker = {
  "kind": "cite" | "undetermined";
  "names": Array<string>;
  "raw": string;
  "start": number;
  "end": number;
  "valid": boolean;
  "error"?: WarningCode | null;
};

export type ChatObservation = {
  "provider"?: "openai";
  "model"?: "gpt-6-luna";
  "latency_ms"?: number | null;
  "input_tokens"?: number | null;
  "output_tokens"?: number | null;
  "total_tokens"?: number | null;
  "cost_usd"?: number | null;
};

export type ChatRequest = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "message": string;
  "history"?: Array<ChatTurn>;
  "conversation_id"?: string | null;
};

export type ChatResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "text": string;
  "facts": { [key: string]: FactResult };
  "parts_to_show": Array<PartAttachment>;
  "warnings": Array<ChatWarning>;
  "markers"?: Array<ChatMarker>;
  "attachment_layout": "none" | "cards" | "list";
  "conversation_id"?: string | null;
  "observation"?: ChatObservation | null;
};

export type ChatToolResult = FindPartResult | GetFactsResult | GetConnectionsResult | PartGroupResult | MachineSummaryResult | CostSummaryResult | ProposeCorrectionResult;

export type ChatTurn = {
  "role": "user" | "assistant";
  "text": string;
};

export type ChatWarning = {
  "code": WarningCode;
  "message": string;
  "names"?: Array<string>;
  "marker"?: string | null;
};

export type CircleOutline = {
  "type"?: "circle";
  "diameter": KnownNumberField | OptionsNumberField | UnknownField;
};

export type CirclePattern = {
  "type"?: "circle";
  "count": KnownIntegerField | OptionsIntegerField | UnknownField;
  "radius": KnownNumberField | OptionsNumberField | UnknownField;
  "start_angle_deg": KnownNumberField | OptionsNumberField | UnknownField;
  "evenly_spaced"?: boolean;
  "angles_deg"?: Array<KnownNumberField | OptionsNumberField | UnknownField> | null;
};

export type Confidence = "sure" | "unsure";

export type ConnectionEvidence = {
  "name": string;
  "original": string;
  "target_name": string;
  "target_row"?: string | null;
  "target_part"?: string | null;
  "resolved": boolean;
  "note"?: string | null;
};

export type ConversationContext = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "conversation_id": string;
  "turns": Array<ChatTurn>;
};

export type ConversationCreateRequest = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
};

export type ConversationDetail = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "conversation": ConversationSummary;
  "messages": Array<SavedUserMessage | SavedAssistantMessage>;
};

export type ConversationId = string;

export type ConversationLedger = {
  "conversation_id": string;
  "entries"?: Array<ToolLedgerEntry>;
};

export type ConversationListRequest = {

};

export type ConversationListResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "conversations": Array<ConversationSummary>;
};

export type ConversationRequest = {
  "conversation_id": string;
};

export type ConversationSendRequest = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "message": string;
};

export type ConversationSendResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "conversation": ConversationSummary;
  "messages": [SavedUserMessage, SavedAssistantMessage];
};

export type ConversationState = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "schema_version"?: "chat-history/v1";
  "detail": ConversationDetail;
  "ledger": ConversationLedger;
};

export type ConversationSummary = {
  "conversation_id": string;
  "title": string;
  "created_at": string;
  "updated_at": string;
};

export type Correction = {
  "original": JsonValue;
  "corrected": JsonValue;
  "by": string;
  "at": string;
  "decision_id": string;
};

export type CorrectionCheck = {
  "method"?: "string_match";
  "drawing": Array<StringMatchEvidence>;
  "bom": Array<StringMatchEvidence>;
  "message": string;
  "proves_correct"?: false;
};

export type CostSummaryResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "records_sha256": string;
  "source_hashes": { [key: string]: string };
  "currency"?: "DKK";
  "recorded_total": string;
  "recorded_row_names": Array<string>;
  "recorded_total_count": number;
  "missing_total_count": number;
  "row_count": number;
  "missing_reasons": Array<MissingCostGroup>;
  "fact": string;
  "facts": { [key: string]: FactResult };
  "snapshot_note"?: true;
  "caveat": string;
};

export type CropReference = {
  "url": string;
  "target": SourceTarget;
  "width": number;
  "height": number;
};

export type CropRequest = {
  "id": string;
  "fact": string;
};

export type CustomerReviewStatus = "Human reviewed" | "AI reviewed" | "Unavailable";

export type Decision = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "decision_id": string;
  "applies_to": string;
  "type": DecisionType;
  "value": JsonValue;
  "old_value"?: JsonValue;
  "status": "pending" | "accepted" | "rejected";
  "by": string;
  "at": string;
  "based_on": { [key: string]: string };
  "ai_answers"?: PrepProvenance | null;
  "check_result"?: CorrectionCheck | null;
  "reason"?: string | null;
  "note"?: string | null;
  "proposal_id"?: string | null;
  "supersedes"?: string | null;
};

export type DecisionJournal = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "item_id": string;
  "decisions": Array<Decision>;
};

export type DecisionType = "correction" | "link" | "set_value" | "choose_option" | "name_mapping" | "confirm" | "reject" | "approve_design";

export type DensityReference = {
  "material": string;
  "density_g_cm3": number;
  "source_url": string;
  "retrieved_at": string;
  "outside_dataset"?: true;
  "family_mapping"?: string | null;
};

export type Derivation = {
  "kind": "arithmetic" | "pattern";
  "expression": string;
  "inputs": Array<string>;
  "pattern_fact"?: string | null;
};

export type DeterminationAttempt = {
  "requested": ReaderSettings;
  "effective": ObservedReaderSettings | null;
  "status": "success" | "execution_failed" | "invalid_output";
  "failure"?: ReaderFailure | null;
  "prior_failures"?: Array<ReaderFailure>;
  "started_at": string;
  "finished_at": string;
  "cache": PrepCacheIdentity;
  "role"?: "determination";
  "output": DeterminationOutput | null;
};

export type DeterminationOutput = {
  "source_sha256": string;
  "fields": { [key: string]: DeterminedField };
  "candidate_sha256": string;
};

export type DeterminationRequest = {
  "job": PrepJobRequest;
  "round": 1 | 2;
  "previous_candidate"?: DeterminationOutput | null;
  "feedback"?: VerificationOutput | null;
};

export type DeterminedField = {
  "state": "known" | "options" | "unknown" | "value" | "match" | "no_match" | "relationship";
  "value"?: JsonValue;
  "options"?: Array<JsonValue>;
  "confidence": Confidence;
  "source_ids"?: Array<string>;
  "reason": string;
  "schema_valid": boolean;
  "evidence_valid": boolean;
  "basis"?: "printed_alternatives" | null;
};

export type DrawingEvidence = {
  "id": string;
  "pages": number;
  "image": string;
  "page_geometry": Array<PageGeometry>;
  "degraded": boolean;
  "source_quality": SourceQuality;
  "source_path": string;
  "source_sha256": string;
  "fields": { [key: string]: DrawingField };
  "numbers"?: Array<DrawingNumber>;
  "words"?: Array<DrawingWord>;
};

export type DrawingField = {
  "name": string;
  "original": string | null;
  "value": JsonValue;
  "confidence"?: Confidence;
  "method": Method;
  "note"?: string | null;
  "review"?: ReviewState | null;
  "provenance"?: PrepProvenance | null;
  "correction"?: Correction | null;
  "page": number;
  "box": [number, number, number, number];
  "source_quality": SourceQuality;
};

export type DrawingNumber = {
  "name": string;
  "text": string;
  "value": number;
  "page": number;
  "box": [number, number, number, number];
  "unit"?: string | null;
  "confidence"?: Confidence;
  "method"?: "parsed";
};

export type DrawingWord = {
  "text": string;
  "page": number;
  "box": [number, number, number, number];
};

export type ErrorCode = "missing_key" | "not_found" | "invalid_request" | "provider_error" | "prep_failed" | "model_unavailable" | "stale_conflict" | "unsupported" | "internal_error";

export type ErrorResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "error": APIError;
};

export type EvidenceField = {
  "name": string;
  "original": string | null;
  "value": JsonValue;
  "confidence"?: Confidence;
  "method": Method;
  "note"?: string | null;
  "review"?: ReviewState | null;
  "provenance"?: PrepProvenance | null;
  "correction"?: Correction | null;
};

export type ExampleWeight = {
  "example": "A" | "B" | "C" | "D";
  "material_source": "drawing" | "bom";
  "material": string;
  "density": DensityReference;
  "calculated_g": number;
  "drawing_g": number;
  "difference_percent": number;
  "matches": boolean;
};

export type Face = "top" | "bottom" | "front" | "back" | "left" | "right" | "outer" | "inner";

export type FactDisplay = ValueDisplay | OptionsDisplay | UndeterminedDisplay;

export type FactResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "fact": string;
  "part_id": string | null;
  "display": ValueDisplay | OptionsDisplay | UndeterminedDisplay;
  "rule": string;
  "badge": string;
  "provenance_badge"?: string | null;
  "review"?: ReviewState | null;
  "sources": Array<FactSource>;
  "snapshot_note"?: boolean;
  "review_item"?: ReviewLink | null;
  "correction"?: Correction | null;
};

export type FactSource = {
  "name": string;
  "says": JsonValue;
  "method": Method;
  "target": SourceTarget;
  "source_sha256"?: string | null;
  "confidence"?: Confidence;
  "source_quality"?: SourceQuality | null;
  "note"?: string | null;
  "review"?: ReviewState | null;
  "provenance"?: PrepProvenance | null;
  "crop"?: CropReference | null;
};

export type FailureClass = "oauth" | "usage_limit" | "rate_limit" | "invocation" | "missing_cli" | "timeout" | "network" | "provider_error" | "output_parse" | "output_schema" | "evidence_invalid" | "unknown_execution";

export type Feature = HoleFeature | SlotFeature;

export type FeatureField = KnownFeatureField | UnknownField;

export type FeaturePosition = {
  "x": KnownNumberField | OptionsNumberField | UnknownField;
  "y": KnownNumberField | OptionsNumberField | UnknownField;
};

export type FieldVerification = {
  "verdict": "verified" | "disagrees" | "unsure";
  "reason": string;
  "source_ids": Array<string>;
  "alternative"?: DeterminedField | null;
};

export type FindPartRequest = {
  "text": string;
};

export type FindPartResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "parts": Array<PartSummary>;
  "facts": { [key: string]: FactResult };
  "unique_part_id"?: string | null;
};

export type FlatTemplate = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "part": string;
  "template"?: "flat_part";
  "units"?: "mm";
  "filled_by": "determine_verify" | "single_model_unverified" | "human";
  "source_sha256": string;
  "review"?: ReviewState;
  "provenance"?: PrepProvenance | null;
  "outline": KnownOutlineField | UnknownField;
  "thickness": KnownNumberField | OptionsNumberField | UnknownField;
  "features"?: Array<KnownFeatureField | UnknownField>;
  "material"?: KnownTextField | OptionsTextField | UnknownField | null;
  "weight_on_drawing"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "finish_notes"?: Array<string>;
};

export type GetConnectionsResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "part_id": string;
  "connections": Array<ConnectionEvidence>;
  "facts": { [key: string]: FactResult };
  "message"?: string;
};

export type GetFactsRequest = {
  "part_id": string;
};

export type GetFactsResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "part_id": string;
  "facts": { [key: string]: FactResult };
};

export type HistoryEvent = {
  "id": string;
  "applies_to": string;
  "kind": "extracted" | "cleanup" | "ai_result" | "decision" | "source_changed" | "model_rebuilt";
  "at": string;
  "message": string;
  "value"?: JsonValue;
  "decision"?: Decision | null;
  "source_hashes"?: { [key: string]: string };
  "superseded"?: boolean;
};

export type HistoryRequest = {
  "id": string;
  "fact"?: string | null;
};

export type HistoryResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "part_id": string;
  "events": Array<HistoryEvent>;
};

export type HoleFeature = {
  "kind"?: "hole";
  "hole_type": "plain" | "threaded" | "countersunk" | "counterbored";
  "face": "top" | "bottom" | "front" | "back" | "left" | "right" | "outer" | "inner";
  "position": FeaturePosition;
  "diameter": KnownNumberField | OptionsNumberField | UnknownField;
  "through": boolean;
  "depth"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "thread_size"?: KnownTextField | OptionsTextField | UnknownField | null;
  "thread_depth"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "countersink_diameter"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "countersink_angle_deg"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "counterbore_diameter"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "counterbore_depth"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "pattern"?: RowPattern | CirclePattern | null;
  "note"?: string | null;
};

export type ImageRequest = {
  "id": string;
  "page"?: number;
  "thumb"?: 0 | 1;
};

export type InstalledIn = {
  "section": string | null;
  "connections": Array<ConnectionEvidence>;
  "note"?: string | null;
};

export type IntegerField = KnownIntegerField | OptionsIntegerField | UnknownField;

export type JobAccuracy = {
  "job": string;
  "confirmed": number;
  "rejected": number;
  "checked": number;
  "total_items": number;
  "accuracy"?: number | null;
};

export type JsonValue = null | boolean | number | string | Array<JsonValue> | { [key: string]: JsonValue };

export type KnownFeatureField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "known";
  "value": HoleFeature | SlotFeature;
  "evidence": ValueEvidence;
  "unit"?: string | null;
};

export type KnownIntegerField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "known";
  "value": number;
  "evidence": ValueEvidence;
  "unit"?: string | null;
};

export type KnownNumberField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "known";
  "value": number;
  "evidence": ValueEvidence;
  "unit"?: string | null;
};

export type KnownOutlineField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "known";
  "value": RectangleOutline | CircleOutline | RingOutline;
  "evidence": ValueEvidence;
  "unit"?: string | null;
};

export type KnownTextField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "known";
  "value": string;
  "evidence": ValueEvidence;
  "unit"?: string | null;
};

export type LinkInfo = {
  "method": Method;
  "drawing_id": string | null;
  "bom_rows": Array<string>;
  "basis"?: string | null;
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "prep_field_name"?: string | null;
};

export type MachineSummaryResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "records_sha256": string;
  "source_hashes": { [key: string]: string };
  "record_count": number;
  "drawing_count": number;
  "bom_row_count": number;
  "drawing_sections": Array<SummarySection>;
  "bom_sections": Array<SummarySection>;
  "facts": { [key: string]: FactResult };
};

export type MappingRelationship = "same" | "kind_of" | "different" | "no_equivalent";

export type MessageId = string;

export type Method = "parsed" | "cleanup_rule" | "exact_match" | "ai_read" | "ai_agreed" | "ai_agreed_after_retry" | "ai_verified" | "ai_verified_after_retry" | "ai_single_model" | "human_decision" | "unresolved";

export type MissingCostGroup = {
  "reason": "missing_unit_cost" | "missing_amount" | "missing_total" | "invalid_total" | "unresolved";
  "row_names": Array<string>;
  "count": number;
};

export type ModelExample = {
  "id": "A" | "B" | "C" | "D";
  "glb": string;
  "choices"?: { [key: string]: JsonValue };
  "possible_reading"?: boolean;
  "source_ids"?: Array<string>;
  "step"?: string | null;
  "volume_mm3"?: number | null;
};

export type ModelRequest = {
  "drawing_id": string;
  "example": "A" | "B" | "C" | "D";
};

export type ModelStatus = {
  "state": "available" | "stale" | "blocked" | "unsupported" | "missing";
  "examples"?: Array<ModelExample>;
  "selected_example"?: "A" | "B" | "C" | "D" | null;
  "reconstruction_label"?: "Reconstruction from 2D drawing. Not the original CAD model.";
  "review"?: ReviewState;
  "provenance"?: PrepProvenance | null;
  "human_input_fields"?: Array<string>;
  "unresolved_fields"?: Array<string>;
  "omitted_details"?: Array<OmittedDetail>;
  "message"?: string | null;
  "stale_reason"?: string | null;
  "built_at"?: string | null;
  "built_template_sha256"?: string | null;
  "current_template_sha256"?: string | null;
  "overall_size_mm"?: [number, number, number] | null;
  "section_view_available"?: boolean | null;
};

export type MoneyDKK = string;

export type NameMapping = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "name": string;
  "kind": "section" | "material";
  "from_name": string;
  "to_name": string | null;
  "relationship": MappingRelationship;
  "evidence": "dataset" | "general_engineering_knowledge";
  "evidence_note": string;
  "method": Method;
  "review"?: ReviewState;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
};

export type NumericField = KnownNumberField | OptionsNumberField | UnknownField;

export type ObservedReaderSettings = {
  "provider"?: "codex_cli" | "claude_code" | null;
  "model"?: string | null;
  "reasoning"?: string | null;
  "service_tier"?: string | null;
  "read_only"?: boolean | null;
  "settings"?: { [key: string]: JsonValue };
};

export type OmittedDetail = {
  "name": string;
  "reason": string;
  "source_ids"?: Array<string>;
  "review_item"?: ReviewLink | null;
};

export type OptionsDisplay = {
  "state"?: "options";
  "values": Array<JsonValue>;
  "message": string;
  "unit"?: string | null;
};

export type OptionsIntegerField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "options";
  "options": Array<TemplateOption_int_>;
  "basis"?: "printed_alternatives";
  "unit"?: string | null;
};

export type OptionsNumberField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "options";
  "options": Array<TemplateOption_float_>;
  "basis"?: "printed_alternatives";
  "unit"?: string | null;
};

export type OptionsTextField = {
  "name": string;
  "method": Method;
  "confidence"?: "sure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "options";
  "options": Array<TemplateOption_str_>;
  "basis"?: "printed_alternatives";
  "unit"?: string | null;
};

export type Outline = RectangleOutline | CircleOutline | RingOutline;

export type OutlineField = KnownOutlineField | UnknownField;

export type PageGeometry = {
  "page": number;
  "source_width": number;
  "source_height": number;
  "image_width": number;
  "image_height": number;
};

export type PartAttachment = {
  "id": string;
  "display_name": string;
  "thumbnail": string | null;
  "has_drawing": boolean;
  "has_3d": boolean;
  "examples": Array<"A" | "B" | "C" | "D">;
  "model_state": "available" | "stale" | "blocked" | "unsupported" | "missing";
  "reason": "citation" | "single_match";
  "explanation"?: string | null;
  "highlights"?: Array<SourceTarget>;
  "drawing_url"?: string | null;
  "model_urls"?: { [key: string]: string };
};

export type PartDetailResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "id": string;
  "display_name": string;
  "section": string | null;
  "has_drawing": boolean;
  "has_3d": boolean;
  "examples": Array<"A" | "B" | "C" | "D">;
  "drawing": DrawingEvidence | null;
  "bom": Array<BOMRow>;
  "link": LinkInfo | null;
  "template": string | null;
  "model": ModelStatus;
  "review_items"?: Array<ReviewLink>;
  "weight_check"?: WeightCheck | null;
  "callouts"?: Array<Callout> | null;
  "crops"?: Array<CropReference> | null;
  "readme_passages"?: Array<ReadmePassage> | null;
  "installed_in"?: InstalledIn | null;
  "facts": { [key: string]: FactResult };
};

export type PartGroupResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "parts": Array<PartSummary>;
  "facts": { [key: string]: FactResult };
  "message": string;
};

export type PartRecord = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "id": string;
  "display_name": string;
  "section": string | null;
  "has_drawing": boolean;
  "has_3d": boolean;
  "examples": Array<"A" | "B" | "C" | "D">;
  "drawing": DrawingEvidence | null;
  "bom": Array<BOMRow>;
  "link": LinkInfo | null;
  "template": string | null;
  "model": ModelStatus;
  "review_items"?: Array<ReviewLink>;
  "weight_check"?: WeightCheck | null;
  "callouts"?: Array<Callout> | null;
  "crops"?: Array<CropReference> | null;
  "readme_passages"?: Array<ReadmePassage> | null;
  "installed_in"?: InstalledIn | null;
};

export type PartRequest = {
  "id": string;
};

export type PartSummary = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "id": string;
  "display_name": string;
  "section": string | null;
  "has_drawing": boolean;
  "has_3d": boolean;
  "examples": Array<"A" | "B" | "C" | "D">;
  "thumbnail"?: string | null;
  "model_state": "available" | "stale" | "blocked" | "unsupported" | "missing";
  "review_items"?: Array<ReviewLink>;
  "weight_check"?: WeightCheck | null;
};

export type PartsInSectionRequest = {
  "section": string;
};

export type PartsRequest = {
  "q"?: string;
  "section"?: string | null;
  "material"?: string | null;
  "has_3d"?: boolean | null;
  "review_status"?: ReviewStatus | null;
};

export type PartsResponse = Array<PartSummary>;

export type PartsWithMaterialRequest = {
  "material": string;
};

export type Pattern = RowPattern | CirclePattern;

export type Point = [number, number];

export type PrepBatchResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "records": Array<PrepProvenance>;
  "counts": PrepCounts;
};

export type PrepCacheIdentity = {
  "pipeline_version"?: "determine-verify/v1";
  "role": "determination" | "verification";
  "source_sha256": string;
  "field_names_sha256": string;
  "candidate_sha256": string | null;
  "feedback_sha256": string | null;
  "prompt_sha256": string;
  "output_contract_sha256": string;
  "settings": ReaderSettings;
  "settings_basis": "requested" | "confirmed";
  "effective_sha256": string | null;
  "mode": "determine_verify" | "single_model_unverified";
};

export type PrepCounts = {
  "count_unit"?: "field";
  "total_fields": number;
  "first_pass_verified": number;
  "retry_verified": number;
  "unresolved": number;
  "unverified_fallback": number;
  "execution_failed_attempts": number;
};

export type PrepFieldResult = {
  "status": "first_pass_verified" | "retry_verified" | "unresolved" | "unverified_fallback";
  "candidate_sha256": string | null;
  "accepted": DeterminedField | null;
};

export type PrepJobRequest = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "pipeline_version"?: "determine-verify/v1";
  "job": string;
  "job_id": string;
  "source": PrepSourceIdentity;
  "field_names": Array<string>;
  "determination_prompt_sha256": string;
  "verification_prompt_sha256": string;
  "output_contract_sha256": string;
};

export type PrepProvenance = {
  "pipeline_version"?: "determine-verify/v1";
  "job": string;
  "job_id": string;
  "mode": "determine_verify" | "single_model_unverified";
  "outcome": "first_pass_verified" | "retry_verified" | "unverified_fallback" | "unresolved";
  "rounds": Array<PrepRound>;
  "source": PrepSourceIdentity;
  "field_names": Array<string>;
  "determination_prompt_sha256": string;
  "verification_prompt_sha256": string;
  "output_contract_sha256": string;
  "field_results"?: { [key: string]: PrepFieldResult };
  "next_launch_attempt_opus"?: true;
};

export type PrepRound = {
  "round": 1 | 2;
  "determination": DeterminationAttempt;
  "verification": VerificationAttempt | null;
};

export type PrepSourceIdentity = {
  "inputs": { [key: string]: string };
  "source_ids": { [key: string]: string };
};

export type ProposeCorrectionRequest = {
  "fact_id": string;
  "new_value": JsonValue;
  "reason": string;
};

export type ProposeCorrectionResult = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "item": ReviewItem;
  "decision": Decision;
  "review_link": ReviewLink;
};

export type ReaderFailure = {
  "classification": FailureClass;
  "execution_failure": boolean;
  "message": string;
  "exit_code"?: number | null;
  "retryable"?: boolean;
  "troubleshooting"?: Array<string>;
  "diagnostic_sha256"?: string | null;
};

export type ReaderSettings = {
  "provider": "codex_cli" | "claude_code";
  "model": string;
  "reasoning": string;
  "service_tier": string;
  "read_only"?: true;
  "settings"?: { [key: string]: JsonValue };
};

export type ReadmePassage = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "name": string;
  "section": string;
  "paragraph": number;
  "text": string;
  "source_sha256": string;
  "method"?: "parsed";
  "snapshot_note"?: boolean;
  "missing_images"?: Array<string>;
  "mentions_unavailable_native_cad"?: boolean;
};

export type ReadmeRequest = {
  "q"?: string;
};

export type ReadmeResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "passages": Array<ReadmePassage>;
};

export type RectangleOutline = {
  "type"?: "rectangle";
  "length": KnownNumberField | OptionsNumberField | UnknownField;
  "width": KnownNumberField | OptionsNumberField | UnknownField;
};

export type RefreshRequest = {
  "part_ids": Array<string>;
  "decision_ids": Array<string>;
  "rebuild_models"?: boolean;
};

export type RefreshResult = {
  "part_ids": Array<string>;
  "facts": { [key: string]: FactResult };
  "models": { [key: string]: ModelStatus };
  "warnings"?: Array<string>;
};

export type ReviewAction = "accept" | "reject" | "set_value" | "choose_option" | "approve_mapping" | "confirm" | "approve_design";

export type ReviewActionRequest = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "action": ReviewAction;
  "value"?: JsonValue;
  "note"?: string | null;
  "source_ids"?: Array<string>;
};

export type ReviewActionResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "item": ReviewItem;
  "decisions": Array<Decision>;
  "refresh": RefreshResult;
};

export type ReviewItem = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "id": string;
  "kind": "correction" | "link" | "template_field" | "name_mapping" | "scan_reading" | "ai_label" | "whole_design" | "weight";
  "applies_to": string;
  "part_id": string | null;
  "status": "pending" | "accepted" | "rejected" | "resolved" | "source_changed";
  "title": string;
  "message": string;
  "current_value"?: JsonValue;
  "proposed_value"?: JsonValue;
  "options"?: Array<JsonValue>;
  "sources"?: Array<FactSource>;
  "source_hashes": { [key: string]: string };
  "ai_answers"?: PrepProvenance | null;
  "mapping"?: NameMapping | null;
  "check_result"?: CorrectionCheck | null;
  "review"?: ReviewState | null;
  "allowed_actions": Array<ReviewAction>;
  "proposal_id"?: string | null;
  "created_at": string;
  "updated_at": string;
  "blocking_fields"?: Array<string> | null;
  "approval_note_required"?: boolean | null;
  "weight_check"?: WeightCheck | null;
};

export type ReviewItemRequest = {
  "item_id": string;
};

export type ReviewLink = {
  "id": string;
  "href": string;
};

export type ReviewListRequest = {
  "status"?: "pending" | "accepted" | "rejected" | "resolved" | "source_changed" | "all";
  "part_id"?: string | null;
  "tab"?: "corrections" | "needs_input" | "ai_interpretations" | "possible_readings" | null;
  "drawing_id"?: string | null;
  "kind"?: string | null;
  "method"?: Method | null;
  "review_status"?: ReviewStatus | null;
  "weight_state"?: "Passed" | "Flagged" | "FAILED" | "Skipped" | null;
};

export type ReviewListResponse = Array<ReviewItem>;

export type ReviewState = {
  "status"?: ReviewStatus;
  "by"?: string | null;
  "at"?: string | null;
  "based_on"?: { [key: string]: string };
  "decision_id"?: string | null;
};

export type ReviewStatus = "not_reviewed" | "human_confirmed" | "human_rejected" | "source_changed";

export type RingOutline = {
  "type"?: "ring";
  "outer_diameter": KnownNumberField | OptionsNumberField | UnknownField;
  "inner_diameter": KnownNumberField | OptionsNumberField | UnknownField;
};

export type RowPattern = {
  "type"?: "row";
  "count": KnownIntegerField | OptionsIntegerField | UnknownField;
  "spacing": KnownNumberField | OptionsNumberField | UnknownField;
  "direction_deg": KnownNumberField | OptionsNumberField | UnknownField;
};

export type SavedAssistantMessage = {
  "id": string;
  "role": "assistant";
  "response": ChatResponse;
  "created_at": string;
};

export type SavedChatMessage = SavedUserMessage | SavedAssistantMessage;

export type SavedUserMessage = {
  "id": string;
  "role": "user";
  "text": string;
  "created_at": string;
};

export type SlotFeature = {
  "kind"?: "slot";
  "face": "top" | "bottom" | "front" | "back" | "left" | "right" | "outer" | "inner";
  "position": FeaturePosition;
  "width": KnownNumberField | OptionsNumberField | UnknownField;
  "length": KnownNumberField | OptionsNumberField | UnknownField;
  "direction_deg": KnownNumberField | OptionsNumberField | UnknownField;
  "through": boolean;
  "depth"?: KnownNumberField | OptionsNumberField | UnknownField | null;
  "pattern"?: RowPattern | CirclePattern | null;
  "note"?: string | null;
};

export type SourceQuality = "clean" | "degraded" | "missing";

export type SourceTarget = {
  "kind": "drawing" | "bom" | "template" | "part" | "readme";
  "name": string;
  "part_id"?: string | null;
  "drawing_id"?: string | null;
  "row_name"?: string | null;
  "page"?: number | null;
  "box"?: [number, number, number, number] | null;
};

export type StatusRequest = {

};

export type StatusResponse = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "chat_available": boolean;
  "chat_state": "configured" | "missing_key";
  "message": string;
  "chat_provider"?: "openai";
  "chat_model"?: "gpt-6-luna";
  "cad_available"?: boolean | null;
  "debug_enabled"?: boolean;
};

export type StringMatchEvidence = {
  "source_name": string;
  "matched": boolean;
  "text": string | null;
};

export type SummaryInput = {
  "fixture"?: boolean;
  "synthetic"?: boolean;
  "fixture_note"?: string | null;
  "records": Array<PartRecord>;
};

export type SummarySection = {
  "section": string | null;
  "member_ids": Array<string>;
  "part_ids": Array<string>;
  "count": number;
  "fact": string;
};

export type TemplateOption_float_ = {
  "value": number;
  "evidence": ValueEvidence;
  "label"?: string | null;
};

export type TemplateOption_int_ = {
  "value": number;
  "evidence": ValueEvidence;
  "label"?: string | null;
};

export type TemplateOption_str_ = {
  "value": string;
  "evidence": ValueEvidence;
  "label"?: string | null;
};

export type TextField = KnownTextField | OptionsTextField | UnknownField;

export type ToolLedgerEntry = {
  "call_id": string;
  "user_message_id": string;
  "tool_name": "find_part" | "get_facts" | "get_connections" | "parts_in_section" | "parts_with_material" | "machine_summary" | "cost_summary" | "propose_correction";
  "arguments": { [key: string]: JsonValue };
  "result": FindPartResult | GetFactsResult | GetConnectionsResult | PartGroupResult | MachineSummaryResult | CostSummaryResult | ProposeCorrectionResult;
};

export type UndeterminedDisplay = {
  "state"?: "undetermined";
  "reason": UndeterminedReason;
  "message": string;
};

export type UndeterminedReason = "missing" | "unreadable_scan" | "unsure_source" | "unlabelled_measurement" | "source_conflict" | "unmapped_names" | "unlinked" | "model_disagreement" | "model_unsure" | "invalid_ai_answer" | "pending_input" | "source_changed" | "unsupported_question";

export type UnknownField = {
  "name": string;
  "method": Method;
  "confidence"?: "unsure";
  "review"?: ReviewState | null;
  "review_item"?: ReviewLink | null;
  "provenance"?: PrepProvenance | null;
  "essential"?: boolean;
  "state"?: "unknown";
  "reason": UndeterminedReason;
  "message": string;
  "evidence"?: ValueEvidence;
};

export type ValueDisplay = {
  "state"?: "value";
  "value": JsonValue;
  "label"?: string | null;
  "unit"?: string | null;
};

export type ValueEvidence = {
  "number_ids"?: Array<string>;
  "source_ids"?: Array<string>;
  "derivation"?: Derivation | null;
};

export type Vector3 = [number, number, number];

export type VerificationAttempt = {
  "requested": ReaderSettings;
  "effective": ObservedReaderSettings | null;
  "status": "success" | "execution_failed" | "invalid_output";
  "failure"?: ReaderFailure | null;
  "prior_failures"?: Array<ReaderFailure>;
  "started_at": string;
  "finished_at": string;
  "cache": PrepCacheIdentity;
  "role"?: "verification";
  "candidate_sha256": string;
  "source_sha256": string;
  "output": VerificationOutput | null;
};

export type VerificationOutput = {
  "candidate_sha256": string;
  "source_sha256": string;
  "fields": { [key: string]: FieldVerification };
  "verification_sha256": string;
};

export type VerificationRequest = {
  "job": PrepJobRequest;
  "round": 1 | 2;
  "candidate": DeterminationOutput;
};

export type WarningCode = "invalid_citation" | "invalid_undetermined" | "unsupported_value" | "uncited_answer" | "malformed_marker" | "single_model" | "stale_model";

export type WeightCheck = {
  "state": "Passed" | "Flagged" | "FAILED" | "Skipped";
  "message": string;
  "examples"?: Array<ExampleWeight>;
  "tolerance_percent"?: number;
  "review"?: ReviewState | null;
  "approval_note"?: string | null;
};

export const API_ENDPOINTS = [
  {
    "method": "GET",
    "path": "/api/status",
    "request": "StatusRequest",
    "response": "StatusResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/parts",
    "request": "PartsRequest",
    "response": "PartsResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/parts/{id}",
    "request": "PartRequest",
    "response": "PartDetailResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/parts/{id}/image",
    "request": "ImageRequest",
    "response": "BinaryResponse",
    "milestone": "M1",
    "media_type": "image/png"
  },
  {
    "method": "GET",
    "path": "/api/models/{drawing_id}_{example}.glb",
    "request": "ModelRequest",
    "response": "BinaryResponse",
    "milestone": "M1",
    "media_type": "model/gltf-binary"
  },
  {
    "method": "POST",
    "path": "/api/chat",
    "request": "ChatRequest",
    "response": "ChatResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/conversations",
    "request": "ConversationListRequest",
    "response": "ConversationListResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "POST",
    "path": "/api/conversations",
    "request": "ConversationCreateRequest",
    "response": "ConversationDetail",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/conversations/{conversation_id}",
    "request": "ConversationRequest",
    "response": "ConversationDetail",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "POST",
    "path": "/api/conversations/{conversation_id}/messages",
    "request": "ConversationSendRequest",
    "response": "ConversationSendResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/review",
    "request": "ReviewListRequest",
    "response": "ReviewListResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "POST",
    "path": "/api/review/{item_id}",
    "request": "ReviewActionRequest",
    "response": "ReviewActionResponse",
    "milestone": "M1",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/parts/{id}/history",
    "request": "HistoryRequest",
    "response": "HistoryResponse",
    "milestone": "M2",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/accuracy",
    "request": "AccuracyRequest",
    "response": "AccuracyResponse",
    "milestone": "M2",
    "media_type": "application/json"
  },
  {
    "method": "GET",
    "path": "/api/parts/{id}/crop",
    "request": "CropRequest",
    "response": "BinaryResponse",
    "milestone": "M3",
    "media_type": "image/png"
  },
  {
    "method": "GET",
    "path": "/api/models/{drawing_id}_{example}.step",
    "request": "ModelRequest",
    "response": "BinaryResponse",
    "milestone": "M3",
    "media_type": "model/step"
  },
  {
    "method": "GET",
    "path": "/api/readme",
    "request": "ReadmeRequest",
    "response": "ReadmeResponse",
    "milestone": "M3",
    "media_type": "application/json"
  }
] as const;

// END GENERATED PAYLOAD TYPES

// Frozen URL policy: encode a complete stable name into ONE RFC3986 segment.
// Server path converters must retain slash-bearing IDs; decode exactly once.
export function normalize_component(value: string): string {
  const result = value.normalize("NFKC").toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
  if (!result) throw new Error("Stable-name component has no usable characters");
  return result;
}

export function drawing_id(value: string): string {
  const result = value.trim().toUpperCase();
  if (!/^D-\d{3}$/.test(result)) throw new Error("Drawing ID must be D- followed by three digits");
  return result;
}

export const drawing_fact_name = (id: string, field: string): string =>
  `${drawing_id(id)}/drawing/${normalize_component(field)}`;
export const template_fact_name = (id: string, field: string): string =>
  `${drawing_id(id)}/template/${normalize_component(field)}`;
export const drawing_part_name = (id: string): string => `${drawing_id(id)}/part`;
export function drawing_number_name(id: string, token: string, occurrence: number): string {
  if (!Number.isInteger(occurrence) || occurrence < 1) throw new Error("Number occurrence must be positive");
  return `${drawing_id(id)}/drawing/n/${normalize_component(token)}@${occurrence}`;
}
export const bom_row_name = (section: string, name: string): string =>
  `BOM:${normalize_component(section)}/${normalize_component(name)}`;
export const bom_fact_name = (section: string, name: string, field: string): string =>
  `${bom_row_name(section, name)}/${normalize_component(field)}`;
export const bom_part_name = (section: string, name: string): string => `${bom_row_name(section, name)}/part`;
export const mapping_name = (kind: "section" | "material", source: string, target: string): string =>
  `names/${kind}/${normalize_component(source)} -> ${normalize_component(target)}`;
export function readme_name(section: string, paragraph: number): string {
  if (!Number.isInteger(paragraph) || paragraph < 1) throw new Error("Paragraph index must be positive");
  return `README/${normalize_component(section)}/p${paragraph}`;
}

export function encode_id(value: string): string {
  return encodeURIComponent(value).replace(/[!'()*]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
}
export function decode_id(segment: string): string {
  if (segment.includes("/")) throw new Error("Expected a single percent-encoded ID segment");
  return decodeURIComponent(segment);
}
export const part_api_path = (id: string): string => `/api/parts/${encode_id(id)}`;
export function image_api_path(id: string, page = 1, thumb = false): string {
  if (!Number.isInteger(page) || page < 1) throw new Error("Page numbers are 1-based");
  return `${part_api_path(id)}/image?page=${page}&thumb=${Number(thumb)}`;
}
export const review_api_path = (id: string): string => `/api/review/${encode_id(id)}`;
export function model_api_path(id: string, example: ModelRequest["example"], format: "glb" | "step" = "glb"): string {
  return `/api/models/${drawing_id(id)}_${example}.${format}`;
}
export const part_link = (id: string): string => `/part/${encode_id(id)}`;
export const review_link = (id: string): string => `/debug/review/${encode_id(id)}`;

function box_transform(box: Box, page: PageGeometry, zoom: number, offset: Point, inverse: boolean): Box {
  if (![...box, zoom, ...offset, page.source_width, page.source_height, page.image_width, page.image_height]
    .every(Number.isFinite) || zoom <= 0 || box[2] < 0 || box[3] < 0 ||
    page.source_width <= 0 || page.source_height <= 0 || page.image_width <= 0 || page.image_height <= 0) {
    throw new Error("Page dimensions/zoom must be positive and coordinates finite; sizes cannot be negative");
  }
  const sx = page.image_width / page.source_width * zoom;
  const sy = page.image_height / page.source_height * zoom;
  const [x, y, width, height] = box;
  return inverse
    ? [(x - offset[0]) / sx, (y - offset[1]) / sy, width / sx, height / sy]
    : [x * sx + offset[0], y * sy + offset[1], width * sx, height * sy];
}

// Saved page coordinates already include PDF crop/rotation. Box=[x,y,w,h],
// top-left origin, x right/y down. Actual PNG dimensions supply both scales.
// Result is CSS/rendered-image pixels at zoom, plus padding/letterbox offset.
export const source_box_to_pixels = (box: Box, page: PageGeometry, zoom = 1, offset: Point = [0, 0]): Box =>
  box_transform(box, page, zoom, offset, false);
export const pixel_box_to_source = (box: Box, page: PageGeometry, zoom = 1, offset: Point = [0, 0]): Box =>
  box_transform(box, page, zoom, offset, true);

export const RECONSTRUCTION_LABEL = "Reconstruction from 2D drawing. Not the original CAD model." as const;
export const SINGLE_MODEL_LABEL = "UNVERIFIED: Sol only; Opus execution failed." as const; // Debug only.
export const PREP_PIPELINE_VERSION = "determine-verify/v1" as const;
export const DEBUG_ENV = "MERIDIAN_DEBUG" as const;
export const CHAT_MODEL = "gpt-6-luna" as const;
export const CHAT_CONTEXT_TURNS = 10 as const; // Includes the current user message; saved history is unlimited.
export const CONVERSATION_TITLE_LIMIT = 80 as const;

// API call shapes distinguish decoded path IDs, query values, and POST bodies.
// PNG/GLB/STEP successes are binary Blob values; every non-2xx JSON response is
// ErrorResponse (including validation failures). M2/M3 methods remain optional.
export interface ApiCalls {
  status: { query: StatusRequest; response: StatusResponse };
  parts: { query: PartsRequest; response: PartsResponse };
  part: { path: PartRequest; response: PartDetailResponse };
  image: { path: PartRequest; query: Pick<ImageRequest, "page" | "thumb">; response: Blob };
  model: { path: ModelRequest; response: Blob };
  chat: { body: ChatRequest; response: ChatResponse };
  conversations: { query: ConversationListRequest; response: ConversationListResponse };
  create_conversation: { body: ConversationCreateRequest; response: ConversationDetail };
  conversation: { path: ConversationRequest; response: ConversationDetail };
  send_conversation: { path: ConversationRequest; body: ConversationSendRequest; response: ConversationSendResponse };
  review: { query: ReviewListRequest; response: ReviewListResponse };
  review_action: { path: ReviewItemRequest; body: ReviewActionRequest; response: ReviewActionResponse };
  history: { path: PartRequest; query: Pick<HistoryRequest, "fact">; response: HistoryResponse };
  accuracy: { query: AccuracyRequest; response: AccuracyResponse };
  crop: { path: PartRequest; query: Pick<CropRequest, "fact">; response: Blob };
  step: { path: ModelRequest; response: Blob };
  readme: { query: ReadmeRequest; response: ReadmeResponse };
}

export interface ApiClient {
  status(request?: StatusRequest): Promise<StatusResponse>;
  parts(request?: PartsRequest): Promise<PartsResponse>;
  part(request: PartRequest): Promise<PartDetailResponse>;
  image(request: ImageRequest): Promise<Blob>;
  model(request: ModelRequest): Promise<Blob>;
  chat(request: ChatRequest): Promise<ChatResponse>;
  conversations(request?: ConversationListRequest): Promise<ConversationListResponse>;
  create_conversation(request?: ConversationCreateRequest): Promise<ConversationDetail>;
  conversation(request: ConversationRequest): Promise<ConversationDetail>;
  send_conversation(path: ConversationRequest, body: ConversationSendRequest): Promise<ConversationSendResponse>;
  review(request?: ReviewListRequest): Promise<ReviewListResponse>;
  review_action(path: ReviewItemRequest, body: ReviewActionRequest): Promise<ReviewActionResponse>;
  history?(request: HistoryRequest): Promise<HistoryResponse>;
  accuracy?(request?: AccuracyRequest): Promise<AccuracyResponse>;
  crop?(request: CropRequest): Promise<Blob>;
  step?(request: ModelRequest): Promise<Blob>;
  readme?(request?: ReadmeRequest): Promise<ReadmeResponse>;
}

// M03 wires the proposal callback into M14. Review directly uses records,
// decisions and CAD; neither side imports chat/tools/router to refresh state.
export type ProposeCorrectionCallback = (request: ProposeCorrectionRequest) => ProposeCorrectionResult;
export type RefreshCallback = (request: RefreshRequest) => RefreshResult;
export type ReviewActionHandler = (item_id: string, action: ReviewActionRequest, reviewer: string) => ReviewActionResponse;
export type RecordsRebuilder = (part_ids?: readonly string[] | null) => PartRecord[];
export type ModelRebuilder = (record: PartRecord, template: FlatTemplate) => ModelStatus;
export type DecisionAppender = (decision: Decision) => Decision;
export type FactResolver = (record: PartRecord) => Record<string, FactResult>;
export type TemplateLoader = (drawing_id: string) => FlatTemplate | null;
export interface ReviewDependencies {
  append_decision: DecisionAppender;
  rebuild_records: RecordsRebuilder;
  resolve_facts: FactResolver;
  load_template: TemplateLoader;
  rebuild_model: ModelRebuilder | null;
}
export interface FactTools {
  find_part(text: string): FindPartResult;
  get_facts(part_id: string): GetFactsResult;
  get_connections(part_id: string): GetConnectionsResult;
  parts_in_section(section: string): PartGroupResult;
  parts_with_material(material: string): PartGroupResult;
  machine_summary(): MachineSummaryResult;
  cost_summary(): CostSummaryResult;
  propose_correction(fact_id: string, new_value: JsonValue, reason: string): ProposeCorrectionResult;
}

// Server-only call boundaries, mirroring Python. These interfaces do not expose
// disk state/ledger or SDK clients through ApiClient. M03 injects one M15 service.
export interface ConversationService {
  list_conversations(request: ConversationListRequest): ConversationListResponse;
  create_conversation(request: ConversationCreateRequest): ConversationDetail;
  read_conversation(request: ConversationRequest): ConversationDetail;
  send(request: ConversationRequest, body: ConversationSendRequest): Promise<ConversationSendResponse>;
}
export type ConversationServiceFactory = (dependencies: {
  history_dir: string; tools: FactTools; client: object | null;
}) => ConversationService;
// /api/chat is a compatibility adapter to that same service. Ignore history;
// absent ID creates a thread; unknown ID errors; return the saved assistant reply.
// ConversationContext/ConversationState/ConversationLedger are SERVER ONLY.
// Only selected-thread context.turns goes to Luna (plus system/current tools).
// Rebuild authorization from trusted stored tool returns, never client history
// or saved assistant claims. Current-turn unique-match fallback never carries over.

export type PrepRunner = (request: PrepJobRequest) => PrepProvenance;
export type Determiner = (request: DeterminationRequest) => DeterminationAttempt;
export type Verifier = (request: VerificationRequest) => VerificationAttempt;
export type CandidateValidator = (candidate: DeterminationOutput, source: PrepSourceIdentity) => DeterminationOutput;
export type MachineSummarizer = (records: readonly PartRecord[]) => MachineSummaryResult;
export type CostSummarizer = (records: readonly PartRecord[]) => CostSummaryResult;

// Customer labels describe actual current review. Source values remain usable
// even when their review is Unavailable. Fallback/parsed/legacy methods confer no AI review.
export interface CustomerReviewInput {
  usable: boolean;
  current_source_hashes: Readonly<Record<string, string>>;
  review?: ReviewState | null;
  provenance?: PrepProvenance | null;
  field_name?: string | null;
}
export function customer_review_status(input: CustomerReviewInput): CustomerReviewStatus {
  const {usable, current_source_hashes: current, review, provenance, field_name} = input;
  if (!usable || Object.keys(current).length === 0) return "Unavailable";
  const based = Object.entries(review?.based_on ?? {});
  if (review?.status === "human_confirmed" && review.by && review.at && based.length > 0 &&
      based.every(([name, hash]) => current[name] === hash)) return "Human reviewed";
  if (provenance?.pipeline_version === PREP_PIPELINE_VERSION &&
      Object.entries(provenance.source.inputs).every(([name, hash]) => current[name] === hash)) {
    const fields = field_name == null ? Object.values(provenance.field_results ?? {}) :
      (provenance.field_results?.[field_name] ? [provenance.field_results[field_name]] : []);
    if (fields.length > 0 && fields.every(field => field.status === "first_pass_verified" || field.status === "retry_verified")) {
      return "AI reviewed";
    }
  }
  return "Unavailable";
}

export type CustomerPage = "chat" | "parts";
export type ShellNavigationItem = CustomerPage | "debug";
export function shell_navigation(status: Pick<StatusResponse, "debug_enabled">): ShellNavigationItem[] {
  return status.debug_enabled === true ? ["chat", "parts", "debug"] : ["chat", "parts"];
}
export type DebugPanel = "review" | "history" | "preparation" | "diagnostics";
export type DebugAccess = {
  enabled: true;
  on_open_review: (item: ReviewLink) => void;
  on_open_history?: (fact_name: string) => void;
};
export type DebugContext = { enabled: false } | DebugAccess;
// A03 propagates A01's launch setting in /api/status. A04 passes the same context
// to every embedded/standalone view; missing props/status always hide Debug.
export function debug_context(status: Pick<StatusResponse, "debug_enabled">,
                              actions: Omit<DebugAccess, "enabled">): DebugContext {
  return status.debug_enabled === true ? { ...actions, enabled: true } : { enabled: false };
}
export interface ShellProps {
  api: ApiClient;
  status: StatusResponse;
  initial_page?: CustomerPage;
  initial_debug_panel?: DebugPanel; // Ignored unless status.debug_enabled === true.
  initial_conversation_id?: ConversationId | null; // M04 restores selection across reload; verify by server read.
  on_open_part: OpenPart;
  on_open_source: OpenSource;
}

export type PartViewTab = "drawing" | "model" | "detail";
export interface PartOpenRequest {
  part_id: string;
  tab?: PartViewTab;
  highlights?: SourceTarget[];
  example?: ModelRequest["example"] | null;
}
export type OpenPart = (request: PartOpenRequest) => void;
export type OpenSource = (target: SourceTarget) => void;
export type ConversationPartOpenRequest = PartOpenRequest & { conversation_id: ConversationId };
export type OpenConversationPart = (request: ConversationPartOpenRequest) => void;
export type OpenConversationSource = (target: SourceTarget, conversation_id: ConversationId) => void;

// A17 Evidence.tsx: values, units, source navigation and three honest review labels.
// All provenance, uncertainty reasons, review actions and warnings are inside Debug.
// Marker spans count Unicode code points (Array.from(text)); hide raw markers.
export interface EvidenceProps {
  response: ChatResponse;
  on_open_source: OpenSource;
  debug?: DebugContext;
}
export interface SourceTagProps {
  facts: FactResult[];
  on_open_source: OpenSource;
  debug?: DebugContext;
}
export interface UndeterminedProps {
  fact: FactResult;
  debug?: DebugContext; // Ordinary label is Unavailable; detailed reason/action is Debug only.
}
export interface MethodBadgeProps {
  debug: DebugAccess;
  method: Method;
  badge: string;
  review?: ReviewState | null;
  provenance?: PrepProvenance | null;
  fact_name?: string;
}
export interface WarningListProps { debug: DebugAccess; warnings: ChatWarning[] }
export interface ReviewStatusProps { status: CustomerReviewStatus }
export interface PartDebugProps {
  debug: DebugAccess;
  part: PartRecord; // Weight (including failed/flagged/skipped), stale/omitted details, review queues, hashes.
  facts?: Record<string, FactResult>;
}

export type ClientChatMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; response: ChatResponse };

// A18 Chat.tsx loads the complete selected conversation from the server, even
// without a key. New chat calls create_conversation; reads never call Luna.
// M04 owns/persists selected_conversation_id and clears its adjacent part panel
// when selection changes (including New chat). It ignores late part/source
// callbacks for another conversation. M18 similarly ignores late reads/sends
// when rendering the selected thread; replies remain saved in their own thread.
export interface ChatProps {
  api: ApiClient;
  status: StatusResponse;
  selected_conversation_id: ConversationId | null;
  on_select_conversation: (conversation_id: ConversationId) => void;
  on_open_part: OpenConversationPart;
  on_open_source: OpenConversationSource;
  debug?: DebugContext;
  initial_messages?: ClientChatMessage[]; // Legacy fixture bootstrap only; ignored when a server thread is selected.
}

// A19 PartPage.tsx: same read-only view in Parts, Chat, and Review. Review
// controls belong around this component in A22, never inside the part view.
export interface PartPageProps {
  api: ApiClient;
  part_id: string;
  record?: PartDetailResponse;
  initial_tab?: PartViewTab;
  highlights?: SourceTarget[];
  example?: ModelRequest["example"] | null;
  embedded?: boolean;
  on_open_part: OpenPart;
  on_open_source: OpenSource;
  debug?: DebugContext;
  on_close?: () => void;
}
export interface DrawingViewProps {
  part_id: string;
  drawing: DrawingEvidence;
  highlights?: SourceTarget[];
  initial_page?: number;
  initial_zoom?: number;
  debug?: DebugContext;
}
export interface BOMRowCardProps { row: BOMRow; facts: FactResult[]; on_open_source: OpenSource; debug?: DebugContext }

// A20 Parts.tsx: same navigation callback as Chat and the shell.
export interface PartsProps {
  api: ApiClient;
  on_open_part: OpenPart;
  initial_query?: PartsRequest;
  debug?: DebugContext; // Engineering review filters and queues are Debug only.
}

// A21 Viewer3D.tsx: A is only the initial viewing choice, never an approval.
// Hide unavailable tabs; stale assets remain viewable, with details inside Debug.
// Keep RECONSTRUCTION_LABEL visible in the ordinary viewer.
export interface Viewer3DProps {
  part: PartRecord;
  example?: ModelRequest["example"] | null;
  on_select_example?: (example: ModelRequest["example"]) => void;
  on_open_source: OpenSource;
  debug?: DebugContext;
  show_section?: boolean; // Reserved M3, hollow clip only.
}

// A22 Review.tsx: action body goes to review_action; updated item/refresh comes
// back. Reviewer is displayed from settings; the server stamps the journal.
export interface ReviewProps {
  debug: DebugAccess; // Mounted only inside Debug, never an ordinary navigation tab.
  api: ApiClient;
  reviewer_name: string;
  on_open_part: OpenPart;
  on_open_source: OpenSource;
  initial_item_id?: string;
  initial_part_id?: string;
  initial_filter?: ReviewListRequest;
  on_reviewed?: (result: ReviewActionResponse) => void;
}
