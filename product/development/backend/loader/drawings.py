"""M1 PDF evidence, using the frozen contracts and the supplied manifest.

``load_drawings(corpus_root, generated_dir)`` returns DrawingEvidence objects;
only PNGs are written, under generated_dir/images. Callers persist the records.
The manifest paths are relative to corpus_root (the project-meridian directory).
Every page uses page_image_path(), including pages after the first. Canonical
corner keys belong to page 1; subsequent pages use e.g. ``title-p2``. A later
page's title never fills a missing first-page title.

Words retain their PDF spelling. All public boxes are PDF points in the saved
page's cropped, rotated, top-left coordinate frame, never raster pixels.
Scans have no extracted numbers or OCR. Their unresolved field regions are
measured from a clean sheet of the same page format, then scaled to the actual
scan page dimensions; the donor is recorded.
This module does not interpret callouts, infer dimensions, or invoke AI.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Sequence

from backend.contracts import (
    Box, Confidence, DrawingEvidence, DrawingField, DrawingNumber, DrawingWord,
    Method, PageGeometry, SourceQuality, drawing_fact_name, drawing_id,
    drawing_number_name, normalize_component,
)


# Label spellings/directions, not source values or engineering expectations.
_LABELS = {
    "title": (r"TITLE\s*/\s*DESCRIPTION\s*:", "below"),
    "notes": (r"NOTES?\s*:", "below"),
    "company": (r"COMPANY\s*:", "below"),
    "material": (r"MATERIAL\s*:", "right"),
    "weight": (r"WEIGHT\s*\[\s*g\s*\]\s*:", "right"),
    "date": (r"DATE\s*:?", "right"),
    "drawn": (r"DRAWN\s*:?", "right"),
    "scale": (r"SCALE\s*:", "right"),
}
_PLACEHOLDERS = {"description", "title", "title/description", "material", "note",
                 "notes", "company", "n/a", "na", "none", "tbd", "?", "-"}
# Lexical numbers only: retain e.g. the digits of R105,0 or M6 without
# assigning radius/thread/length meanings. Those interpretations belong later.
_NUMBER = re.compile(r"(?<![\d.,])[-+−]?\d+(?:[.,]\d+)?(?![\d.,])")
_TOLERANCE = 0.15  # points; coincident text, not neighboring repeated words.


@dataclass(frozen=True)
class _Char:
    text: str
    box: Box
    line: tuple[int, int]
    index: int


@dataclass(frozen=True)
class _Word:
    text: str
    box: Box
    line: tuple[int, int]
    chars: tuple[_Char, ...]


@dataclass(frozen=True)
class _Anchor:
    field: str
    box: Box
    chars: tuple[_Char, ...]


@dataclass
class _Page:
    number: int
    width: float
    height: float
    geometry: PageGeometry | None
    matrix: Any
    words: list[_Word]
    lines: dict[tuple[int, int], list[_Char]]
    horizontal: list[tuple[float, float, float]]  # y, x0, x1
    vertical: list[tuple[float, float, float]]  # x, y0, y1


@dataclass(frozen=True)
class _Layout:
    drawing: str
    page: int
    width: float
    height: float
    boxes: dict[str, Box]


def page_image_path(identifier: str, page: int = 1) -> str:
    """Generated-root-relative PNG path; pages are 1-based."""
    identifier = drawing_id(identifier)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("Page numbers are 1-based")
    return f"images/{identifier}-p{page}.png"


def _xywh(rect: Sequence[float]) -> Box:
    x0, y0, x1, y1 = rect
    return (float(x0), float(y0), max(0., float(x1 - x0)), max(0., float(y1 - y0)))


def _edges(box: Box) -> tuple[float, float, float, float]:
    x, y, w, h = box
    return x, y, x + w, y + h


def _union(boxes: Sequence[Box]) -> Box:
    edges = [_edges(b) for b in boxes]
    return _xywh((min(b[0] for b in edges), min(b[1] for b in edges),
                  max(b[2] for b in edges), max(b[3] for b in edges)))


def _same_box(a: Box, b: Box) -> bool:
    return all(abs(x - y) <= _TOLERANCE for x, y in zip(a, b))


def _overlap(a: Box, b: Box) -> bool:
    ax, ay, ar, ab = _edges(a)
    bx, by, br, bb = _edges(b)
    return (min(ar, br) - max(ax, bx) > 0.5
            and min(ab, bb) - max(ay, by) > min(a[3], b[3]) * .4)


def _contains_center(outer: Box, inner: Box) -> bool:
    x, y, right, bottom = _edges(outer)
    return (x - _TOLERANCE <= inner[0] + inner[2] / 2 <= right + _TOLERANCE
            and y - _TOLERANCE <= inner[1] + inner[3] / 2 <= bottom + _TOLERANCE)


def _display_box(box: Box, page: _Page, pdf: Any) -> Box:
    return _xywh(pdf.Rect(_edges(box)) * page.matrix)


def _read_page(page: Any, number: int, image: Path | None, dpi: int, degraded: bool) -> _Page:
    geometry = None
    if image is not None:
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        image.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(image)
        geometry = PageGeometry(page=number, source_width=page.rect.width,
                                source_height=page.rect.height, image_width=pixmap.width,
                                image_height=pixmap.height)
    lines: dict[tuple[int, int], list[_Char]] = {}
    words: list[_Word] = []
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    if not degraded:
        textpage = page.get_textpage()
        for block_index, block in enumerate(textpage.extractRAWDICT()["blocks"]):
            for line_index, line in enumerate(block.get("lines", [])):
                key = (block.get("number", block_index), line_index)
                chars = [char for span in line["spans"] for char in span["chars"]]
                lines[key] = [_Char(c["c"], _xywh(c["bbox"]), key, index)
                              for index, c in enumerate(chars)]
        for x0, y0, x1, y1, text, block, line, _ in textpage.extractWORDS():
            if not text:
                continue
            box = _xywh((x0, y0, x1, y1))
            if any(w.text == text and _same_box(w.box, box) for w in words):
                continue
            chars = tuple(c for c in lines.get((block, line), [])
                          if _contains_center(box, c.box) and not c.text.isspace())
            words.append(_Word(text, box, (block, line), chars))
        for path in page.get_drawings():
            if "s" not in path["type"]:
                continue  # A filled area is not a measured cell border.
            segments = []
            for item in path["items"]:
                if item[0] == "l":
                    segments.append((item[1], item[2]))
                elif item[0] == "re":
                    r = item[1]
                    segments.extend(((r.tl, r.tr), (r.tr, r.br),
                                     (r.br, r.bl), (r.bl, r.tl)))
                elif item[0] == "qu":
                    q = item[1]
                    segments.extend(((q.ul, q.ur), (q.ur, q.lr),
                                     (q.lr, q.ll), (q.ll, q.ul)))
            for a, b in segments:
                if abs(a.y - b.y) <= .5 and abs(a.x - b.x) > 1:
                    horizontal.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) <= .5 and abs(a.y - b.y) > 1:
                    vertical.append(((a.x + b.x) / 2, min(a.y, b.y), max(a.y, b.y)))
    words.sort(key=lambda w: (w.box[1], w.box[0], w.box[3], w.box[2], w.text))
    return _Page(number, page.cropbox.width, page.cropbox.height, geometry,
                 page.rotation_matrix, words, lines, horizontal, vertical)


def _anchors(page: _Page) -> tuple[list[_Anchor], set[tuple[tuple[int, int], int]]]:
    anchors = []
    label_chars = set()
    for chars in page.lines.values():
        text = "".join(c.text for c in chars)
        for field, (pattern, _) in _LABELS.items():
            for match in re.finditer(r"(?<!\w)" + pattern + r"(?![A-Za-z])", text, re.I):
                selected = tuple(chars[match.start():match.end()])
                label_chars.update((c.line, c.index) for c in selected)
                box = _union([c.box for c in selected])
                if not any(a.field == field and _same_box(a.box, box) for a in anchors):
                    anchors.append(_Anchor(field, box, selected))
    return sorted(anchors, key=lambda a: (a.box[1], a.box[0], a.field)), label_chars


def _cell(anchor: _Anchor, page: _Page, anchors: list[_Anchor]) -> Box | None:
    x, y, right, bottom = _edges(anchor.box)
    cx, cy = (x + right) / 2, (y + bottom) / 2
    # Font ascender boxes may protrude past a rule even when the ink is inside.
    # Enclose the label's center using observed rules, not font-box extrema.
    lefts = [v for v, lo, hi in page.vertical if lo - .5 <= cy <= hi + .5 and v < cx]
    rights = [v for v, lo, hi in page.vertical if lo - .5 <= cy <= hi + .5 and v > cx]
    tops = [v for v, lo, hi in page.horizontal if lo - .5 <= cx <= hi + .5 and v < cy]
    bottoms = [v for v, lo, hi in page.horizontal if lo - .5 <= cx <= hi + .5 and v > cy]
    if not all((lefts, rights, tops, bottoms)):
        return None
    left, top, end, base = max(lefts), max(tops), min(rights), min(bottoms)
    # Several inline labels can share a table row without a vertical divider.
    for other in anchors:
        if other is anchor:
            continue
        ox, oy, ow, oh = other.box
        if _LABELS[anchor.field][1] == "right" and abs(oy - y) < max(oh, anchor.box[3]) * .6:
            if right <= ox < end:
                end = ox
            if ox + ow <= x and ox + ow > left:
                left = x
    if end <= left or base <= top:
        return None
    return (left, top, end - left, base - top)


def _chunks(word: _Word, label_chars: set) -> list[tuple[_Char, ...]]:
    chunks: list[list[_Char]] = []
    for char in word.chars:
        if (char.line, char.index) in label_chars:
            continue
        if not chunks or char.index != chunks[-1][-1].index + 1:
            chunks.append([])
        chunks[-1].append(char)
    return [tuple(chunk) for chunk in chunks]


def _field_text(selected: list[tuple[_Char, ...]], page: _Page) -> str | None:
    by_line: dict[tuple[int, int], dict[int, _Char]] = defaultdict(dict)
    for chunk in selected:
        for char in chunk:
            by_line[char.line][char.index] = char
    ordered = sorted(by_line, key=lambda key: (min(c.box[1] for c in by_line[key].values()),
                                               min(c.box[0] for c in by_line[key].values())))
    values = []
    for key in ordered:
        chosen = by_line[key]
        values.append("".join(c.text for c in page.lines[key]
                              if min(chosen) <= c.index <= max(chosen)
                              and (c.index in chosen or c.text.isspace())))
    return "\n".join(values) or None


def _field_key(field: str, page: int) -> str:
    return field if page == 1 else f"{field}-p{page}"


def _clean_fields(identifier: str, page: _Page, pdf: Any) -> tuple[dict[str, DrawingField], _Layout]:
    anchors, label_chars = _anchors(page)
    fields = {}
    boxes = {}
    for field, (_, direction) in _LABELS.items():
        matches = [a for a in anchors if a.field == field]
        anchor = matches[0] if matches else None
        cell = _cell(anchor, page, anchors) if anchor else None
        selected: list[tuple[_Char, ...]] = []
        reason = None
        if anchor and cell:
            boxes[field] = cell
            ax, ay, ar, ab = _edges(anchor.box)
            for word in page.words:
                for chunk in _chunks(word, label_chars):
                    box = _union([c.box for c in chunk])
                    if not _contains_center(cell, (box[0], box[1], 0., box[3])):
                        continue
                    if direction == "below" and box[1] < ab - .5:
                        continue
                    if direction == "right" and (box[0] < ar - .5 or
                            abs((box[1] + box[3] / 2) - (ay + anchor.box[3] / 2)) > anchor.box[3] * .6):
                        continue
                    selected.append(chunk)
            if any(_overlap(_union([c.box for c in chunk]), other.box)
                   for chunk in selected for other in anchors if other is not anchor):
                reason = "Value overlaps another corner label."
                # Preserve the rest of an overlapping source line, including
                # text beyond the neighbor label's x position. Stop at a label
                # in that same source line, rather than appending its value.
                starts = {chunk[0].line: min(c.index for part in selected
                          for c in part if c.line == chunk[0].line) for chunk in selected}
                for word in page.words:
                    if word.line not in starts:
                        continue
                    limit = min((c.index for other in anchors if other is not anchor
                                 for c in other.chars if c.line == word.line
                                 and c.index > starts[word.line]), default=math.inf)
                    for chunk in _chunks(word, label_chars):
                        if (chunk[0].index >= starts[word.line] and chunk[-1].index < limit
                                and chunk not in selected):
                            selected.append(chunk)
            if any(_overlap(_union([c.box for c in first]), _union([c.box for c in second]))
                   for index, first in enumerate(selected) for second in selected[index + 1:]):
                reason = "Source values overlap within the corner field."
            # A foreign word printed over this label also makes the cell unsafe.
            if any(_overlap(_union([c.box for c in chunk]), anchor.box)
                   for word in page.words for chunk in _chunks(word, label_chars)):
                reason = "Corner label overlaps source text."
            if len(matches) != 1:
                reason = "More than one matching corner label on this page."
        else:
            reason = "Corner label or measured enclosing cell is missing."
        original = _field_text(selected, page)
        value = original.strip() if original else None
        if value and value.casefold().strip(" :") in _PLACEHOLDERS:
            reason = "Source contains a placeholder."
        if not value:
            reason = reason or "No value recorded in the labeled field."
        key = _field_key(field, page.number)
        # Whole measured cell for missing/uncertain fields; label remains visible.
        region = cell or (anchor.box if anchor else (0., 0., page.width, page.height))
        if selected:
            # An overlapping value can extend into its neighbor's cell. Retain
            # that complete source extent in the highlight, not just a cutoff.
            region = _union([region, *[_union([c.box for c in chunk]) for chunk in selected]])
        fields[key] = DrawingField(
            name=drawing_fact_name(identifier, key), original=original,
            value=value if reason is None else None,
            confidence=Confidence.SURE if reason is None else Confidence.UNSURE,
            method=Method.PARSED, note=reason, page=page.number,
            box=_display_box(region, page, pdf),
            source_quality=(SourceQuality.MISSING if not value else
                            SourceQuality.DEGRADED if reason and "overlap" in reason.lower()
                            else SourceQuality.CLEAN),
        )
    return fields, _Layout(identifier, page.number, page.width, page.height, boxes)


def _scan_fields(identifier: str, page: _Page, layouts: list[_Layout], pdf: Any) -> dict[str, DrawingField]:
    # Use an actually measured sheet of the same format/orientation. Do not invent
    # a crop from a percentage of the page, or import a pristine scan counterpart.
    donors = [layout for layout in layouts if len(layout.boxes) == len(_LABELS)
              and abs((layout.width / layout.height) / (page.width / page.height) - 1) < .01]
    if not donors:
        raise ValueError(f"{identifier} page {page.number}: no measured clean corner layout for scan crops")
    donor = min(donors, key=lambda layout: (layout.drawing, layout.page))
    sx, sy = page.width / donor.width, page.height / donor.height
    fields = {}
    for field, (x, y, w, h) in donor.boxes.items():
        key = _field_key(field, page.number)
        fields[key] = DrawingField(
            name=drawing_fact_name(identifier, key), original=None, value=None,
            confidence=Confidence.UNSURE, method=Method.UNRESOLVED, page=page.number,
            box=_display_box((x * sx, y * sy, w * sx, h * sy), page, pdf),
            source_quality=SourceQuality.DEGRADED,
            note=(f"Scan field has not been read. Crop measured from {donor.drawing} "
                  f"page {donor.page}, scaled to this page's measured size; "
                  "no OCR or inferred field value."),
        )
    return fields


def _numbers(identifier: str, pages: list[_Page], pdf: Any) -> list[DrawingNumber]:
    counts: Counter[str] = Counter()
    candidates = []
    for page in pages:
        for word in page.words:
            for match in _NUMBER.finditer(word.text):
                text = match.group()
                value = float(text.replace(",", ".").replace("−", "-"))
                if not math.isfinite(value):
                    continue
                # Character positions give the numeric substring's exact box.
                exact = "".join(c.text for c in word.chars) == word.text
                chars = word.chars[match.start():match.end()] if exact else ()
                box = _union([c.box for c in chars]) if chars else word.box
                confidence = (Confidence.UNSURE if any(
                        other is not word and _overlap(word.box, other.box)
                        for other in page.words) else Confidence.SURE)
                if (match.start() and word.text[match.start() - 1].isalnum()
                        and text.startswith(("-", "+", "−"))):
                    confidence = Confidence.UNSURE  # Could be an identifier's separator.
                candidates.append((page.number, _display_box(box, page, pdf), text, value, confidence))
    # Occurrences use the saved page's reading order, including rotated pages.
    candidates.sort(key=lambda n: (n[0], n[1][1], n[1][0], n[1][3], n[1][2], n[2]))
    numbers = []
    for page, box, text, value, confidence in candidates:
        token = normalize_component(text)
        counts[token] += 1
        numbers.append(DrawingNumber(name=drawing_number_name(identifier, text, counts[token]),
                                     text=text, value=value, page=page, box=box,
                                     confidence=confidence))
    return numbers


def load_drawings(corpus_root: str | Path, generated_dir: str | Path, *,
                  dpi: int = 144, ids: Sequence[str] | None = None) -> list[DrawingEvidence]:
    """Verify manifest PDF hashes/counts, render all pages, extract M1 evidence.

    PyMuPDF is required only for regeneration (the existing ``prep`` extra).
    If ids is supplied, clean donors can still be inspected for scan crop boxes;
    unrequested assets are never rendered. Unknown IDs, altered source bytes, or
    missing measured scan layouts fail explicitly instead of yielding guesses.
    All writes are relative to the caller's generated_dir.
    """
    if not isinstance(dpi, int) or isinstance(dpi, bool) or not 36 <= dpi <= 600:
        raise ValueError("dpi must be an integer between 36 and 600")
    try:
        import pymupdf as pdf
    except ImportError as error:
        raise RuntimeError("Drawing regeneration requires the PyMuPDF prep dependency") from error
    root = Path(corpus_root).resolve()
    output = Path(generated_dir).resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError("Generated images must be outside the unchanged source corpus")
    manifest = json.loads((root / "dataset/manifest.json").read_text(encoding="utf-8"))
    assets = [a for a in manifest["assets"] if re.fullmatch(r"D-\d{3}", a["id"])]
    inventory = {a["id"]: a for a in assets}
    if len(inventory) != len(assets) or not assets:
        raise ValueError("Manifest drawing inventory is empty or contains duplicate IDs")
    requested = set(inventory) if ids is None else {drawing_id(identifier) for identifier in ids}
    if requested - inventory.keys():
        raise ValueError(f"Drawing IDs absent from manifest: {sorted(requested - inventory.keys())}")
    if not requested:
        return []
    need_donors = any(inventory[i].get("distribution") == "degraded-only" for i in requested)
    layouts: list[_Layout] = []
    extracted: dict[str, tuple[dict, list[_Page], dict[str, DrawingField]]] = {}
    # Clean sheets first so raster-only pages use measured, source-backed boxes.
    ordered = sorted(assets, key=lambda a: (a.get("distribution") == "degraded-only", a["id"]))
    for asset in ordered:
        identifier = asset["id"]
        degraded = asset.get("distribution") == "degraded-only"
        if identifier not in requested and (not need_donors or degraded):
            continue
        source = (root / asset["path"]).resolve()
        if not source.is_relative_to(root) or source.suffix.lower() != ".pdf":
            raise ValueError(f"{identifier}: invalid manifest PDF path")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != asset["sha256"] or len(data) != asset["bytes"]:
            raise ValueError(f"{identifier}: supplied bytes differ from the manifest")
        with pdf.open(stream=data, filetype="pdf") as document:
            if document.page_count != asset["pages"]:
                raise ValueError(f"{identifier}: page count differs from manifest")
            pages = []
            fields = {}
            for number, source_page in enumerate(document, 1):
                image = output / page_image_path(identifier, number) if identifier in requested else None
                page = _read_page(source_page, number, image, dpi, degraded)
                if not degraded and page.words:
                    clean, layout = _clean_fields(identifier, page, pdf)
                    fields.update(clean)
                    layouts.append(layout)
                pages.append(page)
            if identifier in requested:
                extracted[identifier] = (asset, pages, fields)
    results = []
    for identifier in sorted(requested):
        asset, pages, fields = extracted[identifier]
        degraded = asset.get("distribution") == "degraded-only" or any(not p.words for p in pages)
        for page in pages:
            if not page.words:
                fields.update(_scan_fields(identifier, page, layouts, pdf))
        words = [DrawingWord(text=w.text, page=p.number, box=_display_box(w.box, p, pdf))
                 for p in pages for w in p.words]
        words.sort(key=lambda w: (w.page, w.box[1], w.box[0], w.box[3], w.box[2], w.text))
        results.append(DrawingEvidence(
            id=identifier, pages=len(pages), image=page_image_path(identifier),
            page_geometry=[p.geometry for p in pages], degraded=degraded,
            source_quality=SourceQuality.DEGRADED if degraded else SourceQuality.CLEAN,
            source_path=asset["path"], source_sha256=asset["sha256"], fields=fields,
            words=words,
            numbers=_numbers(identifier, pages, pdf),
        ))
    return results
