import { useEffect, useRef, useState, type ComponentType } from "react";
import {
  debug_context, encode_id, model_api_path, part_api_path, shell_navigation,
  type ApiClient, type ChatProps, type ConversationId, type DebugPanel,
  type PartOpenRequest, type PartPageProps, type PartsProps, type ReviewLink,
  type ReviewProps, type ShellProps, type SourceTarget, type StatusResponse,
} from "./contracts";
import Chat from "./chat/Chat";
import PartPage from "./part/PartPage";
import Parts from "./part/Parts";

// Screens can be injected for integration without changing their frozen props.
export interface ShellScreens {
  Chat: ComponentType<ChatProps>;
  PartPage: ComponentType<PartPageProps>;
  Parts: ComponentType<PartsProps>;
  Review: ComponentType<ReviewProps>;
}
function Empty({ title, text }: { title: string; text: string }) {
  return <div className="ms-empty"><h2>{title}</h2><p>{text}</p></div>;
}
function EmptyReview() {
  return <Empty title="Review unavailable" text="The engineering review screen is not connected." />;
}
const defaultScreens: ShellScreens = { Chat, Parts, PartPage, Review: EmptyReview };

// Frozen transport only: no storage, context slicing, citation ledger or provider behavior.
export function createApiClient(fetcher: typeof fetch = (...args) => fetch(...args)): ApiClient {
  async function request<T>(url: string, body?: unknown, binary = false): Promise<T> {
    const response = await fetcher(url, body === undefined ? { credentials: "same-origin" } : {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      // Never forward server diagnostics/private paths into ordinary errors.
      throw new Error(response.status === 404 ? "This item is unavailable. Return to Parts."
        : response.status === 501 ? "This feature is unavailable. Try again later."
        : "Could not complete the request. Please try again.");
    }
    return (binary ? response.blob() : response.json()) as Promise<T>;
  }
  function query(url: string, values: object = {}) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) {
      if (value != null) search.set(key, String(value));
    }
    return search.size ? `${url}?${search}` : url;
  }
  return {
    status: () => request("/api/status"),
    parts: (q) => request(query("/api/parts", q)),
    part: ({ id }) => request(part_api_path(id)),
    image: ({ id, ...q }) => request(query(`${part_api_path(id)}/image`, q), undefined, true),
    model: ({ drawing_id, example }) => request(model_api_path(drawing_id, example), undefined, true),
    chat: (body) => request("/api/chat", body),
    conversations: () => request("/api/conversations"),
    create_conversation: (body = {}) => request("/api/conversations", body),
    conversation: ({ conversation_id }) => request(`/api/conversations/${encode_id(conversation_id)}`),
    send_conversation: ({ conversation_id }, body) => request(`/api/conversations/${encode_id(conversation_id)}/messages`, body),
    review: (q) => request(query("/api/review", q)),
    review_action: ({ item_id }, body) => request(`/api/review/${encode_id(item_id)}`, body),
    history: ({ id, ...q }) => request(query(`${part_api_path(id)}/history`, q)),
    accuracy: (q) => request(query("/api/accuracy", q)),
    crop: ({ id, ...q }) => request(query(`${part_api_path(id)}/crop`, q), undefined, true),
    step: ({ drawing_id, example }) => request(model_api_path(drawing_id, example, "step"), undefined, true),
    readme: (q) => request(query("/api/readme", q)),
  };
}

