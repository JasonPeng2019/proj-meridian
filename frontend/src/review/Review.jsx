import React, {useEffect, useState} from 'react';
import {Check, X, ChevronRight, ArrowUpRight, ShieldCheck, AlertTriangle, Box, RefreshCw, Search} from 'lucide-react';
import ReaderAnswers from '../ReaderAnswers';
import PartPage, {DrawingViewer} from '../part/PartPage';
import Viewer3D from '../viewer3d/Viewer3D';
import {api,pathKey,partKey,partURL,reviewURL,textValue,titleCase} from '../api';
import {ErrorMessage, Loading, JsonDetails, StatusBadge, WeightBadge} from '../components';
import {englishName,englishText} from '../language';

const tabs=[['parts','Parts'],['awaiting-review','Full queue'],['corrections','Corrections'],['needs-input','Needs human input'],['ai','AI interpretations'],['possible-readings','Possible readings']];
function category(item) { if(item.type==='correction')return 'corrections';if(item.type==='possible_reading')return 'possible-readings';if(item.type==='ai_interpretation'||item.type==='part')return 'ai';return 'needs-input'; }
function parseValue(value) {try{return JSON.parse(value)}catch{return value}}
const itemPartKey=item=>item.part_key||item.evidence?.part_key;
const settled=item=>['accepted','rejected','human_confirmed','human_rejected','approved','reviewed'].includes(item.status);
function scopedURL(url,key) {const [path,query='']=url.split('?');const params=new URLSearchParams(query);if(key)params.set('part',key);else params.delete('part');return path+(params.size?`?${params}`:'');}
function Evidence({item,navigate}) {
  const evidence=item.evidence || {}, key=item.part_key||evidence.part_key;
  const fact={fact:item.target,field:item.target?.split('/').at(-1),display:item.value==null?{state:'undetermined',message:'Waiting for human input'}:{state:'value',value:item.value},sources:[{name:item.target,page:evidence.page,box:evidence.box,part_key:key}]};
  return <div className="review-evidence"><h4>Source evidence</h4>{evidence.drawing&&<div className="review-drawing"><DrawingViewer part={{key,display_name:item.title,drawing:evidence.drawing}} fact={evidence.box?fact:null}/></div>}{item.original!==undefined&&<div className="review-values"><div><small>ORIGINAL VALUE</small><div className="source-verbatim">{textValue(item.original)}</div></div><div><small>{item.type==='correction'?'PROPOSED VALUE':'CURRENT READING'}</small><div>{textValue(item.value)}</div></div></div>}{evidence.bom?.map(row=><details className="review-bom" key={row.name}><summary>Parts list row: {row.display_name || row.name}</summary><table className="evidence-table"><thead><tr><th>Field</th><th>Original</th><th>Cleaned</th></tr></thead><tbody>{Object.entries(row.fields||{}).map(([k,f])=><tr key={k}><td>{titleCase(k)}</td><td>{textValue(f.original)}</td><td>{textValue(f.value)}</td></tr>)}</tbody></table><p className="snapshot-note">Recorded in the snapshot, may be out of date.</p></details>)}{evidence&&!evidence.drawing&&!evidence.bom&&<details className="review-more disclosure"><summary>Source references</summary><JsonDetails value={evidence}/></details>}<details className="review-more disclosure"><summary>AI readings & reasons</summary><ReaderAnswers readers={item.readers}/></details>{item.weight_check&&<details className="review-more disclosure"><summary>Weight calculation</summary><JsonDetails value={item.weight_check}/></details>}{item.reason&&<div className="review-reason"><strong>Check result / reason</strong><p>{textValue(item.reason)}</p></div>}{item.check_result&&<details className="review-more disclosure"><summary>Automatic check details</summary><JsonDetails value={item.check_result}/></details>}</div>;
}

