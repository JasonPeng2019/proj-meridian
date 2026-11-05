"""Reproducible two-reader dataset preparation. Normal app launch is offline."""
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import copy
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from backend.paths import GENERATED, ROOT, inside
from . import runner

SCAN_KEYS = ("title", "material", "weight_g", "notes", "date", "company", "scale", "drawn")
TEMPLATE_KEYS = ("outline_type", "length", "width", "outer_diameter", "inner_diameter", "thickness", "features")
PRIMARY_TEMPLATES = ("D-013", "D-025", "D-026")
REVIEW = {"status": "not_reviewed"}


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def field_value(obj: dict, key: str) -> Any:
    return obj.get("fields", {}).get(key, {}).get("value")


def schema(keys: list[str] | tuple[str, ...]) -> dict:
    props = {"key": {"type": "string", "enum": list(keys)},
             "state": {"type": "string", "enum": ["known", "options", "unknown"]},
             "value_json": {"type": "string"},
             "confidence": {"type": "string", "enum": ["sure", "unsure"]},
             "fact_ids": {"type": "array", "items": {"type": "string"}},
             "reason": {"type": "string"}, "changed_because": {"type": "string"}}
    item = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    return {"type": "object", "properties": {"items": {"type": "array", "items": item}},
            "required": ["items"], "additionalProperties": False}


BASE_PROMPT = """You are an independent, read-only engineering evidence reader. Do not edit files,
run commands, use other agents, browse the web, or inspect any evidence beyond the supplied inputs.
Return the requested JSON schema. Every requested key must appear exactly once. value_json is a
JSON-encoded value (e.g. a string as \"\\\"text\\\"\", a number as \"5\", an array as \"[3,6]\",
unknown as \"null\"). State known means one determined value; options means genuinely documented
alternatives; unknown means the evidence does not determine it. confidence is only sure or unsure.
Use sure only for a reading supported by the supplied evidence. Copy original spelling and units.
Never invent evidence IDs. fact_ids must be exact supplied source IDs supporting that item.
Reasons must explain the evidence; changed_because is empty on the independent first reading.
"""


def source_ids(drawing: dict) -> set[str]:
    ids = {v["name"] for v in drawing.get("fields", {}).values() if v.get("name")}
    ids.update(n["name"] for n in drawing.get("numbers", []) if n.get("name"))
    ids.update(n["name"] for n in drawing.get("callouts", []) if n.get("name"))
    ids.add(f"{drawing['id']}/drawing/source")
    ids.add(drawing["id"])
    return ids


def scan_job(drawing: dict) -> dict:
    did = drawing["id"]
    return {"id": f"scan:{did}", "kind": "scan", "drawing": did, "keys": list(SCAN_KEYS),
            "images": [str(inside(GENERATED / drawing["corner_image"]))], "sources": sorted(source_ids(drawing)),
            "prompt": BASE_PROMPT + "\nRead ONLY the supplied cropped title block, not measurements. "
            "Copy each field character by character. Do not translate, correct spelling, or fill blanks. "
            "Unreadable or absent fields are unknown/null/unsure. Weight must be a numeric gram value "
            "only if printed unambiguously in grams; other fields are exact strings. Do not infer names "
            "from filenames. Fields: " + ", ".join(SCAN_KEYS) + "\n" + runner.json_text({
                "drawing_id": did, "field_evidence": drawing.get("fields", {}),
                "source_ids": sorted(source_ids(drawing))})}


