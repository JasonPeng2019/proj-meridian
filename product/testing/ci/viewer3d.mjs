// Remote-only product component test. GLBs and review metadata below are SYNTHETIC.
// This tests actual Three/WebGL/OrbitControls, not source reconstruction fidelity.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

assert.equal(process.env.GITHUB_ACTIONS, "true", "Run only in queued remote Actions");
assert.equal(process.env.GITHUB_REF, "refs/heads/harness-v2", "Use this project's publication branch");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const frontend = path.join(root, "development/frontend");
const requireFrontend = createRequire(path.join(frontend, "package.json"));
const requireBrowser = createRequire(path.join(root, "development/.runtime/ci-browser/package.json"));
const { chromium } = requireBrowser("playwright");
const { createServer } = await import(pathToFileURL(requireFrontend.resolve("vite")).href);
const { default: react } = await import(pathToFileURL(requireFrontend.resolve("@vitejs/plugin-react")).href);
const output = path.join(root, "testing/runs/C04-viewer");
await mkdir(output, { recursive: true });

// Deliberately invented asymmetric tetrahedron, in glTF units, away from origin.
// Four independent triangles need no CAD exporter or claimed real drawing.
function syntheticGlb(min, max) {
  const [x, y, z] = min, [X, Y, Z] = max;
  const vertices = [[x,y,z], [X,y,z], [x,Y,z], [x,y,Z]];
  const triangles = [[0,2,1], [0,1,3], [0,3,2], [1,2,3]];
  const positions = new Float32Array(triangles.flatMap(face => face.flatMap(index => vertices[index])));
  const binary = Buffer.from(positions.buffer);
  const json = { asset: { version: "2.0", generator: "SYNTHETIC controlled viewer fixture; no real-source credit" },
    buffers: [{ byteLength: binary.length }], bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: binary.length }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 12, type: "VEC3", min, max }],
    materials: [{ pbrMetallicRoughness: { baseColorFactor: [1,0,0,1] } }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, material: 0 }] }],
    nodes: [{ mesh: 0 }], scenes: [{ nodes: [0] }], scene: 0 };
  const encoded = Buffer.from(JSON.stringify(json));
  const jsonChunk = Buffer.alloc(Math.ceil(encoded.length / 4) * 4, 0x20);
  encoded.copy(jsonChunk);
  const header = Buffer.alloc(20), binHeader = Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4);
  header.writeUInt32LE(20 + jsonChunk.length + 8 + binary.length, 8);
  header.writeUInt32LE(jsonChunk.length, 12); header.writeUInt32LE(0x4e4f534a, 16);
  binHeader.writeUInt32LE(binary.length, 0); binHeader.writeUInt32LE(0x004e4942, 4);
  return Buffer.concat([header, jsonChunk, binHeader, binary]);
}
const boundsA = [[10,20,30], [14,22,33]], boundsB = [[-60,-8,5], [-54,1,17]];
const glbs = { A: syntheticGlb(...boundsA), B: syntheticGlb(...boundsB) };
const requests = [], errors = [], checks = [];
const report = { outcome: "FAIL", synthetic: true, real_source_credit: false,
  scope: "Real Viewer3D/PartPage, Three GLBLoader and WebGL with controlled SYNTHETIC tetrahedra and review state",
  commit: process.env.GITHUB_SHA, run_id: process.env.GITHUB_RUN_ID,
  fixture_sha256: Object.fromEntries(Object.entries(glbs).map(([id, data]) => [id, createHash("sha256").update(data).digest("hex")])) };
const server = await createServer({ configFile: false, root: frontend, plugins: [react()],
  cacheDir: path.join(root, "testing/cache/C04-viewer-vite"),
  resolve: { dedupe: ["react", "react-dom", "three"] },
  server: { host: "127.0.0.1", port: 0, fs: { allow: [root] } } });
