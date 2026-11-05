"""Explicit M1 preparation and its one saved, CLI-free consumer boundary.

Run with ``python -m backend.ai.prepare`` from development, supplying downloaded
deterministic inputs and an actual shared reservation callback. Import/load never
constructs a runner or starts a reader. M08 owns all stage retries, cache, locks,
settings observations and child launches; this module only orders domain jobs.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Literal
import uuid

from pydantic import Field, model_validator

from ..contracts import (
    BOMRow, ContractModel, DrawingEvidence, FactSource, FlatTemplate,
    Method, NameMapping, PrepBatchResult, PrepCounts, PrepProvenance, ReviewAction, ReviewItem,
    ReviewLink, ReviewStatus, SourceTarget, ValueEvidence, contract_digest,
    drawing_part_name, prep_counts, review_api_path, template_fact_name,
)
from . import matching, vision_jobs
from .runner import CliReservation, EvidenceError, Runner


_WORKSPACE = Path(__file__).resolve().parents[3]
_METHODS = {"first_pass_verified": Method.AI_VERIFIED,
            "retry_verified": Method.AI_VERIFIED_AFTER_RETRY,
            "unverified_fallback": Method.AI_SINGLE_MODEL}
_SCHEMA = "meridian-deterministic-inputs/v1"
_NUMBERS = frozenset({"length", "width", "diameter", "inner_diameter", "outer_diameter",
    "x", "y", "depth", "thread_depth", "countersink_diameter", "countersink_angle_deg",
    "counterbore_diameter", "counterbore_depth", "spacing", "direction_deg", "radius",
    "start_angle_deg", "count"})


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse(value: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON keys are not admissible preparation evidence.")
            result[key] = item
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON is not admissible preparation evidence.")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)


def _owned(path: Path) -> Path:
    path = Path(path).resolve()
    if not any(path.is_relative_to(_WORKSPACE / name) for name in ("development", "testing")):
        raise EvidenceError("Preparation writes must stay in this worktree's development/ or testing/.")
    return path


def _atomic(path: Path, value: Any, *, before_replace: Callable[[], None] | None = None) -> None:
    path = _owned(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        if before_replace:
            before_replace()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _pending(review) -> bool:
    return review is None or review.status == ReviewStatus.NOT_REVIEWED


class PreparedKnowledge(ContractModel):
    """M11 -> M12 handoff. No alternate layout or live-reader dependency."""

    pipeline_version: Literal["determine-verify/v1"] = "determine-verify/v1"
    source_only: bool = False  # Deterministic startup before the separate AI run.
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    drawings: list[DrawingEvidence]
    bom_rows: list[BOMRow]
    links: list[matching.LinkResolution]
    mappings: list[NameMapping]
    templates: dict[str, FlatTemplate]
    review_items: list[ReviewItem]
    batch: PrepBatchResult

    @model_validator(mode="after")
    def coherent_boundary(self) -> PreparedKnowledge:
        if self.source_only:
            if self.batch.records or self.mappings or self.templates or self.review_items:
                raise ValueError("Source-only knowledge cannot claim AI jobs or prepared interpretations.")
            if any(field.provenance is not None or field.method not in {
                    Method.PARSED, Method.CLEANUP_RULE, Method.UNRESOLVED}
                    for drawing in self.drawings for field in drawing.fields.values()):
                raise ValueError("Source-only knowledge must retain deterministic drawing evidence.")
        drawings = {drawing.id: drawing for drawing in self.drawings}
        if len(drawings) != len(self.drawings):
            raise ValueError("Prepared drawing IDs must be unique.")
        if (len(self.links) != len(drawings) or {link.drawing_id for link in self.links} != drawings.keys()
                or len({link.drawing_id for link in self.links}) != len(self.links)):
            raise ValueError("Preparation retains one final link resolution per drawing.")
        if len({link.registry_sha256 for link in self.links}) > 1:
            raise ValueError("Links from superseded registries cannot share a publication.")
        records = {(record.job, record.job_id): record for record in self.batch.records}
        if len(records) != len(self.batch.records):
            raise ValueError("Preparation cannot count duplicate jobs.")
        referenced = set()

        def retained(record):
            if record is None:
                return
            key = (record.job, record.job_id)
            if records.get(key) != record:
                raise ValueError("Every projected AI value retains its exact batch provenance.")
            referenced.add(key)

        for drawing in self.drawings:
            for field in drawing.fields.values():
                if field.correction is not None or not _pending(field.review):
                    raise ValueError("Preparation never applies human decisions to source evidence.")
                retained(field.provenance)
                if field.provenance:
                    if field.provenance.job != f"vision.scan.{drawing.id}":
                        raise ValueError("Scan overlays retain their own drawing's job.")
                    expected = field.provenance.field_results.get(field.name)
                    if (field.original is not None or expected is None
                            or field.value != (expected.accepted.value if expected.accepted else None)
                            or field.method != _METHODS.get(expected.status, Method.UNRESOLVED)):
                        raise ValueError("Scan overlays preserve originals and exact final accepted values.")
        for row in self.bom_rows:
            for field in row.fields.values():
                if field.provenance is not None or field.correction is not None or not _pending(field.review):
                    raise ValueError("Prepared BOM evidence remains deterministic and unreviewed.")
        rows = {row.name for row in self.bom_rows}
        for result in self.links:
            link = result.link
            if (link.drawing_id != result.drawing_id or not set(link.bom_rows) <= rows
                    or len(link.bom_rows) != len(set(link.bom_rows)) or not _pending(link.review)):
                raise ValueError("Link ownership, rows or approval state is invalid.")
            if bool(link.bom_rows) != (result.state == "matched"):
                raise ValueError("Only a matched link contains selected rows.")
            retained(link.provenance)
            if link.provenance:
                field_name = f"{result.drawing_id}/link"
                accepted = link.provenance.field_results.get(field_name)
                if (link.provenance.job != "relationships/link/" + contract_digest(field_name)[:20]
                        or accepted is None):
                    raise ValueError("Link provenance belongs to another job.")
                expected = "matched" if accepted.accepted and link.bom_rows else (
                    "no_match" if accepted.accepted else "unresolved")
                if result.state != expected or link.method != _METHODS.get(accepted.status, Method.UNRESOLVED):
                    raise ValueError("Link state must reflect its final accepted candidate.")
            elif (self.source_only and result.state != "matched"
                  and link.method == Method.UNRESOLVED and not link.bom_rows):
                pass  # No AI has been attempted; keep this link unresolved.
            elif link.method != Method.EXACT_MATCH or result.state != "matched":
                raise ValueError("Every non-exact link must retain an actual attempted job.")
        for mapping in self.mappings:
            if not _pending(mapping.review) or mapping.provenance is None:
                raise ValueError("Preparation only saves unapproved AI mapping proposals.")
            retained(mapping.provenance)
        if len({mapping.name for mapping in self.mappings}) != len(self.mappings):
            raise ValueError("Mapping names must be unique.")
        for identity, template in self.templates.items():
            if (identity not in drawings or template.part != identity or not _pending(template.review)
                    or template.filled_by == "human" or template.provenance is None):
                raise ValueError("Templates belong to current drawings and never invent human approval.")
            retained(template.provenance)
            if template.provenance.job != f"vision.template.{identity}":
                raise ValueError("Template provenance belongs to another drawing.")
            # Reproject solely from retained final candidate/proofs/coverage. No files,
            # optional image libraries, runner or CLI are needed on reload.
            if _template(drawings[identity], template.provenance) != template:
                raise ValueError("Saved template differs from its final candidate and proof ledger.")
        if len({item.id for item in self.review_items}) != len(self.review_items):
            raise ValueError("Review IDs must be unique.")
        for item in self.review_items:
            if item.status != "pending" or not _pending(item.review):
                raise ValueError("Preparation does not manufacture human review actions.")
            retained(item.ai_answers)
            if item.mapping and item.mapping not in self.mappings:
                raise ValueError("Review mapping differs from the saved proposal.")
        if referenced != records.keys():
            raise ValueError("All actual jobs/rounds must remain available in projections or Debug review.")
        return self


def load_prepared(path: Path) -> PreparedKnowledge:
    """Validate the saved handoff without loading inputs, images, settings or CLIs."""
    return PreparedKnowledge.model_validate(_parse(Path(path).read_bytes()))


def _review_link(name: str) -> ReviewLink:
    identity = "review/" + name
    return ReviewLink(id=identity, href=review_api_path(identity))


def _unknown(name: str, *, message: str, essential: bool = False,
             record: PrepProvenance | None = None) -> dict[str, Any]:
    return dict(name=name, method=Method.UNRESOLVED, state="unknown", confidence="unsure",
                reason="invalid_ai_answer" if record and any(
                    a.status == "invalid_output" for r in record.rounds
                    for a in (r.determination, r.verification) if a) else "model_unsure",
                message=message, essential=essential, provenance=record,
                review_item=_review_link(name))


def _template_value(value: Any, name: str, option: int | None,
                    proofs: dict[tuple[str, int | None, str], Any], *,
                    record: PrepProvenance | None, essential: bool,
                    path: str = "", key: str = "") -> Any:
    """Convert one semantic value using only its own indexed scalar proofs.

    Known values and each printed option take the same path. Option order and
    proof identity stay intact; a composite need not invent a root proof.
    Domain validation and accepted-state checks happen before this conversion.
    """
    child_name = name + (f"/option-{option + 1}" if option is not None else "") + path
    if value == {"state": "unknown"}:
        return _unknown(child_name, message="The original candidate explicitly leaves this subfield unknown.",
                        essential=essential, record=record)
    if isinstance(value, dict):
        return {k: _template_value(v, name, option, proofs, record=record, essential=essential,
                                  path=path + "/" + k, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [_template_value(v, name, option, proofs, record=record, essential=essential,
                                path=path + f"/{i}", key=key) for i, v in enumerate(value)]
    if value is not None and (key in _NUMBERS or key in {"thread_size", "angles_deg"}):
        evidence = ValueEvidence.model_validate(proofs[(name, option, path)])
        return dict(name=child_name, method=Method.CLEANUP_RULE, state="known", confidence="sure",
            value=value, evidence=evidence.model_dump(mode="json"), provenance=record,
            essential=essential, unit="count" if key == "count" else "deg" if key.endswith("_deg") else
                None if key == "thread_size" else "mm")
    return value


def _template_evidence(name: str, option: int | None,
                       proofs: dict[tuple[str, int | None, str], Any]) -> dict[str, Any]:
    """Keep scalar proofs exact; aggregate only this composite option's leaves."""
    if (name, option, "") in proofs:
        return ValueEvidence.model_validate(proofs[(name, option, "")]).model_dump(mode="json")
    entries = [ValueEvidence.model_validate(p) for (n, index, _), p in proofs.items()
               if n == name and index == option]
    if not entries:
        raise EvidenceError("A known composite or option has no supporting leaf proofs.")
    return ValueEvidence(
        number_ids=sorted({ref for p in entries for ref in
                           [*p.number_ids, *(p.derivation.inputs if p.derivation else [])]}),
        source_ids=sorted({ref for p in entries for ref in
                           [*p.source_ids, *([p.derivation.pattern_fact] if p.derivation
                                              and p.derivation.pattern_fact else [])]})).model_dump(mode="json")


