"""Image-read printed numbers with exact-proposal verification and source locations.

This is a separate evidence layer. It never measures an image or modifies the
original parser output, supplied drawing, template, or human decision history.
"""
from __future__ import annotations

import copy
import math
import re

from backend.paths import GENERATED, inside
from . import runner

PROTOCOL = "printed-image-dimensions-v1"
UNITS = {"mm", "deg", "count", "unitless"}
TOKEN = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
VALIDATOR_REPLAY = "printed-image-numeric-range-validator-v1"


def printed_tokens(text: str) -> list[str]:
    """An unspaced numeric range separator is not the endpoint's sign."""
    result, previous_end = [], None
    for match in TOKEN.finditer(text):
        token = match.group()
        if token.startswith("-") and previous_end == match.start():
            token = token[1:]
        result.append(token)
        previous_end = match.end()
    return result


def job(drawing: dict) -> dict:
    """Read original pages, not fused records or previous model answers."""
    from .pipeline import BASE_PROMPT

    did = drawing["id"]
    sizes = drawing["page_sizes"]
    images = drawing.get("images") or [drawing["image"]]
    if len(images) != len(sizes) or not sizes:
        raise ValueError("Image dimension reading requires every original page and its PDF size")
    if not re.fullmatch(r"[0-9a-f]{64}", str(drawing.get("sha256", ""))):
        raise ValueError("Image dimension reading must bind the original drawing's SHA-256")
    source = f"{did}/drawing/source"
    keys = [f"page_{page}" for page in range(1, len(sizes) + 1)]
    return {"id": f"dimensions:{did}:{PROTOCOL}", "kind": "image_dimensions", "drawing": did,
            "source_sha256": drawing["sha256"], "page_sizes": copy.deepcopy(sizes), "keys": keys,
            "sources": [source], "images": [str(inside(GENERATED / image)) for image in images],
            "prompt": BASE_PROMPT + "\n" + PROTOCOL + """
Read the ORIGINAL supplied drawing images for printed numeric engineering evidence.
For each requested page_N return state known and value_json a JSON array of objects
with EXACT keys text, token, value, unit, box. text copies the complete printed
dimension/callout context; token copies ONE literal printed numeric token from
that text; value is only that token parsed as a number (decimal comma is allowed).
unit is mm, deg, count, or unitless according to the printed context. Preserve
diameter/radius/depth/thread symbols and THRU/count qualifiers in text; do not
turn a thread nominal size into a bore, a radius into a diameter, or a tolerance
into a nominal dimension. Multiple numbers in one callout need separate entries
with the same full text and bounding box and their respective tokens/units.
Include printed overall/body dimensions, thickness alternatives, feature sizes,
hole/slot counts, pitches, offsets, diameters/radii, depths, angles and edge/corner
details. Ignore title-block weight, dates, drawing IDs, scale and page numbers.
Do not assign an unlabeled number to a geometric meaning at this stage. Do not
derive coordinates, scale/convert units, infer hardware dimensions, use another
drawing, or measure geometry from pixels. A box only LOCATES PRINTED TEXT.
box is [x,y,width,height] in ORIGINAL PDF page points, origin top left; convert
the text's image location using the supplied PDF page width/height. It must
tightly enclose the actual printed label/callout, not an entire view or page.
Do not invent unreadable characters. Include only confidently legible tokens.
Use known [] if that page has no legible engineering numbers; unreadable numbers
remain absent. This does not claim a complete drawing or approve any design.
Cite only the supplied drawing/source ID for each page item. In reason identify
which visible dimensions/callouts were readable and what remained unreadable.
The verifier must inspect EVERY token, copied context, unit and exact location
against that ORIGINAL page. Reject a guessed/changed token, wrong page, unrelated
box, inferred dimension or incorrectly classified unit. A close location can be
corrected in the one bounded retry; it never authorizes pixel measurements.
Original pages in image order, with PDF sizes in points:
""" + runner.json_text({"drawing_id": did, "source_sha256": drawing["sha256"],
                         "page_sizes": sizes, "source_ids": [source]})}


def jobs(drawing: dict) -> list[dict]:
    """Bound multi-page transcription size without renumbering original pages.

    Single-page requests intentionally retain the exact existing job and cache
    identity. Multi-page requests keep the full original PDF page-size table.
    """
    original = job(drawing)
    if len(original["keys"]) == 1:
        return [original]
    result = []
    for page, image in enumerate(original["images"], start=1):
        current = copy.deepcopy(original)
        key = f"page_{page}"
        current.update(id=f"{original['id']}:{key}", keys=[key], images=[image], image_original_pages=[page])
        current["prompt"] = original["prompt"].replace(
            "Original pages in image order, with PDF sizes in points:",
            "Original PDF page sizes in points, indexed by ORIGINAL one-based page number:")
        current["prompt"] += (
            "\nSINGLE ORIGINAL PAGE REQUEST. Only ONE image is supplied. Its original PDF page "
            f"number is {page}; return ONLY key {key}. Do not relabel this image page_1. "
            f"Use page_sizes[{page - 1}] for its original PDF-point coordinates. Other original "
            "pages are not supplied and must not be read, reconstructed or returned. "
            "The image_original_pages array maps supplied images to original PDF page numbers:\n" +
            runner.json_text({"image_original_pages": [page], "requested_keys": [key]}))
        result.append(current)
    return result