function PossibleReadingsPreview({item}) {
  const [part,setPart]=useState(null),[error,setError]=useState('');
  useEffect(()=>{setPart(null);setError('');if(item.part_key)api(`/api/parts/${pathKey(item.part_key)}`).then(setPart).catch(e=>setError(e.message))},[item.id]);
  if(error)return <ErrorMessage>{error}</ErrorMessage>;
  if(!part)return <Loading label="Loading possible drawing readings…"/>;
  const examples=part.model?.examples||[];
  return <section className="readings-comparison"><h4>Compare possible readings</h4><p>Each example uses a number printed on the drawing. Neither is chosen by default.</p>{examples.length?<div className="readings-models">{examples.map(example=><div key={example}><h4>Example {example}</h4><Viewer3D part={part} example={example}/></div>)}</div>:<p className="muted">The 3D examples are waiting for other required fields. Review the source numbers and options below.</p>}</section>;
}

function ReadingsDisclosure({item}) {
  const [open,setOpen]=useState(false);
  return <details className="review-more disclosure" onToggle={event=>setOpen(event.currentTarget.open)}><summary>Compare 3D examples</summary>{open&&<PossibleReadingsPreview item={item}/>}</details>;
}

function ReviewActions({item,onAction,busy,navigate}) {
  const [value,setValue]=useState(''),[note,setNote]=useState('');
  useEffect(()=>{setValue('');setNote('')},[item.id]);
  const kind=item.type,options=item.options || item.fact?.display?.values || [],isDesign=item.id?.startsWith('design:');
  const final=['accepted','rejected','human_confirmed','human_rejected','approved'].includes(item.status);
  if(isDesign||kind==='weight')return <div className="review-actions"><p className="muted">Inspect the entire part and resolve waiting fields before approving its design.</p><button className="button primary" onClick={()=>navigate(`/review/part/${pathKey(item.part_key)}`)}><ShieldCheck size={15}/>Review whole design</button></div>;
  return <div className="review-actions">{final&&<div className="notice info">Current status: {titleCase(item.status)}. Further actions are saved as new decisions.</div>}{options.length>0&&<div className="option-choices"><label className="field-label">{kind==='name_mapping'?'Choose a relationship from your review':'Possible readings — choose only after checking the evidence'}</label>{options.map((o,i)=><button className="option-choice" key={i} disabled={busy} onClick={()=>onAction(kind==='name_mapping'?'approve_mapping':'choose_option',o.value??o,note)}><span>{textValue(o.value??o)}</span><span>{kind==='name_mapping'?'Approve relationship':'Choose reading'} <ChevronRight size={13}/></span></button>)}</div>}{kind==='link'&&<label className="field-label">Parts list match<select value={value} onChange={e=>setValue(e.target.value)}><option value="">Select a matching row…</option><option value="__none__">No equivalent parts list row</option>{(item.rows||[]).map(r=><option key={r.name} value={r.name}>{r.display_name} · {r.section}</option>)}</select></label>}<label className="field-label">Review note (optional)<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Record what you checked and why…" rows={2}/></label><div className="row wrap">{kind==='correction'?<button className="button primary" disabled={busy} onClick={()=>onAction('accept',undefined,note)}><Check size={15}/>Accept correction</button>:kind==='name_mapping'?<button className="button primary" disabled={busy} onClick={()=>onAction('approve_mapping',undefined,note)}><Check size={15}/>Approve suggested mapping</button>:kind==='source_changed'?<button className="button primary" disabled={busy} onClick={()=>onAction('accept',undefined,note)}><Check size={15}/>Re-approve against current evidence</button>:kind==='ai_interpretation'?<button className="button primary" disabled={busy} onClick={()=>onAction('confirm',undefined,note)}><Check size={15}/>Confirm interpretation</button>:kind==='link'?<button className="button primary" disabled={busy||!value} onClick={()=>onAction('accept',value==='__none__'?[]:[value],note)}><Check size={15}/>Accept reviewed link</button>:null}<button className="button danger-outline" disabled={busy} onClick={()=>onAction('reject',undefined,note)}><X size={15}/>Reject</button></div>{!['correction','name_mapping','weight','link'].includes(kind)&&<div className="set-value"><label className="field-label">Set a value from your review<input value={value} onChange={e=>setValue(e.target.value)} placeholder="Enter the value shown in the evidence"/></label><button className="button secondary" disabled={busy||!value.trim()} onClick={()=>onAction('set_value',parseValue(value),note)}>Save reviewed value</button></div>}<p className="muted review-disclaimer">Your action is recorded under the configured reviewer name. Original values and rejected readings remain in History.</p></div>;
}

