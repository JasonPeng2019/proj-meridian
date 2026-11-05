# Meridian

A locally runnable engineering assistant for the supplied OpenLPBF v2 snapshot. Chat answers from structured drawing and BOM evidence, attaches the relevant drawing and reconstruction, and keeps corrections separate from the original source.

## Launch

Install **uv and Python 3.12**. In PowerShell, from this directory:

```powershell
. .\project-env.ps1
uv run meridian
```

Open **http://127.0.0.1:8000**. `start.bat` and `./start.sh` also launch the app. The frontend, extraction results, AI reader cache, GLBs, and STEP files are included. Normal browsing requires neither Node, CadQuery, nor the prep CLIs. First launch installs the locked Python runtime dependencies; network access is needed for that install.

For engineering review, launch `uv run meridian --debug-ui` and open **http://127.0.0.1:8000/review/parts**. Search by English name, drawing ID or section, then select a part. Evidence, Model & checks, and History have their own scrollable pane. **Review items** filters the review queues and their counts to that part; **Clear part scope** returns to all items in that category. **Full queue** always shows outstanding items across all parts, even when opened from a selected part; the header also shows the global outstanding count. **Needs human review** contains proposed AI answers awaiting oversight. **Needs human input** contains unresolved values, ambiguous readings or links, incomplete geometry, and failed checks requiring intervention. These queues are separate; neither is a human approval. Each review item offers **Open source material** links: drawing citations open a zoomable original sheet centered on the cited region, parts-list citations show the complete original row beside cleaned values, and README citations show the original passage. Close the inspector to return to the same review. Original PDFs are downloadable; density references are labelled as outside sources. **Review whole design** opens the drawing/model with the guarded approval controls. Debug stays hidden on normal launches; `--hide-debug` explicitly hides it.

The frontend normally builds on Actions and the coordinator downloads its verified static bundle for local use; Node is unnecessary for serving it. If a local fallback build is needed, `scripts/local_build.ps1` queues behind other local builds, waits for at least 3 GB free RAM and CPU load at or below 70% across two samples, then caps Node heap at 1.5 GB and esbuild Go workers at two. These are conservative bounds rather than a guarantee. Normal app startup uses existing records/models instead of rerendering sheets on every launch.

The live server reloads the repository records and append-only decisions when their file signatures change. Visible app tabs check the revision every ten seconds and refresh the selected part/review queue. Delegated decisions show **Jason Peng - delegated review** in Debug history and retain the actual inspecting actor. [Delegated review audit](docs/verification/delegated-review-2026-11-05/README.md).

Chat uses **gpt-6-luna only**. Set `OPENAI_API_KEY` in a local `.env`, or put one key in the ignored `.codex/.secrets/OpenAI_API_Keys.txt`. No key is needed for parts, drawings, 3D, source history, or review. `MERIDIAN_NO_KEY=1` explicitly disables chat for verification. The server binds to localhost.

All project writes must stay under this repository, as required by [AGENTS.md](AGENTS.md). The launch scripts and `project-env.ps1` place temporary files, CLI state, caches and environments here. Do not run development commands before configuring that environment.

## What's in this version

The integrated implementation includes the M1–M3 features in [mvp.md](mvp.md), with focused tests added under the requested nine-hour budget. It contains:

- 30 drawings / 33 pages, all 192 BOM rows, 43 citable upstream README passages, recorded component interfaces, cleanup reports, and stable source IDs.
- Chat with source links, uncertainty tags, cropped evidence on hover, attached parts, and a shared drawing/3D/detail side panel, optional engineering Debug, and saved past chats.
- Nine orbitable reconstructions with twelve variants: D-012, D-013, D-014, D-015, D-017, D-019, D-025, D-026 and D-027. The original three retain both thickness possibilities. All have section clipping and STEP export; [the model scope](docs/verification/model-scope.md) distinguishes retained cuts from body-only partials.
- Search and material/section/view/review filters, deep links and browser history.
- Separate review queues for corrections, unresolved inputs, AI interpretations, and possible readings; Confirm/Reject, mappings, whole-design approval guards, append-only decisions, and source-change reapproval.

