import React, {useEffect, useRef, useState} from 'react';
import {MessageSquare, Box, ShieldCheck, BookOpen, Settings2, ArrowUpRight, Layers, ChevronRight, ArrowLeft, ExternalLink} from 'lucide-react';
import {DebugContext} from './debug';
import {Button} from './components/ui/button';
import Chat from './chat/Chat';
import Parts from './part/Parts';
import PartPage from './part/PartPage';
import Review from './review/Review';
import {api, pathKey, textValue} from './api';
import {ErrorMessage,Loading,StatusBadge} from './components';

function parseReviewLocation(location) {
  const url=new URL(location,window.location.origin);
  let path=url.pathname.slice(8);try{path=decodeURIComponent(path)}catch{}
  const p=path.split('/');
  return {view:'review',review:{...(p[0]==='part'?{partKey:p.slice(1).join('/')}:{category:p[0]||'parts',item:p.slice(1).join('/')}),partFilter:url.searchParams.get('part')}};
}

function parseLocation() {
  const pathname=window.location.pathname,query=new URLSearchParams(window.location.search),state=window.history.state;
  const decode=s=>{try{return decodeURIComponent(s)}catch{return s}};
  let result={view:'chat'};
  if(pathname.startsWith('/chat/'))result={view:'chat',chatId:decode(pathname.slice(6))};
  else if(pathname==='/parts')result={view:'parts'};
  else if(pathname.startsWith('/part/')){let path=decode(pathname.slice(6)),tab;const last=path.split('/').at(-1);if(['2d','3d','detail','debug','evidence','history'].includes(last)){tab=last;path=path.slice(0,-last.length-1)}result={view:'parts',part:{key:path,tab,fact:query.get('fact'),example:query.get('example')}}}
  else if(pathname.startsWith('/review'))result=parseReviewLocation(pathname+window.location.search);
  else if(pathname.startsWith('/readme'))result={view:'readme'};
  if(state?.panel&&result.part)result={...result,view:state.base?.startsWith('/review')?'review':'chat',panel:true,base:state.base,review:state.base?.startsWith('/review')?parseReviewLocation(state.base).review:undefined};
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
  const [route,setRoute]=useState(parseLocation),[parts,setParts]=useState([]),[status,setStatus]=useState(null),[error,setError]=useState(''),[messages,setMessages]=useState([]),[session,setSession]=useState(null),[hash,setHash]=useState(window.location.hash),[chatLoading,setChatLoading]=useState(false),[chatEpoch,setChatEpoch]=useState(0);
  const seenRevision=useRef(null);
  const acceptStatus=data=>{if(seenRevision.current&&seenRevision.current!==data.revision){api('/api/parts').then(d=>setParts(Array.isArray(d)?d:d.parts||[])).catch(()=>{});window.dispatchEvent(new CustomEvent('meridian:revision',{detail:data.revision}))}seenRevision.current=data.revision;setStatus(data)};
  useEffect(()=>{let pending=false;const poll=async()=>{if(document.hidden||pending)return;pending=true;try{acceptStatus(await api('/api/status'))}catch{}finally{pending=false}};const timer=setInterval(poll,10000);document.addEventListener('visibilitychange',poll);return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',poll)}},[]);
  const refresh=()=>{api('/api/parts').then(d=>setParts(Array.isArray(d)?d:d.parts||[])).catch(e=>setError(e.message));api('/api/status').then(acceptStatus).catch(()=>{})};
  useEffect(()=>{refresh();const pop=()=>{setRoute(parseLocation());setHash(window.location.hash)};window.addEventListener('popstate',pop);window.addEventListener('hashchange',pop);return()=>{window.removeEventListener('popstate',pop);window.removeEventListener('hashchange',pop)}},[]);
  const navigate=(url,options={})=>{const current=window.history.state;const panel=options.panel || options.keepPanel&&current?.panel;const state=panel?{panel:true,base:current?.panel?current.base:window.location.pathname+window.location.search}:null;window.history[options.replace?'replaceState':'pushState'](state,'',url);setRoute(parseLocation());setHash(window.location.hash)};
  const resetChat=()=>{setChatEpoch(n=>n+1);setChatLoading(false);setMessages([]);setSession(null);navigate('/chat')};
  const openChat=id=>navigate(`/chat/${id}`);
  const savedSession=id=>{setSession(id);if(route.view==='chat'&&!route.panel)navigate(`/chat/${id}`,{replace:true});else if(route.panel&&window.history.state?.base?.startsWith('/chat'))window.history.replaceState({...window.history.state,base:`/chat/${id}`},'',window.location.href)};
  useEffect(()=>{if(!route.chatId){setChatLoading(false);return}if(route.chatId===session)return;let live=true;setChatLoading(true);api(`/api/chats/${encodeURIComponent(route.chatId)}`).then(chat=>{if(!live)return;setSession(chat.id);setMessages(chat.messages.map(message=>message.role==='user'?{role:'user',text:message.content}:{role:'assistant',...message.response,text:message.content}))}).catch(e=>live&&setError(e.message)).finally(()=>live&&setChatLoading(false));return()=>{live=false}},[route.chatId]);
  return <DebugContext.Provider value={Boolean(status?.debug_ui)}><div className={`app-shell meridian-workspace embedder-workspace ${route.view==='review'?'engineering-workspace':''}`}><header className="app-topbar"><button className="topbar-brand" title="Meridian - new chat" onClick={resetChat}><svg className="meridian-emblem" width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true"><path d="M3 22V4h4l6 9 6-9h4v18M3 4h4M19 4h4M3 22h5m10 0h5" stroke="currentColor" strokeWidth="1.7"/></svg><span>MERIDIAN</span></button><nav aria-label="Main navigation">{[[MessageSquare,'Chat','chat',session?`/chat/${session}`:'/chat'],[Box,'Parts','parts','/parts'],...(status?.debug_ui?[[ShieldCheck,'Debug','review','/review/parts']]:[])].map(([Icon,label,id,url])=><Button variant="ghost" className={`topbar-link ${route.view===id?'active':''}`} aria-current={route.view===id?'page':undefined} key={id} onClick={()=>navigate(url)} title={label}><Icon size={15}/><span>{label}</span></Button>)}</nav><div className="topbar-end"><span className="topbar-project">OPENLPBF <span>/ V2</span></span><Button variant="ghost" className={`topbar-source ${route.view==='readme'?'active':''}`} aria-current={route.view==='readme'?'page':undefined} onClick={()=>navigate('/readme')} title="Source README"><BookOpen size={14}/><span>Source README</span><ArrowUpRight size={12}/></Button>{status?.debug_ui&&<span className="topbar-engineer" title={`Reviewer: ${status?.reviewer_name || 'configured reviewer'}`}>ENGINEERING</span>}</div></header><main className={`main-workspace ${route.panel?'with-panel':''}`}><div className="main-content">{route.view==='chat'?<Chat key={chatEpoch} loading={chatLoading} openChat={openChat} status={status} parts={parts} navigate={navigate} messages={messages} setMessages={setMessages} session={session} setSession={savedSession} resetChat={resetChat} compact={route.panel}/>:route.view==='parts'?<Parts parts={parts} selected={route.part} navigate={navigate}/>:route.view==='review'?<Review route={route.review||{}} navigate={navigate} onChanged={refresh}/>:<ReadmePage hash={hash} navigate={navigate}/>}</div>{route.panel&&<aside className="part-side-panel"><PartPage partKey={route.part.key} initialTab={route.part.tab} factId={route.part.fact} example={route.part.example} compact navigate={navigate} onClose={()=>navigate(route.base||'/chat',{replace:true})}/></aside>}</main>{error&&<div className="connection-error"><ErrorMessage retry={()=>{setError('');refresh()}}>{error}</ErrorMessage></div>}</div></DebugContext.Provider>;
}
