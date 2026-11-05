"""Browser checks mutate only a labelled chat fixture, never engineering reviews."""
from pathlib import Path
import json
import urllib.request
from urllib.parse import quote
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8000'
OUT = ROOT / 'docs/verification'

def get(path):
    return json.load(urllib.request.urlopen(BASE + path))

def verify_debug():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'], ignore_default_args=['--hide-scrollbars'])
        page=browser.new_page(viewport={'width':1600,'height':1000})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE+'/part/D-013/debug')
        page.locator('.debug-view').wait_for()
        assert page.locator('.part-tabs').get_by_role('tab',name='Debug',exact=True).is_visible()
        page.locator('.debug-tabs').get_by_role('button',name='Model & checks',exact=True).click()
        page.locator('.cad-weight > summary').click()
        assert page.locator('.cad-weight-detail').is_visible()
        assert page.get_by_text('Download reconstruction (STEP)',exact=True).count()==2
        page.locator('.cad-provenance > summary').first.click()
        assert 'template sha256' in page.locator('.debug-model').inner_text()
        page.screenshot(path=str(OUT/'debug-model.png'))
        page.locator('.debug-tabs').get_by_role('button',name='History',exact=True).click()
        page.locator('.timeline-entry').first.wait_for()
        assert 'Jason Peng' in page.locator('.history-view').inner_text()
        page.screenshot(path=str(OUT/'debug-history.png'))
        page.goto(BASE+'/part/D-015/debug')
        page.locator('.original-fact > summary').first.click()
        assert page.locator('.original-fact[open]').is_visible()
        page.goto(BASE+'/review/needs-input/names/material/silicon-rubber%20-%3E%20silicone')
        page.get_by_text('AI readings & reasons',exact=True).click()
        assert 'Verification' in page.locator('.reader-answers').inner_text()
        assert 'Accept' in page.locator('.reader-answers').inner_text()
        assert 'Proposal' in page.locator('.reader-answers').inner_text()
        page.screenshot(path=str(OUT/'verified-mapping-readers.png'))
        # Small laptop viewport: each engineering pane must own a usable scrollbar.
        page.set_viewport_size({'width':1280,'height':620})
        page.goto(BASE+'/part/D-013/debug')
        pane=page.locator('.debug-view')
        pane.wait_for()
        metrics=pane.evaluate('''el => ({overflow:getComputedStyle(el).overflowY,
            gutter:el.offsetWidth-el.clientWidth,content:el.scrollHeight,height:el.clientHeight})''')
        assert metrics['overflow']=='scroll' and metrics['gutter']>=10,metrics
        assert metrics['content']>metrics['height']>100,metrics
        pane.evaluate('el => el.scrollTop=el.scrollHeight')
        assert pane.evaluate('el => el.scrollTop')>0
        expect(page.get_by_text('Complete original drawing & raw records',exact=True)).to_be_in_viewport()
        expect(page.locator('.debug-tabs')).to_be_in_viewport()
        page.screenshot(path=str(OUT/'debug-scroll-bottom.png'))
        page.locator('.debug-tabs').get_by_role('button',name='Model & checks',exact=True).click()
        expect(pane).to_have_js_property('scrollTop',0)

        page.goto(BASE+'/review/awaiting-review')
        unsettled=[i for i in get('/api/review') if i.get('status') not in ['accepted','rejected','human_confirmed','human_rejected','approved','reviewed','deferred']]
        expect(page.locator('.review-item')).to_have_count(len(unsettled))
        expect(page.get_by_role('button',name='Show all items awaiting human review',exact=True)).to_have_text(f'{len(unsettled)} awaiting human review')
        page.goto(BASE+'/review/parts')
        search=page.get_by_role('textbox',name='Search review parts',exact=True)
        search.fill('Recoater')
        expect(page.locator('.review-part-row').first).to_be_visible()
        assert page.locator('.review-part-row').count()>1
        search.fill('D-013')
        expect(page.locator('.review-part-row')).to_have_count(1)
        page.locator('.review-part-row').click()
        expect(page.locator('.review-part-focus .part-title h2')).to_have_text('Recoater Plate')
        assert '?part=D-013' in page.url
        expect(search).to_be_visible()
        expect(page.locator('.review-part-focus .debug-view')).to_be_visible()
        assert page.locator('.review-part-focus .debug-view').evaluate('el => el.clientHeight')>=200
        page.reload()
        expect(page.locator('.review-part-focus .part-title h2')).to_have_text('Recoater Plate')
        search.fill('D-014')
        page.locator('.review-part-row').click()
        expect(page.locator('.review-part-focus .part-title h2')).to_have_text('Recoater Linear Plate')
        page.get_by_role('button',name='Clear part search',exact=True).click()
        expect(page.locator('.review-part-row')).to_have_count(len(get('/api/parts')))
        rail=page.locator('.review-parts-results')
        rail.evaluate('el => el.scrollTop=el.scrollHeight')
        assert rail.evaluate('el => el.scrollTop')>0
        expect(search).to_be_in_viewport()
        rail.evaluate('el => el.scrollTop=0')
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(OUT/'engineering-parts.png'))

        page.locator('.review-part-focus-toolbar').get_by_role('button',name='Review items',exact=True).click()
        expect(page.locator('.review-item').first).to_be_visible()
        assert 'part=D-014' in page.url
        scoped=[i for i in get('/api/review') if (i.get('part_key') or (i.get('evidence',{}).get('part_key') if isinstance(i.get('evidence'),dict) else None))=='D-014']
        for label,kind in [('Corrections','correction'),('Possible readings','possible_reading')]:
            expected=sum(i['type']==kind or (kind=='ai_interpretation' and i['type']=='part') for i in scoped)
            expect(page.get_by_role('navigation',name='Review categories').get_by_role('button',name=label).locator('span')).to_have_text(str(expected))
        for label,queue in [('Needs human input','human_input'),('Needs human review','human_review')]:
            expected=sum(i.get('review_queue')==queue for i in scoped)
            expect(page.get_by_role('navigation',name='Review categories').get_by_role('button',name=label).locator('span')).to_have_text(str(expected))
        assert all('D-014' in value for value in page.locator('.review-item > small').all_text_contents())
        page.locator('.review-item').first.click()
        expect(page.locator('.review-item-detail h2')).to_be_visible()
        detail=page.locator('.review-item-detail')
        detail.evaluate('el => el.scrollTop=el.scrollHeight')
        assert detail.evaluate('el => el.scrollTop')>0
        page.screenshot(path=str(OUT/'engineering-scoped-reviews.png'))
        page.get_by_role('button',name='Inspect part',exact=True).click()
        expect(page.locator('.review-part-focus .part-title h2')).to_have_text('Recoater Linear Plate')
        page.go_back()
        expect(page.locator('.review-item-detail h2')).to_be_visible()
        assert 'part=D-014' in page.url
        page.get_by_role('navigation',name='Review categories').get_by_role('button',name='Full queue').click()
        expect(page.locator('.review-scope')).to_have_count(0)
        expect(page.locator('.review-item')).to_have_count(len(unsettled))
        assert 'part=' not in page.url
        page.goto(BASE+'/review/part/D-013?part=D-013')
        expect(page.locator('.part-review-canvas .part-title h2')).to_have_text('Recoater Plate')
        expect(page.get_by_role('button',name='Approve whole design',exact=True)).to_be_disabled()
        controls=page.locator('.part-review-controls')
        controls.evaluate('el => el.scrollTop=el.scrollHeight')
        assert controls.evaluate('el => el.scrollHeight <= el.clientHeight || el.scrollTop > 0')
        expect(page.locator('.part-review-items').locator('xpath=..').locator('summary')).to_be_in_viewport()
        page.screenshot(path=str(OUT/'engineering-design-review.png'))
        # Source links must open the actual evidence without losing the review.
        page.goto(BASE+'/review/ai/D-014/template/outline/length?part=D-014')
        cited='D-014/drawing/n/96.0@1-1'
        page.locator(f'button.review-source-link[data-source-name="{cited}"]').click()
        dialog=page.get_by_role('dialog',name='Source material',exact=True)
        expect(dialog.locator('.drawing-highlight')).to_have_attribute('title',cited)
        expect(dialog.locator('.drawing-highlight')).to_be_in_viewport()
        expect(dialog.get_by_text('Sheet 1 / 1',exact=True)).to_be_visible()
        pdf=dialog.get_by_role('link',name='Original PDF')
        response=page.request.get(BASE+pdf.get_attribute('href'))
        assert response.ok and response.body().startswith(b'%PDF')
        page.screenshot(path=str(OUT/'review-source-drawing.png'))
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        assert '/review/ai/D-014/template/outline/length?part=D-014' in page.url
        mapping=next(i for i in get('/api/review') if i['type']=='name_mapping' and
                     {'drawing','bom'}.issubset({r['kind'] for r in i.get('source_refs',[])}))
        page.goto(BASE+'/review/ai/'+quote(mapping['id'],safe='/'))
        bom_link=page.locator('button.review-source-link[data-source-name^="BOM:"]').first
        bom_link.wait_for(state='attached')
        if not bom_link.is_visible():
            page.locator('.review-source-links details > summary').click()
        bom_link.click()
        expect(dialog.locator('.review-source-table tbody tr').first).to_be_visible()
        assert dialog.locator('.review-source-table tbody tr').count()>3
        expect(dialog.get_by_role('columnheader',name='Original',exact=True)).to_be_visible()
        page.screenshot(path=str(OUT/'review-source-bom.png'))
        dialog.get_by_role('button',name='Close source material',exact=True).click()
        expect(dialog).to_have_count(0)
        assert quote(mapping['id'],safe='/') in page.url
        # Exercise expected input spaces without submitting engineering decisions.
        page.goto(BASE+'/review/needs-input/D-001/template/outline?part=D-001')
        shape=page.get_by_role('combobox',name='Outer shape',exact=True)
        expect(shape.locator('option')).to_have_text(['Choose a shape','Rectangle','Square','Circle','Ring'])
        save=page.get_by_role('button',name='Save reviewed value',exact=True)
        expect(save).to_be_disabled()
        shape.select_option('square')
        page.get_by_role('textbox',name='Side (mm)',exact=True).fill('40')
        expect(save).to_be_enabled()
        shape.select_option('ring')
        page.get_by_role('textbox',name='Outer diameter (mm)',exact=True).fill('40')
        page.get_by_role('textbox',name='Inner diameter (mm)',exact=True).fill('50')
        expect(save).to_be_disabled()
        expect(page.get_by_role('alert')).to_have_text('Inner diameter must be smaller than outer diameter.')
        page.get_by_role('textbox',name='Inner diameter (mm)',exact=True).fill('20')
        expect(save).to_be_enabled()
        page.locator('.review-value-example > summary').click()
        page.locator('.set-value').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'review-value-shape.png'))
        page.goto(BASE+'/review/ai/D-014/template/outline/length?part=D-014')
        number=page.get_by_role('textbox',name='Length (mm)',exact=True)
        number.fill('0')
        expect(save).to_be_disabled()
        number.fill('12.5 mm')
        expect(save).to_be_disabled()
        number.fill('12.5')
        expect(save).to_be_enabled()
        page.goto(BASE+'/review/needs-input/D-001/template/features_review?part=D-001')
        features=page.get_by_role('textbox',name='Reviewed holes and slots (JSON array)',exact=True)
        features.fill('{}')
        expect(save).to_be_disabled()
        features.fill('[]')
        expect(save).to_be_enabled()
        page.locator('.review-value-example > summary').click()
        page.locator('.set-value').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'review-value-features.png'))
        assert not errors,errors
        browser.close()
    (OUT/'debug-browser-check.json').write_text(json.dumps({'debug_launch':True,'calculations':True,'history':True,'raw_sources':True,'laptop_scrollbars':metrics,'searchable_parts':True,'global_awaiting_review_queue':len(unsettled),'human_input_and_review_separate':True,'source_drawing_region_and_pdf':True,'mapping_original_bom_row':True,'source_modal_retains_review':True,'typed_review_formats_and_validation':True,'part_scoped_review_counts':True,'scope_refresh_back_navigation':True,'independent_review_scroll':True,'design_approval_controls_retained':True,'page_errors':errors},indent=2),encoding='utf-8')


