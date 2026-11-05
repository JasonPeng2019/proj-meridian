"""Deterministic evidence resolution; chat only puts these results into words."""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.store import AI_METHODS, Store, normalized, read_json

SNAPSHOT_FIELDS = {"supplier", "supplier_order", "cost", "total_cost", "link", "datasheet", "image", "design", "order", "v_v", "vv"}

def trusted(field: dict | None) -> bool:
    return bool(field) and field.get("value") is not None and field.get("confidence", "sure") == "sure" and field.get("review", {}).get("status") != "human_rejected" and field.get("state") != "unknown"

def badge(field: dict) -> str:
    method, review = field.get("method", "parsed"), field.get("review", {})
    if method == "computed_summary":
        return "Computed from recorded source facts"
    if method == "source_inventory":
        return "From source inventory"
    if method == "mapping_status":
        return "Human-reviewed name mapping" if review.get("status") == "human_confirmed" else "Name mapping awaiting review" if review.get("status") != "human_rejected" else "Rejected name mapping"
    if method == "unrecorded_field":
        return "Not determined from the evidence"
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
                "cleanup": field.get("cleanup", []), "note": field.get("note"), "badge": badge(field),
                "source_path": field.get("source_path"), "source_row": field.get("source_row")}

    def row_field(self, row: dict, key: str) -> dict:
        """Resolve current decisions, including canonical rows shared by drawings."""
        original = row.get("fields", {}).get(key, {})
        name = original.get("name")
        if name:
            self.store.fields.setdefault(name, original)
        return self.store.fields.get(name, original)

    def linked_parts(self, row_id: str) -> list[dict]:
        result = []
        for part in self.store.records:
            link = part.get("link") or {}
            # A candidate name is not a proven link. Only the projected linked
            # rows of an accepted link may attach a drawing to BOM evidence.
            if not part.get("drawing") or not trusted(link) or link.get("method") == "unresolved":
                continue
            if row_id in link.get("value", link.get("bom_rows", [])) and any(r["name"] == row_id for r in part.get("bom", [])):
                result.append(part)
        return result

    def derived(self, name: str, value: Any, sources: list[str], *, method: str = "computed_summary", note: str = "", part: dict | None = None, **extra: Any) -> dict:
        field = {"name": name, "value": value, "original": note, "method": method,
                 "confidence": "sure", "fact_ids": list(dict.fromkeys(sources)), "note": note,
                 "compact_sources": len(sources) > 12, **extra}
        self.store.fields[name] = field
        if part:
            self.store.owners[name] = part
        fact = self.display(name, field)
        fact["derivation"] = {"operation": method, "source_fact_ids": field["fact_ids"]}
        return fact

    def display(self, target: str, field: dict | None = None) -> dict:
        field = field if field is not None else self.store.fields[target]
        part = self.store.owners.get(target)
        state = field.get("state")
        value = field.get("selected", field.get("value"))
        if value is None and state == "known" and field.get("type"):
            value = field["type"]
        if state == "options" and field.get("selected") is None:
            display = {"state": "options", "values": [o.get("value") if isinstance(o, dict) else o for o in field.get("options", [])]}
        # Mapping-status facts report the rejection itself, rather than using
        # the rejected relationship as accepted engineering evidence.
        elif (field.get("method") == "mapping_status" and value is not None) or trusted({**field, "value": value}):
            display = {"state": "value", "value": value}
        else:
            message = field.get("note") or field.get("reason")
            if field.get("not_recorded"):
                message = "Not recorded. Raw source: " + repr(field.get("original")) + ". Cleanup: " + ", ".join(field.get("cleanup", [])) + ". " + (message or "")
            if not message:
                message = "Too blurry to read on the scan." if part and (part.get("drawing") or {}).get("degraded") else "Not recorded or not reliably determined from the evidence."
            display = {"state": "undetermined", "message": message}
        sources = [self.source(field, part)]
        for name in field.get("fact_ids", []):
            if name in self.store.fields:
                sources.append(self.source(self.store.fields[name]))
        if field.get("compact_sources"):
            # Aggregate tools need the source identities, not hundreds of
            # repeated crop/null/original metadata records. The server ledger
            # resolves these identities to their full source facts.
            sources = [{k: s[k] for k in ("name", "method", "badge", "source_path", "source_row") if s.get(k) is not None} for s in sources]
        review_item = target if (target.endswith("/link") and field.get("method") == "unresolved") or ("/template/" in target and state == "unknown" and field.get("method") != "human_decision") else None
        linked = list(field.get("related_part_keys", []))
        if target.startswith("BOM:"):
            row_id = next((name for name in self.store.rows if target == name or target.startswith(name + "/")), None)
            linked += [p["key"] for p in self.linked_parts(row_id)] if row_id else []
        return {"fact": target, "field": target.split("/")[-1], "part_key": part.get("key") if part else None,
                "part_keys": linked,
                "display": display, "badge": badge(field), "review": field.get("review"), "sources": sources,
                "snapshot_note": bool(field.get("snapshot_note")) or target.split("/")[-1] in SNAPSHOT_FIELDS,
                "review_item": review_item, "correction": field.get("correction"),
                "callout": ({k: field[k] for k in ("feature", "count", "thread", "thread_class", "through", "width_mm", "length_mm", "radius_mm") if k in field} or None) if trusted(field) and not field.get("correction") else None}

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
            # A source fact and the unresolved cross-source interpretation are
            # different facts. Never overwrite the trusted printed grade in
            # the citation ledger with a mapping-dependent display state.
            result = self.derived(part["key"] + "/resolved/material", None,
                                  [f["name"] for f in [draw, *bom_fields] if f],
                                  part=part, state="unknown", method="unresolved", note=message)
            result["field"] = "material"
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
            if drawing.get("id") and re.search(r"(?<!\w)" + re.escape(drawing["id"]) + r"(?!\w)", text, re.I):
                score = 100
            elif any(normalized(a) == query for a in aliases):
                score = 90
            elif any(query and query in normalized(a) for a in aliases):
                score = 70
            elif any(len(normalized(a)) >= 5 and normalized(a) in query for a in aliases):
                score = 65
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
        model = part.get("model") or {}
        if model.get("weight_check"):
            self.derived(part["key"] + "/model/verification", {
                "weight_check": model["weight_check"], "omitted": model.get("omitted", []),
                "notice": model.get("notice"), "review": model.get("review"),
                "examples": {key: {"selections": value.get("selections"), "volume_mm3": value.get("volume_mm3")}
                             for key, value in model.get("models", {}).items()},
            }, [name for name in (part["key"] + "/drawing/weight_g", part["key"] + "/template/thickness") if name in self.store.fields],
                part=part, note="Computed model verification, not a design approval. Density references are outside sources, not the dataset. Failed checks need manual review; possible readings are never selected by weight.")
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
        return {"name": row_id, "linked_parts": [self.summary(p) for p in self.linked_parts(row_id)],
                "facts": [self.display(f["name"], self.row_field(row, key)) for key, f in row.get("fields", {}).items()]}

    def get_field(self, part_id: str, field: str) -> dict:
        """A missing interpreted field cannot be filled with an unlabeled number."""
        part = self.store.part(part_id)
        key = normalized(field)
        if key == "material":
            fact = self.material(part)
            if fact:
                return {"part": self.summary(part), "facts": [fact]}
        if key in {"holes", "holecount", "holescount", "callouts", "threadedholes", "slots", "slotcount"} or "hole" in key:
            thread = re.search(r"\bm\d+(?:[.,]\d+)?\b", field, re.I)
            thread = thread.group().upper().replace(",", ".") if thread else None
            callouts = []
            for original in (part.get("drawing") or {}).get("callouts", []):
                current = self.store.fields.get(original["name"], original)
                if current.get("feature") != "general_note" and (not thread or str(current.get("thread", "")).upper() == thread):
                    callouts.append(self.display(current["name"], current))
            features = {"slot"} if "slot" in key else {"threaded_hole"} if thread or "threaded" in key else {"hole", "threaded_hole"}
            counts = [f for f in callouts if f["display"]["state"] == "value" and not f.get("correction") and (f.get("callout") or {}).get("feature") in features
                      and isinstance(f["callout"].get("count"), int) and f["callout"]["count"] > 0]
            fact = self.derived(part["key"] + "/drawing/callout-summary/" + key, {"count": sum(f["callout"]["count"] for f in counts), "thread": thread, "scope": "Explicit counted callouts of the requested feature only; holes and slots are separate. This is not a census of all physical features."} if counts else None,
                                [f["fact"] for f in callouts], part=part,
                                note="Only explicit trusted hole counts are summed; unlabeled dimensions and unclassified callouts cannot establish a complete hole count.",
                                state="known" if counts else "unknown")
            return {"part": self.summary(part), "facts": [fact, *callouts]}
        matches = [self.display(name, value) for name, value in self.store.fields.items()
                   if self.store.owners.get(name) is part and normalized(name.split("/")[-1]) == key
                   and "/drawing/n/" not in name and "/features/" not in name]
        if matches:
            return {"part": self.summary(part), "facts": matches}
        sources = [part["id"]]
        if key in {"width", "length", "height", "diameter", "thickness"}:
            sources += [n["name"] for n in (part.get("drawing") or {}).get("numbers", []) if not n.get("label")]
        fact = self.derived(part["id"] + "/unrecorded/" + (key or "field"), None, sources,
                            method="unrecorded_field", part=part, state="unknown", compact_sources=False,
                            note=f"No reliably labeled {field} is recorded. Unlabeled drawing numbers do not identify an edge or feature; do not infer this value.")
        return {"part": self.summary(part), "facts": [fact]}

    def get_connections(self, part_id: str) -> dict:
        part = self.store.part(part_id)
        return {"part": self.summary(part), "connections": part.get("connections", []), "message": "Only recorded Interface with relationships are included. No connections recorded." if not part.get("connections") else "These relationships are recorded in the pinned BOM snapshot.", "facts": [self.display(part["id"])]}

    def parts_in_section(self, section: str) -> dict:
        parts = []
        for part in self.store.records:
            names = [part.get("section")] + [r.get("section") for r in part.get("bom", [])]
            if any(self.relationship(section, n, "section")[0] == "same" for n in names if n):
                parts.append(self.summary(part))
        rows = []
        for row in self.store.rows.values():
            family = self.row_field(row, "part_family")
            recorded_section = family.get("value") if trusted(family) else row.get("section")
            if self.relationship(section, recorded_section, "section")[0] == "same":
                name = self.row_field(row, "name")
                rows.append({"row_id": row["name"], "name": name.get("value"), "section": recorded_section,
                             "facts": [self.display(name["name"], name), self.display(family["name"], family)],
                             "linked_drawing_ids": [p["key"] for p in self.linked_parts(row["name"])]})
        return {"parts": parts, "bom_row_count": len(rows), "bom_rows": rows,
                "mapping_status": self.mapping_status(section, "section"),
                "note": "BOM rows retain their own names and sections even when linked drawings have different names/sections. For parts-list questions use bom_rows and bom_row_count. Differently named drawing sections are combined only after human approval of their mapping."}

    def parts_with_material(self, material: str) -> dict:
        parts = []
        for part in self.store.records:
            evidence = []
            drawing = (part.get("drawing") or {}).get("fields", {}).get("material")
            if drawing and trusted(self.store.fields.get(drawing["name"], drawing)):
                evidence.append(self.store.fields.get(drawing["name"], drawing))
            for row in part.get("bom", []):
                field = row.get("fields", {}).get("material", {})
                field = self.store.fields.get(field.get("name"), field)
                if trusted(field):
                    evidence.append(field)
            matches = []
            for recorded in evidence:
                values = recorded["value"] if isinstance(recorded["value"], list) else [recorded["value"]]
                for value in values:
                    relation, mapping = self.relationship(value, material)
                    grade_match = self.recorded_grade_match(value, material)
                    if grade_match or relation == "same" or (relation == "kind_of" and mapping and normalized(mapping.get("left")) == normalized(value) and normalized(mapping.get("right")) == normalized(material)):
                        matches.append({"recorded_material": value, "relationship": relation,
                                        "source_fact": self.display(recorded["name"], recorded),
                                        "mapping": self.mapping_fact(mapping) if mapping else None,
                                        "grade_token_match": self.derived(recorded["name"] + "/grade-token/" + normalized(material),
                                            {"query": material, "recorded_material": value, "rule": "Exact printed numeric alloy-grade token; a printed temper suffix may be omitted. This does not establish a general material family."},
                                            [recorded["name"]]) if grade_match else None})
            if matches:
                parts.append({**self.summary(part), "material_matches": matches, "material_fact": self.material(part)})
        return {"parts": parts, "mapping_status": self.mapping_status(material, "material"), "note": "Materials recorded, with exact grades preserved. Includes exact source materials and approved kind_of mappings in the specific-to-general direction only. A material list does not establish how each material is used."}

    @staticmethod
    def recorded_grade_match(recorded: Any, query: str) -> bool:
        """Recognize a literal printed grade token, never infer an alloy family."""
        if not isinstance(recorded, str):
            return False
        tokens = re.findall(r"(?<![\w.])(?:\d\.\d{4}|\d{4}(?:-[A-Za-z]\d+)?)(?![\w.])", recorded)
        aliases = {normalized(value) for token in tokens for value in (token, token.split("-", 1)[0])}
        # EN AW is printed grade notation, not an inferred general-material
        # relationship. Match the complete literal notation inside a source.
        aliases.update(normalized(value) for value in re.findall(r"\bEN[\s-]*AW[\s-]*\d{4}(?:-[A-Za-z]\d+)?\b", recorded, re.I))
        return normalized(query) in aliases

    def mapping_fact(self, mapping: dict) -> dict:
        review = mapping.get("review", {})
        approved = review.get("status") == "human_confirmed"
        status = review.get("status", "pending")
        fact = self.derived(mapping["name"], {"kind": mapping.get("kind"), "left": mapping.get("left"), "right": mapping.get("right"),
                            "status": status, "approved_relationship": mapping.get("relationship") if approved else None,
                            "direction": "left is a kind of right" if approved and mapping.get("relationship") == "kind_of" else None},
                            [], method="mapping_status", review=review,
                            note="Approved mappings alone may resolve different names. Pending or rejected proposals do not establish equivalence.")
        fact["mapping_evidence"] = mapping.get("evidence")
        if not approved and status != "human_rejected":
            fact["review_item"] = mapping["name"]
        return fact

    def mapping_status(self, text: str, kind: str = "section") -> dict:
        query = normalized(text)
        mappings = [self.mapping_fact(m) for m in self.store.mappings if (not kind or m.get("kind") == kind)
                    and any(query and (query in normalized(v) or normalized(v) in query) for v in (m.get("name"), m.get("left"), m.get("right")))]
        return {"facts": mappings, "note": "These are current review statuses, not new approvals. Without a human-confirmed same mapping, differently named sections remain separate. Pending items require the Review UI."}

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

    def machine_summary(self) -> dict:
        drawings, families = defaultdict(list), defaultdict(list)
        drawing_sources, row_sources = [], []
        for part in self.store.records:
            drawing = part.get("drawing")
            if not drawing:
                continue
            # This is the source directory section, not an inferred subsystem
            # or the family of a linked BOM row.
            section = drawing.get("section") or part.get("section") or "Unrecorded section"
            value = {"id": part["id"], "key": part["key"], "name": part["display_name"],
                     "source_filename": drawing.get("source_filename"), "section": section}
            source = self.derived(drawing["id"] + "/source-inventory", value, [], method="source_inventory", part=part,
                                  source_path=drawing.get("source_path"), note="Drawing membership in the supplied source inventory; names may be filenames when a printed title is unreadable.")
            drawings[section].append((value, source["fact"]))
            drawing_sources.append(source["fact"])
        for row in self.store.rows.values():
            family_field = self.row_field(row, "part_family")
            family = family_field.get("value") if trusted(family_field) else row.get("section")
            family = str(family or "Unrecorded family")
            name_field = self.row_field(row, "name")
            value = {"row_id": row["name"], "name": name_field.get("value") if trusted(name_field) else row.get("display_name"),
                     "family": family, "linked_drawing_ids": [p["id"] for p in self.linked_parts(row["name"])]}
            owner = self.store.owners.get(name_field.get("name"))
            value["part_keys"] = [p["key"] for p in self.linked_parts(row["name"])] or ([owner["key"]] if owner else [])
            sources = [f["name"] for f in (name_field, family_field) if f.get("name")]
            source = self.derived(row["name"] + "/source-inventory", value, sources, method="source_inventory",
                                  source_path=row.get("source_path"), source_row=row.get("source_row"),
                                  note="One canonical row from the pinned BOM; shared drawing links do not duplicate rows.")
            families[family].append((value, source["fact"]))
            row_sources.append(source["fact"])
        drawing_groups = []
        for index, (section, members) in enumerate(sorted(drawings.items())):
            value = {"section": section, "drawing_count": len(members), "parts": [v for v, _ in members]}
            drawing_groups.append({**value, "summary_fact": self.derived(f"machine/summary/drawing-section/{index}", value, [n for _, n in members], related_part_keys=[v["key"] for v, _ in members])})
        family_groups = []
        for index, (family, members) in enumerate(sorted(families.items())):
            value = {"family": family, "bom_row_count": len(members), "parts": [v for v, _ in members]}
            family_groups.append({**value, "summary_fact": self.derived(f"machine/summary/bom-family/{index}", value, [n for _, n in members], snapshot_note=True,
                                related_part_keys=list(dict.fromkeys(key for v, _ in members for key in v["part_keys"])))})
        totals = {"drawing_count": len(drawing_sources), "bom_row_count": len(row_sources),
                  "drawing_section_count": len(drawings), "bom_family_count": len(families)}
        return {**totals, "drawing_sections": drawing_groups, "bom_families": family_groups,
                "facts": [self.derived("machine/summary/inventory", totals, drawing_sources + row_sources,
                                       related_part_keys=[p["key"] for p in self.store.records if p.get("drawing")])],
                "note": "Counts use actual source sections and canonical BOM families separately. Differently named groups are not merged without an approved mapping; drawing counts are documents, not physical quantities."}

    @staticmethod
    def money(field: dict) -> tuple[Decimal, str] | None:
        value = field.get("value")
        if not trusted(field) or not isinstance(value, dict) or not isinstance(value.get("currency"), str) or not value["currency"].strip():
            return None
        amount = value.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float, str, Decimal)):
            return None
        try:
            number = Decimal(str(amount))
        except InvalidOperation:
            return None
        return (number, value["currency"]) if number.is_finite() else None

    def cost_summary(self) -> dict:
        totals = defaultdict(Decimal)
        included, missing_total, missing_price, missing_quantity, both = [], [], [], [], []
        source_names, included_total_sources = [], []
        for row in self.store.rows.values():
            fields = {key: self.row_field(row, key) for key in ("total_cost", "cost", "amount")}
            source_names.extend(f["name"] for f in fields.values() if f.get("name"))
            money = self.money(fields["total_cost"])
            if money is not None:
                amount, currency = money
                totals[currency] += amount
                included.append(row["name"])
                included_total_sources.append(fields["total_cost"]["name"])
            else:
                missing_total.append(row["name"])
            no_price = self.money(fields["cost"]) is None
            quantity = fields["amount"].get("value")
            no_quantity = not trusted(fields["amount"]) or isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity)
            if no_price:
                missing_price.append(row["name"])
            if no_quantity:
                missing_quantity.append(row["name"])
            if no_price and no_quantity:
                both.append(row["name"])
        value = {"totals_by_currency": [{"currency": currency, "amount": float(total.quantize(Decimal("0.01")))} for currency, total in sorted(totals.items())],
                 "row_count": len(self.store.rows), "rows_included": len(included), "rows_missing_total": len(missing_total),
                 "rows_missing_price": len(missing_price), "rows_missing_quantity": len(missing_quantity),
                 "rows_missing_both_price_and_quantity": len(both),
                 "rows_missing_price_only": len(set(missing_price) - set(missing_quantity)),
                 "rows_missing_quantity_only": len(set(missing_quantity) - set(missing_price))}
        if len(totals) == 1:
            value.update(value["totals_by_currency"][0])
        fact = self.derived("BOM/summary/recorded-cost", value, source_names, snapshot_note=True,
                            note="Sum of trusted canonical recorded row totals, once per BOM row and separately by currency. Missing values are unknown, never free. No unit-price multiplication replaces a missing recorded total.")
        fact["derivation"].update(operation="sum_recorded_row_totals_by_currency", included_total_fact_ids=included_total_sources)
        return {**value, "included_row_ids": included, "missing_total_row_ids": missing_total,
                "missing_price_row_ids": missing_price, "missing_quantity_row_ids": missing_quantity,
                "facts": [fact], "note": "As recorded in the snapshot, may be out of date. Recorded subtotal only, not the complete machine cost or a current quote. Blank prices and quantities are unknown, never zero."}

    def get_overview(self) -> dict:
        machine, cost = self.machine_summary(), self.cost_summary()
        return {"drawing_count": machine["drawing_count"], "bom_row_count": machine["bom_row_count"],
                "drawing_subsystems": [g["section"] for g in machine["drawing_sections"]],
                "bom_families": [g["family"] for g in machine["bom_families"]],
                "machine_summary": machine, "cost_summary": cost,
                "facts": cost["facts"], "note": cost["note"]}

    def propose_correction(self, fact_id: str, new_value: Any, reason: str) -> dict:
        proposal = self.store.propose(fact_id, new_value, reason)
        return {"status": "pending", "review_item": proposal["decision_id"], "target": fact_id, "check_result": proposal["check_result"], "message": "Waiting for human review. This proposal has not changed the accepted facts."}

