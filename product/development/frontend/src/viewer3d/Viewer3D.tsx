import { useEffect, useId, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  customer_review_status, model_api_path, RECONSTRUCTION_LABEL,
  type CustomerReviewStatus, type ModelExample, type ModelRequest,
  type PartRecord, type Viewer3DProps,
} from "../contracts";

type Example = ModelRequest["example"];
const EXAMPLES: readonly Example[] = ["A", "B", "C", "D"];
const MAX_GLB_BYTES = 128 * 1024 * 1024;
type ViewState = { key: string; state: "loading" | "ready" | "error"; message?: string };
type Actions = { fit: () => void; zoom: (factor: number) => void; section: (percent: number) => void };

function drawingId(part: PartRecord): string | null {
  const id = part.drawing?.id ?? part.id.split("/")[0];
  return /^D-\d{3}$/.test(id) ? id : null;
}

// Metadata identifies saved assets; a tab or a successful fetch is never review evidence.
export function availableModelExamples(part: PartRecord): ModelExample[] {
  if (!drawingId(part) || !["available", "stale"].includes(part.model.state)) return [];
  return EXAMPLES.flatMap(id => {
    const item = part.model.examples?.find(candidate => candidate.id === id && candidate.glb.trim());
    return item ? [item] : [];
  });
}

function currentSourceHashes(part: PartRecord): Record<string, string> {
  const hashes: Record<string, string> = {};
  const conflicts = new Set<string>();
  const add = (name: string | undefined | null, hash: string) => {
    if (!name || !hash) return;
    if (hashes[name] && hashes[name] !== hash) conflicts.add(name);
    hashes[name] = hash;
  };
  const sources: Array<[string, string]> = [];
  if (part.drawing) {
    sources.push([part.drawing.id, part.drawing.source_sha256]);
    for (const field of Object.values(part.drawing.fields)) sources.push([field.name, part.drawing.source_sha256]);
  }
  for (const row of part.bom) {
    sources.push([row.name, row.source_sha256]);
    for (const field of Object.values(row.fields)) sources.push([field.name, row.source_sha256]);
  }
  for (const [name, hash] of sources) {
    add(name, hash);
    // Only map declared provenance input names to independently present source hashes.
    add(part.model.provenance?.source.source_ids[name], hash);
  }
  for (const name of conflicts) delete hashes[name];
  return hashes;
}

function modelReviewStatus(part: PartRecord, usable: boolean): CustomerReviewStatus {
  const model = part.model;
  // A saved stale asset can be inspected, but has no current review claim.
  const current = model.state === "available" &&
    !(model.built_template_sha256 && model.current_template_sha256 &&
      model.built_template_sha256 !== model.current_template_sha256);
  const provenance = model.provenance;
  const verified = provenance?.mode === "determine_verify" &&
    ["first_pass_verified", "retry_verified"].includes(provenance.outcome) &&
    Object.keys(provenance.source.inputs).length > 0 && provenance.field_names.length > 0 &&
    provenance.field_names.every(name => {
      const field = provenance.field_results?.[name];
      return field && ["first_pass_verified", "retry_verified"].includes(field.status) &&
        field.accepted?.schema_valid === true && field.accepted.evidence_valid === true;
    });
  return customer_review_status({ usable: usable && current,
    current_source_hashes: currentSourceHashes(part), review: model.review,
    provenance: verified ? provenance : null });
}

export function defaultModelExample(part: PartRecord): Example {
  const available = availableModelExamples(part);
  const selected = part.model.selected_example;
  // selected_example is a human choice, not an AI choice or an asset-order hint.
  if (selected && available.some(item => item.id === selected) &&
    modelReviewStatus(part, true) === "Human reviewed") return selected;
  return available[0]?.id ?? "A";
}

