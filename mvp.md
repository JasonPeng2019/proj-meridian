# Project Meridian: MVP Build Spec

## Current execution updates (2026-11-05)

These user-requested updates supersede the historical timing/testing rules below:

- The deadline is nine hours. Follow [docs/build-plan.md](docs/build-plan.md): lightweight push checks cancel superseded runs; the coordinator dispatches queued heavy/API integration runs itself. Build the frontend remotely and download a source/hash-verified bundle for local use. Needed local fallback builds hold the resource lock and wait for headroom. Dataset-prep CLI readers remain local with a hard cap of four; coding agents are excluded from that reader cap, with an overall conservative budget of four project CLI workers.
- The latest prep workflow is Sol proposal → Opus verification of that exact proposal → one bounded feedback retry. Keep legacy independent-reader receipts separate. Assess every additional drawing for supported, source-grounded CAD; unknown essential geometry blocks generation, while minor uncertain features may be omitted visibly.
- Customer views use concise standard Detail sections and English display translations. Engineering records, model calculations, hashes, provider receipts and history live in an optional Debug tab, hidden by default and enabled with `--debug-ui`. Source evidence and essential uncertainty remain accessible.
- Focused automated verification is required. Preserve the original evidence and never manufacture Jason's reviews.
- Save local past chats with reopen, refresh/restart persistence, new-chat and targeted deletion. Keep the history drawer closed by default; a reopened conversation retrieves fresh evidence for each new answer.
- The current question/benchmark source is [docs/Question-benchmark/benchmark_draft.md](docs/Question-benchmark/benchmark_draft.md). It replaces the five representative demo questions as the planned evaluation set. There are 20 numbered questions and 21 execution cases because Q11 has before/after variants. Its expected answers remain a draft for Jason to check.
- Follow [the updated benchmark run plan](docs/Question-benchmark/PLAN.md): use these exact question texts, add the missing aggregate tools, evaluate twice, and report rule checks, independent judge scores, combined results, timing, tokens and repeatability separately. Benchmarks must not feed expected answers into chat, extraction or dataset prep.
- The existing five-question observations are historical smoke checks, not results for the new benchmark. Do not label them as the new benchmark's score.

**Time budget:** nine hours. **Approach:** build in **stacked milestones**. Each milestone is a complete, working, **submittable** version, tagged in git as `stable-m1`, `stable-m2`, and so on. Preserve these historical tags and verify the final integrated `v1` state before submission.

**This file is the border.** Build only what's in the milestones below. When this file and `proposal.md` disagree, **this file wins** for the build. `proposal.md` is the reference for how anything included here should behave.

---

## How to use this file

1. **Milestones are built in order.** M1 is the smallest version that meets the assignment, fully AI-filled. Each later milestone adds to the one before it and never breaks it.
2. **Each milestone ends with "stabilize and tag"** (the procedure is below). Nothing from the next milestone is merged until the current one is tagged.
3. **Agents can work ahead.** An agent with nothing to do for the current milestone can start the next one **on a separate branch**, against the contracts. It just doesn't merge until the current tag exists.
4. **Submitting at any time:** `git checkout stable-mN`, run `uv run meridian` once to confirm it starts, and submit. Each tag's README already describes exactly what that version does.

---

## The non-negotiables

These hold in **every** milestone, including M1. They're the product's honesty. If an agent is short on time, these come first.

1. **Never show a guessed value.** Anything uncertain is shown as Undetermined.
2. **Every claim cites a real source** that the tools actually returned. Citations are never made up.
3. **Labels tell the truth** about where a value came from: rule-based ("From PDF," "From parts list"), AI ("AI interpretation, not reviewed"), or human ("Entered by Jason Peng" for a value Jason set while checking).
4. **Original values are never edited or lost.** Corrections and decisions are stored separately and applied on top.
5. **3D models always say** "Reconstruction from 2D drawing. Not the original CAD model."
6. **API keys are never committed.**

---

## What we're deliberately not doing

This is the boundary for coding practices and edge cases. Agents should **not** spend time on any of these.

**Coding practices skipped:**

