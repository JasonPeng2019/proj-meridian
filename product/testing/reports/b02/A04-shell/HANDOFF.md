# B02 / M04 shell handoff — 2026-11-05

Scope: `development/frontend/src/App.tsx`, the focused remote-only suite
`testing/tests/shell_m0.cjs`, and this report. No other screen, contract, package,
config, global style, plan, USER_TODO, source record, or chat store was changed.

The shell has a desktop sidebar, Chat/Parts selection, responsive scoped CSS,
keyboard focus/skip link, and a nonmodal shared part panel. The same `PartPage`
slot is used beside Chat and Parts; the Chat instance remains mounted across
page/panel changes. Close/Escape returns focus to the opening control. A narrow
viewport stacks the part panel below the content instead of hiding Chat.

`status.debug_enabled === true` alone exposes Debug. Review is nested inside
Debug, not ordinary navigation. Detailed server status text and synthetic fixture
identification are displayed only in Debug, with credential/private-path
redaction. Ordinary capability failures use short actionable messages. The M0
part placeholder displays only `Unavailable` review status; M02/M17 continue to
own honest derivation of Human reviewed / AI reviewed / Unavailable. The frozen
reconstruction label is preserved for a model request. No engineering result,
human review, fixture content, or runtime observation was invented.

## Frozen integration points

`Shell` implements `ShellProps`, adding an optional typed `screens` injection.
`App` accepts optional props and otherwise fetches `/api/status` through the
frozen `ApiClient` transport in this owned module. No concrete API client existed
in the assigned revision. Missing status has a connection/retry state; it never
enables Debug. No browser persistence store or client citation ledger is created.

ROOT's M1 integration delta is to import the producer exports into `App.tsx` and
replace the corresponding `emptyScreens` slots (or pass stable components through
`screens`). Canonical paths and props:

- `./chat/Chat` → `ChatProps` (A18).
- `./part/PartPage` → `PartPageProps` (A19), identical component for both contexts.
- `./part/Parts` → `PartsProps` (A20).
- `./review/Review` → `ReviewProps` (A22), mounted only inside enabled Debug.

The existing A02 contracts are unchanged. Chat receives full `status` and must
keep its detailed message/fixture diagnostics in Debug. The shell's transport
does not truncate history or supply client history/ledger to conversation send.
List/new/read/send use A02's `/api/conversations` routes and A03 supplies their
actual capability; this M0 shell does not implement a list or composer.

The shell stores only selected conversation ID in the `conversation` URL query,
verifies restored IDs with a server read before passing them to Chat, clears the
part panel on selection change (including New chat's newly created ID), and
ignores late part/source callbacks for another ID. A late restore cannot override
a newer selection. Fixture/synthetic restores stay unavailable. M18 still owns
full saved-message rendering and its own stale-read/send handling; M15 owns
selected-thread last10 context and all storage/authorization. History reads have
no key check here.

`sourcePartRequest` preserves the actual source target, page and box; explicit
part IDs take precedence. Drawing IDs and BOM row IDs map via frozen stable-name
rules. Missing identity and README targets show a brief unavailable notice rather
than opening an unrelated part. README reading/deep-link routing remains M3.
`on_open_source` still receives the original target. Part requests retain requested
tab, example and highlights. The placeholder contains no review actions.

## Actual verification and remaining work

Local work was limited to reading contracts/rules, static TypeScript/CSS and test
inspection, `node --check testing/tests/shell_m0.cjs` (syntax only, exit 0), and
`git diff --check` (exit 0) plus path inspection. No tests, typecheck, build,
browser, PDF/CAD, model/provider call or heavy job ran locally. No runtime or
source-derived engineering validation is claimed. No new human decision is
needed for this M0 slice, so no USER_TODO delta is requested.

The authored deterministic suite covers default-hidden/enabled navigation,
customer copy isolation, frozen injected props, source identity/highlight
preservation, exact history/part/asset transport routes and brief API errors.
It uses actual React server rendering and transport with a scripted fetch boundary.
It does **not** exercise effects, selection transitions, keyboard interaction,
Debug/Review clicks or visual layout. Those browser checks remain for integration
and V3, including stale callback/restore races, reload, New chat, panel clearing,
Chat preservation, shared PartPage behavior, Debug redaction and focus return.

ROOT should publish this exact committed candidate to `harness-v2` and run on
Actions from `product/testing` (all commands below are locally SKIPPED):

```sh
npm --prefix ../development/frontend ci
npm --prefix ../development/frontend run typecheck
../development/frontend/node_modules/.bin/tsc --strict --target ES2022 --module commonjs --jsx react-jsx --lib ES2022,DOM --esModuleInterop --skipLibCheck --rootDir ../development/frontend/src --outDir tmp/A04-shell/compiled ../development/frontend/src/App.tsx
NODE_PATH="$PWD/../development/frontend/node_modules" node tests/shell_m0.cjs
npm --prefix ../development/frontend run build
```

Remote results are pending; no remote passing run is claimed. No package/config
or shared contract delta is requested. ROOT remains the CI/integration writer.
