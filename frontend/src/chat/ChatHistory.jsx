import React,{useEffect,useRef,useState} from 'react';
import {X,MessageSquare,Trash2} from 'lucide-react';
import {api} from '../api';
import {ErrorMessage,Loading} from '../components';

export default function ChatHistory({current,onOpen,onClose,onDeleted}) {
  const [chats,setChats]=useState(null),[error,setError]=useState(''),[deleting,setDeleting]=useState(null);
  const dialog=useRef(null),close=useRef(onClose);
  close.current=onClose;
  useEffect(()=>{
    const previous=document.activeElement, panel=dialog.current;
    const focusable=()=>[...panel.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')];
    (focusable()[0]||panel).focus();
    const keydown=event=>{
      if(event.key==='Escape'){event.preventDefault();close.current();return;}
      if(event.key!=='Tab')return;
      const items=focusable(),first=items[0],last=items.at(-1),active=document.activeElement;
      if(!first){event.preventDefault();panel.focus();return;}
      if(event.shiftKey&&(active===first||!panel.contains(active))){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&(active===last||!panel.contains(active))){event.preventDefault();first.focus();}
    };
    const focusin=event=>{if(!panel.contains(event.target))(focusable()[0]||panel).focus();};
    document.addEventListener('keydown',keydown);
    document.addEventListener('focusin',focusin);
    return()=>{document.removeEventListener('keydown',keydown);document.removeEventListener('focusin',focusin);if(previous?.isConnected)previous.focus();};
  },[]);
  useEffect(()=>{let live=true;api('/api/chats').then(data=>live&&setChats(data)).catch(e=>live&&setError(e.message));return()=>{live=false}},[]);
  const remove=async id=>{setDeleting(id);setError('');try{const res=await fetch(`/api/chats/${id}`,{method:'DELETE'});if(!res.ok)throw new Error('Could not delete this chat.');setChats(items=>items.filter(item=>item.id!==id));onDeleted?.(id)}catch(e){setError(e.message)}finally{setDeleting(null)}};
  return <div className="chat-history-scrim" onClick={onClose}><section ref={dialog} tabIndex={-1} className="chat-history-panel" role="dialog" aria-modal="true" aria-label="Past chats" onClick={e=>e.stopPropagation()}><header><h2>Past chats</h2><button className="icon-button" title="Close past chats" aria-label="Close past chats" onClick={onClose}><X size={18}/></button></header>{error&&<ErrorMessage>{error}</ErrorMessage>}{!chats&&!error?<Loading label="Opening chats…"/>:chats?.length?<div className="saved-chat-list">{chats.map(chat=><div className={`saved-chat-row ${chat.id===current?'active':''}`} key={chat.id}><button className="saved-chat-open" disabled={Boolean(deleting)} onClick={()=>{onOpen(chat.id);onClose()}}><MessageSquare size={16}/><span><strong>{chat.title||'Untitled chat'}</strong><small>{new Date(chat.updated_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})} · {Math.floor(chat.message_count/2)} {chat.message_count===2?'exchange':'exchanges'}</small></span></button><button className="saved-chat-delete icon-button" disabled={Boolean(deleting)} title={`Delete chat: ${chat.title}`} onClick={()=>remove(chat.id)}><Trash2 size={14}/></button></div>)}</div>:<p className="no-saved-chats">Your saved conversations will appear here.</p>}</section></div>;
}