- **Focused verification:** use unit checks for evidence, decisions and geometry contracts; queued remote integration, CAD and browser checks cover release behavior. Do not add a broad linting/formatting framework or duplicate checks without a concrete risk.
- **No abstractions for the future:** no plugin systems, interfaces, or "in case we need it" layers. Duplicated code is fine.
- **No refactoring** of working code. If it works, leave it.
- **No logging framework.** `print` is fine.
- **Concise documentation:** README, current build/benchmark plans and saved verification receipts; avoid unrelated documentation.
- **No data migrations or versioned formats.** If a format changes, regenerate.
- **No performance work.** Load everything into memory.
- **No database.** Part records are one `generated/records.json` file loaded into memory, instead of the SQLite database in `proposal.md`.

**Product concerns skipped (single local user):**

- **No login, accounts, permissions, or multiple users.** The reviewer is always Jason Peng, from the settings file.
- **No hand-filled production answers.** The supplied benchmark draft is isolated from chat/prep. Report automated benchmark results and actual human reviews separately.
- **No security hardening.** It runs locally.
- **Desktop browser only.** English display translations retain immutable original wording; broader localization and mobile work are outside scope.
- **One chat model: `gpt-6-luna` only.**

**Edge cases ignored:**

- **Data outside this dataset:** other drawing layouts, other spreadsheets, other units. Hardcoding for these 30 drawings and this one spreadsheet is fine.
- **Malformed input** beyond what the demo uses. If a source file is odd, the loader can fail loudly.
- **Malformed AI output:** never treat an invalid response as verified. Permit only the protocol's one bounded feedback retry; unresolved results remain undetermined.
- **Network and API failures:** show a plain error message. The only automatic retry is the runner waiting out rate limits.
- **Long chats:** only the last 10 turns are sent to the model.
- **Simultaneous edits:** there's only one user.

**Error handling, in general:** the setup loader stops with a clear message, and the UI shows a plain error. Nothing more.

---

## Milestones

### M0: Skeleton (about hour 0–1, not submittable)

**Goal:** everyone can start working in parallel.

- `uv` project (`pyproject.toml`, `uv.lock`), `uv run meridian`, `start.sh`, `start.bat`, `.env.example`, `ai_settings.yaml`.
- A FastAPI stub serving every endpoint in the contracts, using **fixture data**.
- A React + Vite + Tailwind + shadcn/ui scaffold with the left sidebar (Chat, Parts, Review) and empty pages.
- **Fixtures:** 2 sample part records (D-013, D-025), 1 sample template, 1 sample GLB, and 1 sample chat API response.
- Contracts (below) written and **frozen**.

**W2 starts the runner right away** (it's on M1's critical path), testing early that both CLIs accept an image and return JSON in non-interactive mode.

**Jason, in parallel:** log into Claude Code and Codex, and put a chat API key in `.env`. That's all. Everything else is filled by AI, and Jason only checks it.

---

### M1: Minimum submittable version (target: tagged by about hour 6)

**Goal:** meets every assignment requirement using source extraction and the proposer–verifier pipeline. Human approvals remain separate, explicit review actions. This is the floor you can always submit.

**The runner (W2), built first:**
- runs Sol xhigh priority/Fast from `ai_settings.yaml` to propose, then Opus regular verifies that exact proposal and fingerprint against original evidence; validates source IDs and caches receipts by input/settings hash;
- runs prep **serially**, behind the RAM/CPU resource gate; four readers is a hard ceiling, not a target, and the conservative overall CLI-worker budget also applies;
- runs in **stages**: (1) scans and templates, (2) matching using scan titles, (3) name mappings using links; each job permits one bounded feedback retry before unresolved fields go to review;
- invalid or unsupported responses never become verified values; retain earlier independent-reader receipts with their original protocol labels.

