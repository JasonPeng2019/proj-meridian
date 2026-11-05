// SYNTHETIC controlled viewer harness. No real drawing, model or human review credit.
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { PartPage } from "../../../development/frontend/src/part/PartPage";
import type { ApiClient, ModelRequest, PartDetailResponse } from "../../../development/frontend/src/contracts";

const probe = (window as any).viewerProbe = {
  synthetic: true, frames: [] as any[], live: new Set<THREE.WebGLRenderer>(),
  lastCanvas: null as HTMLCanvasElement | null,
  renderersDisposed: 0, geometriesDisposed: 0, materialsDisposed: 0, sourceOpened: 0,
};
function capture(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera) {
  if (!probe.live.has(renderer)) return;
  const meshes: THREE.Mesh[] = [];
  scene.traverse(object => { if (object instanceof THREE.Mesh) meshes.push(object); });
  if (!meshes.length) return;
  const bounds = new THREE.Box3().setFromObject(meshes[0], true);
  const gl = renderer.getContext();
  const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
  gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  let changed = 0, fingerprint = 2166136261;
  for (let i = 0; i < pixels.length; i += 16) {
    if ([0, 1, 2].some(j => Math.abs(pixels[i + j] - pixels[j]) > 12)) changed++;
    fingerprint = Math.imul(fingerprint ^ pixels[i], 16777619) >>> 0;
  }
  const projected = [];
  for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) {
    for (const z of [bounds.min.z, bounds.max.z]) projected.push(new THREE.Vector3(x, y, z).project(camera).toArray());
  }
  probe.frames.push({ position: camera.position.toArray(), bounds: [bounds.min.toArray(), bounds.max.toArray()],
    projected, changed, fingerprint, webgl: gl.getParameter(gl.VERSION), aspect: (camera as THREE.PerspectiveCamera).aspect,
    colors: meshes.flatMap(mesh => (Array.isArray(mesh.material) ? mesh.material : [mesh.material])
      .map(material => (material as THREE.MeshStandardMaterial).color?.getHex())),
    clipping: renderer.clippingPlanes.length });
  probe.lastCanvas = renderer.domElement;
  if (probe.frames.length > 100) probe.frames.shift();
}
// WebGLRenderer creates render/dispose as instance methods. Observe actual mesh
// callbacks, then read pixels in a microtask after rendering, before compositing.
const seen = new WeakSet<THREE.WebGLRenderer>(), queued = new WeakSet<THREE.WebGLRenderer>();
const beforeRender = THREE.Mesh.prototype.onBeforeRender;
THREE.Mesh.prototype.onBeforeRender = function(renderer, scene, camera, geometry, material, group) {
  beforeRender.call(this, renderer, scene, camera, geometry, material, group);
  if (!seen.has(renderer)) {
    seen.add(renderer); probe.live.add(renderer);
    const dispose = renderer.dispose.bind(renderer);
    renderer.dispose = () => {
      probe.renderersDisposed++; probe.live.delete(renderer);
      if (probe.lastCanvas === renderer.domElement) probe.lastCanvas = null;
      dispose();
    };
  }
  if (queued.has(renderer)) return;
  queued.add(renderer);
  queueMicrotask(() => { queued.delete(renderer); capture(renderer, scene, camera); });
};
const originalGeometryDispose = THREE.BufferGeometry.prototype.dispose;
THREE.BufferGeometry.prototype.dispose = function() { probe.geometriesDisposed++; originalGeometryDispose.call(this); };
const originalMaterialDispose = THREE.Material.prototype.dispose;
THREE.Material.prototype.dispose = function() { probe.materialsDisposed++; originalMaterialDispose.call(this); };