function disposeTrees(roots: THREE.Object3D[], replaced: THREE.Material[] = []) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>(replaced);
  const textures = new Set<THREE.Texture>();
  const skeletons = new Set<THREE.Skeleton>();
  for (const root of roots) root.traverse(object => {
    if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Points) {
      geometries.add(object.geometry);
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material);
      if (object instanceof THREE.SkinnedMesh) skeletons.add(object.skeleton);
    }
  });
  for (const material of materials) {
    for (const value of Object.values(material)) {
      if (value instanceof THREE.Texture) textures.add(value);
    }
    material.dispose();
  }
  const images = new Set<ImageBitmap>();
  for (const texture of textures) {
    if (typeof ImageBitmap !== "undefined" && texture.image instanceof ImageBitmap) images.add(texture.image);
    texture.dispose();
  }
  for (const image of images) image.close();
  for (const skeleton of skeletons) skeleton.dispose();
  for (const geometry of geometries) geometry.dispose();
  for (const root of roots) root.clear();
}

// This viewport accepts self-contained GLB 2 only. It never follows a model's
// relative/network resource links or mistakes an HTML SPA fallback for a model.
function validateGlb(buffer: ArrayBuffer) {
  if (buffer.byteLength < 20 || buffer.byteLength > MAX_GLB_BYTES) throw new Error("Invalid GLB size");
  const header = new DataView(buffer);
  const jsonLength = header.getUint32(12, true);
  if (header.getUint32(0, true) !== 0x46546c67 || header.getUint32(4, true) !== 2 ||
    header.getUint32(8, true) !== buffer.byteLength || header.getUint32(16, true) !== 0x4e4f534a ||
    jsonLength % 4 !== 0 || jsonLength > buffer.byteLength - 20) throw new Error("Invalid GLB header");
  const json: unknown = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jsonLength)));
  const checkUris = (value: unknown) => {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (key === "uri" && typeof child === "string" && !child.startsWith("data:")) {
        throw new Error("External GLB resource");
      }
      checkUris(child);
    }
  };
  checkUris(json);
}