The M1–M3 implementation stabilized as one integrated snapshot. The `stable-m1`, `stable-m2` and `stable-m3` tags identify that same verified release; they do not represent separate historical builds.

**Review state is intentionally incomplete.** The production decision log contains Jason's actual review actions: retaining D-013's printed 3 mm and 6 mm as possible readings (neither selected as correct), and accepting the recorded 5005-to-Aluminium material mapping through the UI. Other AI interpretations, mappings and ambiguous links still need review. No automated run is counted as Jason's review. Detailed check failures, omissions and engineering review state are in Debug; the customer view uses a simple review/availability status.

## Try these questions

- “What is the Recoater Plate made of? Show its drawing and 3D reconstruction.” Opens D-013 and makes both thickness examples available.
- “Which parts have Aluminium recorded in the BOM? Give a few examples across machine sections.” Uses structured records across the dataset.
- “What supplier and cost are recorded for the timing belt? Can we order it now?” Separates the recorded snapshot from current availability.
- “How thick is D-023, and is the original native CAD available?” Shows uncertainty and abstains where evidence is absent.
- “What is the machine's build volume?” Cites the supplied upstream README.
- “What interfaces are recorded for the recoater carriage?” Returns only relationships actually recorded in the BOM.

For the correction loop, ask about D-019, then explicitly propose changing its placeholder title to your reviewed name. Chat creates a **pending** proposal. Launch with `--debug-ui`, open Debug → Corrections, inspect the source and string-match check, then Accept or Reject. Ask again: the answer uses the accepted overlay; Debug retains the original, replacement, actual reviewer and date. The isolated automated demonstration does not count as a human check or alter production D-019.

## How it works

FastAPI serves the prebuilt React/Vite/Tailwind interface and JSON API. The deterministic loader extracts positioned clean-PDF text, renders sheet/corner images, and cleans the spreadsheet without losing original cell values. Blank prices remain unknown; the misleading zero-total rows become unknown totals rather than free parts. Filename/name matches are accepted only when unique. Other links go through the prep readers and remain unresolved unless an evidence-grounded proposal is verified.

The offline prep runner uses **Claude Opus in regular mode** and **GPT-6.1 Sol, xhigh, priority/Fast service**, with a hard cap of four concurrent CLI readers. Coding agents are excluded from that reader limit. Sol now proposes a reading and Opus verifies that exact proposal against the source evidence. The verifier accepts, rejects or requests input for each field; repairable feedback gets one bounded retry. Referenced evidence IDs, proposal fingerprints and numeric grounding are validated locally. Complete input/settings hashes address the cache. Existing independent-reader receipts remain labelled as legacy results. The supported non-interactive CLI adapters and their commands are in `backend/ai/runner.py`; no substitute model is selected silently. Every name mapping still requires human approval, even when the proposal is verified.

At runtime, GPT-6-luna calls narrow tools over the resolved structured records. Python decides source precedence, conflicts, mappings, possible readings and uncertainty. Luna's final answer is returned directly without an output validator or repair retry. Known references are connected to evidence panels and attachments; missing references do not suppress or rewrite the answer. A single unambiguous part match provides a visual fallback when an answer omits a part citation. Saved chats retain up to 200 messages locally; only the last ten dialogue turns enter the model context, with fresh facts fetched after review actions.

CadQuery builds supported flat outlines and features in millimetres, exports STEP in millimetres and GLB in metres. Numeric geometry needs source references or an explicit human decision. Unknown essential dimensions block the body; omitted smaller features remain documented in Debug. Models say **“Reconstruction from 2D drawing. Not the original CAD model.”** Cached exports allow a runtime-only install to restore the shipped geometry. A new geometry input is generated and checked on Actions; interactive local reviews restore matching caches or mark the model unavailable until those exports arrive.

Human actions are individual JSON events under `decisions/`, bound to source fingerprints. They overlay immutable extraction, survive regeneration, and reopen for review if dependent evidence changes. Original predictions, proposals, rejections and invalidated approvals remain in history. The app is a single-user local demonstration; it is not a multiuser or manufacturing approval system.

