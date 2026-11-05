import React, {useEffect, useRef, useState} from 'react';
import {Box, FileText, List, History, ZoomIn, ZoomOut, Scan, ChevronLeft, ChevronRight, X, Maximize2, ArrowUpRight, Link2, Layers, Fingerprint, Info, Download} from 'lucide-react';
import {useDebug} from '../debug';
import Viewer3D, {Weight} from '../viewer3d/Viewer3D.jsx';
import {api, imageURL, partKey, pathKey, textValue, titleCase, partURL, reviewURL} from '../api';
import {englishText, englishName, translated} from '../language';
import {Loading, ErrorMessage, StatusBadge, WeightBadge, Value, JsonDetails, SafeLink} from '../components';

export function FactBadge({fact, onClick}) { return <button className={`fact-badge ${fact?.review?.status === 'human_confirmed' ? 'confirmed' : fact?.badge?.toLowerCase().includes('ai') ? 'ai' : ''}`} onClick={onClick} title="View this fact's full history">{fact?.badge || 'Source record'}{fact?.review?.status==='human_confirmed' && ' · reviewed'}</button>; }

function evidenceFact(part,id) {
  const fields=[...Object.values(part.drawing?.fields||{}),...(part.drawing?.numbers||[]),...(part.drawing?.callouts||[])];
  const field=fields.find(f=>f.name===id);
  if(!field)return null;
  const known=field.value!=null&&field.confidence!=='unsure'&&field.state!=='unknown';
  return {fact:id,field:id.includes('/drawing/n/')?'Unlabeled drawing number':id.split('/').at(-1),display:known?{state:'value',value:field.value}:{state:'undetermined',message:field.note||'Not reliably determined from the evidence'},badge:field.method?.startsWith('ai')?'AI interpretation, not reviewed':'From PDF',sources:[{name:id,says:field.original??field.value,page:field.page,box:field.box,part_key:partKey(part)}]};
}

function rawField(part,id) {
  let found;
  const walk=value=>{if(!value || typeof value!=='object' || found)return;if(value.name===id){found=value;return}for(const [k,v] of Object.entries(value))if(!['readers','review','correction'].includes(k))walk(v)};
  walk(part.drawing?.fields);walk(part.template);walk(part.bom);return found;
}

function HistoryEntry({entry:e,part,onSource}) {
  const target=e.fact||e.applies_to||e.target,raw=rawField(part,target),source=e.source;
  return <><div className="row between"><strong>{titleCase(e.type || e.event || e.kind || 'Evidence')}</strong><small className="muted">{e.at || e.timestamp || 'Original source'}</small></div>{target&&<code className="timeline-target">{target}</code>}{e.value!==undefined&&<div className="timeline-value">{textValue(e.value)}</div>}<div className="timeline-meta">{e.method&&<span>Method: {e.method}</span>}{e.status&&<span>{titleCase(e.status)}</span>}{e.by&&<span>By {e.by}</span>}</div>{e.old_value!==undefined&&<p className="muted">Originally: {textValue(e.old_value)}</p>}{e.note&&<p className="timeline-note">{e.note}</p>}{e.message&&<p className="timeline-note">{e.message}</p>}{e.based_on?.sha256&&<small className="muted fingerprint block">Evidence SHA-256: {e.based_on.sha256}</small>}{e.check_result&&<details><summary>Automatic check result</summary><JsonDetails value={e.check_result}/></details>}{raw?.cleanup?.length>0&&<details><summary>Parts list cleanup rules</summary><JsonDetails value={raw.cleanup}/></details>}{raw?.readers&&<details><summary>Both AI readings, including retry rounds</summary><JsonDetails value={raw.readers}/></details>}{source?.drawing&&target&&<button className="text-button" onClick={()=>onSource?.(target)}>Open source drawing{source.page?` · sheet ${source.page}`:''} <ArrowUpRight size={12}/></button>}{source?.bom?.length>0&&<details><summary>Linked parts list rows</summary>{source.bom.map(r=><p key={r.name}>{r.display_name || r.name}</p>)}</details>}</>;
}

