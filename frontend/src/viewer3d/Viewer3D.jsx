import React, { Component, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Bounds, OrbitControls, useBounds, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import './viewer3d.css';

const NOTICE = 'Reconstruction from 2D drawing. Not the original CAD model.';
const asset = path => path?.startsWith('/') || /^https?:/.test(path || '') ? path : `/generated/${path}`;
const number = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

class ModelError extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() { return this.state.error ? <div className="cad-empty" role="alert">Could not load reconstruction. {this.state.error.message}</div> : this.props.children; }
}

function Fit({ trigger, modelKey }) {
  const bounds = useBounds();
  useEffect(() => { bounds.refresh().clip().fit(); }, [bounds, trigger, modelKey]);
  return null;
}

function Model({ model, section, cut, fit }) {
  const { scene } = useGLTF(asset(model.glb));
  const clone = useMemo(() => scene.clone(true), [scene]);
  const bounds = model.bounds_mm;
  const center = bounds.min.map((value, index) => (value + bounds.max[index]) / 2);
  const plane = useMemo(() => new THREE.Plane(new THREE.Vector3(-1, 0, 0), cut), [cut]);
  useEffect(() => {
    clone.traverse(item => {
      if (item.isMesh) {
        const material = new THREE.MeshStandardMaterial({ color: '#969da6', metalness: 0.12, roughness: 0.6, side: THREE.DoubleSide, clippingPlanes: section ? [plane] : [], clipShadows: true });
        item.material = material;
      }
    });
    return () => clone.traverse(item => { if (item.isMesh) item.material.dispose(); });
  }, [clone, section, plane]);
  return <>
    <Bounds fit clip observe margin={1.35}>
      <group position={center.map(value => -value)}><primitive object={clone} scale={1000} /></group>
      <Fit trigger={fit} modelKey={model.glb} />
    </Bounds>
    <OrbitControls makeDefault enableDamping minPolarAngle={0.01} maxPolarAngle={Math.PI - 0.01} />
  </>;
}

export function Weight({ check, selected }) {
  if (!check) return null;
  const attempts = check.examples?.[selected]?.attempts || [];
  return <details className={`cad-weight cad-weight-${String(check.state).toLowerCase()}`}>
    <summary><strong>{check.state} weight check</strong><span>{check.state==='FAILED'?'Needs manual review':'View calculation'}</span></summary>
    <div className="cad-weight-detail">{attempts.map((attempt,index)=><p key={index}>{number(attempt.calculated_g)} g calculated · {number(attempt.drawing_g)} g on drawing · {number(attempt.difference_percent)}% difference.<br/>Using {attempt.source} material: {attempt.material}. <a href={attempt.source_url} target="_blank" rel="noreferrer">Density source</a> ({attempt.looked_up}); outside source, not the dataset. {attempt.note}</p>)}<p>{check.limitation}</p>{check.approval&&<p>Approved by {check.approval.by} on {check.approval.at}. {check.approval.note}</p>}</div>
  </details>;
}

export default function Viewer3D({ part, example, onExampleChange }) {
  const manifest = part?.model || part?.model_manifest || part?.models_manifest || {};
  const examples = manifest.examples || [];
  const preferred = manifest.selected_example || part?.preferred_example || part?.selected_example || 'A';
  const [localExample, setLocalExample] = useState(preferred);
  const selected = examples.includes(example) ? example : examples.includes(localExample) ? localExample : examples[0];
  const model = manifest.models?.[selected];
  const [fit, setFit] = useState(0);
  const [section, setSection] = useState(false);
  const [cutPercent, setCutPercent] = useState(50);
  const host = useRef(null);
  const size = model?.bounds_mm?.size;
  const cut = size ? (cutPercent / 100 - 0.5) * size[0] : 0;
  const template = part?.template || {};
  const reviewed = part?.design_review;
  const reviewLabel = reviewed ? `Reconstruction reviewed by ${reviewed.by} on ${reviewed.at}${part?.review_status === 'source_changed' ? '; some source evidence changed since review' : ''}` : manifest.label || 'AI reconstruction. Not reviewed by a person';
  const choose = value => { setLocalExample(value); onExampleChange?.(value); };
  useEffect(() => { setLocalExample(preferred); setSection(false); }, [part?.id, preferred]);
  return <section className="cad-viewer" ref={host} aria-label="3D reconstruction viewer">
    <div className="cad-toolbar">
      <div className="cad-examples" role="group" aria-label="Possible drawing readings">{examples.map(value => <button type="button" key={value} onClick={() => choose(value)} aria-pressed={value === selected}>Example {value}{manifest.models?.[value]?.selections?.thickness!=null?` · ${number(manifest.models[value].selections.thickness)} mm`:''}</button>)}</div>
      {model && <div className="cad-actions">
        <button type="button" onClick={() => setFit(value => value + 1)} title="Fit model in view">Fit</button>
        <button type="button" aria-pressed={section} onClick={() => setSection(value => !value)}>Section</button>
        <button type="button" onClick={() => { if (document.fullscreenElement) document.exitFullscreen?.(); else host.current?.requestFullscreen?.(); }}>Full screen</button>
      </div>}
    </div>
    {examples.length > 1 && <div className="cad-options">Possible readings</div>}
    {model ? <>
      <div className="cad-canvas">
        <ModelError key={model.glb}><Canvas camera={{ position: [350, -450, 300], near: 0.01, far: 100000, fov: 35, up: [0, 0, 1] }} gl={{ antialias: true, localClippingEnabled: true }}>
          <color attach="background" args={['#edf2f7']} />
          <ambientLight intensity={1.5} />
          <directionalLight position={[100, -200, 400]} intensity={3} />
          <directionalLight position={[-200, 100, 80]} intensity={1.2} />
          <gridHelper args={[Math.max(size?.[0] || 250, size?.[1] || 250) * 1.4, 20, '#c4cfdc', '#dae2eb']} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, -(size?.[2] || 0) / 2 - 1]} />
          <Suspense fallback={null}><Model model={model} section={section} cut={cut} fit={fit} /></Suspense>
        </Canvas></ModelError>
        <div className="cad-help">Drag to orbit · scroll to zoom · right-drag to pan</div>
      </div>
      {section && <label className="cad-section">Section position <input aria-label="Section position" type="range" min="0" max="100" value={cutPercent} onChange={event => setCutPercent(Number(event.target.value))} /></label>}
    </> : <div className="cad-empty">{'3D unavailable'}</div>}
    <div className="cad-disclosure"><p>{NOTICE}</p></div>
  </section>;
}
