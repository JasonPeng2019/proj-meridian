"""Deterministic evidence resolution; chat only puts these results into words."""
from __future__ import annotations

import json
import re
from typing import Any

from backend.app.store import AI_METHODS, Store, normalized, read_json

SNAPSHOT_FIELDS = {"supplier", "supplier_order", "cost", "total_cost", "link", "datasheet", "image", "design", "order", "v_v", "vv"}

def trusted(field: dict | None) -> bool:
    return bool(field) and field.get("value") is not None and field.get("confidence", "sure") == "sure" and field.get("review", {}).get("status") != "human_rejected" and field.get("state") != "unknown"

def badge(field: dict) -> str:
    method, review = field.get("method", "parsed"), field.get("review", {})
    if method == "human_decision":
        correction = field.get("correction", {})
        return f"Entered by {correction.get('by', 'reviewer')} on {correction.get('at', '')[:10]}"
    if method in AI_METHODS or method.startswith("ai_"):
        label = "AI reading of a blurry scan" if method == "ai_read" else "AI interpretation (agreed after a second look)" if method == "ai_agreed_after_retry" else "AI interpretation"
        if review.get("status") == "human_confirmed":
            return f"{label}, reviewed by {review.get('by')} on {review.get('at', '')[:10]}"
        if review.get("status") == "human_rejected":
            return label + ", rejected by reviewer"
        return label + ", not reviewed"
    if method == "unresolved":
        return "Unresolved evidence"
    if method == "cleanup_rule":
        return "From parts list (cleaned)"
    return "From parts list" if field.get("name", "").startswith("BOM:") else "From README" if field.get("name", "").startswith("README/") else "From PDF"