const hash = "a".repeat(64);
const aiProvenance = {
  pipeline_version: "determine-verify/v1" as const, job: "SYNTHETIC template", job_id: "SYNTHETIC",
  mode: "determine_verify" as const, outcome: "first_pass_verified" as const, rounds: [],
  source: { inputs: { "D-901": hash }, source_ids: { "D-901": "D-901" } },
  field_names: ["SYNTHETIC geometry"], determination_prompt_sha256: hash, verification_prompt_sha256: hash,
  output_contract_sha256: hash, field_results: { "SYNTHETIC geometry": {
    status: "first_pass_verified" as const, candidate_sha256: hash, accepted: {
      state: "known" as const, value: "SYNTHETIC geometry", confidence: "sure" as const,
      source_ids: ["D-901"], reason: "SYNTHETIC controlled test evidence", schema_valid: true, evidence_valid: true,
    },
  } },
};
const base: PartDetailResponse = {
  fixture: true, synthetic: true, fixture_note: "SYNTHETIC invented tetrahedra; no real-source or human review credit",
  id: "D-901/part", display_name: "SYNTHETIC reconstruction fixture", section: null,
  has_drawing: true, has_3d: true, examples: ["A", "B"],
  drawing: { id: "D-901", pages: 1, image: "", source_path: "SYNTHETIC", source_sha256: hash,
    source_quality: "clean", degraded: false, page_geometry: [], fields: {} },
  bom: [], link: null, template: null, facts: {},
  model: { state: "available", examples: [{ id: "A", glb: "SYNTHETIC_A.glb" }, { id: "B", glb: "SYNTHETIC_B.glb", step: "SYNTHETIC_B.step" }],
    selected_example: "B", overall_size_mm: [6000, 9000, 12000], section_view_available: true,
    review: { status: "human_confirmed", by: "SYNTHETIC reviewer", at: "2026-01-01T00:00:00Z", based_on: { "D-901": hash } } },
  weight_check: { state: "FAILED", message: "SYNTHETIC engineering weight warning" },
};
const noCall = () => { throw new Error("Unexpected synthetic harness API call"); };
const api = new Proxy({}, { get: () => noCall }) as ApiClient;

function Harness() {
  const [part, setPart] = useState(base);
  const [example, setExample] = useState<ModelRequest["example"] | undefined>();
  const [debug, setDebug] = useState(false);
  (probe as any).input = { model: part.model, drawing_hash: part.drawing?.source_sha256 };
  const choose = (next: PartDetailResponse, requested?: ModelRequest["example"]) => { setPart(next); setExample(requested); };
  return <main><h1>SYNTHETIC WebGL viewer test — no real-source credit</h1>
    <nav aria-label="Synthetic scenarios">
      <button onClick={() => choose(base)}>SYNTHETIC reviewed B</button>
      <button onClick={() => choose({ ...base, model: { ...base.model, review: { status: "not_reviewed" } } })}>SYNTHETIC unreviewed</button>
      <button onClick={() => choose({ ...base, model: { ...base.model, review: { status: "not_reviewed" }, provenance: aiProvenance } })}>SYNTHETIC AI reviewed</button>
      <button onClick={() => choose({ ...base, model: { ...base.model, review: { status: "not_reviewed" },
        provenance: { ...aiProvenance, mode: "single_model_unverified", outcome: "unverified_fallback" } } })}>SYNTHETIC fallback</button>
      <button onClick={() => choose({ ...base, model: { ...base.model, state: "stale", stale_reason: "SYNTHETIC source changed" } })}>SYNTHETIC stale</button>
      <button onClick={() => choose({ ...base, drawing: { ...base.drawing!, source_sha256: "b".repeat(64) } })}>SYNTHETIC changed evidence</button>
      <button onClick={() => choose({ ...base, has_3d: false, model: { state: "missing", examples: [] } })}>SYNTHETIC missing</button>
      <button onClick={() => choose({ ...base, model: { state: "available", examples: [{ id: "C", glb: "SYNTHETIC_BAD.glb" }] } }, "C")}>SYNTHETIC bad GLB</button>
      <button onClick={() => choose({ ...base, model: { state: "available", examples: [{ id: "D", glb: "SYNTHETIC_NETWORK.glb" }] } }, "D")}>SYNTHETIC network</button>
      <button onClick={() => choose({ ...base, id: "D-902/part", drawing: { ...base.drawing!, id: "D-902" },
        model: { state: "available", examples: [{ id: "A", glb: "SYNTHETIC_DELAYED.glb" }] } })}>SYNTHETIC delayed</button>
      <button onClick={() => setDebug(value => !value)}>SYNTHETIC toggle Debug</button>
    </nav>
    <PartPage api={api} part_id={part.id} record={part} example={example} initial_tab="model" embedded
      on_open_part={noCall} on_open_source={() => probe.sourceOpened++}
      debug={debug ? { enabled: true, on_open_review: noCall } : undefined} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