Open **Past chats** from Chat to reopen or delete a saved conversation; **New chat** starts a separate one. Conversations survive refresh and server restart, are stored only in ignored `.runtime/chats/`, and retain up to 100 exchanges within an 8 MB limit. Each new answer retrieves current evidence. Conversations from before this feature was installed cannot be recovered.

## Verification and observations

The canonical question set is [docs/Question-benchmark/benchmark_draft.md](docs/Question-benchmark/benchmark_draft.md); see [its execution plan](docs/Question-benchmark/PLAN.md). It contains 20 numbered questions and 21 before/after execution cases. The final run captured all 42 answers across two passes. Expected answers remain a draft for Jason to check; automated scores and human review are separate. The five-question measurements below are historical smoke checks.

**Final benchmark:** [run 42020759881](docs/benchmark/run-42020759881/README.md) has **31/42 strict rule passes**, **27/42 meaning scores of 2**, and **22/42 combined passes**, with two combined results pending prerequisites. All 42 responses and independent judgments are saved. Genuine issues include contradictory counts and unsupported extra claims; some failures concern new verified dimensions or the frozen draft's presentation requirements. Rules and scores were not relaxed. Chat measured 958,236 tokens, plus 71,592 for isolated correction setup; monetary chat cost is unknown. Human judge spot-checks remain **0**. This is an automated prototype evaluation, not a completed human accuracy study.

Focused checks cover uncertainty, citation provenance, mapping direction, correction replay, changed-source reapproval, no-key operation, link projection, raw/AI separation, CAD units and STEP round trips. Browser checks cover the principal routes, drawing page three, highlighted/cropped evidence, review controls, A/B models, chat side panels, back/forward navigation, and download availability. Saved transcripts and screenshots are in [docs/verification](docs/verification).

**Final integration checkpoint:** [Actions 42020759881](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42020759881) passed all **194 tests**, independent STEP/GLB checks at **1,380 geometric points**, all **nine parts / twelve variants**, fresh-clone startup and offline regeneration in **9.924 seconds**. Every variant rendered; customer and Debug browser sweeps had zero errors or failed responses. Saved-chat reopen, refresh, new-chat and targeted deletion passed. The live isolated correction workflow passed, with all 40 pinned assets and production decisions unchanged. [Reports and screenshots](docs/verification/run-42020759881/checkpoint.json) include the new countersunk plate, two-sided clamping ring and Past chats drawer. Earlier checks caught missing slot orientation, degree-symbol encoding and coincident bore counting before the final pack shipped.

**Initial release checkpoint (before the later UI, benchmark and prep updates):** 32 tests passed; the production browser sweep had zero JavaScript errors or failed responses. A fresh Git clone ran with no key, Node dependencies, CadQuery, pytest, or prep CLI state. Removing all generated outputs except `ai_cache/` restored extraction, all twelve GLB/STEP assets and Jason's D-013 decision in **18.969 seconds**, without provider calls. All **40/40** pinned asset hashes matched. The isolated correction demonstration proposed through live chat, accepted through the review UI, changed the same question's answer, preserved the raw sheet/title, and produced no browser errors or failed responses. See [release-check.json](docs/verification/release-check.json), [correction-demo.json](docs/verification/correction-demo.json) and [cad-check.json](docs/verification/cad-check.json).

Five representative questions were run twice against the actual GPT-6-luna API: **10/10 behavior checks passed**, median **5.445 seconds**, **81,182 input / 1,780 output tokens**. The checks establish attachments, valid citations, snapshot caveats and abstention behavior; they are not a ground-truth accuracy benchmark. Four of five questions attached the same parts on both runs; the question asking for “a few examples” varied its valid examples. Billing cost is not asserted without account-specific rates. See [live-questions.json](docs/verification/live-questions.json).

The current proposer–verifier prep completed 45 jobs with 98 reader receipts (97 provider calls and one cache hit), leaving 20 scan fields undetermined. Refinement restored the original three cut patterns; one bounded D-013 feedback repair supplied structured slot directions. Expansion then assessed the remaining 27 drawings, reusing eleven fingerprinted blocked assessments and making 36 fresh sequential calls with two bounded feedback rounds in 45.8 minutes. Its [58-receipt final lineage](generated/ai_cache/model_expansion/receipt-index-20261105T104806207369Z.json) records six new eligible parts and 21 blocked parts. These are verified AI readings, not human design approvals.

