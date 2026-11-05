import React,{useEffect,useState} from 'react';
import {X,MessageSquare,Trash2} from 'lucide-react';
import {api} from '../api';
import {ErrorMessage,Loading} from '../components';

export default function ChatHistory({current,onOpen,onClose,onDeleted}) {
  const [chats,setChats]=useState(null),[error,setError]=useState(''),[deleting,setDeleting]=useState(null);
  useEffect(()=>{let live=true;api('/api/chats').then(data=>live&&setChats(data)).catch(e=>live&&setError(e.message));return()=>{live=false}},[]);
  const remove=async id=>{setDeleting(id);setError('');try{const res=await fetch(`/api/chats/${id}`,{method:'DELETE'});if(!res.ok)throw new Error('Could not delete this chat.');setChats(items=>items.filter(item=>item.id!==id));onDeleted?.(id)}catch(e){setError(e.message)}finally{setDeleting(null)}};
  return <div className="chat-history-scrim" onClick={onClose}><section className="chat-history-panel" role="dialog" aria-modal="true" aria-label="Past chats" onClick={e=>e.stopPropagation()}><header><h2>Past chats</h2><button className="icon-button" title="Close past chats" onClick={onClose}><X size={18}/></button></header>{error&&<ErrorMessage>{error}</ErrorMessage>}{!chats&&!error?<Loading label="Opening chats…"/>:chats?.length?<div className="saved-chat-list">{chats.map(chat=><div className={`saved-chat-row ${chat.id===current?'active':''}`} key={chat.id}><button className="saved-chat-open" disabled={Boolean(deleting)} onClick={()=>{onOpen(chat.id);onClose()}}><MessageSquare size={16}/><span><strong>{chat.title||'Untitled chat'}</strong><small>{new Date(chat.updated_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})} · {Math.floor(chat.message_count/2)} {chat.message_count===2?'exchange':'exchanges'}</small></span></button><button className="saved-chat-delete icon-button" disabled={Boolean(deleting)} title={`Delete chat: ${chat.title}`} onClick={()=>remove(chat.id)}><Trash2 size={14}/></button></div>)}</div>:<p className="no-saved-chats">Your saved conversations will appear here.</p>}</section></div>;
}
