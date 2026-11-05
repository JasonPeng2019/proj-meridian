// Runs with shell_m0.cjs after App.tsx and its imports are compiled remotely.
const assert = require("node:assert/strict");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "../..");
const frontendRequire = createRequire(path.join(root, "development/frontend/package.json"));
const React = frontendRequire("react");
const { renderToStaticMarkup } = frontendRequire("react-dom/server");
const { PartPage, drawingHighlightStyle } = require(path.join(root, "testing/tmp/A04-shell/compiled/part/PartPage.js"));
const noCall = () => { throw new Error("Server rendering must not call a service or navigate"); };
const api = new Proxy({}, { get: () => noCall });
const debug = { enabled: true, on_open_review: noCall };
const geometry = { page: 1, source_width: 100, source_height: 50, image_width: 400, image_height: 300 };
const part = {
  fixture: true, synthetic: true, id: "D-013/part", display_name: "Declared plate fixture", section: null,
  has_drawing: true, has_3d: false, examples: [],
  drawing: { id: "D-013", pages: 2, image: "/api/image", page_geometry: [geometry], degraded: false,
    source_quality: "clean", source_path: "C:/private/input.pdf", source_sha256: "drawing-hash",
    fields: { material: { name: "D-013/drawing/material", original: "original material", value: "current material",
      method: "parsed", page: 1, box: [10, 5, 20, 10], source_quality: "clean", note: "api_key=private-value" } } },
  bom: [{ name: "BOM:section/item", display_id: "item", display_name: "Purchased item", section: "Section 1", source_sha256: "bom-hash",
    fields: { price: { name: "BOM:section/item/price", original: "", value: null, method: "parsed", currency: "DKK" },
      material: { name: "BOM:section/item/material", original: "uncertain candidate", value: "uncertain candidate", confidence: "unsure", method: "parsed" } } }],
  link: null, template: null, model: { state: "missing", unresolved_fields: ["internal-model-field"] },
  weight_check: { state: "FAILED", message: "engineering weight detail" },
  review_items: [{ id: "pending-review", href: "/debug/review/pending-review" }],
  facts: {
    "D-013/drawing/thickness": { fact: "D-013/drawing/thickness", part_id: "D-013/part", display: { value: 5, unit: "mm" },
      rule: "private-rule", badge: "parsed", sources: [] },
    "D-013/drawing/material": { fact: "D-013/drawing/material", part_id: "D-013/part", display: { reason: "model_disagreement", message: "verifier disagreed" },
      rule: "private-rule", badge: "unresolved", sources: [] },
    "D-013/drawing/diameter": { fact: "D-013/drawing/diameter", part_id: "D-013/part", display: { values: [10, 12], message: "printed choices", unit: "mm" },
      rule: "private-rule", badge: "parsed", sources: [] },
  },
};
const render = (overrides = {}) => renderToStaticMarkup(React.createElement(PartPage, {
  api, part_id: part.id, record: part, on_open_source: noCall, on_open_part: noCall, ...overrides,
})).replace(/<style>[\s\S]*?<\/style>/g, "");

for (const context of [undefined, { enabled: false }]) {
  const ordinary = render({ debug: context });
  assert.match(ordinary, /Declared plate fixture/);
  assert.match(ordinary, /5 mm/);
  assert.match(ordinary, /Printed options: 10 \/ 12 mm/);
  assert.match(ordinary, /Unavailable/);
  assert.match(ordinary, /Source unavailable/);
  assert.doesNotMatch(ordinary, /Debug|FAILED|engineering weight|pending-review|private-rule|model_disagreement|verifier disagreed|original material|uncertain candidate|internal-model-field|private-value|C:\/private/);
  assert.doesNotMatch(ordinary, /Human reviewed|AI reviewed/); // No review is invented from parsed values.
}
const engineering = render({ debug });
assert.match(engineering, /Debug/);
assert.match(engineering, /FAILED: engineering weight detail/);
assert.match(engineering, /Original: original material/);
assert.match(engineering, /Current value: current material/);
assert.match(engineering, /model_disagreement/);
assert.match(engineering, /Open review item/);
assert.doesNotMatch(engineering, /private-value|C:\/private/);

const bomOnly = render({ record: { ...part, has_drawing: false, drawing: null }, initial_tab: "drawing" });
assert.match(bomOnly, /Parts list/);
assert.match(bomOnly, /Drawing: Unavailable/);
assert.doesNotMatch(bomOnly, /role="tab"[^>]*>Drawing</);
const requestedModel = render({ initial_tab: "model" });
assert.match(requestedModel, /3D view: Unavailable/);
assert.match(requestedModel, /Reconstruction from 2D drawing. Not the original CAD model./);
const drawing = render({ initial_tab: "drawing", highlights: [{ kind: "drawing", name: "D-013/drawing/material", drawing_id: "D-013", page: 2, box: [10, 5, 20, 10] }] });
assert.match(drawing, /Zoom in/);
assert.match(drawing, /Zoom out/);
assert.match(drawing, />Fit</);
assert.match(drawing, /value="2" selected=""/);

// Different horizontal/vertical image scales must preserve source-box placement.
assert.deepEqual(drawingHighlightStyle([10, 5, 20, 10], geometry), {
  left: "10%", top: "10%", width: "20%", height: "20%",
});
console.log("PASS: part SSR, honest unavailable/options, default-hidden Debug, private text redaction, multi-page selection and source-coordinate overlay; browser/image loading not exercised");
