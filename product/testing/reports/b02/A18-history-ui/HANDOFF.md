# A18 early R17 history UI

Scope: PLAN M18 / WORKFLOW B02 early history slice only, based on native `1aba9fbec246cf8e4adbe676cad9fb2fc4234733`. No full Chat/product/gate, real source accuracy, browser, build or sending integration claim.

Implemented `development/frontend/src/chat/Chat.tsx` with frozen `ChatProps`, named/default `Chat` exports, no new dependencies or M19 import. Server-only list/create/read, updated-time ordering, parent-owned ID selection, full saved messages, M17 Evidence, attachment detail/drawing/example-specific model callbacks and reconstruction identification. No client history/ledger is sent. Thread switches reset drafts/errors and unmount old message/evidence controls; version/lifecycle checks discard stale read/create/send responses. Request failures use fixed customer copy, never server exception/status diagnostics. No-key list/create/read remain independent of send availability. Debug is supplied through frozen props to M17; warnings and review remain there. Scoped CSS handles narrow panel/mobile layouts and visible keyboard focus without Tailwind.

The continuation path is authored against the frozen server endpoint, gated by `status.chat_available` and key state. Current early backend sending remains unavailable. Real grounded sending, full shell/part integration and E3/E7/E15 product acceptance remain B05/B06/V2/V3.

## Checks

| Outcome | Command / inspection | Evidence |
| --- | --- | --- |
| PASS | `node --check testing/tests/chat_history_ui.cjs` | Local syntax only; exit 0. |
| PASS | `git diff --cached --check` | Local whitespace/static check; exit 0. |
| PASS | Static ownership/API inspection | Only Chat.tsx and this narrow testing suite/report. No package/config/contracts/App/source/data edits, storage, provider calls or client history/ledger payload. |
| SKIPPED | `npm --prefix ../development/frontend run typecheck` from `testing/` | Remote only; not executed by worker. |
| SKIPPED | `npm --prefix ../development/frontend run build -- --outDir ../../testing/tmp/A18-history-ui/frontend-dist` from `testing/` | Remote only; not executed by worker. |
| SKIPPED | `node tests/chat_history_ui.cjs` from `testing/` | Remote only; not executed by worker. |

## ROOT remote run and wiring

ROOT should publish the exact candidate to `harness-v2` and run the checks on Actions. From the remote `product/testing/` directory, install locked existing dependencies if absent:

```sh
npm --prefix ../development/frontend ci
npm --prefix ci ci
export PLAYWRIGHT_BROWSERS_PATH="$PWD/tmp/A18-history-ui/browsers"
npm exec --prefix ci -- playwright install --with-deps chromium
npm --prefix ../development/frontend run typecheck
npm --prefix ../development/frontend run build -- --outDir ../../testing/tmp/A18-history-ui/frontend-dist
node tests/chat_history_ui.cjs
```

Suite uses actual React/browser interactions and deterministic synthetic API objects, never real chats, keys, model executions or source review. It starts/stops a Vite server and Chromium within its own process, with cache/result files under `testing/tmp/A18-history-ui/`. Assertions cover no-key list/read/create, ordering, >10 saved messages, M17 source and drawing/model callbacks, hidden/enabled Debug, late reads/creates/sends after switches, question-only send, successful continuation/full reload/reordering, failed send retaining draft, read retry, parent-restored selection, responsive width and focus. Server restart persistence is the accepted M15/M03 responsibility; this suite cannot establish that or full shell integration. Download `testing/tmp/A18-history-ui/result.json` after a passing remote run. No remote result exists yet.

Tiny shell wiring request (ROOT/A04-owned App.tsx, unchanged here): `import Chat from "./chat/Chat";` and set `emptyScreens.Chat` to `Chat` (or inject `screens={{ Chat }}`). Preserve frozen props, parent URL selection and shared panel callbacks. M19 remains absent; use the current shared panel placeholder until its producer lands.

No new human decision or USER_TODO is required. Inbox was empty on startup; reread before RESULT publication. Implementation handoff PASS concerns authored scoped artifacts/static checks only; all runtime evidence remains SKIPPED pending the exact remote revision.
