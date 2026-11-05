# A17 / M17 M1 component handoff

Implementation candidate only; remote runtime validation is **PENDING**. This report does not claim a passing component runtime, source-validation run, browser journey, product gate, AI execution, or human review. Historical codegen/qualification results are not evidence for this change. `RESULT.json` records the full committed candidate tip.

## Scope and interfaces

The latest task-card instruction explicitly owns `development/frontend/src/shared/Evidence.tsx`; it supersedes the older `chat/Evidence.tsx` deliverable path in the same card and plan. No compatibility file or other module was edited.

Named exports use the unchanged frozen props from `contracts.ts`: `Evidence(EvidenceProps)`, `SourceTag(SourceTagProps)`, `Undetermined(UndeterminedProps)`, `MethodBadge(MethodBadgeProps)`, `WarningList(WarningListProps)`, and `ReviewStatus(ReviewStatusProps)`. No default export, parallel payload schema, API client, storage, global navigation, provider, approval implementation, or shared CSS was added. Inline Tailwind classes use the existing configuration.

`Evidence` removes marker-looking syntax and only renders citations authorized by the response's exact valid Unicode-code-point marker spans and supplied facts. Invalid/missing marker metadata produces Unavailable; explanations appear in Debug. Source tags offer pointer hover, click/keyboard expansion, Escape/close dismissal and one callback button per supplied source, preserving each target and source text. Values/units and printed options remain separate from source and review badges. No source is inferred. Missing-source citations say so when expanded.

The frozen `customer_review_status` helper receives actual supplied source hashes, review and field-bound provenance. Input aliases use declared source-ID bindings and accepted-field evidence references matched to the supplied source hash. Conflicting/unavailable hash bindings do not confer review; opaque or insufficient bindings conservatively stay Unavailable. Parsed/legacy method names, equal values and Sol-only fallback never confer AI review. `ReviewStatus` accepts only the frozen three-label union.

Debug is absent without `debug.enabled === true`. Optional Debug contains uncertainty reasons, original/corrected values, reviewer/date, source hashes, method/confidence/notes, candidate/source digests, retained determination/verifier rounds and reasons/evidence, fallback identification and warnings. Waiting for review requires an actual `ReviewLink` with ID and destination and calls only `debug.on_open_review`; decision history calls only the supplied optional callback. Debug-only `MethodBadge`/`WarningList` require `DebugAccess` and additionally check its enabled flag. Arbitrary provenance objects, CLI failure messages, authentication and private path fields are never dumped; display text redacts recognizable credential/private-path strings. Source text is verbatim except for those privacy redactions and raw marker suppression.

M3 crops remain deferred. Reconstruction identification belongs to the existing viewer/part contracts; this component neither creates a model view nor removes its label. Weight/history/approval workflows remain with their assigned owners.

## Actual local checks

- Read operating rules, goal/handoff, PLAN R9/R10/M17, WORKFLOW and frozen Python/TypeScript payloads/props, plus the explicitly synthetic contract fixture. No fixture is credited as original evidence or executed AI/human review.
- Static TypeScript inspection: reviewed imports/exports, payload narrowing, Unicode offsets, Debug gates, source/review callbacks and source-hash mapping. This was source inspection, **not** compiler validation.
- `git diff --cached --check`: whitespace/error inspection of the staged scoped changes; result recorded in RESULT.
- `git diff --cached --name-only` and final `git status --porcelain=v1 --untracked-files=all`: ownership and clean-source inspection; exact final tip is in RESULT.
- Invocation metadata reports Codex `gpt-6.1-sol`, high reasoning, fast service tier. No child CLI or fallback was launched.

## Exact remote commands (pending)

ROOT publishes the candidate as ordinary `product/` files to `JasonPeng2019/proj-meridian`, exclusively `harness-v2`, records its exact outer revision, and runs these commands on the remote Linux runner from `product/testing`. Dependency setup, compiler, SSR checks and build are remote only:

```sh
npm --prefix ../development/frontend ci
npm --prefix ../development/frontend run typecheck
../development/frontend/node_modules/.bin/tsc --strict --target ES2022 --module commonjs --jsx react-jsx --lib ES2022,DOM --esModuleInterop --skipLibCheck --rootDir ../development/frontend/src --outDir tmp/A17-evidence-ui/compiled ../development/frontend/src/shared/Evidence.tsx
NODE_PATH="$PWD/../development/frontend/node_modules" node smoke/A17-evidence-ui/render.cjs
npm --prefix ../development/frontend run build
```

The authored remote render check covers fixture Unicode spans, marker suppression, actual source counts, default-hidden/enabled Debug, real versus missing review destinations, correction visibility, label rendering and display redaction. It has **not run**. Capture compiler/runtime/build outputs and exit codes against the exact candidate. No dependency install, suite, typecheck, build, browser, model, PDF or CAD execution was performed locally.

V3 owns integrated browser journeys: hover/focus/click/Escape and narrow-screen source access; every source verbatim and unchanged callback target; known/options/Unavailable and honest status mapping; default/enabled Debug across Chat/Parts/Review; actual review/history callbacks; malformed/invalid citations and source highlights. The planned `testing/frontend/mvp.spec.ts` does not exist in this candidate; no executable browser command or passing journey is invented here.

## Exact shared integration requests

- A18/A19/A22 import the named widgets from `../shared/Evidence`, using the existing frozen props. A04 supplies the unchanged `on_open_source` boundary; enabling Debug supplies the same frozen context everywhere. Place Debug-only `MethodBadge` and `WarningList` inside the host Debug view. No change to contracts, callbacks or package/config/CSS is requested.
- ROOT/A01 run the exact pending remote commands above for this candidate; the ordinary workflow does not yet invoke this new focused render check. This is an integration request only; no CI file was edited.
- No USER_TODO, human decision, source correction, fixture modification or prep-contract change is requested by this slice.
