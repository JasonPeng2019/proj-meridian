import React from 'react';
import {Flag} from 'lucide-react';
import {useDebug} from '../debug';

export default function ReconstructionFlag({part}) {
  const debug=useDebug();
  if(!debug||!part?.has_drawing)return null;
  const manifest=part.model||part.model_manifest||{};
  const models=Object.values(manifest.models||{});
  const unavailable=manifest.stale||!models.length;
  const incomplete=manifest.features_all_determined!==true||models.some(m=>m.features_all_determined!==true||m.omitted?.length||m.waiting?.length);
  if(!unavailable&&!incomplete)return null;
  const notes=[...new Set([
    ...(manifest.stale?[manifest.stale_message||'The reconstruction must be rebuilt from the current inputs.']:[]),
    ...(manifest.omitted_feature_notes||[]),...(manifest.omitted||[]),
    ...models.flatMap(m=>m.omitted||[]),
    ...(!models.length?(manifest.waiting||[]):[]),
  ].map(String))];
  return <aside className="reconstruction-flag" role="alert" aria-label="Reconstruction completeness warning">
    <Flag size={19} aria-hidden="true"/>
    <div><strong>{unavailable?'3D reconstruction unavailable':'Incomplete 3D reconstruction'}</strong>
      <p>{manifest.stale?'The previous model does not reflect the current inputs.':unavailable?'The drawing could not be fully reconstructed.':'Some drawing details are missing or unresolved in this model.'}</p>
      {notes.length>0&&<details><summary>Missing details and reasons</summary><ul>{notes.map((note,i)=><li key={i}>{note}</li>)}</ul></details>}
    </div>
  </aside>;
}
