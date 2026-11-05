"""Remote deterministic M13 checks. Every dimension here is INVENTED test data.

No source drawing is read, no actual-part template is supplied, and these
meshes are never D-013/D-025/D-026 deliverables. Run in ROOT's queued CAD job:

    MERIDIAN_REQUIRE_CAD=1 uv run --project ../development --extra cad --extra test \
      python -m pytest tests/test_cad_build.py -q -p no:cacheprovider \
      --basetemp=tmp/pytest-cad --junitxml=reports/cad-build/remote.xml

Keep that job separate from browser work, with OMP_NUM_THREADS=1,
OPENBLAS_NUM_THREADS=1 and MKL_NUM_THREADS=1. Archive testing/tmp/cad-build/:
the tests retain GLB, STEP, source-bound manifests and independent measurements.
Policy/cache checks do not require CadQuery. Required-CAD mode fails rather
than skipping if that remote job lacks its CAD dependency. No test runs on
import; ordinary app startup need not import this suite or a CAD package.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile

import pytest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.cad import build  # noqa: E402


PART = "D-901"
FIXTURE_NOTE = "Invented analytic CAD fixture. No actual part/source was inspected or reconstructed."


def _known(tag, value, *, unit=None, essential=False):
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    return dict(name=f"{PART}/template/{tag}", method="parsed", state="known", value=value,
                unit=unit, essential=essential,
                evidence=dict(number_ids=[f"{PART}/drawing/n/{tag}@1"] if numeric else [],
                              source_ids=[] if numeric else [f"{PART}/source"]))


def _options(tag, values, *, unit=None):
    return dict(name=f"{PART}/template/{tag}", method="parsed", state="options", unit=unit,
                options=[dict(value=value, label=f"Printed synthetic option {i + 1}",
                    evidence=dict(number_ids=[f"{PART}/drawing/n/{tag}-option-{i + 1}@1"]
                        if isinstance(value, (int, float)) else [], source_ids=[f"{PART}/source"]))
                    for i, value in enumerate(values)])


def _unknown(tag, *, essential=False):
    return dict(name=f"{PART}/template/{tag}", method="unresolved", state="unknown",
                essential=essential, reason="unreadable_scan", message="Synthetic coordinate/detail is unreadable.",
                evidence=dict(source_ids=[f"{PART}/source"]))


def _template(*, outline=None, thickness=5, features=(), part=PART):
    if outline is None:
        outline = dict(type="rectangle", length=_known("length", 40, unit="mm"),
                       width=_known("width", 30, unit="mm"))
    data = dict(part=PART, units="mm", filled_by="human", source_sha256=c.contract_digest(FIXTURE_NOTE),
                fixture=True, synthetic=True, fixture_note=FIXTURE_NOTE,
                outline=_known("outline", outline, essential=True),
                thickness=_known("thickness", thickness, unit="mm", essential=True), features=list(features))
    if part != PART:
        data = json.loads(json.dumps(data).replace(PART, part))
    return c.FlatTemplate.model_validate(data)


def _hole(tag="hole", *, hole_type="plain", face="top", x=12, y=10, diameter=4,
          through=True, depth=None, pattern=None, essential=False, **extra):
    feature = dict(kind="hole", hole_type=hole_type, face=face,
                   position=dict(x=_known(tag + "-x", x, unit="mm"), y=_known(tag + "-y", y, unit="mm")),
                   diameter=_known(tag + "-diameter", diameter, unit="mm"), through=through, pattern=pattern)
    if depth is not None:
        feature["depth"] = _known(tag + "-depth", depth, unit="mm")
    feature.update(extra)
    return _known(tag, feature, essential=essential)


def _slot(tag="slot", *, face="top", x=20, y=15, width=4, length=14, angle=30,
          through=True, depth=None, pattern=None, essential=False):
    feature = dict(kind="slot", face=face,
        position=dict(x=_known(tag + "-x", x, unit="mm"), y=_known(tag + "-y", y, unit="mm")),
        width=_known(tag + "-width", width, unit="mm"), length=_known(tag + "-length", length, unit="mm"),
        direction_deg=_known(tag + "-direction", angle, unit="deg"), through=through, pattern=pattern)
    if depth is not None:
        feature["depth"] = _known(tag + "-depth", depth, unit="mm")
    return _known(tag, feature, essential=essential)


def _record(template, *, previous=None):
    """Construct an honestly synthetic drawing inventory matching fixture tokens."""
    numbers = {}

    def visit(node):
        if isinstance(node, dict):
            value, evidence = node.get("value"), node.get("evidence", {})
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                for name in evidence.get("number_ids", []):
                    assert name not in numbers or numbers[name] == value
                    numbers[name] = value
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(template.model_dump(mode="json"))
    drawing = c.DrawingEvidence(id=template.part, pages=1, image="synthetic-test-only.png",
        page_geometry=[dict(page=1, source_width=100, source_height=100, image_width=100, image_height=100)],
        degraded=False, source_quality="clean", source_path="synthetic-test-only.pdf",
        source_sha256=template.source_sha256, fields={},
        numbers=[dict(name=name, text=str(value), value=value, page=1, box=(0, 0, 1, 1), unit="mm")
                 for name, value in numbers.items()])
    return c.PartRecord(id=c.drawing_part_name(template.part), display_name="Synthetic CAD test fixture",
        section=None, has_drawing=True, has_3d=bool(previous and previous.examples),
        examples=[e.id for e in previous.examples] if previous else [], drawing=drawing, bom=[], link=None,
        template="synthetic-test-only-template", model=previous or c.ModelStatus(state="missing"),
        fixture=True, synthetic=True, fixture_note=FIXTURE_NOTE)


@pytest.fixture
def output_dir(request):
    parent = ROOT / "testing/tmp/cad-build"
    parent.mkdir(parents=True, exist_ok=True)
    # Retained for the remote artifact, with isolated per-test ownership.
    prefix = re_safe(request.node.name)[:65] + "-"
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def re_safe(value):
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)


@pytest.fixture
def cad():
    if os.environ.get("MERIDIAN_REQUIRE_CAD") == "1":
        return importlib.import_module("cadquery")
    return pytest.importorskip("cadquery", reason="CAD geometry is qualified in ROOT's separate remote CAD job")


def _path(asset):
    path = Path(asset)
    return path if path.is_absolute() else ROOT / "development" / path


def _manifest(status):
    return json.loads((_path(status.examples[0].glb).parent / "manifest.json").read_text(encoding="utf-8"))


def _binary_glb(path):
    """Independent scene transforms, binary vertices/indices and mesh volume.

    This reads actual BIN data rather than trusting accessors' declared bounds
    or the builder's manifest/CAD volume. No qualified probe dimensions enter.
    """
    import numpy as np

    payload = path.read_bytes()
    assert struct.unpack_from("<4sII", payload) == (b"glTF", 2, len(payload))
    chunks, offset = [], 12
    while offset < len(payload):
        size, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        assert size % 4 == 0 and offset + size <= len(payload)
        chunks.append((kind, payload[offset:offset + size]))
        offset += size
    assert [kind for kind, _ in chunks] == [0x4E4F534A, 0x004E4942]
    document, binary = json.loads(chunks[0][1]), chunks[1][1]
    assert len(document["buffers"]) == 1 and "uri" not in document["buffers"][0]
    assert not document.get("textures") and not document.get("images")
    assert not document.get("extensionsRequired")
    assert any(c.RECONSTRUCTION_LABEL in node.get("name", "") for node in document["nodes"])

    def accessor(index):
        acc = document["accessors"][index]
        view = document["bufferViews"][acc["bufferView"]]
        dtype = np.dtype({5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[acc["componentType"]])
        width = {"SCALAR": 1, "VEC3": 3}[acc["type"]]
        stride = view.get("byteStride", width * dtype.itemsize)
        local = acc.get("byteOffset", 0)
        assert view["buffer"] == 0 and acc["count"] > 0 and "sparse" not in acc
        assert local + (acc["count"] - 1) * stride + width * dtype.itemsize <= view["byteLength"]
        assert view.get("byteOffset", 0) + view["byteLength"] <= document["buffers"][0]["byteLength"]
        values = np.ndarray((acc["count"], width), dtype=dtype, buffer=binary,
            offset=view.get("byteOffset", 0) + local, strides=(stride, dtype.itemsize)).copy()
        assert np.isfinite(values).all()
        return values

    def matrix(node):
        if "matrix" in node:
            return np.array(node["matrix"]).reshape(4, 4, order="F")
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                             [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                             [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
        value = np.eye(4)
        value[:3, :3] = rotation @ np.diag(node.get("scale", [1, 1, 1]))
        value[:3, 3] = node.get("translation", [0, 0, 0])
        return value

    points, colours, mesh_triangles = [], [], []
    signed_volume, triangles = 0.0, 0

    def visit(index, parent, ancestors):
        nonlocal signed_volume, triangles
        assert index not in ancestors
        node = document["nodes"][index]
        world = parent @ matrix(node)
        if "mesh" in node:
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                assert primitive.get("mode", 4) == 4
                values = accessor(primitive["attributes"]["POSITION"]).astype(float)
                declared = document["accessors"][primitive["attributes"]["POSITION"]]
                assert np.allclose(values.min(axis=0), declared["min"], atol=1e-7, rtol=0)
                assert np.allclose(values.max(axis=0), declared["max"], atol=1e-7, rtol=0)
                transformed = (world @ np.column_stack((values, np.ones(len(values)))).T).T[:, :3]
                points.append(transformed)
                indices = accessor(primitive["indices"]).reshape(-1).astype(int)
                assert len(indices) % 3 == 0 and indices.min() >= 0 and indices.max() < len(values)
                faces = transformed[indices.reshape(-1, 3)]
                mesh_triangles.append(faces)
                signed_volume += float(np.einsum("ij,ij->i", faces[:, 0], np.cross(faces[:, 1], faces[:, 2])).sum() / 6)
                triangles += len(faces)
                colour = document["materials"][primitive["material"]]["pbrMetallicRoughness"]["baseColorFactor"]
                assert 0 < colour[0] < 1 and max(colour[:3]) - min(colour[:3]) < 1e-7
                assert colour[3] == pytest.approx(1, abs=1e-7)
                colours.append(colour)
        for child in node.get("children", []):
            visit(child, world, ancestors | {index})

    for index in document["scenes"][document.get("scene", 0)]["nodes"]:
        visit(index, np.eye(4), set())
    assert points and triangles > 0 and colours
    vertices = np.concatenate(points)
    return dict(bounds_m=[vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
                volume_mm3=abs(signed_volume) * 1e9, triangles=triangles, base_colour_factors=colours,
                _triangles_m=np.concatenate(mesh_triangles))


class _VerifiedSolid:
    """Require STEP containment and independent GLB winding to agree per probe."""

    def __init__(self, solid, triangles, proof, report_path):
        self.solid, self.triangles = solid, triangles
        self.proof, self.report_path = proof, report_path

    def isInside(self, vector, tolerance):
        import numpy as np

        expected = bool(self.solid.isInside(vector, tolerance))
        x, y, z = vector.toTuple()
        rays = self.triangles - np.array([x, z, -y]) * 0.001
        a, b, d = rays[:, 0], rays[:, 1], rays[:, 2]
        an, bn, dn = (np.linalg.norm(value, axis=1) for value in (a, b, d))
        denominator = an * bn * dn + np.einsum("ij,ij->i", a, b) * dn
        denominator += np.einsum("ij,ij->i", b, d) * an + np.einsum("ij,ij->i", d, a) * bn
        determinant = np.einsum("ij,ij->i", a, np.cross(b, d))
        winding = abs(float((2 * np.arctan2(determinant, denominator)).sum()))
        assert (winding > 2 * math.pi) == expected, f"GLB/STEP void disagreement at {vector.toTuple()}"
        self.proof["void_probes"].append(dict(point_mm=list(vector.toTuple()), step_inside=expected,
            glb_inside=winding > 2 * math.pi, glb_solid_angle_sum=winding))
        self.report_path.write_text(json.dumps(self.proof, indent=2) + "\n", encoding="utf-8")
        return expected


def _prove(cad, status, expected_volume, expected_bounds, output_dir, *, example=0):
    assert status.state == "available", status.model_dump(mode="json")
    assert status.selected_example is None and status.examples[example].possible_reading
    asset = status.examples[example]
    assert asset.volume_mm3 == pytest.approx(expected_volume, abs=1e-6, rel=1e-10)
    assert status.built_template_sha256 == status.current_template_sha256
    assert status.built_at is not None and status.built_at.utcoffset() is not None
    assert "SYNTHETIC TEST GEOMETRY" in status.message
    glb, step = _path(asset.glb), _path(asset.step)
    assert glb.is_file() and step.is_file()
    assert "synthetic" in glb.parts and "reconstruction" in glb.name
    assert c.RECONSTRUCTION_LABEL in step.read_text(encoding="utf-8")
    imported = cad.importers.importStep(str(step)).val()
    assert imported.isValid() and len(imported.Solids()) == 1
    assert imported.Volume() == pytest.approx(expected_volume, abs=1e-5, rel=1e-10)
    box = imported.BoundingBox()
    actual_bounds = [[box.xmin, box.ymin, box.zmin], [box.xmax, box.ymax, box.zmax]]
    for actual, expected in zip(actual_bounds, expected_bounds):
        assert actual == pytest.approx(expected, abs=1e-6)
    lo, hi = expected_bounds
    expected_glb = [[lo[0] / 1000, lo[2] / 1000, -hi[1] / 1000],
                    [hi[0] / 1000, hi[2] / 1000, -lo[1] / 1000]]
    binary = _binary_glb(glb)
    triangles = binary.pop("_triangles_m")
    manifest = _manifest(status)
    # Curved mesh extrema may be inside the analytic circle by the exporter's
    # qualified 0.00005 m linear deflection; planar stock bounds stay tighter.
    bound_tolerance = 2e-7 if manifest["template"]["outline"]["value"]["type"] == "rectangle" else 5.1e-5
    for actual, expected in zip(binary["bounds_m"], expected_glb):
        assert actual == pytest.approx(expected, abs=bound_tolerance)
    assert binary["volume_mm3"] == pytest.approx(expected_volume, rel=0.0025)
    assert manifest["template"]["synthetic"] and manifest["template"]["fixture"]
    assert manifest["source_sha256"] == manifest["template"]["source_sha256"]
    assert manifest["template_sha256"] == c.contract_digest(manifest["template"])
    assert manifest["glb_units"] == "m" and manifest["step_units"] == "mm"
    assert manifest["colour"] == [0.6, 0.6, 0.6, 1.0]
    for value, identity in manifest["artifacts"].items():
        path = _path(value)
        assert path.stat().st_size == identity["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
    proof = dict(scope=FIXTURE_NOTE, example=asset.id, template_sha256=status.built_template_sha256,
                 expected_volume_mm3=expected_volume, step_volume_mm3=imported.Volume(),
                 expected_bounds_mm=expected_bounds, step_bounds_mm=actual_bounds,
                 glb_bounds_tolerance_m=bound_tolerance, glb_volume_relative_tolerance=0.0025, glb=binary, void_probes=[])
    report_path = output_dir / f"independent-{asset.id}.json"
    report_path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return _VerifiedSolid(imported.Solids()[0], triangles, proof, report_path)


def _forbid_cad(monkeypatch):
    def unexpected(name):
        # pytest.fail is not caught by the builder's Exception boundary. An
        # unexpected import must fail this check, not masquerade as a blocker.
        pytest.fail("This policy/cache case must not import " + name)
    monkeypatch.setattr(build, "import_module", unexpected)


@pytest.mark.parametrize("changed", [None, "pdf", "numbers"])
def test_prepared_template_binds_drawing_snapshot_and_original_pdf(changed, monkeypatch, output_dir):
    from backend.ai.runner import Runner, JobDefinition, EvidenceBundle, EvidenceInput
    from backend.settings import load_settings

    template = _template()
    record = _record(template)
    snapshot = record.drawing.model_dump(mode="json")
    digest = c.contract_digest(snapshot)
    source = c.PrepSourceIdentity(inputs={"drawing": digest}, source_ids={f"{PART}/source": "drawing"})
    definition = JobDefinition(job="SYNTHETIC-cad-binding", determination_instructions=FIXTURE_NOTE,
        verification_instructions=FIXTURE_NOTE, value_schemas={f"{PART}/template/thickness": {"type": "number"}},
        evidence=lambda request: EvidenceBundle({"drawing": EvidenceInput(value=snapshot)}),
        validate_candidate=lambda candidate, source: candidate, validation_version="synthetic-binding/v1")
    runner = Runner(jobs={definition.job: definition}, prep_settings=load_settings().data["prep"],
        workspace_root=ROOT, runtime_root=output_dir / "unused-runner", reserve_cli_slot=lambda: pytest.fail("No CLI allowed"))
    job = definition.request("SYNTHETIC-cad-binding", source)
    attempt = runner._invalid(c.DeterminationRequest(job=job, round=1), "Synthetic unreviewed provenance; no model call.")
    provenance = runner._provenance(job, [c.PrepRound(round=1, determination=attempt, verification=None)])
    template = c.FlatTemplate.model_validate({**template.model_dump(mode="json"), "source_sha256": digest,
        "filled_by": "determine_verify", "provenance": provenance.model_dump(mode="json")})
    if changed == "pdf":
        record.drawing.source_sha256 = c.contract_digest("SYNTHETIC replacement PDF")
    elif changed == "numbers":
        record.drawing.numbers[0].value += 1
    called = []
    sentinel = c.ModelStatus(state="blocked", message="SYNTHETIC source boundary reached; no CAD execution.")
    monkeypatch.setattr(build, "build_template", lambda *args, **kwargs: called.append(args) or sentinel)
    _forbid_cad(monkeypatch)
    result = build.create_model_rebuilder(output_dir)(record, template)
    if changed is None:
        assert called and result == sentinel
    else:
        assert not called and result.state == "blocked" and not result.examples
        assert "bound" in result.message


def test_module_reload_and_factory_never_import_cad(monkeypatch, output_dir):
    original = builtins.__import__
    requested = []

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"cadquery", "OCP", "vtk", "numpy"}:
            requested.append(name)
            raise AssertionError("Ordinary startup requested CAD: " + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    importlib.reload(build)
    assert callable(build.create_model_rebuilder(output_dir))
    assert not requested and not list(output_dir.iterdir())


@pytest.mark.parametrize("target", ["outline", "length", "thickness", "feature", "coordinate", "slot-direction", "row-direction"])
def test_unknown_essential_blocks_before_cad(target, output_dir, monkeypatch):
    data = _template().model_dump(mode="json")
    tag = target
    if target in {"outline", "thickness"}:
        data[target] = _unknown(tag)  # Required even if its flag is false.
    elif target == "length":
        data["outline"]["value"]["length"] = _unknown(tag)
    elif target == "feature":
        data["features"] = [_unknown(tag, essential=True)]
    elif target == "coordinate":
        hole = _hole(essential=True)
        hole["value"]["position"]["x"] = _unknown(tag)
        data["features"] = [hole]
    elif target == "slot-direction":
        slot = _slot(essential=True)
        slot["value"]["direction_deg"] = _unknown(tag)
        data["features"] = [slot]
    else:
        pattern = dict(type="row", count=_known("count", 2), spacing=_known("spacing", 8), direction_deg=_unknown(tag))
        data["features"] = [_hole(pattern=pattern, essential=True)]
    template = c.FlatTemplate.model_validate(data)
    _forbid_cad(monkeypatch)
    status = build.build_template(template, output_dir)
    assert status.state == "blocked" and not status.examples
    assert f"{PART}/template/{tag}" in status.unresolved_fields
    assert status.current_template_sha256 == c.contract_digest(template)
    assert status.built_at is None and status.built_template_sha256 is None
    assert "unreadable" in status.message
    assert not list(output_dir.iterdir())


def test_more_than_four_examples_never_truncates(output_dir, monkeypatch):
    data = _template().model_dump(mode="json")
    data["thickness"] = _options("thickness", [2, 3, 4], unit="mm")
    data["outline"]["value"]["length"] = _options("length", [40, 45], unit="mm")
    _forbid_cad(monkeypatch)
    status = build.build_template(c.FlatTemplate.model_validate(data), output_dir)
    assert status.state == "blocked" and not status.examples
    assert "6 examples" in status.message and "truncated" in status.message
    assert len(status.unresolved_fields) == 2 and not list(output_dir.iterdir())


@pytest.mark.parametrize("face", ["front", "back", "left", "right", "outer", "inner"])
def test_essential_side_faces_are_explicitly_unsupported(face, output_dir, monkeypatch):
    _forbid_cad(monkeypatch)
    status = build.build_template(_template(features=[_hole(face=face, essential=True)]), output_dir)
    assert status.state == "unsupported" and not status.examples
    assert face in status.message and "top/bottom" in status.message


def test_duplicate_field_names_block_before_cad(output_dir, monkeypatch):
    data = _template().model_dump(mode="json")
    data["outline"]["value"]["width"]["name"] = data["outline"]["value"]["length"]["name"]
    _forbid_cad(monkeypatch)
    status = build.build_template(c.FlatTemplate.model_validate(data), output_dir)
    assert status.state == "blocked" and "unique" in status.message


@pytest.mark.parametrize("target,unit", [("length", "in"), ("length", "deg"), ("angle", "mm"), ("count", "mm")])
def test_geometry_units_are_never_guessed_or_converted(target, unit, output_dir, monkeypatch):
    pattern = dict(type="row", count=_known("count", 2), spacing=_known("spacing", 8),
                   direction_deg=_known("row-direction", 0, unit="deg"))
    data = _template(features=[_hole(pattern=pattern)]).model_dump(mode="json")
    node = (data["outline"]["value"]["length"] if target == "length" else
            data["features"][0]["value"]["pattern"]["direction_deg" if target == "angle" else "count"])
    node["unit"] = unit
    _forbid_cad(monkeypatch)
    status = build.build_template(c.FlatTemplate.model_validate(data), output_dir)
    assert status.state == "blocked" and "unit" in status.message


@pytest.mark.parametrize("problem", ["part", "source", "synthetic", "number", "derivation"])
def test_factory_checks_record_source_and_evidence(problem, output_dir, monkeypatch):
    template = _template(features=[_hole()])
    record = _record(template)
    if problem == "part":
        record.id = "D-902/part"
    elif problem == "source":
        record.drawing.source_sha256 = "0" * 64
    elif problem == "synthetic":
        record.fixture = record.synthetic = False
        record.fixture_note = None
    elif problem == "number":
        record.drawing.numbers = []
    else:
        data = template.model_dump(mode="json")
        data["thickness"]["evidence"] = dict(derivation=dict(kind="arithmetic", expression="missing + 1",
            inputs=[f"{PART}/drawing/missing"]))
        template = c.FlatTemplate.model_validate(data)
    _forbid_cad(monkeypatch)
    status = build.create_model_rebuilder(output_dir)(record, template)
    assert status.state == "blocked" and not status.examples
    assert not list(output_dir.iterdir())


def test_outputs_cannot_escape_generated_or_isolated_testing_paths(output_dir):
    for path in (ROOT, ROOT / "development/backend", ROOT / "testing/tests", output_dir / "../../../../development/backend"):
        with pytest.raises(ValueError, match="CAD output must"):
            build.create_model_rebuilder(path)


def test_missing_cad_is_missing_and_has_no_built_evidence(output_dir, monkeypatch):
    def unavailable(name):
        raise ModuleNotFoundError(name)
    monkeypatch.setattr(build, "import_module", unavailable)
    status = build.build_template(_template(), output_dir)
    assert status.state == "missing" and not status.examples
    assert status.built_template_sha256 is None and status.built_at is None


def test_unverified_previous_status_cannot_advertise_fake_stale_evidence(output_dir, monkeypatch):
    # Deliberately invalid bytes exercise refusal, never a positive model fixture.
    path = output_dir / "invalid.glb"
    path.write_bytes(b"not a CAD model")
    previous = c.ModelStatus(state="available", examples=[dict(id="A", glb=path.as_posix())],
                             built_template_sha256="0" * 64)
    data = _template().model_dump(mode="json")
    data["thickness"] = _unknown("thickness")
    _forbid_cad(monkeypatch)
    status = build.build_template(c.FlatTemplate.model_validate(data), output_dir, previous=previous)
    assert status.state == "blocked" and not status.examples
    assert status.built_template_sha256 is None and status.built_at is None


@pytest.mark.parametrize("kind", ["rectangle", "circle", "ring"])
def test_outline_extrusions_mm_step_and_metre_grey_glb(kind, cad, output_dir):
    if kind == "rectangle":
        template, volume, bounds = _template(), 40 * 30 * 5, [[0, 0, 0], [40, 30, 5]]
    elif kind == "circle":
        template = _template(outline=dict(type="circle", diameter=_known("diameter", 36)))
        volume, bounds = math.pi * 18**2 * 5, [[-18, -18, 0], [18, 18, 5]]
    else:
        template = _template(outline=dict(type="ring", outer_diameter=_known("outer", 36), inner_diameter=_known("inner", 12)))
        volume, bounds = math.pi * (18**2 - 6**2) * 5, [[-18, -18, 0], [18, 18, 5]]
    status = build.create_model_rebuilder(output_dir)(_record(template), template)
    _prove(cad, status, volume, bounds, output_dir)
    assert _manifest(status)["template"] == template.model_dump(mode="json")
    assert status.provenance == template.provenance and status.review == template.review
    assert status.overall_size_mm == pytest.approx([hi - lo for lo, hi in zip(*bounds)])


@pytest.mark.parametrize("face,through", [("top", True), ("bottom", True), ("top", False), ("bottom", False)])
def test_plain_holes_have_global_lower_left_coordinates_and_correct_inward_depth(face, through, cad, output_dir):
    depth = 5 if through else 2
    template = _template(features=[_hole(face=face, through=through, depth=None if through else depth)])
    status = build.build_template(template, output_dir)
    solid = _prove(cad, status, 6000 - math.pi * 2**2 * depth, [[0, 0, 0], [40, 30, 5]], output_dir)
    assert not solid.isInside(cad.Vector(12, 10, 4 if face == "top" else 1), 1e-7)
    assert solid.isInside(cad.Vector(1, 1, 2), 1e-7)
    if not through:
        assert solid.isInside(cad.Vector(12, 10, 1 if face == "top" else 4), 1e-7)


@pytest.mark.parametrize("hole_type,face", [("countersunk", "top"), ("countersunk", "bottom"),
                                            ("counterbored", "top"), ("counterbored", "bottom")])
@pytest.mark.parametrize("through", [True, False])
def test_counter_features_analytic_volume_and_entry_face(hole_type, face, through, cad, output_dir):
    depth = 5 if through else 3
    if hole_type == "countersunk":
        extra = dict(countersink_diameter=_known("cs-diameter", 8), countersink_angle_deg=_known("cs-angle", 90, unit="deg"))
        cone_depth = (4 - 2) / math.tan(math.radians(45))
        removed = math.pi * 2**2 * depth + math.pi * cone_depth * (4**2 + 4*2 + 2**2) / 3 - math.pi * 2**2 * cone_depth
    else:
        extra = dict(counterbore_diameter=_known("cb-diameter", 8), counterbore_depth=_known("cb-depth", 2))
        removed = math.pi * 2**2 * depth + math.pi * (4**2 - 2**2) * 2
    status = build.build_template(_template(features=[_hole(hole_type=hole_type, face=face,
        through=through, depth=None if through else depth, **extra)]), output_dir)
    solid = _prove(cad, status, 6000 - removed, [[0, 0, 0], [40, 30, 5]], output_dir)
    assert not solid.isInside(cad.Vector(15, 10, 4.5 if face == "top" else 0.5), 1e-7)
    assert solid.isInside(cad.Vector(15, 10, 0.5 if face == "top" else 4.5), 1e-7)
    if not through:
        assert solid.isInside(cad.Vector(12, 10, 0.5 if face == "top" else 4.5), 1e-7)


@pytest.mark.parametrize("face,through", [("top", True), ("bottom", True), ("top", False), ("bottom", False)])
def test_capsule_slots_direction_end_to_end_length_and_blind_depth(face, through, cad, output_dir):
    depth = 5 if through else 2
    template = _template(features=[_slot(face=face, through=through, depth=None if through else depth)])
    area = 4 * (14 - 4) + math.pi * 2**2
    status = build.build_template(template, output_dir)
    solid = _prove(cad, status, 6000 - area * depth, [[0, 0, 0], [40, 30, 5]], output_dir)
    z = 4 if face == "top" else 1
    assert not solid.isInside(cad.Vector(20 + 5 * math.cos(math.pi/6), 15 + 5 * math.sin(math.pi/6), z), 1e-7)
    assert solid.isInside(cad.Vector(20 - 3 * math.sin(math.pi/6), 15 + 3 * math.cos(math.pi/6), z), 1e-7)
    if not through:
        assert solid.isInside(cad.Vector(20, 15, 1 if face == "top" else 4), 1e-7)


def test_row_pattern_uses_evidenced_start_spacing_and_direction(cad, output_dir):
    pattern = dict(type="row", count=_known("count", 3), spacing=_known("spacing", 8),
                   direction_deg=_known("row-angle", 90, unit="deg"))
    status = build.build_template(_template(features=[_hole(x=8, y=6, diameter=3, pattern=pattern)]), output_dir)
    solid = _prove(cad, status, 6000 - 3 * math.pi * 1.5**2 * 5, [[0, 0, 0], [40, 30, 5]], output_dir)
    for y in (6, 14, 22):
        assert not solid.isInside(cad.Vector(8, y, 2.5), 1e-7)
    assert solid.isInside(cad.Vector(16, 6, 2.5), 1e-7)


@pytest.mark.parametrize("irregular", [False, True])
def test_circle_pattern_uses_round_centre_and_printed_angles(irregular, cad, output_dir):
    angles = [0, 90, 225] if irregular else [45, 135, 225, 315]
    pattern = dict(type="circle", count=_known("count", len(angles)), radius=_known("radius", 12),
                   start_angle_deg=_known("start-angle", 45, unit="deg"), evenly_spaced=not irregular)
    if irregular:
        pattern["angles_deg"] = [_known(f"angle-{i}", angle, unit="deg") for i, angle in enumerate(angles)]
    template = _template(outline=dict(type="ring", outer_diameter=_known("outer", 36), inner_diameter=_known("inner", 12)),
                         features=[_hole(x=0, y=0, diameter=2, pattern=pattern)])
    volume = math.pi * (18**2 - 6**2) * 5 - len(angles) * math.pi * 5
    status = build.build_template(template, output_dir)
    solid = _prove(cad, status, volume, [[-18, -18, 0], [18, 18, 5]], output_dir)
    for angle in angles:
        assert not solid.isInside(cad.Vector(12 * math.cos(math.radians(angle)), 12 * math.sin(math.radians(angle)), 2), 1e-7)
    assert solid.isInside(cad.Vector(-12, 0, 2), 1e-7)


def test_slot_patterns_use_same_global_frame(cad, output_dir):
    pattern = dict(type="row", count=_known("count", 2), spacing=_known("spacing", 15),
                   direction_deg=_known("row-angle", 0, unit="deg"))
    template = _template(features=[_slot(x=10, y=15, width=3, length=8, angle=90, pattern=pattern)])
    status = build.build_template(template, output_dir)
    solid = _prove(cad, status, 6000 - 2 * (3 * 5 + math.pi * 1.5**2) * 5,
                   [[0, 0, 0], [40, 30, 5]], output_dir)
    for x in (10, 25):
        assert not solid.isInside(cad.Vector(x, 17, 2), 1e-7)
    assert solid.isInside(cad.Vector(17, 15, 2), 1e-7)


def test_explicit_circle_angles_do_not_expand_unused_start_angle_choices(cad, output_dir):
    pattern = dict(type="circle", count=_known("count", 3), radius=_known("radius", 8),
        start_angle_deg=_options("unused-start", [0, 45, 90, 135, 180], unit="deg"), evenly_spaced=False,
        angles_deg=[_known(f"explicit-angle-{i}", angle, unit="deg") for i, angle in enumerate([0, 90, 180])])
    template = _template(features=[_hole(x=20, y=15, pattern=pattern)])
    status = build.build_template(template, output_dir)
    solid = _prove(cad, status, 6000 - 3 * math.pi * 2**2 * 5, [[0, 0, 0], [40, 30, 5]], output_dir)
    assert len(status.examples) == 1 and status.examples[0].choices == {}
    assert _manifest(status)["template"] == template.model_dump(mode="json")
    for x, y in [(28, 15), (20, 23), (12, 15)]:
        assert not solid.isInside(cad.Vector(x, y, 2), 1e-7)


def test_cosmetic_threads_use_identified_printed_drill_diameter_without_nominal_conversion(cad, output_dir):
    thread = _hole(hole_type="threaded", diameter=4.2,
        thread_size=_known("thread-size", "M5"), thread_depth=_known("thread-depth", 3),
        note="Synthetic callout explicitly identifies diameter as the tap drill diameter.")
    status = build.build_template(_template(features=[thread]), output_dir)
    solid = _prove(cad, status, 6000 - math.pi * 2.1**2 * 5, [[0, 0, 0], [40, 30, 5]], output_dir)
    assert not solid.isInside(cad.Vector(14.05, 10, 2.5), 1e-7)
    assert solid.isInside(cad.Vector(14.2, 10, 2.5), 1e-7)
    assert "M5" in status.message and "No helical geometry" in status.message and "drill" in status.message
    assert any("helical" in omission.reason for omission in status.omitted_details)
    assert f"{PART}/source" in status.examples[0].source_ids


def test_only_geometry_alternatives_expand_all_four_examples_with_exact_evidence(cad, output_dir):
    thread = _hole(hole_type="threaded", diameter=4.2, thread_size=_options("thread-size", ["M5", "M6"]),
        thread_depth=_options("thread-depth", [2, 4]), note="Synthetic drill diameter convention is explicit.")
    data = _template(features=[thread]).model_dump(mode="json")
    data["thickness"] = _options("thickness", [5, 7], unit="mm")
    data["outline"]["value"]["length"] = _options("length", [40, 44], unit="mm")
    data["material"] = _options("material", ["Synthetic steel", "Synthetic aluminium"])
    data["weight_on_drawing"] = _options("weight", [100, 120], unit="g")
    template = c.FlatTemplate.model_validate(data)
    normalized = template.model_dump(mode="json")
    status = build.build_template(template, output_dir)
    assert status.state == "available", status.message
    assert [e.id for e in status.examples] == list("ABCD") and status.selected_example is None
    assert status.overall_size_mm is None and "differs by example" in status.message
    expected_choices = [(40, 5), (40, 7), (44, 5), (44, 7)]
    for i, (length, thickness) in enumerate(expected_choices):
        ex = status.examples[i]
        assert ex.choices == {f"{PART}/template/length": length, f"{PART}/template/thickness": thickness}
        _prove(cad, status, length * 30 * thickness - math.pi * 2.1**2 * thickness,
               [[0, 0, 0], [length, 30, thickness]], output_dir, example=i)
        choice_evidence = _manifest(status)["measurements"][i]["choice_evidence"]
        for field in (normalized["outline"]["value"]["length"], normalized["thickness"]):
            option = next(option for option in field["options"] if option["value"] == ex.choices[field["name"]])
            assert choice_evidence[field["name"]] == option
            assert set(option["evidence"]["number_ids"]) <= set(ex.source_ids)
    assert _manifest(status)["template"] == template.model_dump(mode="json")


def test_unknown_minor_details_have_exact_names_sources_reason_and_review_link(cad, output_dir):
    unknown = _unknown("minor-detail")
    unknown["review_item"] = dict(id="synthetic-minor-review", href="/api/review/synthetic-minor-review")
    hole = _hole()
    hole["value"]["position"]["x"] = _unknown("missing-coordinate")
    template = _template(features=[unknown, hole])
    status = build.build_template(template, output_dir)
    _prove(cad, status, 6000, [[0, 0, 0], [40, 30, 5]], output_dir)
    omissions = {item.name: item for item in status.omitted_details}
    assert set(omissions) == {f"{PART}/template/minor-detail", f"{PART}/template/missing-coordinate"}
    for omitted in omissions.values():
        assert omitted.source_ids == [f"{PART}/source"]
        assert "unreadable_scan: Synthetic coordinate/detail is unreadable." in omitted.reason
    assert omissions[f"{PART}/template/minor-detail"].review_item.id == "synthetic-minor-review"
    assert "Feature" in omissions[f"{PART}/template/missing-coordinate"].reason


def test_unknown_cosmetic_depth_does_not_remove_evidenced_drill_geometry(cad, output_dir):
    template = _template(features=[_hole(hole_type="threaded", diameter=4.2, thread_size=_known("thread-size", "M5"),
        thread_depth=_unknown("thread-depth"), note="Synthetic diameter is a printed tap drill diameter.")])
    status = build.build_template(template, output_dir)
    _prove(cad, status, 6000 - math.pi * 2.1**2 * 5, [[0, 0, 0], [40, 30, 5]], output_dir)
    omission = next(item for item in status.omitted_details if item.name.endswith("thread-depth"))
    assert "Non-geometric annotation omitted" in omission.reason and "unreadable_scan" in omission.reason


def test_minor_side_face_omission_and_unidentified_thread_are_disclosed(cad, output_dir):
    features = [_hole("side", face="left"), _hole("nominal-thread", hole_type="threaded",
        diameter=5, thread_size=_known("thread-size", "M5"))]
    status = build.build_template(_template(features=features), output_dir)
    _prove(cad, status, 6000, [[0, 0, 0], [40, 30, 5]], output_dir)
    assert len(status.omitted_details) == 2
    assert "unsupported" in status.omitted_details[0].reason
    assert "not identified" in status.omitted_details[1].reason


def test_essential_thread_without_drill_convention_blocks_before_cad(output_dir, monkeypatch):
    template = _template(features=[_hole(hole_type="threaded", diameter=5,
        thread_size=_known("thread-size", "M5"), essential=True)])
    _forbid_cad(monkeypatch)
    status = build.build_template(template, output_dir)
    assert status.state == "blocked" and "No nominal-to-drill conversion" in status.message


@pytest.mark.parametrize("problem", ["zero-thickness", "negative-length", "inverted-ring", "blind-through",
    "outside-hole", "slot-width", "counterbore-depth", "countersink-angle", "empty-cut", "irregular-angles", "ambiguous-angles", "ring-slot"])
def test_invalid_or_unsupported_geometry_never_advertises_a_model(problem, cad, output_dir):
    data = _template().model_dump(mode="json")
    if problem == "zero-thickness":
        data["thickness"]["value"] = 0
    elif problem == "negative-length":
        data["outline"]["value"]["length"]["value"] = -40
    elif problem == "inverted-ring":
        data = _template(outline=dict(type="ring", outer_diameter=_known("outer", 12), inner_diameter=_known("inner", 36))).model_dump(mode="json")
    elif problem == "blind-through":
        data["features"] = [_hole(through=False, depth=5)]
    elif problem == "outside-hole":
        data["features"] = [_hole(x=0, y=0)]
    elif problem == "slot-width":
        data["features"] = [_slot(width=8, length=4)]
    elif problem == "counterbore-depth":
        data["features"] = [_hole(hole_type="counterbored", counterbore_diameter=_known("head", 8), counterbore_depth=_known("head-depth", 8))]
    elif problem == "countersink-angle":
        data["features"] = [_hole(hole_type="countersunk", countersink_diameter=_known("head", 8), countersink_angle_deg=_known("head-angle", 180, unit="deg"))]
    elif problem == "empty-cut":
        data["features"] = [_hole("first"), _hole("duplicate")]
    elif problem in {"irregular-angles", "ambiguous-angles"}:
        pattern = dict(type="circle", count=_known("count", 3), radius=_known("radius", 5),
            start_angle_deg=_known("start", 0, unit="deg"), evenly_spaced=problem == "ambiguous-angles",
            angles_deg=[_known("one-angle", 0, unit="deg")])
        data["features"] = [_hole(pattern=pattern)]
    else:
        data = _template(outline=dict(type="ring", outer_diameter=_known("outer", 36), inner_diameter=_known("inner", 12)),
            features=[_slot(x=0, y=0, width=2, length=24, angle=0)]).model_dump(mode="json")
    status = build.build_template(c.FlatTemplate.model_validate(data), output_dir)
    assert status.state == "blocked", status.model_dump(mode="json")
    assert not status.examples and status.built_at is None and status.built_template_sha256 is None
    assert not list(output_dir.rglob("*.glb")) and not list(output_dir.rglob("manifest.json"))


def test_cache_survives_factory_restart_without_cad_and_preserves_timestamp_hashes_and_human_choice(cad, output_dir, monkeypatch):
    data = _template().model_dump(mode="json")
    data["thickness"] = _options("thickness", [5, 7], unit="mm")
    template = c.FlatTemplate.model_validate(data)
    first = build.create_model_rebuilder(output_dir)(_record(template), template)
    assert first.state == "available", first.message
    paths = [_path(e.glb) for e in first.examples] + [_path(e.step) for e in first.examples]
    identities = {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}
    first.selected_example = "B"  # An explicit simulated human viewing choice.
    _forbid_cad(monkeypatch)
    cached = build.create_model_rebuilder(output_dir)(_record(template, previous=first), template)
    assert cached.state == "available" and "cached" in cached.message
    assert cached.built_at == first.built_at and cached.examples == first.examples
    assert cached.selected_example == "B"
    assert identities == {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}


def test_missing_essential_change_retains_only_verified_old_assets_as_stale(cad, output_dir, monkeypatch):
    template = _template()
    first = build.build_template(template, output_dir)
    assert first.state == "available", first.message
    data = template.model_dump(mode="json")
    data["thickness"] = _unknown("thickness")
    changed = c.FlatTemplate.model_validate(data)
    _forbid_cad(monkeypatch)
    stale = build.create_model_rebuilder(output_dir)(_record(template, previous=first), changed)
    assert stale.state == "stale" and stale.examples == first.examples
    assert stale.built_at == first.built_at and stale.built_template_sha256 == c.contract_digest(template)
    assert stale.current_template_sha256 == c.contract_digest(changed)
    assert stale.built_template_sha256 != stale.current_template_sha256 and stale.stale_reason


@pytest.mark.parametrize("damage", ["corrupt-glb", "missing-glb", "missing-step"])
def test_corrupted_or_missing_cache_assets_are_never_called_available(damage, cad, output_dir, monkeypatch):
    template = _template()
    first = build.build_template(template, output_dir)
    assert first.state == "available", first.message
    if damage == "corrupt-glb":
        _path(first.examples[0].glb).write_bytes(b"damaged CAD artifact")
    else:
        _path(first.examples[0].step if damage == "missing-step" else first.examples[0].glb).unlink()

    def unavailable(name):
        raise ModuleNotFoundError(name)
    monkeypatch.setattr(build, "import_module", unavailable)
    status = build.build_template(template, output_dir, previous=first)
    assert status.state == "missing" and not status.examples
    assert status.built_at is None and status.built_template_sha256 is None


def test_effective_template_change_rebuilds_only_affected_part_and_preserves_previous_identity(cad, output_dir):
    data = _template().model_dump(mode="json")
    data["thickness"] = _options("thickness", [5, 7], unit="mm")
    original = c.FlatTemplate.model_validate(data)
    other = _template(part="D-902")
    first = build.build_template(original, output_dir)
    unaffected = build.build_template(other, output_dir)
    assert first.state == unaffected.state == "available"
    path = _path(unaffected.examples[0].glb)
    unchanged_identity = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    option = data["thickness"]["options"][1]
    data["thickness"] = dict(name=f"{PART}/template/thickness", method="human_decision", state="known",
                              value=option["value"], evidence=option["evidence"], unit="mm", essential=True)
    effective = c.FlatTemplate.model_validate(data)
    updated = build.create_model_rebuilder(output_dir)(_record(original, previous=first), effective)
    _prove(cad, updated, 40 * 30 * 7, [[0, 0, 0], [40, 30, 7]], output_dir)
    assert len(updated.examples) == 1 and updated.selected_example is None
    assert updated.current_template_sha256 == c.contract_digest(effective) != first.built_template_sha256
    assert updated.examples[0].glb != first.examples[0].glb
    assert all(_path(example.glb).is_file() for example in first.examples)
    assert unchanged_identity == (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())


def test_failed_export_retains_old_built_digest_instead_of_claiming_a_rebuild(cad, output_dir, monkeypatch):
    template = _template()
    first = build.build_template(template, output_dir)
    assert first.state == "available", first.message
    changed = _template(thickness=7)

    def failure(*args):
        raise RuntimeError("Synthetic kernel/export failure")
    monkeypatch.setattr(build, "_solid", failure)
    status = build.build_template(changed, output_dir, previous=first)
    assert status.state == "stale" and status.examples == first.examples
    assert status.built_at == first.built_at and status.built_template_sha256 == c.contract_digest(template)
    assert status.current_template_sha256 == c.contract_digest(changed)
    assert "Synthetic kernel/export failure" in status.stale_reason