function PartReview({partKey:key,items,navigate,onAction,busy,revision}) {
  const [part,setPart]=useState(null),[note,setNote]=useState(''),[view,setView]=useState({});
  const navigatePart=(url,options)=>{const parsed=new URL(url,window.location.origin),base=partURL(key);if(parsed.pathname===base||parsed.pathname.startsWith(base+'/')){setView({tab:parsed.pathname===base?undefined:parsed.pathname.slice(base.length+1),fact:parsed.searchParams.get('fact'),example:parsed.searchParams.get('example')});}else navigate(url,options)};
  const relevant=items.filter(i=>i.part_key===key),waiting=part?.model?.waiting||[];
  const needsValue=relevant.filter(i=>['template','link','source_changed'].includes(i.type)&&!['accepted','human_confirmed','rejected'].includes(i.status)&&!i.options?.length);
  const blocked=part?.waiting?.length || waiting.length || needsValue.length,check=part?.model?.weight_check||part?.weight_check,failed=String(check?.state||'').toLowerCase()==='failed';
  return <div className="part-review-layout"><div className="part-review-canvas"><PartPage key={`${key}-${revision}`} partKey={key} initialTab={view.tab||'debug'} factId={view.fact} example={view.example} navigate={navigatePart} onLoaded={setPart}/></div><aside className="part-review-controls"><div className="section-heading"><ShieldCheck size={20}/><div><h3>Review this design</h3><p>One part. Every AI interpretation.</p></div></div><p>Inspect the drawing, reconstruction, template fields and source evidence before approving.</p><WeightBadge check={check}/>{blocked>0&&<div className="notice warning"><AlertTriangle size={16}/><span>{blocked} {blocked===1?'field still needs':'fields still need'} input{waiting.length?`: ${waiting.map(textValue).join(', ')}`:''}.</span></div>}{failed&&<div className="notice error">FAILED weight check — needs manual approval. Explain why the reconstruction is acceptable.</div>}<label className="field-label">Approval note {failed?'(required)':'(optional)'}<textarea rows={4} value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you check?"/></label><button className="button primary full-width" disabled={!part?.has_3d||Boolean(blocked)||busy||failed&&!note.trim()} onClick={()=>onAction(`design:${part.id}`,'approve_design',undefined,note)}><ShieldCheck size={16}/>Approve whole design</button><p className="muted">{part&&!part.has_3d?'A built reconstruction is required for whole-design approval. ':''}Approval applies only to this part. Possible readings may stay open. Your decision is saved with the evidence fingerprint.</p><details className="review-more disclosure"><summary>Items on this part ({relevant.length})</summary><div className="part-review-items">{relevant.map(i=><button key={i.id} onClick={()=>navigate(reviewURL(i.id,category(i)))}><span>{i.title || i.target}</span><small>{titleCase(i.status)}</small><ChevronRight size={13}/></button>)}</div></details></aside></div>;
}