def template_job(drawing: dict) -> dict:
    did = drawing["id"]
    image = drawing.get("images") or [drawing["image"]]
    return {"id": f"template:{did}", "kind": "template", "drawing": did,
            "keys": list(TEMPLATE_KEYS), "images": [str(inside(GENERATED / p)) for p in image], "sources": sorted(source_ids(drawing)),
            "numbers": {n["name"]: n["value"] for n in drawing.get("numbers", [])},
            "prompt": BASE_PROMPT + """\nFill a flat-part template from this drawing, in millimetres.
Read the attached full drawing. The main material field and weight are supplied separately.
Requested keys: outline_type (rectangle/circle/ring), length (X), width (Y), outer_diameter,
inner_diameter, thickness, features. Only relevant dimensions are known; irrelevant ones are unknown.
Stacked thickness values which are alternatives MUST be state options with a JSON array, sorted ascending.
Do not select one thickness or invent which example is primary. The outline is centered on X=0,Y=0;
extrusion Z=0..thickness. Ignore dimension text placement when interpreting actual geometry.
features value is a JSON array of hole/slot objects. Each has kind, face='top', x,y,
diameter (hole) or width,length (slot), through boolean, depth for blind holes,
hole_type plain/threaded/countersunk/counterbored, optional thread string and required actual
countersink_diameter/angle or counterbore_diameter/depth. Never infer a drill diameter from a thread.
Use explicit pattern only if certain: {type:row,count,spacing,direction} (angle degrees, anchor first
position) or {type:circle,count,radius,start_angle} (degrees, center x,y). Hole positions are center
coordinates in the same XY frame. A feature with missing dimensions or positions is unknown and
must be omitted, with reason describing the omission. The features state is unknown if you cannot
determine all features; return only the certain features in its array and explain missing information.
All numeric scalar fields within a feature must be {state:known,value:number,fact_ids:[IDs]}.
A feature may carry parent fact_ids. Every numeric value must match its cited drawing number.
For an arithmetically derived coordinate/radius use {state:known,value:number,fact_ids:[IDs],
expression:'n0/2-n1'}, where n0,n1 are cited drawing numbers IN ORDER. Only +,-,*,/ and constants
0,1,2 are allowed. Do not invent absolute positions from undimensioned views. You may use literal
0 for a geometrically established center or literal 90/180/270/360 for cardinal pattern directions.
Do not infer numeric dimensions from pixels, scale, standard hardware, or symmetry unless dimensioned.
Features must use same deterministic ordering: holes before slots, then x ascending, then y ascending.
""" + "\nEvidence:\n" + runner.json_text({k: v for k, v in drawing.items() if k in
    ("id", "fields", "numbers", "callouts", "page_sizes", "section", "source_filename")})}


def custom_rows(bom: list[dict]) -> list[dict]:
    return [r for r in bom if norm(field_value(r, "type")) == "custom"]


def brief_row(row: dict) -> dict:
    return {"name": row["name"], "display_name": row["display_name"], "section": row.get("section"),
            "material": field_value(row, "material"), "notes": field_value(row, "notes"),
            "datasheet": datasheet_filenames(field_value(row, "datasheet"))}


def datasheet_filenames(value: Any) -> list[str]:
    if isinstance(value, dict): return [str(value["filename"])] if value.get("filename") else []
    if isinstance(value, list): return [name for entry in value for name in datasheet_filenames(entry)]
    return [v.replace("\\", "/").split("/")[-1] for v in re.split(r"[,;\s]+", str(value or "")) if v]


def exact_link(drawing: dict, bom: list[dict]) -> dict | None:
    filename = str(drawing.get("source_filename") or drawing.get("source_path", "")).replace("\\", "/").split("/")[-1]
    datasheet = [r for r in bom if filename and filename.lower() in
                 [v.lower() for v in datasheet_filenames(field_value(r, "datasheet"))]]
    if len(datasheet) > 1:
        return None
    candidates = datasheet
    if not candidates:
        names = {norm(Path(filename).stem), norm(field_value(drawing, "title"))} - {""}
        candidates = [r for r in bom if norm(r["display_name"]) in names]
    if len(candidates) != 1:
        return None
    return {"bom_rows": [candidates[0]["name"]], "method": "exact_match", "readers": {},
            "reason": "Unique datasheet filename" if datasheet else "Unique normalized original filename or title"}


