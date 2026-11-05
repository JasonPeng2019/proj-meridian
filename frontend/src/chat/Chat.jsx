import ChatHistory from './ChatHistory';
import {englishName,englishText} from '../language';
import {useDebug, sourceBadge} from '../debug';
import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {ArrowUp, ArrowUpRight, Box, FileText, Plus, AlertTriangle, Check, Copy, Layers, Search, History, LoaderCircle} from 'lucide-react';
import {Button} from '../components/ui/button';
import {api, pathKey, partKey, partURL, imageURL, reviewURL, textValue} from '../api';
import {ErrorMessage, JsonDetails} from '../components';

function factKey(name,fact) { return fact?.part_key || fact?.sources?.find(s=>s.part_key)?.part_key || (name.startsWith('BOM:')?partKey({id:name.replace(/\/[^/]+$/,'/part')}):name.split('/')[0]); }
function sourceName(name) { return name?.startsWith('BOM:')?'Parts list':name?.startsWith('README/')?'README':name?.split('/')[0]||'Source'; }
function openSource(name,fact,navigate,source) {
  if(name.startsWith('README/')) {navigate(`/readme#${name.slice(7)}`);return;}
  if(name.startsWith('names/')) {navigate(reviewURL(name));return;}
  const s=source||fact?.sources?.[0], key=s?.part_key||factKey(name,fact);
  navigate(partURL(key,name.startsWith('BOM:') || s?.name?.startsWith('BOM:')?'detail':name.endsWith('/part')?undefined:'2d',{fact:s?.name||name}),{panel:true});
}

function FloatingEvidence({anchor,children,onEnter,onLeave}) {
  const popup=useRef(null),[position,setPosition]=useState({visibility:'hidden'});
  useLayoutEffect(()=>{
    const update=()=>{if(!anchor.current||!popup.current)return;const rect=anchor.current.getBoundingClientRect(),height=Math.min(popup.current.offsetHeight,window.innerHeight-24),width=Math.min(340,window.innerWidth-24);const left=Math.min(Math.max(12,rect.left-8),window.innerWidth-width-12);const below=rect.bottom+8;const top=below+height<window.innerHeight-12?below:Math.max(12,rect.top-height-8);setPosition({position:'fixed',left,top,bottom:'auto',width,maxHeight:Math.min(500,window.innerHeight-24),visibility:'visible'})};
    update();const observer=new ResizeObserver(update);observer.observe(popup.current);window.addEventListener('resize',update);return()=>{observer.disconnect();window.removeEventListener('resize',update)};
  },[]);
  return createPortal(<span className="citation-popover floating-evidence chat-evidence" ref={popup} style={position} onMouseEnter={onEnter} onMouseLeave={onLeave} onFocus={onEnter} onBlur={onLeave}>{children}</span>,document.body);
}

