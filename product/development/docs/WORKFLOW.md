# Project Meridian multi-agent workflow

## Basis

- **Plan:** [PLAN.md](PLAN.md), including 27 modules, requirements R1-R17, expectations E1-E15 and five verification checkpoints. Module IDs M01-M27 differ from product milestones M0-M3.
- **Assignment:** [Project Meridian requirements](../inputs/project-meridian/README.md). [mvp (1).md](<../inputs/mvp (1).md>) controls build scope; [proposal.md](../inputs/proposal.md) supplies included-feature behavior. The user's later instructions add minimal deterministic tests and selective semantic verification.
- **Destination/application root:** This workflow is `product/development/docs/WORKFLOW.md`. Implementation paths below are relative to `Avathon/product/development/`.
- **Status:** B00 M01/M02 and the bounded prep/CAD qualification slices were accepted and integrated locally. Product V1?V5 and the final benchmark remain unverified; HANDOFF records exact evidence and current execution state.
- **Concurrency:** At most four local CLI agents total, including coding, test, semantic and prep subprocesses. ROOT is this conversation. Lower the count under CPU/RAM pressure. One prep job runs determination then verification sequentially; reserve a child CLI slot while counting the prep owner. Queue other prep jobs. CAD, regeneration, builds and browser verification run remotely and sequentially. See PLAN's resource update and CWD AGENTS.md.
- **Tier mapping:** Use the explicit model bindings below for every coding, coordination, test, and semantic assignment. Application chat and data preparation have their own bindings; an agent's tier does not select the application's model.
- **Human inputs:** Use existing CLI-account authentication and the chat key under CWD `.secrets`. Queue mapping/evidence decisions for Jason in `development/USER_TODO.md`; coding and prep continue while he reviews later. Synthetic test decisions never enter his actual decision journal.

## Remote verification and local resource budget

Follow the resource update in [PLAN.md](PLAN.md) and CWD AGENTS.md. Publish through the private `JasonPeng2019/proj-meridian` origin, using only branch `harness-v2`. Lightweight push/PR checks cancel superseded runs. ROOT dispatches heavy checkpoint/regeneration and optional paid checks itself; "manual" means agent-triggered with no human confirmation. Queue heavy runs, use separate sequential CAD and browser jobs, and budget the private Linux runner for two CPUs/8 GB RAM. The first remote run proves Linux CAD dependencies/export and actual headless 3D rendering. Download revision-checked frontend bundles for local serving; required local heavy fallbacks use a single shared serial slot with measured headroom.

M01 owns CI/artifact setup; M23 adds the real gate suites and the preliminary [20-question benchmark](benchmark_draft.md) without creating another semantic code-review checkpoint. M02 must freeze summary-tool contracts before A14 implements `machine_summary()`/`cost_summary()` for Q01/Q02/Q18. A24 documents actual benchmark/usage/repeatability outcomes. Apply milestone conditions and isolated test decisions from PLAN R16/E14; final M3 verification covers all 20 logical questions and Q11's two states. Use cached independent Sol wording judgments only for actual benchmark responses; the app always chats through Luna. Jason's draft/judge spot-check goes in USER_TODO and does not block coding.

B03 implementation can remain parallel against frozen interfaces, but A11's actual local prep waits for a reserved child CLI slot. Sol determination finishes before Opus verification starts, including the single disagreement retry. Stop/suspend other project coding launches as needed to stay within the shared ceiling. Deterministic regeneration, CAD and browser workloads use Actions; local agents author code and inspect reports.

The customer UI is clean by default. Ordinary review status has exactly **Human reviewed**, **AI reviewed**, or **Unavailable**, mapped honestly from actual state. All verification details, needs-human-review notices/queues/actions, disagreements/fallback, weight failures/flags and detailed history/accuracy belong inside **Debug**. A01 supplies its default-hidden launch setting; A02 freezes the status mapping/props; A03 exposes the setting; A04 shows Chat/Parts and optional Debug (Review inside Debug); A19 owns part Debug and A22 its review controls. A17/A21 keep normal views free of engineering warnings/counters. Source navigation and reconstruction identification remain usable. Debug exposes only available non-secret information, not invented evidence. V3 covers hidden/enabled modes and status truthfulness. No new module or semantic checkpoint is added.

**Past chats (R17/E15)** are ordinary customer functionality. A01 configures/ignores `development/chat_history/`; A02 freezes conversation list/create/read/send payloads and server-owned ledger boundaries; A15 owns local JSON conversations and the grounded reply service in its existing file; A03 wires routes; A18 supplies New chat/history selection/reopening/continuation; A04 coordinates thread/part-panel changes. Persist all messages/citations/attachments across reload/restart, but send only that thread's last 10 turns to Luna. Reads work without a key. V2 covers persistence/context/ledger isolation; V3 covers two threads/reload. A02's bounded history-contract follow-up must finish before A15/A18, while A08 can use the refreshed prep contracts. Keep 27 modules and the existing gates/reviewer schedule.

## Model bindings and fallback

### Coding, coordination, and verification agents

| Tier | Primary model and launcher | Reasoning | Processing mode | Allowed fallback |
| --- | --- | --- | --- | --- |
| **STRONG** | DeepSeek v4.1 Flash, `deepseek-v4.1-flash:cloud`, through Codex CLI and Ollama | **max** | Ollama provider mode | None specified |
| **STRONGER** | GPT 6.1 Sol, `gpt-6.1-sol`, through Codex CLI | **high** | **fast / priority** | None specified |
| **STRONGEST** | GPT 6.1 Sol, `gpt-6.1-sol`, through Codex CLI | **max** | **fast / priority** | None specified |
| **GOD-TIER** | Opus 5.5, `claude-opus-5-5`, through Claude Code | **xhigh** | **regular**, fast mode off | GPT 6.1 Sol **max / priority** through Codex CLI, only for a confirmed OAuth or usage-limit failure on that launch |

