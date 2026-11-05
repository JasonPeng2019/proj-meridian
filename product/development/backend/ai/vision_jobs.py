"""M1 image jobs for the frozen ordered runner; importing launches nothing.

``build_scan_job`` and ``build_template_job`` return a JobDefinition and its
code-bound PrepJobRequest. Register the definition with M08, then submit the
request, then call ``validate_vision_result`` before publishing or consuming
accepted fields. M11 owns scheduling, CLI reservations, caching and publication.

Scan attachments contain only measured whole-field corner crops. Templates
receive original PNGs and the unmodified deterministic drawing inventory.
Their fixed feature slots contain semantic geometry (the same representation
as contracts.template_candidate_value), or ``{"kind": "absent"}`` for an
explicitly inspected empty slot. Unknown is never a substitute for absence.

One additional fixed ``proofs`` field records ValueEvidence per geometry leaf,
using JSON-pointer paths and an optional zero-based option index. It supplies
machine-checkable numeric provenance without changing the frozen candidate
contract or putting evidence wrappers inside semantic geometry. A verifier
must check each geometry field INCLUDING these proofs against the image.
Expressions use n0, n1, ... in Derivation.inputs order, not executable code.
Only numeric input references, +, -, *, /, unary signs and the mathematical
constant 2 (radius/diameter/half-spacing) are supported; recorded patterns may
also use 0/90/180/360 for the CAD frame and circle angles. Unsupported proofs
stay invalid. Geometric meaning, transcription, feature presence and printed
alternative association require actual candidate-bound Opus verification;
host validation alone never establishes AI review.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..contracts import (
    Confidence, DeterminationOutput, DeterminedField, DrawingEvidence,
    DrawingField, DrawingNumber, Method, PrepJobRequest, PrepProvenance,
    PrepSourceIdentity, ValueEvidence, contract_digest, template_fact_name,
)
from ..loader.drawings import page_image_path
from .runner import EvidenceBundle, EvidenceError, EvidenceInput, JobDefinition, with_field_validation


VISION_VERSION = "vision-determine-verify/v1"
SUPPORTED_TEMPLATES = frozenset({"D-013", "D-025", "D-026"})
CORNER_FIELDS = ("title", "notes", "company", "material", "weight", "date", "drawn", "scale")
_WORKSPACE = Path(__file__).resolve().parents[3]
_PLACEHOLDERS = frozenset({"description", "title", "title/description", "material", "notes",
                          "note", "company", "n/a", "na", "none", "tbd", "?", "-",
                          "unknown", "undetermined"})


@dataclass(frozen=True)
class VisionJob:
    definition: JobDefinition
    request: PrepJobRequest


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _original(drawing: DrawingEvidence) -> DrawingEvidence:
    try:
        drawing = DrawingEvidence.model_validate_json(drawing.model_dump_json())
    except ValidationError as exc:
        raise EvidenceError("Vision jobs require valid original deterministic drawing evidence.") from exc
    if any(f.method not in {Method.PARSED, Method.UNRESOLVED} or f.provenance is not None
           or f.correction is not None or (f.review is not None and f.review.status != "not_reviewed")
           for f in drawing.fields.values()):
        raise EvidenceError("Vision jobs require original deterministic fields, never prior AI/review overlays.")
    return drawing


def _page_paths(drawing: DrawingEvidence, image_root: Path) -> dict[int, Path]:
    root = Path(image_root).resolve()
    return {p.page: root / page_image_path(drawing.id, p.page) for p in drawing.page_geometry}


def _images(drawing: DrawingEvidence, paths: dict[int, Path]) -> dict[int, bytes]:
    # Lazy optional prep dependency: ordinary startup/import requires no Pillow.
    from PIL import Image

    result = {}
    for page in drawing.page_geometry:
        data = paths[page.page].read_bytes()
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or image.size != (page.image_width, page.image_height):
                raise EvidenceError("Original PNG dimensions disagree with deterministic page geometry.")
        result[page.page] = data
    return result


def _inside(box: Any, outer: Any, tolerance: float = 0.0) -> bool:
    x, y, w, h = box
    ox, oy, ow, oh = outer
    return (all(math.isfinite(v) for v in (*box, *outer)) and w > 0 and h > 0
            and x >= ox - tolerance and y >= oy - tolerance
            and x + w <= ox + ow + tolerance and y + h <= oy + oh + tolerance)


def _overlap(a: Any, b: Any) -> bool:
    return (max(a[0], b[0]) < min(a[0] + a[2], b[0] + b[2])
            and max(a[1], b[1]) < min(a[1] + a[3], b[1] + b[3]))


def _crop(data: bytes, field: DrawingField, geometry: Any) -> tuple[bytes, list[int]]:
    from PIL import Image

    if not _inside(field.box, (0, 0, geometry.source_width, geometry.source_height), .05):
        raise EvidenceError("A corner field has no positive, in-page whole-field box.")
    x, y, w, h = field.box
    sx, sy = geometry.image_width / geometry.source_width, geometry.image_height / geometry.source_height
    pixels = [max(0, math.floor(x * sx)), max(0, math.floor(y * sy)),
              min(geometry.image_width, math.ceil((x + w) * sx)),
              min(geometry.image_height, math.ceil((y + h) * sy))]
    with Image.open(BytesIO(data)) as image:
        output = BytesIO()
        image.crop(tuple(pixels)).save(output, format="PNG")
    return output.getvalue(), pixels


def _source(bundle: EvidenceBundle, refs: dict[str, str]) -> PrepSourceIdentity:
    return PrepSourceIdentity(inputs={k: v.sha256 for k, v in bundle.inputs.items()}, source_ids=refs)


def _bind(job: str, job_id: str | None, instructions: tuple[str, str], schemas: dict[str, Any],
          inputs: dict[str, EvidenceInput], refs: dict[str, str], check_original: Any,
          validate: Any) -> VisionJob:
    # Capture JSON by value. Neither a caller nor a returned bundle can mutate
    # the inventory underlying future validation without changing its digest.
    files = {k: v for k, v in inputs.items() if v.path is not None}
    values = {k: _json(v.value) for k, v in inputs.items() if v.path is None}

    def bundle() -> EvidenceBundle:
        return EvidenceBundle({**files, **{k: EvidenceInput(value=json.loads(v)) for k, v in values.items()}})

    identity = _source(bundle(), refs)
    identity_json = identity.model_dump_json()

    def check(source: PrepSourceIdentity) -> None:
        if source != PrepSourceIdentity.model_validate_json(identity_json):
            raise EvidenceError("Job source inventory or reference ownership changed; build a fresh job.")
        check_original()
        bundle().check(source)

    def evidence(request: PrepJobRequest) -> EvidenceBundle:
        check(request.source)
        if request.job != job or request.field_names != list(schemas):
            raise EvidenceError("Evidence requested for another vision job or field inventory.")
        return bundle()

    def validator(candidate: DeterminationOutput, source: PrepSourceIdentity) -> DeterminationOutput:
        check(source)
        if candidate.source_sha256 != contract_digest(source) or set(candidate.fields) != set(schemas):
            raise EvidenceError("Vision candidate does not bind this exact source and fixed field inventory.")
        return with_field_validation(candidate, validate(candidate, source))

    definition = JobDefinition(job=job, determination_instructions=instructions[0],
        verification_instructions=instructions[1], value_schemas=schemas, evidence=evidence,
        validate_candidate=validator, validation_version=VISION_VERSION)
    return VisionJob(definition, definition.request(job_id or job, identity))


_SCAN_DETERMINE = """Determine the exact printed text of each fixed scan corner field.
Only the supplied whole-field corner crops are admissible: never use another
field, drawing, clean counterpart, title elsewhere, filenames, OCR caches,
proposal examples or engineering knowledge. The inventory binds each crop to
its original page and whole-field box in source points and pixels. Preserve
spelling, punctuation, capitalization and line breaks; do not translate,
correct, concatenate neighboring labels or infer missing text. Exclude the
field label itself. Cite exactly that field's own whole-field source ID.
Return state=known, confidence=sure and a string only if fully legible. Blank,
placeholder, overlapping or unreadable text is state=unknown, value=null,
confidence=unsure with a concrete reason; never manufacture options. For a
correction round, revisit the original crop using the actual verifier critique.
"""

_SCAN_VERIFY = """Verify every field of the supplied exact Sol candidate against its
original corner crop, using Read for every attached crop. You are verifying a
candidate, not independently guessing and comparing strings. Check spelling,
capitalization, punctuation, all lines, label boundaries, legibility and the
candidate's own whole-field citation. No other field or outside source can
support a reading. Return verified only for an entirely supported sure field;
return disagrees for a demonstrable error, or unsure for unreadable/unknown or
insufficient evidence. Every field requires an explicit verdict, nonempty
reason and its own whole-field evidence ID. Suggested alternatives are feedback
only: Sol must revise and you must reverify before any alternative is usable.
Persistent disagreement or uncertainty remains unresolved. Do not claim review
because two strings are equal. Do not compute candidate/source hashes.
"""


def build_scan_job(drawing: DrawingEvidence, *, image_root: Path, crop_dir: Path,
                   job_id: str | None = None) -> VisionJob:
    """Prepare bounded PNG crops only; no PDF/OCR/model calls or publication.

    image_root is the existing extraction's generated root (containing images/).
    crop_dir must be inside this worktree's development/ or testing/ directory.
    Multipage keys such as title-p2 remain distinct whole-field citations.
    """
    drawing = _original(drawing)
    if not drawing.degraded or not drawing.fields:
        raise EvidenceError("Scan jobs require degraded drawing evidence and measured corner fields.")
    expected = {f"{key}-p{p}" if p > 1 else key for p in range(1, drawing.pages + 1) for key in CORNER_FIELDS}
    if set(drawing.fields) != expected:
        raise EvidenceError("Scan corner field inventory is incomplete or contains a non-corner field.")
    target = Path(crop_dir).resolve()
    if not any(target.is_relative_to(_WORKSPACE / name) for name in ("development", "testing")):
        raise EvidenceError("Scan crop writes must stay in this worktree's development/ or testing/.")
    paths = _page_paths(drawing, image_root)
    originals = _images(drawing, paths)
    original_hashes = {page: _sha(data) for page, data in originals.items()}
    geometry = {p.page: p for p in drawing.page_geometry}
    inputs, refs, regions = {}, {}, {}
    for key, field in drawing.fields.items():
        if field.name != f"{drawing.id}/drawing/{key}" or field.original is not None or field.value is not None:
            raise EvidenceError("Scans require untouched unresolved fields in their original namespaces.")
        crop, pixels = _crop(originals[field.page], field, geometry[field.page])
        # Content addressed crops cannot collide across source revisions.
        path = (target / drawing.id / f"{key}-{_sha(crop)}.png").resolve()
        if not path.is_relative_to(target):
            raise EvidenceError("A corner crop path escapes its assigned output directory.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != crop:
                raise EvidenceError("An existing content-addressed corner crop was modified.")
        else:
            path.write_bytes(crop)
        input_key = f"crop:{key}"
        inputs[input_key] = EvidenceInput(path=path, image=True)
        refs[field.name] = input_key
        regions[field.name] = {"input_key": input_key, "page": field.page, "box": list(field.box),
                               "pixel_bounds": pixels, "whole_field": True}
    inputs["inventory"] = EvidenceInput(value={"version": VISION_VERSION, "kind": "scan-corners",
        "drawing_id": drawing.id, "pdf_sha256": drawing.source_sha256,
        "page_geometry": [p.model_dump(mode="json") for p in drawing.page_geometry],
        "original_page_sha256": {str(k): v for k, v in original_hashes.items()}, "fields": regions})

    def check_original() -> None:
        if any(_sha(paths[p].read_bytes()) != digest for p, digest in original_hashes.items()):
            raise EvidenceError("Original scan page changed; its corner crops are stale.")

    def validate(candidate: DeterminationOutput, source: PrepSourceIdentity) -> dict[str, tuple[bool, bool]]:
        validity = {}
        for name, field in candidate.fields.items():
            known = (field.state == "known" and isinstance(field.value, str) and bool(field.value.strip())
                     and field.value.strip().casefold() not in _PLACEHOLDERS
                     and field.confidence == Confidence.SURE)
            unknown = field.state == "unknown" and field.value is None and field.confidence == Confidence.UNSURE
            shape = (known or unknown) and not field.options and field.basis is None
            validity[name] = (shape, shape and field.source_ids == [name] and source.source_ids.get(name) == refs[name])
        return validity

    return _bind(f"vision.scan.{drawing.id}", job_id, (_SCAN_DETERMINE, _SCAN_VERIFY),
                 {name: {"type": "string", "minLength": 1} for name in regions},
                 inputs, refs, check_original, validate)


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_UNKNOWN = _object({"state": _enum("unknown")})
_NUMBER = {"anyOf": [{"type": "number"}, _UNKNOWN]}
_INTEGER = {"anyOf": [{"type": "integer", "minimum": 1}, _UNKNOWN]}
_TEXT = {"anyOf": [{"type": "string", "minLength": 1}, _UNKNOWN]}
_POSITION = _object({"x": _NUMBER, "y": _NUMBER})
_FACE = _enum("top", "bottom", "front", "back", "left", "right", "outer", "inner")
_PATTERN = {"anyOf": [
    _object({"type": _enum("row"), "count": _INTEGER, "spacing": _NUMBER, "direction_deg": _NUMBER}),
    _object({"type": _enum("circle"), "count": _INTEGER, "radius": _NUMBER, "start_angle_deg": _NUMBER,
             "evenly_spaced": {"type": "boolean"}, "angles_deg": _nullable({"type": "array", "items": _NUMBER})}),
]}
_OUTLINE = {"anyOf": [
    _object({"type": _enum("rectangle"), "length": _NUMBER, "width": _NUMBER}),
    _object({"type": _enum("circle"), "diameter": _NUMBER}),
    _object({"type": _enum("ring"), "outer_diameter": _NUMBER, "inner_diameter": _NUMBER}),
]}
_FEATURE = {"anyOf": [
    _object({"kind": _enum("absent")}),
    _object({"kind": _enum("hole"), "hole_type": _enum("plain", "threaded", "countersunk", "counterbored"),
        "face": _FACE, "position": _POSITION, "diameter": _NUMBER, "through": {"type": "boolean"},
        "depth": _nullable(_NUMBER), "thread_size": _nullable(_TEXT), "thread_depth": _nullable(_NUMBER),
        "countersink_diameter": _nullable(_NUMBER), "countersink_angle_deg": _nullable(_NUMBER),
        "counterbore_diameter": _nullable(_NUMBER), "counterbore_depth": _nullable(_NUMBER),
        "pattern": _nullable(_PATTERN)}),
    _object({"kind": _enum("slot"), "face": _FACE, "position": _POSITION, "width": _NUMBER,
        "length": _NUMBER, "direction_deg": _NUMBER, "through": {"type": "boolean"},
        "depth": _nullable(_NUMBER), "pattern": _nullable(_PATTERN)}),
]}


class _Proof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: str
    option: int | None
    path: str
    evidence: ValueEvidence


class _Proofs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entries: list[_Proof] = Field(max_length=2048)


def _proof_schema(names: list[str]) -> dict[str, Any]:
    # Inline the tiny frozen ValueEvidence shape for both CLI schema dialects.
    strings = {"type": "array", "items": {"type": "string"}}
    derivation = _object({"kind": _enum("arithmetic", "pattern"), "expression": {"type": "string", "minLength": 1},
        "inputs": {**strings, "minItems": 1}, "pattern_fact": _nullable({"type": "string"})})
    evidence = _object({"number_ids": strings, "source_ids": strings, "derivation": _nullable(derivation)})
    entry = _object({"field": _enum(*names), "option": _nullable({"type": "integer", "minimum": 0}),
                     "path": {"type": "string"}, "evidence": evidence})
    return _object({"entries": {"type": "array", "items": entry, "maxItems": 2048}})


def _shape(value: Any, schema: dict[str, Any]) -> bool:
    """Validate the deliberately small schema vocabulary authored above."""
    if "anyOf" in schema:
        return any(_shape(value, option) for option in schema["anyOf"])
    kind = schema["type"]
    if kind == "null":
        return value is None
    if kind == "number":
        return type(value) in {int, float} and math.isfinite(value)
    if kind == "integer":
        return type(value) is int and value >= schema.get("minimum", -math.inf)
    if kind == "boolean":
        return type(value) is bool
    if kind == "string":
        return (isinstance(value, str) and len(value) >= schema.get("minLength", 0)
                and ("enum" not in schema or value in schema["enum"]))
    if kind == "array":
        return (isinstance(value, list) and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf)
                and all(_shape(v, schema["items"]) for v in value))
    if kind == "object":
        return (isinstance(value, dict) and set(value) == set(schema["properties"])
                and all(_shape(value[k], sub) for k, sub in schema["properties"].items()))
    return False


def _leaves(value: Any, path: str = "") -> dict[str, Any]:
    if value is None or value == {"state": "unknown"}:
        return {}
    if isinstance(value, dict):
        return {p: v for key, item in value.items() for p, v in _leaves(item, path + "/" + key).items()}
    if isinstance(value, list):
        return {p: v for i, item in enumerate(value) for p, v in _leaves(item, path + f"/{i}").items()}
    return {path: value}


def _expression(expression: str, values: list[float], *, pattern: bool = False) -> float:
    """A bounded arithmetic interpreter, with no eval/calls/attribute access."""
    if len(expression) > 512:
        raise ValueError("Derivation is too long")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 64:
        raise ValueError("Derivation is too complex")
    used = set()

    def visit(node: ast.AST, depth: int = 0) -> float:
        if depth > 12:
            raise ValueError("Derivation is too deep")
        if isinstance(node, ast.Name) and re.fullmatch(r"n(?:0|[1-9]\d*)", node.id):
            i = int(node.id[1:])
            used.add(i)
            return values[i]
        if (isinstance(node, ast.Constant) and type(node.value) is int
                and node.value in ({0, 2, 90, 180, 360} if pattern else {2})):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth + 1)
            return -value if isinstance(node.op, ast.USub) else value
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
        raise ValueError("Unsupported derivation operation")

    result = visit(tree.body)
    if used != set(range(len(values))) or not math.isfinite(result):
        raise ValueError("Derivation must use every recorded input and yield a finite number")
    return result


def _admissible_number(number: DrawingNumber, drawing: DrawingEvidence) -> bool:
    p = next(p for p in drawing.page_geometry if p.page == number.page)
    # Discard sheet border/grid labels, title-block identifiers/material grades,
    # dates, scales and weights as geometry dimensions. Conservative exclusions
    # remain unresolved rather than substituting another equal-valued token.
    interior = (.025 * p.source_width, .04 * p.source_height, .95 * p.source_width, .92 * p.source_height)
    if (number.confidence != Confidence.SURE or not math.isfinite(number.value)
            or not _inside(number.box, interior) or any(
                f.page == number.page and _overlap(number.box, f.box) for f in drawing.fields.values())):
        return False
    try:
        value = float(number.text.replace(",", ".").replace("\N{MINUS SIGN}", "-"))
    except ValueError:
        return False
    return value == number.value and any(
        word.page == number.page and number.text in word.text and _inside(number.box, word.box, .2)
        for word in drawing.words)


def _printed_groups(drawing: DrawingEvidence, numbers: dict[str, DrawingNumber]) -> list[list[str]]:
    # Only an explicit printed connector admits options. Two nearby dimensions,
    # repeated values or two model readings never constitute alternatives.
    groups = []
    for marker in drawing.words:
        if not re.fullmatch(r"(?:or|eller|either|alternativ(?:e|t)?|alt\.)", marker.text, re.I):
            continue
        line = [w for w in drawing.words if w.page == marker.page
                and abs((w.box[1] + w.box[3] / 2) - (marker.box[1] + marker.box[3] / 2)) < max(2, marker.box[3] / 2)]
        # Bound the local callout; don't merge every dimension on the same row.
        line = [w for w in line if abs(w.box[0] - marker.box[0]) <= 8 * marker.box[3]]
        ids = [n.name for n in numbers.values() if n.page == marker.page
               and any(_inside(n.box, w.box, .2) for w in line)]
        if len(ids) >= 2 and ids not in groups:
            groups.append(ids)
    return groups


def _semantic(value: Any) -> bool:
    if not isinstance(value, dict):
        return True
    kind = value.get("kind")
    if kind in {"hole", "slot"}:
        if value["through"] is False and value["depth"] is None:
            return False
        if kind == "hole":
            required = {"plain": (), "threaded": ("thread_size",),
                "countersunk": ("countersink_diameter", "countersink_angle_deg"),
                "counterbored": ("counterbore_diameter", "counterbore_depth")}[value["hole_type"]]
            if any(value[k] is None for k in required):
                return False
    if value.get("type") == "ring":
        inner, outer = value["inner_diameter"], value["outer_diameter"]
        if type(inner) in {int, float} and type(outer) in {int, float} and inner >= outer:
            return False
    for path, leaf in _leaves(value).items():
        if type(leaf) in {int, float}:
            key = path.rsplit("/", 1)[-1]
            if key in {"length", "width", "diameter", "inner_diameter", "outer_diameter", "thickness",
                       "spacing", "radius", "depth", "thread_depth", "countersink_diameter",
                       "counterbore_diameter", "counterbore_depth"} and leaf <= 0:
                return False
    return True


_TEMPLATE_DETERMINE = """Determine the fixed flat-part template fields from this drawing's
original images and deterministic inventory only. No proposal/example answers,
clean counterparts, historical prep, approximate pixel scaling or engineering
guesses. Supported outlines are rectangle/circle/ring; supported features are
plain/threaded/countersunk/counterbored holes and slots with optional row/circle
patterns. The CAD frame is mm, x right/y up, rectangle lower-left origin or
round-part centre; image y goes down. Weight is grams. Never infer a drill size
from a thread standard, material from a name, or thickness from appearance.
The inventory identifies every supplied number, box, admissibility decision,
page and corner field. Border/grid/title-block numbers are not dimensions.
Use known only for supported sure semantic geometry; retain unknown subfields
as {"state":"unknown"}, or the whole field as state=unknown/null/unsure.
For every scalar leaf of a known value or option, put exactly one entry in the
fixed proofs field: field=its stable field name, option=null for known or the
zero-based option index, path=JSON pointer (empty for a scalar), evidence using
the supplied ValueEvidence schema. Cite every proof's IDs also in that field's
source_ids. Direct numbers require one admissible number ID equal to the value.
Arithmetic requires explicit inputs, expression using n0/n1/... in inputs order,
and only +,-,*,/,unary signs and constant 2. Explain the geometric relationship
in the field reason. Pattern derivations additionally cite their original
pattern_fact source ID and may use 0/90/180/360 for CAD-frame/circle conventions,
with at least one actual recorded numeric input. Never use arbitrary constants
or unprinted counts.
Non-numeric geometry/absence proofs cite original page images. Material must
be verbatim sure corner text; printed weight must use the weight field's own
number. Thread text must occur verbatim in drawing words. Numeric options each
need their OWN directly printed number plus the supplied printed-alternatives
group ID; independent dimensions are not options. If no group is admissible,
do not output options. Do not use disagreement as options. Each unused feature
slot requires known value={"kind":"absent"} supported by inspecting the full
drawing, never by default. If the slot inventory is insufficient, leave a slot
unknown and explain the omitted features. The proofs field is known/sure with
entries (empty only if all other fields are unknown), cites the original image
IDs and explains its scope. During reconsideration use actual Opus criticism
and original evidence, then submit the revised candidate for reverification.
"""

_TEMPLATE_VERIFY = """Verify every field of THIS exact Sol candidate against the original
images (Read every image) and deterministic inventory, including the proofs
ledger. Do not make a second blind guess or compare duplicate answers. Check
each state, semantic value, option, numeric token's actual meaning/units/box,
geometry relationship, supported derivation/pattern, CAD frame, feature absence
and completeness against the drawing. Check every scalar proof for the field,
not just whether cited IDs exist. Algebraic equality alone does not prove a
dimension belongs to that feature. Border labels, scales, dates, material-grade
digits and unrelated equal-valued numbers are inadmissible dimensions. Options
must be actual printed alternatives for this same field, each with its own
number; unrelated measurements or reader disagreement must remain unresolved.
Unknown, unsure or host-invalid fields cannot receive verified. Every fixed
field needs an explicit verified/disagrees/unsure verdict with a nonempty
source-backed reason and evidence references from its original evidence.
For a verified verdict, source_ids must cite exactly that candidate field's
supporting IDs; do not cite another field's or an unrelated number's evidence.
Verify material/thread wording verbatim, printed weight in grams, all required
hole/slot dimensions and actual pattern counts/spacing; do not infer standards
or seed proposal/example values. A suggested alternative is criticism only,
requiring Sol revision and your reverification. Persistent disagreement/unsure
stays unresolved. Never promote your alternative or compute binding hashes.
"""


def build_template_job(drawing: DrawingEvidence, *, image_root: Path,
                       feature_slots: int = 12, job_id: str | None = None) -> VisionJob:
    """Build one source-bound M1 template job; no live execution or saved output.

    Slot count is an inventory bound, never a predicted number of features.
    Changing it changes prompt/contract/source digests and requires a fresh job.
    """
    drawing = _original(drawing)
    if drawing.id not in SUPPORTED_TEMPLATES or drawing.degraded:
        raise EvidenceError("M1 templates require clean deterministic D-013, D-025 or D-026 evidence.")
    if type(feature_slots) is not int or not 1 <= feature_slots <= 32:
        raise EvidenceError("The fixed feature-slot inventory must contain 1 through 32 slots.")
    paths = _page_paths(drawing, image_root)
    _images(drawing, paths)
    inputs = {f"page:{p}": EvidenceInput(path=path, image=True) for p, path in paths.items()}
    refs = {f"{drawing.id}/drawing/page/{p}": f"page:{p}" for p in paths}
    page_refs = set(refs)
    numbers = {n.name: n for n in drawing.numbers}
    if len(numbers) != len(drawing.numbers):
        raise EvidenceError("Number IDs must be unique in the original inventory.")
    admissible = {name: n for name, n in numbers.items() if _admissible_number(n, drawing)}
    refs.update({name: "drawing" for name in numbers})
    refs.update({f.name: "drawing" for f in drawing.fields.values()})
    groups = _printed_groups(drawing, admissible)
    group_refs = {f"{drawing.id}/drawing/printed-alternatives/{i+1}": group for i, group in enumerate(groups)}
    refs.update({name: "inventory" for name in group_refs})
    names = {k: template_fact_name(drawing.id, k) for k in
             ("outline", "thickness", "material", "weight-on-drawing", "proofs")}
    schemas = {names["outline"]: _OUTLINE, names["thickness"]: {"type": "number"},
               names["material"]: {"type": "string", "minLength": 1},
               names["weight-on-drawing"]: {"type": "number"}}
    for i in range(feature_slots):
        schemas[template_fact_name(drawing.id, f"feature-{i+1:02d}")] = _FEATURE
    schemas[names["proofs"]] = _proof_schema(list(schemas))
    inputs["drawing"] = EvidenceInput(value=drawing.model_dump(mode="json"))
    inputs["inventory"] = EvidenceInput(value={"version": VISION_VERSION, "kind": "flat-template",
        "drawing_id": drawing.id, "field_names": list(schemas), "feature_slots": feature_slots,
        "number_admissibility": {name: name in admissible for name in numbers},
        "printed_alternatives": group_refs, "cad_units": "mm", "weight_units": "g"})

    page_hashes = {page: inputs[f"page:{page}"].sha256 for page in paths}

    def check_original() -> None:
        if any(_sha(paths[p].read_bytes()) != digest for p, digest in page_hashes.items()):
            raise EvidenceError("Original template page changed; construct a fresh job.")

    def valid_proof(value: Any, evidence: ValueEvidence, field: str, option: bool, path: str) -> bool:
        cited = set(evidence.number_ids + evidence.source_ids)
        if evidence.derivation:
            cited.update(evidence.derivation.inputs)
            if evidence.derivation.pattern_fact:
                cited.add(evidence.derivation.pattern_fact)
        if not cited or not cited <= refs.keys():
            return False
        if type(value) in {int, float}:
            pool = admissible
            if field == names["weight-on-drawing"]:
                weight = drawing.fields.get("weight")
                pool = {key: n for key, n in numbers.items() if weight and weight.confidence == Confidence.SURE
                        and n.confidence == Confidence.SURE and n.page == weight.page and _inside(n.box, weight.box, .2)}
            if evidence.derivation:
                d = evidence.derivation
                if option or field == names["weight-on-drawing"] or not set(d.inputs) <= pool.keys():
                    return False
                if set(evidence.number_ids) != set(d.inputs):
                    return False
                if d.kind == "pattern" and d.pattern_fact not in page_refs:
                    return False
                try:
                    if len(d.expression) > 512:
                        return False
                    constants = {node.value for node in ast.walk(ast.parse(d.expression, mode="eval"))
                                 if isinstance(node, ast.Constant) and type(node.value) is int}
                    angle = any(part.endswith("_deg") for part in path.split("/"))
                    if constants & {90, 180, 360} and not angle:
                        return False
                    if 0 in constants and not (angle or path in {"/position/x", "/position/y"}):
                        return False
                    if any(pool[key].unit not in {None, "mm", "deg", "\N{DEGREE SIGN}", "count"} for key in d.inputs):
                        return False
                    computed = _expression(d.expression, [pool[key].value for key in d.inputs], pattern=d.kind == "pattern")
                except (ValueError, SyntaxError, IndexError, ArithmeticError, RecursionError):
                    return False
                return math.isclose(computed, value, rel_tol=1e-12, abs_tol=1e-9)
            unit = "g" if field == names["weight-on-drawing"] else (
                "deg" if any(part.endswith("_deg") for part in path.split("/")) else
                "count" if path.endswith("/count") else "mm")
            units = {None, unit} | ({"\N{DEGREE SIGN}"} if unit == "deg" else set())
            return (len(evidence.number_ids) == 1 and evidence.number_ids[0] in pool
                    and pool[evidence.number_ids[0]].value == value and pool[evidence.number_ids[0]].unit in units)
        if evidence.derivation or evidence.number_ids or not set(evidence.source_ids) & page_refs:
            return False
        if field == names["material"]:
            original = drawing.fields.get("material")
            return bool(original and original.confidence == Confidence.SURE and original.value == value
                        and original.name in evidence.source_ids
                        and f"{drawing.id}/drawing/page/{original.page}" in evidence.source_ids)
        return type(value) in {str, bool}

    def validate(candidate: DeterminationOutput, source: PrepSourceIdentity) -> dict[str, tuple[bool, bool]]:
        proof_field = candidate.fields[names["proofs"]]
        ledger = None
        if (proof_field.state == "known" and proof_field.confidence == Confidence.SURE
                and set(proof_field.source_ids) <= refs.keys() and set(proof_field.source_ids) & page_refs
                and _shape(proof_field.value, schemas[names["proofs"]])):
            try:
                ledger = _Proofs.model_validate(proof_field.value)
            except ValidationError:
                pass
        index, duplicates = {}, set()
        if ledger:
            for proof in ledger.entries:
                key = (proof.field, proof.option, proof.path)
                if key in index:
                    duplicates.add(key)
                index[key] = proof
        validity, consumed = {}, set()
        for name, field in candidate.fields.items():
            if name == names["proofs"]:
                continue
            shape = field.state in {"known", "options", "unknown"}
            values = [(None, field.value)] if field.state == "known" else list(enumerate(field.options))
            if field.state != "unknown":
                shape = (shape and field.confidence == Confidence.SURE
                         and all(_shape(value, schemas[name]) and _semantic(value) for _, value in values))
            if name in {names["thickness"], names["weight-on-drawing"]}:
                shape = shape and all(type(value) in {int, float} and value > 0 for _, value in values)
            if field.state == "options":
                # The native subset only supports scalar numeric/text options.
                shape = shape and name in {names["thickness"], names["material"], names["weight-on-drawing"]}
                shape = shape and len({_json(v) for v in field.options}) == len(field.options)
            evidence_valid = bool(shape and set(field.source_ids) <= refs.keys() and field.source_ids)
            option_numbers, supporting_ids = [], set()
            for option, value in values:
                for path, leaf in _leaves(value).items():
                    key = (name, option, path)
                    consumed.add(key)
                    proof = index.get(key)
                    if not proof or key in duplicates:
                        evidence_valid = False
                        continue
                    evidence = proof.evidence
                    used = set(evidence.number_ids + evidence.source_ids)
                    if evidence.derivation:
                        used.update(evidence.derivation.inputs)
                        if evidence.derivation.pattern_fact:
                            used.add(evidence.derivation.pattern_fact)
                    supporting_ids.update(used)
                    evidence_valid = (evidence_valid and used <= set(field.source_ids)
                                      and valid_proof(leaf, evidence, name, option is not None, path))
                    if path.endswith("/thread_size") and isinstance(leaf, str):
                        evidence_valid = evidence_valid and any(w.text == leaf and
                            f"{drawing.id}/drawing/page/{w.page}" in evidence.source_ids for w in drawing.words)
                    if option is not None:
                        option_numbers.extend(evidence.number_ids)
            if field.state == "options":
                supporting_ids.update(group for group, ids in group_refs.items()
                                      if group in field.source_ids and set(option_numbers) <= set(ids))
                evidence_valid = evidence_valid and any(
                    group in field.source_ids and len(option_numbers) == len(field.options)
                    and len(set(option_numbers)) == len(option_numbers) and set(option_numbers) <= set(ids)
                    for group, ids in group_refs.items())
            if field.state != "unknown":
                evidence_valid = evidence_valid and set(field.source_ids) == supporting_ids
            validity[name] = (bool(shape), bool(evidence_valid))
        ledger_valid = bool(ledger is not None and not duplicates and consumed == set(index)
                            and all(evidence for _, evidence in validity.values())
                            and proof_field.confidence == Confidence.SURE
                            and set(proof_field.source_ids) <= refs.keys()
                            and set(proof_field.source_ids) & page_refs)
        validity[names["proofs"]] = (ledger is not None and not duplicates and consumed == set(index), ledger_valid)
        # A malformed/extra proof must never leave another field usable in the
        # Sol-only execution-failure path. Correctly formed unsupported entries
        # invalidate their owning field without erasing other available fields.
        if not validity[names["proofs"]][0]:
            validity = {name: (shape, False) for name, (shape, _) in validity.items()}
        return validity

    return _bind(f"vision.template.{drawing.id}", job_id, (_TEMPLATE_DETERMINE, _TEMPLATE_VERIFY),
                 schemas, inputs, refs, check_original, validate)


def scan_readings(job: VisionJob, drawing: DrawingEvidence, result: PrepProvenance) -> dict[str, DrawingField]:
    """Project validated Sol values in memory; retain every round in provenance.

    No human review is created. Unresolved scans are null/unsure, not verifier
    alternatives or unverified guesses from an earlier round.
    """
    result = validate_vision_result(job, result)
    if not job.definition.job.startswith("vision.scan."):
        raise EvidenceError("Scan projection requires a scan job.")
    drawing = _original(drawing)
    inventory = job.definition.evidence(job.request).inputs["inventory"].value
    if (drawing.id != inventory["drawing_id"] or drawing.source_sha256 != inventory["pdf_sha256"]
            or set(f.name for f in drawing.fields.values()) != set(inventory["fields"])
            or any(list(f.box) != inventory["fields"][f.name]["box"] or f.page != inventory["fields"][f.name]["page"]
                   or f.original is not None or f.value is not None for f in drawing.fields.values())):
        raise EvidenceError("Scan projection drawing or whole-field regions differ from the original job.")
    methods = {"first_pass_verified": Method.AI_VERIFIED, "retry_verified": Method.AI_VERIFIED_AFTER_RETRY,
               "unverified_fallback": Method.AI_SINGLE_MODEL, "unresolved": Method.UNRESOLVED}
    output = {}
    for key, original in drawing.fields.items():
        resolved = result.field_results[original.name]
        field = resolved.accepted
        output[key] = DrawingField.model_validate({**original.model_dump(mode="json"),
            "value": field.value if field else None, "confidence": "sure" if field else "unsure",
            "method": methods[resolved.status], "provenance": result.model_dump(mode="json"),
            "note": field.reason if field else "Undetermined scan field; retained prep rounds explain the unresolved reading."})
    return output


def validate_vision_result(job: VisionJob, result: PrepProvenance) -> PrepProvenance:
    """Required domain check before M11 publication; never rewrite raw rounds.

    M08 checks all verdict IDs belong to the job. Here each verified verdict
    must also cite the exact supporting references of its candidate field.
    Invalid domain output raises EvidenceError: retain its raw runtime rounds
    for Debug, publish it as unresolved, and never reinterpret it as an Opus
    execution failure or auto-promote a verifier alternative.
    """
    # Reparse instead of trusting model_copy(update=...), which bypasses Pydantic
    # validators. Recheck actual source files as well as candidate-bound hashes.
    result = PrepProvenance.model_validate_json(result.model_dump_json())
    if (result.job != job.request.job or result.job_id != job.request.job_id or result.source != job.request.source
            or result.field_names != job.request.field_names
            or result.determination_prompt_sha256 != job.request.determination_prompt_sha256
            or result.verification_prompt_sha256 != job.request.verification_prompt_sha256
            or result.output_contract_sha256 != job.request.output_contract_sha256):
        raise EvidenceError("Vision projection requires this job's exact source-bound provenance.")
    job.definition.evidence(job.request).check(result.source)
    for round_ in result.rounds:
        candidate = round_.determination.output
        if candidate is not None:
            checked = job.definition.validate_candidate(candidate, result.source)
            if checked != candidate:
                raise EvidenceError("Candidate domain validation changed; the retained output is unsupported.")
        verification = round_.verification
        if candidate is not None and verification is not None and verification.output is not None:
            for name, verdict in verification.output.fields.items():
                if verdict.verdict == "verified" and set(verdict.source_ids) != set(candidate.fields[name].source_ids):
                    raise EvidenceError("Verified vision verdict cites evidence outside its exact candidate field support.")
    return result


def template_review_details(job: VisionJob, result: PrepProvenance) -> dict[str, Any]:
    """In-memory evidence for optional Debug/Review; no queue/action/publication.

    Preserve actual Sol answers and Opus findings in both rounds. A missing
    Opus answer is explicit, including in authorized unverified fallback; an
    alternative stays inside the verdict, never inside accepted/proposed value.
    """
    result = validate_vision_result(job, result)
    if not job.definition.job.startswith("vision.template."):
        raise EvidenceError("Template review details require a template job.")
    details = {}
    for name in result.field_names:
        rounds = []
        for round_ in result.rounds:
            candidate = round_.determination.output
            verification = round_.verification
            verdicts = verification.output if verification else None
            rounds.append({"round": round_.round,
                "candidate_sha256": candidate.candidate_sha256 if candidate else None,
                "candidate": candidate.fields[name].model_dump(mode="json") if candidate else None,
                "verification_status": verification.status if verification else None,
                "missing_opus_output": verdicts is None,
                "failure": verification.failure.model_dump(mode="json") if verification and verification.failure else None,
                "verdict": verdicts.fields[name].model_dump(mode="json") if verdicts else None})
        details[name] = {**result.field_results[name].model_dump(mode="json"), "rounds": rounds}
    return details
