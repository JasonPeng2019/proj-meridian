import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { ChatProps, ConversationDetail, ConversationSummary, PartAttachment, PartViewTab } from "../contracts";
import { Evidence } from "./Evidence";

// Selection/URL and the adjacent part panel belong to the shell. Only server
// snapshots live here; no client context window or citation ledger is constructed.
export function Chat(props: ChatProps) {
  const { api, selected_conversation_id: selected, on_select_conversation } = props;
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [listing, setListing] = useState(true);
  const [listError, setListError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(false);
  const listVersion = useRef(0);
  const actionVersion = useRef(0);
  const current = useRef(selected);
  const alive = useRef(false);
  // Layout cleanup also invalidates retained source/part callbacks at commit.
  useLayoutEffect(() => {
    alive.current = true;
    return () => { alive.current = false; listVersion.current++; actionVersion.current++; };
  }, [api]);
  useLayoutEffect(() => {
    current.current = selected;
    actionVersion.current++;
    setCreating(false); setCreateError(false);
  }, [selected, api]);

  async function refresh() {
    const version = ++listVersion.current;
    setListing(true); setListError(false);
    try {
      const result = await api.conversations();
      if (!alive.current || version !== listVersion.current) return;
      setHistory([...result.conversations].sort((a, b) =>
        Date.parse(b.updated_at) - Date.parse(a.updated_at) || a.conversation_id.localeCompare(b.conversation_id)));
    } catch {
      if (alive.current && version === listVersion.current) setListError(true);
    } finally {
      if (alive.current && version === listVersion.current) setListing(false);
    }
  }
  useEffect(() => { void refresh(); }, [api]);

  function select(id: string) {
    actionVersion.current++;
    setCreating(false); setCreateError(false);
    on_select_conversation(id);
  }
  async function create() {
    if (creating) return;
    const version = ++actionVersion.current;
    setCreating(true); setCreateError(false);
    try {
      const detail = await api.create_conversation({});
      if (!alive.current || version !== actionVersion.current) return;
      // Never invent a local ID or select a placeholder conversation.
      on_select_conversation(detail.conversation.conversation_id);
      void refresh();
    } catch {
      if (alive.current && version === actionVersion.current) setCreateError(true);
    } finally {
      if (alive.current && version === actionVersion.current) setCreating(false);
    }
  }

  return <div className="meridian-chat">
    <ChatStyles />
    <aside className="mc-history" aria-label="Past chats">
      <div className="mc-history-heading"><h2>Past chats</h2>
        <button type="button" onClick={() => void create()} disabled={creating}>{creating ? "Creating…" : "New chat"}</button></div>
      {createError && <p role="alert">Could not create a chat. Try New chat again.</p>}
      <button type="button" className="mc-refresh" onClick={() => void refresh()} disabled={listing}>Refresh chats</button>
      {listing && <p role="status" className="mc-muted">Loading chats…</p>}
      {listError && <p role="alert">Could not load past chats. Use Refresh chats to try again.</p>}
      {!listing && !listError && history.length === 0 && <p className="mc-muted">Your saved chats will appear here.</p>}
      <ul>{history.map(item => <li key={item.conversation_id}>
        <button type="button" aria-current={selected === item.conversation_id ? "true" : undefined}
          onClick={() => select(item.conversation_id)}>
          <span className="mc-title">{item.title || "New chat"}</span>
          <time dateTime={item.updated_at}>{displayDate(item.updated_at)}</time>
        </button>
      </li>)}</ul>
    </aside>
    <Thread key={selected ?? "no-selection"} {...props} on_changed={() => void refresh()}
      is_current={() => alive.current && current.current === selected} />
  </div>;
}

function displayDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function Thread({ api, status, selected_conversation_id: id, on_open_part, on_open_source,
  debug, on_changed, is_current }: ChatProps & { on_changed: () => void; is_current: () => boolean }) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(Boolean(id));
  const [readError, setReadError] = useState(false);
  const [sendError, setSendError] = useState(false);
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState("");
  const alive = useRef(false);
  const lifecycle = useRef(0);
  const version = useRef(0);
  const sendLock = useRef(false);
  const composerId = useId();
  const canAct = () => alive.current && is_current();
  useLayoutEffect(() => {
    alive.current = true;
    lifecycle.current++;
    sendLock.current = false;
    setSending(false);
    return () => { alive.current = false; lifecycle.current++; version.current++; };
  }, [api]);

  async function read() {
    if (!id) return;
    const request = ++version.current;
    setLoading(true); setReadError(false);
    try {
      const result = await api.conversation({ conversation_id: id });
      if (!canAct() || request !== version.current) return;
      if (result.conversation.conversation_id !== id || result.messages.some(item =>
        item.role === "assistant" && item.response.conversation_id != null && item.response.conversation_id !== id)) {
        throw new Error("Wrong conversation");
      }
      setDetail(result);
    } catch {
      if (canAct() && request === version.current) { setDetail(null); setReadError(true); }
    } finally {
      if (canAct() && request === version.current) setLoading(false);
    }
  }
  useEffect(() => { setDetail(null); void read(); }, [api, id]);

  const missingKey = status.chat_state === "missing_key";
  const available = status.chat_available && !missingKey;
  async function send() {
    const message = draft.trim();
    if (!id || !message || !available || !detail || loading || sendLock.current || !canAct()) return;
    const session = lifecycle.current;
    const currentSend = () => canAct() && session === lifecycle.current;
    sendLock.current = true;
    setSending(true); setSendError(false);
    try {
      // The server owns all history, tool context and citation authorization.
      const result = await api.send_conversation({ conversation_id: id }, { message });
      if (!currentSend()) return;
      if (result.conversation.conversation_id !== id || result.messages.some(item =>
        item.role === "assistant" && item.response.conversation_id != null && item.response.conversation_id !== id)) {
        throw new Error("Wrong conversation");
      }
      setDraft("");
      await read(); // Reload the full saved thread, including messages beyond the model window.
      if (currentSend()) on_changed();
    } catch {
      if (!currentSend()) return;
      setSendError(true);
      // A failed request may have persisted its user message. Show server truth
      // before offering another send, without inventing an assistant response.
      await read();
      if (currentSend()) on_changed();
    } finally {
      if (currentSend()) { sendLock.current = false; setSending(false); }
    }
  }
  const messages = detail && detail.conversation.conversation_id === id ? detail.messages : [];
  return <section className="mc-thread" aria-label="Selected chat">
    <header className="mc-thread-heading"><h2>{detail?.conversation.title || (id ? "Saved chat" : "Start a conversation")}</h2>
      <p className="mc-muted">{id ? "Saved messages and their sources." : "Choose a past chat or create a new one."}</p></header>
    {!available && <p className="mc-notice" role="status">{missingKey
      ? "Chat is unavailable because the server API key is missing. Configure the chat key on the server to ask questions. You can still read saved chats and browse Parts."
      : "Sending is unavailable right now. You can still create and read saved chats, or browse Parts."}</p>}
    <div className="mc-messages" aria-busy={loading}>
      {loading && <p role="status">Loading saved messages…</p>}
      {readError && <div role="alert"><p>Could not open this saved chat. Try again or select another chat.</p>
        <button type="button" onClick={() => void read()} disabled={loading}>Retry saved chat</button></div>}
      {!loading && detail && messages.length === 0 && <p className="mc-muted">No messages yet.</p>}
      {messages.map(message => <article key={message.id} className={`mc-message mc-${message.role}`} aria-label={message.role === "user" ? "Your message" : "Meridian answer"}>
        <div className="mc-message-heading"><strong>{message.role === "user" ? "You" : "Meridian"}</strong>
          <time dateTime={message.created_at}>{displayDate(message.created_at)}</time></div>
        {message.role === "user" ? <p className="mc-text">{message.text}</p> : <>
          <Evidence response={message.response} debug={debug} on_open_source={target => {
            if (id && canAct()) on_open_source(target, id);
          }} />
          {message.response.parts_to_show.length > 0 && <ul className={`mc-attachments${message.response.attachment_layout === "list" ? " mc-compact" : ""}`} aria-label="Attached parts">
            {message.response.parts_to_show.map(part => <li key={part.id}>
              <strong>{part.display_name}</strong>
              <div className="mc-part-actions"><button type="button" onClick={() => open(part, "detail")}>Open part</button>
                {part.has_drawing && <button type="button" onClick={() => open(part, "drawing")}>Drawing</button>}
                {part.has_3d && (part.model_state === "available" || part.model_state === "stale") &&
                  part.examples.map(example => <button type="button" key={example} onClick={() => open(part, "model", example)}>
                    3D{part.examples.length > 1 ? ` · ${example}` : ""}
                  </button>)}</div>
              {part.has_3d && (part.model_state === "available" || part.model_state === "stale") && <small>Reconstruction, not original CAD</small>}
            </li>)}
          </ul>}
        </>}
      </article>)}
    </div>
    <form className="mc-composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      <label htmlFor={composerId}>Your question</label>
      <textarea id={composerId} rows={3} value={draft} onChange={event => setDraft(event.target.value)}
        disabled={!id || !detail || loading || sending || !available} placeholder="Ask about a part or its sources…" />
      {sendError && <p role="alert">Could not send your question. Check the saved messages before trying again.</p>}
      <div className="mc-send-row"><p className="mc-muted">{sending ? "Sending…" : "Answers link to their available sources."}</p>
        <button type="submit" disabled={!id || !detail || loading || sending || !available || !draft.trim()}>Send</button></div>
    </form>
  </section>;

  function open(part: PartAttachment, tab: PartViewTab, example?: PartAttachment["examples"][number]) {
    if (id && canAct()) on_open_part({ conversation_id: id, part_id: part.id, tab, highlights: part.highlights, example });
  }
}

