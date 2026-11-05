"""M1 snapshot BOM evidence; no network, decisions, or drawing inference.

``load_bom`` returns the frozen BOMRow contracts in CSV order. Display IDs are
1-based source row ordinals, never decision keys. Fields use HEADER_KEYS; each
note retains the verbatim source header because BOMField has no header member.
Row fingerprints cover ordered original header/cell pairs, not row positions.

Cleanup and interface extraction share one CSV pass. The final index lookup
resolves forward references and detects collisions without re-reading cells.
M3's status repairs, attachment splitting, total checks and report are deferred.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from backend.contracts import (
    BOMField,
    BOMRow,
    Confidence,
    ConnectionEvidence,
    Method,
    bom_fact_name,
    bom_part_name,
    bom_row_name,
    normalize_component,
)


DEFAULT_BOM_PATH = (
    Path(__file__).resolve().parents[2]
    / "inputs/project-meridian/dataset/context/openlpbf-bom.csv"
)

# Original spelling and order are evidence. Never silently drop an unknown cell.
HEADER_KEYS = {
    "Name": "name",
    "Part family": "section",
    "Type": "type",
    "Design": "design",
    "Order": "order",
    "V&V": "validation",
    "Notes": "notes",
    "Design Intend": "design_intent",
    "Image": "image",
    "Material": "material",
    "Product name": "product_name",
    "Supplier Order": "supplier_order",
    "Interface with": "interface_with",
    "Link": "link",
    "Supplier": "supplier",
    "Datasheet": "datasheet",
    "Amount": "amount",
    "Cost": "cost",
    "Total cost": "total_cost",
    "Count (Interface with)": "interface_count",
}
SNAPSHOT_NOTE = "Recorded in the snapshot, may be out of date."
TEMPORARY_LINK_NOTE = "Temporary link from the original export, likely expired."
_SNAPSHOT_KEYS = {
    "supplier", "supplier_order", "product_name", "cost", "total_cost", "link",
    "image", "datasheet", "design", "order", "validation",
}
_PRICES = {"cost", "total_cost"}
_NUMBERS = {"amount", "interface_count"}
_LISTS = {"material", "interface_with"}


def _number(text: str, *, price: bool) -> int | float:
    pattern = r"DKK\s*([+-]?\d+(?:\.\d+)?)" if price else r"([+-]?\d+(?:\.\d+)?)"
    match = re.fullmatch(pattern, text)
    if match is None:
        raise ValueError(f"Expected {'DKK price' if price else 'number'}, got {text!r}")
    value = Decimal(match[1])
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("BOM numbers must be finite")
    return result


def _field(header: str, original: str, section: str, name: str) -> BOMField:
    key = HEADER_KEYS[header]
    text = original.strip()
    cleanup = []
    notes = [f"Original header: {header}"]
    if original != text:
        cleanup.append("trim_whitespace")
    value: str | int | float | list[str] | None = text
    if not text:
        value = None
        cleanup.append("blank_to_null")
        notes.append("Not recorded.")
    elif key in _PRICES | _NUMBERS:
        value = _number(text, price=key in _PRICES)
        notes.append("Parsed DKK amount." if key in _PRICES else "Parsed numeric value.")
    elif key in _LISTS:
        value = [item.strip() for item in text.split(",") if item.strip()]
        cleanup.append("split_comma_list")
        if not value:
            value = None
            cleanup.append("empty_list_to_null")
            notes.append("Not recorded.")
        if key == "material":
            notes.append("Recorded material list; composition or variant meaning is not specified.")
    if key in _SNAPSHOT_KEYS:
        notes.append(SNAPSHOT_NOTE)
    if key in {"image", "datasheet"} and "http" in text.lower():
        notes.append(TEMPORARY_LINK_NOTE)
    return BOMField(
        name=bom_fact_name(section, name, key), original=original, value=value,
        method=Method.CLEANUP_RULE if cleanup else Method.PARSED,
        cleanup=cleanup, note=" ".join(notes), snapshot_note=key in _SNAPSHOT_KEYS,
        currency="DKK" if key in _PRICES else None,
    )


def load_bom(source: str | Path = DEFAULT_BOM_PATH) -> list[BOMRow]:
    """Read the supplied CSV into source-separated, unreviewed BOM evidence.

    Duplicate stable names are retained and flagged, never suffixed or selected.
    A consumer must keep the list (or a multi-map), not overwrite colliding rows
    in a dictionary. ``target_part`` is the BOM-only /part identity; drawing links
    belong to the matching/record modules. Connections are directed statements
    from the recorded cell, with no inferred reciprocal or diagram connections.
    """
    # Decode without universal-newline translation so embedded CRLF cells survive.
    text = Path(source).read_bytes().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    headers = next(reader, None)
    if headers != list(HEADER_KEYS):
        raise ValueError("BOM headers differ from the supplied 20-column source; no cells loaded")

    rows: list[BOMRow] = []
    identities: dict[str, list[BOMRow]] = defaultdict(list)
    names: dict[str, list[BOMRow]] = defaultdict(list)
    references: list[ConnectionEvidence] = []
    for ordinal, cells in enumerate(reader, 1):
        if len(cells) != len(headers):
            raise ValueError(f"BOM row {ordinal} has {len(cells)} cells; expected {len(headers)}")
        raw = dict(zip(headers, cells, strict=True))
        section, name = raw["Part family"].strip(), raw["Name"].strip()
        # Fail clearly for unusable identities instead of inventing engineering names.
        stable_name = bom_row_name(section, name)
        fields = {HEADER_KEYS[h]: _field(h, raw[h], section, name) for h in headers}
        total = fields["total_cost"]
        if not raw["Cost"].strip() or not raw["Amount"].strip():
            total.value = None
            total.method = Method.CLEANUP_RULE
            total.cleanup.append("blank_cost_or_amount -> total not recorded")
            total.note += " Total not recorded because Cost or Amount is blank; a source zero is not free."

        interface = fields["interface_with"]
        connections = [
            ConnectionEvidence(
                name=interface.name, original=raw["Interface with"],
                target_name=target, resolved=False,
            )
            for target in (interface.value or [])
        ]
        if not connections:
            interface.note += " No connections recorded."
        row = BOMRow(
            name=stable_name, display_id=f"BOM-{ordinal:03d}",
            display_name=name, section=section,
            source_sha256=hashlib.sha256(json.dumps(
                list(zip(headers, cells, strict=True)), ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            fields=fields, connections=connections,
        )
        rows.append(row)
        identities[stable_name].append(row)
        names[normalize_component(name)].append(row)
        references.extend(connections)

    for candidates in identities.values():
        if len(candidates) > 1:
            displays = ", ".join(row.display_id for row in candidates)
            for row in candidates:
                row.identity_conflict = True
                row.fields["name"].confidence = Confidence.UNSURE
                row.fields["name"].note += f" Stable identity collision: {displays}; do not auto-select."
    for candidates in names.values():
        if len(candidates) > 1:
            displays = ", ".join(row.display_id for row in candidates)
            for row in candidates:
                row.fields["name"].note += f" Ambiguous normalized part name: {displays}."

    for reference in references:
        try:
            candidates = names.get(normalize_component(reference.target_name), [])
        except ValueError:
            candidates = []
        if len(candidates) == 1 and not candidates[0].identity_conflict:
            target = candidates[0]
            reference.target_row = target.name
            reference.target_part = bom_part_name(target.section, target.display_name)
            reference.resolved = True
            reference.note = "Unique normalized BOM name match; recorded interface only."
        elif candidates:
            reference.note = "Ambiguous interface target; no row selected. Candidates: " + ", ".join(
                f"{row.display_id} ({row.name})" for row in candidates
            )
        else:
            reference.note = "No matching BOM row recorded; interface reference remains unresolved."
    return rows
