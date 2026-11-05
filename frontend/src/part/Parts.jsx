import React, {useMemo, useState} from 'react';
import {Search, SlidersHorizontal, Box, ChevronLeft, ChevronRight, FileText, X, Layers} from 'lucide-react';
import {englishName, englishText} from '../language';
import {partKey, partURL, textValue} from '../api';
import {Button} from '../components/ui/button';
import {Badge} from '../components/ui/badge';
import {Input} from '../components/ui/input';
import PartPage from './PartPage';

function materials(part) {
  const all=[...(part.material?.state==='value'?[part.material.value]:part.material?.state==='options'?part.material.values||[]:[]),part.drawing?.fields?.material?.value,...(part.bom||[]).map(r=>r.fields?.material?.value)];
  return [...new Set(all.flat().filter(Boolean).map(textValue))];
}

function reviewStatus(part) {
  return part.review_status || part.review?.status || part.template?.review?.status || part.link?.review?.status || 'not_reviewed';
}

export default function Parts({parts,selected,navigate}) {
  const [query,setQuery]=useState(''),[section,setSection]=useState(''),[material,setMaterial]=useState(''),[assets,setAssets]=useState(''),[review,setReview]=useState('');
  const sections=[...new Set(parts.map(p=>p.section).filter(Boolean))].sort(),mats=[...new Set(parts.flatMap(materials))].sort();
  const filtered=useMemo(()=>parts.filter(p=>{
    const hay=[p.display_name,englishName(p.display_name),p.id,p.section,...materials(p),...(p.bom||[]).map(r=>r.display_name)].join(' ').toLowerCase();
    const reviewed=['human_confirmed','reviewed'].includes(reviewStatus(p));
    return hay.includes(query.toLowerCase())&&(!section||p.section===section)&&(!material||materials(p).includes(material))&&(!assets||(assets==='3d'?p.has_3d:assets==='2d'?p.has_drawing&&!p.has_3d:!p.has_drawing))&&(!review||(review==='reviewed'?reviewed:!reviewed));
  }),[parts,query,section,material,assets,review]);
  const countFilters=[section,material,assets,review].filter(Boolean).length;
  const resetFilters=()=>{setSection('');setMaterial('');setAssets('');setReview('')};

  if(selected)return <div className="parts-workspace focused-part"><div className="parts-detail"><Button variant="ghost" className="library-back" onClick={()=>navigate('/parts')}><ChevronLeft size={15}/>All parts</Button><PartPage partKey={selected.key} initialTab={selected.tab} factId={selected.fact} example={selected.example} navigate={navigate}/></div></div>;

  return <div className="parts-workspace library-catalog"><section className="parts-browser" aria-labelledby="parts-library-heading">
    <header className="parts-browser-header">
      <div className="library-heading"><div><span className="library-kicker">WORKSPACE / PARTS</span><h2 id="parts-library-heading">Parts library</h2><p>Explore drawings, models and their source evidence.</p></div><span className="library-total">{parts.length} parts</span></div>
      <div className="library-toolbar">
        <div className="search-field library-search"><Search size={16}/><Input aria-label="Search parts" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search part or material…"/>{query&&<Button variant="ghost" size="icon" aria-label="Clear search" onClick={()=>setQuery('')}><X size={14}/></Button>}</div>
        <details className="parts-filters">
          <summary><SlidersHorizontal size={15}/>Filters{countFilters>0&&<span className="filter-count">{countFilters}</span>}</summary>
          <div className="library-filter-panel">
            <div className="row between"><strong>Filter parts</strong>{countFilters>0&&<Button variant="ghost" size="sm" onClick={resetFilters}>Reset</Button>}</div>
            <div className="filter-grid">
              <label>Section<select aria-label="Machine section" value={section} onChange={e=>setSection(e.target.value)}><option value="">All sections</option>{sections.map(s=><option key={s} value={s}>{englishText(s)}</option>)}</select></label>
              <label>Available views<select aria-label="Available views" value={assets} onChange={e=>setAssets(e.target.value)}><option value="">All views</option><option value="3d">2D + 3D</option><option value="2d">2D only</option><option value="bom">Parts list only</option></select></label>
              <label>Material<select aria-label="Material" value={material} onChange={e=>setMaterial(e.target.value)}><option value="">All materials</option>{mats.map(m=><option key={m} value={m}>{englishText(m)}</option>)}</select></label>
              <label>Review<select aria-label="Review status" value={review} onChange={e=>setReview(e.target.value)}><option value="">All review states</option><option value="reviewed">Human reviewed</option><option value="unreviewed">Not human reviewed</option></select></label>
            </div>
          </div>
        </details>
      </div>
    </header>
    <div className="library-results-heading"><span className="part-results-count" aria-live="polite">{filtered.length} {filtered.length===1?'part':'parts'}{countFilters||query?` of ${parts.length}`:''}</span>{(countFilters>0||query)&&<Button variant="ghost" size="sm" onClick={()=>{resetFilters();setQuery('')}}>Clear all<X size={13}/></Button>}</div>
    <div className="part-results library-table-wrap"><table className="library-table"><thead><tr><th scope="col">Part</th><th scope="col">Section</th><th scope="col">Material</th><th scope="col">Views</th><th scope="col">Status</th><th scope="col"><span className="library-sr-only">Open part</span></th></tr></thead><tbody>
      {filtered.map(p=>{
        const key=partKey(p),Icon=p.has_3d?Box:p.has_drawing?FileText:Layers;
        const human=Boolean(p.design_review)||['human_confirmed','reviewed'].includes(reviewStatus(p));
        const available=Boolean(p.has_3d)&&reviewStatus(p)!=='source_changed';
        const label=reviewStatus(p)==='source_changed'?'Unavailable':human?'Human reviewed':available?'AI reviewed':'Unavailable';
        const materialLabel=materials(p).map(englishText).join(' / ');
        return <tr key={key} className="library-part-row" onClick={()=>navigate(partURL(key))}>
          <td><Button variant="ghost" className="part-result" onClick={e=>{e.stopPropagation();navigate(partURL(key))}}><span className="library-part-name"><strong>{englishName(p.display_name)}</strong><small>{key}</small></span></Button></td>
          <td className="library-section" data-label="Section">{p.section?englishText(p.section):<span className="library-missing">Unassigned</span>}</td>
          <td className="library-material" data-label="Material">{materialLabel||<span className="library-missing">—</span>}</td>
          <td data-label="Views"><span className="library-view"><Icon size={13}/>{p.has_3d?'2D + 3D':p.has_drawing?'2D drawing':'Parts list'}</span></td>
          <td data-label="Status"><Badge variant="outline" className={`library-review ${human&&label!=='Unavailable'?'human':label==='Unavailable'?'unavailable':''}`}>{label}</Badge></td>
          <td className="library-open"><ChevronRight size={15}/></td>
        </tr>;
      })}
    </tbody></table>{!filtered.length&&<div className="empty-inline library-no-results"><Search size={22}/><strong>No matching parts</strong><p>Try another name, material or set of filters.</p><Button variant="outline" size="sm" onClick={()=>{resetFilters();setQuery('')}}>Clear search and filters</Button></div>}</div>
  </section></div>;
}