def match_job(drawing: dict, rows: list[dict]) -> dict:
    return {"id": f"link:{drawing['id']}", "kind": "link", "drawing": drawing["id"], "keys": ["link"],
            "images": [], "sources": sorted(source_ids(drawing) | {r["name"] for r in rows}),
            "row_ids": [r["name"] for r in rows],
            "prompt": BASE_PROMPT + "\nMatch this drawing to the custom BOM rows using names, notes, "
            "section as written, material and datasheet. Do not assume differing section/material names "
            "have already been approved as equivalent. Key link value is a JSON array of EXACT BOM row "
            "canonical names, or [] when no match. Usually one row. Multiple rows only if evidence "
            "explicitly supports this drawing representing all of them; ambiguity means unknown/unsure. "
            "Cite drawing field IDs and BOM row IDs in fact_ids. Explain ambiguity in reason.\n" +
            runner.json_text({"drawing": {"id": drawing["id"], "section": drawing.get("section"),
                              "source_filename": drawing.get("source_filename"), "degraded": drawing.get("degraded"),
                              "fields": {k: {"name": v["name"], "value": v.get("value") if v.get("confidence") == "sure" else None,
                                                   "confidence": v.get("confidence")}
                                         for k, v in drawing.get("fields", {}).items() if k in ("title", "material", "notes")}},
                              "custom_bom": [brief_row(r) for r in rows]})}


def mapping_jobs(drawings: dict, bom: list[dict], links: dict) -> list[dict]:
    rows = {r["name"]: r for r in bom}
    pairs: dict[tuple, list[str]] = {}
    for did, link in links.items():
        for rid in link.get("bom_rows", []):
            if rid not in rows:
                continue
            drawing, row = drawings[did], rows[rid]
            material = field_value(row, "material")
            if isinstance(material, list): material = ", ".join(material)
            for kind, left, right in (("section", drawing.get("section"), row.get("section")),
                                      ("material", field_value(drawing, "material"), material)):
                if left and right and norm(left) != norm(right):
                    pairs.setdefault((kind, str(left), str(right)), []).extend([f"{did}/drawing/source", rid])
    # Unrepresented BOM sections have no equivalent in this drawing corpus.
    covered = {str(rows[r]["section"]) for l in links.values() for r in l.get("bom_rows", []) if r in rows}
    drawing_sections = {norm(d.get("section")) for d in drawings.values()}
    for section in sorted({r["section"] for r in bom} - covered):
        if norm(section) not in drawing_sections:
            pairs.setdefault(("section", "", section), [])
    jobs = []
    for (kind, left, right), evidence in sorted(pairs.items()):
        name = f"names/{kind}/{re.sub(r'[^a-z0-9]+', '-', left.lower()).strip('-')} -> {re.sub(r'[^a-z0-9]+', '-', right.lower()).strip('-')}"
        jobs.append({"id": f"mapping:{name}", "name": name, "kind": "mapping", "mapping_kind": kind,
                     "left": left or None, "right": right, "keys": ["relationship"], "images": [],
                     "sources": sorted(set(evidence)), "evidence": sorted(set(evidence)),
                     "prompt": BASE_PROMPT + "\nSuggest a name relationship: same, kind_of (LEFT is more "
                     "specific than RIGHT), different, or no_equivalent. This is only a suggestion: "
                     "EVERY mapping requires actual human approval before use. Material relationships "
                     "may use general engineering knowledge and MUST say 'based on general engineering "
                     "knowledge, not the dataset' in reason. Section relationships should be grounded "
                     "in the supplied established links. Empty left means no represented drawing section; "
                     "use no_equivalent. Key relationship has JSON string value.\n" + runner.json_text({
                         "kind": kind, "left": left or None, "right": right,
                         "established_links": evidence, "all_drawing_sections": sorted({d.get("section", "") for d in drawings.values()})})})
    return jobs


def expression_value(expression: str, values: list[float]) -> float:
    """Small arithmetic evidence checker, not eval or arbitrary code execution."""
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Name) and re.fullmatch(r"n\d+", node.id):
            return values[int(node.id[1:])]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value in (0, 1, 2):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return walk(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add): return a + b
            if isinstance(node.op, ast.Sub): return a - b
            if isinstance(node.op, ast.Mult): return a * b
            return a / b
        raise ValueError("Unsupported numeric derivation")
    return float(walk(ast.parse(expression, mode="eval")))


