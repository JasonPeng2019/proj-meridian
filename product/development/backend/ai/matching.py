"""M1 relationship jobs. No I/O, model calls, decisions or publication on import.

M11 constructs MatchingRegistry from M05/M06 outputs, the original manifest and
any completed M09 scan readings already overlaid on DrawingEvidence. First use
exact_links(), then link_job() for every remaining drawing. Register each job's
definition with M08 and call its request through the frozen PrepRunner. Pass the
returned provenance to resolve_link(). Only after that complete link inventory
may mapping_jobs() run. M11 alone publishes these results.

Source validation is deliberately conservative: a semantic link needs recorded
filename or lexical evidence on both sides, beyond a section/material resemblance.
Translations with no recorded anchor are unsupported, even if a model is sure.
Mapping validation establishes recorded names/associations, not a material
taxonomy. Material semantics are explicitly outside-dataset proposals. Every
mapping remains unapproved; this module never changes facts or search indexes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from typing import Literal

from pydantic import JsonValue

from ..contracts import (
    BOMRow, Confidence, ContractModel, DeterminationOutput, DeterminedField,
    DrawingEvidence, EvidenceField, FactSource, LinkInfo, MappingRelationship,
    Method, NameMapping, PrepJobRequest, PrepProvenance, PrepSourceIdentity,
    ReviewAction, ReviewItem, ReviewLink, ReviewState, SourceTarget,
    contract_digest, drawing_part_name, mapping_name, review_api_path,
)
from .runner import EvidenceBundle, EvidenceError, EvidenceInput, JobDefinition, with_field_validation


MATCHING_VERSION = "relationships/determine-verify/v1"
REGISTRY_REF = "relationships/registry"
LINKS_REF = "relationships/completed-links"
OUTSIDE_KNOWLEDGE = (
    "The names and linked occurrences are recorded in the dataset. The proposed "
    "material relationship is based on general engineering knowledge, not the dataset."
)
_METHODS = {"first_pass_verified": Method.AI_VERIFIED,
            "retry_verified": Method.AI_VERIFIED_AFTER_RETRY,
            "unverified_fallback": Method.AI_SINGLE_MODEL}


def _compact(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def _tokens(text: str) -> set[str]:
    # Split CamelCase without translating names or importing section mappings.
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", unicodedata.normalize("NFKC", text))
    return {word.casefold() for word in re.findall(r"[^\W_]+", text) if len(word) >= 3}


def _basename(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).name


def _filenames(value: JsonValue) -> set[str]:
    """Recorded attachment labels only; temporary URLs are never fetched or guessed."""
    if not isinstance(value, str):
        return set()
    labels = re.sub(r"\s*\(https?://[^)]*\)", "", value, flags=re.I)
    return {_basename(label.strip()).casefold() for label in labels.split(",")
            if label.strip().lower().endswith(".pdf")}


def _text(field: EvidenceField | None) -> str | None:
    if (field is None or field.confidence != Confidence.SURE or not isinstance(field.value, str)
            or not field.value.strip() or field.method == Method.UNRESOLVED):
        return None
    if field.method in {Method.AI_READ, Method.AI_AGREED, Method.AI_AGREED_AFTER_RETRY}:
        return None
    return field.value


def _review_link(name: str) -> ReviewLink:
    identity = "review/" + name
    return ReviewLink(id=identity, href=review_api_path(identity))


class LinkResolution(ContractModel):
    """Explicit state plus the frozen LinkInfo; candidates are never selected rows."""

    drawing_id: str
    state: Literal["matched", "ambiguous", "no_match", "unresolved"]
    link: LinkInfo
    candidate_rows: list[str]
    source_ids: list[str]
    registry_sha256: str


@dataclass(frozen=True)
class RelationshipJob:
    definition: JobDefinition
    request: PrepJobRequest
    field_name: str
    kind: Literal["link", "section", "material"]
    from_name: str
    to_name: str | None = None


class MatchingRegistry:
    def __init__(self, drawings: Sequence[DrawingEvidence], bom_rows: Sequence[BOMRow],
                 manifest: Mapping[str, JsonValue], *,
                 images: Mapping[str, Sequence[Path]] | None = None):
        # Own a serialized snapshot, so later producer/caller mutations cannot
        # silently change evidence beneath a request or accepted link inventory.
        self._images = {identity: tuple(EvidenceInput(path=Path(path).resolve(), image=True) for path in paths)
                        for identity, paths in (images or {}).items()}
        if not self._images.keys() <= {drawing.id for drawing in drawings}:
            raise EvidenceError("Image evidence names a drawing outside the registry.")
        payload = {"version": MATCHING_VERSION,
                   "drawings": [d.model_dump(mode="json") for d in sorted(drawings, key=lambda d: d.id)],
                   "bom": [r.model_dump(mode="json") for r in sorted(bom_rows, key=lambda r: (r.name, r.display_id))],
                   "manifest": dict(manifest),
                   "image_hashes": {identity: [image.sha256 for image in inputs]
                                    for identity, inputs in self._images.items()}}
        self._snapshot = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False)
        owned = json.loads(self._snapshot)
        self._image_hashes = owned["image_hashes"]
        self.digest = contract_digest(owned)
        self._drawings = {d["id"]: DrawingEvidence.model_validate(d) for d in owned["drawings"]}
        if len(self._drawings) != len(drawings):
            raise EvidenceError("Drawing IDs collide; no relationship registry can select one.")
        self._rows = [BOMRow.model_validate(row) for row in owned["bom"]]
        for drawing in self._drawings.values():
            supplied = set(owned["image_hashes"].get(drawing.id, []))
            for key, field in drawing.fields.items():
                if key not in {"title", "notes", "material"}:
                    continue
                if (field.method in _METHODS.values() and _text(field) is not None
                        and (not field.provenance or not supplied.intersection(field.provenance.source.inputs.values()))):
                    raise EvidenceError("AI-read drawing fields require their original source-bound image evidence.")
        counts = Counter(row.name for row in self._rows)
        self._custom = [row for row in self._rows if _text(row.fields.get("type")) == "Custom"]
        self._eligible = {row.name: row for row in self._rows if counts[row.name] == 1
                          and not row.identity_conflict and _text(row.fields.get("type")) == "Custom"
                          and _text(row.fields.get("name")) == row.display_name}
        self._metadata: dict[str, dict] = {}
        assets = owned["manifest"].get("assets", [])
        for drawing in self._drawings.values():
            entries = [a for a in assets if isinstance(a, dict) and a.get("id") == drawing.id]
            if (len(entries) != 1 or entries[0].get("path") != drawing.source_path
                    or entries[0].get("sha256") != drawing.source_sha256
                    or not isinstance(entries[0].get("source_path"), str)
                    or not entries[0]["source_path"].strip()
                    or not isinstance(entries[0].get("subsystem"), str)
                    or not entries[0]["subsystem"].strip()):
                raise EvidenceError("Drawing evidence lacks matching original manifest provenance.")
            self._metadata[drawing.id] = entries[0]
        self._files: dict[str, list[BOMRow]] = defaultdict(list)
        for row in self._rows:
            for filename in _filenames(_text(row.fields.get("datasheet"))):
                self._files[filename].append(row)
        self._drawing_files = Counter(_basename(meta["source_path"]).casefold()
                                      for meta in self._metadata.values())

    def _drawing(self, identity: str) -> DrawingEvidence:
        if identity not in self._drawings:
            raise EvidenceError("The requested drawing does not exist in the registry.")
        return self._drawings[identity]

    def _names(self, identity: str) -> list[str]:
        drawing = self._drawing(identity)
        values = [PurePosixPath(_basename(self._metadata[identity]["source_path"])).stem]
        title = _text(drawing.fields.get("title"))
        return values + ([title] if title else [])

    def _anchors(self, identity: str, row: BOMRow) -> list[tuple[str, str]]:
        """Actually present, paired references supporting an admissible candidate.

        Section/material alone never establishes a link. A duplicate attachment
        is a candidate anchor, never an exact selection or proof of correctness;
        Opus must check Sol's interpretation of it against these original rows.
        """
        drawing = self._drawing(identity)
        meta = self._metadata[identity]
        pairs = []
        datasheet = _text(row.fields.get("datasheet"))
        if _basename(meta["source_path"]).casefold() in _filenames(datasheet):
            pairs.append((f"{identity}/source", row.fields["datasheet"].name))
        row_name = _text(row.fields.get("name"))
        if row_name:
            choices = [(f"{identity}/source", self._names(identity)[0])]
            choices += [(f.name, text) for key in ("title", "notes")
                        if (f := drawing.fields.get(key)) and (text := _text(f))]
            for ref, value in choices:
                if (_compact(value) == _compact(row_name)
                        or _tokens(value) & _tokens(row_name)):
                    pairs.append((ref, row.fields["name"].name))
        return pairs

    def _possible(self, identity: str) -> list[str]:
        return sorted(name for name, row in self._eligible.items() if self._anchors(identity, row))

    def exact_links(self) -> list[LinkResolution]:
        self._check_images()
        results = []
        for identity in sorted(self._drawings):
            filename = _basename(self._metadata[identity]["source_path"]).casefold()
            attached = self._files.get(filename, [])
            # Filename ambiguity has priority: never bypass it using a title.
            ambiguous_file = len(attached) > 1 or self._drawing_files[filename] > 1
            rows = [r.name for r in attached if r.name in self._eligible]
            basis = "Unique recorded datasheet filename."
            if not attached and not ambiguous_file:
                names = {_compact(value) for value in self._names(identity)}
                named = [row for row in self._custom if _compact(row.display_name) in names]
                rows = [row.name for row in named if row.name in self._eligible]
                ambiguous_file = len(named) > 1
                # Also guard collisions between drawing titles/original names.
                if len(rows) == 1:
                    token = _compact(self._eligible[rows[0]].display_name)
                    ambiguous_file = ambiguous_file or sum(token in {_compact(v) for v in self._names(d)}
                                                           for d in self._drawings) > 1
                basis = "Unique normalized original filename/title and custom BOM name."
            matched = len(rows) == 1 and not ambiguous_file
            candidates = sorted(set(rows) | set(self._possible(identity)))
            state = "matched" if matched else "ambiguous" if ambiguous_file or len(rows) > 1 else "unresolved"
            selected = rows if matched else []
            refs = sorted({ref for row in selected for pair in self._anchors(identity, self._eligible[row]) for ref in pair})
            results.append(LinkResolution(drawing_id=identity, state=state,
                link=LinkInfo(method=Method.EXACT_MATCH if matched else Method.UNRESOLVED,
                              drawing_id=identity, bom_rows=selected,
                              basis=basis if matched else "No unique exact link; determination/verification required.",
                              review_item=None if matched else _review_link(f"{identity}/link")),
                candidate_rows=candidates, source_ids=refs, registry_sha256=self.digest))
        return results

    def _check_images(self) -> None:
        for identity, inputs in self._images.items():
            if [item.sha256 for item in inputs] != self._image_hashes[identity]:
                raise EvidenceError("Original relationship images changed; construct a new registry.")

    def _job(self, *, kind: Literal["link", "section", "material"], field_name: str,
             from_name: str, to_name: str | None, value_schema: dict,
             context: dict, validate) -> RelationshipJob:
        self._check_images()
        image_drawings = ({from_name} if kind == "link" else
                          {occurrence["drawing_id"] for occurrence in context["occurrences"]})
        row_names = (set(self._eligible) if kind == "link" else
                     {occurrence["row"] for occurrence in context["occurrences"]})
        # Original typed fields, not a replacement interpretation or a whole
        # corpus dump. Each projected record retains its original source hash.
        drawing_inputs = []
        row_inputs = []
        references = {REGISTRY_REF: "registry", f"{field_name}/context": "context"}
        for identity in sorted(image_drawings):
            drawing = self._drawing(identity)
            value = drawing.model_dump(mode="json", exclude={"words", "numbers"})
            value["fields"] = {key: field for key, field in value["fields"].items()
                               if key in {"title", "notes", "material"}}
            drawing_inputs.append(value)
            references[f"{identity}/source"] = "registry"
            references.update({field["name"]: "registry" for field in value["fields"].values()})
        for name in sorted(row_names):
            row = self._eligible[name]
            value = row.model_dump(mode="json", exclude={"connections"})
            value["fields"] = {key: field for key, field in value["fields"].items()
                               if key in {"name", "type", "section", "material", "datasheet", "notes", "design_intent"}}
            row_inputs.append(value)
            references.update({name: "registry", **{field["name"]: "registry" for field in value["fields"].values()}})
        context = {**context, "registry_sha256": self.digest}
        inputs = {"registry": EvidenceInput(value={"version": MATCHING_VERSION,
                      "registry_sha256": self.digest, "drawings": drawing_inputs, "bom": row_inputs,
                      "excluded_custom_rows": [row.model_dump(mode="json") for row in self._custom
                                               if row.name not in self._eligible] if kind == "link" else [],
                      "manifest_assets": [self._metadata[d] for d in sorted(image_drawings)]}),
                  "context": EvidenceInput(value=context)}
        for identity in sorted(image_drawings):
            for index, image in enumerate(self._images.get(identity, ()), 1):
                key = f"image/{identity}/{index}"
                inputs[key] = image
                references[key] = key
        if "links" in context:
            references[LINKS_REF] = "context"
        source = PrepSourceIdentity(inputs={key: value.sha256 for key, value in inputs.items()},
                                    source_ids=references)
        bundle = EvidenceBundle(inputs=inputs)
        job_name = f"relationships/{kind}/{contract_digest(field_name)[:20]}"

        def evidence(request: PrepJobRequest) -> EvidenceBundle:
            if request.source != source:
                raise EvidenceError("Relationship evidence identity changed; construct a new job.")
            # Return fresh typed JSON so a caller cannot mutate the closure.
            return EvidenceBundle(inputs={key: (item if item.image else EvidenceInput(value=json.loads(item.read())))
                                          for key, item in bundle.inputs.items()})

        def validator(candidate: DeterminationOutput, supplied: PrepSourceIdentity) -> DeterminationOutput:
            bound = supplied == source and candidate.source_sha256 == contract_digest(source)
            try:
                bundle.check(source)
            except EvidenceError:
                bound = False
            validity = {}
            for name, field in candidate.fields.items():
                shape, supported = validate(field)
                validity[name] = (name == field_name and shape,
                                  name == field_name and bound and supported
                                  and bool(field.reason.strip()) and bool(field.source_ids)
                                  and set(field.source_ids) <= source.source_ids.keys())
            return with_field_validation(candidate, validity)

        determine = (
            "Determine this relationship using only the supplied original registry and context. "
            "Use existing stable IDs, not display IDs. Sections are compared as written; no unapproved "
            "mapping is evidence. A drawing may link to several rows only with support for EACH row. "
            "Repeated filenames identify candidates, never a preferred row. Cite the actual paired "
            "drawing/row fields, or both recorded mapping names and completed-links. "
            "Use unknown/unsure for unsupported cases; never options for disagreement. "
            "For links use match or no_match and the exact drawing_id/bom_rows shape. "
            "For mappings use relationship and the exact relationship/to_name shape; "
            "kind_of is directed from specific from_name to broader to_name. "
            "Material semantics use general engineering knowledge OUTSIDE the dataset. "
            "All mapping results are proposals awaiting human approval."
        )
        verify = (
            "Verify EACH field of the supplied exact Sol candidate against the ORIGINAL evidence. "
            "Return verified/disagrees/unsure, a concrete reason and paired source IDs. Check actual "
            "row existence, custom eligibility, name/attachment support, duplicate ambiguity and "
            "every proposed row separately. Equal strings or another guess are not verification. "
            "For mappings inspect completed links/counts and recorded names; distinguish a proposed "
            "section correspondence from proof. Material taxonomy is outside-dataset engineering "
            "knowledge and must be judged as such, never as a printed dataset assertion. "
            "No mapping is human approved. Alternatives are feedback only."
        )
        definition = JobDefinition(job=job_name, determination_instructions=determine,
            verification_instructions=verify, value_schemas={field_name: value_schema},
            evidence=evidence, validate_candidate=validator, validation_version=MATCHING_VERSION)
        return RelationshipJob(definition, definition.request(field_name, source),
                               field_name, kind, from_name, to_name)

    def link_job(self, identity: str) -> RelationshipJob:
        self._drawing(identity)
        field_name = f"{identity}/link"
        schema = {"type": "object", "properties": {
            "drawing_id": {"type": "string", "enum": [identity]},
            "bom_rows": {"type": "array", "items": ({"type": "string", "enum": sorted(self._eligible)}
                                                      if self._eligible else {"type": "string"})}},
            "required": ["drawing_id", "bom_rows"], "additionalProperties": False}

        def validate(field: DeterminedField) -> tuple[bool, bool]:
            if field.state == "unknown":
                return True, False
            value = field.value
            shape = (field.state in {"match", "no_match"} and isinstance(value, dict)
                     and set(value) == {"drawing_id", "bom_rows"} and value["drawing_id"] == identity
                     and isinstance(value["bom_rows"], list)
                     and all(isinstance(row, str) for row in value["bom_rows"]))
            if not shape:
                return False, False
            names = value["bom_rows"]
            shape = len(names) == len(set(names)) and bool(names) == (field.state == "match")
            if not shape or any(name not in self._eligible for name in names):
                return shape, False
            refs = set(field.source_ids)
            if field.state == "no_match":
                # Absence of anchors on an unreadable drawing is not evidence
                # of absence. A sure recorded title/full registry are required.
                supported = (not self._possible(identity)
                    and len(self._eligible) == len(self._custom)
                    and (not self._eligible or _text(self._drawing(identity).fields.get("title")) is not None)
                    and {REGISTRY_REF, f"{identity}/source"} <= refs)
            else:
                supported = all(any(set(pair) <= refs for pair in self._anchors(identity, self._eligible[name]))
                                for name in names)
            return shape, supported

        context = {"stage": "links", "drawing_id": identity,
                   "candidate_rows": sorted(self._eligible), "anchored_rows": self._possible(identity),
                   "exact_result": next(r.model_dump(mode="json") for r in self.exact_links() if r.drawing_id == identity)}
        return self._job(kind="link", field_name=field_name, from_name=identity, to_name=None,
                         value_schema=schema, context=context, validate=validate)

    def _accepted(self, job: RelationshipJob, provenance: PrepProvenance):
        # Reparse retained rounds and recheck current source validation; never
        # trust caller-injected accepted values or historical blind-reader data.
        record = PrepProvenance.model_validate(provenance.model_dump(mode="json"))
        request = job.request
        bundle = job.definition.evidence(request)
        if (bundle.inputs["context"].value["registry_sha256"] != self.digest
                or record.job != request.job or record.job_id != request.job_id or record.source != request.source
                or record.field_names != request.field_names
                or record.determination_prompt_sha256 != request.determination_prompt_sha256
                or record.verification_prompt_sha256 != request.verification_prompt_sha256
                or record.output_contract_sha256 != request.output_contract_sha256):
            raise EvidenceError("Retained relationship result is stale or belongs to another candidate/job.")
        bundle.check(record.source)
        for round_ in record.rounds:
            output = round_.determination.output
            if output and job.definition.validate_candidate(output, record.source) != output:
                raise EvidenceError("Retained relationship candidate fails current source validation.")
        result = record.field_results[job.field_name]
        return record, result.accepted, _METHODS.get(result.status, Method.UNRESOLVED)

    def resolve_link(self, identity: str, provenance: PrepProvenance) -> LinkResolution:
        job = self.link_job(identity)
        record, field, method = self._accepted(job, provenance)
        rows = list(field.value["bom_rows"]) if field else []
        state = ("matched" if rows else "no_match") if field else "unresolved"
        return LinkResolution(drawing_id=identity, state=state,
            link=LinkInfo(method=method, drawing_id=identity, bom_rows=rows,
                          basis=field.reason if field else "No supported verified or authorized unverified candidate.",
                          review_item=_review_link(job.field_name), provenance=record,
                          prep_field_name=job.field_name),
            candidate_rows=self._possible(identity), source_ids=field.source_ids if field else [],
            registry_sha256=self.digest)

    def mapping_jobs(self, links: Sequence[LinkResolution]) -> list[RelationshipJob]:
        if (len(links) != len(self._drawings) or {r.drawing_id for r in links} != self._drawings.keys()
                or len({r.drawing_id for r in links}) != len(links)):
            raise EvidenceError("Mapping jobs require the complete link stage, including unresolved drawings.")
        exact = {link.drawing_id: link for link in self.exact_links()}
        for link in links:
            if link.link.provenance is None and exact[link.drawing_id].state != "matched":
                raise EvidenceError("Finish each non-exact link job before mapping; failed/unresolved attempts are allowed.")
            expected = (self.resolve_link(link.drawing_id, link.link.provenance)
                        if link.link.provenance else exact[link.drawing_id])
            if link != expected:
                raise EvidenceError("Mapping input contains stale, fabricated or unvalidated links.")
        retained = [link.model_dump(mode="json") for link in sorted(links, key=lambda link: link.drawing_id)]
        pairs: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for link in links:
            if link.state != "matched":
                continue
            drawing = self._drawing(link.drawing_id)
            for row_name in link.link.bom_rows:
                row = self._eligible[row_name]
                if _text(row.fields.get("section")) == row.section:
                    pairs[("section", self._metadata[drawing.id]["subsystem"], row.section)].append(
                        {"drawing_id": drawing.id, "row": row_name,
                         "source_ids": [f"{drawing.id}/source", row.fields["section"].name]})
                material = _text(drawing.fields.get("material"))
                row_material = row.fields.get("material")
                if (material and row_material and row_material.confidence == Confidence.SURE
                        and isinstance(row_material.value, list)):
                    for name in sorted({n for n in row_material.value if isinstance(n, str) and n.strip()}):
                        pairs[("material", material, name)].append({"drawing_id": drawing.id,
                            "row": row_name, "source_ids": [drawing.fields["material"].name, row_material.name]})
        jobs, names = [], set()
        for (kind, source_name, target_name), occurrences in sorted(pairs.items()):
            field_name = mapping_name(kind, source_name, target_name)
            if field_name in names:
                raise EvidenceError("Mapping stable names collide; retain the original names for review.")
            names.add(field_name)
            context = {"stage": "post-link-mappings", "kind": kind, "from_name": source_name,
                       "to_name": target_name, "links": retained, "occurrences": occurrences,
                       "count": len(occurrences), "approved": False,
                       "evidence_basis": "general_engineering_knowledge" if kind == "material" else "dataset",
                       "evidence_note": OUTSIDE_KNOWLEDGE if kind == "material" else
                           "Recorded section pairs/counts from completed links; correspondence is a proposal."}
            schema = {"type": "object", "properties": {
                "relationship": {"type": "string", "enum": [r.value for r in MappingRelationship]},
                "to_name": {"type": ["string", "null"], "enum": [target_name, None]}},
                "required": ["relationship", "to_name"], "additionalProperties": False}

            def validate(field: DeterminedField, target=target_name, recorded=occurrences,
                         source_label=source_name) -> tuple[bool, bool]:
                if field.state == "unknown":
                    return True, False
                value = field.value
                shape = (field.state == "relationship" and isinstance(value, dict)
                         and set(value) == {"relationship", "to_name"}
                         and isinstance(value["relationship"], str)
                         and value["relationship"] in {r.value for r in MappingRelationship}
                         and value["to_name"] == (None if value["relationship"] == "no_equivalent" else target))
                if not shape:
                    return False, False
                refs = set(field.source_ids)
                # A non-equivalence claim about identical recorded names is
                # unsupported. Other semantics remain explicit AI proposals.
                consistent = (value["relationship"] == "same" or _compact(source_label) != _compact(target))
                return True, (consistent and LINKS_REF in refs
                              and any(set(o["source_ids"]) <= refs for o in recorded))

            jobs.append(self._job(kind=kind, field_name=field_name, from_name=source_name,
                                  to_name=target_name, value_schema=schema, context=context, validate=validate))
        return jobs

    def resolve_mapping(self, job: RelationshipJob, provenance: PrepProvenance) -> NameMapping | None:
        if job.kind not in {"section", "material"}:
            raise EvidenceError("Expected a post-link mapping job.")
        record, field, method = self._accepted(job, provenance)
        if field is None:
            return None
        context = job.definition.evidence(job.request).inputs["context"].value
        return NameMapping(name=job.field_name, kind=job.kind, from_name=job.from_name,
            to_name=field.value["to_name"], relationship=field.value["relationship"],
            evidence=context["evidence_basis"], evidence_note=context["evidence_note"], method=method,
            review=ReviewState(), review_item=_review_link(job.field_name), provenance=record)

    def review_item(self, job: RelationshipJob, provenance: PrepProvenance, *, at: datetime) -> ReviewItem:
        """Debug-only pending handoff with real sources and all retained rounds.

        The publisher supplies an actual timestamp; no human action is invented.
        Unresolved candidates remain review suggestions, never effective values.
        """
        record, field, _ = self._accepted(job, provenance)
        last = record.rounds[-1].determination.output
        candidate = last.fields[job.field_name] if last else None
        mapping = self.resolve_mapping(job, record) if job.kind != "link" else None
        context = job.definition.evidence(job.request).inputs["context"].value
        refs = set()
        for round_ in record.rounds:
            if round_.determination.output:
                refs.update(round_.determination.output.fields[job.field_name].source_ids)
            if round_.verification and round_.verification.output:
                verdict = round_.verification.output.fields[job.field_name]
                refs.update(verdict.source_ids)
                if verdict.alternative:
                    refs.update(verdict.alternative.source_ids)
        if job.kind == "link":
            refs.update(field.name for field in self._drawing(job.from_name).fields.values())
            for name in self._possible(job.from_name):
                refs.update(f.name for key, f in self._eligible[name].fields.items()
                            if key in {"name", "datasheet", "section", "material"})
        else:
            refs.update(ref for occurrence in context["occurrences"] for ref in occurrence["source_ids"])
        drawing_ids = ({job.from_name} if job.kind == "link" else
                       {o["drawing_id"] for o in context["occurrences"]})
        sources = []
        for drawing in self._drawings.values():
            if drawing.id not in drawing_ids:
                continue
            sources.append(FactSource(name=f"{drawing.id}/source", says=self._metadata[drawing.id],
                method=Method.PARSED, source_sha256=drawing.source_sha256,
                target=SourceTarget(kind="drawing", name=f"{drawing.id}/source",
                                    part_id=drawing_part_name(drawing.id), drawing_id=drawing.id)))
            for evidence in drawing.fields.values():
                if evidence.name in refs:
                    sources.append(FactSource(name=evidence.name, says=evidence.original,
                        method=evidence.method, confidence=evidence.confidence, provenance=evidence.provenance,
                        source_sha256=drawing.source_sha256, source_quality=evidence.source_quality,
                        target=SourceTarget(kind="drawing", name=evidence.name,
                            part_id=drawing_part_name(drawing.id), drawing_id=drawing.id,
                            page=evidence.page, box=evidence.box)))
        for row in self._eligible.values():
            for evidence in row.fields.values():
                if evidence.name in refs:
                    sources.append(FactSource(name=evidence.name, says=evidence.original,
                        method=evidence.method, confidence=evidence.confidence, source_sha256=row.source_sha256,
                        target=SourceTarget(kind="bom", name=evidence.name, row_name=row.name)))
        fallback = record.mode == "single_model_unverified"
        message = ("UNVERIFIED: Sol only; Opus execution failed. Retry Opus on the next launch. " if fallback else "")
        message += ("Mapping proposal awaits human approval; it has no effect on facts/search." if job.kind != "link"
                    else "Review the recorded candidates and per-field verdicts; unresolved rows remain unlinked.")
        if job.kind == "material":
            message += " " + OUTSIDE_KNOWLEDGE
        return ReviewItem(id=_review_link(job.field_name).id, kind="link" if job.kind == "link" else "name_mapping",
            applies_to=job.field_name, part_id=drawing_part_name(job.from_name) if job.kind == "link" else None,
            status="pending", title="Relationship review", message=message,
            current_value=field.value if field and job.kind == "link" else None,
            proposed_value=candidate.value if candidate else None, sources=sources,
            source_hashes=record.source.inputs, ai_answers=record, mapping=mapping,
            allowed_actions=([ReviewAction.ACCEPT, ReviewAction.REJECT, ReviewAction.SET_VALUE] if job.kind == "link"
                             else [ReviewAction.APPROVE_MAPPING, ReviewAction.REJECT] if mapping
                             else [ReviewAction.SET_VALUE, ReviewAction.REJECT]),
            created_at=at, updated_at=at)
