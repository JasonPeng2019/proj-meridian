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
    Feature, OptionsField, Outline, PageGeometry, ReaderFailure, TemplateOption,
    VerificationOutput, bom_fact_name, bom_row_name, contract_digest, prep_counts,
    template_candidate_value,
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


def drawing(work, identity="D-001", *, scan=False, alternatives=False):
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
        if alternatives:
            words.append(DrawingWord(text="or", page=1, box=(182, 130, 12, 12)))
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


def proof(name, path="", *, number=None, refs=(), option=None):
    return dict(field=name, option=option, path=path,
        evidence=dict(number_ids=[number] if number else [], source_ids=list(refs), derivation=None))


def feature_value(kind="hole"):
    if kind == "slot":
        return dict(kind="slot", face="top", position={"x": 7, "y": 7}, width=5, length=12,
                    direction_deg=7, through=True, depth=None, pattern=None)
    return dict(kind="hole", hole_type="plain", face="top", position={"x": 7, "y": 7},
        diameter=5, through=True, depth=None, thread_size=None, thread_depth=None,
        countersink_diameter=None, countersink_angle_deg=None, counterbore_diameter=None,
        counterbore_depth=None, pattern=None)


def coverage_item(page, identity, slots=(), *, kind="hole", disposition="supported"):
    return dict(id=identity, description="SYNTHETIC machining group " + identity,
        source_ids=[page], view_ids=["main"], kind=kind, disposition=disposition, slot_ids=list(slots),
        face_interpretation="Entrance face is explicit in each mapped slot, or unresolved as stated.",
        depth_interpretation="Through/blind and stepped depths use mapped scalar proofs, or remain unresolved.",
        multiplicity_interpretation="Each slot preserves its singleton or complete repeated pattern.", reason=NOTE)


def set_coverage(fields, identity, items=()):
    page = f"{identity}/drawing/page/1"
    fields[f"{identity}/template/coverage"] = field(dict(complete=True, capacity_exceeded=False,
        views=[dict(id="main", description="SYNTHETIC main view and section", source_ids=[page],
                    feature_ids=[item["id"] for item in items])], features=deepcopy(list(items))), [page])


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
    for target in features:
        fields[target] = field({"kind": "absent"}, [page])
        entries.append(proof(target, "/kind", refs=[page]))
        if feature and target == features[0]:
            kind = "slot" if feature == "slot" else "hole"
            value = feature_value(kind)
            fields[target] = field(value, [page, numbers["7"], numbers["5"], *([numbers["12"]] if kind == "slot" else [])])
            entries.pop()
            entries.extend(proof(target, path, refs=[page])
                           for path in (("/kind", "/hole_type", "/face", "/through") if kind == "hole"
                                        else ("/kind", "/face", "/through")))
            entries.extend([proof(target, "/position/x", number=numbers["7"]),
                            proof(target, "/position/y", number=numbers["7"])])
            entries.extend([proof(target, "/diameter", number=numbers["5"])] if kind == "hole" else [
                proof(target, "/width", number=numbers["5"]), proof(target, "/length", number=numbers["12"]),
                proof(target, "/direction_deg", number=numbers["7"])])
    fields[name("proofs")] = field({"entries": entries}, [page])
    set_coverage(fields, identity, [coverage_item(page, "machining", [features[0]],
        kind="slot" if feature == "slot" else "hole")] if feature and features else [])
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
            # Hash the actual typed representation, including its defaults.
            # The host's candidate digest validator must remain strict.
            data = {"source_sha256": contract_digest(request.job.source),
                    "fields": {name: DeterminedField.model_validate(value).model_dump(mode="json")
                               for name, value in fields.items()}}
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
    slots = kwargs.pop("feature_slots", 2)
    return prep.prepare(paths[0], manifest=paths[1], image_root=work, output=work / "prepared.json",
                        runner=scripted.runner, feature_slots=slots, **kwargs)