Pin these settings on each process rather than relying on user defaults. The local Codex/Ollama profile is `ollama-launch`; its model is `deepseek-v4.1-flash:cloud`, with `model_reasoning_effort="max"`. For Sol use `--model gpt-6.1-sol`, the assigned `model_reasoning_effort="high"` or `"max"`, and `service_tier="fast"` (Codex's spelling for priority). For Claude Code use `--model claude-opus-5-5 --effort xhigh` and process settings `fastMode: false` and `fallbackModel: []`. Do not use a floating model alias or a generic automatic fallback chain that substitutes models on overload or unavailability. These are launch requirements, not a claim that this document's authoring session has changed models.

The settings are supported by the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), [GPT 6.1 Sol model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol), and Claude Code's [model configuration](https://code.claude.com/docs/en/model-config) and [fast-mode configuration](https://code.claude.com/docs/en/fast-mode). Local CLI help/profile inspection confirmed the installed launch interfaces; real inference qualification remains execution work.

**GOD-TIER fallback is per launch:**

1. Start every new launch, owner resumption, reviewer follow-up, and repair launch with Opus 5.5 **xhigh / regular**, even if the previous launch used Sol.
2. Fall back only when that launch has a confirmed **OAuth authentication failure** or **account/model usage-limit error**. Classify the actual error payload; a generic HTTP status, temporary overload, or network failure is insufficient.
3. For a qualifying error, use Sol **max / priority** for that launch only. Record the requested/effective model, reasoning, mode, and redacted error classification in the handoff. Do not persist a fallback default or an indefinitely cached "Opus unavailable" flag.
4. For other failures, investigate the proper primary: inspect CLI help and diagnostics, correct model/argument/configuration issues, and retry meaningfully. Missing tools, bad arguments, timeouts, overload, malformed responses, or task errors do not authorize coding-agent substitution. If the primary cannot be made to work, report the affected launch blocked and continue independent work. A failed fallback does not authorize a third model.

### Application chat and data preparation

| Product role | Required model and route | Failure behavior |
| --- | --- | --- |
| **Chat app bot** | **GPT 6 Luna only**, `gpt-6-luna`, through the **OpenAI Responses API**, using the server's OpenAI API key from `.secrets` | Surface the error or missing-key state. No model/provider fallback. Chat reasoning/processing mode is unspecified; do not inherit coding-agent max/priority settings. |
| **Prep determiner** | Codex CLI **GPT 6.1 Sol, max reasoning, priority** | Produce the candidate with evidence, state and reasons. No alternate model is specified for Sol. |
| **Prep verifier** | Claude Code **Opus 5.5, xhigh reasoning, regular mode** | Inspect Sol's exact candidate against original evidence; return field verdicts/reasons/evidence. If execution fails after invocation troubleshooting, continue with Sol's valid result explicitly **single-model, unverified**. |

This ordered pipeline applies to scans, images, geometry/templates, ambiguous drawing/BOM links, name mappings and all AI prep. Opus sees the candidate and original evidence; do not run two independent guesses or compare equal strings as verification. An explicit verifier disagreement allows exactly one Sol revision using its criticism and original evidence, then one Opus reverification. Preserve both rounds; unresolved/unsure/invalid fields stay unresolved. Verifier alternatives are feedback, not directly accepted replacements. The prep-specific Sol-only exception applies only to actual Opus execution failure; disagreement/unsure/invalid output cannot invoke it.

In Sol-only mode, valid source-backed output may continue explicitly **unverified**. Keep missing verifier output and the failed attempt visible, exclude fallback from verified counts, and preserve evidence/uncertainty/mapping approval rules. Every later launch tries Opus again. Cache identities include pipeline version, stage/role, candidate/source digests, prompts, models/settings, contract and verification mode. Historical blind-reader caches/qualification do not establish determine-then-verify acceptance; preserve historical evidence and qualify the new sequence truthfully.

Resolve `.secrets` from the workspace location (currently `../../../.secrets` relative to the application root), with a configurable location for another checkout. Load the selected OpenAI key privately into the backend API client; never into the browser, tracked configuration, captures, or logs. Do not automatically load the application's `.secrets` key into coding/prep CLI subprocess environments; those CLIs use their own configured authentication. A01 documents the key-free location/variable configuration. The [GPT 6 Luna documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) defines its Responses/tool-calling interface.

## Workspace and asynchronous human review

For local orchestration, follow CWD `AGENTS.md` and `harness-to-use/AVATHON_SETUP.md`; these local harness files are excluded from product pushes. Native harness code/configuration is in CWD `harness-to-use/`; the product Git root is `Avathon/product/`. Implementation paths below are relative to `development/`; test/report paths use `../testing/`. Every worker worktree retains those two directories. Run tests with their working directory and temporary/cache/output roots beneath `testing/`.

**No coding or dataset-prep step waits for human review.** ROOT queues real mapping, geometry, evidence, and release-review questions in [USER_TODO.md](../USER_TODO.md). Keep available validated AI results and unapproved/unknown states truthful. Missing human input may defer a particular reconstruction, demonstration, or stable-release claim, but never the next coding batch or M2/M3 integration. Deterministic validators and the two scheduled semantic reviews remain software checkpoints; ROOT evaluates findings and assigns actual defects to owners.

## Coordination and launch rules

**ROOT — GOD-TIER.** ROOT owns plan/workflow consistency, dependency scheduling, contract decisions, integration, and gate/release decisions. This needs the strongest reasoning because it spans the entire assignment, evolving evidence, parallel file ownership, and the distinction between verified software and reviewed engineering data. ROOT does not count as the independent semantic verifier.

Each module has one named logical agent in the roster. Resume that owner for subsequent milestone slices and repairs; an unavailable session can be replaced using the same logical assignment and handoff. Only the selected milestone slice is assigned in one turn. A module owner also owns its generated artifacts, with the exceptions and serialization rules below.

Every launch includes:

1. The agent's roster row, batch slice, tier, owned path, required upstream inputs, and relevant PLAN requirements/expectations.
2. The frozen contract definitions and relevant sections of the original MVP/proposal/assignment. Source examples are not verified engineering answers.
3. One direct deliverable and the row's completion condition. Report actual commands/results, files changed, unresolved inputs, and any contract mismatch. Do not report a blocked live check as passed.
4. The tier's exact model/launcher, reasoning, processing mode, and authentication route from the bindings above. Verify the effective model where the CLI exposes it, and report any mismatch. Record safe requested/effective settings and any fallback reason; never include credentials. Prep jobs additionally record which determination/verification stages completed and their actual verdicts.

