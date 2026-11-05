import { useEffect, useId, useState, type CSSProperties } from "react";
import {
  source_box_to_pixels, RECONSTRUCTION_LABEL,
  type ApiClient, type Box, type DebugContext, type DrawingEvidence, type FactResult,
  type JsonValue, type PageGeometry, type PartDetailResponse, type PartPageProps,
  type PartViewTab, type SourceTarget,
} from "../contracts";
import { MethodBadge, SourceTag, Undetermined } from "../chat/Evidence";
import { Viewer3D, availableModelExamples } from "../viewer3d/Viewer3D";

// Source text is shown as text, with the same private-data redaction as citation widgets.
function publicText(value: string): string {
  return value.replace(/\b(?:sk|sk-proj|sk-ant)-[A-Za-z0-9_-]+/g, "[credential withheld]")
    .replace(/\bBearer\s+[^\s"<>]+/gi, "[credential withheld]")
    .replace(/\b(?:api[_ -]?key|access[_ -]?token|password|secret)["']?\s*[:=]\s*["']?[^\s,;}]+/gi, "[credential withheld]")
    .replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"<>]*/g, "[private path withheld]")
    .replace(/(?:file:\/\/|\/(?:home|Users|root|tmp|var|mnt)\/|~\/)[^\s"<>]*/g, "[private path withheld]");
}

function valueText(value: JsonValue): string {
  if (value === null) return "Unavailable";
  if (Array.isArray(value)) return value.map(valueText).join(", ");
  return publicText(typeof value === "string" ? value : JSON.stringify(value));
}

function fieldLabel(name: string): string {
  const label = (name.split("/").pop() || name).replace(/[_-]/g, " ");
  return publicText(label.charAt(0).toUpperCase() + label.slice(1));
}

function FactValue({ fact, debug }: { fact: FactResult; debug?: DebugContext }) {
  const display = fact.display;
  if ("value" in display) return <>{display.label && <span>{publicText(display.label)} </span>}{valueText(display.value)}{display.value !== null && display.unit ? ` ${publicText(display.unit)}` : ""}</>;
  if ("values" in display && display.values.length > 0) return <>Printed options: {display.values.map(valueText).join(" / ")}{display.unit ? ` ${publicText(display.unit)}` : ""}</>;
  return <Undetermined fact={fact} debug={debug} />;
}

// Percentages stay aligned with the responsive image at every zoom level.
export function drawingHighlightStyle(box: Box, geometry: PageGeometry): CSSProperties {
  const [x, y, width, height] = source_box_to_pixels(box, geometry);
  return { left: `${x / geometry.image_width * 100}%`, top: `${y / geometry.image_height * 100}%`,
    width: `${width / geometry.image_width * 100}%`, height: `${height / geometry.image_height * 100}%` };
}

function Drawing({ api, part_id, drawing, highlights = [] }: {
  api: ApiClient; part_id: string; drawing: DrawingEvidence; highlights?: SourceTarget[];
}) {
  const cited = highlights.filter(target => target.kind === "drawing" &&
    (!target.drawing_id || target.drawing_id === drawing.id));
  const initialPage = cited.find(target => target.page && target.page >= 1 && target.page <= drawing.pages)?.page ?? 1;
  const [page, setPage] = useState(initialPage);
  const [zoom, setZoom] = useState(1);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const pageId = useId();
  const geometry = drawing.page_geometry.find(item => item.page === page);
  const boxes = cited.filter(target => (target.page ?? 1) === page && target.box);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null); setFailed(false);
    api.image({ id: part_id, page }).then(blob => {
      if (!active) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [api, part_id, page, attempt]);

  return <section aria-label="Drawing">
    <div className="mp-drawing-tools">
      {drawing.pages > 1 ? <label htmlFor={pageId}>Page <select id={pageId} value={page}
        onChange={event => setPage(Number(event.target.value))}>{Array.from({ length: drawing.pages }, (_, index) =>
          <option key={index + 1} value={index + 1}>{index + 1} of {drawing.pages}</option>)}</select></label>
        : <span>Page 1</span>}
      <div className="mp-zoom" aria-label="Drawing zoom">
        <button type="button" aria-label="Zoom out" disabled={zoom <= .5} onClick={() => setZoom(value => Math.max(.5, value - .25))}>−</button>
        <output aria-live="polite">{Math.round(zoom * 100)}%</output>
        <button type="button" aria-label="Zoom in" disabled={zoom >= 4} onClick={() => setZoom(value => Math.min(4, value + .25))}>+</button>
        <button type="button" onClick={() => setZoom(1)}>Fit</button>
      </div>
    </div>
    {failed ? <div className="mp-message" role="alert"><p>Drawing image unavailable. Try loading it again.</p>
      <button type="button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>
      : !url ? <p role="status" className="mp-message">Loading drawing…</p>
      : <div className="mp-canvas" tabIndex={0} role="region" aria-label={`Drawing ${drawing.id}, page ${page}. Scroll to pan when zoomed.`}>
        <div className="mp-paper" style={{ width: `${zoom * 100}%` }}>
          <img src={url} alt={`Drawing ${drawing.id}, page ${page}`} onError={() => setFailed(true)} />
          {geometry && boxes.map((target, index) => <span key={`${target.name}-${index}`} className="mp-highlight"
            style={drawingHighlightStyle(target.box!, geometry)} title={`Source: ${publicText(target.name)}`} aria-hidden="true" />)}
        </div>
      </div>}
    {boxes.length > 0 && geometry && <p className="mp-caption">Highlighted areas show the selected source.</p>}
  </section>;
}

export function PartPage({ api, part_id, record, initial_tab = "detail", highlights = [], example, debug, embedded,
  on_open_source }: PartPageProps) {
  const [part, setPart] = useState<PartDetailResponse | null>(record?.id === part_id ? record : null);
  const [loading, setLoading] = useState(!part);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<PartViewTab>(initial_tab);
  const tabId = useId();

  useEffect(() => {
    setTab(initial_tab);
  }, [part_id, initial_tab]);
  useEffect(() => {
    let active = true;
    setFailed(false);
    if (record?.id === part_id) { setPart(record); setLoading(false); return; }
    setPart(null); setLoading(true);
    api.part({ id: part_id }).then(result => {
      if (!active) return;
      if (result.id !== part_id) throw new Error("Wrong part");
      setPart(result);
    }).catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, part_id, record, attempt]);

  const current = part?.id === part_id ? part : null;
  const hasDrawing = Boolean(current?.has_drawing && current.drawing);
  const hasModel = Boolean(current && availableModelExamples(current).length);
  const visibleTab = tab === "model" && hasModel ? "model" : tab === "drawing" && hasDrawing ? "drawing" : "detail";
  const facts = Object.values(current?.facts ?? {});
  const sourceSelected = (fact: FactResult) => highlights.some(target => target.name === fact.fact ||
    fact.sources.some(source => source.name === target.name || (target.row_name && source.target.row_name === target.row_name)));

  return <article className={`meridian-part${embedded ? " mp-embedded" : ""}`} aria-label="Part details">
    <PartStyles />
    {loading && <p className="mp-message" role="status">Loading part…</p>}
    {failed && <div className="mp-message" role="alert"><h2>Part unavailable</h2><p>Could not load this part. Try again or select another part.</p>
      <button type="button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>}
    {!loading && !failed && current && <>
      <header className="mp-heading"><h2>{publicText(current.display_name || current.id)}</h2>
        <p className="mp-muted">{publicText(current.id)}{current.section ? ` · ${publicText(current.section)}` : ""}</p></header>
      {tab === "model" && !hasModel && <div className="mp-model-unavailable"><p>3D view: Unavailable</p><p className="mp-muted">{RECONSTRUCTION_LABEL}</p></div>}
      <div className="mp-tabs" role="tablist" aria-label="Part views">
        <button id={`${tabId}-detail`} role="tab" type="button" aria-selected={visibleTab === "detail"}
          aria-controls={`${tabId}-content`} onClick={() => setTab("detail")}>Details</button>
        {hasDrawing && <button id={`${tabId}-drawing`} role="tab" type="button" aria-selected={visibleTab === "drawing"}
          aria-controls={`${tabId}-content`} onClick={() => setTab("drawing")}>Drawing</button>}
        {hasModel && <button id={`${tabId}-model`} role="tab" type="button" aria-selected={visibleTab === "model"}
          aria-controls={`${tabId}-content`} onClick={() => setTab("model")}>3D</button>}
      </div>
      <div id={`${tabId}-content`} role="tabpanel" aria-labelledby={`${tabId}-${visibleTab}`}>
        {visibleTab === "model" ? <Viewer3D key={current.id} part={current} example={example}
          on_open_source={on_open_source} debug={debug} /> : visibleTab === "drawing" && current.drawing ? <Drawing key={`${part_id}:${JSON.stringify(highlights)}`}
          api={api} part_id={part_id} drawing={current.drawing} highlights={highlights} /> : <>
          <section className="mp-section"><h3>Part facts</h3>
            {facts.length === 0 ? <p className="mp-muted">Values unavailable.</p> : <div className="mp-table-wrap"><table className="mp-facts"><thead><tr><th>Property</th><th>Value</th><th>Source</th></tr></thead>
              <tbody>{facts.map(fact => <tr key={fact.fact} className={sourceSelected(fact) ? "mp-selected" : undefined}>
                <th scope="row">{fieldLabel(fact.fact)}</th><td><FactValue fact={fact} debug={debug} /></td>
                <td><SourceTag facts={[fact]} on_open_source={on_open_source} debug={debug} /></td></tr>)}</tbody></table></div>}
          </section>
          {current.bom.length > 0 && <section className="mp-section"><h3>Parts list</h3>
            {current.bom.map(row => <div key={row.name} className="mp-bom-row">
              <h4>{publicText(row.display_name || row.display_id)}</h4><p className="mp-muted">{publicText(row.display_id)} · {publicText(row.section)}</p>
              <dl className="mp-values">{Object.entries(row.fields).map(([name, field]) => <div key={name}>
                <dt>{fieldLabel(name)}</dt><dd>{field.confidence === "unsure" ? "Unavailable" : valueText(field.value)}
                  {field.value !== null && field.confidence !== "unsure" && (field.unit || field.currency) ? ` ${publicText(field.unit || field.currency || "")}` : ""}</dd></div>)}</dl>
            </div>)}
          </section>}
          {!hasDrawing && <p className="mp-muted">Drawing: Unavailable</p>}
        </>}
      </div>
      {debug?.enabled === true && <PartDebug part={current} debug={debug} />}
    </>}
  </article>;
}

function PartDebug({ part, debug }: { part: PartDetailResponse; debug: Extract<DebugContext, { enabled: true }> }) {
  return <details className="mp-debug"><summary>Debug</summary>
    {(part.synthetic || part.fixture) && <p>Declared synthetic fixture; not source evidence.</p>}
    <p>Model state: {part.model.state}</p>
    {part.model.message && <p>{publicText(part.model.message)}</p>}
    {part.model.stale_reason && <p>{publicText(part.model.stale_reason)}</p>}
    {part.model.unresolved_fields?.length ? <p>Unresolved model fields: {part.model.unresolved_fields.map(publicText).join(", ")}</p> : null}
    {part.weight_check && <div><h3>Weight check</h3><p>{part.weight_check.state}: {publicText(part.weight_check.message)}</p></div>}
    {part.review_items?.length ? <div><h3>Review items</h3>{part.review_items.map(item =>
      <button type="button" key={item.id} onClick={() => debug.on_open_review(item)}>Open review item</button>)}</div> : null}
    {part.drawing && <div><h3>Drawing evidence</h3><p>Source hash: {publicText(part.drawing.source_sha256)}</p>
      {Object.entries(part.drawing.fields).map(([name, field]) => <details key={name}><summary>{fieldLabel(name)}</summary>
        <p>Original: {field.original === null ? "Unavailable" : publicText(field.original)}</p>
        <p>Current value: {valueText(field.value)}</p>
        {field.note && <p>{publicText(field.note)}</p>}
        <MethodBadge debug={debug} method={field.method} badge={fieldLabel(name)} review={field.review}
          provenance={field.provenance} fact_name={field.name} />
      </details>)}</div>}
    {part.bom.map(row => <div key={row.name}><h3>{publicText(row.display_name || row.display_id)} · parts list evidence</h3>
      <p>Source hash: {publicText(row.source_sha256)}</p>
      {Object.entries(row.fields).map(([name, field]) => <details key={name}><summary>{fieldLabel(name)}</summary>
        <p>Original: {field.original === null ? "Unavailable" : publicText(field.original)}</p>
        <p>Current value: {valueText(field.value)}</p>
        {field.note && <p>{publicText(field.note)}</p>}
        {field.cleanup?.map((note, index) => <p key={index}>{publicText(note)}</p>)}
        <MethodBadge debug={debug} method={field.method} badge={fieldLabel(name)} review={field.review}
          provenance={field.provenance} fact_name={field.name} />
      </details>)}</div>)}
  </details>;
}

function PartStyles() {
  return <style>{`
    .meridian-part { color: #172b3a; font: 14px/1.6 system-ui, sans-serif; min-width: 0; }
    .meridian-part * { box-sizing: border-box; }
    .meridian-part .mp-heading { margin-bottom: 20px; }
    .meridian-part .mp-heading h2 { font-size: 21px; }
    .meridian-part .mp-muted, .meridian-part .mp-caption { color: #526777; }
    .meridian-part .mp-heading p { margin-top: 6px; font-size: 12px; }
    .meridian-part .mp-tabs { display: flex; gap: 8px; border-bottom: 1px solid #d9e1e7; padding-bottom: 12px; margin-bottom: 20px; }
    .meridian-part button[aria-selected="true"] { background: #e5f0f3; color: #124b5d; border-color: #b6d1da; font-weight: 600; }
    .meridian-part :is(button, select, summary, [tabindex]):focus-visible { outline: 3px solid #1675be; outline-offset: 3px; }
    .meridian-part h3 { font-size: 15px; font-weight: 650; margin: 0 0 12px; }
    .meridian-part h4 { font-size: 14px; font-weight: 650; margin: 0; }
    .meridian-part .mp-section + .mp-section { border-top: 1px solid #e0e7eb; padding-top: 20px; margin-top: 24px; }
    .meridian-part .mp-table-wrap { overflow-x: auto; }
    .meridian-part .mp-facts { border-collapse: collapse; width: 100%; text-align: left; }
    .meridian-part .mp-facts th, .meridian-part .mp-facts td { padding: 12px 8px; border-bottom: 1px solid #e0e7eb; vertical-align: top; }
    .meridian-part .mp-facts thead th { font-size: 11px; font-weight: 600; color: #526777; }
    .meridian-part .mp-facts tbody th { font-weight: 500; width: 28%; }
    .meridian-part .mp-selected { background: #fff7da; }
    .meridian-part .mp-bom-row + .mp-bom-row { margin-top: 20px; }
    .meridian-part .mp-values { margin: 12px 0; }
    .meridian-part .mp-values > div { display: grid; grid-template-columns: minmax(100px, 1fr) 2fr; gap: 12px; border-bottom: 1px solid #edf1f4; padding: 7px 0; }
    .meridian-part .mp-values dt { color: #526777; }
    .meridian-part .mp-values dd { margin: 0; overflow-wrap: anywhere; }
    .meridian-part .mp-drawing-tools { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
    .meridian-part .mp-drawing-tools select { font: inherit; border: 1px solid #bac7d0; border-radius: 5px; background: #fff; color: inherit; padding: 6px; }
    .meridian-part .mp-zoom { display: flex; align-items: center; gap: 6px; }
    .meridian-part .mp-zoom output { min-width: 48px; text-align: center; font-size: 12px; }
    .meridian-part .mp-canvas { max-height: 70vh; min-height: 160px; overflow: auto; border: 1px solid #cbd5df; border-radius: 7px; background: #edf1f4; }
    .meridian-part .mp-paper { position: relative; flex: none; margin: 0 auto; line-height: 0; background: #fff; }
    .meridian-part .mp-paper img { display: block; width: 100%; height: auto; }
    .meridian-part .mp-highlight { position: absolute; border: 2px solid #cf7800; background: #ffbd293b; pointer-events: none; min-width: 3px; min-height: 3px; }
    .meridian-part .mp-caption { margin-top: 10px; font-size: 12px; }
    .meridian-part .mp-message { padding: 30px 0; }
    .meridian-part .mp-message button { margin-top: 12px; }
    .meridian-part .mp-model-unavailable { border: 1px solid #d9e1e7; border-radius: 7px; padding: 12px; margin-bottom: 16px; }
    .meridian-part .mp-debug { margin-top: 24px; padding: 16px; border: 1px solid #cbd5df; border-radius: 7px; background: #f8fafc; overflow-wrap: anywhere; }
    .meridian-part .mp-debug summary { cursor: pointer; font-weight: 600; }
    .meridian-part .mp-debug p, .meridian-part .mp-debug button, .meridian-part .mp-debug > div, .meridian-part .mp-debug details { margin-top: 10px; }
    @media (max-width: 550px) { .meridian-part .mp-facts th, .meridian-part .mp-facts td { padding: 10px 5px; } .meridian-part .mp-values > div { grid-template-columns: 1fr 1.5fr; } }
  `}</style>;
}

export default PartPage;
