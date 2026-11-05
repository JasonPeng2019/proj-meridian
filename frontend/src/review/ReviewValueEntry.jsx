import React, {useEffect, useId, useRef, useState} from 'react';
import {api, titleCase} from '../api';
import ReviewValueInput from './ReviewValueInput';

const unwrap = value => value && typeof value === 'object' && 'value' in value ? value.value : value;
function readable(value, target) {
  if (target.endsWith('/template/outline') && value && typeof value === 'object') {
    const shape = unwrap(value.type);
    if (shape === 'rectangle') return `Rectangle: ${unwrap(value.length)} × ${unwrap(value.width)} mm`;
    if (shape === 'circle') return `Circle: outer diameter ${unwrap(value.outer_diameter)} mm`;
    if (shape === 'ring') return `Ring: outer diameter ${unwrap(value.outer_diameter)} mm; inner diameter ${unwrap(value.inner_diameter)} mm`;
  }
  if (Array.isArray(value)) return `${value.length} ${target.endsWith('/features_review') ? 'supported hole/slot entries' : 'entries'}`;
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') {
    const tail = target.split('/').at(-1);
    const unit = tail.endsWith('_g') ? ' g' : /(?:thickness|length|width|diameter|radius|depth|offset|^x$|^y$)/.test(tail) ? ' mm' : tail.endsWith('angle') ? ' degrees' : '';
    return `${value}${unit}`;
  }
  return typeof value === 'string' ? value : 'Structured value';
}
function guidance(item) {
  const tail = item.target?.split('/').at(-1);
  if (tail === 'outline') return ['Choose rectangle, square, circle or ring, and describe its dimensions. Use mm or state another unit.', 'A rectangle, 80 mm long and 40 mm wide.'];
  if (tail === 'features_review') return ['Describe holes or slots, their sizes, top/bottom face, centre positions and whether they pass through. Missing positions need clarification.', 'One plain through hole on the top face, diameter 4.5 mm, centre x = 0 mm and y = 0 mm.'];
  if (tail === 'features_complete') return ['Say whether the complete feature inventory has been checked: true or false.', 'False — the side holes still need checking.'];
  return ['Use ordinary words, numbers and units. You do not need to write JSON or match the internal format.', `The reviewed ${titleCase(tail).toLowerCase()} is …`];
}

export default function ReviewValueEntry({item, onSave, busy}) {
  const id = useId();
  const [mode, setMode] = useState('describe'), [input, setInput] = useState('');
  const [guided, setGuided] = useState({valid: false}), [preview, setPreview] = useState(null);
  const [parsing, setParsing] = useState(false), [error, setError] = useState('');
  const request = useRef(0);
  useEffect(() => () => { request.current++; }, []);
  const [hint, example] = guidance(item);
  const raw = mode === 'describe' ? input : guided.valid ? JSON.stringify(guided.value) : '';
  useEffect(() => { request.current++; setPreview(null); setError(''); setParsing(false); }, [raw, mode]);
  const parse = async () => {
    const version = ++request.current;
    setParsing(true); setError(''); setPreview(null);
    try {
      const result = await api('/api/review-parse', {item_id: item.id, input: raw});
      if (version === request.current) setPreview(result);
    } catch (failure) {
      if (version === request.current) setError(failure.message);
    } finally {
      if (version === request.current) setParsing(false);
    }
  };
  return <section className="review-value-entry" aria-label="Reviewed value entry">
    <h4>Enter a reviewed value</h4>
    <div className="review-entry-modes" role="group" aria-label="Input method">
      <button type="button" aria-pressed={mode === 'describe'} disabled={busy || parsing} onClick={() => setMode('describe')}>Describe it</button>
      <button type="button" aria-pressed={mode === 'guided'} disabled={busy || parsing} onClick={() => setMode('guided')}>Guided fields</button>
    </div>
    {mode === 'describe' ? <>
      <label className="review-value-label" htmlFor={id}>Your reviewed value</label>
      <p id={`${id}-hint`} className="review-value-hint">{hint}</p>
      <textarea id={id} aria-describedby={`${id}-hint`} value={input} onChange={event => setInput(event.target.value)} disabled={busy || parsing} maxLength={12000} rows={4} placeholder={example}/>
    </> : <ReviewValueInput item={item} onChange={setGuided} disabled={busy || parsing}/>}
    <p className="review-value-hint">AI handles formatting. Check the interpretation before saving; it does not verify your engineering decision.</p>
    <button className="button secondary" disabled={busy || parsing || !raw.trim()} onClick={parse}>{parsing ? 'Interpreting…' : 'Interpret input'}</button>
    {error && <p className="review-value-error" role="alert">{error}</p>}
    {preview?.status === 'needs_clarification' && <div className="review-parsed-preview" role="status">
      <h4>More information needed</h4><p>{preview.summary}</p>
      {preview.questions?.length > 0 && <ul>{preview.questions.map((question, index) => <li key={index}>{question}</li>)}</ul>}
    </div>}
    {preview?.status === 'ready' && <div className="review-parsed-preview" role="status">
      <h4>What will be saved</h4><p className="review-parsed-value">{readable(preview.value, item.target)}</p>
      <p>{preview.summary}</p>
      {preview.value !== null && typeof preview.value === 'object' && <details className="review-value-example"><summary>Formatted data</summary><pre><code>{JSON.stringify(preview.value, null, 2)}</code></pre></details>}
    </div>}
    <button className="button primary review-save-value" disabled={busy || parsing || preview?.status !== 'ready' || !preview?.receipt} onClick={() => {onSave(preview.receipt); setPreview(null);}}>Save reviewed value</button>
  </section>;
}