def test_exact_boundary_atomic_save_and_cli_free_reload(work, monkeypatch):
    paths = inputs(work)
    scripted = Scripted(work, monkeypatch)
    saved = execute(work, scripted, paths)
    assert set(saved.model_dump()) == {"pipeline_version", "source_only", "input_sha256", "drawings", "bom_rows", "links",
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
        assert all("choose_option" not in item.allowed_actions and item.options == []
                   for item in saved.review_items)


def test_template_projection_keeps_proofs_and_only_verified_absence(work, monkeypatch):
    original = drawing(work, "D-013")
    saved = execute(work, Scripted(work, monkeypatch), inputs(work, [original]))
    template = saved.templates["D-013"]
    assert template.outline.value.length.value == 12
    assert template.outline.value.width.value == 7
    assert template.outline.value.length.evidence.number_ids == [original.numbers[0].name]
    assert template.thickness.value == 5
    assert template.features == []
    assert template.outline.essential and template.thickness.essential
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


@pytest.mark.parametrize("kind", ["hole", "slot"])
def test_known_feature_must_survive_frozen_contract_handoff(work, monkeypatch, kind):
    """Known hole and slot values survive ROOT's null-note representation fix."""
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            fields.update(template_fields(request.job, definition, feature=kind))

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    feature = saved.templates[original.id].features[0]
    assert feature.state == "known" and feature.value.kind == kind
    if kind == "hole":
        assert feature.value.diameter.value == 5
    else:
        assert feature.value.width.value == 5 and feature.value.length.value == 12
    assert feature.value.note is None and feature.essential
    candidate = feature.provenance.field_results[feature.name].accepted
    assert "note" not in candidate.value
    assert feature.provenance.rounds[-1].determination.output.fields[feature.name] == candidate
    assert prep.load_prepared(work / "prepared.json") == saved


@pytest.mark.parametrize("kind", ["hole", "slot"])
@pytest.mark.parametrize("change", ["geometry", "note"])
def test_known_feature_rejects_changed_geometry_and_non_null_note(work, monkeypatch, kind, change):
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            fields.update(template_fields(request.job, definition, feature=kind))

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    payload = saved.model_dump(mode="json")
    feature = payload["templates"][original.id]["features"][0]
    if change == "geometry":
        feature["value"]["diameter" if kind == "hole" else "width"]["value"] = 999
    else:
        feature["value"]["note"] = "Invented engineering note must not be normalized away"
    path = work / "altered-feature.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="exact|candidate|Template"):
        prep.load_prepared(path)


@pytest.mark.parametrize("unknown_essential", ["outline", "thickness"])
def test_unknown_hole_details_and_main_geometry_are_essential(work, monkeypatch, unknown_essential):
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            fields.update(template_fields(request.job, definition, feature="hole"))
            feature = f"{original.id}/template/feature-01"
            required = f"{original.id}/template/{unknown_essential}"
            page = f"{original.id}/drawing/page/1"
            fields[feature]["value"]["diameter"] = {"state": "unknown"}
            fields[f"{original.id}/template/coverage"]["value"]["features"][0]["disposition"] = "unresolved"
            fields[feature]["source_ids"] = [page, original.numbers[1].name]
            fields[required] = field(refs=[page])
            ledger = fields[f"{original.id}/template/proofs"]["value"]["entries"]
            ledger[:] = [entry for entry in ledger if entry["field"] != required and not (
                entry["field"] == feature and entry["path"] == "/diameter")]

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    template = saved.templates[original.id]
    major = getattr(template, unknown_essential)
    assert major.state == "unknown" and major.essential
    hole = template.features[0]
    assert hole.state == "known" and hole.essential
    assert hole.value.diameter.state == "unknown" and hole.value.diameter.essential
    assert hole.provenance == template.provenance == hole.value.diameter.provenance
    assert hole.value.diameter.provenance.source.inputs
    assert template.features[1].state == "unknown" and template.features[1].essential
    assert prep.load_prepared(work / "prepared.json") == saved


def detail_numbers(original):
    """Additional invented printed tokens; no real D-series dimensions."""
    for index, value in enumerate((0, 2, 3, 90)):
        box = (300 + 25 * index, 200, 20, 12)
        original.numbers.append(DrawingNumber(name=f"{original.id}/drawing/n/detail-{value}@1",
            text=str(value), value=value, page=1, box=box))
        original.words.append(DrawingWord(text=str(value), page=1, box=box))
    return original


def set_geometry(fields, identity, suffix, value, numbers):
    """Author fixture values/proofs together; assertions below check preservation."""
    target, page = f"{identity}/template/{suffix}", f"{identity}/drawing/page/1"
    entries = fields[f"{identity}/template/proofs"]["value"]["entries"]
    entries[:] = [entry for entry in entries if entry["field"] != target]
    refs = set()

    def leaves(item, path=""):
        if item is None or item == {"state": "unknown"}:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                leaves(child, path + "/" + key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                leaves(child, path + f"/{index}")
        elif type(item) in {int, float}:
            token = numbers[str(item)]
            entries.append(proof(target, path, number=token))
            refs.add(token)
        else:
            entries.append(proof(target, path, refs=[page]))
            refs.add(page)

    leaves(value)
    fields[target] = field(value, sorted(refs or {page}))


def test_complete_holes_counterbores_countersinks_blind_depths_and_slot_patterns_project_intact(work, monkeypatch):
    original = detail_numbers(drawing(work, "D-013"))
    hole = feature_value()
    hole.update(diameter=2, position={"x": 5, "y": 5}, hole_type="counterbored",
        counterbore_diameter=3, counterbore_depth=2,
        pattern=dict(type="circle", count=3, radius=3, start_angle_deg=0, evenly_spaced=True, angles_deg=None))
    blind = feature_value()
    blind.update(diameter=2, position={"x": 7, "y": 5}, through=False, depth=3,
                 hole_type="countersunk", countersink_diameter=3, countersink_angle_deg=90)
    slot = feature_value("slot")
    slot.update(width=2, length=3, position={"x": 5, "y": 5}, direction_deg=0,
                pattern=dict(type="row", count=2, spacing=3, direction_deg=0))
    values = [hole, blind, slot]

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            numbers = {n.text: n.name for n in original.numbers}
            set_geometry(fields, original.id, "outline", dict(type="rectangle", length=12, width=12), numbers)
            items = []
            for index, value in enumerate(values, 1):
                suffix = f"feature-{index:02d}"
                set_geometry(fields, original.id, suffix, value, numbers)
                items.append(coverage_item(f"{original.id}/drawing/page/1", f"group-{index}",
                    [f"{original.id}/template/{suffix}"], kind=value["kind"]))
            set_coverage(fields, original.id, items)

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]), feature_slots=3)
    template = saved.templates[original.id]
    assert len(template.features) == 3 and all(f.state == "known" and f.essential for f in template.features)
    assert [template_candidate_value(f.value) for f in template.features] == [dict(v, note=None) for v in values]
    counterbore, countersink, slots = [f.value for f in template.features]
    assert counterbore.counterbore_diameter.value == 3 and counterbore.counterbore_depth.value == 2
    assert counterbore.pattern.count.value == 3 and counterbore.pattern.radius.value == 3
    assert counterbore.pattern.start_angle_deg.value == 0
    assert not countersink.through and countersink.depth.value == 3
    assert countersink.countersink_diameter.value == 3 and countersink.countersink_angle_deg.value == 90
    assert slots.pattern.count.value == 2 and slots.pattern.spacing.value == 3 and slots.pattern.direction_deg.value == 0
    assert counterbore.counterbore_depth.essential and counterbore.pattern.count.essential and slots.pattern.count.essential
    for projected, expected in zip(template.features, values):
        candidate = template.provenance.field_results[projected.name].accepted
        assert candidate.value == expected and "note" not in candidate.value
    assert prep.load_prepared(work / "prepared.json") == saved