def validate(value, current: dict, key: str, refs: list[str]) -> None:
    """Validate a transcription's structure; Opus checks its visual truth."""
    if not isinstance(value, list) or refs != [f"{current['drawing']}/drawing/source"]:
        raise ValueError("Printed image numbers must cite their original drawing")
    page = int(key.removeprefix("page_"))
    width, height = current["page_sizes"][page - 1]
    seen = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"text", "token", "value", "unit", "box"}:
            raise ValueError("Malformed printed image number")
        text, token, number, box = entry["text"], entry["token"], entry["value"], entry["box"]
        if (not isinstance(text, str) or not text.strip() or not isinstance(token, str) or
                not TOKEN.fullmatch(token) or token not in printed_tokens(text) or
                type(number) not in (int, float) or not math.isfinite(number) or
                not math.isclose(number, float(token.replace(",", ".")), rel_tol=0, abs_tol=1e-9) or
                not isinstance(entry["unit"], str) or entry["unit"] not in UNITS):
            raise ValueError("Image number must copy a literal printed token without conversion")
        if (not isinstance(box, list) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
            raise ValueError("Image number requires a finite PDF-point text box")
        x, y, w, h = box
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError("Image number text box escapes its original page")
        identity = runner.fingerprint(entry)
        if identity in seen:
            raise ValueError("Duplicate image number")
        seen.add(identity)


def _decode_cached_round(result: dict, index: int):
    """Read exact historical packets; never recompute their original validation."""
    from . import pipeline

    if (result.get("protocol") != pipeline.PROTOCOL or
            result.get("job", {}).get("kind") != "image_dimensions" or
            not 1 <= len(result.get("rounds", [])) <= 2):
        return None
    raw = result["rounds"][index]
    proposer, verifier = raw.get("codex", {}), raw.get("claude", {})
    validation = proposer.get("validation", {})
    keys = [key for key in result["job"]["keys"] if key in validation]
    if (not keys or set(validation) != set(keys) or any(type(value) is not bool for value in validation.values()) or
            proposer.get("role") != "proposer" or verifier.get("role") != "verifier" or
            proposer.get("protocol") != pipeline.PROTOCOL or verifier.get("protocol") != pipeline.PROTOCOL or
            proposer.get("round") != index or verifier.get("round") != index):
        return None
    packet = {"protocol": pipeline.PROTOCOL, "keys": keys, "proposal": proposer.get("answer"),
              "locally_valid_keys": sorted(key for key in keys if validation[key]),
              "invalid_keys": [key for key in keys if not validation[key]]}
    fingerprint = runner.fingerprint(packet)
    if proposer.get("proposal_fingerprint") != fingerprint or verifier.get("proposal_fingerprint") != fingerprint:
        return None
    current = {**result["job"], "keys": keys}
    previous = {}
    if index:
        first = result["rounds"][0].get("codex", {})
        before = pipeline.decode_answer(first, result["job"])
        previous = {key: before.get(key) for key in keys if first.get("validation", {}).get(key) is True}
    proposals = pipeline.decode_answer(proposer, current, retry=index > 0, previous=previous)
    verdicts = pipeline.decode_verification(verifier, current, fingerprint)
    if (set(proposals) != set(keys) or set(verdicts) != set(keys) or
            any(proposals[key].get("state") != "known" or verdicts[key]["decision"] != "accept" for key in keys)):
        return None
    return keys, fingerprint, proposals, verdicts


def revalidate_cached_result(result: dict) -> dict:
    """Offline structural replay of an already accepted exact final proposal.

    Original model output, validation flags, fingerprints and round receipts are
    immutable. No reader, execution or retry function is called by this helper.
    """
    updated = copy.deepcopy(result)
    if not result.get("rounds") or not any(state == "invalid" for state in result.get("states", {}).values()):
        return updated
    decoded = _decode_cached_round(result, len(result["rounds"]) - 1)
    if decoded is None:
        return updated
    keys, fingerprint, proposals, verdicts = decoded
    if any(result["states"].get(key) not in {"invalid", "verified", "verified_after_retry"} for key in keys):
        return updated
    updated.setdefault("validator_replays", []).append({
        "protocol": VALIDATOR_REPLAY, "kind": "local_structural_validation", "provider_calls": 0,
        "original_result_sha256": runner.fingerprint(result),
        "raw_rounds_sha256": runner.fingerprint(result["rounds"]),
        "proposal_fingerprint": fingerprint, "keys": keys,
        "previous_states": copy.deepcopy(result["states"]), "previous_answers": copy.deepcopy(result["answers"]),
        "validation": {key: True for key in keys},
        "reason": "Adjacent numeric range hyphens are separators; original model responses and verifier acceptance are unchanged."})
    for key in keys:
        updated["answers"]["codex"][key] = proposals[key]
        updated["answers"]["claude"][key] = verdicts[key]
        updated["states"][key] = "verified_after_retry" if len(result["rounds"]) == 2 else "verified"
    return updated


def assemble(result: dict) -> dict:
    """Only verified original-page transcriptions enter the numeric index."""
    from .pipeline import PROTOCOL as PREP_PROTOCOL, VERIFIED_STATES, resolved

    current = result["job"]
    pages, fields = {}, []
    for key in current["keys"]:
        reading = resolved(result, key)
        if result.get("validator_replays"):
            reading["validator_replays"] = copy.deepcopy(result["validator_replays"])
        pages[key] = reading
        if result.get("protocol") != PREP_PROTOCOL or result["states"].get(key) not in VERIFIED_STATES:
            continue
        page = int(key.removeprefix("page_"))
        for entry in reading["value"]:
            identity = runner.fingerprint({"page": page, **entry})[:16]
            fields.append({**copy.deepcopy(entry), "name": f"{current['drawing']}/drawing/visual-n/p{page}-{identity}",
                           "page": page, "original": entry["text"], "confidence": "sure",
                           "source_sha256": current["source_sha256"], "method": reading["method"],
                           "fact_ids": reading["fact_ids"], "readers": reading["readers"],
                           "review": copy.deepcopy(reading["review"]), "note": reading["note"]})
    return {"protocol": PROTOCOL, "source_sha256": current["source_sha256"],
            "fields": sorted(fields, key=lambda field: (field["page"], field["box"][1], field["box"][0], field["token"])),
            "pages": pages}


def merge(previous: dict | None, incoming: dict) -> dict:
    """Combine page receipts only for the same original PDF and protocol."""
    if previous is None:
        return copy.deepcopy(incoming)
    if (previous.get("source_sha256") != incoming.get("source_sha256") or
            previous.get("protocol") != PROTOCOL or incoming.get("protocol") != PROTOCOL):
        raise ValueError("Cannot merge printed image evidence from different original drawings or protocols")
    updated_pages = set(incoming["pages"])
    # A repeated page replaces its old index together with its receipt, so stale
    # numbers cannot survive a later unsuccessful reading of that same page.
    fields = [field for field in previous["fields"] if f"page_{field['page']}" not in updated_pages]
    fields.extend(incoming["fields"])
    return {"protocol": PROTOCOL, "source_sha256": incoming["source_sha256"],
            "pages": copy.deepcopy({**previous["pages"], **incoming["pages"]}),
            "fields": copy.deepcopy(sorted(fields, key=lambda field: (
                field["page"], field["box"][1], field["box"][0], field["token"])))}


def attach(drawing: dict, evidence: dict | None) -> dict:
    """Return a copy augmented with this original drawing's verified numeric facts."""
    result = copy.deepcopy(drawing)
    if not evidence or evidence.get("source_sha256") != drawing.get("sha256"):
        return result
    if evidence.get("protocol") != PROTOCOL:
        return result
    existing = {field["name"] for field in result.get("numbers", [])}
    for field in evidence.get("fields", []):
        if (field.get("method") not in ("ai_verified", "ai_verified_after_retry") or
                field.get("source_sha256") != drawing.get("sha256") or
                not isinstance(field.get("name"), str) or
                not field["name"].startswith(f"{drawing['id']}/drawing/visual-n/")):
            continue
        page = field.get("page")
        if type(page) is not int or not 1 <= page <= len(drawing["page_sizes"]):
            continue
        entry = {key: field.get(key) for key in ("text", "token", "value", "unit", "box")}
        reading = evidence.get("pages", {}).get(f"page_{page}", {})
        identity = runner.fingerprint({"page": page, **entry})[:16]
        if (field["name"] != f"{drawing['id']}/drawing/visual-n/p{page}-{identity}" or
                reading.get("method") not in ("ai_verified", "ai_verified_after_retry") or
                reading.get("state") != "known" or entry not in (reading.get("value") or []) or
                field.get("readers") != reading.get("readers") or not field.get("readers")):
            continue
        try:
            validate([entry], {"drawing": drawing["id"], "page_sizes": drawing["page_sizes"]},
                     f"page_{page}", field.get("fact_ids", []))
        except (ValueError, TypeError, IndexError):
            continue
        if field["name"] not in existing:
            result.setdefault("numbers", []).append(copy.deepcopy(field))
            existing.add(field["name"])
    return result
