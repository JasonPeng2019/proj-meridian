# Meridian

A locally runnable engineering assistant for the supplied OpenLPBF v2 snapshot. Chat answers from structured drawing and BOM evidence, attaches the relevant drawing and reconstruction, and keeps corrections separate from the original source.

## Launch

Install **uv and Python 3.12**. In PowerShell, from this directory:

```powershell
. .\project-env.ps1
uv run meridian
```

Open **http://127.0.0.1:8000**. `start.bat` and `./start.sh` also launch the app. The frontend, extraction results, AI reader cache, GLBs, and STEP files are included. Normal browsing requires neither Node, CadQuery, nor the prep CLIs. First launch installs the locked Python runtime dependencies; network access is needed for that install.

Chat uses **gpt-6-luna only**. Set `OPENAI_API_KEY` in a local `.env`, or put one key in the ignored `.codex/.secrets/OpenAI_API_Keys.txt`. No key is needed for parts, drawings, 3D, source history, or review. `MERIDIAN_NO_KEY=1` explicitly disables chat for verification. The server binds to localhost.

All project writes must stay under this repository, as required by [AGENTS.md](AGENTS.md). The launch scripts and `project-env.ps1` place temporary files, CLI state, caches and environments here. Do not run development commands before configuring that environment.

## What's in this version

The integrated implementation includes the M1–M3 features in [mvp.md](mvp.md), with focused tests added under the requested nine-hour budget. It contains:

- 30 drawings / 33 pages, all 192 BOM rows, 43 citable upstream README passages, recorded component interfaces, cleanup reports, and stable source IDs.
- Chat with validated source markers, uncertainty tags, cropped evidence on hover, attached parts, and a shared drawing/3D/detail/history side panel.
- Three orbitable reconstructions, D-013, D-025 and D-026, each with A/B thickness possibilities, dimensions, provenance, section clipping, and STEP export.
- Search and material/section/view/review filters, deep links and browser history.
- Separate review queues for corrections, unresolved inputs, AI interpretations, and possible readings; Confirm/Reject, mappings, whole-design approval guards, append-only decisions, and source-change reapproval.

The M1–M3 implementation stabilized as one integrated snapshot. The `stable-m1`, `stable-m2` and `stable-m3` tags identify that same verified release; they do not represent separate historical builds.

**Review state is intentionally incomplete.** Jason approved retaining both printed D-013 thicknesses, 3 mm and 6 mm, as possible readings on 2026-11-05. Neither was selected as correct. That is the only production human decision shipped. The other AI interpretations have not been human-confirmed; measured human-review accuracy is therefore **not yet available**. Eleven name mappings and 23 ambiguous drawing-to-BOM links remain pending. Uncertain hole and slot placements are omitted visibly on all three models. Whole-design approval stays disabled until the remaining inputs are resolved.

## Try these questions

- “What is the Recoater Plate made of? Show its drawing and 3D reconstruction.” Opens D-013 and makes both thickness examples available.
- “Which parts have Aluminium recorded in the BOM? Give a few examples across machine sections.” Uses structured records across the dataset.
- “What supplier and cost are recorded for the timing belt? Can we order it now?” Separates the recorded snapshot from current availability.
- “How thick is D-023, and is the original native CAD available?” Shows uncertainty and abstains where evidence is absent.
- “What is the machine's build volume?” Cites the supplied upstream README.
- “What interfaces are recorded for the recoater carriage?” Returns only relationships actually recorded in the BOM.

For the correction loop, ask about D-019, then explicitly propose changing its placeholder title to your reviewed name. Chat creates a **pending** proposal. Open Review → Corrections, inspect the source and string-match check, then Accept or Reject. Ask the same question again: the current answer uses the accepted overlay and cites the original, replacement, reviewer and date. Detail/History retains both. An isolated automated demonstration is saved with the verification artifacts; it does not count as a human check or alter production D-019.

## How it works

FastAPI serves the prebuilt React/Vite/Tailwind interface and JSON API. The deterministic loader extracts positioned clean-PDF text, renders sheet/corner images, and cleans the spreadsheet without losing original cell values. Blank prices remain unknown; the misleading zero-total rows become unknown totals rather than free parts. Filename/name matches are accepted only when unique. Other links go through the prep readers and remain unresolved unless they agree confidently.

The offline prep runner uses **Claude Opus in regular mode** and **GPT-6.1 Sol, xhigh, priority/Fast service**, with concurrency four and a hard cap of sixteen. It validates referenced evidence IDs, caches by the complete input/settings hash, and retries only sure-versus-sure disagreements by sharing the other reading. The supported non-interactive CLI adapters and their commands are in `backend/ai/runner.py`; no substitute model is selected silently. Every name mapping still requires human approval, even if the readers agree.

At runtime, GPT-6-luna calls narrow tools over the resolved structured records. Python decides source precedence, conflicts, mappings, possible readings and uncertainty. The server validates that each citation exists and was returned by a tool in the current turn. A single unambiguous part match provides a visual fallback when an answer omits a part citation. Only the last ten dialogue turns are retained; fresh facts are fetched after review actions.