// Only the selected ID is kept in the URL; full saved history stays server-owned.
function restoredConversation(): string | null {
  return typeof window === "undefined" ? null : new URL(window.location.href).searchParams.get("conversation");
}
function persistSelection(id: ConversationId | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("conversation", id);
  else url.searchParams.delete("conversation");
  window.history.replaceState(window.history.state, "", url);
}
export function sourcePartRequest(target: SourceTarget): PartOpenRequest | null {
  const part_id = target.part_id || (target.drawing_id ? `${target.drawing_id}/part`
    : target.kind === "bom" && target.row_name ? `${target.row_name}/part` : null);
  if (target.kind === "readme" || !part_id) return null;
  return { part_id, tab: target.kind === "drawing" ? "drawing" : "detail", highlights: [target] };
}
// Selected server diagnostics are displayed only inside enabled Debug.
function diagnostic(text: string): string {
  return text.replace(/\b(?:sk|sk-proj|sk-ant)-[A-Za-z0-9_-]+/g, "[credential withheld]")
    .replace(/\bBearer\s+[^\s"<>]+/gi, "[credential withheld]")
    .replace(/\b(?:api[_ -]?key|access[_ -]?token|password|secret)["']?\s*[:=]\s*["']?[^\s,;}]+/gi, "[credential withheld]")
    .replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"<>]*/g, "[private path withheld]")
    .replace(/(?:file:\/\/|\/(?:home|Users|root|tmp|var|mnt)\/|~\/)[^\s"<>]*/g, "[private path withheld]");
}

export interface AppShellProps extends ShellProps { screens?: Partial<ShellScreens> }
export function Shell({ api, status, initial_page = "chat", initial_debug_panel,
  initial_conversation_id, on_open_part, on_open_source, screens }: AppShellProps) {
  const { Chat, Parts, PartPage, Review } = { ...defaultScreens, ...screens };
  const [page, setPage] = useState<"chat" | "parts" | "debug">(initial_page);
  const [debugPanel, setDebugPanel] = useState<DebugPanel>(initial_debug_panel ?? "diagnostics");
  const [reviewItem, setReviewItem] = useState<ReviewLink | null>(null);
  const [part, setPart] = useState<PartOpenRequest | null>(null);
  const [selection, setSelection] = useState<ConversationId | null>(null);
  const selected = useRef<ConversationId | null>(null);
  const selectionVersion = useRef(0);
  const [notice, setNotice] = useState<string | null>(null);
  const partTrigger = useRef<HTMLElement | null>(null);
  const panelHeading = useRef<HTMLHeadingElement | null>(null);
  const enabled = status.debug_enabled === true;
  const visiblePage = page === "debug" && !enabled ? "chat" : page;

  useEffect(() => {
    const id = initial_conversation_id === undefined ? restoredConversation() : initial_conversation_id;
    if (!id) return;
    const version = selectionVersion.current;
    let active = true;
    // Verify restored selection by a no-key server read before M18 sees it.
    api.conversation({ conversation_id: id }).then((detail) => {
      if (!active || version !== selectionVersion.current) return;
      if (detail.conversation.conversation_id !== id || detail.synthetic || detail.fixture) {
        throw new Error("Unavailable conversation");
      }
      selected.current = id; setSelection(id); setPart(null); persistSelection(id);
    }).catch(() => {
      if (!active || version !== selectionVersion.current) return;
      persistSelection(null);
      setNotice("Saved chat unavailable. Select another chat or start a new one.");
    });
    return () => { active = false; };
  }, [api, initial_conversation_id]);
  useEffect(() => { if (part) panelHeading.current?.focus(); }, [part, visiblePage]);

  function selectConversation(id: ConversationId) {
    selectionVersion.current += 1;
    if (selected.current !== id) {
      selected.current = id; setSelection(id); setPart(null); setNotice(null); persistSelection(id);
    }
    setPage("chat");
  }
  function openPart(request: PartOpenRequest) {
    partTrigger.current = typeof document === "undefined" ? null : document.activeElement as HTMLElement;
    setPart(request); setNotice(null); on_open_part(request);
  }
  function openSource(target: SourceTarget) {
    const request = sourcePartRequest(target);
    if (request) openPart(request);
    else setNotice("Source view unavailable. Open Parts to find the source.");
    on_open_source(target);
  }
  function closePart() { setPart(null); partTrigger.current?.focus(); }
  const debug = debug_context(status, { on_open_review: (item) => {
    if (!enabled) return;
    setReviewItem(item); setDebugPanel("review"); setPage("debug");
  } });

  return <div className="meridian-shell">
    <ShellStyles />
    <a className="ms-skip" href="#meridian-content">Skip to content</a>
    <aside className="ms-sidebar" aria-label="Application sidebar">
      <div className="ms-brand"><span className="ms-mark" aria-hidden="true">M</span><div>Meridian<small>Engineering knowledge</small></div></div>
      <nav aria-label="Main navigation">{shell_navigation(status).map((item) =>
        <button type="button" key={item} aria-current={visiblePage === item ? "page" : undefined}
          onClick={() => { setPage(item); setNotice(null); }}>
          <span aria-hidden="true">{item === "chat" ? "◇" : item === "parts" ? "▦" : "⚙"}</span>
          {item === "chat" ? "Chat" : item === "parts" ? "Parts" : "Debug"}
        </button>)}</nav>
      <p className="ms-sidebar-note">Explore parts and their sources.</p>
    </aside>
    <main id="meridian-content" tabIndex={-1} className="ms-main">
      <header className="ms-header"><div><p className="ms-eyebrow">Project Meridian</p>
        <h1>{visiblePage === "chat" ? "Chat" : visiblePage === "parts" ? "Parts" : "Debug"}</h1></div>
        <p>{visiblePage === "chat" ? "Ask questions. Explore the evidence." : visiblePage === "parts" ? "Find a part and open its sources." : "Engineering tools and diagnostics."}</p>
      </header>
      {notice && <p role="status" className="ms-notice">{notice}</p>}
      <div className={`ms-workspace${part ? " ms-with-panel" : ""}`}>
        <section className="ms-content" aria-label={visiblePage === "chat" ? "Conversation" : visiblePage === "parts" ? "Parts browser" : "Engineering Debug"}>
          {/* Keep Chat and its draft mounted across page/panel changes. */}
          <div hidden={visiblePage !== "chat"}>
            <Chat api={api} status={status} selected_conversation_id={selection}
              on_select_conversation={selectConversation} debug={debug}
              on_open_part={({ conversation_id, ...request }) => {
                if (conversation_id === selected.current && conversation_id !== null) {
                  setPage("chat"); openPart(request);
                }
              }}
              on_open_source={(target, conversation_id) => {
                if (conversation_id === selected.current && conversation_id !== null) {
                  setPage("chat"); openSource(target);
                }
              }} />
          </div>
          {visiblePage === "parts" && <Parts api={api} on_open_part={openPart} debug={debug} />}
          {visiblePage === "debug" && debug.enabled && <>
            <nav className="ms-debug-nav" aria-label="Debug navigation">
              <button type="button" aria-current={debugPanel === "diagnostics" ? "page" : undefined} onClick={() => setDebugPanel("diagnostics")}>Diagnostics</button>
              <button type="button" aria-current={debugPanel === "review" ? "page" : undefined} onClick={() => setDebugPanel("review")}>Review</button>
            </nav>
            {debugPanel === "review" ? <Review api={api} debug={debug} reviewer_name="Jason Peng"
              initial_item_id={reviewItem?.id} on_open_part={openPart} on_open_source={openSource} />
              : <div className="ms-debug"><h2>Diagnostics</h2><p>{diagnostic(status.message)}</p>
                {(status.synthetic || status.fixture) && <p>Server responses use declared synthetic fixtures. They are not runtime evidence.</p>}
                {status.fixture_note && <p>{diagnostic(status.fixture_note)}</p>}
                <p>Chat state: {status.chat_state}; available: {String(status.chat_available)}.</p>
              </div>}
          </>}
        </section>
        {part && <aside className="ms-panel" aria-label="Selected part" onKeyDown={(event) => {
          if (event.key === "Escape") { event.stopPropagation(); closePart(); }
        }}>
          <div className="ms-panel-header"><h2 ref={panelHeading} tabIndex={-1}>Selected part</h2>
            <button type="button" onClick={closePart} aria-label="Close part panel">Close</button></div>
          <PartPage key={`${part.part_id}:${part.tab ?? "detail"}:${part.example ?? ""}:${JSON.stringify(part.highlights ?? [])}`}
            api={api} part_id={part.part_id} initial_tab={part.tab} highlights={part.highlights}
            example={part.example} embedded={visiblePage !== "parts"} debug={debug}
            on_open_part={openPart} on_open_source={openSource} on_close={closePart} />
        </aside>}
      </div>
    </main>
  </div>;
}

const defaultApi = createApiClient();
export default function App(props: Partial<AppShellProps> = {}) {
  const api = props.api ?? defaultApi;
  const [loaded, setLoaded] = useState<StatusResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (props.status) return;
    let active = true;
    setLoaded(null); setFailed(false);
    api.status().then((value) => { if (active) setLoaded(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [api, props.status, attempt]);
  const status = props.status ?? loaded;
  if (!status) return <div className="meridian-shell ms-start"><ShellStyles /><main>
    <h1>Meridian</h1><p role="status">{failed ? "Could not connect. Check the server and try again." : "Connecting…"}</p>
    {failed && <button type="button" onClick={() => setAttempt(value => value + 1)}>Try again</button>}
  </main></div>;
  return <Shell {...props} api={api} status={status}
    on_open_part={props.on_open_part ?? (() => {})} on_open_source={props.on_open_source ?? (() => {})} />;
}

function ShellStyles() {
  return <style>{`
    .meridian-shell { min-height: 100dvh; display: flex; background: #f5f7fa; color: #172b3a; font: 15px/1.6 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .meridian-shell *, .meridian-shell *::before, .meridian-shell *::after { box-sizing: border-box; }
    .meridian-shell [hidden] { display: none !important; }
    .meridian-shell h1, .meridian-shell h2, .meridian-shell p { margin: 0; }
    .meridian-shell h1 { font-size: 28px; line-height: 1.3; letter-spacing: -.025em; }
    .meridian-shell h2 { font-size: 19px; line-height: 1.4; }
    .meridian-shell button { font: inherit; padding: .5rem .85rem; border: 1px solid #bac7d0; border-radius: 7px; background: #fff; color: #172b3a; cursor: pointer; }
    .meridian-shell button:hover { background: #eaf1f5; }
    .meridian-shell :is(button, a, input, textarea, select, summary, [tabindex]):focus-visible { outline: 3px solid #1675be; outline-offset: 3px; }
    .meridian-shell .ms-skip { position: absolute; left: 1rem; top: -100px; z-index: 100; padding: .75rem; background: #fff; color: #134d78; }
    .meridian-shell .ms-skip:focus { top: 1rem; }
    .meridian-shell .ms-sidebar { width: 232px; flex: 0 0 232px; background: #fff; border-right: 1px solid #d9e1e7; padding: 30px 20px; display: flex; flex-direction: column; gap: 36px; }
    .meridian-shell .ms-brand { display: flex; align-items: center; gap: 12px; font-size: 20px; font-weight: 700; }
    .meridian-shell .ms-brand small { display: block; font-size: 11px; font-weight: 500; color: #526777; }
    .meridian-shell .ms-mark { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 10px; color: #fff; background: #164e63; }
    .meridian-shell .ms-sidebar nav { display: grid; gap: 8px; }
    .meridian-shell .ms-sidebar nav button { text-align: left; display: flex; gap: 12px; align-items: center; border-color: transparent; font-weight: 600; }
    .meridian-shell button[aria-current="page"] { background: #e5f0f3; color: #124b5d; border-color: #b6d1da; }
    .meridian-shell .ms-sidebar-note { margin-top: auto; font-size: 12px; color: #526777; }
    .meridian-shell .ms-main { flex: 1; min-width: 0; padding: 32px; }
    .meridian-shell .ms-header { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
    .meridian-shell .ms-header > p { color: #526777; font-size: 13px; }
    .meridian-shell .ms-eyebrow { color: #526777; text-transform: uppercase; font-size: 10px; font-weight: 700; letter-spacing: .12em; margin-bottom: 6px; }
    .meridian-shell .ms-workspace { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
    .meridian-shell .ms-workspace.ms-with-panel { grid-template-columns: minmax(280px, 1fr) minmax(330px, 1.15fr); }
    .meridian-shell .ms-content, .meridian-shell .ms-panel { min-width: 0; border: 1px solid #d9e1e7; border-radius: 12px; background: #fff; padding: 24px; overflow-wrap: anywhere; }
    .meridian-shell .ms-content { min-height: 380px; }
    .meridian-shell .ms-empty { padding: 50px 10px; max-width: 480px; margin: 0 auto; }
    .meridian-shell .ms-empty p { margin-top: 10px; color: #526777; }
    .meridian-shell .ms-panel-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e0e7eb; padding-bottom: 16px; margin-bottom: 20px; }
    .meridian-shell .ms-notice { padding: 12px 16px; margin-bottom: 20px; background: #edf4f8; border: 1px solid #b7cedb; border-radius: 8px; }
    .meridian-shell .ms-debug-nav { display: flex; gap: 8px; margin-bottom: 24px; }
    .meridian-shell .ms-debug p + p { margin-top: 12px; }
    .meridian-shell.ms-start { align-items: center; justify-content: center; padding: 32px; }
    .meridian-shell.ms-start p { margin: 16px 0; }
    @media (max-width: 1100px) { .meridian-shell .ms-main { padding: 24px; } .meridian-shell .ms-workspace.ms-with-panel { grid-template-columns: minmax(0, 1fr); } }
    @media (max-width: 700px) {
      .meridian-shell { flex-direction: column; }
      .meridian-shell .ms-sidebar { width: auto; flex: none; padding: 16px; gap: 18px; border-right: 0; border-bottom: 1px solid #d9e1e7; }
      .meridian-shell .ms-sidebar nav { display: flex; flex-wrap: wrap; }
      .meridian-shell .ms-sidebar-note { display: none; }
      .meridian-shell .ms-main { padding: 20px 16px; }
      .meridian-shell .ms-header { display: block; margin-bottom: 20px; }
      .meridian-shell .ms-header > p { margin-top: 8px; }
      .meridian-shell .ms-content, .meridian-shell .ms-panel { padding: 18px; }
      .meridian-shell .ms-empty { padding: 28px 0; }
    }
  `}</style>;
}
