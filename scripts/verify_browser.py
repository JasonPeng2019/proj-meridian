"""Read-only browser smoke checks. Never submits a human review action."""
from pathlib import Path
import json
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8000'
OUT = ROOT / 'docs/verification'

def get(path):
    return json.load(urllib.request.urlopen(BASE + path))

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts, review = get('/api/parts'), get('/api/review')
    ai_item = next((i for i in review if i['type']=='ai_interpretation'), review[0])
    model = next((p['key'] for p in parts if p.get('has_3d')), 'D-025')
    bom = next(p['key'] for p in parts if not p.get('has_drawing'))
    errors, failures = [], []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(ROOT / '.cache/frontend-browser'), headless=True, viewport={'width': 1600, 'height': 1000}, args=['--enable-unsafe-swiftshader'])
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append({'url':page.url,'message':str(e),'stack':e.stack}))
        page.on('response', lambda r: failures.append({'status':r.status,'url':r.url}) if r.status >= 400 else None)
        for name, path in [
            ('chat-empty', '/chat'),
            ('parts-library', '/parts'),
            ('drawing-highlight', '/part/D-013/2d?fact=D-013%2Fdrawing%2Fmaterial'),
            ('drawing-multipage', '/part/D-003/2d'),
            ('model', '/part/'+model+'/3d'),
            ('d013-example-a', '/part/D-013/3d?example=A'),
            ('d013-example-b', '/part/D-013/3d?example=B'),
            ('bom-detail', '/part/'+bom+'/detail'),
            ('history', '/part/D-013/history'),
            ('readme', '/readme#physical-system/p1'),
            ('review-needs-input', '/review/needs-input'),
            ('review-item', '/review/ai/'+ai_item['id']),
            ('review-design', '/review/part/D-013'),
        ]:
            page.goto(BASE+path)
            page.wait_for_timeout(1800)
            page.screenshot(path=str(OUT / (name+'.png')))
            print(name, 'body_chars', len(page.locator('body').inner_text()), 'horizontal_overflow', page.evaluate('document.documentElement.scrollWidth > innerWidth'), flush=True)
        page.goto(BASE+'/parts')
        page.get_by_placeholder('Search part or material…').fill('recoater')
        page.wait_for_timeout(250)
        print('filtered_parts', page.locator('.part-result').count(), flush=True)
        page.goto(BASE+'/part/D-003/2d')
        page.wait_for_timeout(800)
        page.locator('.sheet-thumb').nth(2).click()
        print('multipage_sheet',page.locator('.viewer-toolbar').inner_text(),flush=True)
        page.screenshot(path=str(OUT/'drawing-page3.png'))
        page.goto(BASE+'/part/D-013/detail')
        page.locator('.fact-card').filter(has=page.get_by_role('heading',name='Thickness',exact=True)).locator('.fact-badge').click()
        page.locator('.history-modal').wait_for()
        page.screenshot(path=str(OUT/'d013-thickness-history.png'))
        print('human_thickness_history', 'Jason Peng' in page.locator('.history-modal').inner_text(),flush=True)
        page.goto(BASE+'/review/part/D-013')
        page.locator('.part-tabs').get_by_role('button',name='2D drawing',exact=True).click()
        print('review_controls_retained',page.locator('.part-review-controls').is_visible(),'approval_disabled',page.get_by_role('button',name='Approve whole design',exact=True).is_disabled(),flush=True)
        page.screenshot(path=str(OUT/'review-d013-drawing.png'))
        page.goto(BASE+'/review/possible-readings/options:D-025/template/thickness')
        page.wait_for_timeout(1300)
        print('possible_reading_viewers',page.locator('.readings-models .cad-viewer').count(),flush=True)
        page.locator('.readings-comparison').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'possible-readings-compare.png'))
        page.goto(BASE+'/review/needs-input')
        page.locator('.review-toolbar select').nth(0).select_option('name_mapping')
        page.wait_for_timeout(250)
        mappings=[i for i in review if i['type']=='name_mapping']
        visible=page.locator('.review-item').count()
        assert visible==len(mappings), (visible,len(mappings))
        print('all_name_mappings_visible',visible,'pending_approval',sum(i.get('status')=='pending_approval' for i in mappings),flush=True)
        page.screenshot(path=str(OUT/'review-name-mappings.png'))
        changed=next((i for i in review if i['type']=='source_changed'),None)
        if changed:
            page.goto(BASE+'/review/needs-input/'+changed['id'])
            page.get_by_role('button',name='Re-approve against current evidence',exact=True).wait_for()
            page.screenshot(path=str(OUT/'review-source-changed.png'))
            print('source_changed_reapprove_control_visible',True,flush=True)
        else:
            print('source_changed_reapprove_control','no changed-evidence items in live data; action not submitted',flush=True)
        context.close()
    result = {'page_errors':errors,'failed_responses':failures,'model_checked':model,'bom_checked':bom}
    (OUT/'browser-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    assert not errors, errors
    assert not failures, failures

if __name__ == '__main__':
    main()