CadQuery builds supported flat outlines and features in millimetres, exports STEP in millimetres and GLB in metres. Numeric geometry needs source references or an explicit human decision. Unknown essential dimensions block the body; unknown smaller features are omitted with warnings. Models say **“Reconstruction from 2D drawing. Not the original CAD model.”** Cached exports allow a runtime-only install to restore the shipped geometry. A new geometry input requires the optional CAD dependency to build an uncached version.

Human actions are individual JSON events under `decisions/`, bound to source fingerprints. They overlay immutable extraction, survive regeneration, and reopen for review if dependent evidence changes. Original predictions, proposals, rejections and invalidated approvals remain in history. The app is a single-user local demonstration; it is not a multiuser or manufacturing approval system.

## Verification and observations

Focused checks cover uncertainty, citation provenance, mapping direction, correction replay, changed-source reapproval, no-key operation, link projection, raw/AI separation, CAD units and STEP round trips. Browser checks cover the principal routes, drawing page three, highlighted/cropped evidence, review controls, A/B models, chat side panels, back/forward navigation, and download availability. Saved transcripts and screenshots are in [docs/verification](docs/verification).

**Final results:** 32 tests passed; the production browser sweep had zero JavaScript errors or failed responses. A fresh Git clone ran with no key, Node dependencies, CadQuery, pytest, or prep CLI state. Removing all generated outputs except `ai_cache/` restored extraction, all twelve GLB/STEP assets and Jason's D-013 decision in **18.969 seconds**, without provider calls. All **40/40** pinned asset hashes matched. The isolated correction demonstration proposed through live chat, accepted through the review UI, changed the same question's answer, preserved the raw sheet/title, and produced no browser errors or failed responses. See [release-check.json](docs/verification/release-check.json), [correction-demo.json](docs/verification/correction-demo.json) and [cad-check.json](docs/verification/cad-check.json).

Five representative questions were run twice against the actual GPT-6-luna API: **10/10 behavior checks passed**, median **5.445 seconds**, **81,182 input / 1,780 output tokens**. The checks establish attachments, valid citations, snapshot caveats and abstention behavior; they are not a ground-truth accuracy benchmark. Four of five questions attached the same parts on both runs; the question asking for “a few examples” varied its valid examples. Billing cost is not asserted without account-specific rates. See [live-questions.json](docs/verification/live-questions.json).

The final prep has 45 agreed fields, three agreed after retry, 31 undetermined scan fields, and 27 items sent for input (23 links plus four template fields), with eleven additional mapping approvals. Jason's subsequent D-013 decision resolves one of those four template inputs. There are 96 trusted reader results across 45 jobs; the complete cached replay made **zero provider calls in 2.735 seconds**. The first source-clean run took about **525 seconds**, with parallel reader latency distinct from wall time. Both readers' outputs and settings remain inspectable.

Trusted prep receipts report Claude 124 ordinary input, 216,011 cache-creation input, 207,523 cache-read input and 43,536 output tokens, with **$2.6408086 provider list cost**; this is not a subscription invoice. Codex reports 713,388 input (178,816 cached) and 51,577 output tokens, without a dollar-cost receipt. These exclude preflights, interrupted work and excluded replay experiments, so are not total account billing. The timed source-clean run also included two subsequently discarded section suggestions. Exact scope and settings are in [prep-summary.json](docs/verification/prep-summary.json).

The recorded BOM subtotal is **168,591.52 DKK**, with 75 missing unit prices and 76 unknown row totals (one further row lacks quantity). This is not a complete machine cost or a current quote. Density checks show **FAILED** for D-013 and D-026, and **Passed** for at least one D-025 possibility. These checks never choose a thickness, hide a model, or establish geometric correctness. FAILED design approval requires a note as well as resolved inputs.

## Important errors and limitations

- Conservative matching leaves most drawing links unresolved. In particular, the supplied BOM does not contain an exact “Build Base Ring” row for D-025. Attaching a plausible row automatically would conceal uncertainty.
- The degraded scans retain 31 unreadable/unagreed fields. D-019 has the printed placeholder “Description”; D-026 has overlapping title-block text. These are shown as uncertainty rather than silently repaired.
- All three reconstructions show the supported outer body and both thickness readings, with unknown hole/slot details omitted. Threads are cosmetic; section clipping is hollow rather than a solid cut face. No native CAD is supplied. Do not use these partial reconstructions for fabrication.
- An early replay experiment accidentally fed previously merged AI scan readings back into prep. Fourteen resulting requests were excluded, the raw extraction was rebuilt, and a regression check now asserts that merging cannot alter `drawings.json`. The final audit lists the trusted keys and confirms none of the excluded responses contributes to the final result. The extra experiment incurred provider usage; zero-call cached replay is not a zero-cost initial run.
- An early chat response incorrectly said the images were unavailable despite attaching them. The prompt now explicitly distinguishes the UI's attachments from structured tool payloads. The saved later live questions and browser run verify the corrected behavior.
- Clean-install verification caught Pillow being available only through development dependencies. It is now an explicit runtime dependency; fresh-clone checks assert thumbnail/crop responses and fail on any browser request error.
- No broad answer-key benchmark or completed human accuracy study is claimed. Automated review events in isolated verification are labelled “Automated verification” and excluded from accuracy. System diagrams, supplier discovery, a graph view, additional 3D parts and an MCP server are outside this MVP.

## Development and regeneration

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
