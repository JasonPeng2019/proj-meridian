import { useEffect, useId, useState } from "react";
import type { PartsProps, PartsRequest, PartSummary } from "../contracts";

export function Parts({ api, on_open_part, initial_query, debug }: PartsProps) {
  const [query, setQuery] = useState<PartsRequest>(() => ({ ...initial_query }));
  const [search, setSearch] = useState(initial_query?.q ?? "");
  const [parts, setParts] = useState<PartSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const searchId = useId();

  useEffect(() => {
    let active = true;
    setLoading(true); setFailed(false);
    api.parts(query).then(result => {
      if (active) setParts(result);
    }).catch(() => {
      if (active) setFailed(true);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [api, query, attempt]);

  return <section className="meridian-parts" aria-label="Part inventory">
    <PartsStyles />
    <form className="ml-search" onSubmit={event => {
      event.preventDefault(); setQuery(current => ({ ...current, q: search.trim() }));
    }}>
      <label htmlFor={searchId}>Find a part</label>
      <div className="ml-search-row">
        <input id={searchId} type="search" value={search} onChange={event => setSearch(event.target.value)}
          placeholder="Search part names, drawing IDs or materials" />
        <button type="submit">Search</button>
        {(search || query.q) && <button type="button" onClick={() => {
          setSearch(""); setQuery(current => ({ ...current, q: "" }));
        }}>Clear</button>}
      </div>
    </form>
    {loading && <p className="ml-muted" role="status">Loading parts…</p>}
    {failed && <div role="alert" className="ml-message"><p>Could not load parts. Try again.</p>
      <button type="button" onClick={() => setAttempt(value => value + 1)}>Try again</button></div>}
    {!loading && !failed && <>
      <p className="ml-count" role="status">{parts.length} {parts.length === 1 ? "part" : "parts"}{query.q ? ` matching “${query.q}”` : ""}</p>
      {parts.length === 0 ? <p className="ml-message">{query.q
        ? "No parts match this search. Try a drawing ID or a shorter name."
        : "No parts are available yet."}</p> : <ul className="ml-list">{parts.map(part =>
        <li key={part.id} className="ml-part">
          <div className="ml-part-info"><h2><button type="button" className="ml-name"
            onClick={() => on_open_part({ part_id: part.id, tab: "detail" })}>{part.display_name || part.id}</button></h2>
            <p className="ml-id">{part.id}</p>
            <p className="ml-muted">{part.section || "Section unavailable"}</p>
            <dl className="ml-availability"><div><dt>Drawing</dt><dd>{part.has_drawing ? "Available" : "Unavailable"}</dd></div>
              <div><dt>3D model</dt><dd>{part.has_3d && ["available", "stale"].includes(part.model_state) ? "Available" : "Unavailable"}</dd></div></dl>
          </div>
          <div className="ml-actions"><button type="button" onClick={() => on_open_part({ part_id: part.id, tab: "detail" })}>Open part</button>
            {part.has_drawing && <button type="button" onClick={() => on_open_part({ part_id: part.id, tab: "drawing" })}>Open drawing</button>}</div>
          {debug?.enabled === true && <details className="ml-debug"><summary>Debug</summary>
            <p>Model state: {part.model_state}</p>
            {(part.synthetic || part.fixture) && <p>Declared synthetic fixture; not source evidence.</p>}
            {part.weight_check && <p>Weight check: {part.weight_check.state}</p>}
            {part.review_items?.map(item => <button type="button" key={item.id} onClick={() => debug.on_open_review(item)}>Open review item</button>)}
          </details>}
        </li>)}</ul>}
    </>}
  </section>;
}

function PartsStyles() {
  return <style>{`
    .meridian-parts { color: #172b3a; font: 14px/1.6 system-ui, sans-serif; }
    .meridian-parts * { box-sizing: border-box; }
    .meridian-parts .ml-search { display: grid; gap: 8px; margin-bottom: 24px; }
    .meridian-parts label { font-weight: 600; }
    .meridian-parts .ml-search-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .meridian-parts input { min-width: 180px; flex: 1; border: 1px solid #bac7d0; border-radius: 7px; padding: .65rem .8rem; font: inherit; background: #fff; color: inherit; }
    .meridian-parts button { font: inherit; cursor: pointer; }
    .meridian-parts :is(button, input, summary):focus-visible { outline: 3px solid #1675be; outline-offset: 3px; }
    .meridian-parts .ml-muted, .meridian-parts .ml-id, .meridian-parts .ml-count { color: #526777; }
    .meridian-parts .ml-count { margin-bottom: 12px; }
    .meridian-parts .ml-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }
    .meridian-parts .ml-part { border: 1px solid #d9e1e7; border-radius: 9px; padding: 18px; display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }
    .meridian-parts .ml-part-info { flex: 1; min-width: 180px; }
    .meridian-parts h2 { margin: 0; font-size: 17px; }
    .meridian-parts .ml-name { border: 0; background: none; text-align: left; color: #124b5d; font-weight: 650; padding: 0; border-radius: 0; }
    .meridian-parts .ml-name:hover { text-decoration: underline; background: none; }
    .meridian-parts .ml-id { font-size: 12px; overflow-wrap: anywhere; }
    .meridian-parts .ml-availability { display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 12px 0 0; font-size: 12px; }
    .meridian-parts .ml-availability > div { display: flex; gap: 6px; }
    .meridian-parts dt { color: #526777; }
    .meridian-parts dd { margin: 0; }
    .meridian-parts .ml-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .meridian-parts .ml-message { padding: 20px 0; }
    .meridian-parts .ml-message button { margin-top: 12px; }
    .meridian-parts .ml-debug { flex-basis: 100%; border-top: 1px solid #d9e1e7; padding-top: 12px; }
    .meridian-parts .ml-debug summary { cursor: pointer; }
    .meridian-parts .ml-debug p, .meridian-parts .ml-debug button { margin-top: 8px; }
  `}</style>;
}

export default Parts;