function DrawingSources({part,fact,navigate,openFact,compact}) {
  const debug=useDebug();
  const relevant=fact?[fact]:(part.facts||[]).filter(f=>f.fact?.includes('/drawing/')&&!f.fact?.includes('/n/'));
  return <aside className="drawing-sources"><div className="eyebrow">{part.drawing?.degraded?'DEGRADED SCAN READINGS':'CITED EVIDENCE'}</div>{part.drawing?.degraded&&<p className="muted source-explainer">AI readings are shown beside the original scan. Uncertain fields stay Undetermined.</p>}{relevant.map(f=>{const raw=Object.values(part.drawing?.fields||{}).find(v=>v.name===f.fact);return <section key={f.fact}><h4>{titleCase(f.field)}</h4><div className="fact-value"><Value fact={f}/></div>{f.display?.message&&<p className="muted">{f.display.message}</p>}<FactBadge fact={f} onClick={()=>openFact(f)}/>{f.sources?.map((s,i)=><div className="panel-source" key={i}><small>{s.name}</small><p className="source-verbatim">{s.says==null?'No extracted source text. See the original drawing.':textValue(s.says)}</p>{s.box&&<button className="text-button" onClick={()=>navigate(partURL(partKey(part),'2d',{fact:s.name}),{keepPanel:compact,replace:true})}>Highlight on drawing <ArrowUpRight size={11}/></button>}</div>)}{debug&&raw?.readers&&<details className="source-readers"><summary>Both AI readings & reasons</summary>{Object.entries(raw.readers).map(([reader,data])=><div key={reader}><strong>{reader}</strong>{(data.rounds||[data]).map((round,i)=>{const answer=round.answer||round;return <div key={i}><small>Round {i+1} · {answer.confidence}</small><p>{answer.value_json ?? textValue(answer.value)}</p><p>{answer.reason}</p></div>})}</div>)}</details>}</section>})}</aside>;
}

function HistoryView({part, fact, onSource}) {
  const [data,setData]=useState(null), [error,setError]=useState('');
  useEffect(()=>{let live=true;setData(null);setError('');api(`/api/parts/${pathKey(partKey(part))}/history${fact ? `?fact=${encodeURIComponent(fact.fact)}`:''}`).then(d=>live&&setData(d)).catch(e=>live&&setError(e.message));return()=>{live=false}},[part.id,fact?.fact]);
  if(error) return <ErrorMessage>{error}</ErrorMessage>;
  if(!data) return <Loading label="Loading original evidence and decisions…"/>;
  let entries=Array.isArray(data)?data:(data.events || data.history || data.timeline || []);
  if(fact) entries=entries.filter(e=>!e.fact&&!e.applies_to&&!e.target || [e.fact,e.applies_to,e.target].includes(fact.fact));
  return <div className="history-view"><div className="section-heading"><History size={17}/><div><h3>{fact?'Fact history':'Evidence & decision history'}</h3><p>Original evidence and every review decision stay in this record.</p></div></div>{fact&&<div className="history-current"><small>CURRENT DISPLAY VALUE</small><h3><Value fact={fact}/></h3><code>{fact.fact}</code></div>}{entries.length?entries.map((e,i)=><article className="timeline-entry" key={e.decision_id||i}><span className="timeline-dot"/><HistoryEntry entry={e} part={part} onSource={onSource}/></article>):<div className="empty-inline">No decisions recorded for this {fact?'fact':'part'} yet. Original evidence is available in Detail.</div>}{!fact&&<section className="history-current"><small>CURRENT VALUES</small>{(part.facts||[]).map(f=><div className="current-history-fact" key={f.fact}><span>{titleCase(f.field)}</span><Value fact={f}/></div>)}</section>}</div>;
}