**Parallel implementation uses agreed interfaces.** M02 freezes payloads, component props, and callable signatures before consumers start. Independent modules can be implemented together against those contracts; ROOT runs the integrated build after all required exports are present. A shared contract does not waive the need to run the real integrated path before its checkpoint.

**File ownership:** A01 alone changes project/package/config/launcher plumbing; A02 owns contracts/declared fixtures; A03 owns the server/composition file; A04 owns the frontend shell/router. Domain owners request changes to these files through their owners. A11 is the single publisher of prep outputs, A12 of assembled records, and A13 of model files. Real review writes run through A07/A16's application path. Coordinate generation in that order; multiple agents do not rewrite the same output directory concurrently. Gate validators own their test files/reports, and semantic verifiers own only their reports.

After **every agent return**, ROOT applies `$stay-current`: compare progress with the plan; use `$plan` for a necessary scope/module change and update this workflow to match. Leave still-valid assignments alone. Missing work, cycles, or a changed contract are resolved explicitly rather than hidden in another agent's module.

## Module agents and strengths

All rows inherit the corresponding PLAN module's full completion criteria. “Inputs” identify prerequisites for the implementation slice; shared-interface consumers can use declared fixtures until their real producer is ready. Final integration always uses the completed real producer.

| Agent / plan task | Owned implementation file | Strength and reason | Inputs and direct assignment | Completion evidence |
| --- | --- | --- | --- | --- |
| **A01-scaffold / M01** | `pyproject.toml` | **STRONGER** — cross-platform launch and packaging plumbing | Source specs and explicit model bindings; create the setup bundle: locked uv project, runtime/development extras, launcher/config/key-free env example/secret exclusions, Luna-only backend key loading from `.secrets`, independently authenticated prep CLI settings, frontend build plumbing, and unchanged corpus/notices. | Launch/build commands resolve; keys are excluded; runtime/prep settings stay separate; ordinary runtime does not depend on prep/CAD tools. |
| **A02-contracts / M02** | `backend/contracts.py` | **STRONGEST** — incorrect shared contracts would spread across all agents | Freeze fact/record/decision/template/review/chat shapes, sequential determination/verifier verdicts, candidate/source binding, bounded retry and unverified fallback metadata; summary tools and debug status/props; later fields, stable IDs/URLs, coordinates and call boundaries. Supply declared synthetic fixtures and a valid sample GLB. | Consumers have concrete examples/signatures; explicit verification cannot be inferred from string equality or old blind-reader caches; no circular imports. |
| **A03-server / M03** | `backend/app/main.py` | **STRONGER** — constrained composition and lifecycle integration | A01/A02, then the domain services for each slice; provide launch, status, API/static routes and explicit service wiring. Progress from M0 fixtures to V1 real records, V2 real backend, and M2/M3 endpoints. | Actual routes satisfy frozen payloads, slash-bearing IDs/assets work, missing key is truthful, and API requests are not swallowed by SPA fallback. |
| **A04-shell / M04** | `frontend/src/App.tsx` | **STRONGER** — shared navigation state across several screens | A01/A02 and frozen component interfaces; create clean Chat/Parts shell with optional Debug containing Review, then connect screens and shared part panel. M3 adds complete stable routes and the small highlighted README reader. | Chat stays beside the part panel; standalone and embedded part views agree; M3 back/forward and direct reload work. |
| **A05-drawings / M05** | `backend/loader/drawings.py` | **STRONGEST** — PDF positions and questionable fields require careful source interpretation | A01/A02, supplied manifest/PDFs; extract positioned verbatim evidence, label-anchored corner fields, page PNGs and scan crop boxes. M3 adds self-describing callouts and source-coordinate crops. | Independently checked source cases preserve originals; missing/placeholder/overlap stays unsure; highlights align; no inferred dimensions are introduced. |
| **A06-bom / M06** | `backend/loader/bom.py` | **STRONGER** — bounded cleanup and relationship resolution | A01/A02, the actual CSV/headers; normalize rows, retain originals/cleanup reasons, DKK/null/list/snapshot rules, and recorded interface references. M3 completes remaining cleanup and reporting. | All source rows remain inspectable; blank price is not zero; duplicates/ambiguous targets are exposed rather than silently selected. |
| **A07-decisions / M07** | `backend/loader/decisions.py` | **STRONGEST** — preservation and precedence of human decisions are critical | A01/A02 and source fingerprints; implement append-only proposal/action histories and effective overlays. M2 adds changed-evidence invalidation/reapproval without replacing reviewed-evidence hashes. | Pending/rejected proposals do not alter facts; accepted decisions survive regeneration; originals and superseded decisions remain. |
| **A08-runner / M08** | `backend/ai/runner.py` | **STRONGEST** — ordered subprocesses, verification, cache and retry interact | Use A01/A02 to run Sol determination, then Opus verification of that exact candidate/source; validation, role/version-aware cache, serial resource queue, rate limits, one correction/reverification round and authorized unverified fallback. | Scripted cases prove ordering, candidate binding, explicit field verdicts, rejection/revision/reverification, unresolved/invalid handling, cache invalidation and next-launch Opus retry. Record actual model settings and new sequence qualification separately from B00 capability. |
| **A09-vision / M09** | `backend/ai/vision_jobs.py` | **STRONGEST** — source-backed template states must not become guesses | A02/A05/A08; implement scan-corner and three flat-template jobs with exact-text, number-ID, state/options and derivation validation. | Unreadable scans remain Undetermined; unresolved template fields retain available answers and identify missing Opus output; all accepted numerical fields have admissible evidence. |
| **A10-matching / M10** | `backend/ai/matching.py` | **STRONGEST** — ambiguous links and mappings affect many answers | A02/A05/A06/A08; implement unique exact matches, reader candidates, and post-link section/material mapping proposals. Runtime scan/link inputs arrive from A11's stages. | Duplicate filenames do not auto-match; IDs are real; every mapping awaits approval; general-knowledge material evidence is labeled. |
| **A11-preparation / M11** | `backend/ai/prepare.py` | **STRONGEST** — staged retries must not leave stale downstream results | A05–A10; orchestrate ordered determine/verify jobs, publication, downstream invalidation and first-pass verified/retry-verified/unresolved counts with separate unverified fallback counts. | Saved results feed records with truthful author/verifier provenance; changed inputs/candidates invalidate dependent verification; one retry only; ordinary startup needs no CLI call. |
| **A12-records / M12** | `backend/loader/records.py` | **STRONGEST** — multiple evidence/decision shapes converge here | A02/A05/A06/A07 plus fixed prep fixtures, then A11 outputs; assemble source-separated effective records, stable registries, links and templates. | Drawing-only/BOM-only/multi-row cases work; real prep outputs integrate; no human decision or original evidence disappears on rebuild. |
| **A13-cad / M13** | `backend/cad/build.py` | **STRONGEST** — geometry, examples and source states must agree | Early CAD/export qualification; full slice uses A02/A12 effective-template contracts. Build supported neutral-grey GLBs, unknown/omission handling and targeted rebuilds. M2 supplies volume; M3 adds labeled STEP output. | Analytic fixture geometry is correct; real uncertain inputs remain pending; accepted changes affect only the relevant outputs. All three real models are required at the M1 release gate. |
| **A14-tools / M14** | `backend/app/tools.py` | **STRONGEST** — deterministic source resolution defines product truth | A02/A12/A07, approved mapping data and M16's frozen proposal callback; implement read/group/connection/proposal tools and B3 rules 0–5. M3 exposes callouts and README search. | Source conflicts, unsure values, lists, mapping approval, directional material search, badges and snapshot notes follow the intended rules. |
| **A15-chat / M15** | `backend/app/chat.py` | **STRONGEST** — tool traces, citations and attachment behavior are tightly coupled | A02 history boundary/A01 storage settings for the early R17 persistence slice; A14 and server-only `.secrets` key configuration for the full OpenAI Responses tool loop using **gpt-6-luna only**, last-10-turn history, result ledger, marker validation, attachment selection/warnings and usage observations. This coding agent itself uses its STRONGEST Sol binding. | Scripted Responses calls exercise real tools and assert Luna-only requests/no model fallback; fabricated/unseen citations fail; a part remains accessible on abstention; recorded usage/errors are genuine. |
| **A16-review / M16** | `backend/app/review.py` | **STRONGEST** — human authority, durable state and rebuilds must stay consistent | A02/A07/A12/A13; implement pending items, evidence/string-match checks, actions and refresh/rebuild calls. M2 adds confirmations, rejection, whole-design approval and weight-note constraints. | Chat can propose only; acceptance changes effective values while preserving originals; pending/rejection does not; no approval silently supplies missing information. |
| **A17-evidence-ui / M17** | `frontend/src/chat/Evidence.tsx` | **STRONGER** — shared source/uncertainty interactions need consistency | A02/A04 navigation contracts and declared payloads; implement readable source tags/hover cards and three honest customer review labels; put detailed provenance, corrections, uncertainty explanations and verification warnings in Debug. M3 adds crops. | Widgets expose real source text/targets; raw markers are hidden; uncertainty differs from provenance; review links exist only for actual items. |
| **A18-chat-ui / M18** | `frontend/src/chat/Chat.tsx` | **STRONGER** — complete chat/card/panel interaction | A02/A04/A17 plus frozen A19 part-view props; implement messages, composer/errors, cards/list and shared-panel opening. May implement alongside A19 against frozen props. | Supported answers and abstentions expose the relevant drawing/3D; chat remains visible; missing-key and error states are usable. |
| **A19-part-ui / M19** | `frontend/src/part/PartPage.tsx` | **STRONGER** — one source-backed view reused in several contexts | A02/A17/A21 contracts and payloads; implement clean part shell, 2D zoom/page/highlight, Detail/BOM values, three honest customer statuses and optional Debug. M2 adds history/weight diagnostics inside Debug; M3 adds thumbnails and source-backed panels. | Standalone, Chat and Review reuse the same view; boxes align; unsupported tabs are hidden; original and corrected values remain distinguishable. |
| **A20-parts-ui / M20** | `frontend/src/part/Parts.tsx` | **STRONG** — bounded inventory rendering and filtering | A02/A04 selection callback and record payloads; implement all-parts search/navigation. M2 adds status; M3 adds approved-mapping-aware filters. | Drawing-only and BOM-only parts remain usable; search uses the documented names; failed weight never hides a part. |
| **A21-viewer / M21** | `frontend/src/viewer3d/Viewer3D.tsx` | **STRONGER** — interactive assets, camera and truthful status | A01/A02, sample GLB, effective model metadata; implement orbit/zoom/Fit/A–B and reconstruction/waiting/omission/stale labels. M2 shows weight; M3 adds size/section/STEP actions. | Geometry actually loads; controls change the camera/asset; A is only a viewing default; review/uncertainty labels stay truthful. |
| **A22-review-ui / M22** | `frontend/src/review/Review.tsx` | **STRONGER** — several governed actions sharing evidence views | A02/A17 and A19/A21 view contracts, then real A16 API; implement pending evidence/actions. M2 adds tabs/filters and one-part approval using the same read-only views. | Decisions are possible through Review with evidence, reviewer/time and plain errors; approval blocks/note requirements are clear; ordinary part pages gain no review controls. |
| **A23-checks / M23** | `scripts/check_milestone.py` | **STRONG** — small invocation/reporting wrapper | A01/A02 and the five suite names below; provide early launch smoke and cumulative gate commands, nonzero failure status, semantic-report references, and separate manual/live checklist state. | A failed or missing necessary check cannot be reported passed; commands are real and recorded; the wrapper does not grow into a test framework. |
| **A24-submission / M24** | `README.md` | **STRONGER** — technical claims and observed evidence must match the release | Source brief, actual configuration/build/results and capture paths; draft early, finish separately at each release with genuine observations, key-free `.secrets` setup, Luna chat/Sol–Opus prep disclosure, any Sol-only fallback counts, limitations and notices. | README describes the selected version and models actually used; captures/measurements exist; unavailable observations are identified; no unbuilt feature, unearned verification, or fabricated human approval is claimed. |
| **A25-weight / M25** | `backend/cad/weight.py` | **STRONGER** — controlled numeric rules with sourced material data | Verified M1 software, A13 volumes, effective drawing/BOM materials and approved mappings; implement four-state weight checking and ship the sourced/date-stamped density data artifact. | Correct material/fallback/5%/missing-weight states; no guessed density; model remains viewable; outside-data and material basis are disclosed. |
| **A26-audit / M26** | `backend/app/audit.py` | **STRONGER** — history and accuracy require careful event accounting | Verified M1 journal/record contracts plus M2 fingerprint/review fields; project part/fact history and checked-item counts from retained evidence. | Rejected/superseded/source-changed events remain visible; unchecked items do not inflate accuracy; whole-part confirmations do not double-count fields. |
| **A27-readme / M27** | `backend/loader/readme.py` | **STRONG** — bounded heading/paragraph extraction | Verified M2 software, A02 passage contract, supplied upstream README; extract stable citable paragraphs and flag omitted images/native CAD. | Search/reader open the same text/ID; omitted CAD never becomes an available asset; machine context is kept distinct from the app README. |

