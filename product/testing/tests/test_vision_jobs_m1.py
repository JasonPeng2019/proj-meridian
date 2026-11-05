"""Remote-only M09 checks. All drawings/images/CLI outcomes here are synthetic.

From testing/: ../development/.venv/bin/python -B -m pytest -q -p no:cacheprovider
  --basetemp=tmp/A09-pytest --junitxml=reports/ci/A09-vision.xml tests/test_vision_jobs_m1.py
No PDF regeneration, real prep readers, human decisions or source-derived
engineering conclusions are exercised by this focused module suite.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw
import pytest
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend.ai.runner import CliReservation, EvidenceError, Runner  # noqa: E402
from backend.ai.vision_jobs import (  # noqa: E402
    CORNER_FIELDS, build_scan_job, build_template_job, scan_readings, template_review_details,
    validate_vision_result,
)
from backend.contracts import (  # noqa: E402
    DeterminationOutput, DeterminedField, DrawingEvidence, DrawingField,
    DrawingNumber, DrawingWord, PageGeometry, PrepProvenance, contract_digest,
    customer_review_status, prep_counts, template_fact_name,
)


NOTE = "Invented M09 evidence; no real drawing or model review."
PEER = ROOT / "testing/fixtures/runner/scripted_cli.py"
BOXES = {"title": (700, 500, 200, 50), "notes": (400, 500, 300, 80),
         "company": (700, 550, 90, 30), "material": (400, 580, 200, 30),
         "weight": (600, 580, 100, 30), "date": (400, 610, 80, 25),
         "drawn": (480, 610, 100, 25), "scale": (580, 610, 100, 25)}


@pytest.fixture
def work():
    directory = ROOT / "testing/tmp/A09-vision"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=directory) as folder:
        yield Path(folder)


def drawing(work, identifier="D-013", *, scan=False, pages=1, alternatives=False):
    fields, numbers, words, geometries = {}, [], [], []
    for page in range(1, pages + 1):
        geometries.append(PageGeometry(page=page, source_width=1000, source_height=700,
                                       image_width=2000, image_height=1400))
        for key, box in BOXES.items():
            field_key = key if page == 1 else f"{key}-p{page}"
            text = None if scan else {"material": "SYNTHETIC alloy", "weight": "14.0"}.get(key)
            fields[field_key] = DrawingField(name=f"{identifier}/drawing/{field_key}", original=text,
                value=text, confidence="sure" if text else "unsure", method="unresolved" if scan else "parsed",
                note=NOTE, page=page, box=box, source_quality="degraded" if scan else "clean")
        if not scan:
            for token, value, box in [
                ("12", 12, (100, 100, 18, 12)), ("7", 7, (160, 130, 8, 12)),
                ("5", 5, (210, 130, 8, 12)), ("8", 8, (100, 2, 8, 12)),
                ("14.0", 14, (650, 585, 30, 12)),
            ]:
                name = f"{identifier}/drawing/n/{token.replace('.', '-')}@{page}"
                numbers.append(DrawingNumber(name=name, text=token, value=value, page=page, box=box))
                words.append(DrawingWord(text=token, page=page, box=box))
            if alternatives:
                words.append(DrawingWord(text="or", page=page, box=(182, 130, 12, 12)))
        image = Image.new("RGB", (2000, 1400), "white")
        canvas = ImageDraw.Draw(image)
        for key, box in BOXES.items():
            x, y, w, h = box
            canvas.rectangle((2*x, 2*y, 2*(x+w)-1, 2*(y+h)-1), outline="black")
            canvas.text((2*x+3, 2*y+3), f"SYNTHETIC {key} page {page}", fill="black")
        for word in words:
            if word.page == page:
                canvas.text((2*word.box[0], 2*word.box[1]), word.text, fill="black")
        path = work / f"images/{identifier}-p{page}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    return DrawingEvidence(id=identifier, pages=pages, image=f"images/{identifier}-p1.png",
        page_geometry=geometries, degraded=scan, source_quality="degraded" if scan else "clean",
        source_path=f"SYNTHETIC/{identifier}.pdf", source_sha256=hashlib.sha256(NOTE.encode()).hexdigest(),
        fields=fields, numbers=numbers, words=words)


def name(job, suffix):
    return next(n for n in job.request.field_names if n.endswith("/" + suffix))


def number(d, token):
    return next(n.name for n in d.numbers if n.text == token)


def page_ref(d):
    return f"{d.id}/drawing/page/1"


def known(value, refs, **updates):
    item = dict(state="known", value=value, options=[], confidence="sure", source_ids=refs,
                reason=NOTE, basis=None)
    item.update(updates)
    return item


def unknown(refs):
    return dict(state="unknown", value=None, options=[], confidence="unsure", source_ids=refs,
                reason=NOTE, basis=None)


def proof(field, ids=(), *, path="", option=None, source_ids=(), derivation=None):
    return {"field": field, "option": option, "path": path,
            "evidence": {"number_ids": list(ids), "source_ids": list(source_ids), "derivation": derivation}}


def template_fields(job, d, *, value=7, token="7"):
    fields = {n: unknown([page_ref(d)]) for n in job.request.field_names}
    target, proofs = name(job, "thickness"), name(job, "proofs")
    fields[target] = known(value, [number(d, token)])
    fields[proofs] = known({"entries": [proof(target, [number(d, token)])]}, [page_ref(d)])
    return fields


def checked(job, fields):
    host = {n: DeterminedField(**v, schema_valid=False, evidence_valid=False) for n, v in fields.items()}
    data = {"source_sha256": contract_digest(job.request.source),
            "fields": {n: f.model_dump(mode="json") for n, f in host.items()}}
    candidate = DeterminationOutput(**data, candidate_sha256=contract_digest(data))
    result = job.definition.validate_candidate(candidate, job.request.source)
    for field in result.fields:
        assert result.fields[field].model_dump(exclude={"schema_valid", "evidence_valid"}) == host[field].model_dump(
            exclude={"schema_valid", "evidence_valid"}), "A validator repaired a candidate"
    return result


def sol(fields):
    return {"role": "determination", "answer": {"fields": deepcopy(fields)}}


def opus(fields, *, verdicts=None, alternatives=None, action=None):
    verdicts, alternatives = verdicts or {}, alternatives or {}
    step = {"role": "verification", "answer": {"fields": {n: {
        "verdict": verdicts.get(n, "unsure" if f["state"] == "unknown" else "verified"),
        "reason": NOTE, "source_ids": f["source_ids"], "alternative": alternatives.get(n),
    } for n, f in fields.items()}}}
    if action:
        step["action"] = action
    return step


def runner(work, job, steps):
    scenario = work / "scenario.json"
    scenario.write_text(json.dumps({"steps": steps, "calls": [], "active": 0}), encoding="utf-8")

    @contextmanager
    def reserved_scripted_child():
        # Only the synthetic Python peer is spawned, and only on remote Actions.
        yield CliReservation(total_cli_processes=2, owner_counted=True)

    config = yaml.safe_load((ROOT / "development/ai_settings.yaml").read_text(encoding="utf-8"))["prep"]
    instance = Runner(jobs={job.definition.job: job.definition}, prep_settings=config, workspace_root=ROOT,
        runtime_root=work / "runtime", reserve_cli_slot=reserved_scripted_child,
        executables={cli: [sys.executable, "-B", str(PEER), "--script-role", role, "--scenario", str(scenario)]
                     for cli, role in (("codex", "determination"), ("claude", "verification"))},
        environment=dict(os.environ), timeout_seconds=10, min_interval_seconds=0, rate_cooldown_seconds=0)
    return instance, scenario


def test_scan_only_whole_corner_crops_and_exact_text_per_page(work):
    d = drawing(work, "D-003", scan=True, pages=3)
    job = build_scan_job(d, image_root=work, crop_dir=work / "corners")
    bundle = job.definition.evidence(job.request)
    assert len(job.request.field_names) == 3 * len(CORNER_FIELDS)
    assert all(k.startswith("crop:") for k, v in bundle.inputs.items() if v.image)
    assert set(job.request.source.source_ids) == set(job.request.field_names)
    metadata = bundle.inputs["inventory"].value
    for field in d.fields.values():
        region = metadata["fields"][field.name]
        assert region["whole_field"] and region["page"] == field.page and region["box"] == list(field.box)
        with Image.open(work / f"images/{d.id}-p{field.page}.png") as source:
            with Image.open(bundle.inputs[region["input_key"]].path) as crop:
                assert crop.tobytes() == source.crop(tuple(region["pixel_bounds"])).tobytes()
                assert crop.width < source.width and crop.height < source.height
    text = "MiXeD text, Ø7\nsecond line."
    fields = {n: known(text, [n]) for n in job.request.field_names}
    result = checked(job, fields)
    assert all(f.value == text and f.schema_valid and f.evidence_valid for f in result.fields.values())
    one, other = job.request.field_names[:2]
    fields[one]["source_ids"] = [other]
    assert not checked(job, fields).fields[one].evidence_valid


def test_scan_rejects_placeholders_missing_boxes_and_stale_source(work):
    d = drawing(work, "D-001", scan=True)
    job = build_scan_job(d, image_root=work, crop_dir=work / "corners")
    fields = {n: unknown([n]) for n in job.request.field_names}
    title = d.fields["title"].name
    fields[title] = known("Description", [title])
    assert not checked(job, fields).fields[title].schema_valid
    fields[title] = unknown([title])
    item = checked(job, fields).fields[title]
    assert item.value is None and item.confidence == "unsure"
    bad = d.model_copy(deep=True)
    bad.fields["title"] = bad.fields["title"].model_copy(update={"box": (0, 0, 0, 0)})
    with pytest.raises(EvidenceError):
        build_scan_job(bad, image_root=work, crop_dir=work / "bad")
    image = work / "images/D-001-p1.png"
    image.write_bytes(image.read_bytes() + b"SYNTHETIC source change")
    with pytest.raises(EvidenceError, match="page changed"):
        job.definition.evidence(job.request)


@pytest.mark.parametrize("identifier", ["D-013", "D-025", "D-026"])
def test_supported_template_inventories_are_bound_and_answers_unseeded(work, identifier):
    d = drawing(work, identifier)
    job = build_template_job(d, image_root=work, feature_slots=2)
    bundle = job.definition.evidence(job.request)
    assert bundle.inputs["drawing"].value == d.model_dump(mode="json")
    assert job.request.source.inputs == {k: v.sha256 for k, v in bundle.inputs.items()}
    assert job.request == job.definition.request(job.request.job_id, job.request.source)
    assert "candidate" in job.definition.verification_instructions
    fields = template_fields(job, d)
    output = checked(job, fields)
    assert output.fields[name(job, "thickness")].evidence_valid
    assert output.fields[name(job, "outline")].value is None
    assert output.candidate_sha256 != contract_digest({})
    changed = build_template_job(d, image_root=work, feature_slots=3)
    assert job.request.source != changed.request.source
    assert job.request.output_contract_sha256 != changed.request.output_contract_sha256
    assert job.request.determination_prompt_sha256 != job.request.verification_prompt_sha256


@pytest.mark.parametrize("value,token", [(9, "7"), (8, "8"), (14, "14.0"), (True, "7"), (-7, "7")])
def test_numeric_validation_rejects_invention_grid_corner_values_and_bad_types(work, value, token):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    item = checked(job, template_fields(job, d, value=value, token=token)).fields[name(job, "thickness")]
    assert not item.evidence_valid


@pytest.mark.parametrize("expression,expected,valid", [
    ("n0 - n1", 5, True), ("n0 / 2", 6, True), ("n0 + 13", 25, False),
    ("n0 / (n0-n0)", 6, False), ("n0 ** 2", 144, False),
    ("__import__('os').getcwd()", 6, False), ("n9", 6, False), ("2", 2, False),
])
def test_only_recorded_bounded_arithmetic_is_supported(work, expression, expected, valid):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields = template_fields(job, d)
    target, ledger = name(job, "thickness"), name(job, "proofs")
    ids = [number(d, "12"), number(d, "7")] if expression == "n0 - n1" else [number(d, "12")]
    fields[target] = known(expected, ids)
    derivation = {"kind": "arithmetic", "expression": expression, "inputs": ids, "pattern_fact": None}
    fields[ledger]["value"]["entries"] = [proof(target, ids, derivation=derivation)]
    assert checked(job, fields).fields[target].evidence_valid is valid


def test_pattern_requires_original_fact_and_each_nested_numeric_leaf_has_its_own_proof(work):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields = template_fields(job, d)
    target, ledger = name(job, "outline"), name(job, "proofs")
    a, b, page = number(d, "12"), number(d, "7"), page_ref(d)
    fields[target] = known({"type": "rectangle", "length": 12, "width": 7}, [a, b, page])
    entries = fields[ledger]["value"]["entries"]
    entries.extend([proof(target, path="/type", source_ids=[page]), proof(target, [a], path="/length"),
                    proof(target, [b], path="/width")])
    assert checked(job, fields).fields[target].evidence_valid
    entries.pop()
    assert not checked(job, fields).fields[target].evidence_valid
    entries.append(proof(target, [b], path="/width", derivation={"kind": "pattern", "expression": "n0",
                   "inputs": [b], "pattern_fact": "INVENTED/pattern"}))
    assert not checked(job, fields).fields[target].evidence_valid
    entries[-1]["evidence"]["derivation"]["pattern_fact"] = page
    assert checked(job, fields).fields[target].evidence_valid
    entries.append(deepcopy(entries[-1]))
    assert not checked(job, fields).fields[name(job, "thickness")].evidence_valid


def test_recorded_circle_pattern_constants_and_declared_units_are_checked(work):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields = template_fields(job, d)
    target, ledger = name(job, "feature-01"), name(job, "proofs")
    token, radius, diameter, page = number(d, "12"), number(d, "7"), number(d, "5"), page_ref(d)
    fields[target] = known({"kind": "hole", "hole_type": "plain", "face": "top",
        "position": {"x": 0, "y": 0}, "diameter": 5, "through": True, "depth": None,
        "thread_size": None, "thread_depth": None, "countersink_diameter": None,
        "countersink_angle_deg": None, "counterbore_diameter": None, "counterbore_depth": None,
        "pattern": {"type": "circle", "count": 12, "radius": 7, "start_angle_deg": 30,
                    "evenly_spaced": True, "angles_deg": None}}, [token, radius, diameter, page])
    entries = fields[ledger]["value"]["entries"]
    for path in ("/kind", "/hole_type", "/face", "/through", "/pattern/type", "/pattern/evenly_spaced"):
        entries.append(proof(target, path=path, source_ids=[page]))
    for path in ("/position/x", "/position/y"):
        entries.append(proof(target, [radius], path=path, derivation={"kind": "pattern", "expression": "n0-n0",
                       "inputs": [radius], "pattern_fact": page}))
    entries.extend([proof(target, [diameter], path="/diameter"), proof(target, [token], path="/pattern/count"),
                    proof(target, [radius], path="/pattern/radius"), proof(target, [token], path="/pattern/start_angle_deg",
                    derivation={"kind": "pattern", "expression": "360 / n0", "inputs": [token], "pattern_fact": page})])
    assert checked(job, fields).fields[target].evidence_valid
    entries[-1]["evidence"]["derivation"]["kind"] = "arithmetic"
    assert not checked(job, fields).fields[target].evidence_valid
    different_units = d.model_copy(deep=True)
    different_units.numbers = [n.model_copy(update={"unit": "in"}) if n.text == "7" else n
                               for n in different_units.numbers]
    other_job = build_template_job(different_units, image_root=work, feature_slots=1)
    assert not checked(other_job, template_fields(other_job, different_units)).fields[name(other_job, "thickness")].evidence_valid


@pytest.mark.parametrize("printed", [False, True])
def test_options_need_a_real_printed_connector_and_each_own_number(work, printed):
    d = drawing(work, alternatives=printed)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields = template_fields(job, d)
    target, ledger = name(job, "thickness"), name(job, "proofs")
    a, b = number(d, "7"), number(d, "5")
    groups = job.definition.evidence(job.request).inputs["inventory"].value["printed_alternatives"]
    fields[target] = known(None, [a, b, *groups], state="options", options=[7, 5], basis="printed_alternatives")
    fields[ledger]["value"]["entries"] = [proof(target, [a], option=0), proof(target, [b], option=1)]
    assert checked(job, fields).fields[target].evidence_valid is printed
    fields[ledger]["value"]["entries"][1]["evidence"]["number_ids"] = [a]
    assert not checked(job, fields).fields[target].evidence_valid


def test_material_weight_thread_and_feature_shape_are_independently_checked(work):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields = template_fields(job, d)
    material, weight, ledger = name(job, "material"), name(job, "weight-on-drawing"), name(job, "proofs")
    page, mat_id, weight_id = page_ref(d), d.fields["material"].name, number(d, "14.0")
    fields[material] = known("SYNTHETIC alloy", [mat_id, page])
    fields[weight] = known(14, [weight_id])
    fields[ledger]["value"]["entries"].extend([
        proof(material, source_ids=[mat_id, page]), proof(weight, [weight_id])])
    result = checked(job, fields)
    assert result.fields[material].evidence_valid and result.fields[weight].evidence_valid
    fields[material]["value"] = "Guessed material"
    assert not checked(job, fields).fields[material].evidence_valid
    fields[material]["value"] = "SYNTHETIC alloy"
    feature = name(job, "feature-01")
    fields[feature] = known({"kind": "hole", "hole_type": "threaded", "face": "top",
        "position": {"x": 7, "y": 7}, "diameter": 5, "through": False, "depth": None,
        "thread_size": "M999", "thread_depth": None, "countersink_diameter": None,
        "countersink_angle_deg": None, "counterbore_diameter": None, "counterbore_depth": None,
        "pattern": None}, [page, number(d, "7"), number(d, "5")])
    entries = fields[ledger]["value"]["entries"]
    for path in ("/kind", "/hole_type", "/face", "/thread_size", "/through"):
        entries.append(proof(feature, path=path, source_ids=[page]))
    entries.extend([proof(feature, [number(d, "7")], path="/position/x"),
                    proof(feature, [number(d, "7")], path="/position/y"),
                    proof(feature, [number(d, "5")], path="/diameter")])
    assert not checked(job, fields).fields[feature].schema_valid
    fields[feature]["value"]["depth"] = {"state": "unknown"}
    assert not checked(job, fields).fields[feature].evidence_valid  # No printed M999.
    fields[feature]["value"]["thread_size"] = {"state": "unknown"}
    entries[:] = [p for p in entries if p["path"] != "/thread_size"]
    assert checked(job, fields).fields[feature].evidence_valid


def test_rejects_wrong_drawing_overlays_unowned_refs_and_mutated_input(work):
    d = drawing(work)
    with pytest.raises(EvidenceError):
        build_template_job(drawing(work, "D-014"), image_root=work)
    bad = d.model_copy(deep=True)
    bad.fields["material"] = bad.fields["material"].model_copy(update={"method": "ai_agreed"})
    with pytest.raises(EvidenceError, match="original deterministic"):
        build_template_job(bad, image_root=work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields = template_fields(job, d)
    fields[name(job, "thickness")]["source_ids"].append("D-025/drawing/n/7@1")
    assert not checked(job, fields).fields[name(job, "thickness")].evidence_valid
    bundle = job.definition.evidence(job.request)
    bundle.inputs["drawing"].value["numbers"][0]["value"] = 999
    assert job.definition.evidence(job.request).inputs["drawing"].value == d.model_dump(mode="json")
    image = work / "images/D-013-p1.png"
    image.write_bytes(image.read_bytes() + b"SYNTHETIC MUTATION")
    with pytest.raises(EvidenceError):
        job.definition.evidence(job.request)


def test_scripted_verification_receives_exact_candidate_original_images_and_whole_field_sources(work):
    d = drawing(work, "D-001", scan=True)
    job = build_scan_job(d, image_root=work, crop_dir=work / "corners")
    fields = {n: unknown([n]) for n in job.request.field_names}
    title = d.fields["title"].name
    fields[title] = known("Exact, multiline\nSYNTHETIC text", [title])
    instance, scenario = runner(work, job, [sol(fields), opus(fields)])
    record = instance(job.request)
    calls = json.loads(scenario.read_text(encoding="utf-8"))["calls"]
    assert [c["role"] for c in calls] == ["determination", "verification"]
    assert calls[1]["prompt"]["candidate"] == record.rounds[0].determination.output.model_dump(mode="json")
    assert calls[1]["prompt"]["original_evidence"] == calls[0]["prompt"]["original_evidence"]
    assert len(calls[0]["images"]) == len(CORNER_FIELDS)
    assert record.field_results[title].status == "first_pass_verified"
    readings = scan_readings(job, d, record)
    assert readings["title"].value == fields[title]["value"] and readings["title"].original is None
    assert readings["title"].box == d.fields["title"].box
    assert readings["notes"].value is None and readings["notes"].method == "unresolved"
    assert all(f.review is None for f in readings.values())


@pytest.mark.parametrize("scan", [True, False])
def test_domain_final_check_rejects_wrong_field_verdict_evidence_without_rewriting_rounds(work, scan):
    d = drawing(work, "D-001" if scan else "D-013", scan=scan)
    job = (build_scan_job(d, image_root=work, crop_dir=work / "corners") if scan else
           build_template_job(d, image_root=work, feature_slots=1))
    if scan:
        fields = {n: unknown([n]) for n in job.request.field_names}
        target, wrong_ref = d.fields["title"].name, d.fields["notes"].name
        fields[target] = known("Synthetic title", [target])
    else:
        fields = template_fields(job, d)
        target, wrong_ref = name(job, "thickness"), number(d, "12")
    verifier = opus(fields)
    verifier["answer"]["fields"][target]["source_ids"] = [wrong_ref]
    instance, _ = runner(work, job, [sol(fields), verifier])
    record = instance(job.request)
    original = record.model_dump_json()
    with pytest.raises(EvidenceError, match="exact candidate field"):
        validate_vision_result(job, record)
    assert record.model_dump_json() == original


def test_scripted_disagreement_uses_sol_revision_and_bound_opus_reverification(work):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    target, ledger = name(job, "thickness"), name(job, "proofs")
    wrong, corrected = template_fields(job, d, value=9), template_fields(job, d)
    verifier = opus(wrong, verdicts={target: "disagrees", ledger: "unsure"},
                    alternatives={target: deepcopy(corrected[target])})
    instance, scenario = runner(work, job, [sol(wrong), verifier, sol(corrected), opus(corrected)])
    record = instance(job.request)
    assert len(record.rounds) == 2 and record.field_results[target].status == "retry_verified"
    assert record.field_results[target].accepted.value == 7
    calls = json.loads(scenario.read_text(encoding="utf-8"))["calls"]
    assert calls[2]["prompt"]["previous_candidate"] == record.rounds[0].determination.output.model_dump(mode="json")
    assert calls[2]["prompt"]["verifier_feedback"] == record.rounds[0].verification.output.model_dump(mode="json")
    assert calls[3]["prompt"]["candidate"] == record.rounds[1].determination.output.model_dump(mode="json")
    assert calls[0]["prompt"]["original_evidence"] == calls[3]["prompt"]["original_evidence"]
    assert record.rounds[1].verification.output.candidate_sha256 != record.rounds[0].verification.output.candidate_sha256


@pytest.mark.parametrize("last_action", ["disagrees", "unsure", "oauth", "malformed"])
def test_persistent_disagreement_never_promotes_opus_alternative_or_fallback(work, last_action):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields, target = template_fields(job, d), name(job, "thickness")
    alternative = known(12, [number(d, "12")])
    disagree = opus(fields, verdicts={target: "disagrees"}, alternatives={target: alternative})
    last = opus(fields, verdicts={target: last_action}) if last_action in {"disagrees", "unsure"} else opus(fields, action=last_action)
    instance, _ = runner(work, job, [sol(fields), disagree, sol(fields), last])
    record = instance(job.request)
    assert len(record.rounds) == 2 and record.mode == "determine_verify"
    assert record.field_results[target].accepted is None
    details = template_review_details(job, record)[target]
    assert details["status"] == "unresolved" and details["accepted"] is None
    assert [r["candidate"]["value"] for r in details["rounds"]] == [7, 7]
    assert details["rounds"][0]["verdict"]["alternative"]["value"] == 12
    assert details["rounds"][1]["missing_opus_output"] == (last_action in {"oauth", "malformed"})


def test_actual_scripted_opus_execution_failure_is_unverified_and_opus_retries_next_launch(work):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields, target = template_fields(job, d), name(job, "thickness")
    instance, scenario = runner(work, job, [sol(fields), opus(fields, action="oauth"), opus(fields)])
    first = instance(job.request)
    assert first.mode == "single_model_unverified"
    assert first.field_results[target].status == "unverified_fallback"
    assert first.field_results[target].accepted.value == 7
    assert prep_counts([first]).first_pass_verified == 0
    details = template_review_details(job, first)[target]["rounds"][0]
    assert details["missing_opus_output"] and details["failure"]["execution_failure"]
    assert customer_review_status(usable=True, current_source_hashes=first.source.inputs,
                                  provenance=first, field_name=target) == "Unavailable"
    second = instance(job.request)
    assert second.field_results[target].status == "first_pass_verified"
    calls = json.loads(scenario.read_text(encoding="utf-8"))["calls"]
    assert [c["role"] for c in calls] == ["determination", "verification", "verification"]
    assert calls[2]["prompt"]["candidate"] == calls[1]["prompt"]["candidate"]
    assert customer_review_status(usable=True, current_source_hashes=second.source.inputs,
                                  provenance=second, field_name=target) == "AI reviewed"


@pytest.mark.parametrize("action", ["blind_guess", "skip_image_read", "wrong_image"])
def test_invalid_or_blind_verifier_output_is_unresolved_and_not_execution_fallback(work, action):
    d = drawing(work)
    job = build_template_job(d, image_root=work, feature_slots=1)
    fields, target = template_fields(job, d), name(job, "thickness")
    instance, _ = runner(work, job, [sol(fields), opus(fields, action=action)])
    record = instance(job.request)
    assert record.field_results[target].accepted is None and record.mode == "determine_verify"
    assert record.rounds[0].verification.status == "invalid_output"
    assert not record.rounds[0].verification.failure.execution_failure
    assert template_review_details(job, record)[target]["rounds"][0]["missing_opus_output"]
    with pytest.raises(EvidenceError):
        template_review_details(job, record.model_copy(update={"job_id": "ANOTHER CANDIDATE"}))
    assert PrepProvenance.model_validate_json(record.model_dump_json()) == record