export function DrawingViewer({part, fact, page:controlledPage, onPageChange}) {
  const [pageLocal,setPageLocal]=useState(1), [zoom,setZoom]=useState(1), [failed,setFailed]=useState(false);
  const viewport=useRef(null), image=useRef(null), drag=useRef(null);
  const key=partKey(part), pages=Number(part.drawing?.pages)||1, page=controlledPage||pageLocal;
  const setPage=p=>{setPageLocal(p);onPageChange?.(p);setFailed(false)};
  const source=fact?.sources?.find(s=>s.box && (!s.part_key || s.part_key===key)) || fact?.sources?.find(s=>s.box);
  const sourceField=part.drawing?.fields && Object.values(part.drawing.fields).find(f=>f.name===fact?.fact);
  const box=source?.box || sourceField?.box;
  const factPage=source?.page || sourceField?.page || 1;
  useEffect(()=>{setZoom(1);setFailed(false);setPageLocal(1)},[key]);
  useEffect(()=>{if(fact?.fact) setPage(factPage)},[fact?.fact]);
  const sizes=part.drawing?.page_sizes;
  const size=Array.isArray(sizes?.[page-1])?sizes[page-1]:[595,842];
  const highlight=box&&factPage===page;
  return <div className="drawing-viewer"><div className="viewer-toolbar"><div className="row"><button title="Zoom out" onClick={()=>setZoom(z=>Math.max(.3,z-.2))}><ZoomOut size={16}/></button><span className="zoom-readout">{Math.round(zoom*100)}%</span><button title="Zoom in" onClick={()=>setZoom(z=>Math.min(4,z+.2))}><ZoomIn size={16}/></button><button onClick={()=>setZoom(1)}><Scan size={15}/> Fit</button></div><div className="row"><button disabled={page<=1} onClick={()=>setPage(page-1)}><ChevronLeft size={15}/></button><span className="muted">Sheet {page} / {pages}</span><button disabled={page>=pages} onClick={()=>setPage(page+1)}><ChevronRight size={15}/></button></div></div>{fact&&<div className="evidence-strip"><span className="blue-dot"/><strong>{titleCase(fact.field || fact.fact?.split('/').at(-1))}</strong><span><Value fact={fact}/></span><span className="muted">Source highlighted {highlight?'below':'where available'}</span></div>}<div className="drawing-scroll" ref={viewport} onPointerDown={e=>{if(e.button!==0)return;drag.current={x:e.clientX,y:e.clientY,left:e.currentTarget.scrollLeft,top:e.currentTarget.scrollTop};e.currentTarget.setPointerCapture(e.pointerId)}} onPointerMove={e=>{if(drag.current){e.currentTarget.scrollLeft=drag.current.left-(e.clientX-drag.current.x);e.currentTarget.scrollTop=drag.current.top-(e.clientY-drag.current.y)}}} onPointerUp={()=>{drag.current=null}} onPointerCancel={()=>{drag.current=null}}>{failed?<ErrorMessage>The drawing image could not be loaded.</ErrorMessage>:<div className="drawing-paper" style={{width:`${zoom*90}%`}}><img ref={image} draggable="false" src={imageURL(key,page)} alt={`${part.display_name}, drawing sheet ${page}`} onError={()=>setFailed(true)}/>{highlight&&<div className="drawing-highlight" title={fact.fact} style={{left:`${box[0]/size[0]*100}%`,top:`${box[1]/size[1]*100}%`,width:`${Math.max(box[2]/size[0]*100,1)}%`,height:`${Math.max(box[3]/size[1]*100,.7)}%`}}/>}</div>}</div><div className="viewer-footnote">Drag to pan · use the toolbar to zoom · original drawing preserved{part.drawing?.degraded?' · degraded scan':''}</div></div>;
}

function BOMRows({part, navigate}) {
  if(!part.bom?.length) return <p className="muted">{part.link?.status==='unresolved' || part.link?.method==='unresolved'?'Undetermined — drawing and parts list have not been linked.':'No linked parts list row recorded.'}</p>;
  return part.bom.map(row=><article className="bom-card" key={row.name}><div className="row between"><div><strong>{row.display_name || row.name}</strong><small className="muted block">{row.display_id} · {row.section}</small></div>{row.key&&<button className="icon-button" title="Open row" onClick={()=>navigate(partURL(row.key,'detail'))}><ArrowUpRight size={15}/></button>}</div><p className="snapshot-note">Recorded in the snapshot, may be out of date.</p><table className="evidence-table"><thead><tr><th>Field</th><th>Original</th><th>Cleaned value</th></tr></thead><tbody>{Object.entries(row.fields||{}).map(([field,f])=><tr key={field}><td>{titleCase(field)}</td><td className="source-verbatim">{textValue(f.original)}</td><td>{field==='link'?<SafeLink href={f.value}/>:textValue(f.value)}{f.cleanup&&<small className="muted block">{textValue(f.cleanup)}</small>}</td></tr>)}</tbody></table></article>);
}

function DisplayValue({fact}) {
  if(fact?.display?.state==='value'&&typeof fact.display.value==='string')return <>{englishText(fact.display.value)}</>;
  return <Value fact={fact}/>;
}

