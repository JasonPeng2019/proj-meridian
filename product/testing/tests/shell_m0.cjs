// Remote-only deterministic checks; invoke from testing/ after compiling App.tsx.
// These exercise real server rendering and transport, not browser interaction.
const assert = require("node:assert/strict");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "../..");
const frontendRequire = createRequire(path.join(root, "development/frontend/package.json"));
const React = frontendRequire("react");
const { renderToStaticMarkup } = frontendRequire("react-dom/server");
const { Shell, createApiClient, sourcePartRequest } = require(path.join(root, "testing/tmp/A04-shell/compiled/App.js"));
const { customer_review_status } = require(path.join(root, "testing/tmp/A04-shell/compiled/contracts.js"));
const noCall = () => { throw new Error("Rendering must not call a service or navigate"); };
const status = { chat_available: false, chat_state: "missing_key", synthetic: true,
  message: "M03 fixture diagnostic; needs-human-review; FAILED weight; api_key=private-value",
  fixture_note: "internal fixture provenance" };
const render = (overrides = {}) => renderToStaticMarkup(React.createElement(Shell, {
  api: new Proxy({}, { get: () => noCall }), status,
  on_open_part: noCall, on_open_source: noCall, ...overrides,
}));
// Strip CSS before checking customer-facing text.
const visibleMarkup = (value) => value.replace(/<style>[\s\S]*?<\/style>/g, "");
for (const debug_enabled of [undefined, false]) {
  const markup = render({ status: { ...status, debug_enabled }, initial_debug_panel: "review" });
  const content = visibleMarkup(markup);
  assert.match(content, /Main navigation/);
  assert.match(content, /Chat/);
  assert.match(content, /Parts/);
  assert.match(content, /Configure the chat key on the server/);
  assert.doesNotMatch(content, /Debug|Review|M03|fixture|provenance|needs-human|FAILED|private-value/);
  assert.match(markup, /:focus-visible/);
  assert.match(markup, /@media \(max-width: 700px\)/);
  assert.match(content, /Skip to content/);
}
const enabled = visibleMarkup(render({ status: { ...status, debug_enabled: true } }));
assert.match(enabled, /Debug/);
// Engineering Review is reached through Debug, never an ordinary tab.
assert.doesNotMatch(enabled, />Review<|M03|private-value|needs-human|FAILED/);
const parts = visibleMarkup(render({ initial_page: "parts" }));
assert.match(parts, /Parts unavailable/);
assert.match(parts, /hidden=""/); // Chat stays mounted while Parts is selected.

// Frozen integration props are passed through, without fabricating review state.
let chatProps, partsProps;
render({ initial_page: "parts", screens: {
  Chat: (props) => { chatProps = props; return null; },
  Parts: (props) => { partsProps = props; return null; },
} });
assert.equal(chatProps.selected_conversation_id, null);
assert.deepEqual(chatProps.debug, { enabled: false });
assert.deepEqual(partsProps.debug, { enabled: false });
assert.equal(typeof chatProps.on_select_conversation, "function");
assert.equal(typeof chatProps.on_open_source, "function");
assert.equal(chatProps.api, partsProps.api);
assert.equal(customer_review_status({ usable: false, current_source_hashes: {} }), "Unavailable");
assert.equal(customer_review_status({ usable: true, current_source_hashes: { source: "a" } }), "Unavailable");
// Confirmed/AI review derivation belongs to M02/M17's existing focused suites.

const target = { kind: "drawing", name: "D-013/drawing/material", drawing_id: "D-013", page: 2, box: [1, 2, 3, 4] };
assert.deepEqual(sourcePartRequest(target), { part_id: "D-013/part", tab: "drawing", highlights: [target] });
const linked = { ...target, part_id: "BOM:section/linked/part" };
assert.equal(sourcePartRequest(linked).part_id, linked.part_id);
const bom = { kind: "bom", name: "BOM:section/item/material", row_name: "BOM:section/item" };
assert.deepEqual(sourcePartRequest(bom), { part_id: "BOM:section/item/part", tab: "detail", highlights: [bom] });
assert.equal(sourcePartRequest({ kind: "part", name: "unknown" }), null);
assert.equal(sourcePartRequest({ kind: "readme", name: "README/intro/p1", part_id: "unrelated" }), null);

async function transportChecks() {
  const calls = [];
  let response = { ok: true, status: 200, json: async () => ({ synthetic: true }), blob: async () => new Blob(["synthetic"]) };
  const api = createApiClient(async (url, options) => { calls.push({ url, options }); return response; });
  await api.status();
  await api.conversations();
  await api.create_conversation();
  await api.conversation({ conversation_id: "thread/one" });
  await api.send_conversation({ conversation_id: "thread/one" }, { message: "next" });
  assert.deepEqual(calls.slice(0, 5).map(call => call.url), ["/api/status", "/api/conversations", "/api/conversations", "/api/conversations/thread%2Fone", "/api/conversations/thread%2Fone/messages"]);
  assert.equal(calls[1].options.method, undefined); // No key or write for history reading.
  assert.equal(calls[2].options.body, "{}");
  assert.equal(calls[4].options.body, '{"message":"next"}'); // No client history or citation ledger.
  await api.part({ id: "BOM:section/item/part" });
  assert.equal(calls.at(-1).url, "/api/parts/BOM%3Asection%2Fitem%2Fpart");
  await api.image({ id: "D-013/part", page: 2, thumb: 1 });
  assert.equal(calls.at(-1).url, "/api/parts/D-013%2Fpart/image?page=2&thumb=1");
  const model = await api.model({ drawing_id: "D-013", example: "B" });
  assert.equal(calls.at(-1).url, "/api/models/D-013_B.glb");
  assert.ok(model instanceof Blob);
  await api.parts({ has_3d: false, section: null });
  assert.equal(calls.at(-1).url, "/api/parts?has_3d=false");
  for (const code of [404, 501, 500]) {
    response = { ok: false, status: code, json: noCall, blob: noCall };
    await assert.rejects(api.status(), error => {
      assert.match(error.message, /unavailable|try again/);
      assert.doesNotMatch(error.message, /fixture|M03|private|diagnostic/);
      return true;
    });
  }
}
transportChecks().then(() => console.log("PASS: M0 shell render, frozen props, source targets and transport; browser transitions not exercised"))
  .catch(error => { console.error(error); process.exitCode = 1; });
