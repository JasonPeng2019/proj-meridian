// B00 only: independent Khronos validation and Three.js loading, with no CadQuery.
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const output = path.resolve(root, process.argv[2] || 'testing/runs/A13-cad');
const modules = path.resolve(root, process.argv[3] || 'development/.runtime/a13-gltf/node_modules');
assert.ok(output.startsWith(path.join(root, 'testing/runs') + path.sep));
const require = createRequire(path.join(modules, 'qualification.cjs'));
const validator = require(path.join(modules, 'gltf-validator'));
const THREE = await import(pathToFileURL(path.join(modules, 'three/build/three.module.js')).href);
const { GLTFLoader } = await import(pathToFileURL(path.join(modules, 'three/examples/jsm/loaders/GLTFLoader.js')).href);
const bytes = await readFile(path.join(output, 'synthetic-plate.glb'));
const expectedBounds = [[-0.05, 0, -0.03], [0.05, 0.005, 0.03]];
const tolerance = 1e-7; // m, independently specified from invented geometry
const evidence = {
  outcome: 'FAIL', node: process.version,
  three: JSON.parse(await readFile(path.join(modules, 'three/package.json'), 'utf8')).version,
  gltf_validator: validator.version(),
  cadquery_imported: false,
  scope: 'Real GLTFLoader.parse in Node, no browser/WebGL/app integration claim',
};

try {
  const validation = await validator.validateBytes(new Uint8Array(bytes), {
    uri: 'synthetic-plate.glb', maxIssues: 1000,
    externalResourceFunction: async (uri) => { throw new Error(`Unexpected external resource: ${uri}`); },
  });
  await writeFile(path.join(output, 'khronos-validator.json'), JSON.stringify(validation, null, 2) + '\n');
  evidence.khronos = validation.issues;
  assert.equal(validation.issues.numErrors, 0, 'Khronos validator reported errors');
  const arrayBuffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(arrayBuffer, '', resolve, reject));
  gltf.scene.updateMatrixWorld(true);
  // precise=true computes bounds from loaded vertices, accounting for node transforms.
  const box = new THREE.Box3().setFromObject(gltf.scene, true);
  const bounds = [box.min.toArray(), box.max.toArray()];
  const error = Math.max(...bounds.flat().map((value, i) => Math.abs(value - expectedBounds.flat()[i])));
  assert.ok(Number.isFinite(error) && error <= tolerance, `Loaded bounds error ${error} m`);
  let meshCount = 0, triangles = 0;
  const colours = [];
  gltf.scene.traverse((object) => {
    if (!object.isMesh) return;
    meshCount++;
    const position = object.geometry.getAttribute('position');
    assert.ok(position && position.count > 0);
    triangles += (object.geometry.index?.count ?? position.count) / 3;
    for (const material of [object.material].flat()) {
      const colour = material.color.toArray();
      assert.ok(colour.every(Number.isFinite));
      assert.ok(colour[0] > 0 && colour[0] < 1 && Math.max(...colour) - Math.min(...colour) < 1e-7);
      assert.equal(material.opacity, 1);
      colours.push(colour);
    }
  });
  assert.ok(meshCount > 0 && triangles > 0);
  Object.assign(evidence, {
    outcome: 'PASS', loader: 'three/examples/jsm/loaders/GLTFLoader.js: GLTFLoader.parse(ArrayBuffer)',
    world_bounds_m: bounds, expected_world_bounds_m: expectedBounds,
    max_bounds_error_m: error, bounds_tolerance_m: tolerance,
    loaded_meshes: meshCount, loaded_triangles: triangles, loaded_linear_colours: colours,
  });
} catch (error) {
  evidence.diagnostics = error.stack || String(error);
  process.exitCode = 1;
}
evidence.completed_at = new Date().toISOString();
await writeFile(path.join(output, 'loader-validation.json'), JSON.stringify(evidence, null, 2) + '\n');
console.log(JSON.stringify(evidence, null, 2));
