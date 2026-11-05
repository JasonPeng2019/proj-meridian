"""Combine extracted evidence and cached AI results. Human decisions live in app."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote

from backend.paths import GENERATED
from .build import normalize, read_json, slug, write_json


def attachments(field):
    value = field.get("value")
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def exact_link(drawing, rows):
    filename = normalize(Path(drawing.get("source_filename", "")).stem)
    candidates = [row["name"] for row in rows if any(
        normalize(Path(unquote(item.get("filename", ""))).stem) == filename
        for item in attachments(row["fields"].get("datasheet", {})))]
    reason = "Unique datasheet filename match."
    if not candidates:
        title = drawing.get("fields", {}).get("title", {})
        if title.get("confidence") == "sure" and title.get("value"):
            candidates = [row["name"] for row in rows if normalize(row["display_name"]) == normalize(str(title["value"]))]
            reason = "Unique normalized drawing title and BOM name match."
    if len(candidates) == 1:
        return {"bom_rows": candidates, "method": "exact_match", "reason": reason}
    return {"bom_rows": [], "method": "unresolved", "reason": "No unique exact match; waiting for AI matching or human review.", "candidates": candidates}


def connections(row, all_rows):
    field = row["fields"]["interface_with"]
    values = field.get("value") or []
    if not isinstance(values, list):
        values = [values]
    result = []
    for text in values:
        matches = [other["name"] for other in all_rows if normalize(other["display_name"]) == normalize(text)]
        result.append({"target": matches[0] if len(matches) == 1 else None,
                       "text": text, "source": field["name"], "method": "parsed"})
    return result


def assemble_records(drawings: dict, rows: list, output: Path = GENERATED) -> list:
    drawings = deepcopy(drawings)
    ai_path = output / "ai_results.json"
    cached_ai = output / "ai_cache/artifacts/ai_results.json"
    if not ai_path.exists() and cached_ai.exists():
        write_json(ai_path, read_json(cached_ai, {}))
    ai = read_json(ai_path, {})
    # Image-only dimension readings are separate verified evidence. Never add AI
    # readings to drawings.json or present them as deterministic PDF extraction.
    from backend.ai.dimensions import attach as attach_dimensions
    drawings = {did: attach_dimensions(drawing, ai.get("dimension_evidence", {}).get(did))
                for did, drawing in drawings.items()}
    manifest = read_json(output / "models/manifest.json", {})
    row_lookup = {row["name"]: row for row in rows}
    linked = set()
    records = []
    for drawing_id, drawing in drawings.items():
        if drawing["degraded"]:
            readings = ai.get("scans", {}).get(drawing_id, {}).get("fields", {})
            for field_name, reading in readings.items():
                if field_name not in drawing["fields"] or not isinstance(reading, dict):
                    continue
                base = drawing["fields"][field_name]
                merged = {**base, **reading, "name": base["name"], "page": base["page"], "box": base["box"], "source_quality": "degraded"}
                merged["original"] = reading.get("original", reading.get("value"))
                if reading.get("confidence") != "sure" or not str(reading.get("method", "")).startswith("ai_"):
                    merged.update(value=None, confidence="unsure", note="Too blurry to read on the scan.")
                drawing["fields"][field_name] = merged
            drawing["page_fields"]["1"] = deepcopy(drawing["fields"])
        link = deepcopy(ai.get("links", {}).get(drawing_id) or exact_link(drawing, rows))
        requested = link.get("bom_rows", [])
        if not isinstance(requested, list):
            requested = []
        invalid = [name for name in requested if name not in row_lookup]
        allowed = link.get("method") in {"exact_match", "ai_agreed", "ai_agreed_after_retry", "ai_verified", "ai_verified_after_retry"}
        selected = [] if invalid or not allowed else [row_lookup[name] for name in requested]
        if invalid:
            link.update(method="unresolved", reason="AI returned an invalid BOM stable name.", invalid_rows=invalid)
        link["bom_rows"] = [row["name"] for row in selected]
        link["name"] = f"{drawing_id}/link"
        link["drawing"] = drawing_id
        if link.get("method", "").startswith("ai_"):
            link.setdefault("review", {"status": "not_reviewed"})
        linked.update(row["name"] for row in selected)
        title = drawing["fields"].get("title", {})
        display = str(title["value"]) if title.get("confidence") == "sure" and title.get("value") else drawing["source_filename"]
        template = None if drawing["degraded"] else ai.get("templates", {}).get(drawing_id)
        model = manifest.get(drawing_id, {}) if not drawing["degraded"] else {}
        examples = model.get("examples", [])
        records.append({"id": f"{drawing_id}/part", "key": drawing_id, "display_name": display,
                        "section": drawing.get("section"), "has_drawing": True, "has_3d": bool(model.get("models")),
                        "examples": examples, "drawing": drawing, "bom": selected, "link": link,
                        "connections": [connection for row in selected for connection in connections(row, rows)],
                        "template": template, "models": model.get("models", {}), "model_manifest": model,
                        "weight_check": model.get("weight_check"), "mappings": ai.get("mappings", [])})
    for row in rows:
        if row["name"] in linked:
            continue
        family, name = row["name"][4:].split("/", 1)
        records.append({"id": f"{row['name']}/part", "key": f"bom/{family}/{name}",
                        "display_name": row["display_name"], "section": row["section"],
                        "has_drawing": False, "has_3d": False, "examples": [], "drawing": None,
                        "bom": [row], "link": None, "connections": connections(row, rows),
                        "template": None, "weight_check": None, "models": {}, "mappings": ai.get("mappings", [])})
    # drawings.json is the deterministic prep input, never an AI-result store.
    # Scan readings belong only to the deep-copied drawing inside each record.
    write_json(output / "records.json", records)
    return records
