# A02-contracts B00 / M02 smoke

Result: **PASS for the focused contract/fixture checks below**, 2026-11-05, Windows PowerShell. This is the complete M02 contract slice, not an application, preparation, CAD qualification, or V1–V5 gate result.

Working directory for every command:

```text
C:\Users\Jason\Documents\Jason\Take-Home-Assignments\active\Avathon\product\.harness-runtime\worktrees\9835572aa8594664acdb2346c2fcc64e\A02-contracts
```

Branch: `lane/9835572aa8594664acdb2346c2fcc64e/A02-contracts/work`. Starting revision: `a279e45b98554f7c39d0d8cf47667bae860a5180`. The completion record identifies the full committed candidate tip; this report is included in that commit.

## Scope and decisions

- `development/backend/contracts.py` defines Pydantic v2 payloads and dependency signatures. `development/frontend/src/contracts.ts` mirrors the payload schema and freezes A17–A22 props, navigation callbacks, API call shapes, and the proposal/refresh boundary. The checker compares the complete generated payload section to Python, rather than checking a hand-selected set of names.
- Stable descriptive components use NFKC, lowercase, ASCII letters/digits/underscore/hyphen, replacement of other runs with `-`, collapsed hyphens, and trimming. Drawing IDs retain `D-`; BOM rows retain `BOM:`. Duplicate/colliding names require a flag, not an automatic suffix. Every URL ID is encoded as one RFC3986 segment, with slash encoded as `%2F`; decode only once. Image routes take the complete part ID, e.g. `/api/parts/D-013%2Fpart/image?page=1&thumb=1`.
- Boxes are `[x,y,width,height]`, top-left origin, x right/y down, in the saved page frame after crop/rotation. Page numbers start at 1. Pixel scaling uses the actual saved raster width and height independently, multiplied by zoom, with an optional viewport offset. CAD positions use a separate x-right/y-up frame.
- Drawing and BOM evidence remain separate. Effective `FactResult` values retain original source text, method, confidence, review, and correction overlays. Unknown/unsure values, printed options, and Undetermined display are different states. A review link identifies an actual item; uncertainty alone does not create one.
- Prep metadata retains requested/effective identities and settings, both reader slots, classified failures, and up to two rounds. Sol-only mode has an explicitly null Opus output and a separate count; it cannot be labeled independent agreement. Templates preserve numeric number IDs or derivations. Accepted/rejected decisions are append-only events with actor, timezone-aware time, and reviewed source hashes; pending/rejected proposals do not become effective corrections.
- `ReviewActionRequest` is the POST body. `ReviewActionResponse` carries the updated item, decisions, and refresh result. M03 injects M16's proposal callback into M14; M16 receives direct decisions/records/CAD functions through the frozen signatures. The contracts import no chat, tools, review, or router modules.
- Model metadata includes available/stale/blocked/unsupported/missing states, example choices, omissions, review/provenance, and the reconstruction label. Stale GLBs remain viewable. M2/M3 weight/history/accuracy/callout/crop/README/STEP fields and endpoints reserve shapes only.

No contract choice needs a human decision; no proposed USER_TODO entry.

## Environment and exact commands

Tools observed: uv `0.11.19`; Python `3.12.10`; Pydantic `2.14.2`, pydantic-core `2.50.2`; Node `v24.19.0`; npm/npx `11.17.0`; TypeScript `5.9.3`.

The temporary environment and emitted JS/fixture assignment files are under `testing/tmp/A02-contracts/`. Dependencies were not installed globally. uv and npm used the inherited caches:

```text
UV_CACHE_DIR=C:\Users\Jason\Documents\Jason\Take-Home-Assignments\active\Avathon\product\testing\cache\uv
npm_config_cache=C:\Users\Jason\Documents\Jason\Take-Home-Assignments\active\Avathon\product\testing\cache\npm
```

