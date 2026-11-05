// REMOTE ONLY: run from testing/ after frontend/CI npm ci and Chromium install.
// Actual React DOM and browser interactions, with deterministic API boundaries.
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { createRequire } = require("node:module");
const { pathToFileURL } = require("node:url");
const root = path.resolve(__dirname, "../..");
const frontend = path.join(root, "development/frontend");
const frontendRequire = createRequire(path.join(frontend, "package.json"));
const ciRequire = createRequire(path.join(root, "testing/ci/package.json"));
const { chromium } = ciRequire("playwright");
const fixture = JSON.parse(fs.readFileSync(path.join(root, "testing/fixtures/contracts/chat-response.json"), "utf8"));
const entry = `
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import Chat from '/src/chat/Chat.tsx';
const requests = window.requests = [];
const waiting = window.waiting = {};
const summary = (id, title, day) => ({ conversation_id: id, title, created_at: '2026-11-01T12:00:00Z', updated_at: '2026-11-0' + day + 'T12:00:00Z' });
const summaries = [summary('a', 'Older thread', 2), summary('b', 'Recent thread', 4)];
const answer = { ...window.fixture, conversation_id: 'a', text: 'Saved answer [cite: D-013/part]', warnings: [{code: 'invalid_citation', message: 'ENGINEERING_WARNING'}] };
const raw = '[cite: D-013/part]';
answer.markers = [{kind:'cite', names:['D-013/part'], raw, start:13, end:13 + raw.length, valid:true}];
answer.parts_to_show = [{id:'D-013/part', display_name:'Saved part', has_drawing:true, has_3d:true, examples:['B'], model_state:'available', reason:'citation', thumbnail:null}];
const stores = window.stores = {
 a: { conversation:summaries[0], messages:[...Array.from({length:12}, (_, n) => ({id:'u'+n, role:'user', text:'Saved question '+n, created_at:'2026-11-02T12:00:00Z'})), {id:'answer', role:'assistant', response:answer, created_at:'2026-11-02T12:01:00Z'}] },
 b: { conversation:summaries[1], messages:[{id:'b-user', role:'user', text:'Only thread B', created_at:'2026-11-04T12:00:00Z'}] }
};
let created = 0;
const defer = key => new Promise((resolve, reject) => { waiting[key] = {resolve, reject}; });
const api = {
 conversations:async () => { requests.push(['list']); if(window.holdList) return defer('list'); return {conversations:Object.values(stores).map(x=>x.conversation)}; },
 conversation:async ({conversation_id:id}) => { requests.push(['read',id]); if(window.holdRead === id) return defer('read-'+id); if(window.failRead === id) throw Error('PRIVATE_ERROR'); return structuredClone(stores[id]); },
 create_conversation:async body => { requests.push(['create', body]); if(window.holdCreate) return defer('create'); const id='new-'+(++created); return stores[id]={conversation:summary(id,'New chat',5),messages:[]}; },
 send_conversation:async (query, body) => {
   requests.push(['send',query,body]); if(window.holdSend) return defer('send');
   if(window.succeedSend) {
     const store=stores[query.conversation_id];
     const pair=[{id:'sent-user',role:'user',text:body.message,created_at:'2026-11-05T14:00:00Z'},
       {id:'sent-answer',role:'assistant',created_at:'2026-11-05T14:00:01Z',response:{text:'Continued answer',facts:{},parts_to_show:[],warnings:[],attachment_layout:'none',conversation_id:query.conversation_id}}];
     store.messages.push(...pair); store.conversation.updated_at='2026-11-05T14:00:01Z';
     return {conversation:store.conversation,messages:pair};
   }
   throw Error('PRIVATE_SEND_ERROR');
 }
};
window.callbacks = [];
function Harness() {
 const [id, setId] = useState(window.initialId);
 const [available, setAvailable] = useState(false);
 const [debug, setDebug] = useState(false);
 window.choose = setId; window.enableSend = setAvailable; window.enableDebug = setDebug;
 return <Chat api={api} status={{chat_available:available,chat_state:available?'configured':'missing_key',message:'PRIVATE_STATUS fixture diagnostic'}}
 selected_conversation_id={id} on_select_conversation={next => {window.callbacks.push(['select',next]); setId(next);}}
 on_open_part={value => window.callbacks.push(['part',value])} on_open_source={(target,id) => window.callbacks.push(['source',target,id])}
 debug={debug ? {enabled:true,on_open_review:()=>{}} : {enabled:false}} />;
}
createRoot(document.getElementById('root')).render(<Harness/>);
`;