server.middlewares.use(async (request, response, next) => {
  const url = new URL(request.url, "http://localhost");
  if (url.pathname === "/__viewer3d__") {
    const harness = path.join(root, "testing/fixtures/viewer3d/harness.tsx");
    const html = await server.transformIndexHtml(url.pathname,
      `<!doctype html><html><head><title>SYNTHETIC viewer test</title></head><body><div id="root"></div><script type="module" src="/@fs${harness}"></script></body></html>`);
    response.setHeader("Content-Type", "text/html"); response.end(html); return;
  }
  const match = /^\/api\/models\/(D-90[12])_([A-D])\.glb$/.exec(url.pathname);
  if (!match) { next(); return; }
  const [, id, example] = match;
  requests.push(url.pathname);
  if (example === "D") { response.statusCode = 503; response.end("SYNTHETIC network failure"); return; }
  response.setHeader("Content-Type", "model/gltf-binary");
  response.setHeader("X-Meridian-Fixture", "SYNTHETIC");
  const data = example === "C" ? Buffer.from("SYNTHETIC malformed GLB") : glbs[example];
  const send = () => { if (!response.destroyed) { response.setHeader("Content-Length", data.length); response.end(data); } };
  if (id === "D-902") setTimeout(send, 800).unref(); else send();
});

