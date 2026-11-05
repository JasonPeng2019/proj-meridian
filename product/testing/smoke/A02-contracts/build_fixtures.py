"""Deterministically build declared synthetic contract examples, never source facts.

Writes ONLY testing/fixtures/contracts. No journal, prep CLI, source PDF, or app I/O.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from development.backend import contracts as c
from check_contracts import FixtureManifest, SyntheticAsset

DEST = ROOT / "testing/fixtures/contracts"
NOTE = "Invented contract fixture only; not dataset evidence, an executed AI run, or a human decision."
MARKER = {"fixture": True, "synthetic": True, "fixture_note": NOTE}
TIME = "2000-01-01T00:00:00+00:00"
entries = []


def digest(label: str) -> str:
    return hashlib.sha256(("A02 SYNTHETIC ONLY: " + label).encode()).hexdigest()


def save(file: str, model: type, data: dict) -> dict:
    value = model.model_validate({**MARKER, **data})
    canonical = value.model_dump(mode="json")
    (DEST / file).write_text(json.dumps(canonical, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    entries.append({"file": file, "model": model.__name__})
    return canonical


def provenance(single: bool = False) -> dict:
    settings = [
        {"provider": "codex_cli", "model": "gpt-6.1-sol", "reasoning": "max", "service_tier": "fast",
         "read_only": True, "settings": {"image_input": True}},
        {"provider": "claude_code", "model": "claude-opus-5-5", "reasoning": "xhigh", "service_tier": "regular",
         "read_only": True, "settings": {"fastMode": False, "fallbackModel": [], "image_input": True}},
    ]
    answer = {"state": "known" if single else "options", "value": "Synthetic revised title" if single else None,
              "options": [] if single else [4.25, 1.75], "confidence": "sure",
              "source_ids": [c.drawing_fact_name("D-013", "title")] if single else
              [c.drawing_number_name("D-013", "4.25", 1), c.drawing_number_name("D-013", "1.75", 1)],
              "reason": "Invented reader output for a declared fixture; no reader was executed."}
    attempts = []
    for index, requested in enumerate(settings):
        failed = single and index == 1
        attempts.append({
            "requested": requested, "effective": None if failed else requested,
            "status": "execution_failed" if failed else "success",
            "output": None if failed else {"answers": {"title" if single else "thickness": answer},
                                             "output_sha256": digest(f"output-{single}-{index}")},
            "failure": {"classification": "invocation", "execution_failure": True,
                        "message": "Simulated Opus execution failure, not a real CLI observation.",
                        "exit_code": 99, "retryable": False,
                        "troubleshooting": ["Synthetic failure example only; no invocation performed."]} if failed else None,
            "started_at": TIME, "finished_at": TIME,
        })
    return {"job": "scan_fixture" if single else "template_fixture", "job_id": "synthetic-single" if single else "synthetic-dual",
            "mode": "single_model" if single else "dual_reader",
            "outcome": "single_model_fallback" if single else "agreed",
            "rounds": [{"round": 1, "sol": attempts[0], "opus": attempts[1]}],
            "inputs": {"synthetic-drawing": digest("D-013")}, "prompt_sha256": digest("prompt"),
            "output_contract_sha256": digest("output-contract"), "cache_key": digest(f"cache-{single}")}


def number(value: float, index: int) -> dict:
    return {"name": c.drawing_number_name("D-013", str(value), 1), "text": str(value), "value": value,
            "page": 1, "box": [15 + index * 12, 20, 10, 5], "unit": "mm"}


def known(name: str, value, evidence: dict, unit: str | None = "mm") -> dict:
    return {"name": c.template_fact_name("D-013", name), "state": "known", "value": value,
            "method": "ai_agreed", "review": {"status": "not_reviewed"}, "provenance": provenance(),
            "evidence": evidence, "unit": unit}


def drawing_field(id: str, name: str, value: str | None, y: float) -> dict:
    return {"name": c.drawing_fact_name(id, name), "original": value, "value": value,
            "confidence": "sure" if value else "unsure", "method": "parsed", "page": 1,
            "box": [12, y, 70, 6], "source_quality": "clean",
            "note": None if value else "Intentionally absent in this synthetic example."}


def glb(size_mm: tuple[float, float, float]) -> bytes:
    # A closed neutral-grey rectangular solid, 24 vertices (separate face normals),
    # 12 outward triangles. glTF units are meters; y is up, z is the CAD width.
    x, z, y = (size_mm[0] / 2000, size_mm[1] / 2000, size_mm[2] / 2000)
    faces = [
        ((0, 0, 1), [(-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]),
        ((0, 0, -1), [(x, -y, -z), (-x, -y, -z), (-x, y, -z), (x, y, -z)]),
        ((1, 0, 0), [(x, -y, z), (x, -y, -z), (x, y, -z), (x, y, z)]),
        ((-1, 0, 0), [(-x, -y, -z), (-x, -y, z), (-x, y, z), (-x, y, -z)]),
        ((0, 1, 0), [(-x, y, z), (x, y, z), (x, y, -z), (-x, y, -z)]),
        ((0, -1, 0), [(-x, -y, -z), (x, -y, -z), (x, -y, z), (-x, -y, z)]),
    ]
    positions, normals, indices = [], [], []
    for face_index, (normal, vertices) in enumerate(faces):
        positions.extend(component for vertex in vertices for component in vertex)
        normals.extend(list(normal) * 4)
        indices.extend(face_index * 4 + index for index in (0, 1, 2, 0, 2, 3))
    position_bytes = struct.pack("<" + "f" * len(positions), *positions)
    normal_bytes = struct.pack("<" + "f" * len(normals), *normals)
    index_bytes = struct.pack("<" + "H" * len(indices), *indices)
    binary = position_bytes + normal_bytes + index_bytes
    document = {
        "asset": {"version": "2.0", "generator": "A02 deterministic synthetic solid fixture", "extras": MARKER},
        "extras": {**MARKER, "size_mm": size_mm, "gltf_units": "meters"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "SYNTHETIC solid; not a dataset reconstruction"}],
        "meshes": [{"name": "Synthetic training solid", "primitives": [
            {"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0, "mode": 4}]}],
        "materials": [{"name": "Neutral grey (does not imply material)", "pbrMetallicRoughness":
                       {"baseColorFactor": [.6, .6, .6, 1], "metallicFactor": 0, "roughnessFactor": .8}}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes), "byteLength": len(normal_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes) + len(normal_bytes), "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3", "min": [-x, -y, -z], "max": [x, y, z]},
            {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_bytes) + 8 + len(binary))
            + struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    numbers = [number(value, index) for index, value in enumerate([37.0, 22.0, 4.25, 1.75])]
    ids = [n["name"] for n in numbers]
    outline = known("outline", {"type": "rectangle",
        "length": known("length", 37, {"number_ids": [ids[0]]}),
        "width": known("width", 11, {"derivation": {"kind": "arithmetic", "expression": "22 / 2 = 11 mm (invented)",
                                                    "inputs": [ids[1]]}})}, {"source_ids": [c.drawing_fact_name("D-013", "title")]}, None)
    outline["essential"] = True
    template = save("flat-template.json", c.FlatTemplate, {
        "part": "D-013", "filled_by": "two_models", "source_sha256": digest("D-013"),
        "provenance": provenance(), "outline": outline,
        "thickness": {"name": c.template_fact_name("D-013", "thickness"), "state": "options", "method": "ai_agreed",
                      "review": {"status": "not_reviewed"}, "provenance": provenance(), "essential": True, "unit": "mm",
                      "options": [{"value": 4.25, "evidence": {"number_ids": [ids[2]]}, "label": "Synthetic A"},
                                  {"value": 1.75, "evidence": {"number_ids": [ids[3]]}, "label": "Synthetic B"}]},
        "features": [{"name": c.template_fact_name("D-013", "unreadable-detail"), "state": "unknown",
                      "method": "unresolved", "confidence": "unsure", "reason": "missing", "essential": False,
                      "message": "Synthetic minor detail intentionally omitted; no dimensions invented."}],
        "finish_notes": ["Synthetic values; not a reading of the real D-013 drawing."],
    })
    row_name = c.bom_row_name("Mock Section", "Synthetic training bar")
    row = {"name": row_name, "display_id": "BOM-SYN-001", "display_name": "Synthetic training bar", "section": "Mock Section",
           "source_sha256": digest("mock-row"), "fields": {
               "material": {"name": row_name + "/material", "original": "Training alloy Q7", "value": "Training alloy Q7", "method": "parsed"},
               "cost": {"name": row_name + "/cost", "original": " ", "value": None, "method": "cleanup_rule",
                        "cleanup": ["trim_blank_to_null"], "currency": "DKK", "snapshot_note": True},
               "amount": {"name": row_name + "/amount", "original": "2", "value": 2, "method": "parsed"},
               "total_cost": {"name": row_name + "/total_cost", "original": "DKK0.00", "value": None, "method": "cleanup_rule",
                              "cleanup": ["zero_total_with_blank_cost -> not recorded"], "currency": "DKK", "snapshot_note": True},
           }}
    examples = []
    for example, file, thickness in [("A", "sample.glb", 4.25), ("B", "sample-B.glb", 1.75)]:
        data = glb((37, 11, thickness))
        (DEST / file).write_bytes(data)
        save("sample-glb.json" if example == "A" else "sample-B-glb.json", SyntheticAsset,
             {"file": file, "media_type": "model/gltf-binary", "sha256": hashlib.sha256(data).hexdigest(),
              "size_mm": [37, 11, thickness], "gltf_units": "meters"})
        examples.append({"id": example, "glb": f"/api/models/D-013_{example}.glb",
                         "choices": {c.template_fact_name("D-013", "thickness"): thickness}, "source_ids": [ids[2 if example == "A" else 3]]})
    record = save("D-013.json", c.PartRecord, {
        "id": "D-013/part", "display_name": "Synthetic training bar", "section": "Mock Section", "has_drawing": True,
        "has_3d": True, "examples": ["A", "B"],
        "drawing": {"id": "D-013", "pages": 1, "image": "images/synthetic-D-013-p1.png",
                    "page_geometry": [{"page": 1, "source_width": 200, "source_height": 100, "image_width": 800, "image_height": 400}],
                    "degraded": False, "source_quality": "clean", "source_path": "SYNTHETIC-D-013.txt", "source_sha256": digest("D-013"),
                    "fields": {"title": drawing_field("D-013", "title", "Synthetic training bar", 70),
                               "material": drawing_field("D-013", "material", "Training polymer P9", 80)}, "numbers": numbers},
        "bom": [row], "link": {"method": "exact_match", "drawing_id": "D-013", "bom_rows": [row_name],
                                "basis": "Invented unique-name link, not a verified dataset connection."},
        "template": "testing/fixtures/contracts/flat-template.json",
        "model": {"state": "available", "examples": examples, "provenance": provenance(),
                  "omitted_details": [{"name": c.template_fact_name("D-013", "unreadable-detail"),
                                       "reason": "Synthetic minor feature intentionally unknown and omitted."}],
                  "built_at": TIME, "built_template_sha256": digest("template"), "current_template_sha256": digest("template")},
    })
    save("D-025.json", c.PartRecord, {
        "id": "D-025/part", "display_name": "Synthetic training disc", "section": None, "has_drawing": True,
        "has_3d": False, "examples": [],
        "drawing": {"id": "D-025", "pages": 1, "image": "images/synthetic-D-025-p1.png",
                    "page_geometry": [{"page": 1, "source_width": 160, "source_height": 90, "image_width": 640, "image_height": 360}],
                    "degraded": False, "source_quality": "clean", "source_path": "SYNTHETIC-D-025.txt", "source_sha256": digest("D-025"),
                    "fields": {"title": drawing_field("D-025", "title", "Synthetic training disc", 70),
                               "material": drawing_field("D-025", "material", None, 80)}},
        "bom": [], "link": {"method": "unresolved", "drawing_id": "D-025", "bom_rows": [], "basis": "Synthetic unlinked example."},
        "template": None, "model": {"state": "blocked", "unresolved_fields": [c.template_fact_name("D-025", "thickness")],
                                      "message": "Cannot build this synthetic example: thickness intentionally unknown."},
    })
    stale = copy.deepcopy(record)
    stale["model"].update(state="stale", stale_reason="Synthetic template edit with builder unavailable; shipped GLBs remain viewable.",
                          current_template_sha256=digest("changed-template"))
    save("D-013-stale.json", c.PartRecord, stale)
    save("bom-only.json", c.PartRecord, {
        "id": row_name + "/part", "display_name": "Synthetic BOM-only bar", "section": "Mock Section", "has_drawing": False,
        "has_3d": False, "examples": [], "drawing": None, "bom": [row], "link": None, "template": None,
        "model": {"state": "missing", "message": "Synthetic BOM-only record: no drawing or model recorded."},
    })
    part_id, fact_id = record["id"], c.drawing_fact_name("D-013", "material")
    drawing_source = {"name": fact_id, "says": "Training polymer P9", "method": "parsed", "source_sha256": digest("D-013"),
                      "target": {"kind": "drawing", "name": fact_id, "part_id": part_id, "drawing_id": "D-013", "page": 1, "box": [12, 80, 70, 6]}}
    bom_source = {"name": row_name + "/material", "says": "Training alloy Q7", "method": "parsed", "source_sha256": digest("mock-row"),
                  "target": {"kind": "bom", "name": row_name + "/material", "part_id": part_id, "row_name": row_name}}
    fact = {"fact": fact_id, "part_id": part_id, "display": {"state": "undetermined", "reason": "source_conflict",
            "message": "Synthetic drawing: Training polymer P9. Synthetic BOM: Training alloy Q7. Invented conflict, no source claim."},
            "rule": "B3 rule 4: conflicting trusted sources", "badge": "From PDF and parts list", "sources": [drawing_source, bom_source]}
    whole_part = {"fact": part_id, "part_id": part_id, "display": {"state": "value", "value": "Synthetic training bar"},
                  "rule": "Whole-part citation", "badge": "Synthetic fixture", "sources": [
                      {"name": part_id, "says": "Synthetic training bar", "method": "parsed",
                       "target": {"kind": "part", "name": part_id, "part_id": part_id}}]}
    text = f"🧪 Synthetic example. Material is [undetermined: {fact_id}]. View the fixture [cite: {part_id}]."
    markers = []
    for kind, name in [("undetermined", fact_id), ("cite", part_id)]:
        raw = f"[{kind}: {name}]"
        start = text.index(raw)
        markers.append({"kind": kind, "names": [name], "raw": raw, "start": start, "end": start + len(raw), "valid": True})
    chat = save("chat-response.json", c.ChatResponse, {
        "text": text, "facts": {fact_id: fact, part_id: whole_part}, "warnings": [], "markers": markers, "attachment_layout": "cards",
        "parts_to_show": [{"id": part_id, "display_name": record["display_name"], "thumbnail": c.image_api_path(part_id, thumb=True),
                           "has_drawing": True, "has_3d": True, "examples": ["A", "B"], "model_state": "available", "reason": "citation",
                           "highlights": [drawing_source["target"]], "drawing_url": c.image_api_path(part_id),
                           "model_urls": {e["id"]: e["glb"] for e in examples}}],
    })
    save("tool-facts.json", c.GetFactsResult, {"part_id": part_id, "facts": chat["facts"]})
    title_id = c.drawing_fact_name("D-013", "title")
    source_title = copy.deepcopy(drawing_source)
    source_title.update(name=title_id, says="Synthetic training bar")
    source_title["target"].update(name=title_id, box=[12, 70, 70, 6])
    check = {"drawing": [{"source_name": title_id, "matched": False, "text": "Synthetic training bar"}],
             "bom": [{"source_name": row_name, "matched": False, "text": "Synthetic training bar"}],
             "message": "Invented replacement text not matched. A string check is not proof or approval."}
    item = save("review-item.json", c.ReviewItem, {
        "id": "review/" + title_id, "kind": "correction", "applies_to": title_id, "part_id": part_id, "status": "pending",
        "title": "Synthetic pending title correction", "message": "Synthetic proposal only; the effective title is unchanged.",
        "current_value": "Synthetic training bar", "proposed_value": "Synthetic revised title", "sources": [source_title],
        "source_hashes": {"D-013": digest("D-013"), row_name: digest("mock-row")}, "ai_answers": provenance(True),
        "check_result": check, "allowed_actions": ["accept", "reject", "set_value"], "proposal_id": "SYN-P-001", "created_at": TIME, "updated_at": TIME,
    })
    pending = save("decision-pending.json", c.Decision, {
        "decision_id": "SYN-D-001", "applies_to": title_id, "type": "correction", "value": "Synthetic revised title",
        "old_value": "Synthetic training bar", "status": "pending", "by": "Synthetic proposer (fixture only)", "at": TIME,
        "based_on": item["source_hashes"], "check_result": check, "reason": "Invented proposal for smoke checks.", "proposal_id": "SYN-P-001",
    })
    save("proposal-result.json", c.ProposeCorrectionResult, {"item": item, "decision": pending,
         "review_link": {"id": item["id"], "href": "/review/" + c.encode_id(item["id"])}})
    save("review-action.json", c.ReviewActionRequest, {"action": "reject", "note": "Synthetic rejection example."})
    rejected_item = copy.deepcopy(item)
    rejected_item.update(status="rejected", allowed_actions=[], message="Synthetic proposal rejected; effective title remains unchanged.")
    rejected_decision = copy.deepcopy(pending)
    rejected_decision.update(decision_id="SYN-D-002", status="rejected", by="Synthetic reviewer (fixture only)", supersedes="SYN-D-001")
    save("review-action-response.json", c.ReviewActionResponse, {
        "item": rejected_item, "decisions": [rejected_decision],
        "refresh": {"part_ids": [part_id], "facts": chat["facts"], "models": {part_id: record["model"]}, "warnings": []},
    })
    for state in ("configured", "missing_key"):
        save("status-" + state.replace("_", "-") + ".json", c.StatusResponse, {
            "chat_available": state == "configured", "chat_state": state,
            "message": "Synthetic configured-status example; no provider was called." if state == "configured" else
                       "Add an API key to use chat. This is a synthetic missing-key example.", "cad_available": False,
        })
    save("error.json", c.ErrorResponse, {"error": {"code": "missing_key", "message": "Synthetic example: chat key is not configured.", "retryable": False}})
    manifest = FixtureManifest.model_validate({**MARKER, "entries": entries, "binary_assets": ["sample.glb", "sample-B.glb"]})
    (DEST / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(entries)} declared synthetic JSON fixtures and two synthetic GLB solids; no real decisions written.")


if __name__ == "__main__":
    main()
