import React, {useEffect, useId, useMemo, useState} from 'react';

const shapeFields = {
  rectangle: [['length', 'Length'], ['width', 'Width']],
  square: [['side', 'Side']],
  circle: [['outer_diameter', 'Outer diameter']],
  ring: [['outer_diameter', 'Outer diameter'], ['inner_diameter', 'Inner diameter']],
};
const known = value => ({state: 'known', value});
const decimal = value => /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()) && Number.isFinite(Number(value));
const invalid = error => ({valid: false, value: undefined, error});
const valid = value => ({valid: true, value, error: ''});
const labelFor = field => field.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
const featureExample = [{kind: 'hole', face: 'top', x: 0, y: 0, diameter: 4.5, through: true, hole_type: 'plain'}];

function inputKind(item, tail) {
  if (item.target?.endsWith('/template/outline')) return 'outline';
  if (tail === 'features_review' || Array.isArray(item.value)) return 'array';
  if (typeof item.value === 'boolean' || tail === 'features_complete') return 'boolean';
  if (typeof item.value === 'number' || /(?:^|_)(thickness|length|width|diameter|radius|depth|offset|x|y|angle|count)$/.test(tail)) return 'number';
  if (item.value !== null && typeof item.value === 'object') return 'object';
  return 'text';
}

function outlineValue(shape, dimensions) {
  if (!shape) return invalid('Choose a supported outer shape.');
  for (const [field, label] of shapeFields[shape]) {
    if (!dimensions[field]?.trim()) return invalid(`Enter ${label.toLowerCase()} in millimetres.`);
    if (!decimal(dimensions[field]) || Number(dimensions[field]) <= 0) return invalid(`${label} must be a finite number greater than zero.`);
  }
  if (shape === 'ring' && Number(dimensions.inner_diameter) >= Number(dimensions.outer_diameter)) return invalid('Inner diameter must be smaller than outer diameter.');
  if (shape === 'square') return valid({state: 'known', type: 'rectangle', length: known(Number(dimensions.side)), width: known(Number(dimensions.side))});
  return valid({state: 'known', type: shape, ...Object.fromEntries(shapeFields[shape].map(([field]) => [field, known(Number(dimensions[field]))]))});
}

function Example({value, json = false}) {
  return <details className="review-value-example">
    <summary>{json ? 'Example JSON (copy and edit)' : 'Example format'}</summary>
    <p className="review-value-hint">Example only. Enter values established by the source evidence.</p>
    <pre><code>{json ? JSON.stringify(value, null, 2) : value}</code></pre>
  </details>;
}

