"""Remote release publication contracts, using tiny exports and no CAD engine."""
import builtins
import copy
import json
from pathlib import Path

import pytest

from backend.cad import builder
from scripts import cad_artifact as release


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for folder in (root / "generated", root / "decisions")
            for path in folder.rglob("*") if path.is_file()}


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path
    artifact = root / ".tmp/download"
    monkeypatch.setattr("backend.app.store.inside", lambda value: Path(value).resolve())
    original_import = builtins.__import__

    def no_cad(name, *args, **kwargs):
        if name.split(".")[0] in {"cadquery", "trimesh", "numpy", "OCP"}:
            pytest.fail("Artifact installation must never import heavy CAD/numerical modules")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cad)
    known = lambda value: {"state": "known", "value": value, "method": "ai_verified", "fact_ids": ["source"]}
    template = {"part": "D-001", "source_sha256": "original-pdf-sha",
                "outline": {"state": "known", "type": "rectangle", "length": known(20), "width": known(10)},
                "thickness": known(2), "features": []}
    records = [{"id": "D-001/part", "key": "D-001", "display_name": "Fixture", "bom": [],
                "drawing": {"id": "D-001", "sha256": "original-pdf-sha", "fields": {}},
                "link": {"method": "exact_match", "value": []}, "has_3d": False, "examples": [], "models": {},
                "model_manifest": {}, "weight_check": None}]
    for name, value in {"ai_results.json": {"templates": {"D-001": template}}, "records.json": records,
                        "drawings.json": {"D-001": {"sha256": "original-pdf-sha"}},
                        "bom.json": [], "readme.json": [], "models/manifest.json": {"old": "manifest"}}.items():
        write(root / "generated" / name, value)
    write(root / "decisions/unchanged.json", {"type": "fixture_note", "decision_id": "preserved"})
    write(root / "backend/cad/densities.json", [])
    (root / "generated/images").mkdir()
    (root / "generated/images/original.png").write_bytes(b"original image")
    for name in ("ai_results.json", "records.json", "drawings.json"):
        target = artifact / "generated" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / "generated" / name).read_bytes())
    effective = release.effective_templates(root)["D-001"]
    template_hash = builder._hash(effective)
    model = {"glb": "models/D-001_A.glb", "step": "models/D-001_A.step", "template_sha256": template_hash}
    for kind in ("glb", "step"):
        exported = artifact / "generated" / model[kind]
        exported.parent.mkdir(parents=True, exist_ok=True)
        exported.write_bytes(("verified remote " + kind).encode())
        model[kind + "_sha256"] = release.digest(exported)
    part = {"generator_version": builder.VERSION, "template_sha256": template_hash, "source_sha256": "original-pdf-sha",
            "examples": ["A"], "models": {"A": model}, "waiting": [], "weight_check": {"state": "Skipped"}}
    write(artifact / "generated/models/manifest.json", {"D-001": part})
    cache = artifact / "generated/ai_cache/artifacts/cad" / builder._hash({"version": builder.VERSION, "template": effective, "densities": []})
    write(cache / "manifest.json", part)
    for kind in ("glb", "step"):
        (cache / Path(model[kind]).name).write_bytes((artifact / "generated" / model[kind]).read_bytes())
    write(artifact / "docs/ci/cad-inputs.json", {"ai_results_sha256": release.digest(root / "generated/ai_results.json"),
          "drawings_sha256": release.structured_digest(root / "generated/drawings.json"), "decisions": release.decisions(root), "generator_version": builder.VERSION})
    write(artifact / "docs/ci/cad.json", {"passed": True, "decisions_unchanged": True, "built_parts": 1,
          "variant_count": 1, "expected_variants": {"D-001": 1}, "variants": [{"part": "D-001", "variant": "A"}]})
    write(artifact / "docs/ci/browser-stages.json", [{"mode": "customer", "passed": True}, {"mode": "debug", "passed": True}])
    write(artifact / "docs/verification/browser-check.json", {"page_errors": [], "failed_responses": [],
          "models_rendered": [{"drawing": "D-001", "variant": "A", "glb_sha256": model["glb_sha256"]}]})
    return root, artifact, part