def _template(drawing: DrawingEvidence, record: PrepProvenance) -> FlatTemplate | None:
    """Attach the validated ledger to exact semantic values, without guessing.

    Nested wrappers use cleanup_rule for this deterministic representation
    conversion; their enclosing AI field binds the entire semantic geometry.
    Using an AI method on a nested scalar would falsely claim a separate M08
    field/verdict. The complete original provenance is retained on every wrapper.
    """
    accepted = {name: result.accepted for name, result in record.field_results.items()}
    ledger = accepted.get(template_fact_name(drawing.id, "proofs"))
    native = [name for name, field in accepted.items() if field is not None
              and (name.rsplit("/", 1)[-1] in {"outline", "thickness"}
                   or name.rsplit("/", 1)[-1].startswith("feature-"))
              and field.value != {"kind": "absent"}]
    if ledger is None or not native:
        return None
    proofs = {(entry["field"], entry["option"], entry["path"]): entry["evidence"]
              for entry in ledger.value["entries"]}

    def project(suffix, *, essential=False, unit=None):
        name = template_fact_name(drawing.id, suffix)
        field = accepted[name]
        if field is None or field.value == {"kind": "absent"}:
            return _unknown(name, message="No usable verified or authorized unverified candidate for this field.",
                            essential=essential, record=record)
        base = dict(name=name, method=_METHODS[record.field_results[name].status],
                    confidence="sure", provenance=record, essential=essential, review_item=_review_link(name))
        if field.state == "options":
            return dict(base, state="options", basis="printed_alternatives", unit=unit,
                options=[dict(value=_template_value(value, name, i, proofs, record=record, essential=essential),
                              evidence=_template_evidence(name, i, proofs))
                         for i, value in enumerate(field.options)])
        value = _template_value(field.value, name, None, proofs, record=record, essential=essential)
        return dict(base, state="known", value=value, evidence=_template_evidence(name, None, proofs), unit=unit)

    features = []
    slots = [name for name in record.field_names if name.rsplit("/", 1)[-1].startswith("feature-")]
    coverage_name = template_fact_name(drawing.id, "coverage")
    coverage = accepted.get(coverage_name)
    candidate = record.rounds[-1].determination.output
    coverage_errors = vision_jobs.template_coverage_errors(candidate.fields if candidate else {},
        coverage_name=coverage_name, slot_names=slots, source=record.source,
        page_refs={f"{drawing.id}/drawing/page/{page.page}" for page in drawing.page_geometry})
    for name in slots:
        field = accepted[name]
        if (field and field.value == {"kind": "absent"}
                and record.field_results[name].status in {"first_pass_verified", "retry_verified"}):
            continue
        # Every actual hole/slot, including nested placement, blind depths,
        # counterbores/countersinks and pattern counts, is essential. Unknown
        # physical details cannot degrade silently to an outer extrusion.
        absent_unverified = bool(field and field.value == {"kind": "absent"})
        projected = project(name.rsplit("/", 1)[-1], essential=not absent_unverified)
        if absent_unverified:
            projected["message"] = "Unused slot is only Sol-inspected absent; Opus verification is unavailable."
            projected["evidence"] = dict(source_ids=field.source_ids)
        features.append(projected)
    if coverage is None or coverage_errors:
        # Keep accepted geometry and original rounds, but block completeness
        # even when every scalar proof and the outer extrusion are available.
        features.append(_unknown(coverage_name, essential=True, record=record,
            message="Feature coverage is unresolved. " + " ".join(coverage_errors or [
                "No accepted original-image coverage audit or authorized unverified inventory."])))
    else:
        for item in coverage.value["features"]:
            disposition = item["disposition"]
            if disposition == "supported":
                continue
            # Unsupported/recess/side-hole details need a top-level essential
            # FeatureField blocker even if other slots are completely known.
            # Explicitly sourced minor cosmetic omissions remain inspectable.
            omitted = _unknown(coverage_name + "/" + item["id"], record=record,
                essential=disposition != "cosmetic_omission",
                message=f"{item['description']}: {item['reason']} "
                        f"Face: {item['face_interpretation']}; depth: {item['depth_interpretation']}; "
                        f"multiplicity: {item['multiplicity_interpretation']}.")
            omitted["evidence"] = dict(source_ids=item["source_ids"])
            features.append(omitted)
    return FlatTemplate(part=drawing.id, source_sha256=record.source.inputs["drawing"],
        filled_by=record.mode, provenance=record, outline=project("outline", essential=True),
        thickness=project("thickness", essential=True, unit="mm"), features=features,
        material=project("material"), weight_on_drawing=project("weight-on-drawing", unit="g"))


