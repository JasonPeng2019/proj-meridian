import { Fragment, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  customer_review_status, SINGLE_MODEL_LABEL,
  type EvidenceProps, type SourceTagProps, type UndeterminedProps,
  type MethodBadgeProps, type WarningListProps, type ReviewStatusProps,
  type FactResult, type FactSource, type JsonValue, type DebugAccess,
  type PrepProvenance, type ChatWarning,
} from "../contracts";

const badge = "me-badge";
const action = "me-action";
const warning = "me-warning";

// Scoped to these widgets; no utility framework, global stylesheet or host
// wrapper is required. Every public widget includes its own style element.
function EvidenceStyles() {
  return <style>{`
    .meridian-evidence { color: #0f172a; font-family: inherit; font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; white-space: normal; }
    .meridian-evidence *, .meridian-evidence *::before, .meridian-evidence *::after { box-sizing: border-box; }
    .meridian-evidence p { margin: .4rem 0; }
    .meridian-evidence .me-badge { display: inline-flex; align-items: center; border: 1px solid #cbd5e1; border-radius: .35rem; padding: .125rem .5rem; font: inherit; font-size: 12px; font-weight: 600; line-height: 1.6; }
    .meridian-evidence .me-review { background: #f8fafc; color: #334155; }
    .meridian-evidence .me-source-button { background: #eff6ff; border-color: #bfdbfe; color: #1e40af; cursor: pointer; }
    .meridian-evidence .me-action { display: inline-block; border: 0; border-radius: .2rem; padding: .25rem; background: transparent; color: #1d4ed8; font: inherit; text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
    .meridian-evidence button:focus-visible, .meridian-evidence summary:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
    .meridian-evidence .me-warning { border: 1px solid #fcd34d; border-radius: .35rem; background: #fffbeb; color: #78350f; padding: .75rem; }
    .meridian-evidence .me-debug, .meridian-evidence .me-round { margin-top: .5rem; border: 1px solid #cbd5e1; border-radius: .35rem; padding: .75rem; background: #f8fafc; }
    .meridian-evidence summary { cursor: pointer; font-weight: 600; }
    .meridian-evidence .me-stack > * + * { margin-top: .5rem; }
    .meridian-evidence .me-verdict { margin: .5rem 0; border-left: 2px solid #94a3b8; padding-left: .5rem; }
    .meridian-evidence .me-small { font-size: 12px; }
    .meridian-evidence .me-muted { color: #475569; }
    .meridian-evidence .me-break { overflow-wrap: anywhere; }
    .meridian-evidence .me-source-row { display: block; margin-top: .5rem; border-top: 1px solid #cbd5e1; padding-top: .5rem; }
    .meridian-evidence.me-inline { display: inline-block; vertical-align: baseline; }
    .meridian-evidence.me-source-tag { position: relative; display: inline-block; vertical-align: baseline; }
    .meridian-evidence .me-source-popup { position: absolute; left: 0; top: 100%; z-index: 30; display: block; width: 20rem; max-width: 85vw; max-height: min(24rem, 65vh); overflow: auto; border: 1px solid #cbd5e1; border-radius: .5rem; padding: 1rem; background: #fff; color: #0f172a; text-align: left; box-shadow: 0 8px 24px #0f172a26; }
    .meridian-evidence .me-source-fact { display: block; margin-bottom: 1rem; }
    .meridian-evidence .me-source-fact:last-of-type { margin-bottom: .5rem; }
    .meridian-evidence .me-value { display: block; font-weight: 600; }
    .meridian-evidence .me-source-text { display: block; white-space: pre-wrap; overflow-wrap: anywhere; }
    .meridian-evidence.me-warning-list { list-style: none; padding: 0; margin: .5rem 0; }
    .meridian-evidence.me-warning-list > li + li { margin-top: .5rem; }
    .meridian-evidence .me-strong { font-weight: 600; }
    .meridian-evidence .me-answer { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
    @media (max-width: 480px) {
      .meridian-evidence .me-source-popup { position: fixed; top: 20vh; left: 5vw; width: 90vw; max-width: none; max-height: 65vh; }
    }
  `}</style>;
}