class KnowledgeTools:
    def __init__(self, store: Store):
        self.store = store

    def source(self, field: dict, part: dict | None = None) -> dict:
        name = field.get("name", "")
        owner = part or self.store.owners.get(name)
        return {"name": name, "says": field.get("original", field.get("value")), "method": field.get("method", "parsed"),
                "page": field.get("page", 1), "box": field.get("box"), "part_key": owner.get("key") if owner else None,
                "cleanup": field.get("cleanup", []), "note": field.get("note"), "badge": badge(field)}

    def display(self, target: str, field: dict | None = None) -> dict:
        field = field if field is not None else self.store.fields[target]
        part = self.store.owners.get(target)
        state = field.get("state")
        value = field.get("selected", field.get("value"))
        if value is None and state == "known" and field.get("type"):
            value = field["type"]
        if state == "options" and field.get("selected") is None:
            display = {"state": "options", "values": [o.get("value") if isinstance(o, dict) else o for o in field.get("options", [])]}
        elif trusted({**field, "value": value}):
            display = {"state": "value", "value": value}
        else:
            message = field.get("note") or field.get("reason")
            if not message:
                message = "Too blurry to read on the scan." if part and (part.get("drawing") or {}).get("degraded") else "Not recorded or not reliably determined from the evidence."
            display = {"state": "undetermined", "message": message}
        sources = [self.source(field, part)]
        for name in field.get("fact_ids", []):
            if name in self.store.fields:
                sources.append(self.source(self.store.fields[name]))
        review_item = target if (target.endswith("/link") and field.get("method") == "unresolved") or ("/template/" in target and state == "unknown" and field.get("method") != "human_decision") else None
        return {"fact": target, "field": target.split("/")[-1], "part_key": part.get("key") if part else None,
                "display": display, "badge": badge(field), "review": field.get("review"), "sources": sources,
                "snapshot_note": bool(field.get("snapshot_note")) or target.split("/")[-1] in SNAPSHOT_FIELDS,
                "review_item": review_item, "correction": field.get("correction")}

    def relationship(self, left: Any, right: Any, kind: str = "material") -> tuple[str | None, dict | None]:
        if normalized(left) == normalized(right):
            return "same", None
        for mapping in self.store.mappings:
            if mapping.get("kind") != kind:
                continue
            a, b = normalized(mapping.get("left")), normalized(mapping.get("right"))
            if {a, b} == {normalized(left), normalized(right)}:
                if mapping.get("review", {}).get("status") != "human_confirmed":
                    return None, mapping
                return mapping.get("relationship"), mapping
        return None, None

    def material(self, part: dict) -> dict | None:
        draw = (part.get("drawing") or {}).get("fields", {}).get("material")
        if draw:
            draw = self.store.fields.get(draw["name"], draw)
        bom_fields = [r.get("fields", {}).get("material") for r in part.get("bom", []) if r.get("fields", {}).get("material")]
        bom_fields = [self.store.fields.get(f["name"], f) for f in bom_fields]
        candidates = [f for f in bom_fields if trusted(f)]
        bom = candidates[0] if candidates else (bom_fields[0] if bom_fields else None)
        if len(candidates) > 1:
            values = []
            for candidate in candidates:
                for value in candidate["value"] if isinstance(candidate["value"], list) else [candidate["value"]]:
                    if value not in values:
                        values.append(value)
            bom = {**bom, "value": values if len(values) > 1 else values[0]}
        base = draw if trusted(draw) else bom if trusted(bom) else draw or bom
        if not base:
            return None
        result = self.display(base["name"], base)
        result["field"] = "material"
        result["sources"] = [self.source(f, part) for f in ([draw] if draw else []) + bom_fields]
        d, b = trusted(draw), trusted(bom)
        if not d and not b:
            return result
        dv, bv = draw.get("value") if d else None, bom.get("value") if b else None
        if not d:
            result["display"] = {"state": "value", "value": "Materials recorded: " + ", ".join(map(str, bv)) if isinstance(bv, list) and len(bv) > 1 else (bv[0] if isinstance(bv, list) else bv)}
            result["badge"] = badge(bom)
            return result
        if not b:
            result["display"] = {"state": "value", "value": dv}
            return result
        values = bv if isinstance(bv, list) else [bv]
        matches = []
        unapproved = None
        for value in values:
            relation, mapping = self.relationship(dv, value)
            if relation in {"same", "kind_of"}:
                specific = mapping.get("left") if relation == "kind_of" and mapping else dv
                matches.append((value, specific))
            elif mapping and mapping.get("review", {}).get("status") != "human_confirmed":
                unapproved = mapping
        if matches:
            if len(values) > 1:
                replacements = {str(a): b for a, b in matches}
                value = "Materials recorded: " + ", ".join(str(replacements.get(str(v), v)) for v in values)
            else:
                value = matches[0][1]
            result["display"] = {"state": "value", "value": value}
        else:
            message = f"Drawing: {dv}. Parts list: {', '.join(map(str, values))}. "
            message += "These names haven't been mapped yet." if not any(self.relationship(dv, v)[0] == "different" for v in values) else "The sources disagree."
            result["display"] = {"state": "undetermined", "message": message}
            result["review_item"] = unapproved.get("name") if unapproved else None
        return result

    def find_part(self, text: str) -> dict:
        query = normalized(text)
        scored = []
        tokens = set(re.findall(r"[\w]+", text.casefold())) - {"the", "part", "what", "is", "of", "a"}
        for part in self.store.records:
            aliases = [part["display_name"], part["key"], part["id"]]
            drawing = part.get("drawing") or {}
            aliases += [str(drawing.get("source_path", ""))]
            aliases += [r.get("display_name", "") for r in part.get("bom", [])]
            if drawing.get("id") and normalized(drawing["id"]) == query:
                score = 100
            elif any(normalized(a) == query for a in aliases):
                score = 90
            elif any(query and query in normalized(a) for a in aliases):
                score = 70
            else:
                words = set(re.findall(r"[\w]+", " ".join(aliases).casefold()))
                score = len(tokens & words) / max(len(tokens), 1) * 40
            if score >= 18:
                scored.append((score, part))
        scored.sort(key=lambda x: (-x[0], x[1]["key"]))
        if scored and scored[0][0] >= 90:
            scored = [v for v in scored if v[0] == scored[0][0]]
        return {"parts": [self.summary(p) for _, p in scored[:12]]}

    @staticmethod
    def summary(part: dict) -> dict:
        return {k: part.get(k) for k in ("id", "key", "display_name", "section", "has_drawing", "has_3d", "examples", "review_status")}

    def get_facts(self, part_id: str) -> dict:
        part = self.store.part(part_id)
        facts = []
        material = self.material(part)
        if material:
            facts.append(material)
        seen = {material["fact"]} if material else set()
        for name, field in self.store.fields.items():
            if self.store.owners.get(name) is not part or name in seen:
                continue
            if "/drawing/n/" in name or name.endswith("/material"):
                continue
            # Include interpreted fields and self-describing callouts, not raw page text.
            facts.append(self.display(name, field))
            seen.add(name)
        for row in part.get("bom", []):
            for field in row.get("fields", {}).values():
                name = field.get("name")
                if name and name not in seen and not name.endswith("/material"):
                    fact = self.display(name, self.store.fields.get(name, field))
                    fact["part_key"] = part["key"]
                    facts.append(fact)
                    seen.add(name)
        numbers = (part.get("drawing") or {}).get("numbers", [])
        return {"part": self.summary(part), "facts": facts, "unlabeled_measurements": [{k: n.get(k) for k in ("name", "value", "page", "box")} for n in numbers if not n.get("label")][:60], "instruction": "Unlabeled numbers do not identify an edge or feature. Do not infer their meaning. Template fields, where present, supply interpreted measurements."}

    def get_bom_row(self, row_id: str) -> dict:
        row = self.store.rows.get(row_id)
        if not row:
            return {"error": "BOM row not found"}
        return {"name": row_id, "facts": [self.display(f["name"], self.store.fields.get(f["name"], f)) for f in row.get("fields", {}).values()]}

    def get_connections(self, part_id: str) -> dict:
        part = self.store.part(part_id)
        return {"part": self.summary(part), "connections": part.get("connections", []), "message": "Only recorded Interface with relationships are included. No connections recorded." if not part.get("connections") else "These relationships are recorded in the pinned BOM snapshot.", "facts": [self.display(part["id"])]}

    def parts_in_section(self, section: str) -> dict:
        parts = []
        for part in self.store.records:
            names = [part.get("section")] + [r.get("section") for r in part.get("bom", [])]
            if any(self.relationship(section, n, "section")[0] == "same" for n in names if n):
                parts.append(self.summary(part))
        return {"parts": parts, "note": "Differently named sections are combined only after human approval of their mapping."}

    def parts_with_material(self, material: str) -> dict:
        parts = []
        for part in self.store.records:
            values = []
            drawing = (part.get("drawing") or {}).get("fields", {}).get("material")
            if drawing and trusted(self.store.fields.get(drawing["name"], drawing)):
                values.append(self.store.fields.get(drawing["name"], drawing)["value"])
            for row in part.get("bom", []):
                field = row.get("fields", {}).get("material", {})
                field = self.store.fields.get(field.get("name"), field)
                value = field.get("value") if trusted(field) else None
                values.extend(value if isinstance(value, list) else [value] if value else [])
            matched = False
            for value in values:
                relation, mapping = self.relationship(value, material)
                if relation == "same" or (relation == "kind_of" and mapping and normalized(mapping.get("right")) == normalized(material)):
                    matched = True
            if matched:
                parts.append({**self.summary(part), "material_fact": self.material(part)})
        return {"parts": parts, "note": "Includes source-recorded materials and approved kind_of mappings. A material list does not establish how each material is used."}

    def search_readme(self, text: str) -> dict:
        passages = read_json(self.store.generated / "readme.json", [])
        terms = set(re.findall(r"[\w]+", text.casefold())) - {"the", "is", "what", "of", "a", "machine"}
        scored = sorted(((sum(t in p.get("text", "").casefold() for t in terms), p) for p in passages), key=lambda pair: -pair[0])
        results = []
        for score, passage in scored[:5]:
            if score <= 0:
                continue
            self.store.fields[passage["name"]] = passage
            results.append({**self.display(passage["name"], passage), "mentions_unavailable_files": passage.get("mentions_unavailable_files"), "heading": passage.get("heading")})
        return {"facts": results, "note": "README describes the pinned upstream snapshot; images/native CAD mentioned there may not be supplied."}

    def get_overview(self) -> dict:
        rows = list(self.store.rows.values())
        total = 0.0
        missing = 0
        source_names = []
        for row in rows:
            original = row.get("fields", {}).get("total_cost", {})
            field = self.store.fields.get(original.get("name"), original)
            value = field.get("value")
            if trusted(field) and isinstance(value, dict) and value.get("amount") is not None:
                total += value["amount"]
                source_names.append(field["name"])
            else:
                missing += 1
        name = "BOM/summary/recorded-cost"
        missing_price = sum(not trusted(self.store.fields.get((r.get("fields", {}).get("cost") or {}).get("name"), r.get("fields", {}).get("cost", {}))) for r in rows)
        field = {"name": name, "value": {"amount": round(total, 2), "currency": "DKK", "rows_missing_price": missing_price, "rows_missing_total": missing}, "method": "cleanup_rule", "confidence": "sure", "original": "Sum of recorded row totals; blank costs are unknown, never free.", "snapshot_note": True}
        self.store.fields[name] = field
        fact = self.display(name, field)
        fact["derivation"] = {"operation": "sum", "source_fact_ids": source_names}
        return {"drawing_count": sum(bool(p.get("drawing")) for p in self.store.records), "bom_row_count": len(rows), "drawing_subsystems": sorted({p["section"] for p in self.store.records if p.get("drawing")}), "bom_families": sorted({r["section"] for r in rows}), "facts": [fact], "note": "Recorded subtotal only, not the complete machine cost or a current quote."}

    def propose_correction(self, fact_id: str, new_value: Any, reason: str) -> dict:
        proposal = self.store.propose(fact_id, new_value, reason)
        return {"status": "pending", "review_item": proposal["decision_id"], "target": fact_id, "check_result": proposal["check_result"], "message": "Waiting for human review. This proposal has not changed the accepted facts."}

