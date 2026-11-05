import React from 'react';
import {textValue, titleCase} from './api';

export default function ReaderAnswers({readers}) {
  if(!readers||!Object.keys(readers).length)return <p className="muted">No AI responses recorded.</p>;
  return <div className="reader-answers">{Object.entries(readers).map(([name,reader])=><article key={name}><div className="eyebrow">{name==='codex'?'GPT-6.1 Sol':name==='claude'?'Claude Opus':name} · {reader.role==='proposer'?'Proposal':reader.role==='verifier'?'Verification':'Legacy independent reading'}</div>{(reader.rounds||[reader]).filter(round=>round.requested!==false).map((round,i)=>{
    const answer=round.answer||round,verifier=reader.role==='verifier';
    let value=answer.value;
    try{if(answer.value_json!==undefined)value=JSON.parse(answer.value_json)}catch{value=answer.value_json}
    const invalid=round.valid===false||round.validation_passed===false;
    return <div key={i} className="reader-round"><small>Round {i+1}{!verifier&&answer.confidence?` · ${answer.confidence}`:''}{invalid?' · did not pass validation':''}</small><div className="reader-value">{verifier?titleCase(answer.decision||'No valid verification'):answer.state==='unknown'?'Undetermined':value===undefined?'No valid proposal':textValue(value)}</div>{answer.reason&&<p>{answer.reason}</p>}{answer.changed_because&&<p>Changed because: {answer.changed_because}</p>}</div>
  })}</article>)}</div>;
}