function Citation({names,facts,navigate,undetermined=false}) {
  const debug=useDebug();
  const [open,setOpen]=useState(false), [cropErrors,setCropErrors]=useState({});
  const anchor=useRef(null),timer=useRef(null);
  const keepOpen=()=>{clearTimeout(timer.current);setOpen(true)},closeSoon=()=>{clearTimeout(timer.current);timer.current=setTimeout(()=>setOpen(false),160)};
  useEffect(()=>()=>clearTimeout(timer.current),[]);
  const showSource=(name,fact,source)=>{setOpen(false);openSource(name,fact,navigate,source)};
  const valid=names.length>0 && names.every(n=>facts[n]) && (!undetermined || names.every(n=>facts[n]?.display?.state==='undetermined'));
  const first=names[0], firstFact=facts[first];
  const label=undetermined?'Undetermined':`${sourceName(first)}${names.length>1?` +${names.length-1}`:''}`;
  return <span className="citation-wrap" onMouseEnter={keepOpen} onMouseLeave={closeSoon}><button ref={anchor} className={`citation ${undetermined?'uncertain':''} ${valid?'':'invalid'}`} onFocus={keepOpen} onBlur={closeSoon} onClick={()=>valid?showSource(first,firstFact):setOpen(!open)}>{!valid&&<AlertTriangle size={11}/>} {valid?label:'Invalid source'}{!undetermined&&<ArrowUpRight size={10}/>}</button>{open&&<FloatingEvidence anchor={anchor} onEnter={keepOpen} onLeave={closeSoon}><span className="popover-eyebrow">{valid?'SOURCE EVIDENCE':'CITATION WARNING'}</span>{!valid?<span className="block">This marker does not refer to a fact returned in this conversation{undetermined?', or the fact was not returned as Undetermined':''}.</span>:names.map(name=>{const fact=facts[name],sources=fact.sources?.length?fact.sources:[{name,says:fact.display?.value}];return <span className="citation-fact" key={name}>{undetermined&&<span className="uncertain-message">{fact.display?.message || 'The sources could not determine this value.'}</span>}{sources.map((s,i)=>{const key=s.part_key||factKey(name,fact);const cropKey=`${name}-${i}`;return <span className="popover-source" key={cropKey}><button className="source-open" onClick={()=>showSource(name,fact,s)}><FileText size={14}/><strong>{sourceName(s.name||name)}{s.page?` · sheet ${s.page}`:''}</strong><ArrowUpRight size={13}/></button><code>{s.name||name}</code><span className="verbatim">{s.says===null||s.says===undefined?'No extracted source text. See the original drawing.':englishText(textValue(s.says))}</span><span className="fact-badge">{sourceBadge(s.badge || fact.badge || s.method,debug)}</span>{s.box&&!cropErrors[cropKey]&&<img className="source-crop" src={`/api/parts/${pathKey(key)}/crop?fact=${encodeURIComponent(s.name||name)}`} alt="Crop of the cited drawing field" onError={()=>setCropErrors(e=>({...e,[cropKey]:true}))}/>}</span>})}{fact.snapshot_note&&<span className="snapshot-note">Recorded in the snapshot, may be out of date.</span>}</span>})}</FloatingEvidence>}</span>;
}