def verify_redesign(context, errors):
    """Exercise preserved client behavior without paying for or grading a model answer."""
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append({'url': page.url, 'message': str(error)}))
    record = get('/api/parts/D-013')
    fact = next(f for f in record['facts'] if f['field'] == 'thickness')
    answer = f"The drawing records two possible thicknesses. [cite:{fact['fact']}]"
    status = {**get('/api/status'), 'chat_available': True}
    page.route('**/api/status', lambda route: route.fulfill(json=status))
    sent = []
    def reply(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'session_id': 'ui-redesign-fixture', 'text': answer,
                            'facts': {fact['fact']: fact}, 'parts_to_show': [record], 'warnings': []})
    page.route('**/api/chat', reply)
    page.goto(BASE+'/chat')
    composer = page.get_by_role('textbox', name='Message Meridian')
    composer.fill('Show the recoater plate thickness.')
    composer.press('Enter')
    expect(page.locator('.assistant-body .answer-text')).to_contain_text('two possible thicknesses')
    assert sent[0]['message'] == 'Show the recoater plate thickness.'
    expect(page.locator('.attached-card')).to_have_count(1)
    expect(composer).to_have_value('')
    # A citation still opens the drawing at its evidence location in a side panel.
    page.locator('.citation').click()
    expect(page.locator('.part-side-panel .part-title h2')).to_have_text('Recoater Plate')
    expect(page.locator('.part-side-panel .drawing-viewer')).to_be_visible()
    page.go_back()
    expect(page.locator('.part-side-panel')).to_have_count(0)
    expect(page.locator('.assistant-body .answer-text')).to_contain_text('two possible thicknesses')
    page.locator('.attached-card').click()
    expect(page.locator('.part-side-panel .part-title h2')).to_have_text('Recoater Plate')
    page.go_back()
    context.grant_permissions(['clipboard-read','clipboard-write'], origin=BASE)
    page.get_by_title('Copy answer', exact=True).click()
    assert page.evaluate('navigator.clipboard.readText()') == answer
    page.get_by_role('button', name='Past chats', exact=True).click()
    dialog = page.get_by_role('dialog', name='Past chats', exact=True)
    expect(dialog).to_be_visible()
    # Native dialog keyboard behavior must keep focus inside and close on Escape.
    page.keyboard.press('Tab')
    assert dialog.evaluate('el => el.contains(document.activeElement)')
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(page.get_by_role('button', name='Past chats', exact=True)).to_be_focused()
    page.screenshot(path=str(OUT/'redesign-chat-answer.png'))
    # Tab navigation works with a keyboard and keeps the drawing tools intact.
    page.goto(BASE+'/part/D-013/detail')
    page.get_by_role('tab', name='2D drawing', exact=True).focus()
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('Enter')
    expect(page.get_by_role('tab', name='3D model', exact=True)).to_have_attribute('data-state','active')
    page.get_by_role('tab', name='2D drawing', exact=True).click()
    zoom = page.locator('.zoom-readout')
    before = zoom.inner_text()
    page.get_by_title('Zoom in', exact=True).click()
    assert zoom.inner_text() != before
    page.get_by_role('button', name='Fit', exact=True).click()
    expect(zoom).to_have_text('100%')
    page.goto(BASE+'/parts')
    page.locator('.parts-filters > summary').click()
    page.get_by_label('Available views', exact=True).select_option('3d')
    assert page.locator('.part-result').count() == sum(bool(p.get('has_3d')) for p in get('/api/parts'))
    page.get_by_role('button', name='Reset', exact=True).click()
    assert page.locator('.part-result').count() == len(get('/api/parts'))
    responsive = []
    for width, height, label in [(1600,1000,'desktop'),(1366,768,'laptop'),(390,844,'mobile')]:
        page.set_viewport_size({'width':width,'height':height})
        for name, path, ready in [('chat','/chat','.composer'),('parts','/parts','.part-result'),
                                  ('detail','/part/D-013/detail','.summary-box'),
                                  ('drawing','/part/D-003/2d','.drawing-paper')]:
            page.goto(BASE+path)
            page.locator(ready).first.wait_for()
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), (label,name)
            if name == 'chat':
                expect(page.get_by_role('textbox',name='Message Meridian')).to_be_in_viewport()
            if name == 'parts':
                expect(page.get_by_role('textbox', name='Search parts')).to_be_in_viewport()
                # A horizontally scrollable table is contained in its own region.
                assert page.locator('.part-result').count() == len(get('/api/parts'))
            if name == 'drawing':
                expect(page.get_by_title('Zoom in', exact=True)).to_be_in_viewport()
                expect(page.get_by_role('button', name='Fit', exact=True)).to_be_in_viewport()
                page.locator('.sheet-thumb').nth(2).click()
                expect(page.locator('.viewer-toolbar')).to_contain_text('Sheet 3 / 3')
            page.screenshot(path=str(OUT/f'redesign-{label}-{name}.png'))
            responsive.append({'viewport':label,'screen':name,'no_page_overflow':True})
    page.close()
    (OUT/'redesign-browser-check.json').write_text(json.dumps({
        'chat_reply': 'mocked transport; no paid API or answer-quality claim',
        'send_enter_clear': True, 'citations_and_attached_parts': True,
        'back_preserves_conversation': True, 'copy_answer': True,
        'history_focus_trap_escape_restore': True, 'part_keyboard_tabs': True,
        'drawing_zoom_fit': True, 'asset_filter_reset': True,
        'responsive': responsive}, indent=2), encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts, review = get('/api/parts'), get('/api/review')
    if get('/api/status').get('debug_ui'):
        return verify_debug()
    ai_item = next((i for i in review if i['type']=='ai_interpretation'), review[0])
    model = next((p['key'] for p in parts if p.get('has_3d')), 'D-025')
    bom = next(p['key'] for p in parts if not p.get('has_drawing'))
    errors, failures, rendered_models = [], [], []
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
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), path
            if name == 'parts-library':
                assert not page.locator('.parts-filters').evaluate('(el) => el.open')
                assert page.locator('.part-result').count() == len(parts)
            if name == 'model':
                assert page.locator('.model-panels').count() == 0
                assert page.locator('.sheet-rail').count() == 0
                assert page.locator('.cad-provenance').count() == 0
                assert page.locator('.cad-weight').count() == 0
                assert page.locator('.cad-check-summary').count() == 0
                assert 'FAILED' not in page.locator('.part-page').inner_text()
                assert 'Needs manual review' not in page.locator('.part-page').inner_text()
                model_record = get('/api/parts/'+model)
                expected_review = 'Human reviewed' if model_record.get('design_review') else 'AI reviewed'
                assert page.locator('.part-title').get_by_text(expected_review,exact=True).is_visible()
                assert page.locator('.part-tabs').get_by_role('tab', name='Debug', exact=True).count() == 0
                viewer = page.locator('.primary-view').bounding_box()
                body = page.locator('.part-body').bounding_box()
                assert viewer['width'] >= body['width'] * .9
            if name == 'bom-detail':
                assert page.locator('.detail-section[open]').count() == 0
                assert page.locator('.summary-box').count() <= 4
                assert page.locator('.notes-box').count() <= 1
                assert page.locator('#dimensions-heading').count() == 0
                assert '"currency"' not in page.locator('.standard-details').inner_text()
                assert page.locator('.fact-grid').count() == 0
            page.screenshot(path=str(OUT / (name+'.png')))
            print(name, 'body_chars', len(page.locator('body').inner_text()), 'horizontal_overflow', page.evaluate('document.documentElement.scrollWidth > innerWidth'), flush=True)
        # Open one model page at a time; closing it releases its WebGL context.
        page.goto(BASE+'/chat')
        for item in parts:
            if not item.get('has_3d'):
                continue
            record = get('/api/parts/'+item['key'])
            for variant, exported in record['model']['models'].items():
                render_page = context.new_page()
                render_page.on('pageerror', lambda e, view=render_page: errors.append({'url':view.url,'message':str(e),'stack':e.stack}))
                render_page.on('response', lambda r: failures.append({'status':r.status,'url':r.url}) if r.status >= 400 else None)
                try:
                    expected_url = BASE+'/generated/'+exported['glb']
                    with render_page.expect_response(lambda r, url=expected_url: r.url == url, timeout=30000) as loaded:
                        render_page.goto(BASE+'/part/'+item['key']+'/3d?example='+variant)
                    assert loaded.value.ok, expected_url
                    render_page.locator('.cad-canvas canvas').wait_for()
                    render_page.wait_for_timeout(1600)
                    assert render_page.locator('.cad-empty').count() == 0, item['key']
                    assert render_page.locator('.part-tabs').get_by_role('tab',name='Debug',exact=True).count() == 0
                    assert 'FAILED' not in render_page.locator('.part-page').inner_text()
                    render_page.screenshot(path=str(OUT/f"render-{item['key']}-{variant}.png"))
                    rendered_models.append({'drawing':item['key'],'variant':variant,'glb_sha256':exported['glb_sha256']})
                finally:
                    render_page.close()
        page.goto(BASE+'/chat')
        page.get_by_role('button',name='Past chats',exact=True).click()
        page.screenshot(path=str(OUT/'past-chats.png'))
        page.locator('.saved-chat-open').filter(has_text='Automated history fixture question').click()
        page.get_by_text('Saved conversation test message.',exact=True).wait_for()
        assert '/chat/f123456789abcdef0123456789abcdef' in page.url
        page.reload()
        page.get_by_text('Saved conversation test message.',exact=True).wait_for()
        page.screenshot(path=str(OUT/'saved-chat-restored.png'))
        page.get_by_role('button',name='New chat',exact=True).click()
        assert page.locator('.user-message').count()==0
        page.get_by_role('button',name='Past chats',exact=True).click()
        page.get_by_title('Delete chat: Automated history fixture question',exact=True).click()
        page.wait_for_timeout(300)
        assert not any(chat['id']=='f123456789abcdef0123456789abcdef' for chat in get('/api/chats'))
        page.get_by_title('Close past chats',exact=True).click()
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
        page.get_by_title('View thickness source and history', exact=True).click()
        page.locator('.history-modal').wait_for()
        page.screenshot(path=str(OUT/'d013-thickness-history.png'))
        assert page.locator('.source-modal-content').is_visible()
        assert page.locator('.timeline-entry').count() == 0
        page.goto(BASE+'/part/D-015/detail')
        assert 'Silicone Wiper' in page.locator('.part-title h2').inner_text()
        page.goto(BASE+'/part/D-023/detail')
        assert 'Build Cylinder' in page.locator('.part-title h2').inner_text()
        assert 'EN AW-6082 T6' in page.locator('.notes-box').inner_text()
        assert 'længere' not in page.locator('.notes-box').inner_text()
        page.screenshot(path=str(OUT/'english-notes.png'))
        page.goto(BASE+'/review/part/D-013')
        page.locator('.part-tabs').get_by_role('tab',name='2D drawing',exact=True).click()
        print('review_controls_retained',page.locator('.part-review-controls').is_visible(),'approval_disabled',page.get_by_role('button',name='Approve whole design',exact=True).is_disabled(),flush=True)
        page.screenshot(path=str(OUT/'review-d013-drawing.png'))
        page.goto(BASE+'/review/possible-readings/options:D-025/template/thickness')
        page.get_by_text('Compare 3D examples', exact=True).click()
        page.wait_for_timeout(1300)
        print('possible_reading_viewers',page.locator('.readings-models .cad-viewer').count(),flush=True)
        page.locator('.readings-comparison').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'possible-readings-compare.png'))
        page.goto(BASE+'/review/ai')
        page.locator('.review-filter-options > summary').click()
        page.locator('.review-toolbar select').nth(0).select_option('name_mapping')
        page.wait_for_timeout(250)
        mappings=[i for i in review if i['type']=='name_mapping' and i.get('review_queue')=='human_review']
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
        verify_redesign(context, errors)
        context.close()
    result = {'page_errors':errors,'failed_responses':failures,'model_checked':model,'models_rendered':rendered_models,'bom_checked':bom,
              'default_hierarchy': {'focused_model': True, 'filters_collapsed': True, 'technical_details_collapsed': True,
                                    'calculations_moved_to_debug': True, 'debug_hidden_on_customer_launch': True, 'saved_chats_reopen_refresh_delete': True, 'no_horizontal_overflow': True}}
    (OUT/'browser-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    assert not errors, errors
    assert not failures, failures

if __name__ == '__main__':
    main()
