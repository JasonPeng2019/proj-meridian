"""Frozen integration contract (plain JSON throughout).

loader.build_records() -> list[dict], writes generated/records.json,
generated/drawings.json (dict keyed D-xxx), generated/bom.json (list).
loader reads generated/ai_results.json if present and generated/models/manifest.json.
No loader mutation of decisions; the app overlays decisions on original records.

Part: id canonical stable name, key URL key, display_name, section, has_drawing,
has_3d, examples, drawing|null, bom:list, link, connections:list, template|null.
Drawing: id, pages (int), page_sizes:[[width,height]], image relative to generated,
degraded, fields:dict, numbers:list, callouts:list, sha256, source_path.
Field: name stable ID, original, value, confidence(sure|unsure), method,
page(1 based), box([x,y,w,h] PDF points), optional review/readers/cleanup/note.
BOM row: name('BOM:family/slug'), display_id('BOM-001'), display_name,
section (CSV Part family), fields:dict, sha256; field names snake_case.
Connection: target (row canonical name or null), text, source (stable fact ID).

AI result: {scans:{drawing_id:{fields:{field:Field}}},
 links:{drawing_id:{bom_rows:[row.name],method,readers,reason}},
 mappings:[{name,kind,left,right,relationship,method,readers,evidence}],
 templates:{drawing_id:Template}, metrics:{...}}.
pipeline.run_prep() writes ai_results and per-job raw outputs in ai_cache.

Template: part D-xxx, template flat_part, outline:{state,type,length,width,
 outer_diameter,inner_diameter}, thickness:Field, features:list,
 material:Field, weight_on_drawing:Field, review. Every geometric scalar is
 {state:known|options|unknown,value|options,method,fact_ids,confidence,readers?}.
Feature: kind(hole|slot), face, x,y (field objects), diameter/width/length/depth,
 through(bool), hole_type(plain|threaded|countersunk|counterbored),
 thread(optional string), countersink_diameter/angle,counterbore_diameter/depth,
 pattern:{type:row|circle,count,spacing|radius,start_angle,direction}.
Numeric feature fields may be bare numbers only when a parent fact_ids list
 supplies their evidence; AI values must be validated against drawing numbers.

cad.builder.build_all(templates:dict|None=None) -> manifest dict keyed drawing ID.
Writes generated/models/{id}_{A|B}.glb and .step and manifest.json.
Manifest entry: {examples:[A,B],models:{A:{glb,step,bounds_mm,volume_mm3,
template_sha256,...}},weight_check:{state,examples,...},waiting:[],omitted:[]}.
Cache immutable CAD outputs under generated/ai_cache/artifacts for regeneration.

API part routes use key, never canonical id. Drawing key D-013; BOM key
 bom/<family-slug>/<name-slug>. API paths ending image/history/crop registered
 before greedy /api/parts/{key:path}. Review IDs are URL-encoded stable targets.
GET /api/parts -> list records with facts optional. GET part -> record + facts list.
POST /api/chat {message,session_id?} -> {text,facts:{name:FactDisplay},
parts_to_show:PartSummary[],warnings:[],session_id,usage,latency_ms}.
FactDisplay: {fact,display:{state:value|options|undetermined,value|values|message},
badge,review,sources:[{name,says,method,page?,box?,part_key?}],snapshot_note,
review_item,correction,part_key,field}.
GET /api/review -> list {id,type,target,part_key,title,status,value,original,
readers,evidence,fact?,reason,options?}; type correction|link|template|
name_mapping|ai_interpretation|weight|possible_reading|source_changed.
POST /api/review/{item_id:path} {action,value?,note?} -> updated item/result.
Allowed actions accept,reject,set_value,choose_option,approve_mapping,confirm,
approve_design. No chat tool can call this endpoint.
"""