## Parallel coding batches

Every row lists the actual launches. A repeated agent is a resumed module owner, not a second concurrent writer. Strengths are repeated so the launch list is directly actionable. Each batch completes with the named outputs plus the roster completion conditions; verification milestones are inserted at their specified positions.

ROOT can start a ready independent assignment as a slot frees rather than wait for an unrelated sibling's external qualification, but must preserve each row's prerequisites, four-worker limit and gate barriers. If work continues during a gate, it uses an isolated worktree and does not change the candidate under review.

### Batch B00 — Setup and early feasibility

**Ready:** Source documents and corpus are available. Use existing CLI authentication; report an actual authentication failure and queue any necessary user action without stopping independent coding or invoking an alternate chat model.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A01-scaffold | STRONGER | Deliver M01's setup bundle. |
| A02-contracts | STRONGEST | Deliver M02's frozen interfaces and explicitly synthetic fixtures. |
| A08-runner | STRONGEST | Qualification slice only: attempt actual non-interactive read-only image/JSON invocation for Sol max/priority and Opus xhigh/regular. Record effective settings and any failure; qualify authorized Sol-only prep if Opus fails. Keep experimental files temporary. |
| A13-cad | STRONGEST | Qualification slice only: verify supported CadQuery GLB export on a simple synthetic solid and record optional STEP feasibility; do not infer any real dimensions. |