/** Blank inputs deliberately require an explicit review; examples never populate them. */
export default function ReviewValueInput({item, onChange, disabled = false}) {
  const id = useId(), hintId = `${id}-hint`, errorId = `${id}-error`;
  const [raw, setRaw] = useState(''), [shape, setShape] = useState('');
  const [dimensions, setDimensions] = useState({}), [touched, setTouched] = useState(false);
  const tail = (item.target || '').split('/').at(-1) || 'value';
  const kind = inputKind(item, tail);
  const signed = /(?:^|_)(x|y|offset|angle)$/.test(tail);
  const count = /(?:^|_)count$/.test(tail);
  const angle = /(?:^|_)angle$/.test(tail);
  const size = /(?:^|_)(thickness|length|width|diameter|radius|depth)$/.test(tail);
  const result = useMemo(() => {
    if (kind === 'outline') return outlineValue(shape, dimensions);
    if (!raw.trim()) return invalid('Enter a reviewed value.');
    if (kind === 'boolean') return raw === 'true' ? valid(true) : raw === 'false' ? valid(false) : invalid('Choose true or false.');
    if (kind === 'number') {
      const number = Number(raw);
      if (!decimal(raw)) return invalid('Enter a finite decimal number without a unit suffix.');
      if (count && (!Number.isInteger(number) || number <= 0)) return invalid('Enter a whole number greater than zero.');
      if (size && number <= 0) return invalid('Enter a number greater than zero.');
      return valid(number);
    }
    if (kind === 'array' || kind === 'object') {
      let parsed;
      try { parsed = JSON.parse(raw); } catch { return invalid('Enter valid JSON: use double quotes and no trailing commas.'); }
      if (kind === 'array' && !Array.isArray(parsed)) return invalid('Enter a JSON array enclosed in [ and ].');
      if (kind === 'object' && (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object')) return invalid('Enter a JSON object enclosed in { and }.');
      return valid(parsed);
    }
    return valid(raw);
  }, [kind, raw, shape, dimensions, count, size]);
  useEffect(() => { onChange(result); }, [onChange, result]);

  const hasError = touched && !result.valid;
  const description = `${hintId}${hasError ? ` ${errorId}` : ''}`;
  const update = event => { setTouched(true); setRaw(event.target.value); };
  const shared = {disabled, 'aria-describedby': description, 'aria-invalid': hasError || undefined, onBlur: () => setTouched(true)};
  const fieldLabel = labelFor(tail);
  let control;

  if (kind === 'outline') {
    const exampleShape = shape || 'rectangle';
    const exampleDimensions = {length: '80', width: '40', side: '40', outer_diameter: '40', inner_diameter: '20'};
    control = <>
      <p id={hintId} className="review-value-hint">Supported flat shapes: rectangle, square, circle or ring. Enter positive dimensions in mm. Thickness is a separate field. Bent, formed and curved profiles are unsupported.</p>
      <label className="review-value-label" htmlFor={`${id}-shape`}>Outer shape</label>
      <select {...shared} id={`${id}-shape`} value={shape} onChange={event => { setTouched(true); setShape(event.target.value); setDimensions({}); }}>
        <option value="">Choose a shape</option>
        <option value="rectangle">Rectangle</option><option value="square">Square</option><option value="circle">Circle</option><option value="ring">Ring</option>
      </select>
      {shape && <div className="review-value-dimensions">{shapeFields[shape].map(([field, label]) => <label className="review-value-label" key={field} htmlFor={`${id}-${field}`}>
        {label} (mm)
        <input {...shared} id={`${id}-${field}`} type="text" inputMode="decimal" value={dimensions[field] || ''} placeholder={field === 'inner_diameter' ? 'e.g. 20' : 'e.g. 40'} onChange={event => { setTouched(true); setDimensions(previous => ({...previous, [field]: event.target.value})); }}/>
      </label>)}</div>}
      {shape === 'ring' && <p className="review-value-hint">Inner diameter must be smaller than outer diameter.</p>}
      {shape === 'square' && <p className="review-value-hint">A square is saved as a rectangle with equal length and width.</p>}
      <Example json value={outlineValue(exampleShape, exampleDimensions).value}/>
    </>;
  } else if (kind === 'boolean') {
    control = <>
      <label className="review-value-label" htmlFor={id}>{fieldLabel}</label>
      <p id={hintId} className="review-value-hint">Allowed values: true or false. No units.{tail === 'features_complete' ? ' True means the full feature inventory has been checked.' : ''}</p>
      <select {...shared} id={id} value={raw} onChange={update}><option value="">Choose a value</option><option value="true">true</option><option value="false">false</option></select>
      <Example value="true"/>
    </>;
  } else if (kind === 'number') {
    const format = count ? 'A whole number greater than zero; no units.' : size ? 'A finite number greater than zero, in mm.' : angle ? 'A finite signed number in degrees.' : signed ? 'A finite signed number in mm; zero is allowed.' : 'A finite number in the source field’s unit.';
    control = <>
      <label className="review-value-label" htmlFor={id}>{fieldLabel}{size || signed && !angle ? ' (mm)' : angle ? ' (degrees)' : ''}</label>
      <p id={hintId} className="review-value-hint">{format} Enter the number only, without a unit suffix.</p>
      <input {...shared} id={id} type="text" inputMode={count ? 'numeric' : 'decimal'} value={raw} onChange={update} placeholder={count ? 'e.g. 4' : signed ? 'e.g. -12.5' : 'e.g. 4.5'}/>
      <Example value={count ? '4' : signed ? '-12.5' : '4.5'}/>
    </>;
  } else if (kind === 'array' || kind === 'object') {
    const features = tail === 'features_review';
    const example = features ? featureExample : item.value && typeof item.value === 'object' ? item.value : kind === 'array' ? ['source value'] : {field: 'source value'};
    control = <>
      <label className="review-value-label" htmlFor={id}>{features ? 'Reviewed geometry features' : fieldLabel} (JSON {kind})</label>
      <p id={hintId} className="review-value-hint">{features ? 'Enter an array of source-dimensioned holes, slots or corner clips. All sizes and positions use mm. Top/bottom holes use x/y; side holes also require z and an entry on the named rectangle face. Use true/false for through; blind cuts require depth. Corner clips use the fields listed below.' : `Enter a JSON ${kind}, using double quotes and no trailing commas. Preserve the field names and value types shown in the example; keep units consistent with the source.`}</p>
      <textarea {...shared} id={id} className="review-value-json" rows={6} value={raw} onChange={update} spellCheck={false} placeholder={kind === 'array' ? '[ ... ]' : '{ ... }'}/>
      {features && <details className="review-feature-format">
        <summary>Allowed feature fields</summary>
        <dl className="review-format-fields">
          <dt>kind</dt><dd>"hole", "slot" or "corner_chamfer"</dd>
          <dt>face</dt><dd>"top" or "bottom"; plain/threaded side holes can use "x_min", "x_max", "y_min" or "y_max".</dd>
          <dt>x, y</dt><dd>Centre coordinates in mm in the template coordinate system; signed decimal numbers.</dd>
          <dt>through</dt><dd>true or false. For false, add depth in mm.</dd>
          <dt>Hole</dt><dd>diameter in mm; hole_type is "plain", "threaded", "counterbored" or "countersunk". Threads use the supplied drill diameter with a cosmetic thread label.</dd>
          <dt>Counterbore</dt><dd>Add counterbore_diameter and counterbore_depth in mm.</dd>
          <dt>Countersink</dt><dd>Add countersink_diameter in mm and countersink_angle in degrees.</dd>
          <dt>Slot</dt><dd>length and width in mm, with length at least width; direction in degrees.</dd>
          <dt>Side hole</dt><dd>Add z in mm, strictly inside the plate thickness. Global x/y must locate the entry on the named side face. Blind depth is measured into that side. Supply each position separately.</dd>
          <dt>Corner clip</dt><dd>Use corners: an array chosen from "x_min_y_min", "x_min_y_max", "x_max_y_min", "x_max_y_max"; add positive x_setback and y_setback in mm. These cut through the entire thickness; omit face/x/y/through.</dd>
        </dl>
        <p className="review-value-hint">An empty array [] records no supported cuts; it does not confirm the full feature inventory. Missing or unsupported features still need a separate disposition.</p>
      </details>}
      <Example json value={example}/>
    </>;
  } else {
    const multiline = /(?:^|_)(notes?|reason)$/.test(tail);
    const example = typeof item.value === 'string' && item.value.trim() ? item.value : multiline ? 'Checked against the source drawing.' : 'Source text';
    control = <>
      <label className="review-value-label" htmlFor={id}>{fieldLabel}</label>
      <p id={hintId} className="review-value-hint">Enter non-empty plain text as shown in the source. No JSON quotation marks are needed; include units only when they are part of the text.</p>
      {multiline ? <textarea {...shared} id={id} rows={3} value={raw} onChange={update}/> : <input {...shared} id={id} type="text" value={raw} onChange={update}/>}
      <Example value={example}/>
    </>;
  }

  return <div className="review-value-input">
    {control}
    {hasError && <p id={errorId} className="review-value-error" role="alert">{result.error}</p>}
  </div>;
}