function ChatStyles() {
  return <style>{`
    .meridian-chat { display: flex; flex-wrap: wrap; gap: 24px; color: #172b3a; font: 14px/1.6 system-ui, sans-serif; }
    .meridian-chat *, .meridian-chat *::before, .meridian-chat *::after { box-sizing: border-box; }
    .meridian-chat h2, .meridian-chat p, .meridian-chat ul { margin: 0; }
    .meridian-chat h2 { font-size: 18px; line-height: 1.4; }
    .meridian-chat button, .meridian-chat textarea { font: inherit; color: inherit; border: 1px solid #b8c7d0; border-radius: 7px; background: #fff; }
    .meridian-chat button { padding: 7px 11px; cursor: pointer; }
    .meridian-chat button:hover:not(:disabled) { background: #eaf3f5; }
    .meridian-chat button:disabled { cursor: default; opacity: .6; }
    .meridian-chat :is(button, textarea, a, summary):focus-visible { outline: 3px solid #1675be; outline-offset: 3px; }
    .meridian-chat .mc-history { flex: 1 1 190px; min-width: 0; }
    .meridian-chat .mc-history-heading, .meridian-chat .mc-message-heading, .meridian-chat .mc-send-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
    .meridian-chat .mc-history ul { list-style: none; padding: 0; display: grid; gap: 6px; max-height: 60vh; overflow: auto; margin-top: 12px; }
    .meridian-chat .mc-history li button { width: 100%; text-align: left; border-color: transparent; }
    .meridian-chat .mc-history li button[aria-current="true"] { background: #e5f0f3; border-color: #b6d1da; }
    .meridian-chat .mc-title { display: block; font-weight: 600; overflow-wrap: anywhere; }
    .meridian-chat time { display: block; font-size: 11px; color: #526777; }
    .meridian-chat .mc-refresh { margin-top: 12px; font-size: 12px; }
    .meridian-chat .mc-thread { flex: 3 1 320px; min-width: 0; }
    .meridian-chat .mc-thread-heading { margin-bottom: 18px; }
    .meridian-chat .mc-muted { color: #526777; font-size: 13px; }
    .meridian-chat .mc-notice { padding: 12px 14px; background: #edf4f8; border: 1px solid #c6d9e5; border-radius: 8px; margin-bottom: 18px; }
    .meridian-chat .mc-messages { display: grid; gap: 20px; }
    .meridian-chat .mc-message { min-width: 0; padding: 16px; border: 1px solid #e0e7eb; border-radius: 10px; overflow-wrap: anywhere; }
    .meridian-chat .mc-user { background: #f3f7f9; }
    .meridian-chat .mc-message-heading { margin-bottom: 10px; }
    .meridian-chat .mc-text { white-space: pre-wrap; }
    .meridian-chat .mc-attachments { list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(190px, 100%), 1fr)); gap: 10px; margin-top: 18px; }
    .meridian-chat .mc-attachments li { border: 1px solid #cad8df; border-radius: 8px; padding: 12px; }
    .meridian-chat .mc-compact { grid-template-columns: 1fr; }
    .meridian-chat .mc-part-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .meridian-chat .mc-attachments small { display: block; color: #526777; margin-top: 8px; }
    .meridian-chat .mc-composer { display: grid; gap: 10px; border-top: 1px solid #e0e7eb; margin-top: 24px; padding-top: 18px; }
    .meridian-chat .mc-composer label { font-weight: 600; }
    .meridian-chat textarea { width: 100%; min-height: 88px; resize: vertical; padding: 10px 12px; }
    .meridian-chat .mc-send-row button { background: #164e63; color: #fff; border-color: #164e63; }
    .meridian-chat .mc-send-row button:hover:not(:disabled) { background: #103d4e; }
    @media (max-width: 600px) {
      .meridian-chat { gap: 20px; }
      .meridian-chat .mc-history, .meridian-chat .mc-thread { flex-basis: 100%; }
      .meridian-chat .mc-history ul { max-height: 220px; }
      .meridian-chat .mc-message { padding: 12px; }
    }
  `}</style>;
}

export default Chat;