function FocusedReviewPart({partKey:key,revision,navigate,onReviewItems}) {
  const [view,setView]=useState({tab:'debug'});
  const navigatePart=(url,options)=>{
    const parsed=new URL(url,window.location.origin),base=partURL(key);
    if(parsed.pathname===base||parsed.pathname.startsWith(base+'/')){
      setView({tab:parsed.pathname===base?'debug':parsed.pathname.slice(base.length+1),fact:parsed.searchParams.get('fact'),example:parsed.searchParams.get('example')});
    }else navigate(url,options);
  };
  return <section className="review-part-focus">
    <div className="review-part-focus-toolbar row wrap">
      <button className="button secondary" onClick={onReviewItems}>Review items</button>
      <button className="button primary" onClick={()=>navigate(scopedURL(`/review/part/${pathKey(key)}`,key))}><ShieldCheck size={15}/>Review whole design</button>
    </div>
    <div className="review-part-focus-canvas"><PartPage key={`${key}-${revision}`} partKey={key} initialTab={view.tab} factId={view.fact} example={view.example} navigate={navigatePart}/></div>
  </section>;
}

export default function Review({route,navigate,onChanged}) {
  const [items,setItems]=useState(null),[summaries,setSummaries]=useState(null),[error,setError]=useState('');
  const [busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0);
  const [filter,setFilter]=useState(''),[partSearch,setPartSearch]=useState(''),[status,setStatus]=useState(''),[type,setType]=useState(''),[method,setMethod]=useState(''),[weight,setWeight]=useState(''),[accuracy,setAccuracy]=useState(null);
  const load=()=>{
    setError('');
    api('/api/review').then(d=>setItems(Array.isArray(d)?d:d.items||[])).catch(e=>setError(e.message));
    api('/api/accuracy').then(setAccuracy).catch(()=>{});
    api('/api/parts').then(d=>setSummaries(Array.isArray(d)?d:d.parts||[])).catch(e=>setError(e.message));
  };
  useEffect(load,[]);
  const act=async(id,action,value,note)=>{
    setBusy(true);setError('');setNotice('');
    try{await api(`/api/review/${pathKey(id)}`,{action,...(value!==undefined?{value}:{}),...(note?{note}:{})});setNotice('Decision saved. Original evidence is preserved.');setRevision(r=>r+1);load();onChanged?.()}
    catch(e){setError(e.message)}finally{setBusy(false)}
  };
  const active=route.category||'parts',scope=active==='awaiting-review'?'':route.partKey||route.partFilter||'';
  const allItems=items||[],scopedItems=scope?allItems.filter(item=>itemPartKey(item)===scope):allItems;
  const scopePart=(summaries||[]).find(part=>partKey(part)===scope);
  const navigateScoped=(url,options)=>navigate(url.startsWith('/review')?scopedURL(url,scope):url,options);
  const selected=scopedItems.find(item=>item.id===route.item||item.target===route.item);
  const query=partSearch.trim().toLowerCase();
  const catalog=(summaries||[]).filter(part=>[part.display_name,englishName(part.display_name),part.key,part.id,part.drawing?.id,part.section,englishText(part.section)].join(' ').toLowerCase().includes(query));
  const clearFilters=()=>{setFilter('');setStatus('');setType('');setMethod('');setWeight('')};
  const reviewItems=key=>{clearFilters();const local=allItems.filter(item=>itemPartKey(item)===key),queue=['needs-input','corrections','possible-readings','ai'].find(id=>local.some(item=>category(item)===id&&!settled(item)))||'ai';navigate(scopedURL(`/review/${queue}`,key))};
  const filtered=scopedItems.filter(item=>(active==='awaiting-review'?!settled(item):category(item)===active)&&(!filter||[item.title,item.target,item.part_key,englishText(item.title)].join(' ').toLowerCase().includes(filter.toLowerCase()))&&(!status||item.status===status)&&(!type||item.type===type)&&(!method||item.method===method)&&(!weight||String((item.weight_check||(summaries||[]).find(part=>partKey(part)===itemPartKey(item))?.weight_check)?.state||'').toLowerCase()===weight));
  return <div className="review-page">
    <header className="workspace-header"><div><span className="workspace-label">ENGINEERING WORKSPACE</span><h1>Engineering workspace</h1></div><div className="review-header-actions">{items&&<button className="text-button review-global-count" aria-label="Show all items awaiting human review" onClick={()=>{clearFilters();navigate('/review/awaiting-review')}}>{allItems.filter(item=>!settled(item)).length} awaiting human review</button>}{accuracy&&<details className="accuracy-card"><summary><ShieldCheck size={17}/>Human review accuracy</summary><JsonDetails value={accuracy}/></details>}<button className="button secondary" onClick={load}><RefreshCw size={14}/>Refresh</button></div></header>
    {error&&<ErrorMessage>{error}</ErrorMessage>}
    {notice&&<div className="notice success"><Check size={16}/>{notice}</div>}
    <nav className="review-tabs" aria-label="Review categories">{tabs.map(([id,label])=><button key={id} className={active===id?'active':''} onClick={()=>{if(id==='awaiting-review'){clearFilters();navigate('/review/awaiting-review')}else navigate(scopedURL(`/review/${id}`,scope))}}>{label}<span>{id==='parts'?(summaries||[]).length:id==='awaiting-review'?allItems.filter(item=>!settled(item)).length:scopedItems.filter(item=>category(item)===id).length}</span></button>)}</nav>
    {scope&&<div className="review-scope row between"><span>Part scope: <strong>{scopePart?englishName(scopePart.display_name):scope}</strong>{scopePart&&scope!==englishName(scopePart.display_name)&&<span className="muted"> / {scope}</span>}</span><button className="text-button" onClick={()=>navigate(`/review/${active}`)}>Clear part scope <X size={13}/></button></div>}
    {route.partKey?<PartReview key={route.partKey} partKey={route.partKey} revision={revision} items={allItems} navigate={navigateScoped} onAction={act} busy={busy}/>:active==='parts'?<div className="review-parts-workspace">
      <aside className="review-parts-catalog">
        <header><label className="search-field"><Search size={15}/><input aria-label="Search review parts" value={partSearch} onChange={event=>setPartSearch(event.target.value)} placeholder="Search name, drawing ID or section"/>{partSearch&&<button aria-label="Clear part search" onClick={()=>setPartSearch('')}><X size={14}/></button>}</label><p className="muted">{summaries?`${catalog.length} ${catalog.length===1?'part':'parts'}${query?' found':''}`:'Loading parts...'}</p></header>
        <div className="review-parts-results">{!summaries?<Loading label="Loading parts..."/>:catalog.length?catalog.map(part=>{
          const key=partKey(part),partItems=allItems.filter(item=>itemPartKey(item)===key),open=partItems.filter(item=>!settled(item)).length;
          const reviewed=['reviewed','human_confirmed','approved'].includes(part.review_status);
          const label=part.review_status==='source_changed'?'Source changed':reviewed?'Human reviewed':part.has_3d?'AI reviewed':'Source only';
          return <button key={key} className={`review-part-row ${scope===key?'active':''}`} title={`Inspect ${englishName(part.display_name)} (${part.drawing?.id||key})`} aria-current={scope===key?'true':undefined} onClick={()=>navigate(scopedURL('/review/parts',key))}>
            <div className="review-part-summary"><strong>{englishName(part.display_name)}</strong><small>{part.drawing?.id||key} / {englishText(part.section)||'Unassigned section'}</small></div>
            <div className="review-part-counts"><span>{items?`${open} open / ${partItems.length} items`:'Loading review items...'}</span><StatusBadge tone={reviewed?'green':part.review_status==='source_changed'?'amber':''}>{label}</StatusBadge><ChevronRight size={14}/></div>
          </button>;
        }):<div className="empty-inline"><Search size={22}/><p>{query?'No parts match this search.':'No parts are available.'}</p>{query&&<button className="text-button" onClick={()=>setPartSearch('')}>Clear search</button>}</div>}</div>
      </aside>
      {scope?<FocusedReviewPart key={scope} partKey={scope} revision={revision} navigate={navigateScoped} onReviewItems={()=>reviewItems(scope)}/>:<div className="review-part-focus library-empty"><Box size={34}/><h3>Select a part</h3><p>Inspect its drawing, reconstruction and evidence.<br/>Review individual items or the whole design.</p></div>}
    </div>:<>
      <div className="review-toolbar"><label className="search-field"><Search size={15}/><input value={filter} onChange={event=>setFilter(event.target.value)} placeholder="Filter review items..."/></label><details className="review-filter-options"><summary>Filters</summary><div>
        <select aria-label="Review item type" value={type} onChange={event=>setType(event.target.value)}><option value="">All types</option>{[...new Set(scopedItems.map(item=>item.type))].map(value=><option value={value} key={value}>{titleCase(value)}</option>)}</select>
        <select aria-label="Review status" value={status} onChange={event=>setStatus(event.target.value)}><option value="">All review statuses</option>{[...new Set(scopedItems.map(item=>item.status))].map(value=><option value={value} key={value}>{titleCase(value)}</option>)}</select>
        <select aria-label="Interpretation method" value={method} onChange={event=>setMethod(event.target.value)}><option value="">All methods</option>{[...new Set(scopedItems.map(item=>item.method).filter(Boolean))].map(value=><option value={value} key={value}>{value}</option>)}</select>
        <select aria-label="Weight check result" value={weight} onChange={event=>setWeight(event.target.value)}><option value="">Any weight check</option><option value="passed">Passed</option><option value="flagged">Flagged</option><option value="failed">FAILED</option><option value="skipped">Skipped</option></select>
      </div></details></div>
      {!items?<Loading label="Loading review evidence..."/>:<div className="review-content">
        <div className="review-item-list">{filtered.length?filtered.map(item=><button key={item.id} className={`review-item ${selected?.id===item.id?'active':''}`} onClick={()=>navigateScoped(reviewURL(item.id,active))}><div className="row between"><StatusBadge tone={['human_confirmed','accepted','approved','reviewed'].includes(item.status)?'green':'amber'}>{titleCase(item.type)}</StatusBadge><ChevronRight size={14}/></div><strong>{englishText(item.title||item.target)}</strong><small>{item.part_key||item.target}</small><span className="review-item-status">{titleCase(item.status||'Waiting for review')}</span></button>):<div className="empty-inline"><ShieldCheck size={25}/><p>{scope?'No matching review items for this part.':'No items in this view.'}</p>{(filter||status||type||method||weight)&&<button className="text-button" onClick={clearFilters}>Clear filters</button>}{scope&&<button className="text-button" onClick={()=>navigate(scopedURL('/review/parts',scope))}>Inspect this part</button>}</div>}</div>
        <div className="review-item-detail">{selected?<>
          <header><div className="eyebrow">{titleCase(selected.type)} / {titleCase(selected.status)}</div><h2>{englishText(selected.title||selected.target)}</h2><details className="review-identifier"><summary>Field reference</summary><code>{selected.target}</code></details>{itemPartKey(selected)&&<div className="row wrap"><button className="text-button" onClick={()=>navigate(scopedURL('/review/parts',itemPartKey(selected)))}>Inspect part <ArrowUpRight size={13}/></button><button className="text-button" onClick={()=>navigate(scopedURL(`/review/part/${pathKey(itemPartKey(selected))}`,itemPartKey(selected)))}>Review whole design <ArrowUpRight size={13}/></button></div>}</header>
          <Evidence item={selected} navigate={navigateScoped}/>{selected.type==='possible_reading'&&<ReadingsDisclosure key={selected.id} item={selected}/>}
          <ReviewActions item={selected} navigate={navigateScoped} busy={busy} onAction={(...args)=>act(selected.id,...args)}/>
        </>:<div className="library-empty"><ShieldCheck size={36}/><h3>{route.item?'Item unavailable in this part scope':'Select an item to review'}</h3><p>{route.item?'Choose an item from the list or clear the part scope.':'Source evidence and AI readings will appear here.'}</p></div>}</div>
      </div>}
    </>}
  </div>;
}