**Completion:** A01/A02 make consumer work ready. Record each qualification separately. Failed Opus qualification may proceed through the documented Sol-only prep route; do not block M1 solely on Opus availability or claim dual-reader qualification. Sol/image and CAD/export capability still need genuine qualification for their required paths. Resume full A08/A13 implementations in their later batches. M0 fixtures do not count as real product evidence.

### Batch B01 — Deterministic inputs and runner

**Ready:** A01/A02 interfaces and configuration are available.

**Latest-instruction contract refresh:** A02 first updates prep schemas/fixtures/TS mirror for determine-then-verify, plus summary-tool and debug contracts. A05/A06/A07's deterministic work may continue; A08 starts only after that refreshed contract is integrated. A01 updates qualified CLI configuration/debug launch plumbing in its scoped follow-up. The previous prepared blind-reader A08 assignment is superseded before execution.

**Observed CLI limitation:** Keep requested model/settings pins separate from CLI-reported metadata. A successful source-bound stage may have unreported effective fields; retain unknowns and observed partial fields, reject actual reported conflicts and bind cache identity to its settings basis/contract. Missing metadata alone does not invoke fallback. A08's first implementation launch exposed an overly strict success validator; A02 owns the bounded correction alongside the R17 history contract follow-up, then ROOT resumes A08 once with the accepted boundary.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A05-drawings | STRONGEST | M1 drawing evidence/PNG/field-box extractor. |
| A06-bom | STRONGER | M1 core BOM normalization and recorded connections. |
| A07-decisions | STRONGEST | M1 durable decision journal and overlays. |
| A08-runner | STRONGEST | Full M1 determine-then-verify runner using the refreshed contracts; one correction/reverification retry and truthful unverified fallback. Keep actual qualification separate from scripted behavior. |

**Completion:** Positioned source inputs, normalized rows, the decision API and runner are ready for their consumers; suspicious source values and failed reader checks remain explicit.

### Batch B02 — Shells and enrichment jobs

**Ready:** B01 producers and M02 contracts are available.

A02's history/observability follow-up can start from accepted M02 while A08 settles. A03/A04 consume its accepted history boundary; A09/A10 still wait for the accepted runner. The independent A24 early draft can use the already accepted setup evidence. After M02 history acceptance, A15 may implement its independent JSON history slice while corpus preparation proceeds; the full grounded send loop and its gate remain B06/V2.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A02-contracts | STRONGEST | Freeze R17 list/new/read/continue, server-owned thread ledger and UI/service boundaries; correct truthful CLI metadata success/cache handling without changing the determine/verify policy. |
| A03-server | STRONGER | M0 server/launch/status/fixture endpoints; no paid prep during ordinary launch. |
| A04-shell | STRONGER | M0 sidebar, page shells and navigation contracts. |
| A09-vision | STRONGEST | M1 scan/template jobs using A05/A08 interfaces. |
| A10-matching | STRONGEST | M1 exact/AI link and post-link mapping job definitions using A05/A06/A08. |
| A15-chat | STRONGEST | Optional early R17 local JSON history/list/create/read/context slice after accepted history contracts; full grounded send loop remains B06, and unavailable capability is explicit. |
| A24-submission | STRONGER | Optional early setup/architecture draft from accepted M01 evidence while producer contracts settle; no claims of unfinished chat, prep, UI or gates. |

**Completion:** ROOT runs the basic M0 launch smoke check immediately. It is not a sixth formal checkpoint. A09/A10 job interfaces can be orchestrated and both shells compile against fixtures.

### Batch B03 — Saved knowledge and independent viewer components

**Ready:** B02's job/shell contracts, B01 inputs and M02 fixtures are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A11-preparation | STRONGEST | Execute/publish the staged M1 prep pipeline; preserve all unresolved results and actual qualification failures. |
| A12-records | STRONGEST | Build M1 records against fixed prep fixtures, then consume A11's real saved outputs at handoff. |
| A17-evidence-ui | STRONGER | Shared evidence/uncertainty components against the frozen payloads. |
| A21-viewer | STRONGER | M1 GLB viewer against synthetic fixture assets and model status metadata. |