def validate_geometry(value: Any, numbers: dict, allowed: set[str], inherited: list[str], key: str = "") -> None:
    if isinstance(value, dict):
        refs = value.get("fact_ids", inherited)
        if not isinstance(refs, list) or any(r not in allowed for r in refs):
            raise ValueError("Invented feature evidence ID")
        if "value" in value and isinstance(value["value"], (int, float)) and not isinstance(value["value"], bool):
            validate_number(value["value"], refs, numbers, key, value.get("expression"))
        for child, content in value.items():
            if child not in {"fact_ids", "value", "confidence", "expression", "reason"}:
                validate_geometry(content, numbers, allowed, refs, child)
    elif isinstance(value, list):
        for content in value:
            validate_geometry(content, numbers, allowed, inherited, key)
    elif type(value) in (int, float):
        validate_number(value, inherited, numbers, key)


def validate_number(value: float, refs: list[str], numbers: dict, key: str, expression: str | None = None) -> None:
    if not math.isfinite(value):
        raise ValueError("Non-finite geometric value")
    values = [numbers[r] for r in refs if r in numbers and type(numbers[r]) in (int, float)]
    if expression:
        if not values or not math.isclose(value, expression_value(expression, values), abs_tol=1e-6):
            raise ValueError("Arithmetic is not grounded in cited drawing numbers")
        return
    if value == 0 and key in ("x", "y", "start_angle", "direction"):
        return
    if key in ("start_angle", "direction") and value in (90, 180, 270, 360):
        return
    if not values or not any(math.isclose(value, v, abs_tol=1e-6) for v in values):
        raise ValueError(f"Numeric {key}={value} is not in its cited drawing numbers")


def validate_features(features: list, numbers: dict, allowed: set[str], refs: list[str]) -> None:
    def numeric(container, key, positive=False):
        value = container.get(key)
        if isinstance(value, dict):
            if value.get("state") != "known": raise ValueError("Unknown feature scalar")
            value = value.get("value")
        if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
            raise ValueError(f"Missing or invalid feature {key}")
        return value
    for feature in features:
        if not isinstance(feature, dict) or feature.get("kind") not in ("hole", "slot") or feature.get("face") not in ("top", "bottom"):
            raise ValueError("Unsupported feature type or face")
        numeric(feature, "x")
        numeric(feature, "y")
        if type(feature.get("through")) is not bool: raise ValueError("Feature through state missing")
        if not feature["through"]: numeric(feature, "depth", True)
        if feature["kind"] == "hole":
            numeric(feature, "diameter", True)
            hole_type = feature.get("hole_type")
            if hole_type not in ("plain", "threaded", "countersunk", "counterbored"):
                raise ValueError("Unsupported hole type")
            if hole_type == "threaded" and not isinstance(feature.get("thread"), str):
                raise ValueError("Missing literal thread callout")
            for key in {"countersunk": ("countersink_diameter", "countersink_angle"),
                        "counterbored": ("counterbore_diameter", "counterbore_depth")}.get(hole_type, ()):
                numeric(feature, key, True)
        else:
            numeric(feature, "width", True)
            if numeric(feature, "length", True) < numeric(feature, "width", True):
                raise ValueError("Slot length is smaller than its width")
        pattern = feature.get("pattern")
        if pattern:
            count = numeric(pattern, "count", True)
            if count != int(count): raise ValueError("Non-integer feature count")
            if pattern.get("type") == "circle":
                numeric(pattern, "radius", True)
                numeric(pattern, "start_angle")
            elif pattern.get("type") == "row":
                numeric(pattern, "spacing", True)
                if pattern.get("direction") not in ("x", "y"): numeric(pattern, "direction")
            else: raise ValueError("Unsupported feature pattern")
    validate_geometry(features, numbers, allowed, refs)


