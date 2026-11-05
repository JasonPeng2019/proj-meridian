import React,{useEffect,useState} from 'react';
import {X,MessageSquare,Trash2} from 'lucide-react';
import {api} from '../api';
import {ErrorMessage,Loading} from '../components';
import {Button} from '../components/ui/button';
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription,DialogClose} from '../components/ui/dialog';

export default function ChatHistory({current,onOpen,onClose,onDeleted}) {
  const [chats,setChats]=useState(null),[error,setError]=useState(''),[deleting,setDeleting]=useState(null);
  useEffect(()=>{let live=true;api('/api/chats').then(data=>live&&setChats(data)).catch(e=>live&&setError(e.message));return()=>{live=false}},[]);
  const remove=async id=>{setDeleting(id);setError('');try{const res=await fetch(`/api/chats/${id}`,{method:'DELETE'});if(!res.ok)throw new Error('Could not delete this chat.');setChats(items=>items.filter(item=>item.id!==id));onDeleted?.(id)}catch(e){setError(e.message)}finally{setDeleting(null)}};
  return <Dialog open onOpenChange={open=>{if(!open)onClose()}}>
    <DialogContent className="chat-history-panel chat-history-dialog" overlayClassName="chat-history-scrim" showCloseButton={false}>
      <DialogHeader className="chat-history-heading">
        <div><DialogTitle>Past chats</DialogTitle><DialogDescription>Return to a saved conversation.</DialogDescription></div>
        <DialogClose asChild><Button variant="ghost" size="icon" className="icon-button" title="Close past chats" aria-label="Close past chats"><X size={18}/></Button></DialogClose>
      </DialogHeader>
      {error&&<ErrorMessage>{error}</ErrorMessage>}
      {!chats&&!error?<Loading label="Opening chats…"/>:chats?.length?<div className="saved-chat-list">{chats.map(chat=><div className={`saved-chat-row ${chat.id===current?'active':''}`} key={chat.id}>
        <button className="saved-chat-open" disabled={Boolean(deleting)} onClick={()=>{onOpen(chat.id);onClose()}}><MessageSquare size={17}/><span><strong>{chat.title||'Untitled chat'}</strong><small>{new Date(chat.updated_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})} · {Math.floor(chat.message_count/2)} {chat.message_count===2?'exchange':'exchanges'}{chat.id===current&&<span className="saved-chat-current">Current</span>}</small></span></button>
        <Button variant="ghost" size="icon" className="saved-chat-delete icon-button" disabled={Boolean(deleting)} title={`Delete chat: ${chat.title}`} aria-label={`Delete chat: ${chat.title||'Untitled chat'}`} onClick={()=>remove(chat.id)}><Trash2 size={15}/></Button>
      </div>)}</div>:<div className="no-saved-chats"><MessageSquare size={24}/><p>Your saved conversations will appear here.</p></div>}
    </DialogContent>
  </Dialog>;
}