function FactDetails({part, openFact, navigate}) {
  const debug=useDebug();
  const facts=Array.isArray(part.facts)?part.facts:Object.values(part.facts||{});
  const find=key=>facts.find(f=>f.field===key);
  const rows=items=><dl className="summary-rows">{items.map(([label,key,unit])=>{const f=find(key);return <div key={key} id={f?`fact-${encodeURIComponent(f.fact)}`:undefined}><dt>{label}</dt><dd><DisplayValue fact={f}/>{unit&&f?.display?.state!=='undetermined'&&f&&<span className="value-unit"> {unit}</span>}{f&&<button className="fact-source-action" title={`View ${label.toLowerCase()} source and history`} onClick={()=>openFact(f)}><FileText size={13}/></button>}</dd></div>})}</dl>;
  const circle=['circle','ring'].includes(part.template?.outline?.type);
  const dimensions=circle?[['Outer diameter','outer_diameter','mm'],...(part.template.outline.type==='ring'?[['Inner diameter','inner_diameter','mm']]:[])]:[['Length','length','mm'],['Width','width','mm']];
  const noteFields=facts.filter(f=>(['notes','design_intent'].includes(f.field)||f.fact?.includes('/drawing/general/'))&&f.display?.state==='value'&&typeof f.display.value==='string');
  const notes=noteFields.filter((f,i)=>noteFields.findIndex(n=>n.display.value.trim()===f.display.value.trim())===i);
  return <div className="detail-view standard-details"><div className="detail-summary-grid">
    <section className="summary-box" aria-labelledby="overview-heading"><h3 id="overview-heading">Overview</h3>{rows([...(find('title')?[['Drawing title','title']]:[]),['Material','material'],...(part.bom?.length?[['Quantity','amount']]:[])])}<p className="summary-hint">{englishText(part.section)}{part.has_drawing?` · Drawing ${part.drawing.id}`:' · Parts list record'}</p></section>
    <section className="summary-box" aria-labelledby="dimensions-heading"><h3 id="dimensions-heading">Dimensions</h3>{rows([...dimensions,['Thickness','thickness','mm'],['Drawing weight','weight_g','g']])}</section>
    <section className="summary-box notes-box" aria-labelledby="notes-heading"><h3 id="notes-heading">Notes</h3>{notes.length?<div className="design-notes">{notes.map(f=><div className="design-note" key={f.fact}><p>{englishText(f.display.value)}</p><button className="fact-source-action" title="View original note and source" onClick={()=>openFact(f)}><FileText size={13}/></button></div>)}</div>:<p className="summary-empty">No readable design notes recorded.</p>}{notes.some(f=>translated(f.display.value))&&<p className="summary-hint">English display translations. Original wording is available from the source icon.</p>}</section>
    {part.bom?.length>0&&<section className="summary-box supply-box" aria-labelledby="supply-heading"><h3 id="supply-heading">Supply & cost</h3>{rows([['Supplier','supplier'],['Unit cost','cost'],['Recorded total','total_cost'],['Order status','order']])}<p className="summary-hint">Snapshot records; prices and supplier details may be out of date.</p></section>}
  </div>{debug&&<button className="detail-evidence-link" onClick={()=>navigate(partURL(part.key,'debug'))}>Open Debug <ArrowUpRight size={13}/></button>}</div>;
}

function EvidenceDetails({part,openFact,navigate}) {
  const facts=Array.isArray(part.facts)?part.facts:Object.values(part.facts||{});
  return <div className="detail-view evidence-view"><div className="section-heading"><div><h3>Evidence & technical records</h3><p>Source values, provenance and reconstruction inputs.</p></div></div>
    <table className="evidence-table fact-table"><thead><tr><th>Field</th><th>Recorded value</th><th>Source & review</th></tr></thead><tbody>{facts.map(f=><tr key={f.fact}><td>{titleCase(f.field)}</td><td>{typeof f.display?.value==='object'&&f.display.value!==null?<details><summary>View structured value</summary><JsonDetails value={f.display.value}/></details>:<DisplayValue fact={f}/>}<details className="original-fact"><summary>Original wording & sources</summary>{f.sources?.map((s,i)=><div key={i}><code>{s.name}</code><p className="source-verbatim">{textValue(s.says)}</p><button className="text-button" onClick={()=>openFact(f,'source')}>Open source <ArrowUpRight size={12}/></button></div>)}</details></td><td><FactBadge fact={f} onClick={()=>openFact(f)}/>{f.review_item&&<button className="text-button" onClick={()=>navigate(reviewURL(f.review_item))}>Waiting for review</button>}</td></tr>)}</tbody></table>
    <details className="detail-section disclosure"><summary>Original parts-list rows</summary><BOMRows part={part} navigate={navigate}/></details>
    {part.template&&<details className="detail-section disclosure"><summary>Reconstruction template & reader outputs</summary><JsonDetails value={part.template}/></details>}
    <details className="detail-section disclosure"><summary>Recorded connections</summary><Connections part={part} navigate={navigate}/></details>
  </div>;
}