@pytest.mark.parametrize("detail", ["placement", "depth", "count", "counterbore_depth", "entrance_face"])
def test_unknown_significant_physical_detail_creates_essential_feature_blocker(work, monkeypatch, detail):
    original = detail_numbers(drawing(work, "D-013"))

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            numbers = {n.text: n.name for n in original.numbers}
            value = feature_value()
            if detail == "placement":
                value["position"]["x"] = {"state": "unknown"}
            elif detail == "depth":
                value.update(through=False, depth={"state": "unknown"})
            elif detail == "count":
                value["pattern"] = dict(type="row", count={"state": "unknown"}, spacing=3, direction_deg=0)
            elif detail == "counterbore_depth":
                value.update(hole_type="counterbored", counterbore_diameter=7, counterbore_depth={"state": "unknown"})
            set_geometry(fields, original.id, "feature-01", value, numbers)
            if detail == "entrance_face":
                target = f"{original.id}/template/feature-01"
                fields[target] = field(refs=[f"{original.id}/drawing/page/1"])
                entries = fields[f"{original.id}/template/proofs"]["value"]["entries"]
                entries[:] = [entry for entry in entries if entry["field"] != target]
            item = coverage_item(f"{original.id}/drawing/page/1", "unresolved-hole",
                [f"{original.id}/template/feature-01"], disposition="unresolved")
            item["reason"] = f"Original views do not establish {detail}; no geometry default is authorized."
            item["depth_interpretation"] = "A depth written in this inventory is never a scalar proof."
            set_coverage(fields, original.id, [item])

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    template = saved.templates[original.id]
    assert template.features[0].essential
    blocker = next(f for f in template.features if f.name.endswith("/coverage/unresolved-hole"))
    assert blocker.state == "unknown" and blocker.essential
    assert detail in blocker.message and blocker.evidence.source_ids == [f"{original.id}/drawing/page/1"]
    assert template.provenance == blocker.provenance and len(template.provenance.rounds) == 1
    assert prep.load_prepared(work / "prepared.json") == saved


