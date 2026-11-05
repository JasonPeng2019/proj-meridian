import React, {useEffect, useRef, useState} from 'react';
import {ArrowUpRight, X} from 'lucide-react';
import {api, partURL, pathKey, textValue, titleCase} from '../api';
import {ErrorMessage, Loading} from '../components';
import {DrawingViewer} from '../part/PartPage';

export default function SourceInspector({reference, onClose, navigate}) {
  const name = reference?.name;
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState('');
  const modal = useRef(null);
  const closeButton = useRef(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    let live = true;
    setLoaded(null);
    setError('');
    if (!name) return;
    async function load() {
      try {
        const data = await api(`/api/review-source?name=${encodeURIComponent(name)}`);
        let part = null;
        if (data.kind === 'drawing') {
          if (!data.part_key) throw new Error('The source drawing has no part reference.');
          part = await api(`/api/parts/${pathKey(data.part_key)}`);
        }
        if (live) setLoaded({name, data, part});
      } catch (e) {
        if (live) setError(e.message || 'The source material could not be loaded.');
      }
    }
    load();
    return () => { live = false; };
  }, [name]);

  useEffect(() => {
    const previousFocus = document.activeElement;
    closeButton.current?.focus();
    const onKeyDown = event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close.current?.();
      } else if (event.key === 'Tab') {
        const elements = [...(modal.current?.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') || [])]
          .filter(element => element.getClientRects().length);
        const first = elements[0], last = elements.at(-1);
        if (!first) {
          event.preventDefault();
          modal.current?.focus();
        } else if (event.shiftKey && (document.activeElement === first || !modal.current?.contains(document.activeElement))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !modal.current?.contains(document.activeElement))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  if (!name) return null;
  const data = loaded?.name === name ? loaded.data : null;
  const part = loaded?.name === name ? loaded.part : null;
  const open = url => { navigate(url); onClose(); };
  const fact = data?.kind === 'drawing' ? {
    fact: name,
    field: name.split('/').at(-1),
    display: {state: 'value', value: data.original ?? data.value},
    sources: [{name, page: data.page, box: data.box, part_key: data.part_key}],
  } : null;
  const row = data?.row;
  const passage = data?.passage;

  return <div className="modal-scrim" onClick={onClose}>
    <section className="review-source-modal" role="dialog" aria-modal="true" aria-label="Source material" ref={modal} tabIndex={-1} onClick={event => event.stopPropagation()}>
      <header className="review-source-header">
        <div><div className="eyebrow">ORIGINAL SOURCE MATERIAL</div><h2>{data?.label || reference.label || name}</h2></div>
        <button className="icon-button" ref={closeButton} aria-label="Close source material" onClick={onClose}><X size={19}/></button>
      </header>
      <div className="review-source-body">
        {error ? <ErrorMessage>{error}</ErrorMessage> : !data ? <Loading label="Opening source material..."/> : data.kind === 'drawing' ? <>
          <div className="review-source-actions row wrap">
            <button className="button secondary" onClick={() => open(partURL(data.part_key, '2d', {fact: name}))}>Open full drawing <ArrowUpRight size={14}/></button>
            <a className="button secondary" href={`/api/parts/${pathKey(data.part_key)}/pdf`} target="_blank" rel="noopener noreferrer">Original PDF <ArrowUpRight size={14}/></a>
          </div>
          {!data.box && <p className="muted">No exact region was recorded; inspect the complete drawing.</p>}
          <div className="review-source-drawing"><DrawingViewer part={part} fact={fact} focusSource/></div>
        </> : data.kind === 'bom' ? <>
          <div className="review-source-metadata">
            <h3>{row?.display_name || 'Original parts list row'}</h3>
            <dl>
              <dt>Row ID</dt><dd>{row?.display_id || row?.name || 'Not recorded'}</dd>
              <dt>Section</dt><dd>{textValue(row?.section)}</dd>
              <dt>Source path</dt><dd>{textValue(data.source_path ?? row?.source_path)}</dd>
              <dt>Source row</dt><dd>{textValue(data.source_row ?? row?.source_row)}</dd>
            </dl>
          </div>
          <div className="review-source-table-wrap"><table className="evidence-table review-source-table">
            <caption>Original parts list row and cleaned values</caption>
            <thead><tr><th scope="col">Field</th><th scope="col">Original</th><th scope="col">Cleaned</th></tr></thead>
            <tbody>{Object.entries(row?.fields || {}).map(([field, value]) => <tr key={field} className={data.name === value.name ? 'source-field-focus' : undefined}>
              <th scope="row">{titleCase(field)}</th><td className="source-verbatim">{textValue(value.original)}</td><td className="source-verbatim">{textValue(value.value)}</td>
            </tr>)}</tbody>
          </table></div>
        </> : data.kind === 'readme' ? <>
          <div className="review-source-actions row wrap"><button className="button secondary" onClick={() => open(`/readme#${encodeURIComponent((data.name || name).replace(/^README\//, ''))}`)}>Open README <ArrowUpRight size={14}/></button></div>
          {passage?.title && <h3>{passage.title}</h3>}
          <pre className="source-verbatim review-source-passage">{passage?.text ?? data.original ?? data.value ?? 'No original passage was recorded.'}</pre>
        </> : <ErrorMessage>This source material is not available.</ErrorMessage>}
      </div>
    </section>
  </div>;
}