@pytest.mark.parametrize("failure", ["ai", "decisions", "drawings", "export", "browser", "cad", "template", "extra", "stage"])
def test_rejected_artifact_does_not_mutate_live_data(bundle, failure):
    root, artifact, part = bundle
    before = snapshot(root)
    if failure == "ai":
        write(artifact / "generated/ai_results.json", {"unverified": True})
    elif failure == "decisions":
        inputs = release.read(artifact / "docs/ci/cad-inputs.json")
        inputs["decisions"] = {}
        write(artifact / "docs/ci/cad-inputs.json", inputs)
    elif failure == "export":
        (artifact / "generated/models/D-001_A.glb").write_bytes(b"corrupted")
    elif failure == "drawings":
        write(artifact / "generated/drawings.json", {"D-001": {"sha256": "fabricated"}})
    elif failure == "browser":
        write(artifact / "docs/verification/browser-check.json", {"models_rendered": []})
    elif failure == "cad":
        report = release.read(artifact / "docs/ci/cad.json")
        report["expected_variants"]["D-001"] = 0
        write(artifact / "docs/ci/cad.json", report)
    elif failure == "template":
        part["template_sha256"] = "different effective template"
        write(artifact / "generated/models/manifest.json", {"D-001": part})
    elif failure == "extra":
        write(artifact / "generated/models/manifest.json", {"D-001": part, "D-999": part})
    else:
        write(artifact / "docs/ci/browser-stages.json", [{"mode": "customer", "passed": True}])
    with pytest.raises(ValueError):
        release.install(artifact, 123, root=root)
    assert snapshot(root) == before
    assert not (root / "generated/.publish.lock").exists()


def test_success_installs_only_verified_exports_and_backs_up_manifest(bundle):
    root, artifact, _ = bundle
    before = snapshot(root)
    (artifact / "generated/models/unverified-extra.glb").write_bytes(b"must not publish")
    report = release.install(artifact, 123, root=root)
    assert report["passed"] and report["app_data_changed"]
    assert report["installed_models"] == [{"drawing": "D-001", "variant": "A"}]
    assert (root / ".runtime/cad-release/123/before/generated/models/manifest.json").read_bytes() == before["generated/models/manifest.json"]
    assert not (root / "generated/models/unverified-extra.glb").exists()
    for name, content in before.items():
        if name != "generated/models/manifest.json":
            assert (root / name).read_bytes() == content
    assert not (root / "generated/.publish.lock").exists()
    assert release.read(root / "docs/verification/cad-install-123.json") == report


def test_drawings_json_layout_and_line_endings_do_not_change_verified_values(bundle):
    root, artifact, _ = bundle
    original = (root / "generated/drawings.json").read_bytes()
    path = artifact / "generated/drawings.json"
    # Simulate the same extracted values serialized on a different platform.
    encoded = json.dumps(release.read(path), indent=4, ensure_ascii=False).replace("\n", "\r\n")
    path.write_bytes(encoded.encode("utf-8") + b"\r\n")
    assert path.read_bytes() != original
    assert release.structured_digest(path) == release.structured_digest(root / "generated/drawings.json")
    assert release.install(artifact, 124, root=root)["passed"]
    assert (root / "generated/drawings.json").read_bytes() == original


def candidate(bundle):
    root, artifact, part = bundle
    batch = root / "generated/ai_cache/detail-reprepare/batch"
    source = batch / "candidate/generated"
    for name in ("ai_results.json", "records.json", "drawings.json", "bom.json", "readme.json"):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / "generated" / name).read_bytes())
    write(source.parent / "decisions/unchanged.json", release.read(root / "decisions/unchanged.json"))
    # Simulate a newer verified AI preparation without changing its geometry.
    ai = release.read(source / "ai_results.json")
    ai["prep_receipt"] = "exact verified proposal"
    write(source / "ai_results.json", ai)
    write(artifact / "generated/ai_results.json", ai)
    write(artifact / "generated/ai_cache/artifacts/ai_results.json", ai)
    records = release.read(source / "records.json")
    records[0].update(has_3d=True, examples=["A"], models=copy.deepcopy(part["models"]),
                      model_manifest=copy.deepcopy(part), weight_check=copy.deepcopy(part["weight_check"]))
    write(artifact / "generated/records.json", records)
    inputs = release.read(artifact / "docs/ci/cad-inputs.json")
    inputs["ai_results_sha256"] = release.digest(source / "ai_results.json")
    write(artifact / "docs/ci/cad-inputs.json", inputs)
    write(batch / "checkpoint.json", {"complete": True, "candidate": str(source.relative_to(root)).replace("/", "\\"),
          "candidate_sha256": inputs["ai_results_sha256"], "source_hashes": {"generated\\drawings.json": release.digest(root / "generated/drawings.json")}})
    return batch


