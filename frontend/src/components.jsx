import React from 'react';
import {AlertCircle, Loader2, ExternalLink} from 'lucide-react';
import {textValue} from './api';

export function Loading({label='Loading…'}) { return <div className="empty-state"><Loader2 className="spin" size={23}/><span>{label}</span></div>; }
export function ErrorMessage({children, retry}) { return <div className="notice error"><AlertCircle size={17}/><div>{children}</div>{retry && <button onClick={retry}>Try again</button>}</div>; }
export function StatusBadge({children, tone=''}) { return <span className={`status-badge ${tone}`}>{children}</span>; }
export function WeightBadge({check}) { if (!check) return null; const s=String(check.state || check.status || 'skipped'); return <StatusBadge tone={s.toLowerCase()==='failed'?'red':s.toLowerCase()==='passed'?'green':'amber'}>{s.toUpperCase()} weight check</StatusBadge>; }
export function Value({fact}) { const d=fact?.display; if(!d || d.state==='undetermined') return <span className="undetermined" title={d?.message || 'No trusted value recorded'}>Undetermined</span>; if(d.state==='options') return <span>{(d.values || d.options || []).map(textValue).join(' / ')} <small className="muted">possible readings</small></span>; return <>{textValue(d.value)}</>; }
export function JsonDetails({value}) { if(value==null) return <span className="muted">Not recorded</span>; if(typeof value!=='object') return <>{textValue(value)}</>; return <div className="structured">{Object.entries(value).map(([k,v])=><div key={k}><span className="muted">{k.replaceAll('_',' ')}: </span>{typeof v==='object' ? <JsonDetails value={v}/> : textValue(v)}</div>)}</div>; }
export function SafeLink({href, children}) { const valid=/^https?:\/\//i.test(href || ''); return valid ? <a href={href} target="_blank" rel="noreferrer">{children || href}<ExternalLink size={12}/></a> : <span>{children || textValue(href)}</span>; }