**Completion:** Run record assembly on published prep outputs when available; it uses the same code as fixture assembly. UI components build without inventing evidence. Runtime publication follows A11 → A12; the agents do not concurrently rewrite generated records/models.

### Batch B04 — Knowledge integration and checkpoint plumbing

**Ready:** B03's record builder and saved data are available; UI components have stable exports. Deterministic fixtures can qualify software while any separately recorded live input remains pending.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A03-server | STRONGER | Wire real record/image reads for V1; chat/review endpoints remain explicitly unavailable until their services exist. |
| A23-checks | STRONG | Initial M23 runner with basic smoke and cumulative V1–V5 command structure; absent suites/checks are pending or failed, never passed. |
| A20-parts-ui | STRONG | M1 all-parts list/search using frozen record/selection props. |
| A24-submission | STRONGER | Update the early setup/architecture/disclosure draft with actual record outputs; reserve observations for actual later runs. |

**Completion:** M01–M12's software outputs integrate, M23 can invoke V1's forthcoming suite, and frontend work remains independently authored. Freeze the V1 candidate.

### Checkpoint V1 — Foundation and knowledge

Launch **T01-knowledge (STRONGEST)** under the verification protocol below. Pass its minimal deterministic suite before integrating the dependent backend. No semantic agent is scheduled here; ordinary owner/ROOT checks continue, and complete product alignment receives one review at V3.

### Batch B05 — Geometry, fact resolution and part/chat views

**Ready:** V1 passed; A17/A21 and frozen part-view props are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A13-cad | STRONGEST | Full M1 builder and attempted real models from effective templates; report essential fields awaiting human input without blocking Review development. |
| A14-tools | STRONGEST | M1 deterministic fact/search tools and frozen proposal callback boundary. |
| A19-part-ui | STRONGER | M1 clean 2D/Detail/shared view, three customer statuses and optional Debug, mounting A21. |
| A18-chat-ui | STRONGER | M1 Chat screen using A17 and the frozen A19 props; implement alongside A19 without editing its file. |

**Completion:** ROOT compiles the combined components once both A18/A19 exports exist. The backend fact and geometry functions satisfy their contracts; real unresolved geometry stays visibly pending until human review.

### Batch B06 — Governed backend and Review

**Ready:** A13/A14's callable contracts and B05's part view are available; M02 already freezes chat/review service signatures.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A15-chat | STRONGEST | Complete the M1 grounded chat response/marker/attachment loop using the retained R17 persistence slice. |
| A16-review | STRONGEST | M1 review items, actions and durable fact/model refresh. |
| A22-review-ui | STRONGER | M1 pending Review inside optional Debug using the shared part view and frozen payloads. |
| A03-server | STRONGER | Wire M1 chat/review/model endpoints and inject M16's proposal callback into the tools boundary. |

**Completion:** A03 validates the real routes after A15/A16 exports land. Review does not import tools/chat/router, and the tool cannot approve its own proposal. Freeze the V2 backend candidate; the complete frontend shell can be connected after V2.

### Checkpoint V2 — Geometry and governed backend

Launch **T02-core (STRONGEST)**. No semantic agent is scheduled here. A deterministic gate can pass with explicitly synthetic complete templates while real essential fields await Jason; the real three-model requirement remains mandatory at V3, where the complete product receives semantic review.

### Batch B07 — Complete the M1 product and submission evidence

**Ready:** V2 passed; all M1 feature components and real backend services are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A04-shell | STRONGER | Connect real M1 Chat/Parts/Review and shared panel/source/review navigation. |
| A23-checks | STRONG | Complete M1's deterministic/semantic/live/manual release checklist and cumulative suite invocation. |
| A24-submission | STRONGER | Finish M1 README and genuine demo observations/captures after the UI is connected; a live-data prerequisite still pending stays pending. |

**Asynchronous human/data handoff:** ROOT queues mapping approvals, essential geometry/link questions, and any genuine correction/release demonstration needing Jason in `USER_TODO.md`. Continue coding and prep immediately. Keep unsupported geometry unknown and mappings unapproved; build every reconstruction supported by available validated evidence. Later user actions reapply decisions and rebuild affected models through A07/A12/A13/A16. Collect available genuine demo evidence; record missing evidence pending rather than substituting test data or agent-authored human approvals.

**Completion:** Freeze the implemented M1 software candidate for V3 with available real outputs, truthful review states, and concrete `USER_TODO.md` entries. Human TODOs and unavailable demonstrations are separately pending and do not delay later implementation.

### Checkpoint V3 — Complete M1 release

Launch **T03-mvp (STRONGEST)** and **S03-assignment (GOD-TIER)** in parallel. ROOT evaluates both software reports and assigns real defects for repair. Queue human-only release checks in `USER_TODO.md` and proceed to B08 once the software checkpoint is satisfied, without waiting for those TODOs or a stable tag. Preserve the M1 candidate. Create `stable-m1` only when the actual release claims are supported; a pending human check is never reported passed.

### Batch B08 — M2 trust primitives and review presentation

**Ready:** The M1 software checkpoint is satisfied (human TODOs may remain); the reserved M2 contract fields and unchanged part-view interfaces are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A07-decisions | STRONGEST | M2 comparison of reviewed-evidence fingerprints and targeted reapproval state. |
| A25-weight | STRONGER | M25 sourced density data, candidate-material rules and four weight states. |
| A26-audit | STRONGER | M26 full part/fact history and checked-item accuracy projections. |
| A22-review-ui | STRONGER | M2 tabs/filters and per-item/whole-part controls against frozen M2 contracts; final actions use the real service after B09/B10. |

**Completion:** Source-change, weight and audit producers are ready. M2 Review controls compile against the same part-view props; nothing is marked human-reviewed by an agent.

### Batch B09 — M2 actions and shared views

**Ready:** B08 producers are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A16-review | STRONGEST | M2 confirm/reject, part approval, unanswered-field blocking and FAILED-note enforcement using actual journal/weight state. |
| A19-part-ui | STRONGER | M2 history/fact-history and weight diagnostics inside Debug. |
| A20-parts-ui | STRONG | M2 three honest customer status labels; engineering review/weight details only in Debug. |
| A21-viewer | STRONGER | M2 per-example weight states inside Debug, retaining usable failed/flagged models in the normal viewer. |