def decode_answer(raw: dict, job: dict, retry: bool = False, previous: dict | None = None) -> dict:
    result = {}
    if not raw.get("valid") or not isinstance(raw.get("answer"), dict):
        return result
    items = raw["answer"].get("items")
    if not isinstance(items, list):
        return result
    counts = Counter(v.get("key") for v in items if isinstance(v, dict))
    for item in items:
        try:
            key = item["key"]
            if key not in job["keys"] or counts[key] != 1:
                continue
            value = json.loads(item["value_json"])
            if item.get("confidence") not in ("sure", "unsure") or item.get("state") not in ("known", "options", "unknown"):
                continue
            refs = item.get("fact_ids", [])
            if not isinstance(refs, list) or any(r not in job["sources"] for r in refs):
                continue
            decoded = {k: copy.deepcopy(v) for k, v in item.items() if k != "value_json"}
            decoded["value"] = value
            if item["state"] == "unknown":
                decoded["confidence"] = "unsure"
                if value is None:
                    result[key] = decoded
                    continue
            elif value is None or not item.get("reason"):
                continue
            if item["state"] == "options" and (not isinstance(value, list) or len(value) < 2):
                continue
            if job["kind"] == "link":
                if item["state"] == "options" or not isinstance(value, list) or any(r not in job["row_ids"] for r in value):
                    continue
                decoded["value"] = sorted(set(value))
            elif job["kind"] == "mapping":
                if value not in ("same", "kind_of", "different", "no_equivalent"):
                    continue
            elif job["kind"] == "scan" and item["state"] != "unknown":
                if key == "weight_g":
                    if type(value) not in (int, float) or not math.isfinite(value): continue
                elif not isinstance(value, str):
                    continue
            elif job["kind"] == "template":
                if key == "outline_type":
                    if value not in ("rectangle", "circle", "ring"): continue
                elif key == "features":
                    if item["state"] == "options" or not isinstance(value, list): continue
                    validate_features(value, job["numbers"], set(job["sources"]), refs)
                else:
                    vals = value if item["state"] == "options" else [value]
                    if any(type(v) not in (int, float) or v <= 0 for v in vals): continue
                    for v in vals: validate_number(v, refs, job["numbers"], key)
                    if item["state"] == "options":
                        decoded["value"] = sorted(set(vals))
                        if len(decoded["value"]) < 2: continue
            if retry:
                # A changed second answer needs an explicit explanation, and all retries cite evidence.
                if not refs and job.get("sources"):
                    continue
                before = (previous or {}).get(key)
                if before and (before.get("value") != decoded["value"] or before.get("state") != decoded["state"]) and not item.get("changed_because", "").strip():
                    continue
            result[key] = decoded
        except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError, SyntaxError):
            continue
    return result


def execute(job: dict, force: bool = False) -> dict:
    raw = runner.pair(job["prompt"], schema(job["keys"]), job["images"], job["id"], force=force)
    answers = {r: decode_answer(v, job) for r, v in raw.items()}
    return {"job": job, "rounds": [raw], "answers": answers,
            "states": {key: runner.compare(answers["claude"].get(key), answers["codex"].get(key)) for key in job["keys"]}}


def run_retry(result: dict, force: bool = False) -> dict:
    keys = [k for k, status in result["states"].items() if status == "disagree"]
    if not keys:
        return result
    job = result["job"]
    first = result["rounds"][0]
    # Only sure-vs-sure disputed fields are exposed in the one governed retry round.
    filtered = {reader: {**raw, "answer": {"items": [v for v in (raw.get("answer") or {}).get("items", []) if v.get("key") in keys]}}
                for reader, raw in first.items()}
    raw = runner.retry_pair(job["prompt"] + "\nOn retry return ONLY these keys: " + ", ".join(keys),
                            schema(keys), job["images"], job["id"], filtered, force=force)
    result["rounds"].append(raw)
    for reader, output in raw.items():
        decoded = decode_answer(output, {**job, "keys": keys}, retry=True, previous=result["answers"][reader])
        for key in keys:
            result["answers"][reader][key] = decoded.get(key)
    for key in keys:
        status = runner.compare(result["answers"]["claude"].get(key), result["answers"]["codex"].get(key))
        result["states"][key] = "agreed_after_retry" if status == "agreed" else status
    return result


