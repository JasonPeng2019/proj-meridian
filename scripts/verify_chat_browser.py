"""One real chat request, then read-only source and model inspection."""
from pathlib import Path
import json
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/verification'
BASE='http://127.0.0.1:8000'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        context=p.chromium.launch_persistent_context(str(ROOT/'.cache/frontend-browser'),headless=True,viewport={'width':1600,'height':1000},args=['--enable-unsafe-swiftshader'])
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append({'url':page.url,'message':str(e),'stack':e.stack}))
        if '--replay' in sys.argv:
            saved=json.loads((OUT/'live-chat.json').read_text(encoding='utf-8'))
            page.route('**/api/chat',lambda route:route.fulfill(json=saved))
        page.goto(BASE+'/chat')
        page.get_by_placeholder('Ask about a part, material, drawing, or connection…').fill('What material is D-025 made of? Show its drawing and 3D reconstruction.')
        with page.expect_response(lambda r:'/api/chat' in r.url and r.request.method=='POST',timeout=120000) as response:
            page.get_by_title('Send message').click()
        result=response.value.json()
        if '--replay' not in sys.argv:
            (OUT/'live-chat.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        page.locator('.assistant-body').wait_for()
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT/'chat-cited-answer.png'))
        print('response_status',response.value.status,'citations',page.locator('.citation').count(),'cards',page.locator('.attached-card').count(),flush=True)
        page.locator('.citation').first.hover()
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT/'chat-source-hover.png'))
        print('source_crop_count',page.locator('.source-crop').count(),flush=True)
        page.locator('.popover-source').filter(has=page.locator('code',has_text='D-025/drawing/material')).first.get_by_role('button').click()
        page.wait_for_timeout(1300)
        page.screenshot(path=str(OUT/'chat-drawing-panel.png'))
        print('panel_visible',page.locator('.part-side-panel').is_visible(),'chat_visible',page.locator('.assistant-body').is_visible(),'highlight_count',page.locator('.drawing-highlight').count(),flush=True)
        page.locator('.part-side-panel .part-tabs').get_by_role('button',name='3D model',exact=True).click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT/'chat-model-panel.png'))
        page.get_by_role('button',name='Example B',exact=False).click()
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT/'chat-model-example-b.png'))
        page.get_by_role('button',name='Example A',exact=False).click()
        page.wait_for_timeout(900)
        page.get_by_title('Close part').click()
        page.go_back()
        page.wait_for_timeout(500)
        page.go_forward()
        page.wait_for_timeout(500)
        print('back_forward_survives',page.locator('.chat-page').count(),flush=True)
        context.close()
    (OUT/'live-chat-browser-check.json').write_text(json.dumps({'page_errors':errors},indent=2),encoding='utf-8')
    print(json.dumps(errors,indent=2))

if __name__=='__main__':
    main()