**AI prep jobs (W2), all through the runner:**
- **Scans (A2):** corner boxes. Verified fields use `ai_verified` or `ai_verified_after_retry`; the rest are Undetermined. Citations highlight the whole field box. Legacy `ai_read` receipts remain labelled as legacy.
- **Matching (A4):** exact matching first (datasheet filename, then normalized names, exactly one match), then the runner. Verified links use `ai_verified` or `ai_verified_after_retry`; legacy `ai_agreed` receipts retain their original labels. Anything unresolved becomes a review item.
- **Name mappings (A10):** the runner suggests a relationship (`same`, `kind_of`, `different`, `no_equivalent`) for each of the roughly 15 section and material pairs. **Every mapping needs Jason's approval** before it's used. Until then, differing names show as Undetermined ("These names haven't been mapped yet").
- **Templates (B5):** retain D-013, D-025 and D-026 and assess every remaining drawing within the flat subset: rectangle/circle/ring outlines, thickness options, plain/threaded/countersunk/counterbored holes, slots and row/circle patterns. Keep supported cuts, distinguish dimensioned from interpreted pattern placement, and record omissions separately. Unknown essential geometry blocks generation; do not substitute bounding boxes for unsupported outlines.

**Setup loader (W1):**
- **Clean drawings (A1):** text with positions, PNG per page, corner box read by finding labels.
- **Parts list cleanup (A3), core:** load as text, trim, blanks become `null`, parse prices, the zero-total trap, split comma lists, snapshot notes. Originals kept.
- **Connections (A5)**, **part records (A6)** in `generated/records.json`, and **method labels (A8)**.
- **Decisions (A9):** saved in `decisions/` and applied on every rebuild. The AI never overwrites one.
- Merges in the AI results: scan readings, links, approved name mappings, and templates.

**3D (W3):**
- CadQuery builds **one GLB per example** (A and B) from each filled-in template, in neutral grey. Built files are committed.
- Unknown essential geometry makes 3D unavailable; the detailed missing fields appear in Debug. Verified partial geometry may be built with explicit omission receipts.
- Actions generates and probes STEP/GLB assets sequentially. Local review actions restore matching caches or mark models stale/unavailable; they never launch CadQuery locally.

**Backend (W4):**
- `tools.py` with `find_part`, `get_facts` (display values resolved in code using B3 rules 0–5), `get_connections`, `parts_in_section`, `parts_with_material`, and `propose_correction`.
- The chat loop (one provider, tool calling, marker rules in the system prompt).
- The marker parser (`[cite:]` and `[undetermined:]`, with the existence and "returned this conversation" checks), cards for 1–3 parts, a list for 4 or more, the single-match backup rule, and the uncited warning.
- Ordinary chat stays concise. Customer status uses Human reviewed / AI reviewed / Unavailable; review requirements and engineering diagnostics live in Debug. Explicit questions about checks receive the requested evidence and limitations.
- **The review API:**
  - **items:** corrections, unresolved links/template fields, and name mappings waiting for actual approval;
  - **actions:** accept, reject, set a value, choose an option, and approve a mapping;
  - each action writes a decision and re-applies decisions;
  - the correction check is a simple string match against the drawing text and the linked row.
- With no API key, `/api/status` says chat isn't available.

**Frontend (W5, W6, plus W3 for the 3D tab and W4 for the review page):**
- **Chat:** messages, citation tags with a hover card (source, what it says, badge), the Undetermined tag with its message, part cards with a thumbnail, and the side panel.
- **Part page** (also used in the side panel): 2D drawing/highlights, available 3D reconstructions with Fit/section/A–B controls, and concise Detail sections (Overview, Dimensions, one Notes section, Supply & cost). Optional Debug holds full evidence, corrections, decisions, provider receipts and calculations.
- **Parts list:** every part, with search.
- **Review page:** engineering workspace exposed with Debug; each item has source evidence, the exact proposal/verifier response and its actions.
- With no key, the chat says "Add an API key to use the chat."

**Write-up:** README with the delivered scope, saved transcripts/screenshots, prep verification/retry/unresolved counts, and the canonical two-pass benchmark's rules, independent judgments, tokens, timing and stability. Keep historical five-question observations labelled as smoke checks. Report actual human reviews separately.

**Human review, when available:** Jason can approve mappings and resolve template/link fields in Debug. The coordinator never authors these approvals or treats workflow dispatch as human review.

