// Capability probe only: actual WebGL rendering of invented CAD geometry.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const modules = path.join(root, 'development/.runtime/ci-browser/node_modules');
const require = createRequire(path.join(modules, 'probe.cjs'));
const { chromium } = require('playwright');
const output = path.join(root, 'testing/runs/capability/browser');
await mkdir(output, { recursive: true });
const html = `<!doctype html><html><body style="margin:0"><script type="importmap">
{"imports":{"three":"/modules/three/build/three.module.js","three/addons/":"/modules/three/examples/jsm/"}}
</script><script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
try {
 const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
 renderer.setSize(480,360); document.body.append(renderer.domElement);
 const scene=new THREE.Scene(); scene.background=new THREE.Color(0x112233);
 scene.add(new THREE.AmbientLight(0xffffff,2));
 const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(1,2,3);scene.add(light);
 const loaded=await new GLTFLoader().loadAsync('/model.glb');scene.add(loaded.scene);
 const camera=new THREE.PerspectiveCamera(45,480/360,0.001,10);
 camera.position.set(.14,.12,.14);camera.lookAt(0,.0025,0);renderer.render(scene,camera);
 const gl=renderer.getContext(), pixels=new Uint8Array(480*360*4);
 gl.readPixels(0,0,480,360,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
 let changed=0,meshes=0;
 for(let i=0;i<pixels.length;i+=4) if(Math.max(...[0,1,2].map(j=>Math.abs(pixels[i+j]-pixels[j])))>10)changed++;
 loaded.scene.traverse(object=>{if(object.isMesh)meshes++;});
 const box=new THREE.Box3().setFromObject(loaded.scene,true);
 window.probe={ok:true,meshes,changed_pixels:changed,bounds:[box.min.toArray(),box.max.toArray()],webgl:gl.getParameter(gl.VERSION)};
} catch(error){window.probe={ok:false,error:String(error)};}
</script></body></html>`;
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (pathname === '/') { response.setHeader('Content-Type', 'text/html'); response.end(html); return; }
    if (pathname === '/favicon.ico') { response.statusCode = 204; response.end(); return; }
    let file;
    if (pathname === '/model.glb') file = path.join(root, 'testing/runs/capability/cad/synthetic-plate.glb');
    else if (pathname.startsWith('/modules/')) {
      file = path.resolve(modules, pathname.slice('/modules/'.length));
      assert.ok(file.startsWith(modules + path.sep));
    } else { response.statusCode = 404; response.end(); return; }
    response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : 'model/gltf-binary');
    response.end(await readFile(file));
  } catch { response.statusCode = 500; response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
const errors = [];
let report = { outcome: 'FAIL', scope: 'Synthetic Linux CAD/headless WebGL capability; no product UI gate',
  commit: process.env.GITHUB_SHA, run_id: process.env.GITHUB_RUN_ID };
try {
  browser = await chromium.launch({ headless: true, args: [
    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
    '--disable-dev-shm-usage', '--renderer-process-limit=1', '--num-raster-threads=1',
  ] });
  const page = await browser.newPage({ viewport: { width: 480, height: 360 } });
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if(message.type() === 'error') errors.push(message.text()); });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => window.probe !== undefined, null, { timeout: 30000 });
  const measured = await page.evaluate(() => window.probe);
  await page.screenshot({ path: path.join(output, 'render.png') });
  assert.ok(measured.ok, JSON.stringify(measured));
  assert.ok(measured.meshes > 0 && measured.changed_pixels > 200, JSON.stringify(measured));
  const expected = [-.05,0,-.03,.05,.005,.03];
  assert.ok(measured.bounds.flat().every((value,index) => Math.abs(value-expected[index])<1e-7));
  assert.equal(errors.length, 0, JSON.stringify(errors));
  report = { ...report, outcome: 'PASS', browser: browser.version(), measured };
} catch (error) {
  report = { ...report, error: String(error) }; process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ ...report, errors }, null, 2) + '\n');
  console.log(JSON.stringify(report));
}