| Exact command | Actual outcome |
| --- | --- |
| `uv venv --python 3.12 testing/tmp/A02-contracts/venv` | Exit 0; created the temporary Python 3.12.10 environment. |
| `uv pip install --python testing/tmp/A02-contracts/venv/Scripts/python.exe 'pydantic>=2,<3'` | Exit 0; installed Pydantic 2.14.2 and its four dependencies. |
| `testing/tmp/A02-contracts/venv/Scripts/python.exe testing/smoke/A02-contracts/check_contracts.py --write-types` | Exit 0; generated the payload section from 106 concrete models. Handwritten helpers/props follow the generated-section sentinel. |
| `testing/tmp/A02-contracts/venv/Scripts/python.exe testing/smoke/A02-contracts/build_fixtures.py` | Exit 0; wrote 17 declared synthetic JSON examples, the manifest, and two GLB solids. Writes are restricted to the contract fixtures directory; no real decision journal is used. |
| `testing/tmp/A02-contracts/venv/Scripts/python.exe testing/smoke/A02-contracts/check_contracts.py` | Final exit 0; 136 schema definitions match TS; all 17 JSON examples and the manifest validate; canonical JSON round trips, template number references, marker spans, and missing-reader metadata pass. Both GLBs and helper checks pass. |
| `npx.cmd --yes --package typescript@5.9.3 tsc --strict --target ES2022 --module commonjs --lib ES2022,DOM --outDir testing/tmp/A02-contracts/compiled development/frontend/src/contracts.ts testing/tmp/A02-contracts/fixtures.ts` | Final exit 0; no compiler diagnostics. Checked contracts plus typed assignments of all product JSON examples. Emitted files remain in the temporary directory. |
| `node testing/smoke/A02-contracts/check_helpers.cjs` | Exit 0; Python/TS naming, encoding, coordinate, endpoint, and Unicode marker-offset parity pass. |
| `npx.cmd --yes --package typescript@5.9.3 tsc --version` | Exit 0; `Version 5.9.3`. |
| `testing/tmp/A02-contracts/venv/Scripts/python.exe --version` | Exit 0; `Python 3.12.10`. |
| `uv pip show --python testing/tmp/A02-contracts/venv/Scripts/python.exe pydantic` | Exit 0; Pydantic 2.14.2 located in the temporary environment. |
| `git diff --cached --check` | Exit 0; staged changes have no whitespace errors. |
| `git diff --cached --name-only` | Exit 0; 26 staged paths, all within A02 ownership. |

The final successful checks followed the final contract edits. No project package/config files or package `__init__.py` files were needed.

## Observed checks

- Five URL round trips include drawing/BOM/mapping IDs, literal percent text, punctuation, and Unicode. Raw slashes and malformed percent escapes are rejected. Tests distinguish one decode from double decoding.
- Three coordinate cases include nonuniform raster scale, fractional zoom, a zero-size box, and viewport offsets. Independently stated expected pixels and inverse mappings agree in Python and emitted JavaScript; invalid zoom/negative width are rejected.
- The chat example starts with an emoji to exercise Unicode code-point offsets across Python and JS. Its Undetermined marker references an undetermined fact, both markers reference returned fixture facts, and an attachment remains available with uncertainty.
- Numeric template fields without evidence, fake two-Sol consensus, invented missing-reader success, and contradictory status are rejected. The fixture includes two printed alternatives and a minor unknown detail; those states remain distinct.
- Each GLB has the `glTF` magic, version 2, correct total length, aligned JSON and BIN chunks, a glTF 2.0 asset, bounded buffer views/accessors, finite positions/normals, valid indices, scene/mesh/material references, and embedded `fixture`/`synthetic` metadata. Each has 24 vertices and 12 triangles. Dimensions and signed tetrahedral volume match the synthetic rectangular solid. A and B have different synthetic thicknesses, so switching assets does not silently reuse the same geometry.

Final checker output included:

```text
PASS mirror: 136 Python schema definitions match TypeScript
PASS fixture links: template number IDs, chat spans/Undetermined, honest missing Opus and provenance guards
PASS GLB: sample.glb; glTF 2.0 JSON+BIN, 24 vertices, 12 triangles, synthetic solid volume
PASS GLB: sample-B.glb; glTF 2.0 JSON+BIN, 24 vertices, 12 triangles, synthetic solid volume
PASS helpers: normalization/names, five URL round trips, three pixel mappings and inverses
PASS B00 Python smoke: 17 declared JSON fixtures, no real evidence/provider/app validation claimed
PASS TypeScript runtime: names, five URL round trips, three pixel mappings/inverses, endpoint parity, Unicode marker spans
```

## Corrected preliminary failures

An exploratory `python -c` import/schema-count command exited 1 with `KeyError: ''` because PowerShell expanded `$defs` inside its double-quoted argument. The file-based checker replaces that exploratory command and successfully imports the module without package plumbing.

The first invocation of the exact TypeScript compile command above exited 1 with `TS2456: Type alias 'JsonValue' circularly references itself`. Pydantic 2.14.2 emits `{}` for the JSON domain; the schema exporter now explicitly describes recursive JSON values and the generator emits an index signature. The final compile and runtime parity commands then exited 0. No unresolved failing check is represented as passed.

## Limits and ownership

All fixture JSON roots have `fixture: true`, `synthetic: true`, and a short note. The GLBs embed these declarations and have validated, hashed JSON sidecars. Names, material strings, dimensions, hashes, reader output/failures, and proposed/rejected decision examples are invented. They do not validate or claim facts about the real D-013 or D-025. The drawing image/source references are illustrative synthetic addresses; this slice does not ship PDF/PNG evidence.

Real-source extraction/engineering validation, actual prep-reader execution/agreement, chat key/provider behavior, server routes, browser rendering/orbit controls, real CadQuery export/rebuilds, and M1–M3 behavior were **not performed or qualified here**. No credentials or real decision files were accessed. The synthetic fixtures do not count toward the three required real reconstructions or any release gate.

Project changes are limited to the two owned contract files, `testing/fixtures/contracts/`, `testing/smoke/A02-contracts/`, and this report directory. `RESULT.json` is generated completion bookkeeping and is excluded from the commit. The assigned branch tip and clean-source result are recorded separately in that completion record.