Two actual human decisions are preserved: D-013's 3/6 mm alternatives, with neither selected, and the accepted 5005/Aluminium mapping. There are no whole-design approvals or completed confirm/reject accuracy samples; human review accuracy remains unmeasured. Benchmark judge spot-checks by a human remain zero.

The initial independent-reader prep had 45 agreed fields, three agreed after retry, 31 undetermined scan fields, and 27 items sent for input (23 links plus four template fields), with eleven additional mapping approvals. Jason's subsequent D-013 decision resolves one of those four template inputs. There are 96 trusted reader results across 45 jobs; the complete cached replay made **zero provider calls in 2.735 seconds**. The first source-clean run took about **525 seconds**, with parallel reader latency distinct from wall time. These historical independent-reader observations are separate from the current proposer–verifier results.

Trusted prep receipts report Claude 124 ordinary input, 216,011 cache-creation input, 207,523 cache-read input and 43,536 output tokens, with **$2.6408086 provider list cost**; this is not a subscription invoice. Codex reports 713,388 input (178,816 cached) and 51,577 output tokens, without a dollar-cost receipt. These exclude preflights, interrupted work and excluded replay experiments, so are not total account billing. The timed source-clean run also included two subsequently discarded section suggestions. Exact scope and settings are in [prep-summary.json](docs/verification/prep-summary.json).

The recorded BOM subtotal is **168,591.52 DKK**, with 75 missing unit prices and 76 unknown row totals (one further row lacks quantity). This is not a complete machine cost or a current quote. Density checks show **FAILED** for D-013 and D-026, and **Passed** for at least one D-025 possibility. These checks never choose a thickness, hide a model, or establish geometric correctness. FAILED design approval requires a note as well as resolved inputs.

## Important errors and limitations

- Conservative matching leaves most drawing links unresolved. In particular, the supplied BOM does not contain an exact “Build Base Ring” row for D-025. Attaching a plausible row automatically would conceal uncertainty.
- The latest prep leaves 20 scan fields undetermined. D-019 has the printed placeholder “Description”; D-026 has overlapping title-block text. These are shown as uncertainty rather than silently repaired.
- The original three reconstructions now retain the supported hole/slot patterns. D-026 keeps all three primary through holes; its 15 mm possibility omits the printed 15.4 mm counterbore step because it cannot fit, while the 25 mm possibility retains it. Undimensioned corner/edge finishing remains omitted. Threads are cosmetic; section clipping is hollow rather than a solid cut face. No native CAD is supplied. These partial AI reconstructions are not manufacturing models.
- An early replay experiment accidentally fed previously merged AI scan readings back into prep. Fourteen resulting requests were excluded, the raw extraction was rebuilt, and a regression check now asserts that merging cannot alter `drawings.json`. The final audit lists the trusted keys and confirms none of the excluded responses contributes to the final result. The extra experiment incurred provider usage; zero-call cached replay is not a zero-cost initial run.
- An early chat response incorrectly said the images were unavailable despite attaching them. The prompt now explicitly distinguishes the UI's attachments from structured tool payloads. The saved later live questions and browser run verify the corrected behavior.
- Clean-install verification caught Pillow being available only through development dependencies. It is now an explicit runtime dependency; fresh-clone checks assert thumbnail/crop responses and fail on any browser request error.
- No completed human accuracy study is claimed. Automated review events in isolated verification are labelled “Automated verification” and excluded from human accuracy. All 30 drawings were assessed: nine have supported partial reconstructions and 21 require unsupported essential geometry or missing dimensions. D-015 and D-019 retain their bodies only; D-012 and D-017 omit functional mounting features. D-014 and D-027 retain their dimensioned functional cuts. See [the full scope](docs/verification/model-scope.md). System diagrams, supplier discovery, a graph view, custom/round-part templates and an MCP server remain outside this MVP.

## Development and regeneration