function Connections({part,navigate}) { return part.connections?.length?<div className="connections">{part.connections.map((c,i)=><div className="connection" key={i}><Link2 size={14}/><div>{c.target?<button className="text-button" onClick={()=>navigate(partURL(c.part_key || partKey({id:c.target}),'detail'))}>{c.text || c.target} <ArrowUpRight size={12}/></button>:<span>{c.text}</span>}<small className="muted block">Source: {c.source}</small></div></div>)}</div>:<p className="muted">No connections recorded.</p>; }


function SourceView({fact,onSource}) {
  return <div className="source-modal-content"><h3>{titleCase(fact.field)}</h3><p><DisplayValue fact={fact}/></p><StatusBadge>{fact.badge||'Source record'}</StatusBadge>{fact.sources?.map((source,i)=><section key={i}><small>{source.name}</small><p>{englishText(textValue(source.says))}</p>{translated(textValue(source.says))&&<details><summary>Original wording</summary><p className="source-verbatim">{textValue(source.says)}</p></details>}{source.box&&<button className="text-button" onClick={onSource}>Highlight on drawing <ArrowUpRight size={12}/></button>}</section>)}</div>;
}

function DebugView({part,openFact,navigate,initialSection}) {
  const [section,setSection]=useState(initialSection),manifest=part.model||{};
  return <div className="debug-view"><nav className="debug-tabs" aria-label="Debug sections">{[['records','Evidence'],['model','Model & checks'],['history','History']].map(([id,label])=><button key={id} className={section===id?'active':''} onClick={()=>setSection(id)}>{label}</button>)}</nav>{section==='records'?<><EvidenceDetails part={part} openFact={openFact} navigate={navigate}/><details className="detail-section disclosure"><summary>Complete original drawing & raw records</summary><JsonDetails value={{drawing:part.drawing,link:part.link,connections:part.connections}}/></details></>:section==='history'?<HistoryView part={part} onSource={id=>navigate(partURL(part.key,'2d',{fact:id}))}/>:<div className="debug-model"><h3>Reconstruction & verification</h3>{!part.model&&<p>No reconstruction is available.</p>}<Weight check={manifest.weight_check} selected={manifest.examples?.[0]}/>{Object.entries(manifest.models||{}).map(([id,model])=><section className="summary-box" key={id}><h3>Example {id}</h3><p>Solid volume: {model.volume_mm3} mm³. GLB stored in metres; CAD measured in mm.</p><a href={`/generated/${model.step}`} download>Download reconstruction (STEP)</a><p>Reconstruction from 2D drawing. Not the original CAD model.</p><details className="cad-provenance"><summary>Geometry, fingerprints & artifact checks</summary><JsonDetails value={model}/></details></section>)}<details className="detail-section disclosure"><summary>All model calculations, densities & omissions</summary><JsonDetails value={manifest}/></details><details className="detail-section disclosure"><summary>Template, proposer & verifier receipts</summary><JsonDetails value={part.template}/></details></div>}</div>;
}