// Project only displayable fields, never serialize a payload/provenance wholesale.
// Text remains verbatim except for credentials and private filesystem locations.
function publicText(text: string): string {
  return text
    .replace(/\b(?:sk|sk-proj|sk-ant)-[A-Za-z0-9_-]+/g, "[credential withheld]")
    .replace(/\bBearer\s+[^\s"<>]+/gi, "[credential withheld]")
    .replace(/\b(?:api[_ -]?key|access[_ -]?token|password|secret)["']?\s*[:=]\s*["']?[^\s,;}]+/gi, "[credential withheld]")
    .replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"<>]*/g, "[private path withheld]")
    .replace(/(?:file:\/\/|\/(?:home|Users|root|tmp|var|mnt)\/|~\/)[^\s"<>]*/g, "[private path withheld]")
    .replace(/\[(?:cite|undetermined)\b[^\]\r\n]*(?:\]|$)/gi, "[reference]");
}

function valueText(value: JsonValue): string {
  if (typeof value === "string") return publicText(value);
  return publicText(JSON.stringify(value) ?? "null");
}

function sourceLabel(source: FactSource): string {
  const { target } = source;
  switch (target.kind) {
    case "drawing": return `${target.drawing_id ?? "Drawing"}${target.page ? ` · page ${target.page}` : ""}`;
    case "bom": return "Parts list";
    case "template": return "Reconstruction inputs";
    case "readme": return "Dataset README";
    case "part": return "Part";
  }
}

function statusFor(fact: FactResult) {
  const current: Record<string, string> = {};
  const conflicting = new Set<string>();
  const provenances = fact.sources.flatMap(source => source.provenance ? [source.provenance] : []);
  const add = (key: string | null | undefined, hash: string) => {
    if (!key) return;
    if (current[key] && current[key] !== hash) conflicting.add(key);
    current[key] = hash;
  };
  for (const source of fact.sources) {
    if (!source.source_sha256) continue;
    const hash = source.source_sha256;
    add(source.name, hash);
    add(source.target.drawing_id, hash);
    add(source.target.row_name, hash);
    // Bind input keys through declared source IDs; never copy a claimed input
    // hash into the current hashes or infer review from a method/badge string.
    for (const provenance of provenances) {
      const input = provenance.source.source_ids[source.name];
      add(input, hash);
      for (const reference of provenance.field_results?.[source.name]?.accepted?.source_ids ?? []) {
        const key = provenance.source.source_ids[reference];
        if (key && provenance.source.inputs[key] === hash) add(key, hash);
      }
    }
  }
  for (const key of conflicting) delete current[key];
  const usable = "value" in fact.display ? fact.display.value !== null :
    "values" in fact.display && fact.display.values.length > 0;
  const common = { usable, current_source_hashes: current };
  const human = customer_review_status({ ...common, review: fact.review });
  if (human === "Human reviewed") return human;
  // A fact with multiple sources is AI reviewed only if every supporting source
  // has current, field-bound review. Parsed/legacy/fallback sources confer none.
  if (fact.sources.length > 0 && fact.sources.every(source =>
    customer_review_status({ ...common, review: source.review,
      provenance: source.provenance, field_name: source.name }) === "AI reviewed")) return "AI reviewed";
  return human;
}

export function ReviewStatus({ status }: ReviewStatusProps) {
  return <span className="meridian-evidence"><EvidenceStyles /><span className={`${badge} me-review`}>{status}</span></span>;
}

function DisplayValue({ fact }: { fact: FactResult }) {
  const display = fact.display;
  if ("value" in display) return <span>{display.label ? `${publicText(display.label)} ` : ""}{display.value === null ? "Unavailable" : valueText(display.value)}{display.unit ? ` ${publicText(display.unit)}` : ""}</span>;
  if ("values" in display && display.values.length > 0) return <span>
    <span className="me-small me-muted">Printed options: </span>
    {display.values.map((value, index) => <Fragment key={index}>
      {index > 0 ? " / " : ""}{valueText(value)}
    </Fragment>)}{display.unit ? ` ${publicText(display.unit)}` : ""}
  </span>;
  return <span>Unavailable</span>;
}

function Preparation({ provenance }: { provenance: PrepProvenance }) {
  return <div className="me-stack">
    <p>{provenance.mode === "single_model_unverified" ? SINGLE_MODEL_LABEL : publicText(provenance.outcome)}</p>
    {provenance.rounds.map(round => <details key={round.round} className="me-round">
      <summary className="me-summary">Round {round.round}</summary>
      <p>Determination: {publicText(round.determination.status)}</p>
      {round.determination.failure && <p>{publicText(round.determination.failure.classification)}</p>}
      {round.determination.output && <>
        <p className="me-break">Candidate: {publicText(round.determination.output.candidate_sha256)}</p>
        <p className="me-break">Source: {publicText(round.determination.output.source_sha256)}</p>
        {Object.entries(round.determination.output.fields).map(([name, field]) => <div key={name}>
          <p>{publicText(name)}: {publicText(field.state)} — {publicText(field.reason)}</p>
          {field.value !== undefined && <p>Candidate: {valueText(field.value)}</p>}
          {field.options && <p>Candidate options: {field.options.map(valueText).join(" / ")}</p>}
          <p>Evidence: {field.source_ids?.map(publicText).join(", ")}</p>
        </div>)}
      </>}
      {round.verification ? <>
        <p>Verification: {publicText(round.verification.status)}</p>
        <p className="me-break">Candidate: {publicText(round.verification.candidate_sha256)}</p>
        <p className="me-break">Source: {publicText(round.verification.source_sha256)}</p>
        {round.verification.failure && <p>{publicText(round.verification.failure.classification)}</p>}
        {round.verification.output && Object.entries(round.verification.output.fields).map(([name, field]) =>
          <div key={name} className="me-verdict">
            <p>{publicText(name)}: {publicText(field.verdict)}</p>
            <p>{publicText(field.reason)}</p>
            <p>Evidence: {field.source_ids.map(publicText).join(", ")}</p>
          </div>)}
      </> : <p>No verification attempt recorded.</p>}
    </details>)}
  </div>;
}

export function MethodBadge({ debug, method, badge: text, review, provenance, fact_name }: MethodBadgeProps) {
  if (debug.enabled !== true) return null;
  return <div className="meridian-evidence me-stack">
    <EvidenceStyles />
    <span className={badge}>{publicText(text)}</span>{" "}
    <span className="me-small">{publicText(method)}</span>
    {review && <p>Review: {publicText(review.status ?? "not_reviewed")}
      {review.by ? ` · ${publicText(review.by)}` : ""}{review.at ? ` · ${publicText(review.at)}` : ""}</p>}
    {provenance && <Preparation provenance={provenance} />}
    {fact_name && debug.on_open_history && <button type="button" className={action}
      onClick={() => debug.on_open_history?.(fact_name)}>Open decision history</button>}
  </div>;
}

function FactDebug({ fact, debug }: { fact: FactResult; debug: DebugAccess }) {
  return <details className="me-debug">
    <summary className="me-summary">Debug</summary>
    <div className="me-stack">
      <p>{publicText(fact.rule)}</p>
      <p>{publicText(fact.provenance_badge ?? fact.badge)}</p>
      {"reason" in fact.display && <div className={warning}>
        <p>Undetermined · {publicText(fact.display.reason)}</p>
        <p>{publicText(fact.display.message)}</p>
      </div>}
      {"values" in fact.display && <p>{publicText(fact.display.message)}</p>}
      {fact.snapshot_note && <p>These values describe the supplied snapshot.</p>}
      {fact.correction && <div>
        <p>Original: {valueText(fact.correction.original)}</p>
        <p>Correction: {valueText(fact.correction.corrected)}</p>
        <p>{publicText(fact.correction.by)} · {publicText(fact.correction.at)}</p>
        <p>Decision: {publicText(fact.correction.decision_id)}</p>
      </div>}
      {fact.sources.map((source, index) => <div key={index} className="me-source-row me-stack">
        <p className="me-break">{publicText(source.name)}</p>
        {source.source_sha256 && <p className="me-break">Source hash: {publicText(source.source_sha256)}</p>}
        {source.note && <p>{publicText(source.note)}</p>}
        {source.confidence && <p>Confidence: {publicText(source.confidence)}</p>}
        <MethodBadge debug={debug} method={source.method} badge={sourceLabel(source)}
          review={source.review} provenance={source.provenance} />
      </div>)}
      {fact.review_item?.id && fact.review_item.href && <button type="button" className={action}
        onClick={() => debug.on_open_review(fact.review_item!)}>Waiting for review · Open Review</button>}
      {debug.on_open_history && <button type="button" className={action}
        onClick={() => debug.on_open_history?.(fact.fact)}>Open decision history</button>}
    </div>
  </details>;
}

export function Undetermined({ fact, debug }: UndeterminedProps) {
  return <span className="meridian-evidence me-inline">
    <EvidenceStyles />
    <span className="me-muted">Unavailable</span>
    {debug?.enabled === true && <FactDebug fact={fact} debug={debug} />}
  </span>;
}

export function SourceTag({ facts, on_open_source, debug }: SourceTagProps) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const open = !dismissed && (hovered || pinned);
  const count = facts.reduce((total, fact) => total + fact.sources.length, 0);
  return <span className="meridian-evidence me-source-tag"
    onMouseEnter={() => { setHovered(true); setDismissed(false); }} onMouseLeave={() => setHovered(false)}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) { setPinned(false); setHovered(false); } }}
    onKeyDown={event => { if (event.key === "Escape") { setPinned(false); setDismissed(true); trigger.current?.focus(); } }}>
    <EvidenceStyles />
    <button type="button" ref={trigger} className={`${badge} me-source-button`}
      aria-expanded={open} aria-controls={id} onClick={() => { setPinned(!pinned); setDismissed(false); }}>
      {count ? `Sources · ${count}` : "Source unavailable"}
    </button>
    {open && <span id={id} role="group" aria-label="Citation sources"
      className="me-source-popup">
      {facts.map((fact, factIndex) => <span key={`${fact.fact}-${factIndex}`} className="me-source-fact me-stack">
        <span className="me-value"><DisplayValue fact={fact} /></span>
        <ReviewStatus status={statusFor(fact)} />
        {fact.sources.length === 0 && <span className="me-value me-muted">No source supplied.</span>}
        {fact.sources.map((source, index) => <span key={index} className="me-source-row me-stack">
          <button type="button" className={action} onClick={() => on_open_source(source.target)}>
            {publicText(sourceLabel(source))}
          </button>
          <span className="me-source-text">{valueText(source.says)}</span>
        </span>)}
        {debug?.enabled === true && <FactDebug fact={fact} debug={debug} />}
      </span>)}
      <button type="button" className={action} onClick={() => { setPinned(false); setDismissed(true); trigger.current?.focus(); }}>Close sources</button>
    </span>}
  </span>;
}

export function WarningList({ debug, warnings }: WarningListProps) {
  if (debug.enabled !== true || warnings.length === 0) return null;
  return <><EvidenceStyles /><ul aria-label="Evidence warnings" className="meridian-evidence me-warning-list">
    {warnings.map((item, index) => <li key={index} className={warning}>
      <p className="me-strong">{publicText(item.code.replaceAll("_", " "))}</p>
      <p>{publicText(item.message)}</p>
    </li>)}
  </ul></>;
}

export function Evidence({ response, on_open_source, debug }: EvidenceProps) {
  const points = Array.from(response.text);
  const output: ReactNode[] = [];
  const warnings: ChatWarning[] = [...response.warnings];
  // Scan marker-looking text only to remove it. Only the server's exact,
  // valid span can authorize a citation. Offsets are Unicode code points.
  const expression = /\[(cite|undetermined)\b[^\]\r\n]*(?:\]|(?=\r?\n)|$)/gi;
  let cursor = 0;
  for (const match of response.text.matchAll(expression)) {
    const start = Array.from(response.text.slice(0, match.index)).length;
    const end = start + Array.from(match[0]).length;
    output.push(publicText(points.slice(cursor, start).join("")));
    const marker = response.markers?.find(item => item.start === start && item.end === end && item.raw === match[0]);
    const facts = marker?.names.map(name => Object.hasOwn(response.facts, name) ? response.facts[name] : undefined) ?? [];
    const valid = marker?.valid && marker.kind === match[1].toLowerCase() && facts.length > 0 &&
      facts.every(fact => fact && (marker.kind !== "undetermined" || "reason" in fact.display));
    if (valid) {
      const resolved = facts.filter((fact): fact is FactResult => fact !== undefined);
      output.push(<Fragment key={start}>
        {marker.kind === "undetermined" && <span>Unavailable </span>}
        <SourceTag facts={resolved} on_open_source={on_open_source} debug={debug} />
      </Fragment>);
    } else {
      output.push(<span key={start} className="me-muted">Unavailable</span>);
      warnings.push({ code: marker?.error ?? "invalid_citation", message: "This reference could not be validated against the supplied facts." });
    }
    cursor = end;
  }
  output.push(publicText(points.slice(cursor).join("")));
  return <div className="meridian-evidence">
    <EvidenceStyles />
    <div className="me-answer">{output.map((node, index) => <Fragment key={index}>{node}</Fragment>)}</div>
    {debug?.enabled === true && <details className="me-debug">
      <summary className="me-summary">Debug</summary>
      <WarningList debug={debug} warnings={warnings} />
    </details>}
  </div>;
}