@pytest.mark.parametrize("kind", ["pocket", "indent", "recess", "hole", "chamfer"])
def test_unsupported_significant_features_block_and_only_explicit_minor_cosmetics_can_be_omitted(work, monkeypatch, kind):
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            item = coverage_item(f"{original.id}/drawing/page/1", "detail", kind=kind,
                disposition="cosmetic_omission" if kind == "chamfer" else "unsupported")
            item.update(face_interpretation="Left side view entrance.",
                reason="Explicit minor edge break may be omitted." if kind == "chamfer" else
                       "Significant drawn detail cannot be represented by the supported flat geometry.")
            set_coverage(fields, original.id, [item])

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    template = saved.templates[original.id]
    assert len(template.features) == 1
    feature = template.features[0]
    assert feature.state == "unknown" and feature.essential == (kind != "chamfer")
    assert feature.evidence.source_ids == [f"{original.id}/drawing/page/1"]
    assert "Left side" in feature.message and feature.provenance == template.provenance
    # A saved consumer cannot remove the blocker or soften essentiality.
    if feature.essential:
        payload = saved.model_dump(mode="json")
        payload["templates"][original.id]["features"] = []
        altered = work / "omitted-blocker.json"
        altered.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValidationError, match="Saved template differs"):
            prep.load_prepared(altered)


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unclaimed", "overflow"])
def test_inventory_incompleteness_blocks_even_with_accepted_outer_geometry(work, monkeypatch, defect):
    original = drawing(work, "D-013")

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            fields.update(template_fields(request.job, definition, feature="hole"))
            inventory = f"{original.id}/template/coverage"
            value = fields[inventory]["value"]
            if defect == "missing":
                fields[inventory] = field(refs=[f"{original.id}/drawing/page/1"])
            elif defect == "duplicate":
                value["features"][0]["slot_ids"] *= 2
            elif defect == "unclaimed":
                value["features"] = []
                value["views"][0]["feature_ids"] = []
            elif defect == "overflow":
                value.update(complete=False, capacity_exceeded=True)
                overflow = coverage_item(f"{original.id}/drawing/page/1", "overflow", disposition="unresolved")
                overflow["reason"] = "A further drawn pattern exceeds this job's fixed slot capacity."
                value["features"].append(overflow)
                value["views"][0]["feature_ids"].append("overflow")

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    template = saved.templates[original.id]
    assert template.outline.state == template.thickness.state == "known"
    assert template.features[0].state == "known" and template.features[0].essential
    blocker = next(f for f in template.features if f.name.endswith("/coverage"))
    assert blocker.state == "unknown" and blocker.essential
    inventory = f"{original.id}/template/coverage"
    assert template.provenance.field_results[inventory].accepted is None
    assert saved.batch.counts.unverified_fallback == 0
    assert prep.load_prepared(work / "prepared.json") == saved