def test_candidate_promotion_preserves_original_evidence_receipts_and_checkpoint(bundle):
    root, artifact, _ = bundle
    batch = candidate(bundle)
    before = snapshot(root)
    receipt = (batch / "checkpoint.json").read_bytes()
    report = release.install(artifact, 456, batch, root=root)
    assert report["candidate"] == str((batch / "candidate").relative_to(root))
    for name in ("drawings.json", "bom.json", "readme.json", "images/original.png"):
        assert (root / "generated" / name).read_bytes() == before["generated/" + name]
    assert (root / "decisions/unchanged.json").read_bytes() == before["decisions/unchanged.json"]
    assert (batch / "checkpoint.json").read_bytes() == receipt
    assert release.digest(root / "generated/ai_results.json") == report["inputs"]["ai_results_sha256"]
    assert release.digest(root / "generated/ai_cache/artifacts/ai_results.json") == report["inputs"]["ai_results_sha256"]
    assert release.read(root / "generated/records.json")[0]["models"] == release.read(root / "generated/models/manifest.json")["D-001"]["models"]
    assert not (root / "generated/.publish.lock").exists()


def test_incomplete_or_changed_candidate_is_rejected(bundle):
    root, artifact, _ = bundle
    batch = candidate(bundle)
    write(batch / "checkpoint.json", {"complete": False})
    before = snapshot(root)
    with pytest.raises(ValueError, match="incomplete"):
        release.install(artifact, 456, batch, root=root)
    assert snapshot(root) == before


def test_new_live_decision_invalidates_candidate_and_remote_receipt(bundle):
    root, artifact, _ = bundle
    batch = candidate(bundle)
    write(root / "decisions/new-note.json", {"type": "fixture_note", "decision_id": "new"})
    before = snapshot(root)
    with pytest.raises(ValueError, match="decision snapshot"):
        release.install(artifact, 456, batch, root=root)
    assert snapshot(root) == before


def test_candidate_cannot_publish_modified_record_evidence(bundle):
    root, artifact, _ = bundle
    batch = candidate(bundle)
    records = release.read(artifact / "generated/records.json")
    records[0]["display_name"] = "Unverified change"
    write(artifact / "generated/records.json", records)
    before = snapshot(root)
    with pytest.raises(ValueError, match="records change"):
        release.install(artifact, 456, batch, root=root)
    assert snapshot(root) == before


def test_publish_failure_rolls_back_all_exports_and_cleans_lock(bundle, monkeypatch):
    root, artifact, _ = bundle
    before = snapshot(root)
    original_replace = release.os.replace

    def fail_manifest(source, destination):
        if Path(destination) == root / "generated/models/manifest.json" and "prepared" in Path(source).parts:
            raise OSError("fixture publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(release.os, "replace", fail_manifest)
    with pytest.raises(OSError, match="publication failure"):
        release.install(artifact, 789, root=root)
    assert snapshot(root) == before
    assert not (root / "generated/.publish.lock").exists()


@pytest.mark.parametrize("path", ["../outside", "models/../../outside", "..\\outside", "C:/outside"])
def test_path_escape_is_rejected(bundle, path):
    root, _, _ = bundle
    with pytest.raises(ValueError):
        release.checked(root, path)


def test_even_internal_symlinks_cannot_be_published(bundle):
    root, artifact, _ = bundle
    link = artifact / "generated/models/linked.glb"
    try:
        link.symlink_to(artifact / "generated/models/D-001_A.glb")
    except OSError:
        pytest.skip("Symlink creation requires platform privileges")
    before = snapshot(root)
    with pytest.raises(ValueError, match="Links are forbidden"):
        release.install(artifact, 123, root=root)
    assert snapshot(root) == before
