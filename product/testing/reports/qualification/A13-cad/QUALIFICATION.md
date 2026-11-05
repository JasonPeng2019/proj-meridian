# A13-cad B00 qualification — PASS

Qualified on 2026-11-05T08:02:27.236813+00:00 on Windows-10-10.0.19045-SP0. B00 capability probe only; M13 implementation and B05 have not started. All geometry below uses **invented test values, not dimensions taken from any drawing**. No source drawings were read.

## Proven environment and export path

Python **3.12.10**, CadQuery **2.8.0**, **cadquery-ocp 7.9.3.1.1** (OCP module reports **7.9.3.1**), cadquery-ocp-proxy 7.9.3.1.1, NumPy 2.5.4, VTK 9.6.2. The complete 44-package freeze, exact executed argument arrays and launcher binding are in [qualification.json](qualification.json). The lane invocation declares Codex gpt-6.1-sol, max reasoning, service_tier fast, matching the assignment; no fallback.

Independent tools: Node v24.19.0, Three.js 0.187.0, Khronos glTF Validator 2.0.0-dev.3.10; npm 11.17.0, uv 0.11.19. Dependencies are ignored under `development/.runtime/`.

The supported path is `cq.Assembly` with `cq.Color(0.6, 0.6, 0.6, 1)`, then `Assembly.export(..., exportType="GLTF")` to a `.glb` filename. In this actual version, an unscaled export retains millimetre coordinate numbers. **Scale a copy of the solid by 0.001 before GLB export**; glTF distances are metres. CadQuery exports Z-up as Y-up: `(x, y, z) -> (x, z, -y)`. Keep the original solid in mm for volume/STEP. Qualified tessellation settings: 0.00005 m linear and 0.1 rad angular tolerance.

## Synthetic fixture and measured checks

Plate: 100 × 60 × 5 mm, centred in XY, Z from 0 to 5 mm. One Ø10 mm through hole at (0,0); two Ø6 mm through holes at (-25,15) and (25,15) mm. These are all invented, disjoint, internal test features.

Analytic volume: `100*60*5 - pi*5*(5**2 + 2*3**2)` = **29324.557579478194 mm³**.

| Check | Actual result | Acceptance tolerance / outcome |
| --- | --- | --- |
| CadQuery topology / volume | One valid solid; 29324.557579478194 mm³; absolute error 0 | ≤ 1e-6 mm³; PASS |
| CAD bounds | min (-50,-30,0), max (50,30,5) mm | ≤ 1e-6 mm per coordinate; PASS |
| Binary glTF 2.0 | `glTF` magic; header version 2; declared and actual length 85432 bytes; JSON 4256 bytes then BIN 81148 bytes | Aligned chunks, JSON asset 2.0, one mesh, 27 accessors, 2,700 triangles; PASS |
| GLB world bounds | min (-0.05000000074505806, -6.66e-18, -0.02999999932944774), max (0.05000000074505806, 0.004999999888241296, 0.02999999932944774) m | Expected min (-0.05,0,-0.03), max (0.05,0.005,0.03) m; max error 7.45058056917e-10 m ≤ 1e-7 m (0.0001 mm); PASS |
| Tessellated volume, extra check | 29324.646065383084 mm³ | Relative error 3.01746768555e-06 = 0.000301747% ≤ 0.1%; PASS |
| Neutral grey | Linear RGBA (0.31854677200317383, same, same, 1) | sRGB 0.6 becomes linear ≈0.31855; equal RGB, opaque, no textures; PASS |
| Khronos validator | 0 errors, 0 warnings, 0 infos, 0 hints | PASS |
| Three.js GLTFLoader | Real `parse(ArrayBuffer)` loaded 9 mesh primitives / 2,700 triangles; colours and actual transformed vertex bounds checked | Same bounds error/tolerance; separate Node process without CadQuery; PASS |
| STEP export / re-import | 26309 bytes; one valid solid; 29324.557579478176 mm³; bounds preserved | Absolute analytic/round-trip volume error 1.81898940355e-11 mm³ ≤ 1e-5 mm³; bounds ≤ 1e-6 mm; PASS |

STEP used `cq.exporters.export(plate, path, exportType="STEP")` and `cq.importers.importStep(path)` in mm. STEP feasibility is proven for this synthetic solid. Product reconstruction labels/download naming remain the later M3/R14 slice.

## Reproduce from the lane worktree root

PowerShell (no global installs; existing base Python 3.12.10 is read only). The recorded base interpreter was `C:\Users\Jason\AppData\Local\Programs\Python\Python312\python.exe`. Replace `$basePython` only with an existing Python 3.12 interpreter.

