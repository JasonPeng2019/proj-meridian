"""Source-only runtime checks, with synthetic files isolated under testing/.

Remote command: python -B -m pytest -q tests/test_source_runtime.py tests/test_tools.py
The PDF-labelled fixture is inert bytes: this suite never extracts/renders PDFs,
executes a reader, calls an API, or attributes a test decision to a real person.
"""

import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.ai.prepare import PreparedKnowledge  # noqa: E402
from backend.loader.bom import HEADER_KEYS, load_bom  # noqa: E402
from backend.loader.records import RecordRegistry, RecordsError, read_records  # noqa: E402


NOTE = "Synthetic source-runtime fixture; no real engineering facts, AI execution or human review."
MARKERS = dict(fixture=True, synthetic=True, fixture_note=NOTE)


@pytest.fixture
def workspace():
    parent = ROOT / "testing/tmp/source-runtime"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as temporary:
        yield Path(temporary)


def source_bundle(workspace, *, drawing_material="Synthetic polymer", bom_material="Synthetic polymer",
                  drawing_confidence="sure", rows=None):
    """Write explicit synthetic source bytes and an already-extracted evidence file."""
    source_root = workspace / "source"
    dataset = source_root / "dataset"
    pdf = dataset / "drawings/D-001.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"Synthetic inert source bytes, not a rendered drawing or a valid CAD input.")
    pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    csv_path = dataset / "context/openlpbf-bom.csv"
    csv_path.parent.mkdir(parents=True)
    default_row = {"Name": "Synthetic bracket", "Part family": "Synthetic Cell", "Type": "Custom",
        "Material": bom_material or "", "Datasheet": "SyntheticBracket.pdf", "Amount": "2",
        "Cost": "DKK0.10", "Total cost": "DKK0.20"}
    raw_rows = rows if rows is not None else [default_row]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(HEADER_KEYS))
        writer.writeheader()
        for values in raw_rows:
            writer.writerow({key: values.get(key, "") for key in HEADER_KEYS})
    fields = {key: c.DrawingField(name=c.drawing_fact_name("D-001", key), original=value, value=value,
        confidence=drawing_confidence if key == "material" else "sure", method="parsed", page=1,
        box=(10, 10, 30, 10), source_quality="clean") for key, value in {
        "title": "Synthetic bracket", "material": drawing_material, "notes": "Synthetic source note only."}.items()}
    drawing = c.DrawingEvidence(id="D-001", pages=1, image="images/D-001/page-1.png", degraded=False,
        source_quality="clean", source_path="dataset/drawings/D-001.pdf", source_sha256=pdf_hash, fields=fields,
        page_geometry=[c.PageGeometry(page=1, source_width=100, source_height=100, image_width=100, image_height=100)],
        numbers=[c.DrawingNumber(name="D-001/drawing/n/4@1", text="4", value=4, page=1, box=(20, 20, 4, 4), unit="mm")])
    manifest = {"assets": [
        {"id": "D-001", "path": drawing.source_path, "sha256": pdf_hash, "media_type": "application/pdf",
         "source_path": "SYNTHETIC/SyntheticBracket.pdf", "subsystem": "Synthetic Cell"},
        {"id": "OPENLPBF-BOM", "path": "dataset/context/openlpbf-bom.csv", "media_type": "text/csv",
         "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()}]}
    manifest_path = dataset / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    payload = dict(**MARKERS, schema="meridian-deterministic-inputs/v1",
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        drawings=[drawing.model_dump(mode="json")], bom=[row.model_dump(mode="json") for row in load_bom(csv_path)])
    inputs = workspace / "inputs.json"
    inputs.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return inputs, manifest_path


def test_source_only_registry_has_exact_links_and_zero_ai_jobs(workspace, monkeypatch):
    inputs, manifest = source_bundle(workspace)
    def forbidden(*args, **kwargs):
        raise AssertionError("Source-only startup must never execute AI preparation.")
    monkeypatch.setattr("backend.ai.prepare.prepare", forbidden)
    monkeypatch.setattr("backend.ai.runner.Runner.__call__", forbidden)
    registry = RecordRegistry.from_inputs(inputs, manifest, records_path=workspace / "records.json")
    document = registry.document
    assert document.prepared.source_only is True
    assert document.prepared.batch.records == []
    assert document.prepared.batch.counts == c.prep_counts([])
    assert not document.prepared.templates and not document.prepared.mappings and not document.prepared.review_items
    assert len(registry.records) == 1
    record = registry.records[0]
    assert record.synthetic and record.fixture
    assert record.link.method == c.Method.EXACT_MATCH
    assert record.link.provenance is None and record.link.review is None
    assert registry.drawing_sections == {"D-001": "Synthetic Cell"}
    assert registry.sources_for("D-001/manifest/section")[0].says == "Synthetic Cell"
    assert registry.sources_for(record.id)[0].target.drawing_id == "D-001"
    registry.save()
    saved = read_records(workspace / "records.json")
    assert saved.prepared.source_only and saved.prepared.batch.counts.total_fields == 0
    assert registry() == registry.records
    assert registry.drawing_sections == {"D-001": "Synthetic Cell"}


def test_ambiguous_exact_candidates_stay_unselected_and_no_prep_is_invented(workspace):
    rows = [{"Name": name, "Part family": "Synthetic Cell", "Type": "Custom",
             "Datasheet": "SyntheticBracket.pdf"} for name in ("Synthetic bracket", "Synthetic bracket variant")]
    inputs, manifest = source_bundle(workspace, rows=rows)
    registry = RecordRegistry.from_inputs(inputs, manifest)
    assert len(registry.records) == 3
    link = registry.document.prepared.links[0]
    assert link.state == "ambiguous" and link.link.method == c.Method.UNRESOLVED
    assert link.link.bom_rows == [] and len(link.candidate_rows) == 2
    assert registry.part_for("D-001/part").bom == []
    assert registry.document.prepared.batch.counts.total_fields == 0
    assert registry.document.prepared.review_items == []


@pytest.mark.parametrize("changed", ["manifest", "drawing", "bom", "input-manifest-hash"])
def test_source_hash_and_manifest_bindings_reject_changed_originals(workspace, changed):
    inputs, manifest = source_bundle(workspace)
    if changed == "input-manifest-hash":
        payload = json.loads(inputs.read_text("utf-8"))
        payload["manifest_sha256"] = "0" * 64
        inputs.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path = {"manifest": manifest, "drawing": manifest.parent / "drawings/D-001.pdf",
                "bom": manifest.parent / "context/openlpbf-bom.csv"}[changed]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((RecordsError, ValueError)):
        RecordRegistry.from_inputs(inputs, manifest)


def test_source_changes_after_startup_fail_rebuild_and_protected_output(workspace):
    inputs, manifest = source_bundle(workspace)
    output = workspace / "records.json"
    registry = RecordRegistry.from_inputs(inputs, manifest, records_path=output)
    registry.save()
    before = output.read_bytes()
    pdf = manifest.parent / "drawings/D-001.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    with pytest.raises(RecordsError):
        registry()
    assert output.read_bytes() == before
    with pytest.raises(RecordsError):
        registry.save()


def test_source_only_boundary_does_not_accept_fabricated_preparation(workspace):
    inputs, manifest = source_bundle(workspace)
    registry = RecordRegistry.from_inputs(inputs, manifest)
    payload = registry.document.prepared.model_dump(mode="json")
    payload["source_only"] = False
    # An unresolved link in full mode needs its real attempted job; the
    # explicit source-only mode is the sole permission to omit that attempt.
    link = payload["links"][0]
    link["state"], link["link"]["method"], link["link"]["bom_rows"] = "unresolved", "unresolved", []
    with pytest.raises(ValueError, match="actual attempted job"):
        PreparedKnowledge.model_validate(payload)
    payload["source_only"] = True
    assert PreparedKnowledge.model_validate(payload).batch.counts.total_fields == 0
