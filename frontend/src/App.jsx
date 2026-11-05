import React, {useEffect, useState} from 'react';
import {MessageSquare, Box, ShieldCheck, BookOpen, Settings2, ArrowUpRight, Layers, ChevronRight, ArrowLeft, ExternalLink} from 'lucide-react';
import {DebugContext} from './debug';
import Chat from './chat/Chat';
import Parts from './part/Parts';
import PartPage from './part/PartPage';
import Review from './review/Review';
import {api, pathKey, textValue} from './api';
import {ErrorMessage,Loading,StatusBadge} from './components';

function parseLocation() {
  const pathname=window.location.pathname,query=new URLSearchParams(window.location.search),state=window.history.state;
  const decode=s=>{try{return decodeURIComponent(s)}catch{return s}};
  let result={view:'chat'};
  if(pathname==='/parts')result={view:'parts'};
  else if(pathname.startsWith('/part/')){let path=decode(pathname.slice(6)),tab;const last=path.split('/').at(-1);if(['2d','3d','detail','debug','evidence','history'].includes(last)){tab=last;path=path.slice(0,-last.length-1)}result={view:'parts',part:{key:path,tab,fact:query.get('fact'),example:query.get('example')}}}
  else if(pathname.startsWith('/review')){const p=decode(pathname.slice(8)).split('/');result={view:'review',review:p[0]==='part'?{partKey:p.slice(1).join('/')}:{category:p[0]||'corrections',item:p.slice(1).join('/')}}}
  else if(pathname.startsWith('/readme'))result={view:'readme'};
  if(state?.panel&&result.part)result={...result,view:state.base?.startsWith('/review')?'review':'chat',panel:true,base:state.base,review:state.base?.startsWith('/review')?(()=>{const p=decode(state.base.slice(8)).split('/');return p[0]==='part'?{partKey:p.slice(1).join('/')}:{category:p[0]||'corrections',item:p.slice(1).join('/')}})():undefined};
  return result;
}

function ReadmePage({hash,navigate}) {
  const [data,setData]=useState(null),[error,setError]=useState('');
  useEffect(()=>{api('/api/readme').then(setData).catch(e=>setError(e.message))},[]);
  useEffect(()=>{if(data&&window.location.hash){setTimeout(()=>document.getElementById(decodeURIComponent(window.location.hash.slice(1)))?.scrollIntoView({behavior:'smooth',block:'center'}),50)}},[data,hash]);
  if(error)return <ErrorMessage>{error}</ErrorMessage>;if(!data)return <Loading label="Opening the source README…"/>;
  const passages=Array.isArray(data)?data:(data.passages||data.sections||[]);
  return <div className="readme-page"><header className="workspace-header"><div><span className="workspace-label">SOURCE DOCUMENT</span><h1>OpenLPBF README</h1></div><StatusBadge>ORIGINAL EVIDENCE</StatusBadge></header><div className="readme-layout"><aside><div className="eyebrow">CONTENTS</div>{passages.map((p,i)=><a key={i} href={`#${(p.name||p.id||`passage-${i}`).replace(/^README\//,'')}`}>{p.title||p.section||p.heading||`Passage ${i+1}`}<ChevronRight size={12}/></a>)}</aside><article><div className="document-note"><BookOpen size={19}/><span>Project context from the supplied README. Each passage has its own stable citation.</span></div>{passages.length?passages.map((p,i)=>{const id=(p.name||p.id||`passage-${i}`).replace(/^README\//,'');return <section id={id} className={decodeURIComponent(window.location.hash.slice(1))===id?'readme-passage highlighted':'readme-passage'} key={id}><h2>{p.title||p.section||p.heading||`Passage ${i+1}`}</h2><p>{p.text||p.content||p.says||textValue(p)}</p><a className="passage-citation" href={`#${id}`}><BookOpen size={12}/>{p.name||p.id||id}</a></section>}):<div className="readme-raw">{data.text||data.markdown||data.content||textValue(data)}</div>}</article></div></div>;
}

export default function App() {
  const [route,setRoute]=useState(parseLocation),[parts,setParts]=useState([]),[status,setStatus]=useState(null),[error,setError]=useState(''),[messages,setMessages]=useState([]),[session,setSession]=useState(null),[hash,setHash]=useState(window.location.hash);
  const refresh=()=>{api('/api/parts').then(d=>setParts(Array.isArray(d)?d:d.parts||[])).catch(e=>setError(e.message));api('/api/status').then(setStatus).catch(()=>{})};
  useEffect(()=>{refresh();const pop=()=>{setRoute(parseLocation());setHash(window.location.hash)};window.addEventListener('popstate',pop);window.addEventListener('hashchange',pop);return()=>{window.removeEventListener('popstate',pop);window.removeEventListener('hashchange',pop)}},[]);
  const navigate=(url,options={})=>{const current=window.history.state;const panel=options.panel || options.keepPanel&&current?.panel;const state=panel?{panel:true,base:current?.panel?current.base:window.location.pathname+window.location.search}:null;window.history[options.replace?'replaceState':'pushState'](state,'',url);setRoute(parseLocation());setHash(window.location.hash)};
  const resetChat=()=>{setMessages([]);setSession(null);navigate('/chat')};
  return <DebugContext.Provider value={Boolean(status?.debug_ui)}><div className="app-shell"><aside className="app-sidebar"><button className="brand-button" title="Meridian — new chat" onClick={resetChat}><span className="brand-glyph">m<span>·</span></span></button><div className="sidebar-rule"/><nav>{[[MessageSquare,'Chat','chat','/chat'],[Box,'Parts','parts','/parts'],[ShieldCheck,'Review','review','/review/corrections']].map(([Icon,label,id,url])=><button className={`sidebar-link ${route.view===id?'active':''}`} key={id} onClick={()=>navigate(url)} title={label}><Icon size={21}/><span>{label}</span></button>)}</nav><div className="sidebar-bottom"><button className={`sidebar-link ${route.view==='readme'?'active':''}`} onClick={()=>navigate('/readme')} title="Source README"><BookOpen size={20}/><span>README</span></button><div className="sidebar-rule"/><div className="profile-avatar" title={`Human reviewer: ${status?.reviewer_name || 'configured reviewer'}`}>{(status?.reviewer_name || 'Reviewer').split(/\s+/).map(w=>w[0]).slice(0,2).join('')}</div></div></aside><main className={`main-workspace ${route.panel?'with-panel':''}`}><div className="main-content">{route.view==='chat'?<Chat status={status} parts={parts} navigate={navigate} messages={messages} setMessages={setMessages} session={session} setSession={setSession} resetChat={resetChat} compact={route.panel}/>:route.view==='parts'?<Parts parts={parts} selected={route.part} navigate={navigate}/>:route.view==='review'?<Review route={route.review||{}} navigate={navigate} onChanged={refresh}/>:<ReadmePage hash={hash} navigate={navigate}/>}</div>{route.panel&&<aside className="part-side-panel"><PartPage partKey={route.part.key} initialTab={route.part.tab} factId={route.part.fact} example={route.part.example} compact navigate={navigate} onClose={()=>navigate(route.base||'/chat',{replace:true})}/></aside>}</main>{error&&<div className="connection-error"><ErrorMessage retry={()=>{setError('');refresh()}}>{error}</ErrorMessage></div>}</div></DebugContext.Provider>;
}