@pytest.mark.parametrize("final_verdict", ["disagrees", "unsure", "execution_failed"])
def test_coverage_disagreement_retains_both_rounds_and_cannot_become_fallback(work, monkeypatch, final_verdict):
    original = drawing(work, "D-013")
    holder = {}

    def customize(request, definition, fields):
        if not definition.job.startswith("vision.template.") or isinstance(request, DeterminationRequest):
            return
        inventory = f"{original.id}/template/coverage"
        if request.round == 2 and final_verdict == "execution_failed":
            return holder["scripted"].runner._attempt(request, status="execution_failed", failure=ReaderFailure(
                classification="provider_error", execution_failure=True, message=NOTE,
                troubleshooting=["Synthetic verifier execution failed after a real coverage disagreement."]))
        fields[inventory] = FieldVerification(verdict="disagrees" if request.round == 1 else final_verdict,
            reason="Section view shows a significant unlisted recess.",
            source_ids=request.candidate.fields[inventory].source_ids)

    scripted = holder["scripted"] = Scripted(work, monkeypatch, customize=customize)
    saved = execute(work, scripted, inputs(work, [original]))
    record = next(record for record in saved.batch.records if record.job == f"vision.template.{original.id}")
    assert len(record.rounds) == 2 and record.mode == "determine_verify"
    assert record.rounds[0].verification.output.fields[f"{original.id}/template/coverage"].verdict == "disagrees"
    assert record.field_results[f"{original.id}/template/coverage"].accepted is None
    assert record.rounds[1].determination.output.fields[f"{original.id}/template/coverage"].value["features"] == []
    if final_verdict == "execution_failed":
        assert original.id not in saved.templates  # No accepted final geometry; never resurrect round one.
    else:
        assert any(f.state == "unknown" and f.essential for f in saved.templates[original.id].features)
    assert saved.batch.counts.unverified_fallback == 0


def printed_thickness_fields(request, definition):
    fields = template_fields(request, definition)
    bundle = definition.evidence(request)
    drawing = bundle.inputs["drawing"].value
    identity = drawing["id"]
    name = f"{identity}/template/thickness"
    group = next(iter(bundle.inputs["inventory"].value["printed_alternatives"]))
    numbers = {n["text"]: n["name"] for n in drawing["numbers"]}
    fields[name] = {**field(refs=[numbers["7"], numbers["5"], group]),
                    "state": "options", "confidence": "sure", "options": [7, 5], "basis": "printed_alternatives"}
    entries = fields[f"{identity}/template/proofs"]["value"]["entries"]
    entries[:] = [entry for entry in entries if entry["field"] != name]
    entries.extend([proof(name, number=numbers["7"], option=0), proof(name, number=numbers["5"], option=1)])
    return fields