def _vision_reviews(job: vision_jobs.VisionJob, drawing: DrawingEvidence,
                    record: PrepProvenance, *, at: datetime) -> list[ReviewItem]:
    details = (vision_jobs.template_review_details(job, record)
               if job.definition.job.startswith("vision.template.") else None)
    items = []
    for name, result in record.field_results.items():
        if details is None and result.status == "unresolved":
            # Failed scan readings remain null/unsure with retained rounds;
            # unreadability alone does not create a human review task (R5).
            continue
        field = result.accepted
        last = record.rounds[-1].determination.output
        candidate = last.fields[name] if last else None
        source_field = next((f for f in drawing.fields.values() if f.name == name), None)
        sources = [FactSource(name=f"{drawing.id}/source", says=drawing.source_path,
            method=Method.PARSED, source_sha256=drawing.source_sha256,
            target=SourceTarget(kind="drawing", name=f"{drawing.id}/source",
                                part_id=drawing_part_name(drawing.id), drawing_id=drawing.id))]
        if source_field:
            sources.append(FactSource(name=name, says=source_field.original, method=source_field.method,
                confidence=source_field.confidence, source_quality=source_field.source_quality,
                source_sha256=drawing.source_sha256, target=SourceTarget(kind="drawing", name=name,
                    part_id=drawing_part_name(drawing.id), drawing_id=drawing.id,
                    page=source_field.page, box=source_field.box)))
        # ai_answers retains every round. Keep proposed_value semantic so a
        # downstream review action cannot mistake Debug details for geometry.
        message = "Prepared evidence awaits optional human review; no human decision was applied."
        if details is not None:
            rounds = details[name]["rounds"]
            message += f" Debug retains {len(rounds)} actual round(s)."
            if rounds[-1]["missing_opus_output"]:
                message += " Final Opus output is unavailable."
        if record.mode == "single_model_unverified":
            message = "UNVERIFIED: initial Opus execution failed; retry Opus on every launch. " + message
        actions = [ReviewAction.ACCEPT, ReviewAction.REJECT, ReviewAction.SET_VALUE]
        if field and field.state == "options":
            actions.append(ReviewAction.CHOOSE_OPTION)
        items.append(ReviewItem(id=_review_link(name).id,
            kind="template_field" if details is not None else "scan_reading", applies_to=name,
            part_id=drawing_part_name(drawing.id), status="pending", title="Prepared evidence review",
            message=message, current_value=field.value if field else None,
            proposed_value=candidate.value if candidate else None,
            options=field.options if field else [], sources=sources, source_hashes=record.source.inputs,
            ai_answers=record, allowed_actions=actions,
            created_at=at, updated_at=at))
    return items


