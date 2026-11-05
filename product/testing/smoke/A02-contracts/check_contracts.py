"""Focused B00 contract check; stdlib plus Pydantic v2, no app or model calls."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import json
import math
from pathlib import Path
import struct
import sys

from pydantic import Field, ValidationError


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
c = importlib.import_module("development.backend.contracts")
FIXTURES = ROOT / "testing/fixtures/contracts"
TEMP = ROOT / "testing/tmp/A02-contracts"
TYPES = ROOT / "development/frontend/src/contracts.ts"
SENTINEL = "// END GENERATED PAYLOAD TYPES\n"


class SyntheticAsset(c.Payload):
    file: str
    media_type: str
    sha256: c.SHA256
    size_mm: c.Vector3
    gltf_units: str


class FixtureEntry(c.ContractModel):
    file: str
    model: str


class FixtureManifest(c.Payload):
    entries: list[FixtureEntry]
    binary_assets: list[str]


def ts_type(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(x, ensure_ascii=False) for x in schema["enum"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " | ".join(ts_type(x) for x in schema[key])
    kind = schema.get("type")
    if kind == "array":
        if "prefixItems" in schema:
            return "[" + ", ".join(ts_type(x) for x in schema["prefixItems"]) + "]"
        return f"Array<{ts_type(schema.get('items', {}))}>"
    if kind == "object":
        if "properties" in schema:
            required = schema.get("required", [])
            fields = [f"  {json.dumps(name)}{'' if name in required else '?'}: {ts_type(value)};"
                      for name, value in schema["properties"].items()]
            return "{\n" + "\n".join(fields) + "\n}"
        additional = schema.get("additionalProperties", {})
        return "{ [key: string]: " + (ts_type(additional) if isinstance(additional, dict) else "JsonValue") + " }"
    if kind in {"number", "integer"}:
        return "number"
    if kind in {"string", "boolean", "null"}:
        return kind
    if not schema:
        return "JsonValue"
    raise AssertionError(f"Unhandled schema: {schema}")


def generated_types() -> str:
    definitions = c.contract_json_schema()["$defs"]
    header = (
        "/** Frozen M02 payload mirror of backend/contracts.py.\n"
        " * Schema-derived section verified by testing/smoke/A02-contracts/check_contracts.py.\n"
        " * Defaulted Python fields are optional on input; model_dump emits them.\n"
        " * Python validates runtime constraints (hashes, dates, evidence and provenance).\n"
        " * Dates are timezone-aware ISO strings; numbers are finite.\n"
        " * M2/M3 shapes reserve interfaces only, not implemented behavior.\n"
        " */\n\n"
    )
    declarations = [f"export type {name} = {ts_type(schema)};\n"
                    for name, schema in sorted(definitions.items())]
    endpoints = json.dumps([dataclasses.asdict(e) for e in c.API_ENDPOINTS], ensure_ascii=False, indent=2)
    return header + "\n".join(declarations) + f"\nexport const API_ENDPOINTS = {endpoints} as const;\n\n"


def require_rejection(factory, label: str) -> None:
    try:
        factory()
    except (ValidationError, ValueError):
        return
    raise AssertionError(f"Invalid contract was accepted: {label}")


def check_glb(path: Path, metadata: SyntheticAsset) -> None:
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == metadata.sha256
    magic, version, length = struct.unpack_from("<III", data)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    offset, chunks = 12, []
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        assert chunk_length % 4 == 0
        offset += 8
        assert offset + chunk_length <= len(data)
        chunks.append((chunk_type, data[offset:offset + chunk_length]))
        offset += chunk_length
    assert offset == len(data) and [x[0] for x in chunks] == [0x4E4F534A, 0x004E4942]
    document = json.loads(chunks[0][1])
    binary = chunks[1][1]
    assert document["asset"]["version"] == "2.0"
    assert document["extras"]["fixture"] and document["extras"]["synthetic"]
    assert document["extras"]["fixture_note"]
    assert "uri" not in document["buffers"][0]
    assert document["buffers"][0]["byteLength"] <= len(binary)
    assert len(binary) - document["buffers"][0]["byteLength"] < 4
    assert document["scenes"][document["scene"]]["nodes"] == [0]
    mesh = document["meshes"][document["nodes"][0]["mesh"]]
    primitive = mesh["primitives"][0]
    assert primitive.get("mode", 4) == 4
    accessors = document["accessors"]
    views = document["bufferViews"]
    for view in views:
        assert view["buffer"] == 0 and view.get("byteOffset", 0) % 4 == 0
        assert view.get("byteOffset", 0) + view["byteLength"] <= len(binary)
    decoded = []
    for accessor in accessors:
        view = views[accessor["bufferView"]]
        offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        dimensions = {"SCALAR": 1, "VEC3": 3}[accessor["type"]]
        code, size = {5126: ("f", 4), 5123: ("H", 2)}[accessor["componentType"]]
        count = accessor["count"] * dimensions
        assert accessor.get("byteOffset", 0) + count * size <= view["byteLength"]
        decoded.append(struct.unpack_from("<" + code * count, binary, offset))
    positions = decoded[primitive["attributes"]["POSITION"]]
    normals = decoded[primitive["attributes"]["NORMAL"]]
    indices = decoded[primitive["indices"]]
    vertices = list(zip(positions[::3], positions[1::3], positions[2::3]))
    assert len(vertices) == 24 and len(normals) == 72 and len(indices) == 36
    assert all(math.isfinite(value) for value in positions + normals)
    assert max(indices) < len(vertices) and min(indices) >= 0
    for index in range(0, len(normals), 3):
        assert math.isclose(sum(n * n for n in normals[index:index + 3]), 1, abs_tol=1e-6)
    # glTF is meters with y up; fixture CAD dimensions are mm (x length/y width/z thickness).
    actual = [max(p[i] for p in vertices) - min(p[i] for p in vertices) for i in range(3)]
    expected = [metadata.size_mm[0] / 1000, metadata.size_mm[2] / 1000, metadata.size_mm[1] / 1000]
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(actual, expected))
    volume = 0.0
    for index in range(0, len(indices), 3):
        a, b, d = [vertices[indices[index + k]] for k in range(3)]
        cross = (b[1] * d[2] - b[2] * d[1], b[2] * d[0] - b[0] * d[2], b[0] * d[1] - b[1] * d[0])
        volume += sum(a[i] * cross[i] for i in range(3)) / 6
    assert math.isclose(abs(volume), math.prod(expected), rel_tol=1e-6)
    print(f"PASS GLB: {path.name}; glTF 2.0 JSON+BIN, 24 vertices, 12 triangles, synthetic solid volume")


def helper_cases() -> dict:
    assert c.normalize_component("  Training / BRACKET__ (Q)  ") == "training-bracket__-q"
    assert c.drawing_fact_name(" d-013 ", "Weight_g") == "D-013/drawing/weight_g"
    assert c.template_fact_name("D-025", "Outer Diameter") == "D-025/template/outer-diameter"
    assert c.bom_part_name("Mock Section", "Fixture / Clamp") == "BOM:mock-section/fixture-clamp/part"
    assert c.mapping_name("material", "Mock Alloy Q7", "Mock Metal") == "names/material/mock-alloy-q7 -> mock-metal"
    assert c.readme_name("Synthetic Section", 2) == "README/synthetic-section/p2"
    ids = ["D-013/part", "BOM:mock-section/fixture-clamp/material", "names/material/mock-a -> mock-b",
           "literal%2F/plus+space and!()*'", "README/synthetic-ø/p2"]
    encoded = []
    for value in ids:
        segment = c.encode_id(value)
        assert "/" not in segment and c.decode_id(segment) == value
        encoded.append({"value": value, "encoded": segment})
    require_rejection(lambda: c.decode_id("bad%2"), "invalid percent encoding")
    require_rejection(lambda: c.decode_id("raw/slash"), "unencoded slash")
    page = c.PageGeometry(page=1, source_width=200, source_height=100, image_width=800, image_height=300)
    coordinate_cases = []
    for box, zoom, offset in [((10, 20, 30, 5), 2, (7, 11)), ((0, 0, 0, 0), .25, (0, 0)),
                              ((17.5, 9.25, 1.5, 3.75), 1.3, (4, 8))]:
        pixels = c.source_box_to_pixels(box, page, zoom, offset)
        expected = (box[0] * 4 * zoom + offset[0], box[1] * 3 * zoom + offset[1],
                    box[2] * 4 * zoom, box[3] * 3 * zoom)
        assert all(math.isclose(a, b, abs_tol=1e-10) for a, b in zip(pixels, expected))
        recovered = c.pixel_box_to_source(pixels, page, zoom, offset)
        assert all(math.isclose(a, b, abs_tol=1e-10) for a, b in zip(recovered, box))
        coordinate_cases.append({"box": box, "zoom": zoom, "offset": offset, "pixels": expected})
    require_rejection(lambda: c.source_box_to_pixels((1, 1, 2, 2), page, 0), "zero zoom")
    require_rejection(lambda: c.source_box_to_pixels((1, 1, -2, 2), page), "negative width")
    print("PASS helpers: normalization/names, five URL round trips, three pixel mappings and inverses")
    return {"ids": encoded, "page": page.model_dump(mode="json"), "coordinates": coordinate_cases}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-types", action="store_true")
    args = parser.parse_args()
    source = TYPES.read_text(encoding="utf-8")
    prefix = generated_types()
    assert SENTINEL in source
    suffix = source.split(SENTINEL, 1)[1]
    expected = prefix + SENTINEL + suffix
    if args.write_types:
        TYPES.write_text(expected, encoding="utf-8", newline="\n")
        print(f"WROTE {TYPES.relative_to(ROOT)} from {len(c.CONTRACT_MODELS)} concrete models")
        return
    assert source == expected, "Python/TS payload schema drift (run --write-types deliberately)"
    print(f"PASS mirror: {len(c.contract_json_schema()['$defs'])} Python schema definitions match TypeScript")
    TEMP.mkdir(parents=True, exist_ok=True)
    manifest = FixtureManifest.model_validate_json((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.fixture and manifest.synthetic
    assert set(path.name for path in FIXTURES.glob("*.json")) == {"manifest.json", *(e.file for e in manifest.entries)}
    assert set(path.name for path in FIXTURES.glob("*.glb")) == set(manifest.binary_assets)
    fixtures = {}
    typed = ["// Temporary fixture assignment checks; generated by the focused B00 smoke checker."]
    for index, entry in enumerate(manifest.entries):
        path = FIXTURES / entry.file
        data = json.loads(path.read_text(encoding="utf-8"))
        model = SyntheticAsset if entry.model == "SyntheticAsset" else c.CONTRACT_MODELS[entry.model]
        validated = model.model_validate(data)
        assert validated.fixture and validated.synthetic and validated.fixture_note
        assert json.loads(validated.model_dump_json()) == data, f"Fixture is not canonical: {entry.file}"
        fixtures[entry.file] = validated
        if entry.model != "SyntheticAsset":
            typed.append(f"const fixture_{index}: import('../../../development/frontend/src/contracts').{entry.model} = "
                         + json.dumps(data, ensure_ascii=False) + ";")
            typed.append(f"void fixture_{index};")
        print(f"PASS fixture: {entry.file} -> {entry.model}")
    (TEMP / "fixtures.ts").write_text("\n".join(typed) + "\n", encoding="utf-8")
    record = fixtures["D-013.json"]
    template = fixtures["flat-template.json"]
    number_ids = {number.name for number in record.drawing.numbers}

    def inspect_template(value):
        if isinstance(value, dict):
            if "number_ids" in value:
                assert set(value["number_ids"]) <= number_ids
            if value.get("kind") in {"arithmetic", "pattern"} and "inputs" in value:
                assert set(value["inputs"]) <= number_ids
            for child in value.values():
                inspect_template(child)
        elif isinstance(value, list):
            for child in value:
                inspect_template(child)

    inspect_template(template.model_dump(mode="json"))
    chat = fixtures["chat-response.json"]
    for marker in chat.markers:
        assert chat.text[marker.start:marker.end] == marker.raw
        assert set(marker.names) <= chat.facts.keys()
        if marker.kind == "undetermined":
            assert chat.facts[marker.names[0]].display.state == "undetermined"
    pending = fixtures["review-item.json"]
    assert pending.ai_answers.mode == "single_model"
    assert pending.ai_answers.rounds[0].opus.output is None
    require_rejection(lambda: c.StatusResponse(chat_available=True, chat_state="missing_key", message="fixture"), "contradictory chat status")
    invalid_fallback = pending.ai_answers.model_dump(mode="json")
    invalid_fallback["rounds"][0]["opus"]["status"] = "success"
    require_rejection(lambda: c.PrepProvenance.model_validate(invalid_fallback), "invented missing-reader success")
    fake_consensus = template.provenance.model_dump(mode="json")
    fake_consensus["rounds"][0]["opus"]["effective"] = fake_consensus["rounds"][0]["sol"]["effective"]
    require_rejection(lambda: c.PrepProvenance.model_validate(fake_consensus), "two Sol runs as consensus")
    require_rejection(lambda: c.KnownNumberField(name="D-013/template/invalid", value=9, method="parsed", evidence={}), "uncited numeric template field")
    print("PASS fixture links: template number IDs, chat spans/Undetermined, honest missing Opus and provenance guards")
    for fixture in fixtures.values():
        if isinstance(fixture, SyntheticAsset):
            check_glb(FIXTURES / fixture.file, fixture)
    cases = helper_cases()
    cases["endpoints"] = [dataclasses.asdict(e) for e in c.API_ENDPOINTS]
    (TEMP / "helper-cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS B00 Python smoke: {len(manifest.entries)} declared JSON fixtures, no real evidence/provider/app validation claimed")


if __name__ == "__main__":
    main()