**M1 is stable when:**
1. `uv run meridian` starts on a fresh clone.
2. A full AI prep run finishes in a few minutes and writes its results.
3. "What is the recoater plate made of?" gives a cited answer with the right badge, a part card, and the side panel with the highlighted drawing.
4. The 3D tab for D-013, D-025, and D-026 spins, switches between A and B, and shows the reconstruction label.
5. A question about an unreadable scan field shows the Undetermined tag with its message.
6. The D-019 correction: propose in chat → it appears on the Review page with the check result → Accept → asking again gives the corrected answer, with "originally" and the decision listed on the Detail tab.
7. Answering a template field on the Review page rebuilds that part's model.
8. Deleting `generated/` (except `ai_cache/`) and restarting rebuilds everything, and every decision is still applied.
9. With no API key, the chat shows its message and everything else works.
10. The README matches what this version actually does.

---

### M2: Review and trust (target: tagged by about hour 8)

**Goal:** Jason's hand checks become part of the product, and the accuracy number comes from them.

- **Confirm and Reject for every AI item** (A8, B6): links, template fields, scan readings, and whole parts. Customer status stays compact; Debug preserves the actual reviewer's name, date and action.
- **Human review accuracy:** confirmed/rejected counts only for the AI items Jason actually checked, broken down by job. Report the separate automated benchmark without treating it as human review.
- **Approve whole design** (B6): a part review page that reuses the part page's views, one part at a time, disabled while any field waits for a value.
- **Weight check** (B5): Passed, Flagged, FAILED or Skipped, using a sourced density table. Detailed results and approval requirements live in Debug and never hide the supported model. Approving a FAILED part requires an actual reviewer note.
- **Review tabs and filters** (B6): Corrections, Needs human input, AI interpretations, and Possible readings.
- **History in Debug** (B5), including a single fact's history; customer source access stays concise.
- **Fingerprints and changed evidence** (A9 rule 4), and a **rebuild test** script.

**Jason:** confirm or reject every AI item on the 3 parts, plus the links and scan readings (all of them if time allows, otherwise a sample, and the README says which), and use Approve whole design on the 3 parts.

**M2 is stable when:** every M1 check still passes, plus Confirm and Reject, the accuracy report, Approve whole design, the weight check states, the tabs, the History tab, and the rebuild test all work on the 3 parts.

---

### M3: Product polish (within the nine-hour budget)

**Goal:** the rest of the design that makes it feel like a product.

- **3D:** focused orbit/Fit/section/A–B controls and STEP export. Put model provenance, calculations and extra engineering records in Debug; retain core part details in the standard Detail sections.
- **Chat:** the hover card crop of the cited spot.
- **Data:** hole callouts (A7 level 1), the rest of the cleanup rules plus `cleanup_report.json` (A3), and the README as a citable source with its own page (A11).
- **UI:** parts list filters and the full link scheme (B8).

**M3 is stable when:** every earlier check still passes, plus each item above works on at least one example.

---

### Finish the current run and optional extras

Items 1–2 are required for the current run. Remaining extras are optional only after final verification and within the nine-hour limit:

1. Complete assessment of every additional drawing and generate every eligible flat-part model; this is now required for the current run.
2. Complete the benchmark and scoring using Jason's supplied `docs/Question-benchmark/benchmark_draft.md` and its run plan; this is now required. Do not generate a substitute question set.
3. The diagrams (A12).
4. AI labels for all drawings (A7 level 3).
5. Feature colors and measurement labels drawn on the 3D model.
6. Broader chat-provider support remains excluded; the app uses `gpt-6-luna` only.
7. The files page (B7).

**Not in this build:** the round part template, custom outlines, a solid cut face for the section view, and the MCP server.

---

## Stabilize and tag (end of every milestone)

1. **Freeze merges** for the milestone. Only fixes from here.
2. **Run the milestone's checklist**, plus every earlier milestone's checklist. Fix only what blocks a check.
3. **Commit the outputs:** `generated/` (records, links, templates, AI cache, images, models), `decisions/`, and the built `frontend/dist/`.
4. **Update the README's "What's in this version" section** and its limitations, so this tag's README describes this tag.
5. **Save a few screenshots and chat transcripts** in `docs/stable-mN/`.
6. **Run once from a fresh clone** with `uv run meridian`.
7. **Tag it:** `git tag stable-mN`.

---

## Timeline