function inlineFormat(text,navigate,key) { return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\)]+\))/g).map((s,i)=>s.startsWith('**')?<strong key={`${key}-${i}`}>{s.slice(2,-2)}</strong>:s.startsWith('`')?<code key={`${key}-${i}`}>{s.slice(1,-1)}</code>:/^\[.*\]\(.*\)$/.test(s)?(()=>{const m=s.match(/^\[(.*)\]\((.*)\)$/);return m[2].startsWith('/')?<button className="inline-link" key={`${key}-${i}`} onClick={()=>navigate(m[2])}>{m[1]}</button>:/^https?:\/\//.test(m[2])?<a key={`${key}-${i}`} href={m[2]} target="_blank" rel="noreferrer">{m[1]}</a>:m[1]})():s); }

function AnswerText({text,facts,navigate}) {
  const render=content=>content.split(/(\[(?:cite|undetermined):[^\]]+\])/g).map((token,i)=>{const m=token.match(/^\[(cite|undetermined):\s*([^\]]+)\]$/);if(!m)return <React.Fragment key={i}>{inlineFormat(token,navigate,i)}</React.Fragment>;const names=m[2].split(',').map(s=>s.trim()).filter(Boolean);return <Citation key={i} names={names} facts={facts} navigate={navigate} undetermined={m[1]==='undetermined'}/>});
  const paragraphs=text.split(/\n\s*\n/),short=text.length>1000&&paragraphs.length>2;
  const lead=short?paragraphs.slice(0,2).join('\n\n'):text,rest=short?paragraphs.slice(2).join('\n\n'):'';
  return <div className="answer-text">{render(lead)}{rest&&<details className="answer-more"><summary>More detail</summary><div>{render(rest)}</div></details>}</div>;
}

function PartCards({parts,navigate}) {
  if(!parts?.length)return null;
  if(parts.length>=4)return <details className="attached-list"><summary><Layers size={13}/>{parts.length} referenced parts</summary>{parts.map(p=><button key={p.id} onClick={()=>navigate(partURL(partKey(p)),{panel:true})}><Box size={16}/><span>{englishName(p.display_name)}<small>{partKey(p)}</small></span><span className="muted">{p.has_3d?'2D + 3D':p.has_drawing?'2D drawing':'Parts list'}</span><ArrowUpRight size={14}/></button>)}</details>;
  return <div className="attached-parts"><div className="attachment-label"><Layers size={13}/> Attached evidence</div><div className="part-card-grid">{parts.map(p=><button className="attached-card" key={p.id||p.key} onClick={()=>navigate(partURL(partKey(p)),{panel:true})}>{p.thumbnail || p.has_drawing?<div className="attached-thumbnail"><img src={p.thumbnail||imageURL(partKey(p),1,true)} alt={`${englishName(p.display_name)} drawing`}/></div>:<div className="attached-thumbnail no-drawing"><Box size={27}/></div>}<div className="attached-card-title"><strong>{englishName(p.display_name)}</strong><small>{partKey(p)} · {p.has_3d?'2D + 3D':p.has_drawing?'2D drawing':'Parts list'}</small></div><ArrowUpRight size={15}/></button>)}</div></div>;
}

function Message({message,navigate}) {
  const [copied,setCopied]=useState(false),[debugOpen,setDebugOpen]=useState(false);
  const debug=useDebug();
  if(message.role==='user') return <div className="user-message"><div>{message.text}</div><span className="user-avatar" aria-label="You">JP</span></div>;
  return <article className="assistant-message">
    <div className="assistant-avatar" aria-hidden="true"><Layers size={17}/></div>
    <div className="assistant-body">
      <div className="assistant-label">Meridian</div>
      {message.warnings?.length?<div className="answer-text muted">Unavailable</div>:<AnswerText text={message.text} facts={message.facts||{}} navigate={navigate}/>}
      <PartCards parts={message.parts_to_show} navigate={navigate}/>
      {debug&&<details className="answer-debug" open={debugOpen} onToggle={e=>setDebugOpen(e.currentTarget.open)}><summary>Debug</summary>{debugOpen&&<JsonDetails value={{answer:message.text,warnings:message.warnings,usage:message.usage,latency_ms:message.latency_ms,tools:message.tool_trace,facts:message.facts}}/>}</details>}
      <div className="answer-tools"><Button variant="ghost" size="sm" title="Copy answer" aria-label={copied?'Answer copied':'Copy answer'} onClick={async()=>{try{await navigator.clipboard.writeText(message.warnings?.length?'Unavailable':message.text);setCopied(true);setTimeout(()=>setCopied(false),1500)}catch{setCopied(false)}}}>{copied?<Check size={14}/>:<Copy size={14}/>}<span>{copied?'Copied':'Copy'}</span></Button></div>
    </div>
  </article>;
}

const prompts=[{icon:Box,title:'Explore a part',question:'What is the recoater plate made of?'},{icon:Search,title:'Check the evidence',question:'What do the sources say about the build plate material?'},{icon:FileText,title:'Review a drawing',question:'What is D-019? Show the original title and note.'}];
export default function Chat({status,parts,navigate,messages,setMessages,session,setSession,resetChat,compact,openChat,loading}) {
  const [input,setInput]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[historyOpen,setHistoryOpen]=useState(false);
  const live=useRef(true);
  useEffect(()=>{live.current=true;return()=>{live.current=false}},[]);
  useEffect(()=>{setInput('');setError('')},[session]);
  const bottom=useRef(null),textarea=useRef(null),historyTrigger=useRef(null);
  const closeHistory=()=>{setHistoryOpen(false);requestAnimationFrame(()=>historyTrigger.current?.focus())};
  useEffect(()=>{bottom.current?.scrollIntoView({behavior:'smooth'})},[messages,busy]);
  const send=async text=>{const question=(text||input).trim();if(!question||busy||loading)return;setInput('');setError('');setMessages(m=>[...m,{role:'user',text:question}]);setBusy(true);try{const result=await api('/api/chat',{message:question,...(session?{session_id:session}:{})});if(!live.current)return;setSession(result.session_id);setMessages(m=>[...m,{role:'assistant',...result}]);}catch(e){if(live.current){setError(e.message);setInput(question)}}finally{if(live.current){setBusy(false);textarea.current?.focus()}}};
  const noKey=status?.chat_available===false;
  return <div className={`chat-page workspace-chat ${compact?'chat-split':''}`}>
    <header className="workspace-header">
      <div><h1>Engineering chat</h1><p className="chat-project-name">OpenLPBF v2</p></div>
      <div className="chat-header-actions">
        <Button ref={historyTrigger} variant="ghost" size="sm" disabled={busy||loading} onClick={()=>setHistoryOpen(true)}><History size={15}/>Past chats</Button>
        <Button variant="outline" size="sm" disabled={busy||loading} className="new-chat" aria-label="New chat" onClick={()=>{resetChat();setError('');setInput('')}}><Plus size={15}/><span>New chat</span></Button>
      </div>
    </header>
    {historyOpen&&<ChatHistory current={session} onOpen={openChat} onClose={closeHistory} onDeleted={id=>{if(id===session)resetChat()}}/>}
    <div className="chat-scroll" aria-busy={busy||loading}>
      {loading?<div className="empty-state" role="status"><LoaderCircle className="chat-spinner" size={20}/>Opening conversation…</div>:messages.length===0?<div className="chat-welcome">
        <div className="welcome-symbol" aria-hidden="true"><Layers size={24}/></div>
        <h2>Ask about your machine.</h2>
        <p>Find part details and trace answers to the original drawings.</p>
        <div className="welcome-context"><FileText size={14}/>OpenLPBF v2 drawings & parts list</div>
        <div className="starter-prompts">{prompts.map(({icon:Icon,title,question})=><Button variant="outline" disabled={noKey||busy} key={title} onClick={()=>send(question)}><Icon size={18}/><strong>{title}</strong><span>{question}</span><ArrowUpRight size={15}/></Button>)}</div>
      </div>:<div className="message-column">
        {messages.map((m,i)=><Message key={i} message={m} navigate={navigate}/>)}
        {busy&&<div className="assistant-message" role="status"><div className="assistant-avatar" aria-hidden="true"><Layers size={17}/></div><div className="thinking"><LoaderCircle className="chat-spinner" size={15}/>Checking source evidence…</div></div>}
        <div ref={bottom}/>
      </div>}
    </div>
    <div className="composer-area">
      {error&&<ErrorMessage>{error}</ErrorMessage>}
      {noKey&&<div className="notice info"><InfoIcon/>Add an API key to use the chat. Parts, drawings, 3D models and review remain available.</div>}
      <form className={`composer ${busy?'busy':''}`} onSubmit={e=>{e.preventDefault();send()}}>
        <label className="chat-sr-only" htmlFor="engineering-chat-question">Message Meridian</label>
        <textarea id="engineering-chat-question" ref={textarea} value={input} disabled={noKey||loading} rows={2} placeholder={noKey?'Add an API key to use the chat.':'Ask about a part, material, drawing, or connection…'} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}}/>
        <div className="composer-bottom"><span className="context-chip"><Layers size={13}/>OpenLPBF v2</span><Button className="send-button" size="icon" type="submit" disabled={!input.trim()||busy||noKey||loading} title="Send message" aria-label="Send message"><ArrowUp size={18}/></Button></div>
      </form>
      <div className="composer-footer"><span>{noKey?'Chat unavailable':'Answers linked to source evidence'}</span><span>Enter to send · Shift + Enter for a new line</span></div>
    </div>
  </div>;
}
function InfoIcon(){return <AlertTriangle size={16}/>}
