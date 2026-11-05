import { useEffect, useId, useRef, useState } from "react";
import type {
  CorrectionCheck, FactSource, JsonValue, ReviewAction, ReviewActionRequest, ReviewActionResponse,
  ReviewItem, ReviewListRequest, ReviewProps,
} from "../contracts";
import { MethodBadge } from "../chat/Evidence";

// Debug is still a display surface: never render credentials or private paths.
function publicText(value: string): string {
  return value
    .replace(/\b(?:sk|sk-proj|sk-ant)-[A-Za-z0-9_-]+/g, "[credential withheld]")
    .replace(/\bBearer\s+[^\s"<>]+/gi, "[credential withheld]")
    .replace(/\b(?:api[_ -]?key|access[_ -]?token|password|secret)["']?\s*[:=]\s*["']?[^\s,;}]+/gi, "[credential withheld]")
    .replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"<>]*/g, "[private path withheld]")
    .replace(/(?:file:\/\/|\/(?:home|Users|root|tmp|var|mnt)\/|~\/)[^\s"<>]*/g, "[private path withheld]");
}

function valueText(value: JsonValue): string {
  return publicText(typeof value === "string" ? value : JSON.stringify(value) ?? "null");
}

function statusText(item: ReviewItem): string {
  return item.status === "source_changed" ? "Source changed" : item.status[0].toUpperCase() + item.status.slice(1);
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return `${fallback} ${publicText(error.message)}`;
  return fallback;
}

export function Review(props: ReviewProps) {
  // Also guard at runtime so a stale link/incorrect host cannot mount controls
  // or request review data while the launch setting is off.
  if (props.debug?.enabled !== true) return null;
  return <ReviewPanel key={JSON.stringify([props.initial_item_id, props.initial_part_id, props.initial_filter])} {...props} />;
}

function ReviewPanel({ api, debug, reviewer_name, on_open_part, on_open_source,
  initial_item_id, initial_part_id, initial_filter, on_reviewed }: ReviewProps) {
  const [filter, setFilter] = useState<ReviewListRequest>(() => ({
    status: "pending", ...initial_filter,
    ...(initial_part_id ? { part_id: initial_part_id } : {}),
    ...(initial_item_id ? { status: "all" } : {}),
  }));
  const [requestedId, setRequestedId] = useState(initial_item_id);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [followupWarning, setFollowupWarning] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ReviewActionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const submitting = useRef(false);
  const mounted = useRef(true);
  const noteId = useId();
  const filterId = useId();

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(null);
    api.review(filter).then(saved => {
      if (!active) return;
      setItems(saved); setUncertain(false); setActionError(null);
      setSelected(current => {
        const identity = requestedId ?? current?.id;
        const found = saved.find(item => item.id === identity);
        // Retain a just-completed decision beside the refreshed pending queue.
        return found ?? (requestedId ? null : current && current.status !== "pending" ? current : saved[0] ?? null);
      });
    }).catch(error => {
      if (active) setLoadError(errorText(error, "Review items could not be loaded."));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [api, filter, attempt, requestedId]);

  async function act(action: ReviewAction, fields: Pick<ReviewActionRequest, "value" | "source_ids"> = {}) {
    if (!selected || submitting.current || loading || loadError || uncertain ||
        selected.status !== "pending" || !selected.allowed_actions.includes(action)) return;
    const item = selected;
    submitting.current = true; setBusy(true); setActionError(null); setFollowupWarning(null);
    try {
      const saved = await api.review_action({ item_id: item.id }, { action, note: notes[item.id] ?? null, ...fields });
      // A real saved response is the only trigger for parent-state refresh.
      try { on_reviewed?.(saved); } catch {
        if (mounted.current) setFollowupWarning("Decision saved. Reopen the part to refresh the surrounding view.");
      }
      if (!mounted.current) return;
      setResult(saved); setSelected(saved.item); setRequestedId(undefined);
      setItems(current => current.map(entry => entry.id === item.id ? saved.item : entry));
      setAttempt(current => current + 1);
    } catch (error) {
      if (mounted.current) {
        setUncertain(true);
        setActionError(errorText(error, "The decision result could not be confirmed. Reload to check its saved state before retrying."));
      }
    } finally {
      submitting.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const actionResult = result?.item.id === selected?.id ? result : null;
  const canAct = selected?.status === "pending" && !loading && !loadError && !uncertain && !busy;

  return <section className="meridian-review" aria-label="Debug review">
    <ReviewStyles />
    <header className="mr-header"><div><p className="mr-eyebrow">Debug</p><h1>Review</h1>
      <p className="mr-muted">Inspect original evidence, resolve missing inputs, and record explicit review decisions.</p></div>
      <button type="button" disabled={busy || loading} onClick={() => setAttempt(current => current + 1)}>Reload review</button>
    </header>
    <div className="mr-toolbar"><label htmlFor={filterId}>Show</label>
      <select id={filterId} disabled={busy} value={filter.status ?? "pending"} onChange={event => {
        setFilter(current => ({ ...current, status: event.target.value as ReviewListRequest["status"] }));
        setSelected(null); setRequestedId(undefined); setResult(null); setActionError(null);
      }}>
        <option value="pending">Pending</option><option value="accepted">Accepted</option>
        <option value="rejected">Rejected</option><option value="source_changed">Source changed</option>
        <option value="all">All items</option>
      </select>
      {filter.part_id && <span className="mr-muted">Part: {publicText(filter.part_id)}</span>}
      <span className="mr-muted">Reviewer: {publicText(reviewer_name)}</span>
    </div>
    {loading && <p role="status">Loading review items…</p>}
    {loadError && <p className="mr-alert" role="alert">{loadError} Use Reload review to try again.</p>}
    {actionError && <p className="mr-alert" role="alert">{actionError}</p>}
    {followupWarning && <p className="mr-alert" role="status">{followupWarning}</p>}
    <div className="mr-layout"><aside aria-label="Review items">
      <p className="mr-muted">{items.length} {items.length === 1 ? "item" : "items"}</p>
      {!loading && !loadError && items.length === 0 && <p>No items match this view.</p>}
      <ul className="mr-queue">{items.map(item => <li key={item.id}>
        <button type="button" disabled={busy || loading} aria-current={selected?.id === item.id ? "true" : undefined}
          onClick={() => { setSelected(item); setRequestedId(undefined); setActionError(null); }}>
          <strong>{publicText(item.title)}</strong><span>{publicText(item.applies_to)}</span>
          <span className="mr-status">{statusText(item)}</span>
        </button>
      </li>)}</ul>
    </aside><div className="mr-detail" aria-busy={busy}>
      {!selected && !loading && <p>{requestedId
        ? "The requested review item is unavailable in this view. Select an item or reload."
        : "Select an item to inspect its sources."}</p>}
      {selected && <article aria-label="Selected review item">
        <div className="mr-title"><h2>{publicText(selected.title)}</h2><span className="mr-status">{statusText(selected)}</span></div>
        <p className="mr-muted mr-break">{publicText(selected.applies_to)}</p>
        {(selected.fixture || selected.synthetic) && <p className="mr-alert">Synthetic test fixture. This is not a real engineering review.</p>}
        <div className="mr-actions">
          {selected.part_id && <button type="button" onClick={() => on_open_part({ part_id: selected.part_id!, tab: "detail" })}>Open part</button>}
          {debug.on_open_history && <button type="button" onClick={() => debug.on_open_history?.(selected.applies_to)}>Open decision history</button>}
        </div>
        <dl className="mr-values"><div><dt>Value when proposed</dt><dd>{valueText(selected.current_value ?? null)}</dd></div>
          <div><dt>{selected.kind === "correction" ? "Proposed correction" : "Prepared proposal"}</dt><dd>{valueText(selected.proposed_value ?? null)}</dd></div></dl>
        <h3>Reason{selected.status !== "pending" ? " and review note" : ""}</h3><p className="mr-verbatim">{publicText(selected.message)}</p>
        <p className="mr-muted">Proposed <time dateTime={selected.created_at}>{publicText(selected.created_at)}</time></p>
        {selected.review && <p>Review: {publicText(selected.review.status ?? "not_reviewed")}
          {selected.review.by && <> · {publicText(selected.review.by)}</>}
          {selected.review.at && <> · <time dateTime={selected.review.at}>{publicText(selected.review.at)}</time></>}</p>}
        {selected.status === "source_changed" && <p className="mr-alert">The saved source binding is no longer current. Reload current prepared evidence; a new source-bound proposal is required before review.</p>}
        <CheckEvidence check={selected.check_result} sources={selected.sources ?? []} on_open_source={on_open_source} />
        <section><h3>Original source evidence</h3>
          {(selected.sources ?? []).length === 0 && <p>No navigable source evidence is available.</p>}
          {(selected.sources ?? []).map((source, index) => <details className="mr-source" key={`${source.name}-${index}`}
            open={source.name === selected.applies_to || source.name === source.target.row_name}>
            <summary>{publicText(source.name)}{source.target.page ? ` · page ${source.target.page}` : ""}</summary>
            {source.says !== null && typeof source.says === "object" && !Array.isArray(source.says)
              ? <dl className="mr-row">{Object.entries(source.says).map(([key, value]) => <div key={key}>
                  <dt>{publicText(key)}</dt><dd>{valueText(value)}</dd></div>)}</dl>
              : <blockquote className="mr-verbatim">{valueText(source.says)}</blockquote>}
            <button type="button" onClick={() => on_open_source(source.target)}>Open source</button>
            <MethodBadge debug={debug} method={source.method} badge={source.target.kind === "bom" ? "Original BOM evidence" : "Original source evidence"}
              review={source.review} provenance={source.provenance} />
            {source.note && <p>{publicText(source.note)}</p>}
            {source.source_sha256 && <p className="mr-muted mr-break">Current source hash: {source.source_sha256}</p>}
          </details>)}
        </section>
        <section><h3>Preparation evidence</h3>{selected.ai_answers
          ? <MethodBadge debug={debug} method={selected.sources?.[0]?.method ?? "unresolved"}
              badge="Saved preparation evidence" provenance={selected.ai_answers} fact_name={selected.applies_to} />
          : <p className="mr-muted">No AI preparation answers are recorded for this item.</p>}</section>
        <details className="mr-source"><summary>Saved source binding</summary>
          <p>These target hashes are retained with the proposal and the review decision.</p>
          <dl className="mr-row">{Object.entries(selected.source_hashes).map(([name, hash]) =>
            <div key={name}><dt>{publicText(name)}</dt><dd className="mr-break">{hash}</dd></div>)}</dl>
        </details>
        {selected.status === "pending" && <section className="mr-decision"><h3>Review decision</h3>
          {selected.allowed_actions.length > 0 ? <>
            <p>Only an explicit action below records a decision by {publicText(reviewer_name)}. Pending corrections and mapping proposals do not change effective facts.</p>
            <label htmlFor={noteId}>Review note (optional)</label>
            <textarea id={noteId} rows={3} value={notes[selected.id] ?? ""} disabled={busy}
              onChange={event => setNotes(current => ({ ...current, [selected.id]: event.target.value }))} />
            <M1Actions key={selected.id} item={selected} disabled={!canAct}
              on_action={(action, fields) => { void act(action, fields); }} />
          </> : <p>This item has no supported action in its current state.</p>}
          {busy && <p role="status">Saving decision…</p>}
        </section>}
        {actionResult && <section className="mr-saved" aria-label="Saved decision result"><h3>Decision saved</h3>
          {(actionResult.refresh.warnings ?? []).map((warning, index) => <p key={index} className="mr-alert">{publicText(warning)}</p>)}
          {Object.keys(actionResult.refresh.facts).length > 0 && <p>Facts refreshed for {actionResult.refresh.part_ids.map(publicText).join(", ")}.</p>}
          {Object.entries(actionResult.refresh.models).map(([part, model]) => <p key={part}>
            {publicText(part)} · Model: {publicText(model.state)}{model.message ? ` · ${publicText(model.message)}` : ""}</p>)}
          <details><summary>Retained decisions for this fact</summary><ol className="mr-history">
            {actionResult.decisions.map(decision => <li key={decision.decision_id}>
              <p>{publicText(decision.status)} · {publicText(decision.by)} · <time dateTime={decision.at}>{publicText(decision.at)}</time></p>
              <p>{valueText(decision.old_value ?? null)} → {valueText(decision.value)}</p>
              {decision.reason && <p className="mr-verbatim">Reason: {publicText(decision.reason)}</p>}
              {decision.note != null && <p className="mr-verbatim">Note: {publicText(decision.note)}</p>}
            </li>)}
          </ol></details>
        </section>}
      </article>}
    </div></div>
  </section>;
}

function M1Actions({ item, disabled, on_action }: {
  item: ReviewItem; disabled: boolean;
  on_action: (action: ReviewAction, fields?: Pick<ReviewActionRequest, "value" | "source_ids">) => void;
}) {
  const [draft, setDraft] = useState("");
  const [choice, setChoice] = useState("");
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [rows, setRows] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const valueId = useId();
  const options = item.options ?? [];
  const isTemplate = item.kind === "template_field";
  const isComposite = isTemplate && (item.applies_to.endsWith("/outline") || /\/feature-[^/]+$/.test(item.applies_to));
  const isText = item.kind === "scan_reading" || /\/(?:material|thread_size)$/.test(item.applies_to);
  const evidence = [...new Map((item.sources ?? []).filter(source => source.target.kind === "drawing")
    .map(source => [source.name, source] as const)).values()];
  const linkRows = [...new Set(options.flatMap(option => option && typeof option === "object" && !Array.isArray(option)
    && Array.isArray(option.bom_rows) ? option.bom_rows.filter((row): row is string => typeof row === "string") : []))];
  const allowed = (action: ReviewAction) => item.allowed_actions.includes(action);

  function sendValue() {
    setError(null);
    if (!draft.trim()) { setError("Enter a value before recording the decision."); return; }
    let value: JsonValue;
    if (isComposite) {
      try { value = JSON.parse(draft) as JsonValue; } catch { setError("Enter valid JSON for the structured value."); return; }
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        setError("An outline or feature needs a structured object."); return;
      }
    } else if (isText) value = draft;
    else {
      value = Number(draft);
      if (!Number.isFinite(value)) { setError("Enter a finite numeric value."); return; }
    }
    if (isTemplate && !isText && sourceIds.length === 0) {
      setError("Select the drawing evidence supporting the numeric values."); return;
    }
    on_action("set_value", { value, ...(isTemplate ? { source_ids: sourceIds } : {}) });
  }

  return <div className="mr-value-form">
    {item.mapping && <p>Recorded relationship: {publicText(item.mapping.from_name)} → {publicText(item.mapping.to_name ?? "No equivalent")}
      {" · "}{publicText(item.mapping.relationship)}</p>}
    {allowed("choose_option") && <fieldset disabled={disabled}><legend>Printed alternatives</legend>
      <label htmlFor={valueId}>Choose the printed value</label>
      <select id={valueId} value={choice} onChange={event => setChoice(event.target.value)}>
        <option value="">Select an option</option>{options.map((option, index) =>
          <option key={index} value={index}>{valueText(option)}</option>)}
      </select>
      <button type="button" disabled={choice === ""} onClick={() => on_action("choose_option", { value: options[Number(choice)] })}>Use printed option</button>
    </fieldset>}
    {allowed("set_value") && item.kind === "link" && <fieldset disabled={disabled}><legend>Recorded BOM candidates</legend>
      {linkRows.length === 0 && <p>No eligible candidate rows are recorded.</p>}
      {linkRows.map(row => <label key={row} className="mr-choice"><input type="checkbox" checked={rows.includes(row)}
        onChange={event => setRows(current => event.target.checked ? [...current, row] : current.filter(value => value !== row))} />
        <span>{publicText(row)}</span></label>)}
      <div className="mr-actions"><button type="button" disabled={rows.length === 0}
        onClick={() => on_action("set_value", { value: { drawing_id: item.applies_to.split("/")[0], bom_rows: rows } })}>Set selected link</button>
        <button type="button" onClick={() => on_action("set_value", { value: { drawing_id: item.applies_to.split("/")[0], bom_rows: [] } })}>Record no matching row</button></div>
    </fieldset>}
    {allowed("set_value") && item.kind === "name_mapping" && <fieldset disabled={disabled}><legend>Recorded name pair</legend>
      <label htmlFor={valueId}>Relationship</label><select id={valueId} value={choice} onChange={event => setChoice(event.target.value)}>
        <option value="">Select a relationship</option>{options.map((option, index) => <option key={index} value={index}>{valueText(option)}</option>)}
      </select><button type="button" disabled={choice === ""} onClick={() => on_action("set_value", { value: options[Number(choice)] })}>Set relationship</button>
    </fieldset>}
    {allowed("set_value") && (isTemplate || item.kind === "scan_reading") && <fieldset disabled={disabled}>
      <legend>{isTemplate ? "Source-backed value" : "Read the original scan"}</legend>
      <label htmlFor={valueId}>{isComposite ? "Structured value (JSON)" : isText ? "Text value" : "Numeric value"}</label>
      {isComposite || isText ? <textarea id={valueId} rows={isComposite ? 5 : 2} value={draft} onChange={event => setDraft(event.target.value)} />
        : <input id={valueId} type="number" step="any" value={draft} onChange={event => setDraft(event.target.value)} />}
      {item.proposed_value != null && <button type="button" onClick={() => setDraft(isComposite
        ? JSON.stringify(item.proposed_value, null, 2) : typeof item.proposed_value === "string" ? item.proposed_value : JSON.stringify(item.proposed_value))}>Use saved proposal as draft</button>}
      {isComposite && <p className="mr-muted">Enter semantic outline or feature values. Cite the printed numbers for its numeric fields; the server supplies field identities.</p>}
      {isTemplate && <details className="mr-source" open><summary>Supporting drawing evidence</summary>
        <p className="mr-muted">Select one matching printed number per numeric value, and the drawing location supporting the shape or text.</p>
        {evidence.map(source => <label key={source.name} className="mr-choice"><input type="checkbox" checked={sourceIds.includes(source.name)}
          onChange={event => setSourceIds(current => event.target.checked ? [...current, source.name] : current.filter(name => name !== source.name))} />
          <span>{publicText(source.name)}{typeof source.says === "string" ? ` · ${publicText(source.says)}` : ""}</span></label>)}
      </details>}
      <button type="button" onClick={sendValue}>Set value</button>
    </fieldset>}
    {error && <p role="alert" className="mr-alert">{error}</p>}
    <div className="mr-actions">
      {allowed("accept") && <button type="button" className="mr-accept" disabled={disabled} onClick={() => on_action("accept")}>
        {item.kind === "correction" ? "Accept correction" : item.kind === "link" ? "Accept proposed link" : item.kind === "scan_reading" ? "Accept reading" : "Accept prepared value"}</button>}
      {allowed("approve_mapping") && <button type="button" className="mr-accept" disabled={disabled}
        onClick={() => on_action("approve_mapping")}>Approve recorded mapping</button>}
      {allowed("reject") && <button type="button" disabled={disabled} onClick={() => on_action("reject")}>
        {item.kind === "correction" ? "Reject correction" : "Reject prepared interpretation"}</button>}
    </div>
  </div>;
}

function CheckEvidence({ check, sources, on_open_source }: {
  check?: CorrectionCheck | null; sources: FactSource[]; on_open_source: ReviewProps["on_open_source"];
}) {
  if (!check) return <section><h3>Saved string-match check</h3><p>No correction check is recorded.</p></section>;
  return <section><h3>Saved string-match check</h3><p>{publicText(check.message)}</p>
    <p className="mr-muted">Text matches do not establish correctness or human review.</p>
    {(["drawing", "bom"] as const).map(kind => <div key={kind}><h4>{kind === "drawing" ? "Drawing text" : "Linked BOM cells"}</h4>
      {check[kind].length === 0 ? <p className="mr-muted">No {kind === "drawing" ? "drawing text" : "linked BOM text"} was available for this check.</p>
        : <ul className="mr-check">{check[kind].map((evidence, index) => {
          const source = sources.find(item => item.name === evidence.source_name);
          return <li key={`${evidence.source_name}-${index}`}><strong>{evidence.matched ? "Text match" : "No text match"}</strong>
            <span className="mr-muted mr-break">{publicText(evidence.source_name)}</span>
            <p className="mr-verbatim">{evidence.text == null ? "No text recorded" : publicText(evidence.text)}</p>
            {source && <button type="button" onClick={() => on_open_source(source.target)}>Inspect source</button>}
          </li>;
        })}</ul>}
    </div>)}
  </section>;
}

function ReviewStyles() {
  return <style>{`
    .meridian-review { color: #172b3a; font: 14px/1.6 system-ui, sans-serif; }
    .meridian-review * { box-sizing: border-box; }
    .meridian-review h1 { font-size: 26px; margin: 0 0 4px; }
    .meridian-review h2 { font-size: 19px; margin: 0; }
    .meridian-review h3 { font-size: 15px; margin: 20px 0 8px; }
    .meridian-review h4 { font-size: 13px; margin: 12px 0 6px; }
    .meridian-review p { margin: 6px 0 12px; }
    .meridian-review button, .meridian-review select, .meridian-review textarea, .meridian-review input { font: inherit; color: inherit; border: 1px solid #b9c9d1; border-radius: 6px; padding: 7px 11px; background: #fff; }
    .meridian-review button, .meridian-review summary, .meridian-review select { cursor: pointer; }
    .meridian-review button:hover { background: #edf4f6; }
    .meridian-review button:disabled, .meridian-review select:disabled { opacity: .55; cursor: default; }
    .meridian-review :is(button, select, textarea, summary):focus-visible { outline: 3px solid #1675be; outline-offset: 3px; }
    .meridian-review .mr-header, .meridian-review .mr-toolbar, .meridian-review .mr-title, .meridian-review .mr-actions { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; }
    .meridian-review .mr-header { justify-content: space-between; margin-bottom: 20px; }
    .meridian-review .mr-eyebrow { color: #526777; font-size: 12px; margin: 0; }
    .meridian-review .mr-toolbar { padding-bottom: 18px; border-bottom: 1px solid #d9e1e7; }
    .meridian-review .mr-toolbar label { font-weight: 600; }
    .meridian-review .mr-muted { color: #526777; }
    .meridian-review .mr-break { overflow-wrap: anywhere; }
    .meridian-review .mr-verbatim { white-space: pre-wrap; overflow-wrap: anywhere; }
    .meridian-review .mr-layout { display: grid; grid-template-columns: minmax(180px, 260px) minmax(0, 1fr); gap: 28px; padding-top: 16px; }
    .meridian-review .mr-queue { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
    .meridian-review .mr-queue button { display: grid; gap: 3px; width: 100%; text-align: left; padding: 12px; overflow-wrap: anywhere; }
    .meridian-review .mr-queue button[aria-current=true] { border-color: #267689; background: #eef7f7; }
    .meridian-review .mr-queue button > span { font-size: 12px; }
    .meridian-review .mr-status { color: #365366; font-size: 12px; border: 1px solid #d3dfe5; border-radius: 4px; padding: 1px 7px; width: fit-content; }
    .meridian-review .mr-values { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 18px 0; }
    .meridian-review .mr-values > div { padding: 14px; background: #f5f8fa; border: 1px solid #e0e8ed; border-radius: 6px; }
    .meridian-review dt { color: #526777; font-size: 12px; }
    .meridian-review dd { margin: 3px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    .meridian-review .mr-source { padding: 12px; margin: 9px 0; border: 1px solid #d9e1e7; border-radius: 6px; }
    .meridian-review .mr-source summary { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
    .meridian-review blockquote { padding-left: 12px; margin: 12px 0; border-left: 2px solid #bacbd5; }
    .meridian-review .mr-row { display: grid; gap: 9px; }
    .meridian-review .mr-check { list-style: none; padding: 0; display: grid; gap: 8px; }
    .meridian-review .mr-check li { padding: 8px 0; border-bottom: 1px solid #e5ebef; }
    .meridian-review .mr-check li > span { display: block; font-size: 12px; }
    .meridian-review .mr-check button { font-size: 12px; }
    .meridian-review .mr-alert { background: #fff8e8; color: #624500; padding: 12px; border: 1px solid #ead6a0; border-radius: 6px; overflow-wrap: anywhere; }
    .meridian-review .mr-decision { border-top: 1px solid #d9e1e7; margin-top: 22px; }
    .meridian-review textarea { display: block; width: 100%; margin: 7px 0 12px; resize: vertical; }
    .meridian-review .mr-accept { background: #165e68; color: white; border-color: #165e68; }
    .meridian-review .mr-accept:hover { background: #104c55; }
    .meridian-review .mr-saved { margin-top: 22px; border-top: 1px solid #d9e1e7; }
    .meridian-review .mr-history { padding-left: 20px; }
    .meridian-review .mr-history li { padding: 8px 0; }
    .meridian-review .mr-value-form { display: grid; gap: 12px; }
    .meridian-review fieldset { min-width: 0; display: grid; gap: 10px; border: 1px solid #d9e1e7; border-radius: 6px; padding: 14px; }
    .meridian-review legend { padding: 0 5px; font-weight: 600; }
    .meridian-review .mr-choice { display: flex; align-items: flex-start; gap: 9px; overflow-wrap: anywhere; }
    .meridian-review .mr-choice input { margin-top: 5px; flex: none; }
    @media (max-width: 720px) { .meridian-review .mr-layout { grid-template-columns: 1fr; gap: 20px; } .meridian-review .mr-values { grid-template-columns: 1fr; } }
  `}</style>;
}

export default Review;