def agreed(result: dict, key: str) -> bool:
    return result["states"].get(key) in ("agreed", "agreed_after_retry")


def readers_for(result: dict, key: str) -> dict:
    return {reader: {"rounds": [{"answer": next((v for v in (raw.get(reader, {}).get("answer") or {}).get("items", []) if isinstance(v, dict) and v.get("key") == key), None),
                                "valid": raw.get(reader, {}).get("valid", False),
                                "settings": raw.get(reader, {}).get("settings"),
                                "cache_key": raw.get(reader, {}).get("cache_key")}
                               for raw in result["rounds"]]} for reader in ("claude", "codex")}


def resolved(result: dict, key: str) -> dict:
    accepted = agreed(result, key)
    answer = result["answers"]["claude"].get(key) or {}
    method = "ai_agreed_after_retry" if result["states"].get(key) == "agreed_after_retry" else "ai_agreed"
    return {"state": answer.get("state", "unknown") if accepted else "unknown",
            **({"options": answer["value"]} if accepted and answer.get("state") == "options" else {"value": answer.get("value") if accepted else None}),
            "confidence": "sure" if accepted else "unsure", "method": method if accepted else "ai_unsure",
            "fact_ids": answer.get("fact_ids", []) if accepted else [],
            "readers": readers_for(result, key), "review": copy.deepcopy(REVIEW),
            "note": answer.get("reason") if accepted else f"Waiting for review: {result['states'].get(key, 'invalid')}"}