export default function PartPage({partKey: key, initialTab, factId, example:initialExample, navigate, compact=false, onClose, onLoaded}) {
  const debug=useDebug();
  const [part,setPart]=useState(null), [error,setError]=useState(''), [tab,setTab]=useState(initialTab), [example,setExample]=useState(initialExample), [page,setPage]=useState(1), [historyFact,setHistoryFact]=useState(null);
  useEffect(()=>{let live=true;setPart(null);setError('');api(`/api/parts/${pathKey(key)}`).then(d=>{if(live){setPart(d);setExample(initialExample || d.preferred_example || d.model?.selected_example || 'A');onLoaded?.(d)}}).catch(e=>live&&setError(e.message));return()=>{live=false}},[key]);
  useEffect(()=>{setTab(initialTab);if(initialExample)setExample(initialExample)},[key,initialTab,initialExample,factId]);
  if(error) return <ErrorMessage>{error}</ErrorMessage>; if(!part)return <Loading label="Opening part evidence…"/>;
  const facts=Array.isArray(part.facts)?part.facts:Object.values(part.facts||{}), fact=facts.find(f=>f.fact===factId)||evidenceFact(part,factId||'');
  const has3d=Boolean(part.has_3d || part.model?.models && Object.keys(part.model.models).length || part.model?.waiting?.length);
  const hasBuilt=Boolean(part.has_3d||Object.keys(part.model?.models||{}).length);
  const humanInput=facts.some(f=>f.fact?.includes('/template/')&&f.sources?.some(s=>s.method==='human_decision'));
  const reconstructionLabel=part.review_status==='source_changed'?'REVIEW NEEDS UPDATE':part.design_review?'REVIEWED':hasBuilt?(humanInput?'AI + HUMAN INPUT':'AI RECONSTRUCTION'):has3d?'3D WAITING':part.has_drawing?'2D ONLY':'PARTS LIST ONLY';
  const requested=tab || (has3d?'3d':part.has_drawing?'2d':'detail');
  const current=['debug','evidence','history'].includes(requested)?(debug?'debug':'detail'):requested;
  const tabs=[...(has3d?[['3d','3D model',Box]]:[]),...(part.has_drawing?[['2d','2D drawing',FileText]]:[]),['detail','Detail',List],...(debug?[['debug','Debug',Fingerprint]]:[])];
  const changeTab=t=>{setTab(t);navigate(partURL(key,t,{...(factId?{fact:factId}:{}),...(t==='3d'?{example}:{})}),{replace:true,keepPanel:compact})};
  const openFact=(f,mode)=>{if(mode==='source'){const source=f.sources?.[0];const target=source?.part_key||f.part_key||key;navigate(partURL(target,source?.name?.startsWith('BOM:')?'detail':'2d',{fact:f.fact}),{panel:compact,replace:true})}else setHistoryFact(f)};
  return <div className={`part-page ${compact?'compact':''}`}><header className="part-header"><div className="part-symbol"><Box size={23}/></div><div className="part-title"><div className="eyebrow">{part.drawing?.id || 'PARTS LIST'} <span> / </span> {part.section}</div><h2>{englishName(part.display_name)}</h2><div className="row wrap"><StatusBadge tone={part.review_status==='source_changed'?'amber':part.design_review?'green':has3d?'amber':''}>{reconstructionLabel}</StatusBadge></div></div><div className="row">{compact&&<button className="icon-button" title="Open full page" onClick={()=>navigate(partURL(key,current,{...(factId?{fact:factId}:{})}))}><Maximize2 size={17}/></button>}{onClose&&<button className="icon-button" title="Close part" onClick={onClose}><X size={19}/></button>}</div></header><nav className="part-tabs">{tabs.map(([id,label,Icon])=><button className={current===id?'active':''} key={id} onClick={()=>changeTab(id)}><Icon size={15}/>{label}</button>)}{(part.review_items?.length>0||has3d)&&<button className="review-link" onClick={()=>navigate(`/review/part/${pathKey(key)}`)}>Review this part <ArrowUpRight size={12}/></button>}</nav><div className="part-body">{current==='3d'||current==='2d'?<>{current==='2d'&&Number(part.drawing?.pages)>1&&<aside className="sheet-rail"><div className="eyebrow">SHEETS</div>{Array.from({length:Number(part.drawing?.pages)||0},(_,i)=><button className={`sheet-thumb ${page===i+1?'active':''}`} key={i} onClick={()=>setPage(i+1)}><img src={imageURL(key,i+1,true)} alt={`Sheet ${i+1}`}/><span>Sheet {i+1}</span></button>)}</aside>}<div className="primary-view">{current==='3d'?<Viewer3D part={part} example={example} onExampleChange={e=>{setExample(e);navigate(partURL(key,'3d',{example:e}),{replace:true,keepPanel:compact})}}/>:<><DrawingViewer part={part} fact={fact} page={page} onPageChange={setPage}/>{(fact||part.drawing?.degraded)&&<details className="drawing-source-details disclosure"><summary>Source details</summary><DrawingSources part={{...part,facts}} fact={fact} navigate={navigate} openFact={openFact} compact={compact}/></details>}</>}</div></>:current==='debug'?<DebugView part={{...part,facts}} openFact={openFact} navigate={navigate} initialSection={requested==='history'?'history':'records'}/>:<FactDetails part={{...part,facts}} openFact={openFact} navigate={navigate}/>}</div>{historyFact&&<div className="modal-scrim" onClick={()=>setHistoryFact(null)}><section className="history-modal" onClick={e=>e.stopPropagation()}><button className="modal-close icon-button" onClick={()=>setHistoryFact(null)}><X size={19}/></button>{debug?<HistoryView part={part} fact={historyFact} onSource={id=>{setHistoryFact(null);navigate(partURL(key,'2d',{fact:id}),{keepPanel:compact})}}/>:<SourceView fact={historyFact} onSource={()=>{setHistoryFact(null);openFact(historyFact,'source')}}/>}</section></div>}</div>;
}
