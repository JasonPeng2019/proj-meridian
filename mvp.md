# Project Meridian: MVP Build Spec

**Time budget:** 12–14 hours. **Approach:** build in **stacked milestones**. Each milestone is a complete, working, **submittable** version, tagged in git as `stable-m1`, `stable-m2`, and so on. If time runs out at any point, check out the latest tag and submit it.

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

- **No test suites** (unit, integration, or end-to-end), no CI, no linting, formatting, or type-checking setup. Each milestone has one manual or scripted checklist instead.
- **No abstractions for the future:** no plugin systems, interfaces, or "in case we need it" layers. Duplicated code is fine.
- **No refactoring** of working code. If it works, leave it.
- **No logging framework.** `print` is fine.
- **No docs** beyond the README write-up and short code comments where something is non-obvious.
- **No data migrations or versioned formats.** If a format changes, regenerate.
- **No performance work.** Load everything into memory.
- **No database.** Part records are one `generated/records.json` file loaded into memory, instead of the SQLite database in `proposal.md`.

**Product concerns skipped (single local user):**

- **No login, accounts, permissions, or multiple users.** The reviewer is always Jason Peng, from the settings file.
- **No answer key.** Nothing is hand-filled. Jason checks AI output on the review page, and those checks are the accuracy measure.
- **No security hardening.** It runs locally.
- **Desktop browser only.** No mobile layout, no touch support, no accessibility work, no translations.
- **One chat provider**, whichever one Jason has a key for.

**Edge cases ignored:**

- **Data outside this dataset:** other drawing layouts, other spreadsheets, other units. Hardcoding for these 30 drawings and this one spreadsheet is fine.
- **Malformed input** beyond what the demo uses. If a source file is odd, the loader can fail loudly.
- **Malformed AI output:** anything that doesn't parse counts as "not agreed." No repair attempts.
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

**Goal:** meets every assignment requirement, and **everything is filled by the two-model AI pipeline**. Jason only checks what the AI couldn't agree on. This is the floor you can always submit.

**The runner (W2), built first:**
- runs both CLIs from `ai_settings.yaml`, validates any IDs they use, checks agreement (both `sure`, same answer), and caches results by a hash of the inputs;
- runs jobs **in parallel** with a cap (16) and waits out rate limits;
- runs in **stages**: (1) scans and templates, (2) matching (which uses the scan titles), (3) name mappings (which use the links), then (4) **the retry round** for sure-vs-sure disagreements;
- anything that doesn't parse counts as "not agreed."

**AI prep jobs (W2), all through the runner:**
- **Scans (A2):** corner boxes. Agreed fields are `ai_read`. The rest are Undetermined ("Too blurry to read on the scan"). Citations highlight the whole field box.
- **Matching (A4):** exact matching first (datasheet filename, then normalized names, exactly one match), then the runner. Agreed links are `ai_agreed` or `ai_agreed_after_retry`. Anything else becomes a review item.
- **Name mappings (A10):** the runner suggests a relationship (`same`, `kind_of`, `different`, `no_equivalent`) for each of the roughly 15 section and material pairs. **Every mapping needs Jason's approval** before it's used. Until then, differing names show as Undetermined ("These names haven't been mapped yet").
- **Templates for D-013, D-025, and D-026 (B5):** the flat template subset: outline (rectangle, circle, ring), thickness (with `options`), holes (plain, threaded, countersunk, counterbored; through or a depth), slots, and patterns (row, circle). Agreed fields are AI values. The rest become review items.

**Setup loader (W1):**
- **Clean drawings (A1):** text with positions, PNG per page, corner box read by finding labels.
- **Parts list cleanup (A3), core:** load as text, trim, blanks become `null`, parse prices, the zero-total trap, split comma lists, snapshot notes. Originals kept.
- **Connections (A5)**, **part records (A6)** in `generated/records.json`, and **method labels (A8)**.
- **Decisions (A9):** saved in `decisions/` and applied on every rebuild. The AI never overwrites one.
- Merges in the AI results: scan readings, links, approved name mappings, and templates.

**3D (W3):**
- CadQuery builds **one GLB per example** (A and B) from each filled-in template, in neutral grey. Built files are committed.
- If a template field the shape depends on is still waiting for review, that part shows "3D waiting for human input on: [field]" until Jason answers it.
- After Jason answers a field, that part's model is rebuilt.

**Backend (W4):**
- `tools.py` with `find_part`, `get_facts` (display values resolved in code using B3 rules 0–5), `get_connections`, `parts_in_section`, `parts_with_material`, and `propose_correction`.
- The chat loop (one provider, tool calling, marker rules in the system prompt).
- The marker parser (`[cite:]` and `[undetermined:]`, with the existence and "returned this conversation" checks), cards for 1–3 parts, a list for 4 or more, the single-match backup rule, and the uncited warning.
- Chat wording: "AI-sourced only, not yet reviewed; may contain errors" for AI items, and "Waiting for review," with a link, where a review item exists.
- **The review API:**
  - **items:** corrections, unresolved links, template fields that weren't agreed, and name mappings waiting for approval;
  - **actions:** accept, reject, set a value, choose an option, and approve a mapping;
  - each action writes a decision and re-applies decisions;
  - the correction check is a simple string match against the drawing text and the linked row.