| Hours | What |
|---|---|
| 0–1 | **M0.** W2 starts the runner immediately. Jason logs into the CLIs and adds the chat key. |
| 1–3 | Loaders, bounded prep runner, basic app and the first three CAD templates; coding work respects the shared resource budget. |
| 3–5 | Integrate review workflow, clean customer/Debug views, saved chats and source-grounded prep; preserve historical milestone tags. |
| 5–7 | Finish proposer–verifier prep and all remaining drawing assessments; generate eligible CAD remotely and ship verified caches. |
| 7–8 | Full remote tests, independent STEP/GLB probes, fresh-clone recovery and customer/Debug browser checks; repair concrete failures. |
| 8–9 | Two-pass canonical benchmark, sequential independent judging, final reports/package and buffer. Actual human reviews remain pending until performed. |

## Workstreams

The same six lanes are used in every milestone. Each owns its folders.

| ID | Owns | M1 | M2 | M3 |
|---|---|---|---|---|
| **W0** | root, `fixtures/` | (M0 only) | | |
| **W1** | `backend/loader/` | parse drawings, cleanup core, records, merge AI results, decisions apply | fingerprints, rebuild test | callouts, rest of cleanup, README split |
| **W2** | `backend/ai/` | **the runner (from hour 0)**, retry round, scans, matching, name mappings, templates | accuracy report from Jason's checks | |
| **W3** | `backend/cad/`, `frontend/src/viewer3d/` | GLBs from AI templates, rebuild after review answers, 3D tab | weight check | size readout, thumbnails, section view, STEP |
| **W4** | `backend/app/`, `frontend/src/review/` | tools, chat, markers, chat wording, review API and review page | Confirm and Reject, Approve whole design, review tabs, history API | crop endpoint, README tool |
| **W5** | `frontend/src/chat/` | chat, citation and Undetermined tags, part cards, side panel, "Waiting for review" links | | hover card crop, README page, link scheme |
| **W6** | `frontend/src/part/` | part page shell, 2D tab, Detail tab with AI badges, parts list | History tab | 3D side panels, parts list filters |

---

## Contracts

Every workstream builds against these. They're **frozen after M0**. Change one only by editing this file and telling every agent.

### 1. Folder layout

```
meridian/
  pyproject.toml  uv.lock  start.sh  start.bat  .env.example  ai_settings.yaml
  dataset/                      the supplied files, unchanged
  backend/loader/               W1
  backend/ai/                   W2
  backend/cad/                  W3
  backend/app/                  W4
  frontend/src/chat/            W5
  frontend/src/part/            W6
  frontend/src/viewer3d/        W3
  frontend/src/review/          W4
  frontend/dist/                committed at every tag
  generated/                    records.json, links.json, templates/, models/, images/, ai_cache/ (committed at every tag)
  decisions/                    human decisions (approvals, answers, corrections)
  fixtures/                     W0's sample data
  docs/stable-mN/               screenshots and transcripts per tag
```

### 2. Stable names (`proposal.md` A9)

- `D-013/drawing/material`, `D-013/template/thickness`, `D-013/part`
- `BOM:<section>/<name>/<field>`, `BOM:<section>/<name>/part`
- `README/<section>/p<n>` (M3)
- `names/<kind>/<name> -> <name>` for name mappings

Names are lowercased, with spaces turned into dashes.

### 3. Part record (`generated/records.json`, a list)

```json
{
  "id": "D-013/part",
  "display_name": "Recoater Plate",
  "section": "Recoater",
  "has_drawing": true,
  "has_3d": true,
  "examples": ["A", "B"],
  "drawing": {
    "id": "D-013", "pages": 1, "image": "images/D-013-p1.png", "degraded": false,
    "fields": {
      "material": {"name": "D-013/drawing/material", "value": "3.3315 (EN-AW 5005)", "confidence": "sure",
                   "method": "parsed", "page": 1, "box": [612, 780, 140, 14]}
    },
    "numbers": [{"name": "D-013/drawing/n/270.0@1", "value": 270.0, "page": 1, "box": [0, 0, 0, 0]}]
  },
  "bom": [
    {"name": "BOM:recoater/recoater-head", "display_id": "BOM-028",
     "fields": {"material": {"name": "BOM:recoater/recoater-head/material", "original": "Aluminium",
                             "value": "Aluminium", "method": "parsed"}}}
  ],
  "link": {"method": "ai_agreed", "review": {"status": "not_reviewed"}},
  "template": "templates/D-013.json",
  "weight_check": null
}
```

