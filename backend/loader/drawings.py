"""Positional extraction for the supplied drawing layout; no OCR or inference."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from backend.paths import CORPUS, GENERATED, ROOT, inside
from .build import sha_file, write_json

LAYOUT = json.loads(Path(__file__).with_name("corner_layout.json").read_text(encoding="utf-8"))


def box(rect) -> list[float]:
    r = fitz.Rect(rect)
    return [round(r.x0, 3), round(r.y0, 3), round(r.width, 3), round(r.height, 3)]


def rect(value):
    x, y, w, h = value
    return fitz.Rect(x, y, x + w, y + h)


def unique_words(page) -> list[tuple]:
    # Repeated layers vary by a few thousandths of a PDF point.
    result = []
    for word in page.get_text("words"):
        if not any(word[4] == old[4] and all(abs(word[i] - old[i]) < .1 for i in range(4)) for old in result):
            result.append(word)
    return result


def join_words(words) -> str:
    lines = []
    for word in sorted(words, key=lambda w: (round(w[1] / 3), w[0])):
        if lines and abs(lines[-1][0][1] - word[1]) < 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return "\n".join(" ".join(w[4] for w in sorted(line, key=lambda w: w[0])) for line in lines)


def fields_for_page(drawing_id, page, words, degraded=False):
    width, height = page.rect.width, page.rect.height
    sx, sy = width / LAYOUT["reference_size"][0], height / LAYOUT["reference_size"][1]
    fields = {}
    for name, config in LAYOUT["fields"].items():
        label = next((w for w in words if w[4].startswith(config["label"]) and w[0] > width * .6 and w[1] > height * .7), None)
        fallback = config["fallback"]
        area = rect([fallback[0] * sx, fallback[1] * sy, fallback[2] * sx, fallback[3] * sy])
        if degraded:
            # Skewed/cropped scan variants shift text several points. Cite a
            # padded field region rather than pretend to know word positions.
            area = fitz.Rect(area.x0 - 5, area.y0 - 5, area.x1 + 5, area.y1 + 5) & page.rect
        if label and not config.get("inline"):
            ox, oy, fw, fh = config["offset"]
            area = fitz.Rect(label[0] + ox, label[1] + oy, label[0] + ox + fw, label[1] + oy + fh)
        chosen = [w for w in words if area.contains(fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)) and w is not label]
        raw = join_words(chosen).strip() if label else ""
        if label and config.get("inline"):
            raw = label[4][len(config["label"]):]
            area = fitz.Rect(label[:4])
        # Capture full material text even when it spills into the next label,
        # but flag it rather than treating overlapped text as a reliable value.
        overlap = False
        if label and name == "material":
            next_label = next((w for w in words if w[4] == "WEIGHT"), None)
            if next_label:
                spill = [w for w in words if abs(w[1] - label[1]) < 2 and w[0] > label[2] and w[0] < next_label[2] and w[4] not in {"WEIGHT", "[g]:"}]
                overlap = any(w[2] > next_label[0] for w in spill)
                if overlap:
                    raw = join_words(spill)
                    area |= fitz.Rect(next_label[:4])
        value = raw or None
        reasons = []
        if not raw:
            reasons.append("Too blurry to read on the scan." if degraded else "Field is empty or label absent.")
        if raw.casefold() in {"description", "title", "material", "insert title"}:
            reasons.append("Printed placeholder; not a reliable part title.")
        if overlap:
            reasons.append("Material text overlaps the WEIGHT label; garbled/overprinted source.")
        if "\ufffd" in raw or any(w[4].endswith(":") for w in chosen):
            reasons.append("Value contains a label or garbled characters.")
        if name == "weight_g" and raw:
            if re.fullmatch(r"\d+(?:[.,]\d+)?", raw):
                value = float(raw.replace(",", "."))
            else:
                reasons.append("Weight is not an unambiguous number.")
        highlight = area | fitz.Rect(label[:4]) if label else area
        field = {"name": f"{drawing_id}/drawing/{name}", "original": raw or None,
                 "value": value, "confidence": "unsure" if reasons else "sure",
                 "method": "parsed", "page": page.number + 1, "box": box(highlight),
                 "field_box": box(area), "label_box": box(label[:4]) if label else None}
        if reasons:
            field["note"] = " ".join(reasons)
        if degraded:
            field.update(source_quality="degraded", value=None, original=None)
        fields[name] = field
    return fields


def main_facts(drawing_id, page, words):
    numbers = []
    counts = Counter()
    for word in words:
        x0, y0, x1, y1, text, *_ = word
        if x0 < 65 or x1 > page.rect.width - 45 or y0 < 40 or y1 > page.rect.height - 40:
            continue
        if x0 > 730 and y0 > 650:
            continue
        match = re.fullmatch(r"(?:[RrØø⌀])?([-+]?\d+(?:[.,]\d+)?)°?", text)
        if match:
            value = float(match.group(1).replace(",", "."))
            token = str(value)
            counts[token] += 1
            numbers.append({"name": f"{drawing_id}/drawing/n/{token}@{page.number + 1}-{counts[token]}",
                            "value": value, "original": text, "text": text, "page": page.number + 1,
                            "box": box(word[:4]), "method": "parsed", "confidence": "sure", "label": None})
    callouts = []
    seen = set()
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        lines = []
        for line in block["lines"]:
            r = fitz.Rect(line["bbox"])
            if r.x0 < 65 or r.x1 > page.rect.width - 45 or r.y0 < 40 or r.y1 > page.rect.height - 40 or (r.x0 > 730 and r.y0 > 650):
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                lines.append((text, r))
        # Only explicit semantic callouts. Bare dimensions remain unlabeled.
        all_text = " ".join(t for t, _ in lines)
        block_has_thread = any(re.match(r"^M\d+\s*-\s*\d+[A-Za-z]+\s+THRU", t) for t, _ in lines)
        for text, r in lines:
            props = None
            slot = re.fullmatch(r"(\d+)\s*x\s*(\d+[.,]?\d*)\s*X\s*(\d+[.,]?\d*)\s+THRU ALL", text)
            thread = re.fullmatch(r"(M\d+(?:[.,]\d+)?)\s*-\s*(\d+[A-Za-z]+)\s+(THRU ALL)", text)
            radius = re.fullmatch(r"R(\d+(?:[.,]\d+)?)", text)
            short_thread = re.fullmatch(r"(?:(\d+)\s*x\s*)?(M\d+(?:[.,]\d+)?)\s+THRU(?: ALL)?", text)
            if slot:
                props = {"feature": "slot", "count": int(slot[1]), "width_mm": float(slot[2].replace(",", ".")), "length_mm": float(slot[3].replace(",", ".")), "through": True}
            elif thread:
                count_match = re.match(r"^(\d+)\s*x\s+\d+[.,]?\d*\s+THRU ALL\s+M", all_text)
                props = {"feature": "threaded_hole", "thread": thread[1], "thread_class": thread[2], "through": True}
                if count_match:
                    props["count"] = int(count_match[1])
                    text = all_text
                    for _, line_rect in lines:
                        r |= line_rect
            elif radius:
                props = {"feature": "radius", "radius_mm": float(radius[1].replace(",", "."))}
            elif short_thread:
                props = {"feature": "threaded_hole", "thread": short_thread[2], "through": True}
                if short_thread[1]:
                    props["count"] = int(short_thread[1])
            elif "THRU" in text and not block_has_thread:
                # Diameter/depth glyphs can be vector paths, absent from PDF text.
                props = {"feature": "unclassified_callout", "through": True}
                prefix = next(((t, lr) for t, lr in lines if re.fullmatch(r"\d+\s*x", t) and abs(lr.y0 - r.y0) < 2 and lr.x1 < r.x0), None)
                if prefix:
                    props["count"] = int(re.match(r"\d+", prefix[0])[0])
                    text = prefix[0] + " " + text
                    r |= prefix[1]
            elif re.fullmatch(r"\d+(?:[.,]\d+)?\s*X\s*\d+[^\w\s]?", text):
                # Preserve angle-like notes, but do not repair a missing glyph.
                props = {"feature": "unclassified_callout"}
            if props and (text, tuple(box(r))) not in seen:
                seen.add((text, tuple(box(r))))
                callouts.append({"name": f"{drawing_id}/drawing/callout/p{page.number + 1}-{len(callouts) + 1}",
                                 "text": text, "original": text, "value": text, "page": page.number + 1,
                                 "box": box(r), "confidence": "sure", "method": "parsed", **props})
                if "\ufffd" in text:
                    callouts[-1].update(confidence="unsure", note="PDF text contains a garbled symbol; geometry is undetermined.")
    return numbers, callouts


def boilerplate(drawing_id, page, words):
    result = []
    for key, phrase in {
        "units": "DIMENSIONS ARE IN MILLIMETERS",
        "general_tolerance": "DIN ISO 2768-1 m",
        "edge_finish": "DEBURR AND BREAK SHARP EDGES",
    }.items():
        tokens = phrase.split()
        for i in range(len(words) - len(tokens) + 1):
            selected = words[i:i + len(tokens)]
            if [w[4] for w in selected] == tokens:
                area = fitz.Rect(selected[0][:4])
                for word in selected[1:]:
                    area |= fitz.Rect(word[:4])
                result.append({"name": f"{drawing_id}/drawing/general/{key}", "value": phrase,
                               "original": phrase, "text": phrase, "feature": "general_note",
                               "page": page.number + 1, "box": box(area), "method": "parsed", "confidence": "sure"})
                break
    return result


def parse_drawings(output: Path = GENERATED) -> dict:
    output = inside(output)
    images = inside(output / "images")
    images.mkdir(parents=True, exist_ok=True)
    assets = json.loads((CORPUS / "dataset/manifest.json").read_text(encoding="utf-8"))["assets"]
    drawings = {}
    previous = json.loads((output / "drawings.json").read_text(encoding="utf-8")) if (output / "drawings.json").exists() else {}
    for asset in assets:
        drawing_id = asset["id"]
        if not re.fullmatch(r"D-\d{3}", drawing_id):
            continue
        source = CORPUS / asset["path"]
        fingerprint = sha_file(source)
        degraded = asset.get("distribution") == "degraded-only"
        record = {"id": drawing_id, "pages": 0, "page_sizes": [], "images": [], "fields": {}, "page_fields": {},
                  "degraded": degraded, "source_quality": "degraded" if degraded else "clean",
                  "numbers": [], "callouts": [], "words": [], "text": "", "page_texts": [], "sha256": fingerprint,
                  "source_path": str(source.relative_to(ROOT)).replace("\\", "/"),
                  "upstream_source_path": asset["source_path"], "source_filename": Path(asset["source_path"]).name,
                  "section": asset.get("subsystem"), "source_url": asset.get("source_url")}
        with fitz.open(source) as doc:
            record["pages"] = len(doc)
            for page in doc:
                page_number = page.number + 1
                image_name = f"images/{drawing_id}-p{page_number}.png"
                image_path = inside(output / image_name)
                if not image_path.exists() or previous.get(drawing_id, {}).get("sha256") != fingerprint:
                    page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False).save(image_path)
                record["images"].append(image_name)
                record["page_sizes"].append([page.rect.width, page.rect.height])
                words = unique_words(page) if not degraded else []
                record["page_texts"].append(join_words(words))
                fields = fields_for_page(drawing_id, page, words, degraded)
                record["page_fields"][str(page_number)] = fields
                if page_number == 1:
                    record["fields"] = fields
                    sx, sy = page.rect.width / 1190.55, page.rect.height / 841.89
                    cx, cy, cw, ch = LAYOUT["corner"]
                    corner = [cx * sx, cy * sy, cw * sx, ch * sy]
                    corner_name = f"images/{drawing_id}-corner.png"
                    corner_path = inside(output / corner_name)
                    if not corner_path.exists() or previous.get(drawing_id, {}).get("sha256") != fingerprint or previous.get(drawing_id, {}).get("corner_box") != corner:
                        page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect(corner), alpha=False).save(corner_path)
                    record.update(image=image_name, corner_image=corner_name, corner_box=corner)
                if not degraded:
                    record["words"].extend({"text": w[4], "page": page_number, "box": box(w[:4])} for w in words)
                    numbers, callouts = main_facts(drawing_id, page, words)
                    record["numbers"].extend(numbers)
                    record["callouts"].extend(callouts)
                    record["callouts"].extend(boilerplate(drawing_id, page, words))
        record["text"] = "\n\n".join(record["page_texts"])
        drawings[drawing_id] = record
    write_json(output / "drawings.json", drawings)
    return drawings