TOOL_DEFINITIONS = [
    ("find_part", "Find a drawing or BOM part by name or drawing ID; use before part questions.", {"text": "string"}),
    ("get_facts", "Get source-resolved facts for a part, including uncertainty, material, dimensions, procurement and provenance.", {"part_id": "string"}),
    ("get_field", "Get one labeled field, or explicit hole/slot callouts. Missing width or dimensions stay undetermined; never assign an unlabeled number to an edge.", {"part_id": "string", "field": "string"}),
    ("get_bom_row", "Inspect facts of a canonical BOM row.", {"row_id": "string"}),
    ("get_connections", "Get only recorded component interfaces; absence is not evidence of no physical connection.", {"part_id": "string"}),
    ("parts_in_section", "List parts in a subsystem or BOM family using approved section mappings.", {"section": "string"}),
    ("parts_with_material", "Find parts recorded with a material, following approved kind_of mappings in the specific-to-general direction only.", {"material": "string"}),
    ("mapping_status", "Look up current citable mapping/review status by either name. Use kind section or material. Pending/rejected mappings cannot establish equivalence or a material family.", {"text": "string", "kind": "string"}),
    ("search_readme", "Search citable machine context, build volume, laser, safety, or native-CAD availability in the pinned README.", {"text": "string"}),
    ("machine_summary", "Get source section drawing counts and canonical BOM family row counts with compact citable part lists. Drawing source sections and BOM families stay distinct.", {}),
    ("cost_summary", "Get canonical recorded row-total subtotals by currency, included/missing row counts and missing-price/quantity breakdown. Snapshot only, never full current machine cost.", {}),
    ("get_overview", "Get machine organization and computed recorded cost subtotal with missing-price/quantity counts; wrapper around machine_summary and cost_summary.", {}),
    ("propose_correction", "Create a pending correction explicitly requested by the user; cannot approve anything.", {"fact_id": "string", "new_value": "string", "reason": "string"}),
]

def api_tools() -> list[dict]:
    return [{"type": "function", "name": name, "description": desc, "strict": True,
             "parameters": {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": list(props), "additionalProperties": False}}
            for name, desc, props in TOOL_DEFINITIONS]
