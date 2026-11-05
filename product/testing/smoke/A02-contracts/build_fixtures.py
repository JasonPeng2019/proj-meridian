"""Deterministically build declared synthetic contract examples, never source facts.

Writes ONLY testing/fixtures/contracts. No journal, prep CLI, source PDF, or app I/O.
"""
from __future__ import annotations

import copy
from decimal import Decimal
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


def provenance(single: bool = False, case: str = "first") -> dict:
    """Generate fictional stage records, never execute a CLI or validate real evidence."""
    case = "fallback" if single else case
    settings = [
        {"provider": "codex_cli", "model": "gpt-6.1-sol", "reasoning": "max", "service_tier": "fast",
         "read_only": True, "settings": {"image_input": True}},
        {"provider": "claude_code", "model": "claude-opus-5-5", "reasoning": "xhigh", "service_tier": "regular",
         "read_only": True, "settings": {"fastMode": False, "fallbackModel": [], "image_input": True}},
    ]
    title = c.drawing_fact_name("D-013", "title")
    name = title if single else c.template_fact_name("D-013", "thickness")
    numbers = [c.drawing_number_name("D-013", text, 1) for text in ("4.25", "1.75")]
    source = c.PrepSourceIdentity(inputs={"synthetic-drawing": digest("D-013")},
                                source_ids={ref: "synthetic-drawing" for ref in [title, *numbers]})
    source_hash = c.contract_digest(source)
    mode = "single_model_unverified" if case == "fallback" else "determine_verify"
    answer = {"state": "known" if single else "options", "value": "Synthetic revised title" if single else None,
              "options": [] if single else [4.25, 1.75], "confidence": "sure", "basis": None if single else "printed_alternatives",
              "source_ids": [title] if single else numbers,
              "schema_valid": True, "evidence_valid": True,
              "reason": "Invented determination; no model was executed and no real source was inspected."}
    if case in {"retry", "persistent", "retry_failure"}:
        answer.update(state="known", value=4.25, options=[], basis=None, source_ids=[numbers[0]])
    if case == "unsupported":
        answer["evidence_valid"] = False
    rounds = []
    previous_candidate = previous_feedback = None
    for index in range(2 if case in {"retry", "persistent", "retry_failure"} else 1):
        if index and case == "retry":
            answer.update(value=1.75, source_ids=[numbers[1]], reason="Invented Sol revision following verifier criticism.")
        fields = {name: c.DeterminedField.model_validate(answer).model_dump(mode="json")}
        candidate = {"source_sha256": source_hash, "fields": fields}
        candidate["candidate_sha256"] = c.contract_digest(candidate)
        cache = {"pipeline_version": c.PREP_PIPELINE_VERSION, "source_sha256": source_hash,
                 "field_names_sha256": c.contract_digest([name]),
                 "output_contract_sha256": digest("output-contract"), "mode": mode}
        sol = {"role": "determination", "requested": settings[0], "effective": settings[0], "status": "success",
               "output": candidate, "started_at": f"2000-01-01T00:00:0{index * 4}+00:00",
               "finished_at": f"2000-01-01T00:00:0{index * 4 + 1}+00:00",
               "cache": {**cache, "role": "determination", "settings": settings[0],
                         "prompt_sha256": digest("determination-prompt"), "candidate_sha256": previous_candidate,
                         "feedback_sha256": previous_feedback}}
        verdict = "disagrees" if case in {"retry", "persistent", "retry_failure"} and (not index or case == "persistent") else (
            "unsure" if case in {"unsure", "unsupported"} else "verified")
        feedback = {"verdict": verdict, "reason": "Invented explicit verdict against fictional original evidence.",
                    "source_ids": [title] if single else numbers, "alternative": None}
        if verdict == "disagrees":
            feedback["alternative"] = {**answer, "value": 1.75, "source_ids": [numbers[1]],
                                       "reason": "Synthetic feedback only; this is not accepted without Sol reconsideration."}
        output = {"candidate_sha256": candidate["candidate_sha256"], "source_sha256": source_hash, "fields": {name: feedback}}
        output["verification_sha256"] = c.contract_digest(output)
        failed = case == "fallback" or (case == "retry_failure" and index == 1)
        invalid = case == "invalid"
        opus = {"role": "verification", "requested": settings[1], "effective": None if failed else settings[1],
                "status": "execution_failed" if failed else "invalid_output" if invalid else "success",
                "candidate_sha256": candidate["candidate_sha256"], "source_sha256": source_hash,
                "output": None if failed or invalid else output,
                "failure": {"classification": "invocation" if failed else "output_schema", "execution_failure": failed,
                            "message": "Synthetic failure only, never a real execution observation.", "exit_code": 99 if failed else 0,
                            "troubleshooting": ["Invented diagnostic; no CLI invocation was performed."],
                            "diagnostic_sha256": digest("synthetic-invalid-diagnostic")} if failed or invalid else None,
                "started_at": f"2000-01-01T00:00:0{index * 4 + 2}+00:00",
                "finished_at": f"2000-01-01T00:00:0{index * 4 + 3}+00:00",
                "cache": {**cache, "role": "verification", "settings": settings[1], "prompt_sha256": digest("verification-prompt"),
                          "candidate_sha256": candidate["candidate_sha256"], "feedback_sha256": None}}
        if case == "observability":
            sol["effective"] = None  # Synthetic unreported metadata, not a failed stage.
            opus["effective"] = {"provider": None, "model": "claude-opus-5-5", "reasoning": None,
                                 "service_tier": "standard", "read_only": None,
                                 "settings": {"fastMode": False, "fallbackModel": None, "image_input": None}}
        for attempt in (sol, opus):
            observed = c.ObservedReaderSettings.model_validate(attempt["effective"]) if attempt["effective"] is not None else None
            attempt["cache"].update(
                settings_basis=c.prep_settings_basis(c.ReaderSettings.model_validate(attempt["requested"]), observed, attempt["role"]),
                effective_sha256=c.contract_digest(observed) if observed is not None else None,
            )
        rounds.append({"round": index + 1, "determination": sol, "verification": opus})
        previous_candidate, previous_feedback = candidate["candidate_sha256"], output["verification_sha256"]
    outcome = "unverified_fallback" if case == "fallback" else "retry_verified" if case == "retry" else (
        "first_pass_verified" if case in {"first", "observability"} else "unresolved")
    return c.PrepProvenance.model_validate({"job": "synthetic-prep", "job_id": "synthetic-" + case,
            "mode": mode, "outcome": outcome, "rounds": rounds, "source": source, "field_names": [name],
            "determination_prompt_sha256": digest("determination-prompt"), "verification_prompt_sha256": digest("verification-prompt"),
            "output_contract_sha256": digest("output-contract")}).model_dump(mode="json")