def assemble(results: list[dict], drawings: dict, exact: dict) -> dict:
    output = {"scans": {}, "links": copy.deepcopy(exact), "mappings": [], "templates": {}, "metrics": {}}
    counts = Counter()
    job_counts: dict[str, Counter] = {}
    actual_review = 0
    scan_undetermined = 0
    for result in results:
        job = result["job"]
        relevant_keys = list(result["states"])
        if job["kind"] == "template":
            shape = (result["answers"]["claude"].get("outline_type") or {}).get("value")
            dimensions = {"rectangle": ("length", "width"), "circle": ("outer_diameter",),
                          "ring": ("outer_diameter", "inner_diameter")}.get(shape, TEMPLATE_KEYS)
            relevant_keys = [k for k in relevant_keys if k in ("outline_type", "thickness", "features") or k in dimensions]
        for key in relevant_keys:
            status = result["states"][key]
            counts[status] += 1
            job_counts.setdefault(job["kind"], Counter())[status] += 1
            if status not in ("agreed", "agreed_after_retry"):
                if job["kind"] == "scan": scan_undetermined += 1
                elif job["kind"] != "mapping": actual_review += 1
        if job["kind"] == "scan":
            did = job["drawing"]
            fields = {}
            for key in job["keys"]:
                value = resolved(result, key)
                source = drawings[did].get("fields", {}).get(key, {})
                fields[key] = {**source, **value, "name": f"{did}/drawing/{key}", "original": None,
                               "page": source.get("page", 1), "box": source.get("box", drawings[did].get("corner_box")),
                               "method": "ai_read" if agreed(result, key) and result["states"][key] == "agreed" else value["method"],
                               "source_quality": "degraded", "note": value["note"] if agreed(result, key) else "Too blurry to read on the scan"}
            output["scans"][did] = {"fields": fields}
        elif job["kind"] == "link":
            value = resolved(result, "link")
            candidates = set()
            for round_ in result["rounds"]:
                for raw in round_.values():
                    for item in (raw.get("answer") or {}).get("items", []):
                        if not isinstance(item, dict): continue
                        candidates.update(ref for ref in item.get("fact_ids", []) if ref in job["row_ids"])
                        try:
                            proposed = json.loads(item.get("value_json", "null"))
                            if isinstance(proposed, list): candidates.update(r for r in proposed if r in job["row_ids"])
                        except (ValueError, TypeError): pass
            output["links"][job["drawing"]] = {"bom_rows": value["value"] or [],
                 "method": value["method"] if agreed(result, "link") else "unresolved",
                 "readers": value["readers"], "review": value["review"], "reason": value["note"],
                 "state": "matched" if agreed(result, "link") else "needs_review", "candidates": sorted(candidates)}
        elif job["kind"] == "mapping":
            value = resolved(result, "relationship")
            output["mappings"].append({"name": job["name"], "kind": job["mapping_kind"], "left": job["left"],
                "right": job["right"], "relationship": value["value"], "method": value["method"],
                "readers": value["readers"], "evidence": "based on general engineering knowledge, not the dataset" if job["mapping_kind"] == "material" else job["evidence"],
                "review": {"status": "pending_approval"}, "reason": value["note"]})
        elif job["kind"] == "template":
            did = job["drawing"]
            values = {key: resolved(result, key) for key in job["keys"]}
            outline_type = values["outline_type"]["value"]
            dimension_keys = {"rectangle": ("length", "width"), "circle": ("outer_diameter",),
                              "ring": ("outer_diameter", "inner_diameter")}.get(outline_type, ())
            outline = {"state": values["outline_type"]["state"], "type": outline_type,
                       **{key: values[key] for key in dimension_keys}}
            features = values["features"]["value"] or []
            # Retain field-level provenance on every feature scalar without altering the geometry.
            for feature in features:
                feature.setdefault("fact_ids", values["features"]["fact_ids"])
            output["templates"][did] = {"part": did, "template": "flat_part", "outline": outline,
                "thickness": values["thickness"], "features": features,
                "features_review": values["features"], "material": drawings[did].get("fields", {}).get("material"),
                "weight_on_drawing": drawings[did].get("fields", {}).get("weight_g"),
                "review": copy.deepcopy(REVIEW), "source_sha256": drawings[did].get("sha256")}
    metrics = {"agreed": counts["agreed"], "agreed_after_retry": counts["agreed_after_retry"],
               "sent_to_review": actual_review, "scan_undetermined": scan_undetermined,
               "mapping_approvals_required": len(output["mappings"]),
               "mapping_suggestions_unsure": sum(v for k, v in job_counts.get("mapping", {}).items()
                                                   if k not in ("agreed", "agreed_after_retry")),
               "status_counts": dict(counts), "by_job": {key: dict(value) for key, value in job_counts.items()},
               "jobs": len(results), "exact_links": len(exact)}
    raw = [v for r in results for round_ in r["rounds"] for v in round_.values()]
    metrics.update({"reader_calls": len(raw), "cache_hits": sum(v.get("cache_hit", False) for v in raw),
                    "provider_calls": sum(not v.get("cache_hit", False) for v in raw),
                    "latency_ms_total": sum(v.get("latency_ms", 0) for v in raw),
                    "configured_readers": {r: runner.reader_settings(r) for r in ("claude", "codex")}})
    output["metrics"] = metrics
    return output


def execute_jobs(jobs: list[dict], force: bool, workers: int, checkpoint=None) -> list[dict]:
    if not jobs: return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, job, force) for job in jobs]
        results = []
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if checkpoint: checkpoint(results)
        return results


def preflight(force: bool = False) -> dict:
    image = "project-meridian_Avathon/project-meridian/dataset/context/diagrams/PowderLegend.png"
    check = {"type": "object", "properties": {"visible_text": {"type": "string"}, "image_seen": {"type": "boolean"}},
             "required": ["visible_text", "image_seen"], "additionalProperties": False}
    outcome = runner.pair("Preflight only. Read the attached diagram and return one short exact visible text label. "
                          "Set image_seen true only if you actually saw image content. Do not modify files.", check, [image], "preflight", force=force, timeout=300)
    runner.write_json(runner.CACHE / "preflight.json", outcome)
    if not all(v.get("valid") and v.get("answer", {}).get("image_seen") for v in outcome.values()):
        raise RuntimeError("Image/JSON preflight failed; inspect generated/ai_cache/preflight.json. No model substitution attempted.")
    return outcome


