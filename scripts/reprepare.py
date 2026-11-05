"""Redo prep from pinned, already-extracted evidence; one local CLI at a time.

No PDF/CAD/build/browser subprocess. Keeps legacy receipts and decisions intact.
"""
from __future__ import annotations
import copy,json,time
from datetime import datetime,timezone
from backend.ai import pipeline as p,runner
from backend.paths import ROOT,GENERATED,configure_environment,inside
from scripts.expand_models import raw_drawings,require_settings,sequential_readers,digest


def main():
    configure_environment();require_settings()
    drawings=raw_drawings()
    corpus=inside(ROOT/'project-meridian_Avathon/project-meridian')
    manifest=json.loads((corpus/'dataset/manifest.json').read_text(encoding='utf-8'))
    for asset in manifest['assets']:
        assert digest(corpus/asset['path'])==asset['sha256'],asset['id']
        if asset['id'] in drawings:
            assert drawings[asset['id']]['sha256']==asset['sha256']
    original=json.loads((GENERATED/'ai_results.json').read_text(encoding='utf-8'))
    bom=json.loads((GENERATED/'bom.json').read_text(encoding='utf-8'))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=inside(runner.CACHE/'reprepare'/stamp)
    runner.write_json(folder/'previous-output.json',original)
    before={str(f.relative_to(ROOT)):digest(f) for f in (ROOT/'decisions').glob('*.json')}
    results=[];exact={};started=time.monotonic()
    def stage(jobs,label):
        for i,job in enumerate(jobs,1):
            print(f'{label} [{i}/{len(jobs)}] {job["id"]}',flush=True)
            result=p.run_retry(p.execute(job))
            results.append(result)
            runner.write_json(folder/'checkpoint.json',{'protocol':p.PROTOCOL,'complete':False,'stage':label,'results':results,'exact':exact})
            if job['kind']=='template':
                assembled=p.assemble([result],drawings,{})['templates'][job['drawing']]
                runner.write_json(folder/(job['drawing']+'-template.json'),assembled)
                print(json.dumps({'drawing':job['drawing'],'cuts':len(assembled.get('features',[])),'features_status':assembled.get('features_status'),'features_complete':assembled.get('features_complete',{}).get('value'),'omissions':assembled.get('omitted_feature_notes'),'states':result['states']}),flush=True)
            else:print(json.dumps({'job':job['id'],'states':result['states']}),flush=True)
    with sequential_readers():
        stage([p.template_job(drawings[d]) for d in p.PRIMARY_TEMPLATES],'templates')
        stage([p.scan_job(d) for d in drawings.values() if d.get('degraded')],'scans')
        output=p.assemble(results,drawings,{})
        linked_drawings=copy.deepcopy(drawings)
        for did,scan in output['scans'].items():linked_drawings[did]['fields'].update(scan['fields'])
        rows=p.custom_rows(bom)
        for did,drawing in linked_drawings.items():
            match=p.exact_link(drawing,rows)
            if match:exact[did]=match
        stage([p.match_job(d,rows) for did,d in linked_drawings.items() if did not in exact],'links')
        output=p.assemble(results,drawings,exact)
        stage(p.mapping_jobs(linked_drawings,bom,output['links']),'mappings')
    output=p.assemble(results,drawings,exact)
    output['metrics']['wall_time_ms']=round((time.monotonic()-started)*1000)
    current=json.loads((GENERATED/'ai_results.json').read_text(encoding='utf-8'))
    for did,template in current.get('templates',{}).items():
        if did not in output['templates']:output['templates'][did]=template
    output['previous_prep']={'receipt':str((folder/'previous-output.json').relative_to(GENERATED)),'protocol':'mixed legacy and targeted proposal-verification','sha256':runner.fingerprint(original)}
    output['prep_runs']=copy.deepcopy(current.get('prep_runs',[]))+[{'kind':'full_reprepare','protocol':p.PROTOCOL,'receipt':str((folder/'checkpoint.json').relative_to(GENERATED)),'metrics':output['metrics']}]
    assert before=={str(f.relative_to(ROOT)):digest(f) for f in (ROOT/'decisions').glob('*.json')}
    runner.write_json(folder/'checkpoint.json',{'protocol':p.PROTOCOL,'complete':True,'results':results,'exact':exact,'metrics':output['metrics'],'decisions_unchanged':True})
    runner.write_json(GENERATED/'ai_results.json',output)
    runner.write_json(runner.CACHE/'artifacts/ai_results.json',output)
    runner.write_json(runner.CACHE/'last_run.json',{'protocol':p.PROTOCOL,'receipt':str((folder/'checkpoint.json').relative_to(GENERATED)),'metrics':output['metrics'],'jobs':[r['job']['id'] for r in results]})
    print(json.dumps({'complete':True,'receipt':str(folder.relative_to(ROOT)),'metrics':output['metrics']}),flush=True)

if __name__=='__main__':main()
