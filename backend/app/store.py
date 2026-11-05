"""Immutable extraction plus append-only, fingerprint-bound review decisions."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backend.paths import ROOT, inside
from backend.app.review_queue import classify_review
from backend.app.review_sources import review_sources
from backend.app.review_values import validate_review_value
from backend.app.review_identity import presented_review

AI_METHODS = {"ai_read", "ai_agreed", "ai_agreed_after_retry", "ai_verified", "ai_verified_after_retry"}

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else copy.deepcopy(default)

def settings() -> dict:
    return yaml.safe_load((ROOT / "ai_settings.yaml").read_text(encoding="utf-8"))

def normalized(value: Any) -> str:
    return re.sub(r"[^\w]", "", str(value or "").casefold())

def prediction_fingerprint(field: dict) -> str:
    """Bind an original AI value, independent of reader receipts and review state."""
    value = {key: field[key] for key in ("state", "value", "options", "selected", "type") if key in field}
    def without_receipts(item):
        if isinstance(item, dict):
            return {key: without_receipts(child) for key, child in item.items()
                    if key not in {"readers", "review", "correction", "name"}}
        if isinstance(item, list):
            return [without_receipts(child) for child in item]
        return item
    return hashlib.sha256(json.dumps(without_receipts(value), sort_keys=True).encode()).hexdigest()


def mapping_source_signature(mapping: dict, drawing_hashes: dict, row_hashes: dict) -> str:
    """Bind a mapping review to source evidence, not mutable AI receipt metadata."""
    basis={"kind":mapping.get("kind"),"left":mapping.get("left"),"right":mapping.get("right"),
           "drawings":drawing_hashes,"bom_rows":row_hashes}
    return hashlib.sha256(json.dumps(basis,sort_keys=True).encode()).hexdigest()

class Store:
    def __init__(self, root: Path = ROOT):
        self.root = inside(root)
        self.generated = self.root / "generated"
        self.decisions_dir = self.root / "decisions"
        self.reload()

    def reload(self, rebuild: bool = False) -> None:
        if rebuild or not (self.generated / "records.json").exists():
            if self.root == ROOT:
                from backend.loader import build_records
                build_records()
        self.records = read_json(self.generated / "records.json", [])
        self.ai = read_json(self.generated / "ai_results.json", {})
        self.templates = copy.deepcopy(self.ai.get("templates", {}))
        for part in self.records:
            if isinstance(part.get("template"), dict):
                self.templates.setdefault(part["drawing"]["id"], part["template"])
        self.mappings = copy.deepcopy(self.ai.get("mappings", []))
        self.models = read_json(self.generated / "models" / "manifest.json", {})
        self.rows = {r["name"]: r for r in read_json(self.generated / "bom.json", [])}
        for part in self.records:
            for row in part.get("bom", []):
                self.rows.setdefault(row["name"], row)
        self.parts = {p["key"]: p for p in self.records}
        self.by_id = {p["id"]: p for p in self.records}
        self.fields: dict[str, dict] = {}
        self.owners: dict[str, dict] = {}
        self.raw_fields: dict[str, dict] = {}
        self.events = []
        if self.decisions_dir.exists():
            self.events = sorted((read_json(p, {}) for p in self.decisions_dir.glob("*.json")), key=lambda e: (e.get("at", ""), e.get("decision_id", "")))
        self.changed = []
        self._index()
        for passage in read_json(self.generated / "readme.json", []):
            self.fields[passage["name"]] = passage
        self.raw_fields = copy.deepcopy(self.fields)
        for event in self.events:
            self._apply(event)
        self._refresh_reviewed_readiness()
        # Link decisions rebuild the part index; keep machine-context citations
        # available even when that projection was refreshed during replay.
        for passage in read_json(self.generated / "readme.json", []):
            self.fields[passage["name"]] = passage
        # Publication can change source interpretations or meshes without a new
        # human event. The browser must observe those complete snapshot changes.
        revision = hashlib.sha256(json.dumps(self.events, sort_keys=True).encode())
        for name in ('records.json', 'ai_results.json', 'bom.json', 'readme.json', 'models/manifest.json'):
            path = self.generated / name
            revision.update(name.encode())
            if path.is_file():
                with path.open('rb') as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                        revision.update(chunk)
        self.revision = revision.hexdigest()[:16]
        for part in self.records:
            drawing = part.get("drawing")
            if drawing:
                did = drawing["id"]
                part["template"] = self.templates.get(did)
                part["model"] = self.models.get(did)
                model = part.get("model") or {}
                part["has_3d"] = bool(model.get("examples")) and not model.get("stale")
                part["examples"] = model.get("examples", [])
                part["weight_check"] = model.get("weight_check")
                tpl = self.templates.get(did, {})
                thickness = tpl.get("thickness", {})
                if thickness.get("selected") is not None:
                    opts = [o.get("value") if isinstance(o, dict) else o for o in thickness.get("options", [])]
                    if thickness["selected"] in opts:
                        part["preferred_example"] = chr(65 + opts.index(thickness["selected"]))
            part["review_status"] = self.part_review_status(part)

    def _refresh_reviewed_readiness(self) -> None:
        """Recheck stale prep blockers after effective human geometry replacements.

        This only validates existing values and all documented alternatives. It
        neither generates geometry nor changes original extraction/reader receipts.
        Already-ready and untouched templates retain their exact metadata.
        """
        for template in self.templates.values():
            if template.get("cad_ready") is not False and not template.get("blocking_fields"):
                continue
            outline = template.get("outline") or {}
            geometry = [template.get("thickness"), outline]
            if isinstance(outline, dict):
                geometry.extend(outline.get(key) for key in (
                    "type", "length", "width", "outer_diameter", "inner_diameter", "diameter"))
            if not any(isinstance(field, dict) and field.get("method") == "human_decision"
                       and field.get("correction") for field in geometry):
                continue
            from backend.cad.builder import Unknown, _options, _validate_essential

            candidate = copy.deepcopy(template)
            candidate.pop("cad_ready", None)
            candidate.pop("blocking_fields", None)
            try:
                if "cad_eligibility" in (template.get("blocking_fields") or []) and not candidate.get("cad_eligibility"):
                    raise Unknown("cad_eligibility is unresolved")
                if any(isinstance(field, dict) and field.get("state") == "bounds" for field in geometry):
                    raise Unknown("Essential geometry has unresolved bounds, not a determined value or discrete alternatives")
                variants = list(_options(candidate))
                if not variants:
                    raise Unknown("No determined geometry alternatives")
                for variant, _ in variants:
                    _validate_essential(variant)
            except (Unknown, ValueError, TypeError, KeyError, AttributeError) as exc:
                template.update(cad_ready=False, blocking_fields=[str(exc)])
            else:
                template.update(cad_ready=True, blocking_fields=[])

    def _index(self) -> None:
        self.fields = {}
        self.owners = {}
        def visit(value: Any, part: dict, prefix: str = "") -> Any:
            if isinstance(value, dict):
                if "state" in value and not value.get("name") and prefix:
                    value["name"] = prefix
                name = value.get("name")
                if name and any(k in value for k in ("value", "original", "state")):
                    if name in self.fields:
                        return self.fields[name]
                    self.fields[name] = value
                    self.owners[name] = part
                for key, child in list(value.items()):
                    if key not in {"readers", "review", "correction"}:
                        value[key] = visit(child, part, f"{prefix}/{key}" if prefix else "")
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    value[i] = visit(child, part, f"{prefix}/{i}" if prefix else "")
            return value
        for part in self.records:
            visit(part.get("drawing"), part)
            part["bom"] = [self.rows.get(row["name"], row) for row in part.get("bom", [])]
            for row in part.get("bom", []):
                visit(row.get("fields"), part)
            drawing = part.get("drawing")
            if drawing:
                did = drawing["id"]
                if did in self.templates:
                    visit(self.templates[did], part, f"{did}/template")
                link = part.setdefault("link", {"method": "unresolved"})
                link.setdefault("name", f"{did}/link")
                link.setdefault("value", [r["name"] for r in part.get("bom", [])])
                link.setdefault("confidence", "sure" if link.get("method") != "unresolved" else "unsure")
                self.fields[link["name"]] = link
                self.owners[link["name"]] = part
            self.fields[part["id"]] = {"name": part["id"], "value": part["display_name"], "method": "parsed", "confidence": "sure"}
            self.owners[part["id"]] = part

    def _refresh_link_view(self) -> None:
        """Project current links without touching the immutable extraction files."""
        from backend.loader.records import connections
        drawings = [part for part in self.records if part.get("drawing")]
        old_bom_parts = {part["bom"][0]["name"]: part for part in self.records if not part.get("drawing") and part.get("bom")}
        linked = set()
        for part in drawings:
            link = part.get("link") or {}
            names = link.get("value", link.get("bom_rows", []))
            if link.get("method") == "unresolved" or link.get("review", {}).get("status") == "human_rejected":
                names = []
            part["bom"] = [self.rows[name] for name in names if name in self.rows]
            linked.update(row["name"] for row in part["bom"])
            part["connections"] = [c for row in part["bom"] for c in connections(row, list(self.rows.values()))]
        standalone = []
        for name, row in self.rows.items():
            if name in linked:
                continue
            family, slug = name[4:].split("/", 1)
            part = old_bom_parts.get(name) or {
                "id": name + "/part", "key": f"bom/{family}/{slug}", "display_name": row["display_name"],
                "section": row["section"], "has_drawing": False, "has_3d": False,
                "examples": [], "drawing": None, "link": None, "template": None,
                "models": {}, "weight_check": None, "mappings": self.mappings,
            }
            part["bom"] = [row]
            part["connections"] = connections(row, list(self.rows.values()))
            standalone.append(part)
        self.records = drawings + standalone
        self.parts = {p["key"]: p for p in self.records}
        self.by_id = {p["id"]: p for p in self.records}
        self._index()
        for passage in read_json(self.generated / "readme.json", []):
            self.fields[passage["name"]] = passage
        self.raw_fields = {name: self.raw_fields.get(name, copy.deepcopy(field)) for name, field in self.fields.items()}

    def fingerprint(self, target: str) -> str:
        if target.startswith("names/"):
            mapping = next((m for m in self.ai.get("mappings", []) if m.get("name") == target), {})
            return hashlib.sha256(json.dumps({k: v for k, v in mapping.items() if k != "review"}, sort_keys=True).encode()).hexdigest()
        part = self.owners.get(target)
        if target.startswith("BOM:"):
            row = next((r for n, r in self.rows.items() if target == n or target.startswith(n + "/")), {})
            return row.get("sha256", "")
        return (part.get("drawing") or {}).get("sha256", "") if part else ""

    def _apply(self, event: dict) -> None:
        target = event.get("applies_to", "")
        fingerprint = event.get("based_on", {}).get("sha256")
        mapping = next((m for m in self.ai.get("mappings", []) if m.get("name") == target), {}) if target.startswith("names/") else {}
        source_signature = mapping_source_signature(mapping,
            {p["drawing"]["id"]:p["drawing"].get("sha256", "") for p in self.records if p.get("drawing")},
            {name:row.get("sha256", "") for name,row in self.rows.items()}) if mapping else None
        unchanged_mapping_source = bool(mapping) and any(
            prior.get("sha256") == fingerprint and prior.get("source_signature") == source_signature
            for prior in mapping.get("prior_proposals", []) if isinstance(prior,dict))
        if fingerprint and fingerprint != self.fingerprint(target) and not unchanged_mapping_source:
            if event.get("status") != "pending":
                self.changed.append(event)
            return
        kind, status = event.get("type"), event.get("status")
        field = self.fields.get(target)
        owner = self.owners.get(target)
        if (kind in {"confirm", "reject"} and event.get("prediction_sha256")
                and event["prediction_sha256"] != prediction_fingerprint(self.raw_fields.get(target, {}))):
            self.changed.append({**event, "change_reason": "AI interpretation changed since review"})
            return
        if owner and owner.get("design_review") and kind in {"correction", "set_value", "choose_option", "link", "reject"} and status == "accepted":
            owner["previous_design_review"] = owner.pop("design_review")
        if kind == "name_mapping" and status in {"accepted", "rejected"}:
            mapping = next((m for m in self.mappings if m.get("name") == target), None)
            if mapping:
                value = event.get("value")
                if status == "accepted":
                    mapping["relationship"] = value.get("relationship") if isinstance(value, dict) else value
                mapping["review"] = {"status": "human_confirmed" if status == "accepted" else "human_rejected", "by": event["by"], "at": event["at"]}
        elif kind == "link" and status == "accepted" and field:
            value = event.get("value") or []
            values = value if isinstance(value, list) else [value]
            part = self.owners[target]
            field.update(value=values, bom_rows=values, method="human_decision", confidence="sure",
                         review={"status": "human_confirmed", "by": event["by"], "at": event["at"]},
                         correction={"original": field.get("value"), "corrected": values, "by": event["by"], "at": event["at"]})
            self._refresh_link_view()
        elif kind in {"correction", "set_value", "choose_option"} and status == "accepted" and field:
            old = field.get("original", field.get("value"))
            value = event.get("value")
            if kind == "choose_option":
                field["selected"] = value
            else:
                # A replacement reading cannot inherit an earlier choice or
                # incompatible bounds. The original lives in raw_fields/history.
                for previous_key in ("selected", "options", "bounds", "min", "max", "minimum", "maximum", "lower", "upper"):
                    field.pop(previous_key, None)
                if isinstance(value, dict) and "state" in value:
                    if value["state"] in {"options", "bounds"}:
                        field.pop("value", None)
                    field.update(value)
                else:
                    field["value"] = value
                    if "state" in field:
                        field["state"] = "known"
            field.update(method="human_decision", confidence="sure", correction={"original": old, "corrected": value, "by": event["by"], "at": event["at"]})
            field["review"] = {"status": "human_confirmed", "by": event["by"], "at": event["at"]}
            if target.endswith("/drawing/title"):
                part = self.owners[target]
                part["display_name"] = str(value)
                self.fields[part["id"]]["value"] = str(value)
        elif kind in {"confirm", "reject"} and field:
            field["review"] = {"status": "human_confirmed" if kind == "confirm" else "human_rejected", "by": event["by"], "at": event["at"]}
            if kind == "reject":
                field["confidence"] = "unsure"
                if target.endswith("/link"):
                    field.update(method="unresolved", value=[], bom_rows=[], reason="The previous link was rejected; choose a BOM row or no match.")
                    field.pop("review", None)
                    self._refresh_link_view()
                elif "/template/" in target:
                    field["state"] = "unknown"
                    field.pop("selected", None)
        elif (kind == "defer_unsupported" and status == "accepted" and field and "/template/" in target
              and field.get("state") == "unknown"):
            # An unavailable reconstruction is not an approval or an invented
            # geometry value. Keep the unknown input and the original evidence.
            field["review"] = {"status": "deferred", "by": event["by"], "at": event["at"],
                               "reason": event.get("note", ""), "review_kind": event.get("review_kind", "human")}
        elif kind == "approve_design":
            part = self.by_id.get(target)
            if part:
                part["design_review"] = {"by": event["by"], "at": event["at"], "note": event.get("note", "")}
        if event.get("review_kind") == "delegated":
            metadata = {"review_kind": "delegated", "display_by": event.get("delegated_by", "Jason Peng") + " - delegated review"}
            if field:
                for key in ("review", "correction"):
                    if (isinstance(field.get(key), dict) and
                            field[key].get("by") == event.get("by") and field[key].get("at") == event.get("at")):
                        field[key].update(metadata)

    def part(self, key: str) -> dict:
        part = self.parts.get(key) or self.by_id.get(key)
        if not part:
            raise KeyError("Part not found")
        return part

    def part_review_status(self, part: dict) -> str:
        if any(self.owners.get(e.get("applies_to")) is part for e in self.pending_changed()):
            return "source_changed"
        if part.get("design_review"):
            return "reviewed"
        return "not_reviewed" if any(f.get("method") in AI_METHODS for n, f in self.fields.items() if self.owners.get(n) is part) else "source_evidence"

    def pending_changed(self) -> list[dict]:
        return [old for old in self.changed if not any(
            event.get("applies_to") == old.get("applies_to") and event.get("at", "") > old.get("at", "")
            and event.get("status") == "accepted" and event.get("based_on", {}).get("sha256") == self.fingerprint(old["applies_to"])
            and (event.get("type") not in {"confirm", "reject"} or not event.get("prediction_sha256")
                 or event["prediction_sha256"] == prediction_fingerprint(self.raw_fields.get(old["applies_to"], {})))
            for event in self.events)]

    def append(self, target: str, kind: str, value: Any = None, status: str = "accepted", note: str = "", **extra: Any) -> dict:
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        event = {"decision_id": "HD-" + uuid.uuid4().hex, "applies_to": target, "type": kind,
                 "value": value, "status": status, "note": note, "by": settings().get("reviewer_name", "Jason Peng"),
                 "at": now(), "based_on": {"sha256": self.fingerprint(target)}, **extra}
        if kind in {"confirm", "reject"}:
            event.setdefault("prediction_sha256", prediction_fingerprint(self.raw_fields.get(target, {})))
        path = inside(self.decisions_dir / (event["decision_id"] + ".json"))
        pending = inside(self.decisions_dir / ("." + event["decision_id"] + ".pending"))
        try:
            with pending.open("x", encoding="utf-8") as handle:
                json.dump(event, handle, ensure_ascii=False, indent=2)
            # Publish complete JSON atomically without replacing any prior file.
            os.link(pending, path)
        finally:
            if pending.exists():
                pending.unlink()
        self.reload()
        return event

    def propose(self, target: str, value: Any, reason: str) -> dict:
        if target not in self.fields:
            raise ValueError("Correction target was not found")
        part = self.owners[target]
        evidence = " ".join(str(f.get("original", f.get("value", ""))) for n, f in self.raw_fields.items() if self.owners.get(n) is part)
        matched = normalized(value) in normalized(evidence)
        check = {"exact_text_match": matched, "message": "Proposed text occurs in the extracted evidence." if matched else "No exact text match. Review the original drawing and linked BOM evidence before accepting.", "evidence_excerpt": evidence[:1800]}
        return self.append(target, "correction", value, "pending", reason, old_value=self.fields[target].get("original", self.fields[target].get("value")), check_result=check, proposed_by="chat user")

    def pending_corrections(self) -> list[dict]:
        resolved = {e.get("proposal_id") for e in self.events if e.get("proposal_id") and e.get("status") in {"accepted", "rejected"}}
        return [e for e in self.events if e.get("type") == "correction" and e.get("status") == "pending" and e["decision_id"] not in resolved]

    def review_items(self) -> list[dict]:
        items = []
        def item(target: str, kind: str, field: dict, **extra: Any) -> dict:
            part = self.owners.get(target)
            return {"id": target, "target": target, "type": kind, "part_key": part.get("key") if part else None,
                    "title": target, "value": field.get("value"), "original": field.get("original"),
                    "status": field.get("review", {}).get("status", "pending"), "readers": field.get("readers", {}),
                    "method": field.get("method"), "options": field.get("options", []),
                    "state": field.get("state"),
                    "evidence": self.evidence_for(target), **extra}
        for proposal in self.pending_corrections():
            target = proposal["applies_to"]
            items.append(item(target, "correction", self.fields.get(target, {}), id=proposal["decision_id"], value=proposal["value"], original=proposal.get("old_value"), reason=proposal.get("note"), check_result=proposal.get("check_result")))
        for mapping in self.mappings:
            items.append({"id": mapping["name"], "target": mapping["name"], "type": "name_mapping", "title": f"{mapping.get('left')} → {mapping.get('right')}", "value": mapping.get("relationship"), "status": mapping.get("review", {}).get("status", "pending"), "readers": mapping.get("readers", {}), "evidence": mapping.get("evidence"), "kind": mapping.get("kind"), "options": ["same", "kind_of", "different", "no_equivalent"]})
        for target, original in self.raw_fields.items():
            current = self.fields[target]
            if target.endswith("/link") and current.get("method") == "unresolved":
                candidates = original.get("candidates", original.get("readers", {}))
                items.append(item(target, "link", current, reason=current.get("reason", "Drawing-to-BOM link is unresolved"), candidates=candidates, rows=[{"name": n, "display_name": r.get("display_name"), "section": r.get("section")} for n, r in self.rows.items() if r.get("fields", {}).get("type", {}).get("value") == "Custom"]))
            elif "/template/" in target and current.get("state") == "unknown" and current.get("method") != "human_decision":
                items.append(item(target, "template", current, reason="Waiting for human input"))
            elif original.get("method") in AI_METHODS and current.get("state") != "options":
                items.append(item(target, "ai_interpretation", current))
            if current.get("state") == "options":
                items.append(item(target, "possible_reading", current, id="options:" + target, selected=current.get("selected")))
        for part in self.records:
            if part.get("has_3d"):
                weight = part.get("weight_check") or {}
                state = str(weight.get("state", weight.get("status", ""))).lower()
                try:
                    self.validate_design(part, "")
                    input_reason = ""
                except ValueError as error:
                    input_reason = str(error)
                items.append(item(part["id"], "ai_interpretation", {}, id="design:" + part["id"], title=part["display_name"] + " — whole design", weight_check=weight, status="human_confirmed" if part.get("design_review") else "not_reviewed", input_reason=input_reason))
                if state in {"failed", "flagged", "flagged_for_review"}:
                    items.append(item(part["id"], "weight", {}, id="weight:" + part["id"], title=part["display_name"] + " — weight check", weight_check=weight, status="human_confirmed" if part.get("design_review") else "pending"))
        for event in self.pending_changed():
            items.append(item(event["applies_to"], "source_changed", {}, id="changed:" + event["decision_id"], value=event.get("value"), reason=event.get("change_reason", "Source changed since approval"), previous_decision=event))
        for entry in items:
            entry["review_queue"], entry["queue_reason"] = classify_review(entry)
            entry["review_label"] = "Human reviewed" if entry["review_queue"] == "resolved" else "Needs human input" if entry["review_queue"] == "human_input" else "Needs human review"
            entry["source_refs"] = review_sources(self, entry)
        return items

    def evidence_for(self, target: str) -> dict:
        part = self.owners.get(target)
        field = self.fields.get(target, {})
        if not part:
            return {}
        return {"part_key": part["key"], "drawing": part.get("drawing"), "bom": part.get("bom", []), "page": field.get("page", 1), "box": field.get("box"), "says": field.get("original", field.get("value"))}

    def act(self, item_id: str, action: str, value: Any = None, note: str = "", *, parser_provenance: dict | None = None) -> dict:
        found = next((i for i in self.review_items() if i["id"] == item_id), None)
        if not found:
            raise KeyError("Review item not found")
        target, kind = found["target"], found["type"]
        parser_metadata = {"input_parser": parser_provenance} if parser_provenance and action == "set_value" else {}
        if kind == "correction":
            if action not in {"accept", "reject"}:
                raise ValueError("A correction must be accepted or rejected")
            event = self.append(target, "correction", found["value"], "accepted" if action == "accept" else "rejected", note, proposal_id=item_id, old_value=found.get("original"), check_result=found.get("check_result"))
            if action == "accept" and "/template/" in target:
                self.rebuild_models([target.split("/")[0]])
        elif kind == "source_changed" and action in {"accept", "set_value"}:
            previous = found["previous_decision"]
            if target not in self.fields and not any(m["name"] == target for m in self.mappings):
                raise ValueError("The original target no longer exists in the current evidence")
            chosen = previous.get("value") if action == "accept" else value
            if action == "set_value":
                chosen = validate_review_value(target, chosen, self.fields.get(target, {}), self.templates.get(target.split("/")[0]))
            if previous["type"] == "approve_design":
                self.validate_design(self.owners[target], note)
            event = self.append(target, previous["type"], chosen, note=note or "Re-approved against changed source evidence", previous_decision_id=previous["decision_id"], **parser_metadata)
            if "/template/" in target:
                self.rebuild_models([target.split("/")[0]])
        elif kind == "name_mapping" and action == "reject":
            event = self.append(target, "name_mapping", found["value"], "rejected", note)
        elif action == "approve_mapping" and kind == "name_mapping":
            value = value or found["value"]
            if value not in {"same", "kind_of", "different", "no_equivalent"}:
                raise ValueError("Choose a valid relationship")
            event = self.append(target, "name_mapping", value, note=note)
        elif action == "approve_design":
            part = self.owners[target]
            self.validate_design(part, note)
            targets = [n for n, f in self.raw_fields.items() if self.owners.get(n) is part and f.get("method") in AI_METHODS]
            for name in targets:
                self.append(name, "confirm", note=note)
            event = self.append(part["id"], "approve_design", note=note)
        elif kind == "link" and action in {"accept", "set_value"}:
            values = value if isinstance(value, list) else ([value] if value else [])
            if any(v not in self.rows for v in values):
                raise ValueError("Unknown BOM row")
            event = self.append(target, "link", values, note=note)
        elif action in {"confirm", "reject"}:
            event = self.append(target, action, note=note)
            if action == "reject" and "/template/" in target:
                self.rebuild_models([target.split("/")[0]])
        elif action in {"set_value", "choose_option"}:
            if action == "choose_option":
                options = [o.get("value") if isinstance(o, dict) else o for o in self.fields[target].get("options", [])]
                if value not in options:
                    raise ValueError("Value is not one of the printed options")
            else:
                value = validate_review_value(target, value, self.fields.get(target, {}), self.templates.get(target.split("/")[0]))
            event = self.append(target, action, value, note=note, **parser_metadata)
            if "/template/" in target:
                self.rebuild_models([target.split("/")[0]])
        else:
            raise ValueError("Action is not valid for this item")
        return {"decision": event, "revision": self.revision, "status": "saved"}

    def validate_design(self, part: dict, note: str) -> None:
        waiting = [n for n, f in self.fields.items() if self.owners.get(n) is part and "/template/" in n and f.get("state") == "unknown" and (f.get("method") != "human_decision" or n.endswith(("/thickness", "/outline")))]
        template = self.templates.get((part.get("drawing") or {}).get("id"), {})
        if template.get("feature_protocol") == "supported-feature-subset-v1" and not (
                template.get("features_complete", {}).get("state") == "known" and
                template.get("features_complete", {}).get("value") is True and
                template.get("features_omitted", {}).get("state") == "known" and
                template.get("features_omitted", {}).get("value") == []):
            waiting.append("incomplete hole/slot inventory")
        if (part.get("link") or {}).get("method") == "unresolved":
            waiting.append("drawing-to-BOM link")
        model=part.get("model") or {}
        if model.get("stale"):
            waiting.append("model requires remote regeneration")
        if model.get("waiting") or any(variant.get("omitted") for variant in model.get("models", {}).values()):
            waiting.append("geometry operations are omitted or unresolved")
        if waiting:
            raise ValueError("Fields still need input: " + ", ".join(waiting))
        weight = part.get("weight_check") or {}
        if str(weight.get("state", weight.get("status", ""))).lower() == "failed" and not note.strip():
            raise ValueError("Approving a FAILED weight check requires a note")

    def rebuild_models(self, part_ids: list[str] | set[str] | tuple[str, ...] | None = None) -> None:
        selected = None
        if part_ids is not None:
            if not isinstance(part_ids, (list, set, tuple)) or any(
                    not isinstance(part_id, str) or not re.fullmatch(r"D-\d{3}", part_id) for part_id in part_ids):
                raise ValueError("CAD refresh requires a collection of drawing IDs")
            selected = set(part_ids)
            unknown = selected - self.templates.keys()
            if unknown:
                raise ValueError("No CAD template for drawing IDs: " + ", ".join(sorted(unknown)))
            if not selected:
                return
        try:
            from backend.cad.builder import build_all
            for part in self.records:
                drawing = part.get("drawing") or {}
                if selected is not None and drawing.get("id") not in selected:
                    continue
                template = self.templates.get(drawing.get("id"))
                if template is not None:
                    template["bom_materials"] = [row["fields"]["material"] for row in part.get("bom", []) if row.get("fields", {}).get("material")]
            build_all(self.templates, allow_generation=os.environ.get("GITHUB_ACTIONS") == "true", part_ids=part_ids)
            self.reload()
        except ImportError:
            for part in self.records:
                if part.get("model") and (selected is None or (part.get("drawing") or {}).get("id") in selected):
                    part["model"]["stale"] = True
                    part["model"]["stale_message"] = "Model out of date: rebuild needed. Showing the version from before this change."

    def history(self, key: str, fact: str | None = None) -> list[dict]:
        part = self.part(key)
        originals = [{"type": "extraction", "applies_to": n, "value": f.get("original", f.get("value")), "method": f.get("method"), "source": self.evidence_for(n)} for n, f in self.raw_fields.items() if self.owners.get(n) is part and (not fact or n == fact)]
        events = [e for e in self.events if self.owners.get(e.get("applies_to")) is part and (not fact or e["applies_to"] == fact)]
        return originals + [presented_review(event) for event in events] + [{"type": "source_changed", "applies_to": e["applies_to"], "at": e.get("at"), "message": "Source changed since approval"} for e in self.changed if self.owners.get(e.get("applies_to")) is part and (not fact or e["applies_to"] == fact)]

    def accuracy(self) -> dict:
        """Score reviewed original AI proposals against current, bound evidence.

        Review completion and a replacement value are not accuracy labels. In
        particular, approving a different mapping rejects the original proposal;
        a subsequent confirmation of a human replacement cannot improve its score.
        """
        reviewer = settings().get("reviewer_name", "Jason Peng")
        mappings = {m["name"]: m for m in self.ai.get("mappings", [])}
        latest, replaced = {}, set()
        excluded = {key: 0 for key in (
            "unauthorized", "not_ai", "stale_source", "unbound_source",
            "stale_prediction", "prior_mapping_proposal", "corrected_replacement", "nonfinal_outcome")}
        for event in self.events:
            name, kind = event.get("applies_to"), event.get("type")
            fingerprint = event.get("based_on", {}).get("sha256")
            current = self.fingerprint(name) if name else ""
            if (kind in {"correction", "set_value", "choose_option", "link"}
                    and event.get("status") == "accepted" and fingerprint and fingerprint == current):
                replaced.add(name)
                # A correction supersedes a prior positive assessment, but an
                # explicit rejection of the original remains a measured failure.
                if latest.get(name, {}).get("outcome") == "confirmed":
                    latest.pop(name)
                    excluded["corrected_replacement"] += 1
                continue
            if kind not in {"confirm", "reject", "name_mapping"}:
                continue
            status = event.get("status")
            if ((kind == "name_mapping" and status not in {"accepted", "rejected"})
                    or (kind != "name_mapping" and status != "accepted")):
                excluded["nonfinal_outcome"] += 1
                continue
            delegated = event.get("review_kind") == "delegated"
            authorized = (event.get("delegated_by") == reviewer if delegated else
                          event.get("by") == reviewer and "automated" not in reviewer.lower())
            if not authorized:
                excluded["unauthorized"] += 1
                continue
            raw = self.raw_fields.get(name, {})
            mapping = mappings.get(name, {}) if kind == "name_mapping" else {}
            if (mapping or raw).get("method") not in AI_METHODS:
                excluded["not_ai"] += 1
                continue
            if not fingerprint or not current:
                excluded["unbound_source"] += 1
                continue
            if fingerprint != current:
                signature = mapping_source_signature(mapping,
                    {p["drawing"]["id"]: p["drawing"].get("sha256", "") for p in self.records if p.get("drawing")},
                    {target: row.get("sha256", "") for target, row in self.rows.items()}) if mapping else None
                compatible_prior = bool(mapping) and any(
                    prior.get("sha256") == fingerprint and prior.get("source_signature") == signature
                    for prior in mapping.get("prior_proposals", []) if isinstance(prior, dict))
                # Legacy prior-proposal receipts retain only hashes, not the
                # original relationship: their effective approvals cannot label
                # a refreshed AI prediction without inventing that old value.
                excluded["prior_mapping_proposal" if compatible_prior else "stale_source"] += 1
                continue
            prediction_sha256 = event.get("prediction_sha256")
            if not mapping and prediction_sha256 and prediction_sha256 != prediction_fingerprint(raw):
                excluded["stale_prediction"] += 1
                continue
            if name in replaced:
                excluded["corrected_replacement"] += 1
                continue
            if mapping:
                value = event.get("value")
                relationship = value.get("relationship") if isinstance(value, dict) else value
                outcome = "confirmed" if status == "accepted" and relationship == mapping.get("relationship") else "rejected"
                job = "mappings"
            else:
                outcome = "confirmed" if kind == "confirm" else "rejected"
                job = "templates" if "/template/" in name else "matching" if name.endswith("/link") else "scans"
            latest[name] = {"outcome": outcome, "job": job, "delegated": delegated,
                            "legacy_prediction_unbound": not mapping and not prediction_sha256}
        jobs = {job: {"confirmed": 0, "rejected": 0} for job in ("scans", "matching", "templates", "mappings")}
        for result in latest.values():
            jobs[result["job"]][result["outcome"]] += 1
        total = sum(sum(v.values()) for v in jobs.values())
        return {"jobs": jobs, "reviewed": total,
                "accuracy": sum(v["confirmed"] for v in jobs.values()) / total if total else None,
                "delegated_reviewed": sum(result["delegated"] for result in latest.values()),
                "legacy_prediction_unbound_reviewed": sum(result["legacy_prediction_unbound"] for result in latest.values()),
                "excluded_decisions": excluded,
                "scope": "current_source_reviewed_original_ai_proposals",
                "note": "Agreement with the latest authorized review of original AI proposals on current source evidence, including authorized delegated reviews. This reviewed sample is not whole-dataset accuracy or design approval. Changed mapping relationships count against the original proposal; corrected replacements and unbound or obsolete source receipts are excluded. Legacy field reviews without a prediction fingerprint are disclosed separately. Exclusion counts refer to decision receipts, not unique proposals.",
                "prep": self.ai.get("metrics", {})}