(Values and the linked row are placeholders, not verified matches. `weight_check` stays `null` until M2.)

### 4. Tool result for one fact

What `get_facts` returns. The frontend uses the same shape.

```json
{
  "fact": "D-013/drawing/material",
  "display": {"state": "value", "value": "EN-AW 5005 aluminium"},
  "badge": "From PDF",
  "review": null,
  "sources": [{"name": "D-013/drawing/material", "says": "3.3315 (EN-AW 5005)", "method": "parsed"}],
  "snapshot_note": false,
  "review_item": null,
  "correction": null
}
```

- `display.state` is `value`, `options` (with `values: [...]`), or `undetermined` (with `message`).
- `review` is `null` for rule-based and human facts, and `{"status": "not_reviewed" | "human_confirmed" | "human_rejected", "by": ..., "at": ...}` for AI facts.
- `correction`, once one is accepted: `{"original": "...", "corrected": "...", "by": "Jason Peng", "at": "..."}`.

### 5. Chat markers (`proposal.md` B1)

- `[cite: name1, name2]` goes after a claim.
- `[undetermined: name]` goes where the value would be, and also counts as a citation.

### 6. Chat API response

```json
{
  "text": "The recoater plate is made of EN-AW 5005 aluminium [cite: D-013/drawing/material].",
  "facts": {"D-013/drawing/material": { "...tool result shape above..." }},
  "parts_to_show": [{"id": "D-013/part", "display_name": "Recoater Plate", "thumbnail": "/api/parts/D-013/image?page=1&thumb=1", "has_3d": true}],
  "warnings": []
}
```

### 7. Decision (appended to `decisions/<id>.json`)

```json
{"decision_id": "HD-0001", "applies_to": "D-019/drawing/title", "type": "correction",
 "value": "Silicone gasket for f-theta lens", "old_value": "Description",
 "status": "accepted", "check_result": "...", "by": "Jason Peng", "at": "2026-..."}
```

`type` is `correction`, `link`, `set_value`, `choose_option`, or `name_mapping` (M1); `confirm`, `reject`, or `approve_design` (M2). From M2, decisions also carry `"based_on": {"sha256": "..."}`.

### 8. Template (`generated/templates/D-0XX.json`)

The flat template subset listed in M1, using `proposal.md` B5's example shape. Every field has `state` (`known`, `options`, or `unknown`), `value` or `options`, `method`, and the names of the numbers it came from.

### 9. API endpoints

| Method | Path | Returns | From |
|---|---|---|---|
| GET | `/api/status` | `{"chat_available": true}` | M1 |
| GET | `/api/parts?q=` | the parts list | M1 |
| GET | `/api/parts/{id}` | the record, plus every fact in the tool result shape | M1 |
| GET | `/api/parts/{id}/image?page=1&thumb=0` | a PNG | M1 |
| GET | `/api/models/{drawing_id}_{example}.glb` | a GLB | M1 |
| POST | `/api/chat` | the chat API response | M1 |
| GET | `/api/chats` | saved conversation titles, IDs, timestamps and message counts | Extension |
| GET | `/api/chats/{id}` | a saved conversation with answers, citations and attachments | Extension |
| DELETE | `/api/chats/{id}` | deletes only that saved conversation | Extension |
| GET | `/api/review` | pending review items | M1 |
| POST | `/api/review/{item_id}` | `{"action": "accept|reject|set_value|choose_option|approve_mapping", "value": ..., "note": ...}` in M1; adds `confirm`, `approve_design` in M2 | M1 |
| GET | `/api/parts/{id}/history` | the part's timeline | M2 |
| GET | `/api/accuracy` | confirmed and rejected counts by job | M2 |
| GET | `/api/parts/{id}/crop?fact=...` | a small PNG crop of the cited spot | M3 |
| GET | `/api/models/{drawing_id}_{example}.step` | the STEP download | M3 |
| GET | `/api/readme` | README passages with stable names | M3 |
