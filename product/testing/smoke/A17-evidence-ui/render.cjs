// Remote-only focused presentation checks. No DOM, network or real decisions.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "../../..");
const frontendRequire = createRequire(path.join(root, "development/frontend/package.json"));
const React = frontendRequire("react");
const { renderToStaticMarkup } = frontendRequire("react-dom/server");
const widgets = require(path.join(root, "testing/tmp/A17-evidence-ui/compiled/chat/Evidence.js"));
const fixture = JSON.parse(fs.readFileSync(path.join(root, "testing/fixtures/contracts/chat-response.json"), "utf8"));
const render = (name, props) => renderToStaticMarkup(React.createElement(widgets[name], props));
const forbiddenAction = () => { throw new Error("Render invoked a navigation callback"); };
const debug = { enabled: true, on_open_review: forbiddenAction, on_open_history: forbiddenAction };
const fact = structuredClone(fixture.facts["D-013/drawing/material"]);
fact.review_item = { id: "synthetic-review", href: "/debug/review/synthetic-review" };
fact.correction = { original: "Original synthetic material", corrected: "Synthetic correction",
  by: "Synthetic reviewer", at: "2026-11-05T12:00:00Z", decision_id: "synthetic-decision" };
const hidden = render("Undetermined", { fact });
assert.match(hidden, /Unavailable/);
assert.doesNotMatch(hidden, /Undetermined|source_conflict|Waiting for review|Original synthetic|Synthetic reviewer|Debug/);
const enabled = render("Undetermined", { fact, debug });
for (const text of ["Debug", "source_conflict", "Original synthetic material", "Synthetic reviewer", "Waiting for review"]) {
  assert.ok(enabled.includes(text), `Missing Debug detail: ${text}`);
}
fact.review_item = null;
assert.doesNotMatch(render("Undetermined", { fact, debug }), /Waiting for review/);
assert.doesNotMatch(render("Undetermined", { fact, debug: { enabled: false } }), /Debug|source_conflict/);
const normal = render("Evidence", { response: fixture, on_open_source: forbiddenAction });
assert.match(normal, /🧪/); // The fixture starts with an astral Unicode code point.
assert.match(normal, /Sources · 2/);
assert.match(normal, /Sources · 1/);
assert.doesNotMatch(normal, /\[(?:cite|undetermined):|Debug|source_conflict/);
const invalid = { ...fixture, markers: [], warnings: [], text: "🧪 Invalid [cite: nonexistent] and [undetermined: broken" };
const invalidHidden = render("Evidence", { response: invalid, on_open_source: forbiddenAction });
assert.doesNotMatch(invalidHidden, /nonexistent|broken|invalid citation|Sources ·/);
const invalidDebug = render("Evidence", { response: invalid, on_open_source: forbiddenAction, debug });
assert.match(invalidDebug, /could not be validated/);
const privateWarning = { code: "invalid_citation", message: "C:\\Users\\Synthetic\\private.txt" };
const credentialWarning = { code: "invalid_citation", message: "api_key=synthetic-sensitive-value" };
const warnings = render("WarningList", { debug, warnings: [privateWarning, credentialWarning] });
assert.doesNotMatch(warnings, /Users|private\.txt|synthetic-sensitive-value/);
assert.match(warnings, /withheld/);
assert.equal(render("WarningList", { debug: { enabled: false }, warnings: [privateWarning] }), "");
for (const status of ["Human reviewed", "AI reviewed", "Unavailable"]) {
  assert.match(render("ReviewStatus", { status }), new RegExp(status));
}
assert.match(render("SourceTag", { facts: [fact], on_open_source: forbiddenAction }), /aria-expanded="false"/);
assert.ok(fs.existsSync(path.join(root, "development/frontend/src/chat/Evidence.tsx")));
assert.ok(!fs.existsSync(path.join(root, "development/frontend/src/shared/Evidence.tsx")));
for (const [name, props] of [
  ["Evidence", { response: fixture, on_open_source: forbiddenAction }],
  ["SourceTag", { facts: [fact], on_open_source: forbiddenAction }],
  ["Undetermined", { fact }],
  ["ReviewStatus", { status: "Unavailable" }],
  ["MethodBadge", { debug, method: "parsed", badge: "Synthetic source" }],
  ["WarningList", { debug, warnings: [privateWarning] }],
]) {
  const markup = render(name, props);
  assert.match(markup, /<style>/, `${name} requires self-contained styles`);
  assert.match(markup, /\.meridian-evidence \.me-source-popup \{ position: absolute/);
  assert.match(markup, /button:focus-visible/);
  assert.doesNotMatch(markup, /class="[^"]*\b(?:bg-slate-50|border-blue-200|relative|inline-flex)\b/);
}
console.log("PASS focused rendering: canonical module, standalone scoped styles, Unicode spans, marker suppression, default-hidden/enabled Debug, review destinations, redaction and labels. Visual/hover/navigation journeys remain V3.");
