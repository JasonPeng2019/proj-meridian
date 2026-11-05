// Focused parity checks against independently stated expectations from the
// Python smoke checker; no frontend, browser, app server, or paid services.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../../..");
const temporary = path.join(root, "testing/tmp/A02-contracts");
const contracts = require(path.join(temporary, "compiled/development/frontend/src/contracts.js"));
const cases = JSON.parse(fs.readFileSync(path.join(temporary, "helper-cases.json"), "utf8"));

assert.equal(contracts.normalize_component("  Training / BRACKET__ (Q)  "), "training-bracket__-q");
assert.equal(contracts.drawing_fact_name(" d-013 ", "Weight_g"), "D-013/drawing/weight_g");
assert.equal(contracts.template_fact_name("D-025", "Outer Diameter"), "D-025/template/outer-diameter");
assert.equal(contracts.bom_part_name("Mock Section", "Fixture / Clamp"), "BOM:mock-section/fixture-clamp/part");
assert.equal(contracts.mapping_name("material", "Mock Alloy Q7", "Mock Metal"), "names/material/mock-alloy-q7 -> mock-metal");
assert.equal(contracts.readme_name("Synthetic Section", 2), "README/synthetic-section/p2");
for (const {value, encoded} of cases.ids) {
  assert.equal(contracts.encode_id(value), encoded);
  assert.equal(contracts.decode_id(encoded), value);
}
assert.throws(() => contracts.decode_id("bad%2"));
assert.throws(() => contracts.decode_id("raw/slash"));
const close = (actual, expected) => actual.forEach((value, index) =>
  assert.ok(Math.abs(value - expected[index]) < 1e-10, `${actual} != ${expected}`));
for (const {box, zoom, offset, pixels} of cases.coordinates) {
  const actual = contracts.source_box_to_pixels(box, cases.page, zoom, offset);
  close(actual, pixels);
  close(contracts.pixel_box_to_source(actual, cases.page, zoom, offset), box);
}
assert.throws(() => contracts.source_box_to_pixels([1, 1, 2, 2], cases.page, 0));
assert.throws(() => contracts.source_box_to_pixels([1, 1, -2, 2], cases.page));
assert.equal(contracts.image_api_path("D-013/part", 1, true), "/api/parts/D-013%2Fpart/image?page=1&thumb=1");
assert.equal(contracts.review_api_path("review/D-013/drawing/title"), "/api/review/review%2FD-013%2Fdrawing%2Ftitle");
assert.equal(contracts.review_link("review/D-013/drawing/title"), "/debug/review/review%2FD-013%2Fdrawing%2Ftitle");
assert.equal(contracts.model_api_path("D-013", "B"), "/api/models/D-013_B.glb");
assert.deepEqual(contracts.API_ENDPOINTS, cases.endpoints);
for (const {input, expected} of cases.review_status) {
  assert.equal(contracts.customer_review_status(input), expected);
}
assert.deepEqual(contracts.shell_navigation({}), ["chat", "parts"]);
assert.deepEqual(contracts.shell_navigation({debug_enabled: false}), ["chat", "parts"]);
assert.deepEqual(contracts.shell_navigation({debug_enabled: true}), ["chat", "parts", "debug"]);
const actions = {on_open_review: () => { throw new Error("Hidden Debug action leaked"); }};
assert.deepEqual(contracts.debug_context({}, actions), {enabled: false});
assert.deepEqual(contracts.debug_context({debug_enabled: false}, actions), {enabled: false});
assert.equal(contracts.debug_context({debug_enabled: true}, actions).on_open_review, actions.on_open_review);
assert.equal(contracts.PREP_PIPELINE_VERSION, "determine-verify/v1");
assert.equal(contracts.RECONSTRUCTION_LABEL, "Reconstruction from 2D drawing. Not the original CAD model.");
const chat = JSON.parse(fs.readFileSync(path.join(root, "testing/fixtures/contracts/chat-response.json"), "utf8"));
for (const marker of chat.markers) {
  assert.equal(Array.from(chat.text).slice(marker.start, marker.end).join(""), marker.raw);
}
console.log("PASS TypeScript runtime: names/URLs/coordinates/endpoints/Unicode, honest review status parity, default-hidden/enabled Debug navigation and actions");