export function Viewer3D({ part, example, on_select_example, on_open_source, debug, show_section = true }: Viewer3DProps) {
  const available = availableModelExamples(part);
  const initial = example ?? defaultModelExample(part);
  const scope = `${part.id}:${example ?? ""}:${defaultModelExample(part)}`;
  const [choice, setChoice] = useState({ scope, id: initial });
  const selected = choice.scope === scope ? choice.id : initial;
  const asset = available.find(item => item.id === selected);
  const id = drawingId(part);
  const url = asset && id ? model_api_path(id, selected) : null;
  const [attempt, setAttempt] = useState(0);
  // Metadata refreshes of the same URL also release and reload the saved model.
  const assetKey = JSON.stringify([part.id, url, part.model.built_at, part.model.built_template_sha256, asset]);
  const key = `${assetKey}:${attempt}`;
  const [view, setView] = useState<ViewState>({ key, state: "loading" });
  const state = view.key === key ? view : { key, state: "loading" as const };
  const host = useRef<HTMLDivElement>(null);
  const actions = useRef<Actions | null>(null);
  const [section, setSection] = useState(0);
  const sectionId = useId();
  const sectionAvailable = show_section && part.model.section_view_available === true;

  useEffect(() => {
    const container = host.current;
    actions.current = null;
    setSection(0);
    if (!url || !container) return;
    setView({ key, state: "loading" });
    const abort = new AbortController();
    let renderer: THREE.WebGLRenderer | undefined;
    let controls: OrbitControls | undefined;
    let observer: ResizeObserver | undefined;
    let roots: THREE.Object3D[] = [];
    let replaced: THREE.Material[] = [];
    let frame = 0;
    let stopped = false;
    let ready = false;
    let timedOut = false;
    const objectUrls = new Set<string>();
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, .01, 1000);
    const bounds = new THREE.Box3();
    const center = new THREE.Vector3();
    let radius = 1;
    const plane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
    const stop = () => {
      if (stopped) return;
      stopped = true;
      abort.abort();
      window.clearTimeout(timeout);
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      renderer?.domElement.removeEventListener("webglcontextlost", contextLost);
      controls?.removeEventListener("change", draw);
      controls?.dispose();
      actions.current = null;
      disposeTrees(roots, replaced);
      roots = []; replaced = [];
      scene.clear();
      for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl);
      objectUrls.clear();
      if (renderer) {
        renderer.renderLists.dispose();
        renderer.dispose();
        renderer.forceContextLoss();
        renderer.domElement.remove();
      }
    };
    const fail = (message: string) => {
      if (stopped) return;
      setView({ key, state: "error", message });
      stop();
    };
    const draw = () => {
      if (stopped || frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!stopped && renderer && ready) {
          try { renderer.render(scene, camera); }
          catch { fail("3D view: Unavailable. Try loading it again."); }
        }
      });
    };
    const fit = () => {
      if (!ready || !controls) return;
      // A bounding sphere enclosing the actual transformed bounds fits in both
      // the horizontal and vertical field of view, including portrait panels.
      const vertical = THREE.MathUtils.degToRad(camera.fov / 2);
      const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
      const distance = radius / Math.sin(Math.min(vertical, horizontal)) * 1.12;
      camera.position.copy(center).addScaledVector(new THREE.Vector3(1, .75, 1).normalize(), distance);
      camera.near = radius / 10000;
      camera.far = distance * 10 + radius * 20;
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      controls.minDistance = radius * .05;
      controls.maxDistance = Math.max(distance * 8, radius * 20);
      controls.update();
      draw();
    };
    const resize = () => {
      if (stopped || !renderer) return;
      const width = Math.max(1, container.clientWidth);
      const height = Math.max(1, container.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      // Keep a visible reconstruction inside a resized shared/mobile panel.
      fit();
      draw();
    };
    const contextLost = (event: Event) => {
      event.preventDefault();
      fail("3D view: Unavailable. Graphics connection lost. Try loading it again.");
    };
    const timeout = window.setTimeout(() => {
      timedOut = true;
      fail("3D view: Unavailable. Loading timed out. Try again.");
    }, 30000);

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.localClippingEnabled = true;
      renderer.domElement.setAttribute("aria-label", `Reconstruction example ${selected}. Drag to orbit; scroll or pinch to zoom.`);
      renderer.domElement.setAttribute("role", "img");
      renderer.domElement.addEventListener("webglcontextlost", contextLost);
      container.appendChild(renderer.domElement);
      scene.background = new THREE.Color(0xf0f2f4);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x667078, 2.4));
      const light = new THREE.DirectionalLight(0xffffff, 2.5);
      light.position.set(1, 2, 3);
      scene.add(light);
      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = false; // On-demand rendering; no idle animation loop.
      controls.addEventListener("change", draw);
      actions.current = {
        fit,
        zoom: factor => {
          if (!controls || !ready) return;
          const offset = camera.position.clone().sub(controls.target);
          offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, controls.minDistance, controls.maxDistance));
          camera.position.copy(controls.target).add(offset);
          controls.update(); draw();
        },
        section: percent => {
          if (!renderer || !ready) return;
          plane.constant = THREE.MathUtils.lerp(bounds.max.x, bounds.min.x, percent / 100);
          renderer.clippingPlanes = percent > 0 ? [plane] : [];
          draw();
        },
      };
      observer = new ResizeObserver(resize);
      observer.observe(container);
      window.addEventListener("resize", resize);
      resize();
      const manager = new THREE.LoadingManager();
      manager.setURLModifier(resource => {
        if (stopped) {
          if (resource.startsWith("blob:")) URL.revokeObjectURL(resource);
          throw new Error("GLB load cancelled");
        }
        if (resource.startsWith("blob:")) { objectUrls.add(resource); return resource; }
        if (resource.startsWith("data:")) return resource;
        throw new Error("External GLB resource");
      });
      const loader = new GLTFLoader(manager);
      // CAD presentation uses geometry only. Suppress texture/image requests
      // before parsing, including partially failed or cancelled GLBs.
      loader.register(parser => ({ name: "meridian-neutral-materials", beforeRoot: async () => {
        if (parser.json.materials) parser.json.materials = parser.json.materials.map(() => ({
          pbrMetallicRoughness: { baseColorFactor: [.57, .59, .61, 1], metallicFactor: 0, roughnessFactor: .8 },
          doubleSided: true,
        }));
      } }));
      void (async () => {
        let bytes: ArrayBuffer | null = null;
        try {
          const response = await fetch(url, { signal: abort.signal, credentials: "same-origin", redirect: "error", cache: "no-store" });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          if (Number(response.headers.get("content-length")) > MAX_GLB_BYTES) throw new Error("GLB too large");
          bytes = await response.arrayBuffer();
          if (stopped) return;
          validateGlb(bytes);
          const gltf = await loader.parseAsync(bytes, "");
          const loaded = [...new Set([gltf.scene, ...gltf.scenes])].filter(root => root instanceof THREE.Object3D);
          if (stopped) { disposeTrees(loaded); return; }
          roots = loaded;
          if (!(gltf.scene instanceof THREE.Object3D)) throw new Error("GLB has no active scene");
          let meshes = 0;
          const neutral = new THREE.MeshStandardMaterial({ color: 0x92979c, roughness: .8, metalness: 0, side: THREE.DoubleSide });
          replaced.push(neutral);
          gltf.scene.traverse(object => {
            if (!(object instanceof THREE.Mesh)) return;
            if ((object.geometry.getAttribute("position")?.count ?? 0) > 0) meshes++;
            replaced.push(...(Array.isArray(object.material) ? object.material : [object.material]));
            object.material = neutral;
          });
          gltf.scene.updateMatrixWorld(true);
          bounds.setFromObject(gltf.scene, true);
          const size = bounds.getSize(new THREE.Vector3());
          radius = size.length() / 2;
          if (!meshes || bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray(), radius].every(Number.isFinite) || radius <= 0) {
            throw new Error("GLB has no usable mesh bounds");
          }
          bounds.getCenter(center);
          scene.add(gltf.scene);
          ready = true;
          window.clearTimeout(timeout);
          for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl);
          objectUrls.clear();
          fit();
          setView({ key, state: "ready" });
        } catch {
          if (!stopped && !timedOut) fail("3D view: Unavailable. Could not load this reconstruction. Try again.");
        } finally {
          bytes = null;
          for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl);
          objectUrls.clear();
        }
      })();
    } catch {
      fail("3D view: Unavailable. This device could not start the 3D view. Try again.");
    }
    return stop;
  }, [key, url, selected]);

  useEffect(() => {
    if (!sectionAvailable) { setSection(0); actions.current?.section(0); }
  }, [sectionAvailable]);

  const ready = Boolean(asset && state.state === "ready");
  const review = modelReviewStatus(part, ready);
  const visibleReview = review === "Human reviewed" && part.model.selected_example && part.model.selected_example !== selected
    ? "Unavailable" : review;
  const size = part.model.overall_size_mm;
  const hasSize = size?.length === 3 && size.every(value => Number.isFinite(value) && value > 0);
  return <section className="meridian-viewer" aria-label="3D reconstruction">
    <ViewerStyles />
    <p className="mv-label">{RECONSTRUCTION_LABEL}</p>
    <div className="mv-toolbar">
      <div className="mv-examples" role="group" aria-label="Printed examples">{EXAMPLES.map(option => {
        const exists = available.some(item => item.id === option);
        return <button key={option} type="button" aria-pressed={selected === option} disabled={!exists}
          aria-label={`Example ${option}${exists ? "" : ": Unavailable"}`} onClick={() => {
            setChoice({ scope, id: option }); on_select_example?.(option);
          }}>{option}</button>;
      })}</div>
      <div className="mv-tools" role="group" aria-label="3D view controls">
        <button type="button" aria-label="Zoom out" disabled={!ready} onClick={() => actions.current?.zoom(1.25)}>−</button>
        <button type="button" aria-label="Zoom in" disabled={!ready} onClick={() => actions.current?.zoom(.8)}>+</button>
        <button type="button" disabled={!ready} onClick={() => actions.current?.fit()}>Fit</button>
      </div>
      {part.drawing && <button type="button" onClick={() => on_open_source({ kind: "drawing", name: part.drawing!.id,
        drawing_id: part.drawing!.id, part_id: part.id, page: 1 })}>Open source drawing</button>}
    </div>
    <p className="mv-caption" aria-live="polite">Example {selected} · <span aria-label="Model review status">{visibleReview}</span></p>
    {url && <div className="mv-viewport" ref={host} hidden={state.state === "error"} />}
    {!url ? <p role="status">3D view: Unavailable</p> : state.state === "loading" ? <p role="status">Loading reconstruction…</p>
      : state.state === "error" ? <div role="alert"><p>{state.message}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>
      : <p className="mv-caption">Drag to orbit · Scroll or pinch to zoom</p>}
    {ready && hasSize && <p className="mv-caption">Overall size: {size.map(value => value.toLocaleString(undefined, { maximumFractionDigits: 2 })).join(" × ")} mm</p>}
    {ready && sectionAvailable && <div className="mv-section"><label htmlFor={sectionId}>Hollow section</label>
      <input id={sectionId} type="range" min="0" max="100" value={section} onChange={event => {
        const value = Number(event.target.value); setSection(value); actions.current?.section(value);
      }} /><output htmlFor={sectionId}>{section === 0 ? "Off" : `${section}%`}</output></div>}
    {asset?.step && id && <a className="mv-download" href={model_api_path(id, selected, "step")} download={`${id}_${selected}_reconstruction.step`}>Download STEP reconstruction</a>}
    {debug?.enabled === true && <details className="mv-debug"><summary>Debug · Reconstruction</summary>
      <p>Model state: {part.model.state}</p>
      <p>Saved example: {selected}; renderer: {asset ? state.state : "unavailable"}</p>
      {(part.synthetic || part.fixture) && <p>Declared SYNTHETIC fixture; not source evidence.</p>}
      {part.model.stale_reason && <p>Saved geometry is stale. Open part Debug for model details.</p>}
      {part.model.omitted_details?.length ? <p>Omitted details: {part.model.omitted_details.length}</p> : null}
      {part.weight_check && <p>Weight check: {part.weight_check.state}</p>}
      {part.weight_check?.examples?.map(item => <p key={item.example}>Example {item.example}: {item.matches ? "Matches drawing weight" : "Differs from drawing weight"}</p>)}
    </details>}
  </section>;
}