See [the build plan](docs/build-plan.md). Lightweight [push checks](https://github.com/JasonPeng2019/proj-meridian/actions/workflows/check.yml) cancel superseded runs and build a downloadable frontend. At integration checkpoints, the coordinator dispatches [heavy verification](https://github.com/JasonPeng2019/proj-meridian/actions/workflows/verify.yml): full tests → real CAD generation/roundtrips → fresh runtime/cache regeneration → browser verification, in succession on one hosted Linux runner. Numerical/CAD threads are limited to one. Heavy runs share the `meridian-heavy` queue. Neither workflow launches coding or dataset-prep CLIs.

Push/PR checks require no API credentials. The coordinator triggers integration and paid runs itself; “manual” never means Jason must click, run or confirm. `benchmark=true` selects the two canonical passes; `live_api=true` selects the isolated correction UI check. They use the repository's `OPENAI_API_KEY` Actions secret, with sequential local API fallback if secrets cannot be used. CLI meaning judging stays local and sequential through `scripts/judge_benchmark.py`, with hooks disabled and an ignored cache. Downloadable reports, screenshots, models and frontend artifacts are retained for seven days. `python -m scripts.frontend_artifact fetch --run RUN_ID` installs a matching successful frontend artifact after verifying source and file hashes, without starting Node locally. Hosted project files remain under `GITHUB_WORKSPACE`; the Windows write boundary still applies locally.

The commands below are for the hosted runner or an unavoidable sequential local diagnostic; do not run the full sequence locally alongside agents.

```powershell
. .\project-env.ps1
uv sync --extra dev --extra cad
npm --prefix frontend ci
npm --prefix frontend run build
uv run pytest
uv run meridian rebuild
```

`rebuild` regenerates extraction and replays decisions without new AI requests. Keep `generated/ai_cache/` to restore the shipped prep artifact and model exports after removing the other generated outputs. Do not delete `decisions/`. `uv run meridian models` rebuilds/restores geometry only.

To run a new prep pass, install and authenticate the Claude and Codex CLIs, using process-local state directories inside this repo, then run `uv run meridian prep`. This sends drawing corner images, drawing measurements and selected BOM evidence to the configured providers. Normal chat sends questions and returned structured facts to OpenAI; it does not upload all PDFs. Keys/authentication state stay ignored and must be supplied locally. Changing a model, prompt, schema or source invalidates the relevant cache.

Browser checks require the dev extra and a local Playwright Chromium install (`uv run playwright install chromium` after `project-env.ps1`). Run `uv run python scripts/verify_browser.py` against the running app. `scripts/verify_live.py` makes ten paid chat requests. The release verification script uses only isolated directories under `.verification/`.

## Models, external data, and attribution

Application chat: GPT-6-luna, low reasoning, default service tier. Dataset prep: Claude Opus regular mode and GPT-6.1 Sol xhigh on priority/Fast. Coding assistance used GPT-6.1 Sol high/Fast subagents. Runtime dependencies and exact versions are locked in `uv.lock` and `frontend/package-lock.json`.

The pinned source corpus, original notices and license remain unchanged in [project-meridian_Avathon/project-meridian](project-meridian_Avathon/project-meridian). Preserve [ATTRIBUTION.md](project-meridian_Avathon/project-meridian/ATTRIBUTION.md) and its included CERN-OHL-P-2.0 license when redistributing. The original machine README is citable evidence, separate from this application README. Derived extraction, images and reconstructions were created **2026-11-05** from the supplied sheets; they are not upstream vendor CAD.

The density table is outside-source reference data, labelled as such in the UI, with URLs and lookup date 2026-11-05 in [densities.json](backend/cad/densities.json): ASM aluminum data archived by NIST, Outokumpu stainless data, and SSAB steel data. Approximate family densities are disclosed. Recorded suppliers and prices were not refreshed from the web and are not endorsements.

The customer view hides engineering internals by default. Launch `uv run meridian --debug-ui` to show the part Debug tab (evidence, model calculations and history), or `--hide-debug` to explicitly hide it. `MERIDIAN_DEBUG_UI=1` is the equivalent process environment setting. Display translations preserve original source wording and do not approve material mappings.
