"""Small corpus-specific loader. Source files are never changed or downloaded."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from backend.paths import CORPUS, GENERATED, ROOT, inside

HEADERS = {
    "Name": "name", "Part family": "part_family", "Type": "type",
    "Design": "design", "Order": "order", "V&V": "validation",
    "Notes": "notes", "Design Intend": "design_intent", "Image": "image",
    "Material": "material", "Product name": "product_name",
    "Supplier Order": "supplier_order", "Interface with": "interface_with",
    "Link": "link", "Supplier": "supplier", "Datasheet": "datasheet",
    "Amount": "amount", "Cost": "cost", "Total cost": "total_cost",
    "Count (Interface with)": "interface_count",
}
SNAPSHOT_FIELDS = {"supplier", "supplier_order", "product_name", "link", "cost", "total_cost", "image", "datasheet"}
KNOWN_STATES = {
    "design": {"Done", "In progress"},
    "order": {"Basket", "Ordered", "Received", "Todo"},
    "validation": {"Good", "Major modifications", "Not in use", "Slight modifications"},
}
FIELD_NAMES = ("title", "material", "weight_g", "notes", "date", "company", "scale", "drawn")


def slug(text: str) -> str:
    text = text.replace("æ", "ae").replace("Æ", "Ae").replace("ø", "o").replace("Ø", "O")
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "unnamed"


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", slug(text))


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, value: Any) -> None:
    path = inside(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The replacement is atomic; a running reader never sees half of an extraction.
    temporary = inside(path.with_suffix(path.suffix + ".tmp"))
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def clean_cell(original: str, field: str) -> tuple[Any, list[str], list[str]]:
    rules: list[str] = []
    flags: list[str] = []
    value: Any = original
    if value != value.strip():
        value = value.strip()
        rules.append("trim_whitespace")
    if "\\n" in value:
        value = value.replace("\\n", "\n")
        rules.append("literal_newline")
    if not value:
        return None, rules + ["blank_to_null"], flags
    if field in {"cost", "total_cost"}:
        match = re.fullmatch(r"DKK\s*([-+]?\d+(?:[.,]\d+)?)", value)
        if match:
            amount = float(match.group(1).replace(",", "."))
            value = {"amount": amount, "currency": "DKK"}
            rules.append("parse_dkk_price")
            if amount < 0:
                flags.append("negative_price")
        else:
            flags.append("unparsed_price")
    elif field in {"amount", "interface_count"}:
        if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", value):
            parsed = float(value.replace(",", "."))
            value = int(parsed) if parsed.is_integer() else parsed
            rules.append("parse_number")
            if parsed < 0 or (field == "amount" and parsed == 0):
                flags.append("odd_number")
        else:
            flags.append("unparsed_number")
    elif field in KNOWN_STATES:
        if field == "order" and value == "Recieved":
            value = "Received"
            rules.append("status_spelling_Recieved_to_Received")
        if value not in KNOWN_STATES[field]:
            flags.append("unknown_status")
    elif field in {"material", "interface_with"}:
        value = [piece.strip() for piece in value.split(",") if piece.strip()]
        rules.append("split_comma_list")
    elif field in {"image", "datasheet"}:
        # Airtable exports may hold several filename (temporary URL) entries.
        matches = re.findall(r"([^,]+?)\s*\((https?://[^)]+)\)(?:,\s*|$)", value)
        if matches:
            attachments = [{"filename": name.strip(), "url": url} for name, url in matches]
            value = attachments[0] if len(attachments) == 1 else attachments
            rules.append("split_filename_link")
    return value, rules, flags


def parse_bom(source: Path | None = None, output: Path | None = None) -> list[dict]:
    source = source or CORPUS / "dataset/context/openlpbf-bom.csv"
    output = inside(output or GENERATED)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        originals = list(csv.DictReader(stream))
    counts: Counter = Counter()
    flagged: list[dict] = []
    rows: list[dict] = []
    used_names: set[str] = set()
    for index, raw in enumerate(originals, start=1):
        display_id = f"BOM-{index:03d}"
        section = raw["Part family"].strip()
        display_name = raw["Name"].strip()
        stable_name = f"BOM:{slug(section)}/{slug(display_name)}"
        if stable_name in used_names:
            raise ValueError(f"Duplicate stable BOM name: {stable_name}")
        used_names.add(stable_name)
        fields: dict[str, dict] = {}
        for header, original in raw.items():
            field = HEADERS.get(header, slug(header).replace("-", "_"))
            value, rules, flags = clean_cell(original or "", field)
            if header not in HEADERS:
                flags.append("unknown_header")
            for rule in rules:
                counts[rule] += 1
            for flag in flags:
                flagged.append({"row": stable_name, "display_id": display_id, "field": field, "flag": flag, "original": original})
            fields[field] = {
                "name": f"{stable_name}/{field}", "original": original,
                "value": value, "confidence": "sure", "method": "cleanup_rule" if rules else "parsed",
                "header": header, "row": display_id, "cleanup": rules, "flags": flags,
                "not_recorded": value is None,
            }
            if field in SNAPSHOT_FIELDS:
                fields[field]["snapshot_note"] = True
                fields[field]["note"] = "Recorded in the snapshot, may be out of date."
                if field in {"image", "datasheet"} and value:
                    fields[field]["note"] += " Temporary link from the original export, likely expired."
        if fields["cost"]["value"] is None or fields["amount"]["value"] is None:
            total = fields["total_cost"]
            if total["value"] is not None:
                total["value"] = None
                total["not_recorded"] = True
                total["method"] = "cleanup_rule"
                total["cleanup"].append("zero_total_with_blank_cost_or_amount_to_not_recorded")
                counts["zero_total_with_blank_cost_or_amount_to_not_recorded"] += 1
        else:
            cost = fields["cost"]["value"]
            amount = fields["amount"]["value"]
            total = fields["total_cost"]["value"]
            if isinstance(cost, dict) and isinstance(total, dict) and isinstance(amount, (int, float)):
                if not math.isclose(cost["amount"] * amount, total["amount"], abs_tol=0.011):
                    flagged.append({"row": stable_name, "display_id": display_id, "field": "total_cost", "flag": "total_mismatch", "expected": cost["amount"] * amount, "recorded": total["amount"]})
        rows.append({
            "name": stable_name, "display_id": display_id, "display_name": display_name,
            "section": section, "fields": fields, "sha256": sha_json(raw),
            "source": "OPENLPBF-BOM", "source_path": str(source.relative_to(ROOT)).replace("\\", "/") if source.is_relative_to(ROOT) else source.name,
            "source_row": index + 1, "original": raw,
        })
    for i, row in enumerate(rows):
        for other in rows[i + 1:]:
            if row["section"] == other["section"] and SequenceMatcher(None, normalize(row["display_name"]), normalize(other["display_name"])).ratio() >= 0.91:
                flagged.append({"flag": "near_duplicate_name", "rows": [row["name"], other["name"]]})
    report = {
        "rows": len(rows), "rules_changed": dict(counts), "flagged": flagged,
        "source_sha256": sha_file(source),
        "missing_cost_rows": sum(row["fields"]["cost"]["value"] is None for row in rows),
        "interface_rows": sum(bool(row["fields"]["interface_with"]["value"]) for row in rows),
        "recorded_total_dkk": round(sum(row["fields"]["total_cost"]["value"]["amount"] for row in rows if isinstance(row["fields"]["total_cost"]["value"], dict)), 2),
        "warning": "Sum covers recorded prices only; missing costs are unknown, not free. All procurement fields are snapshot evidence.",
    }
    write_json(output / "bom.json", rows)
    write_json(output / "cleanup_report.json", report)
    return rows


def parse_readme(source: Path | None = None, output: Path | None = None) -> list[dict]:
    source = source or CORPUS / "dataset/context/openlpbf-upstream-readme.md"
    output = inside(output or GENERATED)
    text = source.read_text(encoding="utf-8")
    heading = "Introduction"
    paragraphs: list[dict] = []
    section_counts: Counter = Counter()
    buffer: list[str] = []
    image_pattern = re.compile(r"!\[([^\]]*)\]\([^)]+\)|<img\b[^>]*>", re.I)

    def flush() -> None:
        if not buffer:
            return
        content = "\n".join(buffer).strip()
        buffer.clear()
        original = content
        content = image_pattern.sub(lambda m: f"[Image not included in this dataset: {m.group(1) or 'linked upstream image'}]", content)
        content = html.unescape(re.sub(r"<[^>]+>", "", content)).strip()
        if not content:
            return
        section = slug(heading)
        section_counts[section] += 1
        name = f"README/{section}/p{section_counts[section]}"
        unavailable = bool(re.search(r"solidworks|\bstep\b|native cad|CAD files|assembly", content, re.I))
        paragraphs.append({
            "name": name, "id": name, "heading": heading, "section": section,
            "text": content, "value": content, "original": original,
            "method": "parsed", "confidence": "sure", "source": "OPENLPBF-README",
            "sha256": sha_file(source), "snapshot_note": True,
            "mentions_unavailable_files": unavailable,
            "note": "Describes the upstream project as recorded in this snapshot." + (" Native CAD and linked upstream files are not included in this dataset." if unavailable else ""),
        })

    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+)", line)
        if match:
            flush()
            heading = match.group(1).strip()
        elif not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()
    write_json(output / "readme.json", paragraphs)
    return paragraphs


def parse_drawings(output: Path | None = None) -> dict[str, dict]:
    from .drawings import parse_drawings as extract
    return extract(inside(output or GENERATED))


def build_records() -> list[dict]:
    """Rebuild deterministic records and merge cached AI results, never decisions."""
    drawings = parse_drawings()
    rows = parse_bom()
    parse_readme()
    from .records import assemble_records
    return assemble_records(drawings, rows)