```powershell
$laneRoot = (Get-Location).Path
$env:UV_CACHE_DIR = Join-Path $laneRoot 'testing/cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $laneRoot 'development/.runtime/python'
$env:TEMP = Join-Path $laneRoot 'testing/tmp/A13-cad'
$env:TMP = $env:TEMP
$env:UV_CONCURRENT_DOWNLOADS = '1'
$env:UV_CONCURRENT_INSTALLS = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
foreach ($relative in @('development/.runtime', 'testing/cache/uv', 'testing/cache/npm', 'testing/tmp/A13-cad', 'testing/runs/A13-cad')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $laneRoot $relative) | Out-Null
}
$basePython = (Get-Command python).Source
uv --no-config venv --no-project --python $basePython development/.runtime/c
uv --no-config pip install --link-mode copy --python development/.runtime/c/Scripts/python.exe cadquery==2.8.0 cadquery-ocp==7.9.3.1.1
uv --no-config pip freeze --python development/.runtime/c/Scripts/python.exe
& ./development/.runtime/c/Scripts/python.exe testing/qualification/A13-cad/qualify.py
# Use the same local, empty npm config files as qualification.
New-Item -ItemType File -Force testing/tmp/A13-cad/npm-user.config | Out-Null
New-Item -ItemType File -Force testing/tmp/A13-cad/npm-global.config | Out-Null
npm.cmd install --prefix development/.runtime/a13-gltf --no-audit --no-fund --ignore-scripts --cache testing/cache/npm --userconfig testing/tmp/A13-cad/npm-user.config --globalconfig testing/tmp/A13-cad/npm-global.config --registry https://registry.npmjs.org three@0.187.0 gltf-validator@2.0.0-dev.3.10
node testing/qualification/A13-cad/validate-glb.mjs
```

The actual initial npm install resolved the same exact versions from unpinned `three gltf-validator`; its exact argv is preserved in JSON. The commands above pin those resolved versions. `qualify.py` also directs matplotlib/Numba/XDG caches beneath `testing/cache/`.

Windows observations: long environment paths failed OCP DLL loading with “The filename or extension is too long”; shortening only the environment name was insufficient. The script uses `GetShortPathNameW` to re-execute the **same interpreter through an existing NTFS 8.3 alias**. It verifies file identity and creates no drive mapping, external junction, or registry/config change. If that alias is unavailable on another long-path Windows checkout, this workaround is unavailable; do not infer success. An initial uv cache-rename access denial was resolved by serial download/install and copy mode. The failed unscaled export, failed import traces, and raw install diagnostics remain in ignored `testing/runs/A13-cad/`; the failed attempts are recorded in JSON.

## Scope, limitations and handoff

Ordinary viewing of this saved GLB did not use CadQuery: the independent Node process loaded its embedded buffers and grey material without Python. Generation/rebuilding and this STEP round-trip use CadQuery. This is an observation for **A01's optional CAD extra**; packaging remains A01-owned. `development/pyproject.toml`, `development/uv.lock`, all product source and the future `backend/cad/build.py` are unchanged/absent in this lane snapshot.

Integrated app/browser/WebGL rendering is **unavailable in this B00 snapshot**: no viewer/server implementation is present. The genuine Node Three.js loader check demonstrates loadable geometry; no browser visual/interaction test or full ordinary-runtime launch is claimed. Other operating systems were not available. This qualification proves no source-derived reconstruction, uncertain-template handling, targeted rebuild, or M1/V2 release gate.

Raw evidence and generated binaries are ignored under `testing/runs/A13-cad/`. Durable measurements, complete package freeze, commands/exit codes, file hashes, resolved diagnostics and unavailable capabilities are in [qualification.json](qualification.json). Reproducible probes are [qualify.py](../../../qualification/A13-cad/qualify.py) and [validate-glb.mjs](../../../qualification/A13-cad/validate-glb.mjs). Only these two scripts and these two report files are committed; combined size is below 200 KB.

Proposed USER_TODO entries: **none**. No human decision was needed. ROOT can reconcile `cadquery==2.8.0` / `cadquery-ocp==7.9.3.1.1` with A01's extra and carry the explicit 0.001 export conversion and Windows alias observation into the later builder assignment.

Primary references: [CadQuery assembly glTF export](https://cadquery.readthedocs.io/en/latest/importexport.html#exporting-assemblies-to-gltf), [STEP import](https://cadquery.readthedocs.io/en/latest/importexport.html#importing-step), [glTF 2.0 units/container specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html), [Khronos validator](https://github.com/KhronosGroup/glTF-Validator), [Three.js GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html). Runtime measurements, including the unit conversion requirement, take precedence over assumptions about exporter defaults.