def preparation_summary(prepared: PreparedKnowledge) -> dict[str, Any]:
    """Field counts and orthogonal review counts for engineering Debug only."""
    return {**prepared.batch.counts.model_dump(mode="json"),
            "review_items": len(prepared.review_items),
            "unapproved_mappings": len(prepared.mappings), "drawings": len(prepared.drawings),
            "bom_rows": len(prepared.bom_rows), "templates": len(prepared.templates),
            "exact_links": sum(link.link.method == Method.EXACT_MATCH for link in prepared.links),
            "single_model_unverified": prepared.batch.counts.unverified_fallback}


class PreparationError(EvidenceError):
    """A domain/source failure with preserved raw Debug diagnostics, no publication."""

    def __init__(self, diagnostic: Path):
        self.diagnostic = diagnostic
        super().__init__(f"Preparation source/domain validation failed; no saved publication. Debug: {diagnostic}")


def prepare(inputs: Path, *, manifest: Path, output: Path, runner: Runner,
            image_root: Path | None = None, crop_dir: Path | None = None,
            feature_slots: int = 12) -> PreparedKnowledge:
    """Complete one fresh ordered pass, then atomically publish PreparedKnowledge.

    No prior saved outputs are inputs. M08 can reuse only its current bound
    stages, and finishes its entire correction/reverification before returning.
    Thus registries use final scans, and mapping jobs use final links. Every new
    launch reconstructs those dependencies, invalidating changed descendants.
    """
    output = _owned(output)
    runtime = _owned(runner.runtime)
    if runner.workspace.resolve() != _WORKSPACE:
        raise EvidenceError("Preparation and M08 must use this same assigned workspace.")
    inputs, manifest = Path(inputs).resolve(), Path(manifest).resolve()
    image_root = Path(image_root or inputs.parent).resolve()
    crop_dir = _owned(crop_dir or runtime / "corner-crops")
    if output in {inputs, manifest} or output.is_relative_to(crop_dir):
        raise EvidenceError("Publication cannot overwrite original inputs, manifest or corner crops.")
    records: list[PrepProvenance] = []
    raw: PrepProvenance | None = None
    current = None
    stage = "deterministic-inputs"
    jobs: list[tuple[Any, PrepProvenance]] = []
    try:
        original_inputs, original_manifest = inputs.read_bytes(), manifest.read_bytes()
        payload, manifest_value = _parse(original_inputs), _parse(original_manifest)
        if (not isinstance(payload, dict) or payload.get("schema") != _SCHEMA
                or payload.get("manifest_sha256") != _sha(original_manifest)
                or not isinstance(manifest_value, dict)):
            raise EvidenceError("Deterministic inputs schema or original manifest byte hash is invalid.")
        originals = [DrawingEvidence.model_validate(d) for d in payload["drawings"]]
        bom = [BOMRow.model_validate(row) for row in payload["bom"]]
        for drawing in originals:
            if any(f.method not in {Method.PARSED, Method.UNRESOLVED} or f.provenance is not None
                   or f.correction is not None or not _pending(f.review) for f in drawing.fields.values()):
                raise EvidenceError("Preparation requires original deterministic drawings, never old AI overlays.")
        for row in bom:
            if any(f.method not in {Method.PARSED, Method.CLEANUP_RULE, Method.UNRESOLVED}
                   or f.provenance is not None or f.correction is not None or not _pending(f.review)
                   for f in row.fields.values()):
                raise EvidenceError("Preparation requires original deterministic BOM evidence.")
        # Validate the complete manifest/identity inventory before any model work.
        matching.MatchingRegistry(originals, bom, manifest_value)
        pages = {}
        for drawing in originals:
            for page in drawing.page_geometry:
                path = image_root / vision_jobs.page_image_path(drawing.id, page.page)
                if not path.resolve().is_relative_to(image_root):
                    raise EvidenceError("An original page path escapes its image root.")
                pages[path] = _sha(path.read_bytes())
        if output in {path.resolve() for path in pages}:
            raise EvidenceError("Publication cannot overwrite an original page image.")

        def unchanged():
            if inputs.read_bytes() != original_inputs or manifest.read_bytes() != original_manifest:
                raise EvidenceError("Original deterministic inputs or manifest changed during preparation.")
            if any(_sha(path.read_bytes()) != digest for path, digest in pages.items()):
                raise EvidenceError("An original PNG changed during preparation; descendants are stale.")

        def run(job):
            nonlocal current, raw
            current, raw = job, None
            unchanged()
            runner.jobs[job.definition.job] = job.definition
            raw = runner(job.request)
            record = PrepProvenance.model_validate(raw.model_dump(mode="json"))
            if isinstance(job, vision_jobs.VisionJob):
                record = vision_jobs.validate_vision_result(job, record)
            jobs.append((job, record))
            return record

        drawings, scan_images, templates, reviews = [], {}, {}, []
        stage = "scans"
        for original in originals:
            if not original.degraded:
                drawings.append(original)
                continue
            job = vision_jobs.build_scan_job(original, image_root=image_root, crop_dir=crop_dir)
            record = run(job)
            fields = vision_jobs.scan_readings(job, original, record)
            drawings.append(DrawingEvidence.model_validate({**original.model_dump(mode="json"),
                "fields": {k: f.model_dump(mode="json") for k, f in fields.items()}}))
            # Attach precisely the actual corner crops whose hashes own each
            # overlay's source IDs. Full-page images have unrelated hashes.
            bundle = job.definition.evidence(job.request)
            scan_images[original.id] = [item.path for item in bundle.inputs.values() if item.image]
            records.append(record)
            reviews.extend(_vision_reviews(job, original, record, at=datetime.now(timezone.utc)))
        stage = "templates"
        for original in originals:
            if original.id not in vision_jobs.SUPPORTED_TEMPLATES:
                continue
            job = vision_jobs.build_template_job(original, image_root=image_root, feature_slots=feature_slots)
            record = run(job)
            template = _template(original, record)
            if template is not None:
                templates[original.id] = template
            records.append(record)
            reviews.extend(_vision_reviews(job, original, record, at=datetime.now(timezone.utc)))
        stage = "links"
        registry = matching.MatchingRegistry(drawings, bom, manifest_value, images=scan_images)
        links = []
        for link in registry.exact_links():
            if link.state == "matched":
                links.append(link)
                continue
            job = registry.link_job(link.drawing_id)
            record = run(job)
            links.append(registry.resolve_link(link.drawing_id, record))
            records.append(record)
            reviews.append(registry.review_item(job, record, at=datetime.now(timezone.utc)))
        stage = "mappings"
        mappings = []
        for job in registry.mapping_jobs(links):
            record = run(job)
            proposal = registry.resolve_mapping(job, record)
            if proposal is not None:
                mappings.append(proposal)
            records.append(record)
            reviews.append(registry.review_item(job, record, at=datetime.now(timezone.utc)))
        stage = "publication-validation"

        def validate_publication():
            unchanged()
            for job, record in jobs:
                if isinstance(job, vision_jobs.VisionJob):
                    vision_jobs.validate_vision_result(job, record)
                elif job.kind == "link":
                    if registry.resolve_link(job.from_name, record) not in links:
                        raise EvidenceError("Link descendants changed before publication.")
                else:
                    proposal = registry.resolve_mapping(job, record)
                    if proposal is not None and proposal not in mappings:
                        raise EvidenceError("Mapping descendants changed before publication.")
            registry.mapping_jobs(links)  # Recheck completed final links, never execute another job.

        validate_publication()
        prepared = PreparedKnowledge(input_sha256=_sha(original_inputs), drawings=drawings, bom_rows=bom,
            links=links, mappings=mappings, templates=templates, review_items=reviews,
            batch=PrepBatchResult(records=records, counts=prep_counts(records)))
        # Validate the complete serialized value too, before the single commit point.
        prepared = PreparedKnowledge.model_validate_json(prepared.model_dump_json())
        _atomic(output, prepared.model_dump(mode="json"), before_replace=validate_publication)
        return prepared
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        # A required domain check can reject otherwise generic accepted flags.
        # Never alter actual rounds to fabricate a valid unresolved provenance.
        # Keep raw output separate, count its fields as quarantined/unresolved,
        # and leave any prior atomic publication untouched.
        retained = records + ([raw] if raw is not None and raw not in records else [])
        actual_counts = prep_counts(retained)
        # Nothing in an aborted transaction is eligible for publication credit.
        # Raw generic flags/rounds stay inspectable, never a verified numerator.
        quarantined = actual_counts.total_fields
        diagnostic = runtime / "publication-rejected" / (uuid.uuid4().hex + ".json")
        _atomic(diagnostic, {"pipeline_version": "determine-verify/v1", "stage": stage,
            "published": False, "at": datetime.now(timezone.utc).isoformat(),
            "failure_type": type(exc).__name__, "failure_sha256": _sha(str(exc).encode("utf-8")),
            "request": current.request.model_dump(mode="json") if current else None,
            "prior_domain_validated_records": [record.model_dump(mode="json") for record in records],
            "publication_counts": PrepCounts(total_fields=quarantined, first_pass_verified=0,
                retry_verified=0, unresolved=quarantined, unverified_fallback=0,
                execution_failed_attempts=actual_counts.execution_failed_attempts).model_dump(mode="json"),
            "quarantined_unresolved_fields": quarantined,
            "raw_domain_invalid_result": raw.model_dump(mode="json") if raw is not None else None})
        raise PreparationError(diagnostic) from exc