**Completion:** M2 actions and read-only views agree on the same effective state; the ordinary part page remains free of approval controls.

### Batch B10 — M2 integration and evidence

**Ready:** B09 and A22's M2 UI exports are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A03-server | STRONGER | Connect M2 history/accuracy/review endpoints and model-weight payloads. |
| A23-checks | STRONG | Add V4 and M2 live/manual checks while retaining all prior suites. |
| A24-submission | STRONGER | Record actual review coverage, accuracy denominators, weight sources/results and current limitations once the integrated UI is usable. |

**Asynchronous human handoff:** Queue Jason's real-part, link, and scan review in `USER_TODO.md` with the exact evidence and requested action. Continue coding/testing. Record the actual coverage as unreviewed until he acts; synthetic test decisions never count as human approvals.

**Completion:** Freeze the integrated M2 candidate with honest evidence and coverage.

### Checkpoint V4 — M2 review integrity

Launch **T04-trust (STRONGEST)** and **S04-trust (STRONGEST)** in parallel. S04 reviews only the M2 trust/approval delta and its affected behavior; it does not repeat the complete M1 semantic review. ROOT evaluates both software reports and repairs real defects before dependent integration. Queue any human-only M2 evidence in `USER_TODO.md` and continue B11 without waiting for review or a stable tag. Create `stable-m2` only when its actual release claims are supported.

### Batch B11 — M3 source and export additions

**Ready:** The M2 software checkpoint is satisfied; pending human TODOs or a deferred stable tag do not delay M3 coding.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A05-drawings | STRONGEST | M3 supported self-describing callouts and coordinate-based crop generation. |
| A06-bom | STRONGER | M3 remaining cleanup rules and cleanup report. |
| A13-cad | STRONGEST | M3 labeled STEP exports from the same effective templates as GLBs. |
| A27-readme | STRONG | M27 citable upstream README paragraphs with omitted-content caveats. |

**Completion:** Rerun the existing record builder with the updated extraction outputs; preserve decision precedence and unchanged IDs. If a contract change is actually required, ROOT revises it with A02 and the affected owners before consumers continue.

### Batch B12 — M3 fact exposure and viewer presentation

**Ready:** B11 outputs and frozen optional M3 contracts are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A14-tools | STRONGEST | M3 README search, new callout facts and cleanup context using existing deterministic resolution rules. |
| A17-evidence-ui | STRONGER | M3 hover-card source crops. |
| A19-part-ui | STRONGER | M3 thumbnails and provenance/BOM/specs/installed-in panels using existing supported evidence. |
| A21-viewer | STRONGER | M3 overall size, hollow section controls and STEP action; no feature-color/measurement-label expansion. |

**Completion:** Panels and viewer additions render producer data without creating new material/connection/geometry claims. Deferred diagrams/native CAD stay unavailable.

### Batch B13 — M3 navigation and endpoint integration

**Ready:** B12's tools/components are available.

| Launch | Tier | Bounded assignment |
| --- | --- | --- |
| A04-shell | STRONGER | M3 stable routes/history/deep-link reload and highlighted upstream README reader. |
| A20-parts-ui | STRONG | M3 section/material/availability/review filters. |
| A03-server | STRONGER | M3 crop/README/STEP routes and safe API-versus-SPA fallback wiring. |
| A23-checks | STRONG | Add V5 and the M3 release observations to the cumulative runner. |

**Completion:** The integrated frontend builds and uses real M3 endpoints; stable source/review/part links preserve their intended target.

### Batch B14 — M3 submission update

**Ready:** The B13 integrated application is runnable.

Launch **A24-submission (STRONGER)** to finish the M3 README and real screenshots/transcripts describing only shipped features. ROOT collects unresolved release checks and freezes the V5 candidate after this handoff.

### Checkpoint V5 — M3 feature consistency

Launch **T05-polish (STRONGER)**. No semantic agent is scheduled. T05 checks the necessary behavior and re-runs prior suites. A test failure or a complex implementation does not automatically add semantic review; use the exceptional-review rule below only for a concrete unresolved requirements/meaning question.

After the required tests/release observations pass, ROOT stabilizes and creates `stable-m3`.

## Independent verification assignments

The primary test files below are verification deliverables, not additional product modules. Each test validator reads PLAN's gate row and relevant raw requirements before inspecting code. It creates or extends the smallest behavior-focused suite needed for the completed product slice, runs actual local code, and returns reproducible results. All earlier suites are cumulative. Later validators may extend earlier test files under an explicit exclusive ROOT handoff; previous validators are not editing them concurrently.

**Only two semantic reviews are scheduled:** S03 for the complete M1 product and S04 for the M2 trust/approval delta. These are the important points where cross-system assignment fit or new approval meanings justify the cost. V1/V2/V5 use deterministic validators and ordinary owner/ROOT checks. Do not rerun earlier semantic reviewers at each later checkpoint.

Semantic verifiers read the original assignment, included MVP/proposal sections, relevant source evidence and candidate code. They evaluate intended behavior and assignment alignment independently of the test validator's pass/fail conclusion. They do not edit production files or generate human approvals, and they do not expand scope to deferred features. Each performs one review of its assigned scope; follow-ups inspect the fix diff and affected requirements. Repeat a full review only if a changed design actually invalidates the earlier review's basis, with that reason recorded.

