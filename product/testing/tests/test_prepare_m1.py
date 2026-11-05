"""Remote-only M11 fixtures; no live CLI, corpus output or human decisions.

From product/testing on Actions:
../development/.venv/bin/python -B -m pytest -q -p no:cacheprovider
  --basetemp=tmp/A11-pytest --junitxml=reports/ci/A11-preparation.xml tests/test_prepare_m1.py
The real M08 job loop runs with an in-memory stage transport; domain jobs,
source snapshots, downstream construction, contracts and publication are real.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw
import pytest
from pydantic import ValidationError
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend.ai import prepare as prep  # noqa: E402
from backend.ai import matching, vision_jobs  # noqa: E402
from backend.ai.runner import EvidenceError, Runner  # noqa: E402
from backend.contracts import (  # noqa: E402
    BOMField, BOMRow, DeterminationOutput, DeterminationRequest, DeterminedField,
    DrawingEvidence, DrawingField, DrawingNumber, DrawingWord, FieldVerification,
    PageGeometry, ReaderFailure, VerificationOutput, bom_fact_name, bom_row_name,
    contract_digest, prep_counts, template_candidate_value,
)


NOTE = "Invented M11 fixture only; no real engineering evidence or human review."
BOXES = {"title": (700, 500, 200, 50), "notes": (400, 500, 300, 80),
         "company": (700, 550, 90, 30), "material": (400, 580, 200, 30),
         "weight": (600, 580, 100, 30), "date": (400, 610, 80, 25),
         "drawn": (480, 610, 100, 25), "scale": (580, 610, 100, 25)}


@pytest.fixture
def work():
    parent = ROOT / "testing/tmp/A11-preparation"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as folder:
        yield Path(folder)


def drawing(work, identity="D-001", *, scan=False):
    fields = {}
    for key, box in BOXES.items():
        value = None if scan else {"title": "SYNTHETIC Bracket", "material": "Alloy X"}.get(key)
        fields[key] = DrawingField(name=f"{identity}/drawing/{key}", original=value, value=value,
            confidence="sure" if value else "unsure", method="unresolved" if scan else "parsed",
            page=1, box=box, source_quality="degraded" if scan else "clean", note=NOTE)
    numbers, words = [], []
    if not scan:
        for text, value, box in [("12", 12, (100, 100, 18, 12)), ("7", 7, (160, 130, 8, 12)),
                                  ("5", 5, (210, 130, 8, 12))]:
            numbers.append(DrawingNumber(name=f"{identity}/drawing/n/{text}@1", text=text,
                value=value, page=1, box=box))
            words.append(DrawingWord(text=text, page=1, box=box))
    image = Image.new("RGB", (1000, 700), "white")
    canvas = ImageDraw.Draw(image)
    for key, (x, y, w, h) in BOXES.items():
        canvas.text((x + 2, y + 2), "SYNTHETIC " + key, fill="black")
    path = work / f"images/{identity}-p1.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return DrawingEvidence(id=identity, pages=1, image=f"images/{identity}-p1.png",
        page_geometry=[PageGeometry(page=1, source_width=1000, source_height=700,
                                   image_width=1000, image_height=700)],
        degraded=scan, source_quality="degraded" if scan else "clean",
        source_path=f"dataset/drawings/{identity}.pdf", source_sha256=contract_digest({"fixture": identity}),
        fields=fields, numbers=numbers, words=words)


def row(name="Bracket", *, datasheet="Bracket.pdf", display="BOM-001"):
    values = dict(name=name, section="Cell", type="Custom", datasheet=datasheet, material=["Metal X"])
    fields = {key: BOMField(name=bom_fact_name("Cell", name, key), value=value,
        original=", ".join(value) if isinstance(value, list) else value, method="parsed")
        for key, value in values.items()}
    return BOMRow(name=bom_row_name("Cell", name), display_id=display, display_name=name, section="Cell",
                  source_sha256=contract_digest({"fixture": values}), fields=fields)


def inputs(work, drawings=None, rows=None, *, filename="Bracket.pdf"):
    drawings = drawings if drawings is not None else [drawing(work)]
    rows = rows if rows is not None else [row()]
    manifest = work / "manifest.json"
    manifest.write_text(json.dumps({"synthetic": True, "note": NOTE, "assets": [{
        "id": d.id, "path": d.source_path, "sha256": d.source_sha256,
        "source_path": f"SYNTHETIC/Cell/{filename}", "subsystem": "Cell"} for d in drawings]}), encoding="utf-8")
    path = work / "inputs.json"
    path.write_text(json.dumps({"schema": "meridian-deterministic-inputs/v1", "scope": NOTE,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "drawings": [d.model_dump(mode="json") for d in drawings],
        "bom": [r.model_dump(mode="json") for r in rows]}, ensure_ascii=False), encoding="utf-8")
    return path, manifest


def field(value=None, refs=(), *, state=None):
    state = state or ("unknown" if value is None else "known")
    return dict(state=state, value=value, options=[], confidence="unsure" if state == "unknown" else "sure",
                reason=NOTE, source_ids=list(refs), schema_valid=False, evidence_valid=False)


def proof(name, path="", *, number=None, refs=()):
    return dict(field=name, option=None, path=path,
        evidence=dict(number_ids=[number] if number else [], source_ids=list(refs), derivation=None))


def template_fields(request, definition, *, feature=False):
    source = definition.evidence(request).inputs["drawing"].value
    identity = source["id"]
    page = f"{identity}/drawing/page/1"
    numbers = {n["text"]: n["name"] for n in source["numbers"]}
    fields = {name: field(refs=[page]) for name in request.field_names}
    name = lambda suffix: f"{identity}/template/{suffix}"
    fields[name("outline")] = field({"type": "rectangle", "length": 12, "width": 7},
                                     [page, numbers["12"], numbers["7"]])
    fields[name("thickness")] = field(5, [numbers["5"]])
    entries = [proof(name("outline"), "/type", refs=[page]),
               proof(name("outline"), "/length", number=numbers["12"]),
               proof(name("outline"), "/width", number=numbers["7"]),
               proof(name("thickness"), number=numbers["5"])]
    features = [n for n in fields if n.rsplit("/", 1)[-1].startswith("feature-")]
    if features:
        target = features[0]
        fields[target] = field({"kind": "absent"}, [page])
        entries.append(proof(target, "/kind", refs=[page]))
        if feature:
            value = dict(kind="hole", hole_type="plain", face="top", position={"x": 7, "y": 7},
                diameter=5, through=True, depth=None, thread_size=None, thread_depth=None,
                countersink_diameter=None, countersink_angle_deg=None, counterbore_diameter=None,
                counterbore_depth=None, pattern=None)
            fields[target] = field(value, [page, numbers["7"], numbers["5"]])
            entries.pop()
            entries.extend(proof(target, path, refs=[page])
                           for path in ("/kind", "/hole_type", "/face", "/through"))
            entries.extend([proof(target, "/position/x", number=numbers["7"]),
                            proof(target, "/position/y", number=numbers["7"]),
                            proof(target, "/diameter", number=numbers["5"])])
    fields[name("proofs")] = field({"entries": entries}, [page])
    return fields


class Scripted:
    """Replace transport only. M08 still owns every round and retry decision."""

    def __init__(self, work, monkeypatch, *, customize=None):
        config = yaml.safe_load((ROOT / "development/ai_settings.yaml").read_text(encoding="utf-8"))["prep"]

        @contextmanager
        def no_child():
            raise AssertionError("Fixture transport must never launch a child CLI")
            yield

        self.runner = Runner(jobs={}, prep_settings=config, workspace_root=ROOT,
            runtime_root=work / "runtime", reserve_cli_slot=no_child, environment={}, min_interval_seconds=0)
        self.calls, self.customize = [], customize
        monkeypatch.setattr(self.runner, "_stage", self.stage)

    def stage(self, request, definition, evidence, directory, not_before=None):
        self.calls.append(request)
        if isinstance(request, DeterminationRequest):
            bundle = definition.evidence(request.job)
            if definition.job.startswith("vision.scan."):
                fields = {name: field("SYNTHETIC Bracket" if name.endswith("/title") else
                    "Alloy X" if name.endswith("/material") else None, [name]) for name in request.job.field_names}
            elif definition.job.startswith("vision.template."):
                fields = template_fields(request.job, definition)
            else:
                context = bundle.inputs["context"].value
                name = request.job.field_names[0]
                if context["stage"] == "links":
                    rows = bundle.inputs["registry"].value["bom"]
                    first = rows[0]
                    fields = {name: field({"drawing_id": context["drawing_id"], "bom_rows": [first["name"]]},
                        [f"{context['drawing_id']}/source", first["fields"]["datasheet"]["name"]], state="match")}
                else:
                    refs = [matching.LINKS_REF, *context["occurrences"][0]["source_ids"]]
                    fields = {name: field({"relationship": "same", "to_name": context["to_name"]},
                                         refs, state="relationship")}
            if self.customize:
                replacement = self.customize(request, definition, fields)
                if replacement is not None:
                    return replacement
            data = {"source_sha256": contract_digest(request.job.source), "fields": fields}
            candidate = DeterminationOutput(**data, candidate_sha256=contract_digest(data))
            candidate = definition.validate_candidate(candidate, request.job.source)
            return self.runner._attempt(request, status="success", output=candidate)
        verdicts = {name: FieldVerification(verdict="verified" if f.state != "unknown" and f.schema_valid
            and f.evidence_valid else "unsure", reason=NOTE, source_ids=f.source_ids)
            for name, f in request.candidate.fields.items()}
        if self.customize:
            replacement = self.customize(request, definition, verdicts)
            if replacement is not None:
                return replacement
        data = dict(candidate_sha256=request.candidate.candidate_sha256,
                    source_sha256=contract_digest(request.job.source),
                    fields={n: v.model_dump(mode="json") for n, v in verdicts.items()})
        output = VerificationOutput(**data, verification_sha256=contract_digest(data))
        return self.runner._attempt(request, status="success", output=output)


def execute(work, scripted, paths, **kwargs):
    return prep.prepare(paths[0], manifest=paths[1], image_root=work, output=work / "prepared.json",
                        runner=scripted.runner, feature_slots=2, **kwargs)


def test_exact_boundary_atomic_save_and_cli_free_reload(work, monkeypatch):
    paths = inputs(work)
    scripted = Scripted(work, monkeypatch)
    saved = execute(work, scripted, paths)
    assert set(saved.model_dump()) == {"pipeline_version", "input_sha256", "drawings", "bom_rows", "links",
        "mappings", "templates", "review_items", "batch"}
    assert saved.input_sha256 == hashlib.sha256(paths[0].read_bytes()).hexdigest()
    assert saved.links[0].link.method == "exact_match"
    assert saved.templates == {}
    assert all(m.review.status == "not_reviewed" for m in saved.mappings)
    assert all(item.status == "pending" for item in saved.review_items)
    monkeypatch.setattr(prep, "Runner", lambda **kw: pytest.fail("Loader constructed a runner"))
    monkeypatch.setattr(vision_jobs, "build_scan_job", lambda *a, **kw: pytest.fail("Loader rebuilt scan"))
    monkeypatch.setattr(matching, "MatchingRegistry", lambda *a, **kw: pytest.fail("Loader rebuilt matching"))
    # No original inputs, images or account homes are needed to load the boundary.
    paths[0].unlink()
    paths[1].unlink()
    assert prep.load_prepared(work / "prepared.json") == saved
    assert not list(work.glob("prepared.json.*.tmp"))


def test_final_scan_correction_precedes_registry_and_uses_actual_corner_crops(work, monkeypatch):
    original = drawing(work, scan=True)
    paths = inputs(work, [original], [row(datasheet=None)], filename="UnrelatedSheet.pdf")

    def customize(request, definition, fields):
        if not definition.job.startswith("vision.scan."):
            return
        title = original.fields["title"].name
        if isinstance(request, DeterminationRequest):
            fields[title]["value"] = "SYNTHETIC wrong" if request.round == 1 else "Bracket"
            if request.round == 2:
                assert request.feedback.fields[title].verdict == "disagrees"
        elif request.round == 1:
            fields[title] = FieldVerification(verdict="disagrees", reason=NOTE, source_ids=[title])

    scripted = Scripted(work, monkeypatch, customize=customize)
    saved = execute(work, scripted, paths)
    projected = saved.drawings[0]
    assert projected.fields["title"].value == "Bracket"
    assert projected.fields["title"].original is None
    assert projected.fields["title"].method == "ai_verified_after_retry"
    assert len(projected.fields["title"].provenance.rounds) == 2
    assert original.fields["title"].value is None
    assert saved.links[0].link.method == "exact_match"
    # The unresolved scan fields retain rounds but do not create review tasks.
    assert {r.applies_to for r in saved.review_items if r.kind == "scan_reading"} == {
        original.fields["title"].name, original.fields["material"].name}
    link_start = next(i for i, r in enumerate(scripted.calls) if r.job.job.startswith("relationships/"))
    assert all(r.job.job.startswith("vision.scan.") for r in scripted.calls[:link_start])
    source_hashes = projected.fields["title"].provenance.source.inputs
    for request in scripted.calls[link_start:]:
        bundle = scripted.runner.jobs[request.job.job].evidence(request.job)
        images = [item for item in bundle.inputs.values() if item.image]
        assert images and all(item.path.is_relative_to(work / "runtime/corner-crops") for item in images)
        assert all(item.sha256 in source_hashes.values() for item in images)
        assert hashlib.sha256((work / original.image).read_bytes()).hexdigest() not in {i.sha256 for i in images}


def test_every_non_exact_link_attempt_finishes_before_mapping_including_unresolved(work, monkeypatch):
    drawings = [drawing(work), drawing(work, "D-002")]
    rows = [row(), row("Bracket plate", display="BOM-002")]
    paths = inputs(work, drawings, rows)

    def customize(request, definition, fields):
        if (isinstance(request, DeterminationRequest) and definition.job.startswith("relationships/link/")
                and request.job.job_id == "D-002/link"):
            name = request.job.field_names[0]
            fields[name] = field(refs=["D-002/source"])

    saved = execute(work, scripted := Scripted(work, monkeypatch, customize=customize), paths)
    assert [r.state for r in saved.links] == ["matched", "unresolved"]
    assert all(link.link.provenance is not None for link in saved.links)
    requests = [r for r in scripted.calls if isinstance(r, DeterminationRequest)]
    positions = {r.job.job_id: i for i, r in enumerate(requests)}
    mapping_positions = [i for i, r in enumerate(requests) if not r.job.job.startswith("relationships/link/")]
    assert mapping_positions and min(mapping_positions) > positions["D-002/link"] > positions["D-001/link"]
    assert saved.batch.counts.unresolved >= 1


def test_link_correction_changes_mapping_context_and_never_approves_proposal(work, monkeypatch):
    rows = [row(), row("Bracket plate", display="BOM-002")]
    paths = inputs(work, rows=rows)

    def customize(request, definition, fields):
        if not definition.job.startswith("relationships/link/"):
            return
        name = request.job.field_names[0]
        if isinstance(request, DeterminationRequest) and request.round == 2:
            fields[name] = field({"drawing_id": "D-001", "bom_rows": [rows[1].name]},
                ["D-001/source", rows[1].fields["datasheet"].name], state="match")
        elif not isinstance(request, DeterminationRequest) and request.round == 1:
            fields[name] = FieldVerification(verdict="disagrees", reason=NOTE,
                                             source_ids=request.candidate.fields[name].source_ids)

    saved = execute(work, scripted := Scripted(work, monkeypatch, customize=customize), paths)
    assert saved.links[0].link.bom_rows == [rows[1].name]
    assert saved.links[0].link.method == "ai_verified_after_retry"
    for request in scripted.calls:
        if definition := scripted.runner.jobs[request.job.job]:
            if definition.job.startswith(("relationships/section/", "relationships/material/")):
                context = definition.evidence(request.job).inputs["context"].value
                assert all(o["row"] == rows[1].name for o in context["occurrences"])
                assert context["links"][0]["link"]["bom_rows"] == [rows[1].name]
                assert len(context["links"][0]["link"]["provenance"]["rounds"]) == 2
    assert all(m.review.status == "not_reviewed" for m in saved.mappings)


@pytest.mark.parametrize("failure", ["disagrees", "unsure", "execution_failed"])
def test_retry_bound_and_truthful_separate_counts(work, monkeypatch, failure):
    paths = inputs(work, rows=[row(), row("Bracket plate", display="BOM-002")])
    holder = {}

    def customize(request, definition, fields):
        if definition.job.startswith("relationships/link/") and not isinstance(request, DeterminationRequest):
            name = request.job.field_names[0]
            if failure == "execution_failed":
                return holder["scripted"].runner._attempt(request, status="execution_failed", failure=ReaderFailure(
                    classification="provider_error", execution_failure=True, message=NOTE,
                    troubleshooting=["Synthetic initial Opus launch failed; no answer was returned."]))
            fields[name] = FieldVerification(verdict=failure, reason=NOTE,
                                             source_ids=request.candidate.fields[name].source_ids)

    scripted = holder["scripted"] = Scripted(work, monkeypatch, customize=customize)
    saved = execute(work, scripted, paths)
    record = saved.links[0].link.provenance
    assert len(record.rounds) == (2 if failure == "disagrees" else 1)
    assert record.mode == ("single_model_unverified" if failure == "execution_failed" else "determine_verify")
    counts = saved.batch.counts
    assert counts == prep_counts(saved.batch.records)
    assert counts.total_fields == counts.first_pass_verified + counts.retry_verified + counts.unresolved + counts.unverified_fallback
    summary = prep.preparation_summary(saved)
    assert summary["review_items"] == len(saved.review_items)
    assert summary["single_model_unverified"] == counts.unverified_fallback
    if failure == "execution_failed":
        assert counts.unverified_fallback == 1 and counts.execution_failed_attempts == 1
        before = len(scripted.calls)
        execute(work, scripted, paths)
        assert any(not isinstance(r, DeterminationRequest) and r.job.job_id == "D-001/link"
                   for r in scripted.calls[before:]), "Each launch must attempt the primary verifier again"
    else:
        assert saved.links[0].state == "unresolved" and saved.links[0].link.bom_rows == []
        assert counts.unverified_fallback == 0


def test_template_projection_keeps_proofs_unknown_slots_and_only_verified_absence(work, monkeypatch):
    original = drawing(work, "D-013")
    saved = execute(work, Scripted(work, monkeypatch), inputs(work, [original]))
    template = saved.templates["D-013"]
    assert template.outline.value.length.value == 12
    assert template.outline.value.width.value == 7
    assert template.outline.value.length.evidence.number_ids == [original.numbers[0].name]
    assert template.thickness.value == 5
    assert len(template.features) == 1 and template.features[0].state == "unknown"
    assert template.material.state == "unknown" and template.weight_on_drawing.state == "unknown"
    assert template.source_sha256 == template.provenance.source.inputs["drawing"]
    assert prep.load_prepared(work / "prepared.json") == saved
    record = template.provenance
    assert template_candidate_value(template.outline) == record.field_results[template.outline.name].accepted.value


def test_unverified_absence_is_retained_unknown_and_not_counted_verified(work, monkeypatch):
    original = drawing(work, "D-013")
    holder = {}

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and not isinstance(request, DeterminationRequest):
            return holder["scripted"].runner._attempt(request, status="execution_failed", failure=ReaderFailure(
                classification="provider_error", execution_failure=True, message=NOTE,
                troubleshooting=["Synthetic Opus execution failure before any answer."]))

    scripted = holder["scripted"] = Scripted(work, monkeypatch, customize=customize)
    saved = execute(work, scripted, inputs(work, [original]))
    template = saved.templates[original.id]
    assert template.filled_by == "single_model_unverified"
    assert len(template.features) == 2 and all(f.state == "unknown" for f in template.features)
    assert template.thickness.method == "ai_single_model"
    assert template.provenance.rounds[0].verification.output is None
    assert saved.batch.counts.unverified_fallback >= 4


def test_no_accepted_geometry_does_not_invent_template(work, monkeypatch):
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            page = f"{original.id}/drawing/page/1"
            fields.update({name: field(refs=[page]) for name in fields})

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    assert saved.templates == {}
    assert any(item.kind == "template_field" and item.ai_answers for item in saved.review_items)


def test_domain_invalid_verdict_quarantines_raw_rounds_and_preserves_previous_publication(work, monkeypatch):
    original = drawing(work, scan=True)
    paths = inputs(work, [original])
    previous = b"historical publication remains unchanged\n"
    (work / "prepared.json").write_bytes(previous)

    def customize(request, definition, fields):
        if definition.job.startswith("vision.scan.") and not isinstance(request, DeterminationRequest):
            name = original.fields["title"].name
            # Generic M08 ownership allows this OTHER field ID; M09 must reject it.
            fields[name] = FieldVerification(verdict="verified", reason=NOTE,
                                             source_ids=[original.fields["material"].name])

    with pytest.raises(prep.PreparationError) as caught:
        execute(work, Scripted(work, monkeypatch, customize=customize), paths)
    assert (work / "prepared.json").read_bytes() == previous
    diagnostic = json.loads(caught.value.diagnostic.read_bytes())
    assert diagnostic["published"] is False
    assert diagnostic["quarantined_unresolved_fields"] == 8
    assert diagnostic["publication_counts"]["first_pass_verified"] == 0
    assert diagnostic["publication_counts"]["unverified_fallback"] == 0
    assert diagnostic["raw_domain_invalid_result"]["rounds"][0]["verification"]["output"] is not None


@pytest.mark.parametrize("change", ["inputs", "manifest", "image"])
def test_source_change_aborts_publication_without_fallback(work, monkeypatch, change):
    paths = inputs(work)
    scripted = Scripted(work, monkeypatch)
    stage = scripted.stage
    changed = False

    def transport(*args, **kwargs):
        nonlocal changed
        result = stage(*args, **kwargs)
        if not changed:
            changed = True
            target = paths[0] if change == "inputs" else paths[1] if change == "manifest" else work / "images/D-001-p1.png"
            target.write_bytes(target.read_bytes() + b" ")
        return result

    monkeypatch.setattr(scripted.runner, "_stage", transport)
    with pytest.raises((prep.PreparationError, EvidenceError)):
        execute(work, scripted, paths)
    assert not (work / "prepared.json").exists()


def test_changed_source_rebuilds_registry_and_mapping_identity_each_launch(work, monkeypatch):
    paths = inputs(work)
    scripted = Scripted(work, monkeypatch)
    first = execute(work, scripted, paths)
    first_calls = len(scripted.calls)
    payload = json.loads(paths[0].read_bytes())
    payload["drawings"][0]["fields"]["material"].update(original="Alloy Y", value="Alloy Y")
    paths[0].write_text(json.dumps(payload), encoding="utf-8")
    second = execute(work, scripted, paths)
    assert first.input_sha256 != second.input_sha256
    assert first.links[0].registry_sha256 != second.links[0].registry_sha256
    assert {m.from_name for m in first.mappings if m.kind == "material"} == {"Alloy X"}
    assert {m.from_name for m in second.mappings if m.kind == "material"} == {"Alloy Y"}
    assert all(r.job.source != scripted.calls[0].job.source for r in scripted.calls[first_calls:])


@pytest.mark.parametrize("corrupt", ["pipeline", "count", "link", "mapping_approval", "template_value", "duplicate_job"])
def test_saved_boundary_rejects_incoherent_or_fabricated_values(work, monkeypatch, corrupt):
    saved = execute(work, Scripted(work, monkeypatch), inputs(work, [drawing(work, "D-013")]))
    payload = saved.model_dump(mode="json")
    if corrupt == "pipeline":
        payload["pipeline_version"] = "dual_reader/v0"
    elif corrupt == "count":
        payload["batch"]["counts"]["first_pass_verified"] += 1
    elif corrupt == "link":
        payload["links"][0]["link"]["bom_rows"] = ["BOM:invented/nonexistent"]
    elif corrupt == "mapping_approval":
        payload["mappings"][0]["review"].update(status="human_confirmed", by="invented human",
            at=datetime.now(timezone.utc).isoformat())
    elif corrupt == "template_value":
        payload["templates"]["D-013"]["thickness"]["value"] = 999
    else:
        payload["batch"]["records"].append(deepcopy(payload["batch"]["records"][0]))
        payload["batch"]["counts"] = prep_counts([*saved.batch.records, saved.batch.records[0]]).model_dump(mode="json")
    path = work / "corrupt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        prep.load_prepared(path)


def test_initial_manifest_hash_mismatch_never_runs_model(work, monkeypatch):
    paths = inputs(work)
    paths[1].write_bytes(paths[1].read_bytes() + b" ")
    scripted = Scripted(work, monkeypatch)
    with pytest.raises(prep.PreparationError):
        execute(work, scripted, paths)
    assert scripted.calls == [] and not (work / "prepared.json").exists()


def test_atomic_replace_failure_keeps_old_file_and_cleans_temporary(work, monkeypatch):
    paths = inputs(work)
    output = work / "prepared.json"
    output.write_bytes(b"older historical evidence\n")
    replace = prep.os.replace

    def refuse(source, target):
        if Path(target) == output:
            raise OSError("Synthetic publication failure")
        return replace(source, target)

    monkeypatch.setattr(prep.os, "replace", refuse)
    with pytest.raises(prep.PreparationError):
        execute(work, Scripted(work, monkeypatch), paths)
    assert output.read_bytes() == b"older historical evidence\n"
    assert not list(work.glob("prepared.json.*.tmp"))


def test_explicit_command_uses_host_reservation_and_saved_boundary(work, monkeypatch, capsys):
    paths = inputs(work)
    scripted = Scripted(work, monkeypatch)
    monkeypatch.setattr(prep, "Runner", lambda **kwargs: scripted.runner)
    result = prep.main(["--inputs", str(paths[0]), "--manifest", str(paths[1]), "--image-root", str(work),
        "--output", str(work / "prepared.json"), "--runtime-root", str(work / "runtime")],
        reserve_cli_slot=scripted.runner.reserve_cli_slot)
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["input_sha256"] == prep.load_prepared(work / "prepared.json").input_sha256
    with pytest.raises(SystemExit) as caught:
        prep.main(["--inputs", str(paths[0]), "--manifest", str(paths[1]), "--output", str(work / "no.json"),
                   "--runtime-root", str(work / "runtime")])
    assert caught.value.code == 2 and not (work / "no.json").exists()


def test_known_feature_must_survive_frozen_contract_handoff(work, monkeypatch):
    """Required behavior; current M09/M02 note-default mismatch is escalated.

    This deliberately asserts the required end-to-end result, rather than
    weakening the test to accept an unsupported projection. ROOT must reconcile
    the frozen candidate/native feature interface before M11 can qualify.
    """
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            fields.update(template_fields(request.job, definition, feature=True))

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    feature = saved.templates[original.id].features[0]
    assert feature.state == "known" and feature.value.diameter.value == 5
    assert prep.load_prepared(work / "prepared.json") == saved