function ViewerStyles() {
  return <style>{`
    .meridian-viewer { min-width:0; color:#172b3a; font:14px/1.6 system-ui,sans-serif; }
    .meridian-viewer .mv-label { margin:0 0 14px; color:#526777; }
    .meridian-viewer .mv-toolbar,.meridian-viewer .mv-tools,.meridian-viewer .mv-examples { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
    .meridian-viewer .mv-toolbar { justify-content:space-between; }
    .meridian-viewer button { border:1px solid #b9c7d1; border-radius:5px; background:#fff; color:inherit; padding:6px 12px; cursor:pointer; font:inherit; }
    .meridian-viewer button:disabled { opacity:.5; cursor:default; }
    .meridian-viewer button[aria-pressed="true"] { background:#e5f0f3; border-color:#b6d1da; font-weight:600; }
    .meridian-viewer :is(button,a,input):focus-visible { outline:3px solid #1675be; outline-offset:3px; }
    .meridian-viewer .mv-viewport { width:100%; height:clamp(240px,48vh,560px); overflow:hidden; border:1px solid #cbd5df; border-radius:7px; background:#f0f2f4; }
    .meridian-viewer canvas { display:block; width:100%; height:100%; touch-action:none; }
    .meridian-viewer .mv-caption { margin:10px 0; color:#526777; font-size:12px; }
    .meridian-viewer .mv-section { display:flex; flex-wrap:wrap; align-items:center; gap:12px; margin:12px 0; }
    .meridian-viewer .mv-section input { flex:1; min-width:100px; }
    .meridian-viewer .mv-section output { min-width:40px; }
    .meridian-viewer .mv-download { display:inline-block; margin-top:10px; color:#124b5d; }
    .meridian-viewer .mv-debug { margin-top:20px; border:1px solid #cbd5df; padding:12px; border-radius:7px; }
    .meridian-viewer .mv-debug summary { cursor:pointer; font-weight:600; }
    @media(max-width:550px) { .meridian-viewer .mv-viewport { height:300px; } .meridian-viewer .mv-toolbar { justify-content:flex-start; } }
  `}</style>;
}

export default Viewer3D;