def number(value: float, index: int) -> dict:
    return {"name": c.drawing_number_name("D-013", str(value), 1), "text": str(value), "value": value,
            "page": 1, "box": [15 + index * 12, 20, 10, 5], "unit": "mm"}


def known(name: str, value, evidence: dict, unit: str | None = "mm") -> dict:
    return {"name": c.template_fact_name("D-013", name), "state": "known", "value": value,
            "method": "parsed", "review": {"status": "not_reviewed"},
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


def summary_fixtures(records: list[dict]) -> None:
    """Invent inputs, then calculate summaries from those records; no benchmark values."""
    records = copy.deepcopy(records)
    for index, price in enumerate(("0.10", "0.20")):
        row_name = c.bom_row_name("Synthetic priced group", f"Synthetic item {index}")
        row = {"name": row_name, "display_id": f"BOM-SYN-PRICE-{index}", "display_name": f"Synthetic item {index}",
               "section": "Synthetic priced group", "source_sha256": digest(row_name), "fields": {
                   key: {"name": row_name + "/" + key, "original": str(value), "value": value, "method": "parsed"}
                   for key, value in (("cost", price), ("amount", 1), ("total_cost", price))}}
        records.append(c.PartRecord.model_validate({**MARKER, "id": row_name + "/part", "display_name": row["display_name"],
                       "section": row["section"], "has_drawing": False, "has_3d": False, "examples": [], "drawing": None,
                       "bom": [row], "link": None, "template": None,
                       "model": {"state": "missing", "message": "Synthetic summary input."}}).model_dump(mode="json"))
    records.sort(key=lambda record: record["id"])
    save("summary-inputs.json", c.SummaryInput, {"records": records})
    snapshot = c.contract_digest(records)
    sources, rows, drawing_groups, bom_groups = {}, {}, {}, {}
    for record in records:
        if record["drawing"]:
            drawing = record["drawing"]
            sources[drawing["id"]] = drawing["source_sha256"]
            section = drawing["fields"].get("section", {}).get("value")
            group = drawing_groups.setdefault(section, {"members": {}, "parts": set()})
            group["members"][drawing["id"]] = {"name": record["id"], "says": record["display_name"], "method": "parsed",
                "source_sha256": drawing["source_sha256"], "target": {"kind": "part", "name": record["id"], "part_id": record["id"]}}
            group["parts"].add(record["id"])
        for row in record["bom"]:
            rows[row["name"]] = row
            sources[row["name"]] = row["source_sha256"]
            group = bom_groups.setdefault(row["section"], {"members": {}, "parts": set()})
            group["members"][row["name"]] = {"name": row["name"], "says": row["display_name"], "method": "parsed",
                "source_sha256": row["source_sha256"], "target": {"kind": "bom", "name": row["name"], "row_name": row["name"]}}
            group["parts"].add(record["id"])
    facts = {}
    groups = []
    for kind, inventory in (("drawing", drawing_groups), ("bom", bom_groups)):
        sections = []
        for section, group in sorted(inventory.items(), key=lambda pair: pair[0] or ""):
            name = f"summary/machine/{kind}/" + (c.normalize_component(section) if section else "unsectioned")
            members = sorted(group["members"])
            facts[name] = {**MARKER, "fact": name, "part_id": None, "display": {"state": "value", "value": len(members)}, "rule": "Unique synthetic source members",
                           "badge": "Synthetic summary fixture", "sources": list(group["members"].values()), "snapshot_note": True}
            sections.append({"section": section, "member_ids": members, "part_ids": sorted(group["parts"]), "count": len(members), "fact": name})
        groups.append(sections)
    save("machine-summary.json", c.MachineSummaryResult, {"records_sha256": snapshot, "source_hashes": sources,
         "record_count": len(records), "drawing_count": sum(s["count"] for s in groups[0]), "bom_row_count": len(rows),
         "drawing_sections": groups[0], "bom_sections": groups[1], "facts": facts})
    recorded, missing, total, cost_sources = [], {}, Decimal("0"), []
    for name, row in sorted(rows.items()):
        fields = row["fields"]
        value = fields.get("total_cost", {}).get("value")
        if value is not None:
            recorded.append(name)
            total += Decimal(str(value))
        else:
            reason = "missing_unit_cost" if fields.get("cost", {}).get("value") is None else (
                "missing_amount" if fields.get("amount", {}).get("value") is None else "missing_total")
            missing.setdefault(reason, []).append(name)
        fact_name = name + "/total_cost"
        cost_sources.append({"name": fact_name, "says": fields["total_cost"]["original"], "method": fields["total_cost"]["method"],
                             "source_sha256": row["source_sha256"], "target": {"kind": "bom", "name": fact_name, "row_name": name}})
    fact_name = "summary/cost/recorded_total"
    money = format(total.quantize(Decimal("0.01")), ".2f")
    fact = {**MARKER, "fact": fact_name, "part_id": None, "display": {"state": "value", "value": money, "unit": "DKK"},
            "rule": "Decimal sum of recorded synthetic total_cost fields; missing rows excluded",
            "badge": "Synthetic summary fixture", "sources": cost_sources, "snapshot_note": True}
    save("cost-summary.json", c.CostSummaryResult, {"records_sha256": snapshot, "source_hashes": sources, "recorded_total": money,
         "recorded_row_names": recorded, "recorded_total_count": len(recorded), "missing_total_count": sum(map(len, missing.values())),
         "row_count": len(rows), "missing_reasons": [{"reason": reason, "row_names": names, "count": len(names)} for reason, names in missing.items()],
         "fact": fact_name, "facts": {fact_name: fact}, "caveat": "Synthetic recorded snapshot; prices may be out of date and missing costs are unknown."})


def history_fixtures(chat: dict, disc: dict) -> None:
    """Invented threads/disk snapshots only; never open a real chat store."""
    def at(second: int) -> str:
        return f"2000-01-01T00:{second // 60:02}:{second % 60:02}+00:00"

    first_text = "Synthetic thread A: show the training bar"
    messages = []
    for turn in range(1, 7):
        reply = copy.deepcopy(chat) if turn == 1 else {**MARKER, "text": f"Synthetic A reply {turn}.",
                "facts": {}, "parts_to_show": [], "warnings": [], "markers": [], "attachment_layout": "none"}
        reply["conversation_id"] = "synthetic-thread-a"
        messages.extend([
            {"id": f"synthetic-a-u{turn}", "role": "user", "text": first_text if turn == 1 else f"Synthetic A question {turn}",
             "created_at": at(turn * 2 - 1)},
            {"id": f"synthetic-a-a{turn}", "role": "assistant", "response": reply, "created_at": at(turn * 2)},
        ])
    thread_a = save("conversation-read-a.json", c.ConversationDetail, {
        "conversation": {"conversation_id": "synthetic-thread-a", "title": first_text, "created_at": at(0), "updated_at": at(12)},
        "messages": messages,
    })
    save("conversation-state-a.json", c.ConversationState, {"detail": thread_a,
         "ledger": {"conversation_id": "synthetic-thread-a", "entries": [{"call_id": "synthetic-call-a", "user_message_id": "synthetic-a-u1",
                    "tool_name": "get_facts", "arguments": {"part_id": "D-013/part"},
                    "result": {**MARKER, "part_id": "D-013/part", "facts": chat["facts"]}}]}})
    part_id = disc["id"]
    fact = {"fact": part_id, "part_id": part_id, "display": {"state": "value", "value": disc["display_name"]},
            "rule": "Synthetic whole-part citation", "badge": "Synthetic fixture", "sources": [
                {"name": part_id, "says": disc["display_name"], "method": "parsed",
                 "target": {"kind": "part", "name": part_id, "part_id": part_id}}]}
    raw = f"[cite: {part_id}]"
    text = f"Synthetic B reply: {raw}."
    thread_b = save("conversation-read-b.json", c.ConversationDetail, {
        "conversation": {"conversation_id": "synthetic-thread-b", "title": "Synthetic thread B: show the training disc",
                         "created_at": at(60), "updated_at": at(62)},
        "messages": [
            {"id": "synthetic-b-u1", "role": "user", "text": "Synthetic thread B: show the training disc", "created_at": at(61)},
            {"id": "synthetic-b-a1", "role": "assistant", "created_at": at(62), "response": {
                **MARKER, "conversation_id": "synthetic-thread-b", "text": text, "facts": {part_id: fact}, "warnings": [],
                "markers": [{"kind": "cite", "names": [part_id], "raw": raw, "start": text.index(raw), "end": text.index(raw) + len(raw), "valid": True}],
                "attachment_layout": "cards", "parts_to_show": [{"id": part_id, "display_name": disc["display_name"],
                    "thumbnail": None, "has_drawing": True, "has_3d": False, "examples": [], "model_state": "blocked",
                    "reason": "citation", "drawing_url": c.image_api_path(part_id)}],
            }},
        ],
    })
    save("conversation-state-b.json", c.ConversationState, {"detail": thread_b,
         "ledger": {"conversation_id": "synthetic-thread-b", "entries": [{"call_id": "synthetic-call-b", "user_message_id": "synthetic-b-u1",
                    "tool_name": "get_facts", "arguments": {"part_id": part_id},
                    "result": {**MARKER, "part_id": part_id, "facts": {part_id: fact}}}]}})
    new = save("conversation-new.json", c.ConversationDetail, {"conversation": {
        "conversation_id": "synthetic-thread-new", "title": "New chat", "created_at": at(120), "updated_at": at(120)}, "messages": []})
    save("conversation-create-request.json", c.ConversationCreateRequest, {})
    save("conversation-list.json", c.ConversationListResponse, {
        "conversations": [new["conversation"], thread_b["conversation"], thread_a["conversation"]]})
    continuation = "Synthetic A continuation: retain this thread only"
    save("conversation-send-request.json", c.ConversationSendRequest, {"message": continuation})
    prior = [{"role": item["role"], "text": item["text"] if item["role"] == "user" else item["response"]["text"]}
             for item in thread_a["messages"]]
    save("conversation-context-a.json", c.ConversationContext, {"conversation_id": "synthetic-thread-a",
         "turns": (prior + [{"role": "user", "text": continuation}])[-10:]})
    response = {**MARKER, "conversation_id": "synthetic-thread-a", "text": "Synthetic A continuation reply.",
                "facts": {}, "parts_to_show": [], "warnings": [], "markers": [], "attachment_layout": "none"}
    save("conversation-send-response.json", c.ConversationSendResponse, {
        "conversation": {**thread_a["conversation"], "updated_at": at(14)},
        "messages": [{"id": "synthetic-a-u7", "role": "user", "text": continuation, "created_at": at(13)},
                     {"id": "synthetic-a-a7", "role": "assistant", "response": response, "created_at": at(14)}],
    })


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
        "part": "D-013", "filled_by": "determine_verify", "source_sha256": digest("D-013"),
        "provenance": provenance(), "outline": outline,
        "thickness": {"name": c.template_fact_name("D-013", "thickness"), "state": "options", "method": "ai_verified",
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
    disc = save("D-025.json", c.PartRecord, {
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
    bom_only = save("bom-only.json", c.PartRecord, {
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
         "review_link": {"id": item["id"], "href": "/debug/review/" + c.encode_id(item["id"])}})
    save("review-action.json", c.ReviewActionRequest, {"action": "reject", "note": "Synthetic rejection example."})
    rejected_item = copy.deepcopy(item)
    rejected_item.update(status="rejected", allowed_actions=[], message="Synthetic proposal rejected; effective title remains unchanged.")
    rejected_decision = copy.deepcopy(pending)
    rejected_decision.update(decision_id="SYN-D-002", status="rejected", by="Synthetic reviewer (fixture only)", supersedes="SYN-D-001")
    save("review-action-response.json", c.ReviewActionResponse, {
        "item": rejected_item, "decisions": [rejected_decision],
        "refresh": {"part_ids": [part_id], "facts": chat["facts"], "models": {part_id: record["model"]}, "warnings": []},
    })
    prep_records = [c.PrepProvenance.model_validate(provenance(case=case)) for case in
                    ("first", "retry", "persistent", "unsure", "invalid", "unsupported", "retry_failure")]
    prep_records.append(c.PrepProvenance.model_validate(provenance(True)))
    save("prep-cases.json", c.PrepBatchResult, {"records": prep_records, "counts": c.prep_counts(prep_records)})
    observed = [c.PrepProvenance.model_validate(provenance(case="observability"))]
    save("prep-observability.json", c.PrepBatchResult, {"records": observed, "counts": c.prep_counts(observed)})
    summary_fixtures([record, disc, bom_only])
    history_fixtures(chat, disc)
    for state in ("configured", "missing_key"):
        save("status-" + state.replace("_", "-") + ".json", c.StatusResponse, {
            "chat_available": state == "configured", "chat_state": state,
            "message": "Synthetic configured-status example; no provider was called." if state == "configured" else
                       "Add an API key to use chat. This is a synthetic missing-key example.", "cad_available": False,
        })
    save("status-debug-enabled.json", c.StatusResponse, {"chat_available": False, "chat_state": "missing_key",
         "message": "Synthetic explicit Debug launch; no runtime launch was performed.", "debug_enabled": True})
    save("error.json", c.ErrorResponse, {"error": {"code": "missing_key", "message": "Synthetic example: chat key is not configured.", "retryable": False}})
    manifest = FixtureManifest.model_validate({**MARKER, "entries": entries, "binary_assets": ["sample.glb", "sample-B.glb"]})
    (DEST / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(entries)} declared synthetic JSON fixtures and two synthetic GLB solids; no real decisions written.")


if __name__ == "__main__":
    main()