def test_printed_numeric_options_preserve_own_proofs_order_and_choose_action(work, monkeypatch):
    original = drawing(work, "D-013", alternatives=True)

    def customize(request, definition, fields):
        if definition.job.startswith("vision.template.") and isinstance(request, DeterminationRequest):
            fields.update(printed_thickness_fields(request.job, definition))

    saved = execute(work, Scripted(work, monkeypatch, customize=customize), inputs(work, [original]))
    thickness = saved.templates[original.id].thickness
    assert thickness.state == "options" and thickness.basis == "printed_alternatives"
    assert [option.value for option in thickness.options] == [7, 5]
    assert [option.evidence.number_ids for option in thickness.options] == [
        [original.numbers[1].name], [original.numbers[2].name]]
    review = next(item for item in saved.review_items if item.applies_to == thickness.name)
    assert review.options == [7, 5] and "choose_option" in review.allowed_actions
    assert review.status == "pending" and review.review is None
    assert thickness.provenance.field_results[thickness.name].accepted.options == [7, 5]
    assert all("choose_option" not in item.allowed_actions for item in saved.review_items
               if item.applies_to != thickness.name)
    assert prep.load_prepared(work / "prepared.json") == saved


@pytest.mark.parametrize("kind", ["outline", "hole", "slot"])
def test_composite_option_conversion_uses_option_leaf_proofs_without_root_proof(work, kind):
    """Conversion fixture only: current M09/FlatTemplate allow scalar options.

    Use existing generic native contracts to verify the representation without
    fabricating a model verdict, accepted domain field, batch count or approval.
    """
    original = drawing(work, "D-013", alternatives=True)
    page = f"{original.id}/drawing/page/1"
    numbers = {n.text: n.name for n in original.numbers}
    name = f"{original.id}/template/{'outline' if kind == 'outline' else 'feature-01'}"
    first = {"type": "rectangle", "length": 12, "width": 7} if kind == "outline" else feature_value(kind)
    if kind != "outline":
        first["diameter" if kind == "hole" else "width"] = 7
    second = deepcopy(first)
    second["width" if kind in {"outline", "slot"} else "diameter"] = 5
    values = [first, second]
    proofs = {}

    def leaves(value, path=""):
        if isinstance(value, dict):
            return [leaf for k, v in value.items() for leaf in leaves(v, path + "/" + k)]
        return [] if value is None else [(path, value)]

    for option, value in enumerate(values):
        for path, leaf in leaves(value):
            entry = proof(name, path, number=numbers[str(leaf)] if type(leaf) is int else None,
                          refs=[] if type(leaf) is int else [page], option=option)
            proofs[(name, option, path)] = entry["evidence"]
    assert not any(path == "" for _, _, path in proofs)
    projected = [dict(value=prep._template_value(value, name, index, proofs, record=None, essential=kind == "outline"),
                      evidence=prep._template_evidence(name, index, proofs)) for index, value in enumerate(values)]
    option_type = TemplateOption[Outline] if kind == "outline" else TemplateOption[Feature]
    options = [option_type.model_validate(value) for value in projected]
    container_type = OptionsField[Outline] if kind == "outline" else OptionsField[Feature]
    container = container_type(name=name, method="cleanup_rule", options=options)
    assert container.provenance is None and container.review is None
    for index, option in enumerate(container.options):
        result = template_candidate_value(option.value)
        if kind != "outline":
            assert result.pop("note") is None
        assert result == values[index]
        expected_refs = {numbers[str(v)] for _, v in leaves(values[index]) if type(v) is int}
        assert set(option.evidence.number_ids) == expected_refs
        assert option.evidence.source_ids == [page]
    assert container.options[0].value.position.x.name != container.options[1].value.position.x.name if kind != "outline" else (
        container.options[0].value.width.name != container.options[1].value.width.name)