TOOL_DEFINITIONS = [
    ("find_part", "Find a drawing or BOM part by name or drawing ID; use before part questions.", {"text": "string"}),
    ("get_facts", "Get source-resolved facts for a part, including uncertainty, material, dimensions, procurement and provenance.", {"part_id": "string"}),
    ("get_bom_row", "Inspect facts of a canonical BOM row.", {"row_id": "string"}),
    ("get_connections", "Get only recorded component interfaces; absence is not evidence of no physical connection.", {"part_id": "string"}),
    ("parts_in_section", "List parts in a subsystem or BOM family using approved section mappings.", {"section": "string"}),
    ("parts_with_material", "Find parts recorded with a material, following approved kind_of mappings in the specific-to-general direction only.", {"material": "string"}),
    ("search_readme", "Search citable machine context, build volume, laser, safety, or native-CAD availability in the pinned README.", {"text": "string"}),
    ("get_overview", "Get machine organization and computed recorded cost subtotal with missing-price count.", {}),
    ("propose_correction", "Create a pending correction explicitly requested by the user; cannot approve anything.", {"fact_id": "string", "new_value": "string", "reason": "string"}),
]

def api_tools() -> list[dict]:
    return [{"type": "function", "name": name, "description": desc, "strict": True,
             "parameters": {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": list(props), "additionalProperties": False}}
            for name, desc, props in TOOL_DEFINITIONS]