async function run() {
  const { createServer } = await import(pathToFileURL(frontendRequire.resolve("vite")).href);
  const virtual = path.join(frontend, "a18-entry.tsx");
  const output = path.join(root, "testing/tmp/A18-history-ui");
  fs.mkdirSync(output, { recursive: true });
  const server = await createServer({
    configFile: false, root: frontend, cacheDir: path.join(output, "vite-cache"),
    esbuild: { jsx: "automatic" },
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{ name: "a18-deterministic-harness",
      resolveId(id) { if (id === "/a18-entry.tsx") return virtual; },
      load(id) { if (id === virtual) return entry; },
      configureServer(instance) { instance.middlewares.use((req, res, next) => {
        if (req.url !== "/a18-history-test") return next();
        res.setHeader("Content-Type", "text/html");
        res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="margin:16px"><div id="root"></div><script type="module" src="/a18-entry.tsx"></script></body></html>');
      }); },
    }],
  });
  let browser;
  const errors = [];
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(value => { window.fixture = value; window.initialId = 'a'; }, fixture);
    const url = `http://127.0.0.1:${server.httpServer.address().port}/a18-history-test`;
    const text = () => page.locator("body").innerText();
    const waitText = value => page.waitForFunction(value => document.body.innerText.includes(value), value);
    const absent = async value => assert.ok(!(await text()).includes(value), `Unexpected text: ${value}`);
    await page.goto(url);
    await waitText("Saved question 0");
    await waitText("Saved question 11"); // Beyond the model's 10-message window.
    assert.equal(await page.getByLabel("Your message", { exact: true }).count(), 12);
    assert.match(await text(), /server API key is missing/);
    await absent("PRIVATE_STATUS"); await absent("ENGINEERING_WARNING"); await absent("[cite:");
    assert.equal(await page.getByRole("button", { name: "Send", exact: true }).isDisabled(), true);
    const titles = await page.locator(".mc-history .mc-title").allTextContents();
    assert.deepEqual(titles, ["Recent thread", "Older thread"]);
    await page.getByRole("button", { name: "Drawing", exact: true }).click();
    await page.getByRole("button", { name: "3D", exact: true }).click();
    const partCalls = await page.evaluate(() => window.callbacks.filter(x => x[0] === "part"));
    assert.equal(partCalls[0][1].conversation_id, "a");
    assert.equal(partCalls[0][1].tab, "drawing");
    assert.equal(partCalls[1][1].tab, "model"); assert.equal(partCalls[1][1].example, "B");
    assert.match(await text(), /Reconstruction, not original CAD/);
    await page.getByRole("button", { name: /Sources ·/ }).first().click();
    await page.locator(".me-source-popup .me-source-row button").first().click();
    assert.equal(await page.evaluate(() => window.callbacks.find(x => x[0] === "source")[2]), "a");
    await page.getByRole("button", { name: "Close sources", exact: true }).click();
    await page.evaluate(() => window.enableDebug(true));
    await page.locator(".mc-assistant > .meridian-evidence > .me-debug > summary").click();
    await waitText("ENGINEERING_WARNING");
    await page.evaluate(() => window.enableDebug(false));
    await page.locator(".mc-assistant > .meridian-evidence > .me-debug").waitFor({ state: "detached" });
    await absent("ENGINEERING_WARNING");

    // A late read cannot replace another selection, even after returning to A.
    await page.evaluate(() => {window.holdRead='a'; window.choose('b');});
    await waitText("Only thread B"); await absent("Saved question 0");
    await page.getByRole("button", { name: /Older thread/ }).click();
    await page.waitForFunction(() => !!window.waiting['read-a']);
    await page.getByRole("button", { name: /Recent thread/ }).click();
    await waitText("Only thread B");
    await page.evaluate(() => {window.holdRead=null; window.waiting['read-a'].resolve(window.stores.a);});
    await absent("Saved question 0");
    assert.equal(await page.getByRole("button", { name: "Drawing", exact: true }).count(), 0);

    // New chat still creates a server ID without a key; selection is parent-owned.
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    await waitText("No messages yet.");
    assert.equal(await page.evaluate(() => window.callbacks.filter(x=>x[0]==='select').at(-1)[1]), 'new-1');
    await page.evaluate(() => window.holdCreate=true);
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    await page.waitForFunction(() => !!window.waiting.create);
    await page.getByRole("button", { name: /Recent thread/ }).click();
    await waitText("Only thread B");
    await page.evaluate(() => {window.holdCreate=false; window.waiting.create.resolve({conversation:{conversation_id:'late-created'},messages:[]});});
    assert.equal(await page.evaluate(() => window.callbacks.some(x=>x[0]==='select' && x[1]==='late-created')), false);

    // Request contains only the question. A failed send retains the draft and
    // does not fabricate a reply; a late send cannot replace the active thread.
    await page.evaluate(() => {window.enableSend(true); window.holdSend=true;});
    await page.getByLabel("Your question", { exact: true }).fill("Continue B");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.waitForFunction(() => !!window.waiting.send);
    assert.deepEqual(await page.evaluate(() => window.requests.filter(x=>x[0]==='send').at(-1)), ['send',{conversation_id:'b'},{message:'Continue B'}]);
    await page.getByRole("button", { name: /Older thread/ }).click();
    await waitText("Saved question 0");
    await page.evaluate(() => {window.waiting.send.reject(Error('PRIVATE_LATE_SEND')); window.holdSend=false;});
    await absent("Only thread B"); await absent("Could not send");
    await page.getByLabel("Your question", { exact: true }).fill("Retry draft");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await waitText("Could not send your question");
    assert.equal(await page.getByLabel("Your question", { exact: true }).inputValue(), "Retry draft");
    await absent("PRIVATE_SEND_ERROR");
    await page.evaluate(() => {window.succeedSend=true;});
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await waitText("Continued answer");
    await waitText("Saved question 0");
    assert.equal(await page.getByLabel("Your question", { exact: true }).inputValue(), "");
    await page.waitForFunction(() => document.querySelector('.mc-history .mc-title')?.textContent === 'Older thread');
    await page.evaluate(() => {window.failRead='b';});
    await page.getByRole("button", { name: /Recent thread/ }).click();
    await waitText("Could not open this saved chat"); await absent("Saved question 0");
    await page.evaluate(() => {window.failRead=null;});
    await page.getByRole("button", { name: "Retry saved chat", exact: true }).click();
    await waitText("Only thread B");

    // Simulate a restored parent selection after a browser reload.
    await page.reload(); await waitText("Saved question 0"); await waitText("Saved question 11");
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole("button", { name: "New chat", exact: true }).focus();
    await page.keyboard.press("Tab"); await page.keyboard.press("Shift+Tab");
    assert.notEqual(await page.getByRole("button", { name: "New chat", exact: true }).evaluate(el => getComputedStyle(el).outlineStyle), "none");
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, "result.json"), JSON.stringify({outcome:"PASS", scope:"deterministic Chat component interactions; mocked API, not full product integration", checks:["no-key list/read/create", "ordering", "full saved messages", "evidence and attachment callbacks", "Debug hidden/enabled", "stale read/create/send isolation", "question-only send", "read/send errors", "parent reload selection", "responsive/focus"]}, null, 2));
    console.log("PASS: early R17 Chat component; deterministic API only, no full integration/gate claim");
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