def run_prep(concurrency: int | None = None, force: bool = False, only: str | None = None) -> dict:
    start = time.monotonic()
    settings = yaml.safe_load((ROOT / "ai_settings.yaml").read_text(encoding="utf-8"))["prep"]
    expected = {"reader_a": {"model": "opus", "fast_mode": False},
                "reader_b": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh", "service_tier": "fast"}}
    if any(settings.get(reader, {}).get(key) != value for reader, fields in expected.items() for key, value in fields.items()):
        raise RuntimeError("ai_settings.yaml must retain Opus regular and gpt-6.1-sol xhigh fast. No silent substitutions.")
    workers = max(1, min(4, settings.get("max_concurrency", 4), concurrency or settings.get("concurrency", 4)))
    runner.bootstrap_auth()
    runner.set_concurrency(workers)
    # Always extract raw source facts. A prior app merge must never become reader evidence.
    from backend.loader.drawings import parse_drawings
    drawings = parse_drawings()
    bom = json.loads((GENERATED / "bom.json").read_text(encoding="utf-8"))
    # Templates are submitted first so CAD can integrate without waiting for matching/mappings.
    templates = [template_job(drawings[did]) for did in PRIMARY_TEMPLATES if did in drawings]
    scans = [scan_job(d) for d in drawings.values() if d.get("degraded")]
    exact = {}
    def checkpoint(partial):
        runner.write_json(GENERATED / "ai_results.json", assemble(partial, drawings, exact))
    results = execute_jobs(templates if only == "templates" else templates + scans, force, workers, checkpoint)
    output = assemble(results, drawings, exact)
    runner.write_json(GENERATED / "ai_results.json", output)
    if only != "templates":
        for did, reading in output["scans"].items():
            drawings[did]["fields"].update(reading["fields"])
        rows = custom_rows(bom)
        for did, drawing in drawings.items():
            match = exact_link(drawing, rows)
            if match: exact[did] = match
        previous = list(results)
        results += execute_jobs([match_job(d, rows) for did, d in drawings.items() if did not in exact], force, workers,
                                lambda partial: checkpoint(previous + partial))
        output = assemble(results, drawings, exact)
        runner.write_json(GENERATED / "ai_results.json", output)
        previous = list(results)
        results += execute_jobs(mapping_jobs(drawings, bom, output["links"]), force, workers,
                                lambda partial: checkpoint(previous + partial))
    # Retry stage is intentionally last and only processes validated sure/sure disagreements.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda r: run_retry(r, force), results))
    if only != "templates":
        # A link first resolved by retry can introduce a new pair needing human mapping approval.
        current = assemble(results, drawings, exact)
        existing = {r["job"]["id"] for r in results}
        missing = [job for job in mapping_jobs(drawings, bom, current["links"]) if job["id"] not in existing]
        additions = execute_jobs(missing, force, workers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results += list(pool.map(lambda r: run_retry(r, force), additions))
    output = assemble(results, drawings, exact)
    output["metrics"]["wall_time_ms"] = round((time.monotonic() - start) * 1000)
    runner.write_json(GENERATED / "ai_results.json", output)
    runner.write_json(runner.CACHE / "artifacts" / "ai_results.json", output)
    runner.write_json(runner.CACHE / "last_run.json", {"metrics": output["metrics"], "jobs": [r["job"]["id"] for r in results]})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "run"], nargs="?", default="run")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", choices=["templates"])
    args = parser.parse_args()
    if args.command == "preflight":
        result = preflight(args.force)
        print(runner.json_text({reader: {"valid": v["valid"], "settings": v["settings"], "answer": v["answer"]} for reader, v in result.items()}))
    else:
        result = run_prep(args.concurrency, args.force, args.only)
        print(runner.json_text(result["metrics"]))


if __name__ == "__main__":
    main()
