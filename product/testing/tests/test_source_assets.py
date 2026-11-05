"""Remote composition checks using isolated, explicitly synthetic boundaries.

Run from testing: python -B -m pytest -q -p no:cacheprovider tests/test_source_assets.py
No extraction, CAD, reader, API or real decision store is used. GLB/STEP bytes
are inert transport fixtures, not engineering geometry or source fidelity proof.
"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from test_source_runtime import MARKERS, ROOT, source_bundle, workspace
from backend import contracts as c
from backend.ai.prepare import PreparedKnowledge
from backend.app.main import create_app
from backend.loader.decisions import DecisionStore
from backend.loader.records import RecordRegistry
from backend.settings import Settings, load_settings


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=")
GLBS = {"A": b"glTF\x02\0\0\0\x14\0\0\0SYNTHA!!", "B": b"glTF\x02\0\0\0\x14\0\0\0SYNTHB!!"}
STEP = b"ISO-10303-21;\n/* Synthetic byte boundary only */\nEND-ISO-10303-21;\n"
HASHES = {
    "png": "f6d6acb2dcf66d4e1b6419962726cf72cb16371556bc7dbdfd4e66e2caee2b8c",
    "glbA": "aee8d6a0efaaba740618c575b31a01521834e7038ee67058f0af8e62bf4a545e",
    "glbB": "d1bf64c9fbf6ebfe6e5ce672d963f506baf6ca28be293081fbebeaab464bc2cc",
    "step": "c08e5a63fe2ffb9fead3db885a84ad635ee1e45ca34bfed2544dbc8f0a20a675",
}
AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


def settings_for(workspace, monkeypatch):
    for name in ("MERIDIAN_INPUTS_PATH", "MERIDIAN_CHAT_HISTORY_DIR", "MERIDIAN_SECRETS_DIR", "MERIDIAN_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    data = deepcopy(load_settings().data)
    data["paths"].update(dataset="generated/inputs/source/dataset", decisions="decisions", chat_history="chat_history")
    data["chat"]["credentials"]["secrets_dir"] = "absent-synthetic-secrets"
    return Settings(root=workspace, data=data)


def package(workspace):
    inputs, manifest = source_bundle(workspace / "generated/inputs")
    payload = json.loads(inputs.read_bytes())
    drawing = payload["drawings"][0]
    drawing.update(image="images/D-001-p1.png", pages=2)
    drawing["page_geometry"].append({**drawing["page_geometry"][0], "page": 2})
    inputs.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    for page in (1, 2):
        image = inputs.parent / f"images/D-001-p{page}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(PNG)
    projected = RecordRegistry.from_inputs(inputs, manifest).document.prepared.model_dump(mode="json")
    projected["source_only"] = False  # Exact parsed link; no invented AI job.
    prepared = PreparedKnowledge.model_validate(projected)
    (workspace / "generated/prepared.json").write_text(prepared.model_dump_json(), encoding="utf-8")
    return inputs, manifest


def load_package(workspace, inputs, manifest, store=None):
    return RecordRegistry.from_paths(prepared_path=workspace / "generated/prepared.json", inputs_path=inputs,
        manifest_path=manifest, records_path=workspace / "generated/records.json", decisions=store,
        asset_root=workspace)


def model_files(workspace, registry):
    """Existing builder-manifest boundary, with invented source-bound fields.

    This corpus deliberately has no prepared template. Its intact older geometry
    must stay stale across restart, retaining B as a synthetic selected variant.
    """
    record = registry.part_for("D-001/part")
    proof = dict(number_ids=[record.drawing.numbers[0].name])

    def known(name, value, evidence):
        return dict(name="D-001/template/" + name, method="parsed", state="known", value=value, evidence=evidence)

    template = c.FlatTemplate(**MARKERS, part="D-001", filled_by="human",
        source_sha256=record.drawing.source_sha256,
        outline=known("outline", dict(type="circle", diameter=known("diameter", 4, proof)),
                      dict(source_ids=["D-001/source"])), thickness=known("thickness", 4, proof))
    directory = workspace / "generated/models/synthetic/D-001/transport-fixture"
    directory.mkdir(parents=True)
    examples, artifacts = [], {}
    for example in ("A", "B"):
        paths = {}
        for extension, raw in (("glb", GLBS[example]), ("step", STEP)):
            path = directory / f"D-001_{example}.{extension}"
            path.write_bytes(raw)
            value = path.relative_to(workspace).as_posix()
            paths[extension] = value
            artifacts[value] = dict(bytes=len(raw), sha256=HASHES["glb" + example if extension == "glb" else "step"])
        examples.append(c.ModelExample(id=example, **paths, choices={"synthetic-variant": example},
            source_ids=["D-001/source"], volume_mm3=1))
    built = c.ModelStatus(state="available", examples=examples, built_at=AT,
        built_template_sha256=c.contract_digest(template), current_template_sha256=c.contract_digest(template),
        overall_size_mm=(4, 4, 4), message="Synthetic transport fixture only.")
    manifest = dict(schema="flat-cad/v1", template=template.model_dump(mode="json"),
        template_sha256=c.contract_digest(template), source_sha256=template.source_sha256,
        status=built.model_dump(mode="json"), artifacts=artifacts)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    saved = built.model_copy(deep=True, update=dict(state="stale", selected_example="B",
        stale_reason="No current prepared template exists in this synthetic boundary."))
    registry.set_model_status(record.id, saved)
    return directory, template


def test_missing_package_has_no_implicit_fixture_success_and_keeps_history(workspace, monkeypatch):
    settings = settings_for(workspace, monkeypatch)
    with TestClient(create_app(settings, client=None)) as client:
        assert client.get("/api/parts").json() == []
        assert client.get("/api/review").json() == []
        status = client.get("/api/status").json()
        assert not status["chat_available"] and status["cad_available"] is False
        assert "source data is missing" in status["message"]
        assert client.get("/api/parts/D-013%2Fpart").status_code == 404
        created = client.post("/api/conversations", json={}).json()["conversation"]["conversation_id"]
    with TestClient(create_app(settings, client=None)) as client:
        assert client.get(f"/api/conversations/{created}").status_code == 200
    with TestClient(create_app(settings, fixture_dir=ROOT / "testing/fixtures/contracts", client=None)) as client:
        assert all(part["synthetic"] and part["fixture"] for part in client.get("/api/parts").json())


def test_normal_discovery_refuses_a_synthetic_package(workspace, monkeypatch):
    settings = settings_for(workspace, monkeypatch)
    inputs, manifest = package(workspace)
    before = inputs.read_bytes()
    with pytest.raises(ValueError, match="refuses synthetic"):
        create_app(settings, client=None)
    assert inputs.read_bytes() == before and not (workspace / "generated/records.json").exists()
    # Source-only ordinary discovery follows the same refusal, without paid prep.
    (workspace / "generated/prepared.json").unlink()
    with pytest.raises(ValueError, match="refuses synthetic"):
        create_app(settings, client=None)


def test_registered_bytes_metadata_and_decisions_survive_restart(workspace, monkeypatch):
    settings = settings_for(workspace, monkeypatch)
    inputs, manifest = package(workspace)
    store = DecisionStore(workspace / "decisions", allow_synthetic=True)
    registry = load_package(workspace, inputs, manifest, store)
    fact = "D-001/drawing/title"
    store.append_decision(c.Decision(**MARKERS, decision_id="synthetic-pending", applies_to=fact,
        type="correction", value="Synthetic pending edit", old_value="Synthetic bracket", status="pending",
        by="Synthetic proposer", at=AT, based_on=registry.hashes_for(fact), reason="Test history retention."))
    directory, template = model_files(workspace, registry)
    source_bytes = {path: path.read_bytes() for path in (inputs, manifest, workspace / "generated/prepared.json")}
    history = store.history(fact)
    for restarted in (False, True):
        if restarted:
            registry = load_package(workspace, inputs, manifest, store)
        record = registry.part_for("D-001/part")
        assert record.synthetic and record.fixture and record.has_3d
        assert record.model.state == "stale" and record.model.selected_example == "B"
        assert record.model.built_at == AT and record.model.built_template_sha256 == c.contract_digest(template)
        assert record.model.overall_size_mm == (4, 4, 4)
        assert record.model.examples[1].choices == {"synthetic-variant": "B"}
        assert record.model.review.status == c.ReviewStatus.NOT_REVIEWED
        with TestClient(create_app(settings, registry=registry, inputs_root=inputs.parent, client=None)) as client:
            for path, expected_type, expected_hash in (
                ("/api/parts/D-001%2Fpart/image?page=1&thumb=1", "image/png", HASHES["png"]),
                ("/api/parts/D-001%2Fpart/image?page=2", "image/png", HASHES["png"]),
                ("/api/models/D-001_A.glb", "model/gltf-binary", HASHES["glbA"]),
                ("/api/models/D-001_B.glb", "model/gltf-binary", HASHES["glbB"]),
                ("/api/models/D-001_B.step", "application/step", HASHES["step"]),
            ):
                response = client.get(path)
                assert response.status_code == 200 and response.headers["content-type"] == expected_type
                assert response.headers["X-Meridian-Fixture"] == "synthetic"
                assert hashlib.sha256(response.content).hexdigest() == expected_hash
            assert client.get("/api/models/D-001_C.glb").status_code == 404
            assert client.get("/generated/models/missing.glb").headers["content-type"] == "application/json"
        assert store.history(fact) == history
        assert all(path.read_bytes() == raw for path, raw in source_bytes.items())


def test_intact_current_model_restores_available_and_becomes_stale_without_rebuilder(workspace, monkeypatch):
    inputs, manifest = package(workspace)
    registry = load_package(workspace, inputs, manifest)
    directory, template = model_files(workspace, registry)
    # Inject only the effective-template boundary, explicitly synthetic. This
    # tests composition without constructing reader results or human approvals.
    monkeypatch.setattr(RecordRegistry, "_template_candidates", staticmethod(
        lambda prepared, originals: {"D-001": template.model_copy(deep=True)}))
    registry = load_package(workspace, inputs, manifest)
    status = registry.part_for("D-001/part").model
    status.state, status.stale_reason = "available", None
    registry.set_model_status("D-001/part", status)
    restarted = load_package(workspace, inputs, manifest)
    assert restarted.part_for("D-001/part").model == status
    # A current template edit never silently rebuilds or promotes old geometry.
    changed = template.model_copy(deep=True)
    changed.finish_notes = ["Synthetic template revision; no new CAD was built."]
    monkeypatch.setattr(RecordRegistry, "_template_candidates", staticmethod(
        lambda prepared, originals: {"D-001": changed.model_copy(deep=True)}))
    stale = load_package(workspace, inputs, manifest).part_for("D-001/part").model
    assert stale.state == "stale" and stale.selected_example == "B"
    assert stale.built_at == AT and stale.current_template_sha256 == c.contract_digest(changed)
    assert stale.built_template_sha256 == c.contract_digest(template)


@pytest.mark.parametrize("damage", ["missing", "tampered", "wrong-source", "synthetic-mismatch", "escape"])
def test_invalid_model_identity_never_advertises_or_serves_geometry(workspace, monkeypatch, damage):
    settings = settings_for(workspace, monkeypatch)
    inputs, manifest = package(workspace)
    registry = load_package(workspace, inputs, manifest)
    directory, template = model_files(workspace, registry)
    snapshot = (workspace / "generated/records.json").read_bytes()
    if damage == "missing":
        (directory / "D-001_B.glb").unlink()
    elif damage == "tampered":
        (directory / "D-001_B.glb").write_bytes(b"<html>not a model</html>")
    else:
        data = json.loads((directory / "manifest.json").read_bytes())
        if damage == "wrong-source":
            data["template"]["source_sha256"] = "0" * 64
        elif damage == "synthetic-mismatch":
            data["template"].update(fixture=False, synthetic=False, fixture_note=None)
        else:
            value = data["status"]["examples"][0]["glb"]
            data["status"]["examples"][0]["glb"] = "../../outside.glb"
            data["artifacts"]["../../outside.glb"] = data["artifacts"].pop(value)
        data["template_sha256"] = c.contract_digest(data["template"])
        data["source_sha256"] = data["template"]["source_sha256"]
        (directory / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    # Requests also recheck bytes changed since startup.
    with TestClient(create_app(settings, registry=registry, inputs_root=inputs.parent, client=None)) as client:
        response = client.get("/api/models/D-001_B.glb")
        assert response.status_code == 404 and response.headers["content-type"] == "application/json"
    restarted = load_package(workspace, inputs, manifest)
    record = restarted.part_for("D-001/part")
    assert not record.has_3d and record.model.state == "missing" and record.examples == []
    assert (workspace / "generated/records.json").read_bytes() == snapshot


def test_real_source_driver_refuses_synthetic_inputs_before_builder(workspace, monkeypatch):
    inputs, manifest = package(workspace)
    spec = importlib.util.spec_from_file_location("synthetic_build_source_models", ROOT / "development/scripts/build_source_models.py")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)

    def forbidden(*args, **kwargs):
        raise AssertionError("No CAD factory or model may execute for synthetic saved preparation.")

    monkeypatch.setattr("backend.cad.build.create_model_rebuilder", forbidden)
    monkeypatch.setattr(sys, "argv", ["build_source_models.py", "--inputs", str(inputs), "--manifest", str(manifest),
        "--prepared", str(workspace / "generated/prepared.json"), "--records", str(workspace / "generated/records.json"),
        "--models", str(workspace / "generated/models"), "--decisions", str(workspace / "decisions"),
        "--report", str(workspace / "report.json")])
    with pytest.raises(ValueError, match="refuses synthetic"):
        driver.main()
    assert not (workspace / "generated/models").exists()
    assert not (workspace / "generated/records.json").exists()