- With no API key, `/api/status` says chat isn't available.

**Frontend (W5, W6, plus W3 for the 3D tab and W4 for the review page):**
- **Chat:** messages, citation tags with a hover card (source, what it says, badge), the Undetermined tag with its message, part cards with a thumbnail, and the side panel.
- **Part page** (also used in the side panel): 2D tab (PNG, highlight box, zoom); 3D tab for the 3 parts (spin, zoom, Fit, A/B switch, the reconstruction label); Detail tab (facts with badges or Undetermined; corrected values show "originally X, corrected to Y by Jason Peng on [date]"; a list of this part's decisions).
- **Parts list:** every part, with search.
- **Review page:** one list of everything waiting, each item with its evidence (the drawing with a highlight, or the row's values), both AI answers, and its actions.
- With no key, the chat says "Add an API key to use the chat."

**Write-up (any agent, plus Jason):** the README with every section the assignment asks for, a "What's in this version" section, saved transcripts and screenshots in `docs/stable-m1/`, and observations: time and token use for about 5 questions run twice, plus the AI prep's agreement counts (how many items were agreed, agreed after retry, or sent to review).

**Jason, around hour 5:** check the review page: approve the name mappings, and answer any links or template fields the AI couldn't agree on (roughly 20–40 minutes).

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

- **Confirm and Reject for every AI item** (A8, B6): links, template fields, scan readings, and whole parts. Reviewed items show "reviewed by Jason Peng on [date]" everywhere.
- **The accuracy number:** of the AI items Jason checked, how many he confirmed and how many he rejected, broken down by job (scans, matching, templates). This replaces the answer key and goes in the README.
- **Approve whole design** (B6): a part review page that reuses the part page's views, one part at a time, disabled while any field waits for a value.
- **Weight check** (B5): Passed, Flagged, **FAILED (big red, "needs manual approval")**, or Skipped, using a small density table with sources. It never hides the model. Approving a FAILED part requires a note.
- **Review tabs and filters** (B6): Corrections, Needs human input, AI interpretations, and Possible readings.
- **Full History tab** (B5), and a single fact's history when clicking its badge.
- **Fingerprints and changed evidence** (A9 rule 4), and a **rebuild test** script.

**Jason:** confirm or reject every AI item on the 3 parts, plus the links and scan readings (all of them if time allows, otherwise a sample, and the README says which), and use Approve whole design on the 3 parts.

**M2 is stable when:** every M1 check still passes, plus Confirm and Reject, the accuracy report, Approve whole design, the weight check states, the tabs, the History tab, and the rebuild test all work on the 3 parts.

---

### M3: Product polish (target: tagged by about hour 9.5)

**Goal:** the rest of the design that makes it feel like a product.

- **3D:** the side panels (Model provenance, Bill of materials, Specs and materials, Installed in), the size readout, page thumbnails, the basic section view, and the STEP download.
- **Chat:** the hover card crop of the cited spot.
- **Data:** hole callouts (A7 level 1), the rest of the cleanup rules plus `cleanup_report.json` (A3), and the README as a citable source with its own page (A11).
- **UI:** parts list filters and the full link scheme (B8).

**M3 is stable when:** every earlier check still passes, plus each item above works on at least one example.

---

### Later (only if there's time after M3)

In this order:

1. More parts in 3D (the other 7 flat parts).
2. The 20-question benchmark and its scoring script. Jason writes the questions from the source files.
3. The diagrams (A12).
4. AI labels for all drawings (A7 level 3).
5. Feature colors and measurement labels drawn on the 3D model.
6. A second chat provider.
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
| 1–4.5 | **M1 build**, all six workstreams in parallel. |
| 4.5–5 | **Run the full AI prep** on the real data (a few minutes), then integrate. |
| 5–5.5 | **Jason checks the review page:** approves the name mappings and answers what the AI couldn't agree on. |
| 5.5–6 | **Stabilize and tag `stable-m1`.** |
| 6–7.5 | **M2 build** (much of it from work-ahead branches). Jason confirms or rejects the AI items on the 3 parts. |
| 7.5–8 | **Stabilize and tag `stable-m2`.** |
| 8–9 | **M3 build.** |
| 9–9.5 | **Stabilize and tag `stable-m3`.** |
| 9.5–12.5 | **Jason tests it.** Fixes get re-tagged. "Later" items only if everything is solid. |
| 12.5–13.5 | Final write-up, screenshots, transcripts, and a final fresh-clone run of the latest tag. |
| 13.5–14 | Buffer. |

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
| GET | `/api/review` | pending review items | M1 |
| POST | `/api/review/{item_id}` | `{"action": "accept|reject|set_value|choose_option|approve_mapping", "value": ..., "note": ...}` in M1; adds `confirm`, `approve_design` in M2 | M1 |
| GET | `/api/parts/{id}/history` | the part's timeline | M2 |
| GET | `/api/accuracy` | confirmed and rejected counts by job | M2 |
| GET | `/api/parts/{id}/crop?fact=...` | a small PNG crop of the cited spot | M3 |
| GET | `/api/models/{drawing_id}_{example}.step` | the STEP download | M3 |
| GET | `/api/readme` | README passages with stable names | M3 |
