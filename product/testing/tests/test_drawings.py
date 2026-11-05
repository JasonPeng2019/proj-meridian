"""Focused M05 tests. Execute on Actions with the existing prep/test extras.

Run from testing/; all generated PDFs, PNGs, reports and temporary files remain
here. Source corpus checks use supplied bytes, never the benchmark answer draft.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile

import pymupdf as pdf
import pytest

TESTING = Path(__file__).resolve().parents[1]
DEVELOPMENT = TESTING.parent / "development"
sys.path.insert(0, str(DEVELOPMENT))

from backend.contracts import (  # noqa: E402
    Confidence, DrawingEvidence, SourceQuality, pixel_box_to_source,
    source_box_to_pixels,
)
from backend.loader.drawings import load_drawings, page_image_path  # noqa: E402


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def work():
    folder = TESTING / "tmp/A05-drawings"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=folder) as directory:
        yield Path(directory)


@pytest.fixture(scope="module")
def corpus():
    root = DEVELOPMENT / "inputs/project-meridian"
    manifest = json.loads((root / "dataset/manifest.json").read_text(encoding="utf-8"))
    before = {a["path"]: _digest(root / a["path"]) for a in manifest["assets"]}
    output = TESTING / "runs/A05-drawings/corpus"
    records = load_drawings(root, output, dpi=96, ids=[
        "D-001", "D-002", "D-003", "D-004", "D-006", "D-010", "D-013",
        "D-019", "D-021", "D-026", "D-029",
    ])
    assert before == {a["path"]: _digest(root / a["path"]) for a in manifest["assets"]}
    report = TESTING / "reports/verification/A05-drawings"
    report.mkdir(parents=True, exist_ok=True)
    (report / "source-extraction.json").write_text(json.dumps({
        "scope": "M1 actual corpus extraction; no AI reading or human approval",
        "github_revision": os.environ.get("GITHUB_SHA"),
        "module_sha256": _digest(DEVELOPMENT / "backend/loader/drawings.py"),
        "test_sha256": _digest(Path(__file__)),
        "source_hashes_before_and_after": before,
        "sources_unchanged": True,
        "records": [record.model_dump(mode="json") for record in records],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return root, output, {r.id: r for r in records}


def test_actual_corner_fields_keep_uncertainty_and_missing_titles(corpus):
    _, _, drawings = corpus
    for identifier in ("D-002", "D-004", "D-006", "D-010", "D-021", "D-029"):
        title = drawings[identifier].fields["title"]
        assert title.value is None, (identifier, title)
        assert title.confidence == Confidence.UNSURE
        assert not title.original
    assert drawings["D-002"].fields["notes"].original
    placeholder = drawings["D-019"].fields["title"]
    assert placeholder.original == "Description"
    assert placeholder.value is None
    assert placeholder.confidence == Confidence.UNSURE
    assert "placeholder" in placeholder.note.lower()
    overlap = drawings["D-026"].fields["material"]
    assert overlap.original, "Do not discard the questionable original material text"
    assert overlap.value is None
    assert overlap.confidence == Confidence.UNSURE
    assert "overlap" in overlap.note.lower()
    material = drawings["D-013"].fields["material"]
    assert material.confidence == Confidence.SURE, material
    assert material.value and "WEIGHT" not in material.value.upper()


def test_actual_d013_coincident_words_and_numbers_are_deduplicated(corpus):
    root, _, drawings = corpus
    drawing = drawings["D-013"]
    with pdf.open(root / drawing.source_path) as document:
        raw = document[0].get_text("words")
    assert len(raw) > len(drawing.words), "Representative source must exercise duplicate text"
    for index, word in enumerate(drawing.words):
        assert any(word.text == source[4] for source in raw)
        assert not any(other.text == word.text and other.page == word.page
                       and all(abs(a - b) <= .15 for a, b in zip(word.box, other.box))
                       for other in drawing.words[index + 1:])
    assert len({number.name for number in drawing.numbers}) == len(drawing.numbers)
    assert any(number.text == "270,0" or number.text == "270.0" for number in drawing.numbers)
    for number in drawing.numbers:
        assert any(number.text in word.text and number.page == word.page
                   and word.box[0] - .2 <= number.box[0]
                   and word.box[1] - .2 <= number.box[1]
                   and number.box[0] + number.box[2] <= word.box[0] + word.box[2] + .2
                   and number.box[1] + number.box[3] <= word.box[1] + word.box[3] + .2
                   for word in drawing.words)


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_actual_multipage_images_geometry_and_scan_crops(corpus):
    _, output, drawings = corpus
    assert drawings["D-021"].pages == 2
    assert {word.page for word in drawings["D-021"].words} == {1, 2}
    assert drawings["D-003"].pages == 3
    for drawing in drawings.values():
        assert DrawingEvidence.model_validate_json(drawing.model_dump_json()) == drawing
        for geometry in drawing.page_geometry:
            assert _png_size(output / page_image_path(drawing.id, geometry.page)) == (
                geometry.image_width, geometry.image_height)
    for identifier in ("D-001", "D-003"):
        scan = drawings[identifier]
        assert scan.degraded and scan.source_quality == SourceQuality.DEGRADED
        assert not scan.words and not scan.numbers
        assert {field.page for field in scan.fields.values()} == set(range(1, scan.pages + 1))
        for field in scan.fields.values():
            assert field.value is None and field.original is None
            assert field.confidence == Confidence.UNSURE
            assert "measured from D-" in field.note
            geometry = scan.page_geometry[field.page - 1]
            x, y, width, height = field.box
            assert 0 <= x < x + width <= geometry.source_width + 1
            assert 0 <= y < y + height <= geometry.source_height + 1
            assert width < geometry.source_width and height < geometry.source_height
        assert scan.fields["material"].box != scan.fields["weight"].box


def _sheet(page, title: str, *, overlapping_material: bool = False):
    for rect in [(50, 160, 330, 200), (330, 160, 450, 200), (50, 200, 450, 250),
                 (50, 250, 450, 275), (50, 275, 450, 300), (50, 300, 150, 325)]:
        page.draw_rect(pdf.Rect(rect))
    for point, text in [((55, 171), "TITLE/DESCRIPTION:"), ((335, 171), "COMPANY:"),
                        ((55, 211), "NOTE:"), ((55, 266), "MATERIAL:"),
                        ((275, 266), "WEIGHT [g]:"), ((55, 291), "DRAWN"),
                        ((200, 291), "DATE"), ((55, 316), "SCALE:1:2")]:
        page.insert_text(point, text, fontsize=8)
    page.insert_text((55, 190), title, fontsize=10)
    page.insert_text((335, 190), "Example", fontsize=10)
    page.insert_text((55, 226), "keep  these spaces", fontsize=10)
    page.insert_text((55, 241), "second line, unchanged.", fontsize=10)
    page.insert_text((260 if overlapping_material else 110, 266),
                     "LONG MATERIAL" if overlapping_material else "Alloy A7", fontsize=8)
    page.insert_text((340, 266), "12,5", fontsize=8)
    page.insert_text((95, 291), "JP", fontsize=8)
    page.insert_text((235, 291), "2026-11-05", fontsize=8)
    page.insert_text((180, 316), "R19,25 M6", fontsize=8)


def _synthetic_corpus(work: Path, *, rotate: bool = False, overlap: bool = False) -> Path:
    root = work / "source"
    folder = root / "dataset/drawings"
    folder.mkdir(parents=True)
    with pdf.open() as document:
        for title in ("Panel 37,5", "Later sheet"):
            page = document.new_page(width=500, height=400)
            _sheet(page, title, overlapping_material=overlap)
            if rotate:
                page.set_cropbox(pdf.Rect(30, 140, 470, 340))
                page.set_rotation(90)
        document.save(folder / "D-901.pdf")
    source = folder / "D-901.pdf"
    (root / "dataset/manifest.json").write_text(json.dumps({"assets": [{
        "id": "D-901", "path": "dataset/drawings/D-901.pdf", "pages": 2,
        "distribution": "clean", "bytes": source.stat().st_size,
        "sha256": _digest(source), "media_type": "application/pdf",
    }]}), encoding="utf-8")
    return root


def test_cropped_rotated_pages_have_source_aligned_text_and_pixels(work):
    root = _synthetic_corpus(work, rotate=True)
    output = work / "generated"
    drawing, = load_drawings(root, output, dpi=101)
    assert drawing.fields["title"].value == "Panel 37,5"
    assert drawing.fields["title-p2"].value == "Later sheet"
    assert drawing.fields["notes"].original == "keep  these spaces\nsecond line, unchanged."
    assert drawing.fields["material"].value == "Alloy A7"
    assert drawing.fields["scale"].value == "1:2"
    geometry = drawing.page_geometry[0]
    assert (geometry.source_width, geometry.source_height) == (200, 440)
    with pdf.open(root / drawing.source_path) as document:
        source_word = next(w for w in document[0].get_text("words") if w[4] == "37,5")
    number = next(n for n in drawing.numbers if n.text == "37,5")
    assert number.value == 37.5 and number.page == 1
    assert any(n.text == "19,25" and n.value == 19.25 and n.unit is None for n in drawing.numbers)
    assert any(n.text == "6" and n.value == 6 and n.unit is None for n in drawing.numbers)
    # Independent 90-degree rotation: x'=unrotated_height-y1, y'=x0.
    x0, y0, x1, y1 = source_word[:4]
    assert number.box == pytest.approx((200 - y1, x0, y1 - y0, x1 - x0), abs=.02)
    pixels = source_box_to_pixels(number.box, geometry)
    assert pixel_box_to_source(pixels, geometry) == pytest.approx(number.box)
    pixmap = pdf.Pixmap(str(output / drawing.image))
    px, py, width, height = pixels
    samples = pixmap.samples
    ink = 0
    for y in range(max(0, math.floor(py)), min(pixmap.height, math.ceil(py + height))):
        for x in range(max(0, math.floor(px)), min(pixmap.width, math.ceil(px + width))):
            offset = (y * pixmap.width + x) * pixmap.n
            ink += min(samples[offset:offset + 3]) < 128
    assert ink > 15, "The positioned number highlight must contain the rendered number"


def test_overlapping_text_is_unresolved_without_drawing_id_special_cases(work):
    root = _synthetic_corpus(work, overlap=True)
    drawing, = load_drawings(root, work / "generated", dpi=72)
    assert drawing.fields["material"].original
    assert drawing.fields["material"].value is None
    assert drawing.fields["material"].confidence == Confidence.UNSURE
    assert "overlap" in drawing.fields["material"].note.lower()
    assert drawing.fields["weight"].confidence == Confidence.UNSURE


def test_manifest_validation_rejects_changed_bytes_and_source_output(work):
    root = _synthetic_corpus(work)
    with pytest.raises(ValueError, match="outside the unchanged source corpus"):
        load_drawings(root, root / "images")
    source = root / "dataset/drawings/D-901.pdf"
    source.write_bytes(source.read_bytes() + b"\n% altered synthetic input\n")
    with pytest.raises(ValueError, match="differ from the manifest"):
        load_drawings(root, work / "generated")