def main(argv: list[str] | None = None, *, reserve_cli_slot:
         Callable[[], AbstractContextManager[CliReservation]] | None = None) -> int:
    """Explicit command; ROOT supplies the actual native/shared reservation.

    A host can inject reserve_cli_slot directly, or expose that same callable
    as --reservation module:attribute. There is deliberately no invented CLI
    process count or replacement scheduler. Existing account homes must already
    be provisioned privately inside this worktree before actual execution.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--image-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--crop-dir", type=Path)
    parser.add_argument("--feature-slots", type=int, default=12, choices=range(1, 33))
    parser.add_argument("--reservation", help="Actual shared CLI reservation context manager: module:attribute")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--claude-home", type=Path)
    args = parser.parse_args(argv)
    if reserve_cli_slot is None:
        if not args.reservation or ":" not in args.reservation:
            parser.error("Supply the actual shared CLI reservation via --reservation or the host callback.")
        module, attribute = args.reservation.split(":", 1)
        reserve_cli_slot = getattr(importlib.import_module(module), attribute)
        if not callable(reserve_cli_slot):
            parser.error("The shared reservation must be a callable context manager factory.")
    from ..settings import load_settings

    settings = load_settings()
    runner = Runner(jobs={}, prep_settings=settings.data["prep"], workspace_root=_WORKSPACE,
        runtime_root=args.runtime_root, reserve_cli_slot=reserve_cli_slot,
        cli_homes={key: path for key, path in (("codex", args.codex_home), ("claude", args.claude_home)) if path})
    try:
        result = prepare(args.inputs, manifest=args.manifest, output=args.output, runner=runner,
            image_root=args.image_root, crop_dir=args.crop_dir, feature_slots=args.feature_slots)
    except PreparationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(_json({"output": str(args.output), "input_sha256": result.input_sha256,
                 "counts": preparation_summary(result)}).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