let browser, page;
const checked = name => checks.push({ name, outcome: "PASS" });
try {
  await server.listen();
  browser = await chromium.launch({ headless: true, args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
    "--disable-dev-shm-usage", "--renderer-process-limit=1", "--num-raster-threads=1"] });
  page = await browser.newPage({ viewport: { width: 980, height: 900 }, serviceWorkers: "block" });
  page.setDefaultTimeout(15000);
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    // Observe real disposal without adding product test APIs.
    const liveUrls = new Set(), listeners = new Map();
    const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
    URL.createObjectURL = function(value) { const url = create.call(this, value); liveUrls.add(url); return url; };
    URL.revokeObjectURL = function(url) { liveUrls.delete(url); return revoke.call(this, url); };
    const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
    const key = (type, options) => `${type}:${typeof options === "boolean" ? options : Boolean(options?.capture)}`;
    EventTarget.prototype.addEventListener = function(type, listener, options) {
      if (this instanceof HTMLCanvasElement) {
        if (!listeners.has(this)) listeners.set(this, new Map());
        const target = listeners.get(this), name = key(type, options);
        if (!target.has(name)) target.set(name, new Set());
        target.get(name).add(listener);
      }
      return add.call(this, type, listener, options);
    };
    EventTarget.prototype.removeEventListener = function(type, listener, options) {
      listeners.get(this)?.get(key(type, options))?.delete(listener);
      return remove.call(this, type, listener, options);
    };
    window.viewerResources = () => ({ urls: liveUrls.size,
      canvasListeners: [...listeners.values()].flatMap(target => [...target.values()]).reduce((sum, set) => sum + set.size, 0) });
  });
  const address = server.httpServer.address();
  await page.goto(`http://127.0.0.1:${address.port}/__viewer3d__`);
  const model = page.getByRole("region", { name: "3D reconstruction", exact: true });
  const fit = () => model.getByRole("button", { name: "Fit", exact: true });
  const last = () => page.evaluate(() => window.viewerProbe.frames.at(-1));
  const ready = async expected => {
    await page.waitForFunction(() => document.querySelector('.meridian-viewer button') &&
      [...document.querySelectorAll('.meridian-viewer button')].some(button => button.textContent === "Fit" && !button.disabled));
    await page.waitForFunction(expected => window.viewerProbe.lastCanvas === document.querySelector('.meridian-viewer canvas') &&
      JSON.stringify(window.viewerProbe.frames.at(-1)?.bounds) === JSON.stringify(expected), expected);
    return last();
  };
  let initial = await ready(boundsB);
  assert.equal(await model.getByLabel("Model review status").innerText(), "Human reviewed");
  assert.match(await model.innerText(), /Reconstruction from 2D drawing. Not the original CAD model./);
  assert.ok(initial.changed > 100 && /WebGL/.test(initial.webgl));
  assert.ok(initial.colors.every(color => color === 0x92979c), "Loaded red fixture material must become neutral grey");
  assert.ok(initial.projected.every(point => point.every(value => value > -1 && value < 1)), "Fit must contain actual off-origin bounds");
  assert.equal(await model.getByRole("button", { name: "Example C: Unavailable", exact: true }).isDisabled(), true);
  assert.equal(await model.getByRole("link", { name: "Download STEP reconstruction" }).getAttribute("href"), "/api/models/D-901_B.step");
  assert.match(await model.innerText(), /Overall size:.*mm/);
  await model.getByRole("button", { name: "Open source drawing" }).click();
  assert.equal(await page.evaluate(() => window.viewerProbe.sourceOpened), 1);
  assert.doesNotMatch(await model.innerText(), /FAILED|stale|SYNTHETIC source changed|Debug|verifier/);
  await page.screenshot({ path: path.join(output, "synthetic-render.png") });
  checked("Actual GLB pixels, off-origin Fit, evidence-bound synthetic reviewer B, neutral material, unavailable choices and source/STEP actions");

  const canvas = model.locator("canvas"), box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width * .5, box.y + box.height * .5);
  await page.mouse.down(); await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 8 }); await page.mouse.up();
  await page.waitForFunction(position => JSON.stringify(window.viewerProbe.frames.at(-1)?.position) !== JSON.stringify(position), initial.position);
  assert.notEqual((await last()).fingerprint, initial.fingerprint, "Orbit must change actual rendered pixels");
  await fit().click();
  await page.waitForFunction(position => window.viewerProbe.frames.at(-1).position.every((value, i) => Math.abs(value - position[i]) < 1e-6), initial.position);
  await model.getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.waitForFunction(position => JSON.stringify(window.viewerProbe.frames.at(-1).position) !== JSON.stringify(position), initial.position);
  await fit().click();
  await page.waitForFunction(position => window.viewerProbe.frames.at(-1).position.every((value, i) => Math.abs(value - position[i]) < 1e-6), initial.position);
  checked("Real OrbitControls drag changes camera and pixels; zoom and Fit restore bounds-based camera");

  await model.getByRole("button", { name: "Example A", exact: true }).click();
  await ready(boundsA);
  assert.equal(await model.getByLabel("Model review status").innerText(), "Unavailable", "Selecting A does not inherit B's human choice");
  assert.ok(requests.includes("/api/models/D-901_A.glb") && requests.includes("/api/models/D-901_B.glb"));
  await model.getByLabel("Hollow section").click();
  await page.waitForFunction(() => window.viewerProbe.frames.at(-1).clipping === 1);
  await page.setViewportSize({ width: 375, height: 780 });
  await page.waitForFunction(() => window.viewerProbe.frames.at(-1).aspect < 1.5);
  assert.ok((await last()).projected.every(point => point.every(value => value > -1 && value < 1)));
  await page.getByRole("tab", { name: "Details", exact: true }).click();
  await page.waitForFunction(() => window.viewerProbe.live.size === 0);
  let resources = await page.evaluate(() => ({ ...window.viewerResources(), disposed: window.viewerProbe.renderersDisposed,
    geometries: window.viewerProbe.geometriesDisposed, materials: window.viewerProbe.materialsDisposed }));
  assert.ok(resources.disposed >= 2 && resources.geometries >= 2 && resources.materials >= 4, JSON.stringify(resources));
  assert.equal(resources.canvasListeners, 0); assert.equal(resources.urls, 0);
  checked("A/B switch loads corresponding binary and releases GPU resources; real clipping, responsive Fit and tab-unmount listener/renderer cleanup");

  await page.getByRole("tab", { name: "3D", exact: true }).click();
  await ready(boundsB);
  for (const scenario of ["SYNTHETIC changed evidence", "SYNTHETIC unreviewed", "SYNTHETIC fallback", "SYNTHETIC stale"]) {
    await page.getByRole("button", { name: scenario, exact: true }).click();
    await ready(boundsA);
    assert.equal(await model.getByLabel("Model review status").innerText(), "Unavailable");
    assert.doesNotMatch(await model.innerText(), /FAILED|SYNTHETIC source changed|Debug/);
  }
  await page.getByRole("button", { name: "SYNTHETIC toggle Debug", exact: true }).click();
  await model.getByText("Debug · Reconstruction", { exact: true }).click();
  assert.match(await model.innerText(), /Model state: stale/);
  assert.match(await model.innerText(), /Weight check: FAILED/);
  await page.getByRole("button", { name: "SYNTHETIC AI reviewed", exact: true }).click();
  await ready(boundsA);
  assert.equal(await model.getByLabel("Model review status").innerText(), "AI reviewed");
  checked("Changed/missing review evidence never inherits reviewer default or review label; stale model remains viewable; engineering details only in Debug");

  for (const scenario of ["SYNTHETIC bad GLB", "SYNTHETIC network"]) {
    await page.getByRole("button", { name: scenario, exact: true }).click();
    await model.getByRole("alert").waitFor();
    assert.equal(await fit().isDisabled(), true);
    assert.equal(await model.getByLabel("Model review status").innerText(), "Unavailable");
    assert.equal(await page.evaluate(() => window.viewerProbe.live.size), 0);
  }
  await page.getByRole("button", { name: "SYNTHETIC reviewed B", exact: true }).click();
  await ready(boundsB);
  assert.equal(await model.locator("canvas").evaluate(canvas => {
    const extension = canvas.getContext("webgl2").getExtension("WEBGL_lose_context");
    if (!extension) return false;
    extension.loseContext(); return true;
  }), true);
  await model.getByRole("alert").waitFor();
  assert.match(await model.getByRole("alert").innerText(), /Graphics connection lost/);
  await model.getByRole("button", { name: "Try again", exact: true }).click();
  await ready(boundsB);
  checked("Malformed GLB, HTTP failure and actual WebGL context loss release resources; explicit retry recovers");

  const delayedRequest = page.waitForRequest(request => request.url().endsWith("/api/models/D-902_A.glb"));
  await page.getByRole("button", { name: "SYNTHETIC delayed", exact: true }).click();
  await delayedRequest;
  await page.getByRole("button", { name: "SYNTHETIC reviewed B", exact: true }).click();
  await ready(boundsB);
  // Wait past the controlled delayed response: cancelled A must not reappear.
  await page.waitForTimeout(1000);
  assert.deepEqual((await last()).bounds, boundsB);
  assert.equal(await model.locator("canvas").count(), 1);
  await page.getByRole("button", { name: "SYNTHETIC missing", exact: true }).click();
  await page.getByRole("tab", { name: "3D", exact: true }).waitFor({ state: "detached" });
  assert.equal(await page.getByRole("tab", { name: "3D", exact: true }).count(), 0);
  await page.waitForFunction(() => window.viewerProbe.live.size === 0);
  resources = await page.evaluate(() => window.viewerResources());
  assert.deepEqual(resources, { urls: 0, canvasListeners: 0 });
  checked("In-flight model switch cannot resurrect cancelled asset; unavailable model hides shared PartPage 3D tab and cleans all canvas resources");
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, "synthetic-final.png") });
  report.outcome = "PASS";
  report.browser = browser.version();
} catch (error) {
  report.error = String(error?.stack ?? error); process.exitCode = 1;
  if (page) await page.screenshot({ path: path.join(output, "synthetic-failure.png") }).catch(() => {});
} finally {
  await browser?.close();
  await server.close();
  await writeFile(path.join(output, "report.json"), JSON.stringify({ ...report, checks, requests, errors }, null, 2) + "\n");
  console.log(JSON.stringify({ ...report, checks }));
}