| Gate / launch pair | Strength | Concrete assignment and pass condition | Owned output |
| --- | --- | --- | --- |
| **V1: T01-knowledge** | **STRONGEST** | Minimal deterministic foundation/extraction/BOM/record/decision/prep cases from PLAN V1. Use scripted reader subprocesses, real orchestration/record code, inspected small source cases, controlled time/rate limits and isolated journals. Prove Sol determination precedes candidate/source-bound Opus verification, one disagreement-triggered revision/reverification, persistent rejection/unsure handling and stage-aware cache. Include exact bindings, unverified Sol-only counts/provenance, next-launch Opus retry and fake-credential separation. Pass on intended outputs, bounded retries/concurrency and persistence; no live model calls. | `../testing/tests/test_knowledge.py`; `../testing/reports/verification/V1-tests.md` |
| **V2: T02-core** | **STRONGEST** | Minimal deterministic geometry/B3/tool/chat/review cases from PLAN V2, plus V1. Use analytic solids/tolerances and a scripted Responses provider while executing real tools, API transitions, overlays and target rebuilds. Assert Luna-only requests and errors without model fallback. Prove pending/rejection leaves values unchanged and acceptance changes effective values/answers with originals retained. | `../testing/tests/test_core.py`; `../testing/reports/verification/V2-tests.md` |
| **V3: T03-mvp** | **STRONGEST** | Minimal deterministic browser journeys from PLAN V3 using the real local backend and fixed external-provider boundary, plus all backend suites. Verify meaningful interactions/state, the three honest customer statuses, default-hidden/enabled Debug (including review and weight diagnostics), and actual loaded assets rather than pixel snapshots. Check required release paths and separate genuine-data/manual checks from fixture assertions. | `../testing/frontend/mvp.spec.ts`; `../testing/reports/verification/V3-tests.md` |
| **V3: S03-assignment** | **GOD-TIER** | Independently review the whole M1 candidate against all four mandatory assignment behaviors and submission requirements. Follow the real source-to-answer-to-drawing/3D path and a real accepted correction; inspect three reconstructed parts' evidence/labels and actual saved outputs, disclosures and limitations. This is the broadest cross-system review. Assess software behavior against the assignment; report unavailable human-only evidence as a pending USER_TODO, never as verified by fixtures or as a stop on later coding. Genuine implementation defects go to the owner. | `../testing/reports/verification/V3-semantic.md` |
| **V4: T04-trust** | **STRONGEST** | PLAN V4's minimal weight/review/history/accuracy/source-change cases, earlier suites, and necessary extensions to the M1 browser suite. Use controlled data and isolated source changes to check all four weight states, approval blocking/notes, accurate denominators and targeted reopening. | `../testing/tests/test_review_trust.py`, necessary earlier-suite extensions; `../testing/reports/verification/V4-tests.md` |
| **V4: S04-trust** | **STRONGEST** | Review only the M2 delta: what a confirmation/rejection/whole-design approval means, reviewed-evidence hashes, weight/material fallbacks, missing-value handling, and checked-item accuracy. Verify unchanged evidence retains approval and changed evidence never inherits it silently. Reuse the prior M1 semantic conclusions for unchanged behavior. Pass when the new trust claims match the assignment and actual decision evidence. | `../testing/reports/verification/V4-semantic.md` |
| **V5: T05-polish** | **STRONGER** | PLAN V5's necessary parser/crop/README/STEP checks and browser interactions, plus all prior suites. Extend earlier backend suites for the new deterministic data behavior. Check IDs/source coordinates, omitted-asset caveats, filter/deep-link targets, model load/size/section state and labeled loadable exports. | `../testing/frontend/polish.spec.ts`, necessary earlier-suite extensions; `../testing/reports/verification/V5-tests.md` |
| **Exception only: SX-targeted** | **STRONGEST** | Not scheduled at any gate. ROOT must first identify a specific unresolved requirements/meaning question, the affected assignment requirement, and why deterministic assertions and ordinary owner/ROOT review cannot settle it. Review only that question in parallel with the current validator. Implementation size, routine test failures, or another iteration alone are insufficient reasons to launch it. | A short targeted semantic report for the affected gate, only if actually launched |

## Gate protocol and repair ownership

1. **Freeze the candidate.** ROOT records its production-code revision/content identity and active milestone scope. Where a semantic reviewer is scheduled, it inspects the same candidate as the deterministic validator. No module owner edits candidate production files during verification. Independent work uses a separate worktree.
2. **Launch only the scheduled roles.** Every gate launches its deterministic validator. Only V3 and V4 also launch a semantic reviewer in parallel. The validator owns the minimal necessary test suite/report; the semantic verifier is read-only except its independent report. Keep existing test tools simple, inspect raw evidence for expected values, control nondeterministic inputs, and isolate generated data/decisions. No coverage quota, per-helper suite or speculative failure matrix is required.
3. **Return concrete verdicts.** Every report states candidate identity, task/tier, scope, PASS/FAIL/BLOCKED, and the necessary evidence. Tests list exact commands, intended outcomes and actual failures; skipped/unperformed checks remain visible. Semantic reports briefly map relevant assignment/PLAN requirements to code/evidence and list material mismatches with file references. Reports stay short; findings explain impact on the requested product.
4. **Repair through the owner.** ROOT returns an actual defect to its roster owner at that owner's assigned strength. Test-only defects go to the validator. Material design/scope mismatches go through `$plan` and this workflow. Tests/expected answers are not weakened to accommodate incorrect code, and a reviewer does not quietly implement its own preferred product.
5. **Recheck only what needs renewed review.** Re-run the relevant new suite and all earlier deterministic suites after fixes. Reuse semantic conclusions for unchanged code/requirements. When a fix affects a semantic finding or its basis, resume the same logical reviewer for that diff and the affected requirement; do not commission another full review on every iteration. ROOT resolves actual software findings at scheduled semantic checkpoints; a human-only pending observation is queued rather than blocking subsequent coding. A pending human release observation stays visible in `USER_TODO.md` even if deterministic tests pass; it does not block further coding/prep. External tool failures receive their own truthful status and scoped repair.
6. **Resume dependent integration.** ROOT records the gate result and continues the next ready batch. Independent work need not wait for an unrelated failing component, but nothing depends on a failed/unverified output being treated as correct.

## Completion

ROOT confirms every scheduled module slice has its owner handoff, required tests/reviews pass, and actual release evidence satisfies PLAN's expectations. A23 establishes the real suite/build command syntax during implementation and records it in the reports; command names in this document are not a claim that unimplemented scripts already run. The product launch remains `uv run meridian`; the gate runner is `uv run python scripts/check_milestone.py V1` through `V5` once implemented, with prior suites included automatically.

The latest genuinely stable tag is the submission candidate. M1 needs all four mandatory behaviors, the three real drawing/3D pairs, the governed before/after correction, truthful uncertainty/provenance and reproducible local packaging. M2/M3 tags add only their verified increments. Actual credentials, speculative source claims, synthetic human approvals and fixtures presented as real evidence never enter the submission.

This workflow is complete as a planning artifact when the module coverage, tier assignments, dependencies, worker limits, five gates and report ownership are consistent. Execution begins when requested.
