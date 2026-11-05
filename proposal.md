# Project Meridian: Implementation Proposal

> **Build scope:** this file is the full design and the reference for how things should behave. **What actually gets built is defined in `mvp.md`.** Anything not listed there is post-MVP. When the two disagree, `mvp.md` wins for the build.

## Goal

Build a small app that runs on a local computer, where an engineer can chat about the parts of the OpenLPBF v2 metal 3D printer. The app:

1. answers questions using facts pulled out of the drawings and the parts list ahead of time, and says where each fact came from;
2. attaches the part's 2D drawing, and a spinnable 3D model for at least 3 parts, whenever a part comes up in chat, opening them in a side panel next to the chat;
3. says "I don't know" or "these sources disagree" instead of guessing;
4. lets a user suggest a fix to wrong info, which a person then accepts or rejects on a review page, without ever erasing the original.

The focus is on answers you can trust and check, not on lots of features.

---

## What's in the data (and what I noticed)

**Drawings.** 30 PDFs (`D-001` to `D-030`), one part each, across 6 sections of the machine: Box, Powder, Recoater, Optical, Gas Flow, Z-axis.

- **22 are clean.** The text can be pulled straight out of the PDF.
- **8 are fake "bad scans"** with no text inside, just a picture: D-001, D-003, D-009, D-011, D-020, D-022, D-023, D-030. Their corner boxes are read by the two AI models (A2), and some fields may be unreadable.
- Every drawing has a box in the corner with labeled fields: `TITLE/DESCRIPTION`, `MATERIAL`, `WEIGHT [g]`, `DATE`, `NOTE`, `SCALE`. These are easy to grab.
- Notes are often in Danish ("Justeringsplade til recoater", "1mm silicone pakning").

**Parts list (BOM).** `openlpbf-bom.csv`, 192 rows, 20 columns. It covers names, section, type, material, supplier, order number, link, price in DKK, status columns, notes, and "Interface with."

- Messy, but in predictable ways (see A3 for the full cleanup):
  - typos in status values ("Recieved"), extra spaces, and literal `\n` characters in text;
  - prices stored as text like `DKK53.00`;
  - lots of blanks: Material is blank on 123 rows, Cost on 75;
  - **a hidden trap:** on all 75 rows with no price, "Total cost" says `DKK0.00`. That means "no price recorded," not "free." Adding up Total cost naively would give a wrong machine cost;
  - some cells hold several values separated by commas, like `Stainless steel,Steel`;
  - the Image and Datasheet columns hold `filename.pdf (link)`, and the links are temporary Airtable links that have almost certainly expired.
- **"Interface with" is filled in for only 9 rows**, all Box parts. Most parts have no recorded connections.
- **The Datasheet column names some drawing files.** For example, the "Recoater Arm" row lists `RecoaterArm.PDF`. This is a reliable matching clue (A4), but it only covers 4 of the 30 drawings, and one of them (`RecoaterPlate.pdf`) is listed on two different rows.

**Drawings and parts list don't line up neatly.**

- Names differ, and some are in Danish. Drawing "Bygge Base Ring" is "Build Base Ring."
- Materials are worded differently. The drawing says `3.3315 (EN-AW 5005)` while the parts list says `Aluminium`. EN-AW 5005 is a kind of aluminium, so the drawing is just more specific (A10).
- **D-019's title field says "Description"** because the designer never filled it in. Its note says "1mm silicone pakning," and it probably matches the parts list row "Silicone gasket f-theta ring." This is a real data error, and a good one to use for the correction demo.
- D-026 (Build Plate) is messy on material: its material field is printed on top of the weight label, so the text comes out garbled (A1); its note mentions both stainless steel and aluminium; and its parts list row says "Stainless steel,Steel." How this is shown is covered in B3 (rule 5 and its known limit).
- **Stacked thickness numbers.** On D-013, D-025, D-026, and D-028, the thickness is printed as two numbers stacked on top of each other (for example, "6,0" over "3,0"). The drawing doesn't say which applies. These are handled as `options` (B5).

**Other files.** `manifest.json` lists every file, its section, and whether it's a degraded scan. There's also the machine's README (A11) and 6 system diagrams (A12).

**Missing.** The assignment mentions `fixtures/public_questions.json`, but it isn't in the zip. It's described as examples only, so I'll write my own test questions. Still worth asking the recruiter.

---

## The main idea: two halves

**Half A, the setup loader.** Reads all the files, cleans the parts list, pulls out the facts, links drawings to parts list rows, builds the 3D models, and saves everything into one database.

- **Rule-based steps** (PDF text, parts list cleanup, building part records) are fast and run automatically every time the app starts (`uv run meridian`).
- **AI steps** (reading scans in A2, matching in A4, labeling in A7, name mapping suggestions in A10, diagram label readings in A12, template filling in B5) run only when a source file is new or changed. Their results are saved and reused.
- **Shipped results.** Everything the slow or paid steps produce is included in the submission, so the app runs without Claude Code, Codex, or CadQuery installed:
  - `links.json` (A4), scan readings (A2), AI labels (A7), name mapping suggestions (A10), diagram label readings (A12), and filled-in templates (B5);
  - the built 3D models: GLB files for the viewer and STEP files for download (B5);
  - the `decisions/` folder with every human decision (A9). Unlike the others, this can't be regenerated, so it's never deleted.

  These tools are only needed to **redo** those steps.

**Half B, the app.** Loads the database and answers from it. It never reads the raw PDFs during a chat.

This split is how we show we're answering from organized facts, not just stuffing PDFs into an AI.

---

## Tools

| Job | Tool |
|---|---|
| Backend / server | Python + FastAPI |
| Database | SQLite (one file, nothing to install) for generated data that can be rebuilt any time. Human decisions are kept separately in plain JSON files (A9). |
| Read PDFs and turn pages into images | PyMuPDF |
| Read the parts list | pandas |
| Match drawings to parts list rows | Exact name matching first, then two different AI models (Claude Code and Codex CLI) for the rest, then a human for anything unsure. Run once, results saved. |
| Read text from the blurry scans | The same Claude Code + Codex setup, corner boxes only, results saved (A2). No OCR software. |
| Label what measurements and notes mean (A7), suggest section and material name mappings (A10), read diagram labels (A12), fill 3D templates (B5) | The same Claude Code + Codex setup, run by the setup loader only when a source file changes, results saved |
| Build 3D models | CadQuery (Python). Exports a GLB file for the browser and a STEP file for download. Built files ship with the app. |
| Show 3D models in the browser | **React Three Fiber + Drei** (React tools built on Three.js), loading the GLB files, with spin, zoom, fit, and hover highlighting |
| Chat | **Whichever provider the person running the app supplies a key for:** Anthropic (Claude), OpenAI (GPT), or any OpenAI-compatible address, like many company gateways. Set in `ai_settings.yaml`. The chat calls our lookup functions in `tools.py`. (An MCP server is deferred; see B1.) |
| Frontend | **React**, built with **Vite**, styled with **Tailwind** and **shadcn/ui** (ready-made hover cards, tabs, side panels, sidebar, and badges). Chosen because it gets a polished look, close to the reference screenshots, with the least work. **Shipped prebuilt**, so no Node.js is needed to run it. |
| Python and packages | **uv**, with a lock file. uv installs the right Python version and exact package versions on Mac, Linux, and Windows. (Docker was considered and not chosen; see Launching below.) |
| Launch | **`uv run meridian`**, the same command on every system, plus one-line convenience files `start.sh` (Mac, Linux) and `start.bat` (Windows) that call it |

API keys go in a `.env` file that is never committed. The write-up will say clearly which files get sent to an outside AI service. **Two sides, at two different times** (full table in `gaps.md`, Gap 4):

- **Engineer's side, during prep:** Claude Code and Codex run on the engineer's computer, but the models behind them run on Anthropic's and OpenAI's servers. So while building the database (A2, A4, A7, A10, A12, B5), drawing info, page images, diagram images, and parts list names are sent to Anthropic and OpenAI. This happens once, and again only if something is redone.
- **Customer's side, during use:** the customer gets the pre-built database, built 3D models, and `decisions/`. They don't need Claude Code, Codex, or those accounts. They only need **one API key, for the chat**, which sends their questions and the facts the tools look up to the chat provider.

**Decision: sending data to outside AI providers is acceptable for this project.**

- **Why:** many companies already run AI tools through enterprise agreements or private, internally approved deployments, for example GitHub Copilot Enterprise, or an internal model gateway like TrueFoundry. Building something that scales with AI help while also requiring that no data ever reaches an AI provider isn't realistic. The practical goal is to send data only to the providers a company has approved, and to be open about exactly what's sent.
- **What this means for the design:**
  - **Prep uses the CLIs, and the CLIs decide where requests go.** The setup loader never calls an AI provider itself. It runs each reader's command and reads the answer. Where those requests actually go (a company account, a cloud provider, or a company gateway) is set up **in each CLI's own settings** on the engineer's computer, not in this app. A company that has approved Claude Code and Codex configures them once, and the pipeline doesn't change. (Check each CLI's docs for the exact options.)
  - **The app's settings file (`ai_settings.yaml`) only holds:**
    - **for prep:** the command each reader runs, and which model, for example `reader_a: claude -p --model <model>` and `reader_b: codex exec -m <model>`;
    - **for the chat:** the provider, endpoint, model, and API key (the key comes from `.env`). The chat is the only place the app calls an AI provider directly, so a customer with an internal gateway changes the endpoint and key here.
  - **The chat isn't tied to one provider.** Whoever runs the app supplies the key and picks the provider and model. Supported: Anthropic, OpenAI, and OpenAI-compatible addresses. The two providers format tool calls slightly differently, so `ai_client.py` has a small adapter for each, and the rest of the app doesn't know or care which one is in use.
  - **Keys never ship.** The assignment says to keep credentials out of the submission, so `.env` is never included. Reviewers add their own key, or use the saved transcripts and screenshots (Testing).
  - **The two readers must be different models.** The two-reader check (A4) depends on the readers being independent. If both CLIs are configured to reach the same underlying model, the setup loader shows a warning, since one model tends to repeat its own mistakes.
  - The disclosure table (`gaps.md`, Gap 4) stays in the write-up, so a company can check what would be sent before adopting this.
- **For this submission:** the prep steps use Anthropic (via Claude Code) and OpenAI (via Codex), and the saved chat transcripts use the provider and model of the key supplied for testing. The write-up names that model.

### Launching on someone else's computer

The assignment asks for code that can "run with simple start script and all requirements built in and documented."

- **One command, every system: `uv run meridian`.** It's defined once in the project settings (`pyproject.toml`). uv reads the lock file (`uv.lock`), installs the right Python version and the exact packages if needed, runs the setup loader's rule-based steps, and starts the app.
- **Convenience files:** `start.sh` for Mac and Linux, and `start.bat` for Windows. Each is one line that runs `uv run meridian`. Two files are needed because Windows' built-in terminals can't run `.sh` bash scripts.
- **The only thing to install first is uv**, a one-line install on each system, documented in the README.
- **Nothing else is needed to run the app.** The frontend ships prebuilt, so no Node.js. The scan readings, links, labels, templates, 3D models, and `decisions/` all ship pre-built, so no Claude Code, Codex, CadQuery, or OCR software.
- **No API key:** the chat shows a clear message, like "Add an API key to use the chat." Everything else still works: parts list, drawings, 3D views, history, and the review page. Any chat needs a model somewhere, and shipping one isn't realistic. For reviewers without a key, the saved transcripts and screenshots (Testing) show the chat working.
- **Why not Docker:** Docker bundles the whole system, but reviewers would need Docker Desktop installed, which is a large download. It mainly pays off when an app needs system-level programs, and this plan has none left to run the app. uv covers everything that's left.

---

## Half A: the setup loader

### A1. Clean drawings

- Pull out all text with PyMuPDF (or pdfplumber), **including where on the page each word is**, for highlighting later.
- Read the corner box fields by anchoring on their labels (decision below).
- Save the page as a PNG image for the viewer.

#### Decision: read the corner box by finding each label, then looking next to it

**The problem.** Reading a PDF's text from top to bottom gives words in a jumbled order. In an early test, some titles came out as "A" (a grid letter from the page border) or as the designer's name, because those words happened to come first.

**The approach.** Every field in the corner box has a printed label, like `TITLE/DESCRIPTION:` or `MATERIAL:`. The code finds the label by its exact text, then collects the words in the spot where that field's value goes:

| Label | Where the value is |
|---|---|
| `TITLE/DESCRIPTION:` | Below the label, inside the same box |
| `NOTE:` | Below the label, inside the same box (can be several lines) |
| `COMPANY:` | Below the label |
| `MATERIAL:` | To the right, on the same line, stopping at the next label (`WEIGHT`) |
| `WEIGHT [g]:` | To the right, on the same line |
| `DRAWN`, `DATE` | To the right, on the same line |
| `SCALE:` | In the same word (`SCALE:1:2`) |

This table lives in a small settings file, not in the code, so a drawing with a different corner box layout only needs a new table.

**Rules:**

1. **Remove duplicate words first.** Some PDFs draw the corner box text twice in exactly the same spot (D-013 does this). Words with the same text and position are counted once.
2. **Stop at the next label.** A value never includes another label's text. Without this rule, D-013's material came out as `3.3315 (EN-AW 5005) WEIGHT`.
3. **Mark suspicious values as `unsure`** instead of trusting them:
   - the field is empty;
   - the value looks like a placeholder, such as `Description` (D-019);
   - the value overlaps another label. On D-026, the material and weight text are printed on top of each other, so the extracted text comes out garbled.
4. **Keep the label's and the value's positions**, so the viewer can highlight both.
5. **Every value is marked `method: parsed`** (A8).

**Test results on the 22 clean drawings:**

- **Title:** found on 16. Of those, D-019's is the placeholder `Description`.
- **Title field empty:** 6 drawings (D-002, D-004, D-006, D-010, D-021, D-029). On these, the designer wrote the part's name in the notes instead. For example, D-002's note starts with "Left Wall" and D-021's with "Blower Outlet." The code does **not** copy the name from the notes into the title. The title stays empty and `unsure`, and the notes are saved as written. The matching step (A4) uses the notes as a clue.
- **Material:** found on 14 (one garbled, D-026). Empty on 8, where it's sometimes written in the notes instead, like "2mm non-magnetic stainless" on D-002.

The corner box is in the same place on every drawing in this set, so hard-coding pixel areas would also work here. Anchoring on labels was chosen anyway because it still works if the layout shifts, which matters for adding new drawings later.

### A2. Blurry drawings

**Decision: the two AI models read the scans. No OCR software (like Tesseract) is used.**

A quick test with Tesseract, a free OCR program, read the most important corner box fields on two scans correctly (for example D-023's title, material, and weight), but garbled Danish letters and small print and added junk from the box lines. The two-model pipeline is already in the plan, likely reads Danish and noisy text better, and avoids installing another program. The tradeoff: an AI's mistakes look like plausible text rather than obvious garbage, so the rules below are strict.

**What's read: the corner box only.** Title, material, weight, notes, date, company, and scale. The measurements in the main drawing area are **not** read on scans.

**How:**

1. **Prepare the image.** Render the page at high resolution and crop the corner box. Since the corner box is in the same place on every drawing in this set, its area, and the area of each field inside it, is measured once from the clean drawings (using the label positions from A1) and saved in the same settings file as the label table.
2. **Both models read it separately.** Claude Code and Codex each get the cropped image and the list of fields to read. The prompt says: **copy exactly what's printed, character by character. Don't fix spelling, don't translate, and don't fill in anything you can't see.** Each field gets a value, or `unreadable`, plus `sure` or `unsure`.
3. **Decide each field** with the usual rules (A4), including the retry round:
   - both `sure` with the same text → used, marked `ai_read` (an AI interpretation, A8);
   - anything else → the value is `null` and shows as **Undetermined**, with the message "Too blurry to read on the scan."
4. **No human review queue** for unreadable scan fields. Like unlabeled measurements (A7), an Undetermined value is already a safe answer. A user can still propose a value through the correction feature (B6).
5. **Everything is marked `source_quality: degraded`**, and the badge says "AI reading of a blurry scan."

**Highlights on scans.** There are no exact word positions on a scan, so citations highlight the **whole field box** (for example, the whole MATERIAL cell), using the field areas from step 1.

**Cross-checks.** A misread title or material usually won't match anything in the parts list, so it goes to a person during matching (A4) or shows as Undetermined (B3), instead of quietly spreading.

**What this means for the scans:**

- They get titles, materials, weights, and notes where readable, which helps matching, material answers, and the corner box facts in chat.
- They get **no measurement facts, no AI labels (A7), and no 3D models (B5)**, since those all depend on numbers from the main drawing area. Their 3D view shows "No 3D model: this drawing is a degraded scan."

**Results ship with the app**, like the other AI results, so nothing needs to be re-read to run it.

### A3. Parts list cleanup (part of the setup loader)

The parts list mess is the normal kind of spreadsheet mess, so cleanup is standard and rule-based. **No AI is used.** It runs automatically every time the loader runs.

**The golden rule:** every cleaned value keeps the original text next to it, plus a list of which cleanup rules changed it. Nothing is silently fixed.

**Cleanup rules:**

1. **Load everything as text** (pandas with `dtype=str`), so nothing gets auto-converted in surprising ways. Give every row an ID like `BOM-046` for display, plus a stable name built from its part name and section, which is what decisions point to (A9).
2. **Trim extra spaces** at the start and end of every cell.
3. **Turn literal `\n` into real line breaks** in text fields.
4. **Blanks become `null`, labeled "not recorded."** Never `0`, never an empty string.
5. **Prices:** `DKK53.00` becomes `{"amount": 53.0, "currency": "DKK"}`.
6. **The zero-total trap:** if Cost or Amount is blank, Total cost becomes `null` ("not recorded") even though the file says `DKK0.00`. The original `DKK0.00` is kept and the rule is noted.
7. **Check totals:** where Amount and Cost are both present, check that Amount × Cost = Total cost and flag any mismatch. (In this file, all of them match.)
8. **Status spellings:** a small fixed table maps known values for Design, Order, and V&V, such as `Recieved` → `Received`. Any value not in the table is kept as-is and flagged.
9. **Comma lists:** Material and Interface with are split into lists, such as `Stainless steel,Steel` → `["Stainless steel", "Steel"]`.
10. **Filename + link columns** (Image, Datasheet): split into filename and link. Links are marked "temporary link from the original export, likely expired."
11. **Column names:** given clean internal names (`Design Intend` → `design_intent`), while the original header is kept for display and citations.
12. **Snapshot warnings:** supplier, price, order number, and link fields are always marked "recorded in the snapshot, may be out of date."
13. **Flag, don't fix:** near-duplicate names, unknown status values, and odd numbers are listed in a cleanup report, not changed.

A cleaned field looks like:

```json
"total_cost": {
  "fact_id": "F-1305",
  "original": "DKK0.00",
  "value": null,
  "method": "cleanup_rule",
  "cleanup": ["zero_total_with_blank_cost → not recorded"]
}
```

**Cleanup report:** the loader writes a short summary file, `cleanup_report.json`, listing how many values each rule changed and every flagged item. It's **for the write-up only** and isn't shown in the app. Each individual change is already visible on the part's Detail and History tabs (B5).

### A4. Match drawings to parts list rows

**Why this needs care:** a quick test of simple name matching got only about 11 of 26 drawings clearly right. The misses came from Danish names ("Galvo Bundplade" = Galvo bottom plate), different wording (`TopPlate` vs "Top Side"), missing or junk titles (D-019 says "Description"), and close calls (`Door_x2` could be the front door, back door, or both).

**Step 1: Exact matching (rule-based).**

- **Datasheet filename check first.** If a parts list row's Datasheet column names the drawing's original file, like `RecoaterArm.PDF`, that's a match. This covers about 4 drawings. If the same file is named on more than one row, as `RecoaterPlate.pdf` is (on "Recoater head" and "Recoater stage plate"), it is **not** auto-matched. It goes to step 2 with both rows marked as candidates.
- Then compare the drawing's original file name (from `manifest.json`) and its title to the names of custom parts in the parts list.
- Ignore capitals, spaces, underscores, and dashes, and split joined words, so `WindowFrame` matches "Window Frame."
- Count it as a match only if **exactly one** row matches. If zero or several match, send it to step 2.
- Expect only around 6 exact matches. That's fine.

**Step 2: Ask two different AI models, separately.**

- **Claude Code** (run with `claude -p`, its non-interactive mode) and **Codex CLI** (run with `codex exec`) each get the same prompt, one drawing at a time.
- Using two different models means they're less likely to make the same mistake.
- The prompt includes everything they need, so they don't have to go looking through files:
  - the drawing's file name, folder (section), title, material, and notes. Section names are compared only as written, since the mapping between the two sources' section names (A10) is built after matching;
  - whether the drawing is a clean drawing or a blurry scan;
  - the full list of 56 custom parts from the parts list, with their section and material.
- Both run in **read-only mode** so they can't edit any files.
- Each must reply with JSON only, with just two confidence levels, `sure` or `unsure`:

```json
{
  "bom_row": "Front Door",
  "confidence": "unsure",
  "other_candidates": ["Back Door"],
  "unsure_about": "File name 'Door_x2' could mean the front door, back door, or both",
  "reason": "Box section, aluminium, door-shaped part"
}
```

- Our code checks that `bom_row` and `other_candidates` actually exist in the parts list. If a model makes up a name, its answer counts as `unsure`.
- `bom_row` can be `null` if the model thinks there's no matching row.

**Step 3: Decide.**

| Claude Code | Codex | Result |
|---|---|---|
| sure, row X | sure, row X | **Matched.** Saved as `ai_agreed`. |
| sure, row X | sure, row Y | **Retry round** (below). If that doesn't produce a match, a human decides, labeled "AIs disagree." |
| unsure (either or both) | anything | **Human decides.** Labeled "AI unsure," with what it was unsure about. No retry. |
| invalid or no reply | anything | **Human decides.** Labeled "AI answer invalid." |

**Step 3b: One retry round, only when both are sure but disagree.**

This same retry round is used everywhere the two models work together: reading scans (A2), matching (here), labeling (A7), name mappings (A10), diagram labels (A12), and template filling (B5).

1. **Both models get the other's answer.** Each one sees the other model's answer and reason, worded neutrally: "Another reader answered Y, because [reason]. Keep your answer or change it." Neither is told the other is right.
2. **Each answers again, with evidence.** The second answer must point to the specific evidence: the number ID on the drawing, the parts list row, or the note. A model that changes its answer must also say what was wrong with its first one.
3. **Decide:**

| After the retry | Result |
|---|---|
| Both sure, same answer | **Used**, marked `ai_agreed_after_retry` |
| They swapped answers (both gave in) | Still a disagreement → **human decides** |
| Still different, or either is now unsure, or either answer is invalid | **Human decides** |

4. **Only one retry.** No loops.
5. **Both rounds are saved.** A reviewer can see each model's first answer, second answer, and reasons.

**Why both models get the feedback:** if both simply give in, they swap answers and still disagree, so a fake agreement can't come from both caving. The case that does need care is when one model holds and the other switches. That's usually the retry working (one model had misread something), but it could also be one model just caving. That's why the second answer needs evidence. The result gets its own label, `ai_agreed_after_retry`, so a reviewer can see a retry happened. It's trusted the same as independent agreement: both are AI interpretations, marked "not reviewed" until a person checks them (A8).

**Why unsure answers skip the retry:** a model that wasn't sure in the first place is the most likely to copy whatever it's shown.

**Step 4: Human review.**

- Unsure links go to the review page's "Needs human input" tab (B6).
- For each one, the screen shows:
  - the drawing image, with a link to open the full drawing;
  - the candidate parts list rows side by side, with links to each row;
  - both AI answers with their reasons;
  - the label for why it's here, and the specific thing each AI was unsure about.
- The human picks a row or "no match." The app saves the decision, who made it, and when.
- Until a human decides, the link stays `unresolved`. The chat shows the link as Undetermined ("This drawing isn't linked to a parts list row yet"), with a "Waiting for review" link to the item (A8).

**What gets saved** (`links.json`):

```json
{
  "drawing": "D-027",
  "bom_row": "Build cylinder clamp ring",
  "method": "ai_agreed",
  "claude_code": {"bom_row": "Build cylinder clamp ring", "confidence": "sure", "reason": "'Cylinder Spænd Ring' is Danish for cylinder clamp ring"},
  "codex": {"bom_row": "Build cylinder clamp ring", "confidence": "sure", "reason": "Spænd = clamp; Z-axis drawing, Build-plate family, aluminium"},
  "human_decision": null
}
```

Human link decisions are stored in `decisions/` (A9) and merged in when `links.json` is built, so they survive rebuilds and reruns.

`method` is one of `exact_match`, `ai_agreed`, `human_decision`, or `unresolved` (the same labels used everywhere, see A8). The chat shows this, so a user knows how each link was made.

**Rules that keep this reliable:**

- **Run once, save the results.** Matching is part of the setup loader, but only reruns when a drawing or the parts list changes, not on every launch. This keeps answers the same every time and avoids repeat costs.
- **The app doesn't need Claude Code or Codex to run.** The saved `links.json` ships with the submission. The two tools are only needed to redo the matching from scratch.
- **Agreement isn't proof.** Two models agreeing means the answer is consistent, not guaranteed correct. So Jason checks the `ai_agreed` links with Confirm and Reject (B6), and the write-up reports how many were confirmed and how many rejected.

**Section and material names** are a separate matching problem, handled in A10.

### A5. Connections between parts

- Split the "Interface with" column by commas into "A connects to B" links.
- Match those names back to parts list rows.
- Record that only 9 rows have this info.
- Connections stated in the section diagrams' labels are added too, as AI interpretations that cite the diagram (A12).
- For any part with neither, the chat says "no connections recorded."

### A6. How parts are saved: one record per part

After matching (A4), the setup loader builds **one record per part**. Each record has a **drawing section** and a **parts list section** side by side, and every field remembers where it came from.

Example:

```json
{
  "part_id": "D-026/part",
  "link": {"method": "exact_match", "drawing": "D-026", "bom_rows": ["BOM:build-plate/build-plate"]},

  "drawing": {
    "id": "D-026",
    "source_quality": "clean",
    "page_image": "images/D-026.png",
    "fields": {
      "title":    {"fact_id": "F-0610", "value": "Build Plate", "page": 1, "location": [612, 780, 140, 14], "confidence": "sure"},
      "material": {"fact_id": "F-0611", "value": "AISI 316 Stainless Steel Sheet", "page": 1, "location": [...], "confidence": "unsure",
                   "note": "printed on top of the weight label, so the extracted text is garbled (A1)"},
      "notes":    {"fact_id": "F-0612", "value": "Byggeplade, rustfri og alu. 1-3 stk af hver.", "page": 1, "location": [...], "confidence": "sure"},
      "weight_g": {"fact_id": "F-0613", "value": 7822.5, "page": 1, "location": [...], "confidence": "sure"}
    }
  },

  "bom": [
    {
      "row": "BOM:build-plate/build-plate",
      "display_id": "BOM-046",
      "fields": {
        "name":       {"fact_id": "F-1201", "original": "Build Plate"},
        "material":   {"fact_id": "F-1202", "original": "Stainless steel,Steel", "value": ["Stainless steel", "Steel"]},
        "supplier":   {"fact_id": "F-1203", "original": "DTU", "note": "recorded in snapshot, may be out of date"},
        "total_cost": {"fact_id": "F-1204", "original": "DKK0.00", "value": null,
                       "cleanup": ["zero_total_with_blank_cost → not recorded"], "note": "recorded in snapshot, may be out of date"}
      }
    }
  ]
}
```

**The rules:**

1. **Two sections, never mixed.** The drawing and the parts list can both have a field with the same name, like `material`, and they may disagree. Each source keeps its own value in the record. There is no single merged `material` field **stored**. What the chat **shows** is one value per field, worked out from both sources at answer time (B3, "One value per field").

2. **Every field keeps its source.** Each field is a small object, not a bare value.
   - **Drawing fields** keep the value, page, location on the page (for highlighting), and confidence: `sure` or `unsure`. A field that couldn't be read has `"value": null, "confidence": "unsure"`.
   - **Parts list fields** keep the original text exactly as written, a cleaned version where useful (like prices as numbers), and the row ID.
   - Every field has a `fact_id`, its stable name (A9), so a correction or citation can point at exactly one field. (The `F-xxxx` IDs in this plan's examples are shorthand for those names.)

3. **Not every part has both sides.**
   - Most parts list rows (bought parts like screws and motors) have no drawing, so `drawing` is `null`.
   - Unresolved drawings have no parts list row yet, so `bom` is an empty list.
   - One drawing can link to more than one row. That's why `bom` is a list. For example, `Door_x2` might cover both the front door and the back door.
   - The code must never assume a record has both halves.

4. **Records are never edited after they're built.** Accepted corrections and every other human decision are saved in `decisions/` (A9), and the setup loader applies them on top. The original extracted values always stay in the record, so they can always be shown.

5. **Records are rebuilt only by the setup loader**, from the source files, `links.json`, and the human decisions (A9). Nothing in the app writes to them directly; the app saves decisions, and the loader applies them.

6. **Every field says how it was made** with a `method` label (A8).

### A7. Dimensions and notes: what the drawings can and can't tell us

**The problem:** pulling text out of a PDF gives every number and its spot on the page, but not its meaning. We get "82,0" at a certain position, but not "82 mm is the spacing between two holes." We also can't tell which feature a note or arrow points to.

**The decision:** three layers. Pull out what can be read reliably (level 1). For parts with 3D models, have two AI models fill in the part's template, with a person answering anything they're unsure about (level 2). For all other drawings, have the same two models label what the numbers and notes mean (level 3). Anything still unlabeled gets an honest "I can't tell" from the chat.

**Level 1, all drawings:**

- **Title box fields** (from A1).
- **Hole and thread callouts.** These describe themselves, so no arrow-following is needed. For example, on D-013:
  - `4 x 5,5 X 10,0 THRU ALL` → 4 slots, 5.5 mm wide and 10 mm long, through. (Careful: here `X 10,0` is a slot length, not a depth. Depth uses its own symbol, as in D-026's `Ø 10,0 ↧ 15,4`. The pattern rules have to tell these apart.)
  - `8x 2,5 THRU ALL` with `M3 - 6H THRU ALL` → 8 threaded M3 holes
  - Simple pattern matching turns these into facts. Radius labels (`R1`) and chamfers (`x 90°`) work the same way.
- **Standard boilerplate** that's the same on every drawing (`DIN ISO 2768-1 m`, `DEBURR AND BREAK SHARP EDGES`, `DIMENSIONS ARE IN MILLIMETERS`) is handled by simple pattern matching too.
- **All other numbers and notes** are saved with their positions, but **without** saying what they mean. Levels 2 and 3 fill that in where they can.

These go into the part record's drawing section (A6) as extra lists:

```json
"callouts": [
  {"fact_id": "F-0620", "text": "4 x 5,5 X 10,0 THRU ALL", "feature": "slot", "count": 4, "width_mm": 5.5, "length_mm": 10.0, "through": true, "location": [...], "confidence": "sure"}
],
"dimension_numbers": [
  {"fact_id": "F-0630", "value": 270.0, "location": [...], "label": null},
  {"fact_id": "F-0631", "value": 82.0, "location": [...], "label": null}
],
"notes": [
  {"fact_id": "F-0640", "text": "M5 weld nuts on inside of flanges", "location": [...], "label": null}
]
```

**Level 2, parts with 3D models:**

- Their measurements come from the part's filled-in template (B5). Two AI models fill it in, and a person answers any field the models weren't both sure about.
- That same filled-in template also becomes facts the chat can use, for example: "length: 270 mm (AI-sourced only, not yet reviewed; may contain errors), from the dimension at this spot on D-013."
- Each value keeps its `method` (`ai_agreed`, `ai_agreed_after_retry`, or `human_decision`) and its location on the drawing.
- **Information flows one way:** drawing → filled-in template → both the chat facts and the 3D model. The chat never takes facts from the 3D model, and the two can't disagree because they come from the same file.

**Level 3, AI labels for all drawings:**

Runs in the setup loader, using the same Claude Code + Codex setup as matching (A4). Results are saved and only redone when a drawing changes.

- **The AI labels, it doesn't read.** Each model gets the page image plus the list of numbers and notes the parser already found, each with its ID and position. It can only attach labels to those IDs. It cannot add new numbers or notes. Our code throws out any label that uses an ID not on the list.
- **What it labels:**
  - for each number: what it measures (overall length, thickness, hole spacing, hole diameter, and so on), which view it's in (front, top, side, or a cut-away view like "Section A-A"), and whether it's a size or a tolerance;
  - for each note: which feature it points to (for example, "M5 weld nuts on inside of flanges" → the flanges);
  - for each hole callout, when there are several hole groups: which feature it belongs to.
- **Same agreement rule as matching, including the retry round (A4 step 3b).** A label is kept only if both models say `sure` and give the same label, either at first (`ai_agreed`) or after the retry (`ai_agreed_after_retry`). Otherwise it stays `null`.
- **No human review for unsure labels.** There may be hundreds of labels, and an empty label is already a safe answer. If a user cares about one, they can propose a fix through the normal correction feature (B6).
- **Notes are kept exactly as written.** The setup loader doesn't translate or rewrite them. The chat model can explain a note in the user's language at answer time, while still showing the original text.
- **Blurry scans are skipped.** Their main drawing area isn't read (A2), so there are no numbers to label.

A labeled number looks like:

```json
{"fact_id": "F-0630", "value": 270.0, "location": [...],
 "label": {"meaning": "overall length", "view": "top", "kind": "size", "method": "ai_agreed",
           "claude_code": "overall length, top view", "codex": "overall length, top view"}}
```

**Which source wins.** Each measurement fact says how it was made, and the chat says how much to trust it:

1. a person's answer (`human_decision`), or an AI value a person has reviewed and confirmed (`human_confirmed`);
2. an AI value not yet reviewed: `ai_agreed` or `ai_agreed_after_retry`, trusted the same. The chat says "AI-sourced only, not yet reviewed; may contain errors" (A8), and the badge mentions the retry when there was one;
3. no label, which falls back to "I can't tell."

**Accuracy test.** For the 3 required 3D parts, Jason checks every AI value against the drawing with Confirm and Reject (B6). The confirmed and rejected counts show how accurate the AI values are. There's no hand-made answer key.

**When the chat can't tell:** if a number has no label, a question like "how wide is it?" gets the value as **Undetermined** (B3), with the message "The drawing shows these measurements: 270, 82, 41, 25, but I can't tell which edge each one measures," and those numbers highlighted on the drawing. Hole callouts can still be answered directly.

### A8. Every value says how it was made: rule-based, AI, or human

Every fact, link, and label carries a `method` saying how it was produced. This lets a user tell **rule-based results** (same input, same output, every time) apart from **AI interpretations**, and lets a human review any AI interpretation, even ones both models were sure about.

**The labels:**

| `method` | Kind | Meaning |
|---|---|---|
| `parsed` | Rule-based | Text read directly from a clean PDF, the spreadsheet, or the README |
| `cleanup_rule` | Rule-based | Changed by a parts list cleanup rule (A3); the rule is named |
| `exact_match` | Rule-based | Linked or mapped by exact name or datasheet filename (A4 step 1, A10) |
| `ai_read` | **AI** | Read from a blurry scan's corner box by both AI models, who agreed (A2). Reviewable like any AI item |
| `ai_agreed` | **AI** | Both Claude Code and Codex were sure and agreed independently (A4, A7, A10, A12, B5) |
| `ai_agreed_after_retry` | **AI** | Both were sure but disagreed, then agreed after seeing each other's answer once (A4 step 3b). Trusted the same as `ai_agreed`; the separate label just shows a retry happened |
| `human_decision` | Human | A person picked or entered this on the review page (A4 step 4, B5, B6) |
| `unresolved` | None | No trusted answer yet |

**AI items also carry a review status:**

```json
"review": {"status": "not_reviewed", "by": null, "at": null}
```

- `not_reviewed` is the default for **every** AI item, whether it's `ai_agreed` or `ai_agreed_after_retry`, and even when both models were sure. It stays "AI-generated" until a person approves it.
- `human_confirmed` means a person checked it and agreed. It's then shown as **reviewed**, with who and when.
- `human_rejected` means a person said it was wrong. The AI answer stays in the history, the item falls back to `unresolved` (or to the person's fix, through B6), and nothing is deleted.

**Every kind of AI item can be reviewed:** scan readings (A2), links (A4), labels (A7), diagram label readings (A12), 3D template fields (B5), and whole 3D parts. (Name mappings, A10, go further: each one must be approved before it's used.) Reviews are human decisions, so they're saved in `decisions/` (A9). They survive rebuilds, ship with the app, and only come back for review if the evidence they were based on changes.

**How it shows up in the app:**

- **A small badge** next to every fact in chat answers and part pages: "From PDF," "From parts list (cleaned)," "From README," "AI reading of a blurry scan, not reviewed," "AI interpretation, not reviewed," "AI interpretation (agreed after a second look), not reviewed," "AI interpretation, reviewed by [name] on [date]," or "Entered by [name] on [date]."
- **Chat wording follows the badge.** AI items are always described as AI interpretations, for example: "AI labels say 270 mm is the overall length (AI-sourced only, not yet reviewed; may contain errors)." Once reviewed: "270 mm is the overall length (AI interpretation, reviewed by [name] on [date])."
- **What the chat says about review** depends on the item:

| The value is... | The chat says |
|---|---|
| **AI-only, passed every check, not reviewed** | "AI-sourced only, not yet reviewed; may contain errors." No review link, since nothing is waiting. |
| **Undetermined, and a review item exists** (unresolved link, 3D field waiting for input, name mapping waiting for approval, pending correction) | "Waiting for review," linking straight to that item on the review page (B8, Links). |
| **Undetermined, with no review item** (unreadable scan field (A2), unlabeled measurement (A7), unmatched diagram label (A12), unsure value on a clean drawing (A1), real conflict between sources) | Only the Undetermined message. No "waiting for review," because nothing is in the review queue. A user can still propose a value through the correction feature (B6). |
| **Reviewed** | "Reviewed by [name] on [date]." |
- **Highlights on the drawing** use a different color for AI-labeled numbers than for plain parsed text.
- **Anything that couldn't be determined** still shows its source, the part, drawing, or parts list row it belongs to. Only its **value** is replaced by the "Undetermined" tag (B3).
- **The review page has an "AI interpretations" tab** (B6) listing every AI item, with filters for drawing, type, method, review status, and weight check result.

### A9. Human decisions are saved separately and ship with the app

**Why:** an engineer's approvals have to survive rebuilds, AI reruns, and shipping. When the app goes to a customer, they should never have to re-approve what an engineer already approved.

**Who the reviewer is.** For now, there's no login. The reviewer's name is set in the app's settings file, `reviewer_name: Jason Peng`, and every human decision is saved under that name. Changing reviewers means changing that one line.

**Two kinds of saved data:**

| Kind | Examples | Can it be deleted and rebuilt? |
|---|---|---|
| **Generated** | Parsed facts, cleaned parts list, AI answers, built 3D models, the SQLite database | Yes. The setup loader can recreate all of it. |
| **Human decisions** | Link decisions (A4), name mapping approvals (A10), answers to unsure template fields (B5), chosen examples for `options`, AI confirmations and rejections (A8), "Approve whole design" and its notes (B6), accepted or rejected corrections (B6) | **Never.** Only added to. |

**Where they live:** a `decisions/` folder of plain JSON files, one per drawing or part, each holding that item's decisions in order. Plain files are easy to ship, keep in version control, and read in a diff.

Each decision records what it applies to, what was decided, who decided it, when, and **what evidence it was based on**:

```json
{
  "decision_id": "HD-0042",
  "applies_to": "D-013/template/thickness",
  "type": "choose_option",
  "value": 6.0,
  "based_on": {
    "drawing_sha256": "f89be461b6...",
    "ai_answers": {"claude_code": "options: 6.0 or 3.0", "codex": "options: 6.0 or 3.0"}
  },
  "by": "Jason Peng",
  "at": "2026-11-10T14:02:00Z",
  "note": "Matches the weight check better"
}
```

**Rules:**

1. **Applied on every rebuild.** The setup loader rebuilds all generated data, then applies the decisions on top. Deleting the database never loses a decision.
2. **AI never overwrites a person.** Rerunning the models, for example with a newer model or a better prompt, only fills fields that have no human decision.
3. **Stable names, not running numbers.** Decisions, citations, and links point to things by names built from what they describe. These stay the same across rebuilds. (The `F-0611`-style IDs in examples elsewhere in this plan are shorthand for these names.) The forms:

   | Thing | Stable name |
   |---|---|
   | A drawing fact | `D-013/drawing/material` |
   | A 3D template field | `D-013/template/thickness` |
   | A part with a drawing, as a whole | `D-013/part` |
   | A parts list row's fact | `BOM:<section>/<name>/<field>`, like `BOM:recoater/recoater-arm/material` |
   | A parts-list-only part, as a whole | `BOM:<section>/<name>/part`, like `BOM:electric/12v-psu/part` |
   | A README passage | `README/<section>/p<n>`, like `README/physical-system/p1` |
   | A diagram | `DIAGRAM/<name>`, like `DIAGRAM/zaxis` |
   | A name mapping | `names/<kind>/<name> -> <name>`, like `names/material/EN-AW 5005 -> Aluminium` |

   Names are lowercased with spaces turned into dashes. Parts list rows are named by their section and part name, not their row position, because row order can change between spreadsheet exports. If two rows share a section and name, they're flagged. The `BOM-046` style is only a display ID.
4. **Only changed evidence needs re-approval.** Each decision saves a fingerprint of the drawing or parts list row it was based on (the sha256 from `manifest.json`, or a hash of the row). On rebuild:
   - fingerprint unchanged → the decision still applies, no action needed;
   - fingerprint changed → the decision is kept in the history but marked "source changed since approval." Only that item goes back to "Needs human input," pre-filled with the old answer, so re-approving is one click.

   So after an update, a reviewer only looks at what actually changed.
5. **Nothing is deleted.** A later decision on the same item is added after the earlier one. The latest one is used, and the full history stays visible.
6. **Shipped with the app.** `decisions/` is part of the submission and of anything shipped to a customer. The customer's app shows labels like "reviewed by [engineer] on [date]" without asking them to do anything. A customer can still override anything through the same review page, which adds a new decision on top.

### A10. Same thing, different names: sections and materials

**The problem.** The drawings and the parts list often use different names for the same thing:

| Kind | Drawing says | Parts list says |
|---|---|---|
| Section | Optical | Optics |
| Section | Gas Flow | Gas flow |
| Section | Z-axis | Build-plate (likely; to be confirmed) |
| Material | 3.3315 (EN-AW 5005), 6061 Alloy, 6063-T6, 7075-T6, Plate (SS) | Aluminium |
| Material | AISI 316 Stainless Steel Sheet | Stainless steel |
| Material | Silicon Rubber | Silicone |

Some parts list sections (Electric, SensorGantry, Support, Raw Materials) have no drawing section at all.

**The approach: the same pipeline as part names (A4), with three changes.** Exact matching first (ignoring capitals, spaces, and dashes), then Claude Code and Codex with the retry round (A4 step 3b), then a person. Results get the same labels (A8), the same review page (B6), and the same `decisions/` storage (A9), and they ship with the app.

**Change 1: names are matched once, not part by part.** Each distinct pair of names is matched one time, like "EN-AW 5005" ↔ "Aluminium." That one decision then applies to every part that uses those names. There are only about 15 pairs in this dataset, so this is very little work.

- Because one wrong mapping would spread to every part using it, **a person approves every name mapping**, even when both AI models agree. Until a mapping is approved, it isn't used: if the two sources' names differ, the value shows as Undetermined, with the message "These names haven't been mapped yet."

**Change 2: each mapping has a relationship, not just "match" or "no match."**

| Relationship | Example | What the chat shows |
|---|---|---|
| `same` | "Silicon Rubber" = "Silicone"; "Optical" = "Optics" | One value, citing both sources |
| `kind_of` | "EN-AW 5005" is a kind of "Aluminium" | The **more specific** value, like "EN-AW 5005 aluminium," citing both sources |
| `different` | "7075-T6" vs. "Stainless steel" | A real conflict: **Undetermined**, with both values on hover |
| `no_equivalent` | Parts list section "Electric" has no drawing section | Nothing to compare; the one that exists is shown |

`kind_of` also makes searches work in both directions:

- "Which parts are aluminium?" includes parts recorded as EN-AW 5005, 6061, 6063, or 7075, because each is a kind of aluminium.
- "Which parts are EN-AW 5005?" only includes parts where a source actually says EN-AW 5005. A part recorded only as "Aluminium" isn't included, because it could be any aluminium.

**Change 3: the evidence comes from different places.**

- **Sections can mostly be worked out from the data.** After drawings are linked to parts list rows (A4), the loader counts which parts list section the linked rows belong to, for each drawing section. For example, if all the Z-axis drawings link to Build-plate rows, that's strong, rule-based evidence that they're the same section. The AI models and a person then confirm it. This is why the section mapping runs **after** matching.
- **Materials can't be worked out from the data.** Nothing in the files says EN-AW 5005 is an aluminium. That's general engineering knowledge. The AI models may use it, but each material mapping is labeled **"based on general engineering knowledge, not the dataset,"** and a person approves it.

A saved mapping looks like:

```json
{
  "applies_to": "names/material/EN-AW 5005 -> Aluminium",
  "relationship": "kind_of",
  "evidence": "general engineering knowledge, not the dataset",
  "claude_code": {"relationship": "kind_of", "confidence": "sure", "reason": "EN-AW 5005 is an aluminium-magnesium alloy"},
  "codex": {"relationship": "kind_of", "confidence": "sure", "reason": "5005 is a 5xxx-series aluminium alloy"},
  "review": {"status": "human_confirmed", "by": "Jason Peng", "at": "..."}
}
```

**New names.** A name that appears later, for example in a new drawing, has no mapping yet. Until one is approved, any difference involving it shows as Undetermined ("These names haven't been mapped yet").

### A11. The machine's README as a citable source

**What it is.** `openlpbf-upstream-readme.md` is the original project's README, about 1,500 words. It's mostly background on the project, plus a few hard facts about the machine, for example a 250 × 150 mm build volume, a 300 W laser, closed-loop gas flow, and a safety system with emergency stops, door interlocks, and a safety controller. It doesn't list the machine's six sections.

**How it's read (rule-based, every launch).**

- **Split by headings** into sections (Project Impetus, Physical System, Safety, CAD, and so on), then each section into paragraphs.
- **Each paragraph gets a stable name**, like `README/physical-system/p1`, so answers can cite the exact passage (A9).
- **HTML tags are stripped**, like the `<p align="center">` wrappers around images.
- Every passage is marked `method: parsed` (A8), with the badge **"From README."**

**Two things the README mentions that aren't in this dataset:**

1. **Images.** The README links several images, like a cost chart, a system architecture picture, and exploded views, that weren't included. Each one is replaced with a placeholder, like "[Image not included in this dataset: Cost distribution]," and the chat never describes those images.
2. **Native CAD files.** The README says the original project includes the full native SolidWorks assembly and a STEP assembly. Those weren't included here. That passage is flagged "mentions files not in this dataset," and whenever the chat cites it, it says those files aren't available.

**How the chat uses it.**

- A new tool, `search_readme(text)`, returns matching passages with their stable names (B1).
- README facts are about the whole machine, not one part, so citing one doesn't open a drawing (B2). It's still a valid citation.
- **Clicking a README citation** opens a simple **README page** that shows the README with the cited passage highlighted. This page is required, since README citations need somewhere to open. The rest of the files page (B7) stays optional.
- The README describes the original project **as of this snapshot**. Answers about the project, like its versions or plans, say so.

### A12. The system diagrams

**What they are.** Six images in `dataset/context/diagrams/`. Three are useful labeled exploded views of one section each: **Powder** (`PowderLegend.png`), **Recoater** (`RecoaterLegend.png`), and **Z-axis** (`Zaxis_legend.png`). The other three show the safety logic (`SafetyOPM.png`), how this kind of printer works in general (`SimpleDiagram.png`), and an abstract systems picture (`SystemLevels.png`).

**All six are viewable and citable as whole images.**

- Each gets a stable name, like `DIAGRAM/zaxis`, and its own page under Files (B8), shown **on a white background**, since the images have see-through backgrounds and the black labels disappear otherwise.
- Citing a diagram doesn't open a part (B2). Clicking the citation opens the diagram's page.
- The diagrams are **never used for 3D**. They're illustrations, not to scale, with no measurements.

**The three section diagrams have their labels read (text only).**

- **No positions.** Labels are only used for their text, never their spot on the picture, so there's no OCR, no highlighting, and no cropping on diagrams.
- **The two AI models read them**, with the usual agreement and retry rules (A4). For each of the roughly 30 labels, they give:
  - the label text, exactly as printed;
  - which part it means, chosen from the part records (A6), like part-name matching (A4);
  - any connection phrase in it, like "attach to main platform."
- **Agreed labels** are marked `ai_agreed` (or `ai_agreed_after_retry`). They're AI interpretations, "not reviewed" until a person confirms them on the review page (B6).
- **Labels they don't agree on are left unmatched**, with no review item, like unlabeled measurements (A7). The diagram is still viewable and citable.

**What the readings feed:**

1. **Connections.** The parts list only records connections for 9 Box parts. Connection phrases become connection facts that cite the diagram, for example "the cylinder clamp ring attaches to the main platform [Z-axis diagram]." `get_connections` returns them (B1).
2. **The "Installed in" panel** on the part page (B5). It shows the part's section diagram, whole, with the matching label's text listed next to it.
3. **Section answers.** "What's in the recoater?" can cite the recoater diagram alongside the parts list.
4. **Extra evidence for the section mappings** (A10). For example, the Z-axis diagram labels exactly the parts the parts list files under "Build-plate," supporting "Z-axis = Build-plate."

---

## Half B: the app

### B1. Chat

The AI does **not** get the PDFs. It gets a few tools it's allowed to call:

- `find_part(text)` returns matching parts.
- `get_facts(part_id)` returns all facts for a part, each already resolved to one display value (see "What the tools return" below).
- `get_bom_row(row_id)`
- `parts_with_material(material)`, which follows the `kind_of` rules in A10
- `parts_in_section(section)`
- `get_connections(part_id)`
- `search_readme(text)` returns matching README passages with their stable names (A11)
- `get_diagram(name)` returns a diagram and its agreed label readings (A12)
- `propose_correction(fact_id, new_value, reason)`, which only creates a pending suggestion (B6)

The AI picks which tools to call, reads what comes back, and writes a final answer that cites its sources. It **only puts the tools' results into words**. It never decides which source wins, what a value is, or whether something is undetermined. Code does that (below).

#### What the tools return (the display rules live in code)

The "one value per field" rules (B3), the Undetermined decisions, and the "may be out of date" notes are all applied **in `tools.py`, by plain code**, before anything reaches the chat model. If the chat model applied them itself, its answers would be inconsistent from one question to the next.

So every fact a tool returns already carries its final display:

```json
{
  "fact": "D-013/drawing/material",
  "display": {"state": "value", "value": "EN-AW 5005 aluminium"},
  "rule": "kind_of (A10): drawing is more specific than parts list",
  "badge": "From PDF",
  "review": {"status": "not_reviewed"},
  "sources": [
    {"name": "D-013/drawing/material", "says": "3.3315 (EN-AW 5005)", "method": "parsed"},
    {"name": "BOM:recoater/<linked-row>/material", "says": "Aluminium", "method": "parsed"}
  ],
  "snapshot_note": false,
  "review_item": null
}
```

An undetermined fact looks the same, but its display says so, with the reason and message already written by code:

```json
{
  "fact": "D-009/drawing/weight_g",
  "display": {"state": "undetermined", "reason": "unreadable_scan",
              "message": "Too blurry to read on the scan."},
  "sources": [{"name": "D-009/drawing/weight_g", "says": null, "method": "ai_read",
               "note": "the two models didn't agree on a reading"}],
  "review_item": null
}
```

- `display.state` is `value`, `options` (two or more values printed on the drawing, B5), or `undetermined`.
- `review_item` holds the review page link when one exists (A8), so the "Waiting for review" link comes from code too.
- The chat model's instructions say: use `display` exactly as given, cite `sources`, and never invent or choose values.

#### The chat's output markers

The chat model's final answer uses **two kinds of markers**, so code can read them. The app never shows them raw.

**1. Citations: `[cite: ...]`.** Each claim is followed by a marker holding the stable names (A9) of the facts it came from. One marker can hold several names, separated by commas:

> The recoater plate is made of EN-AW 5005 aluminium [cite: D-013/drawing/material, BOM:recoater/<linked-row>/material].

**2. Undetermined values: `[undetermined: ...]`.** When a tool returned a fact as undetermined, the model writes this marker **where the value would go**, holding that fact's stable name:

> The powder canister's weight is [undetermined: D-009/drawing/weight_g].

(The D-009 examples are illustrative; whether that field is readable will only be known after the scans are read.)

- The frontend replaces it with the **Undetermined tag**. The tag's message comes from the tool result in the database, not from the model's wording, so it's always the right one.
- The marker **also counts as a citation** of that fact. The app shows the fact's source tag after the sentence and opens its part (B2), so the model doesn't need a separate `[cite: ...]` for it.
- Checks, done by the parser (B2):
  - the fact must exist and must have been returned by a tool in this conversation;
  - the tool must actually have returned it as undetermined. A marker on a fact that has a trusted value is shown as an invalid marker, with a warning on the answer;
  - the other way around: if the answer cites an undetermined fact but gives it a value instead of the marker, the answer gets a warning ("This answer states a value for something the sources couldn't determine").

**How citations look (like Perplexity or ChatGPT).** The app never shows the raw `[cite: ...]` markers. Instead:

- **An inline source tag** sits right after the sentence or claim it supports, in the text. It's a small rounded label with a short source name, like **D-013** or **Parts list**. When a claim has more than one source, the tag shows the first and a count, like **D-013 +1**.
- **Hovering over the tag shows a details card** with, for each source:
  - the source name and where in it, like "Drawing D-013, corner box," "Parts list row: Recoater Arm," "README, Physical System," or "Z-axis diagram";
  - what that source says, word for word;
  - a small cropped image of the spot on the drawing, for drawing sources;
  - the source badge (A8), like "From PDF" or "AI interpretation, not reviewed";
  - the "recorded in the snapshot, may be out of date" note, for supplier, price, order number, and link facts.
- **Clicking the tag opens the source.** A drawing source opens the drawing with that spot highlighted. A parts list source opens the part page's Detail tab with the row card (B5). A whole-part citation opens the part page. A README source opens the README page at that passage (A11). A diagram source opens the diagram's page (A12). When a tag has several sources, clicking it opens the first, and the details card has a separate link for each one.
- **On phones and tablets,** which have no hover, the first tap opens the details card and the links inside it open the sources.
- **Invalid citations** (B2) show as a tag in a warning style, with the reason in the details card.
- **The Undetermined tag** (B3) is separate. It sits where the value would be, not after the sentence, and the source tag after the sentence still points to where the value would have come from.

Example as shown to the user:

> The recoater plate is made of EN-AW 5005 aluminium **[D-013 +1]**. It has 8 M3 threaded holes **[D-013]**.

Hovering over **[D-013 +1]** shows the drawing's corner box ("MATERIAL: 3.3315 (EN-AW 5005)"), the linked parts list row ("Material: Aluminium"), and both badges.

**Every part can be cited as a whole, not just its facts.** Each part has a citable entry for itself, like `[cite: D-023/part]` for a part with a drawing or `[cite: BOM:electric/12v-psu/part]` for a parts-list-only part. **When a question is about a specific part, the answer always cites that part, even when the answer is "I don't know"** or "no supplier is recorded." That way the part's drawing still opens (B2), which requirement 3 needs.

#### How the tools are built

- **A plain Python module** (`tools.py`). Each tool is a normal function, plus a short description of its inputs that's sent to the AI model. The chat backend calls these functions directly, in the same program. Nothing extra to run.
- **Read and propose only.** No chat tool can approve, reject, or decide anything. Approvals happen only on the review page (B6), so the AI can never approve its own work.
- **The setup loader's scripts are separate.** Parsing, cleanup, matching, template filling, and model building (Half A) are command-line Python scripts that run ahead of time. They aren't chat tools.

#### Deferred: an MCP server

**Status: explicitly deferred. Not part of this submission, including the bonus list.**

The idea, kept here for later: a thin MCP server could wrap the same functions from `tools.py`, so an engineer could query this machine from their own AI tool (like Claude Desktop or Claude Code). If it's ever built:

- it wraps `tools.py` directly, with no separate copy of the logic;
- it exposes reading and `propose_correction` only, never approving or deciding;
- parts in its results include links that open them in the app, since the drawing and 3D viewer only exist in the app.

The write-up will mention it as a possible next step.

### B2. Chat attaches the drawing and 3D automatically

**Our code, not the AI, decides what to show.** After the AI writes its final answer, a **parser** reads its citation and Undetermined markers (B1), works out which parts they belong to, and attaches those parts' drawings and 3D models to the reply. This way, requirement 3 never depends on the AI remembering to show anything.

**Why the final answer's citations, and not every tool result:** while answering, the AI often looks at parts it doesn't end up talking about. For example, `find_part("recoater plate")` might return 3 candidates before the AI picks one. Using the citations shows only the parts the answer is actually about.

**How the parser works:**

1. **Pull out every marker** from the final answer: `[cite: ...]` and `[undetermined: ...]` (B1). An Undetermined marker counts as a citation of its fact.
2. **Check each one is real.** The cited fact must exist in the database and must have been returned by a tool during this conversation. An undetermined fact counts as a real fact: it exists, it just has no trusted value, so citing it is valid and its part is shown. A citation that fails either check is shown as "invalid citation" and is listed in the answer's warning (step 6). This stops the AI from citing facts it never actually looked up. Undetermined markers get the extra checks listed in B1.
3. **Map each fact to its part.** Stable names start with the drawing or row they belong to, so this is a simple lookup:
   - a drawing fact (`D-013/...`) → part D-013;
   - a parts list fact (`BOM:...`) → that row's part. If the row is linked to a drawing (A4), that drawing is shown. If it has no drawing, a parts list card is shown instead. If the link is `unresolved`, the card says so.
   - a whole-part citation (`D-023/part`, `BOM:.../part`) → that part.
   - a README citation (`README/...`) → no part. It's valid but doesn't open a drawing (A11).
   - a diagram citation (`DIAGRAM/...`) → no part. It's valid, and clicking it opens the diagram's page (A12).
4. **Remove duplicates**, keeping parts in the order they're first cited.
5. **Decide what to show:**

| Cited parts | What the reply shows |
|---|---|
| 1 to 3 | Each part gets an **attached part card** in the message: the part name, a small thumbnail of its drawing, and "Open drawing" and "Open 3D" buttons (3D only if it has a model). Clicking opens the **side panel** (below), with the cited spots highlighted. A part with `options` opens on its reviewer-chosen example, or Example A if none was chosen, with the switch visible. |
| 4 or more | A compact list of part cards, each with "Open drawing" and "Open 3D" buttons. Clicking a card opens the side panel (below). |

6. **Flag uncited answers.** If an answer makes claims about the machine but has no valid citations, the app shows a warning on it, like "This answer has no cited sources," instead of silently showing nothing. Plain replies like "Which part do you mean?" don't need citations.
7. **Backup rule, in case the AI forgets to cite the part.** If `find_part` found **exactly one** part during this turn, and the final answer cites no part at all, the app shows that part anyway, marked "Shown because your question named this part." When `find_part` returned several candidates, this rule doesn't apply, and the citations decide what's shown, as above.

**The side panel.** Drawings and 3D never open inside the chat message itself. The message only carries the attached part cards. Clicking a card, or a citation tag (B1), opens a **side panel next to the chat** showing the part page (B5): 3D, 2D, Detail, and History tabs. The chat stays visible beside it. The drawing thumbnail on each card is what makes the drawing "attached" to the answer, which requirement 3 asks for.

### B3. "I don't know" rules

- If a fact is unreadable or `unsure`, it shows as **Undetermined** (below).
- If a question asks what a measurement means and no AI-agreed or human-entered value exists for it, the answer lists the numbers shown on the drawing, says it can't tell which edge each one measures, and highlights them on the drawing (A7).
- Every fact in an answer shows its `method` badge (A8). AI interpretations are always described as AI interpretations, and say whether a human has reviewed them.
- If the drawing and the parts list really conflict, the value shows as **Undetermined**, with both values in its message (see "One value per field" below).
- If a field has `options` (B5), the answer gives both values as the drawing shows them and points to the example switch in the 3D view. This is **not** shown as Undetermined (see below), because both values are known. If a field is `unknown`, the answer says so and never offers a guess.
- If nothing is found, the answer says there's no evidence instead of making something up.
- Supplier, price, and availability answers always include "as recorded in the snapshot, may be out of date."

#### One value per field

The record stores both sources side by side (A6), but the chat and the part page **show one value per field**, so a user isn't given two of everything. **These rules are applied by code in `tools.py` (B1), never by the chat model.** The value is worked out like this:

0. **Only trusted values take part.** A value that's `unsure` (for example garbled or a placeholder, A1) or unreadable counts as missing here. It's still shown word for word in the citation's hover card.
1. **Only one source has the field** (most fields): show that value. Supplier, price, and status come from the parts list. Weight, dimensions, and notes come from the drawing.
2. **Both sources say the same thing**, or the names are mapped as `same` (A10): show one value, citing both sources.
3. **One is a kind of the other** (`kind_of`, A10): show the more specific value, like "EN-AW 5005 aluminium," citing both sources.
4. **They really conflict** (`different`, A10), or the names **haven't been mapped yet:** show the Undetermined tag in place of the value. Its message gives both values, word for word.
5. **The parts list cell lists several materials**, like "Steel,Elastomer" (5 rows in this dataset). The spreadsheet doesn't say what a list means. In these rows it's sometimes one bought item made of several materials (a timing belt, a blower), sometimes different versions of a part (the build plate), and sometimes unclear. So:
   - **Show the list as written, labeled "Materials recorded:"**, for example "Materials recorded: Steel, Elastomer." Never say "made of" or "versions," since the data doesn't say which.
   - **If the part also has a trusted drawing material,** it's **compatible** when the drawing's material is the same as, or a kind of, **one** item in the list. That item is then shown with the drawing's more specific name, citing both sources. For example, if a drawing said "AISI 316 Stainless Steel Sheet" and its row said "Stainless steel,Steel," the chat would show "Materials recorded: AISI 316 stainless steel, Steel." (D-026 itself is like this, but its drawing material is garbled and `unsure`, so rule 0 applies and it shows "Materials recorded: Stainless steel, Steel" from the parts list, with the garbled drawing text in the hover card.)
   - **If the drawing's material matches none of the items,** it's a real conflict: Undetermined, with the drawing's material and the full list in its message.
   - **Searches** count the part under each listed material. "Which parts use steel?" includes it, worded as "recorded with steel," not "made of steel."

The citation's hover card (B1) always shows what each source said word for word, so nothing is hidden.

**Known limit:** notes are not compared automatically. For example, D-026's note mentions both stainless steel and aluminium, but only its material field is compared with the parts list. The note is still shown in the part's Detail tab.

#### The "Undetermined" tag

When the app can't give a trusted value for something, it shows **one tag, "Undetermined,"** in place of the value. Hovering over it, clicking it, or tapping it (phones and tablets have no hover) shows a message explaining why.

**Undetermined is about the value, not the source.** Every undetermined fact still belongs to a specific part, and comes from a specific drawing (often a specific spot on it) or parts list row. So it keeps everything else a normal fact has:

- **its source:** which part, which drawing or parts list row, and where on the page;
- **its citation:** the answer still cites it, so the citation parser (B2) still opens that part's drawing, with the relevant spot highlighted;
- **its link:** clicking the source opens the drawing or row, just like any other fact.

For example: "Thickness: **[Undetermined]** · source: drawing D-023, side view." The message explains that the number is too blurry to read on the scan, and clicking the source opens D-023 with that spot highlighted.

**Used for:**

| Situation | Example message |
|---|---|
| A value can't be read or isn't on the drawing | "This number is too blurry to read on the scan." |
| A value on a clean drawing is `unsure` and no other source has it | "The drawing's material is printed on top of the weight label, so it can't be read reliably." |
| We can't tell what a number measures | "The drawing shows 270, 82, 41, and 25, but I can't tell which edge each one measures." The numbers are also highlighted on the drawing. |
| The drawing and parts list really conflict (`different`, A10) | "Drawing: 7075-T6 (an aluminium). Parts list: Stainless steel." (illustrative) |
| The two sources use names that haven't been mapped yet (A10) | "Drawing: Silicon Rubber. Parts list: Silicone. These names haven't been mapped yet." |
| A drawing isn't linked to a parts list row | "This drawing isn't linked to a parts list row yet." |
| A field is waiting for a person | "Waiting for human input on: thickness." |

**Not used for:**

- **Two readings (`options`).** Both values are known and printed on the drawing. They're handled by the Example A / Example B switch in the 3D view (B5), and the chat states both values.
- **Unsupported 3D shapes.** That's a limit of the 3D viewer, not an uncertain fact. The 3D viewer shows its own message, like "No 3D model: bent sheet metal isn't supported."
- **Missing or invalid citations or markers.** Those get a warning on the whole answer (B1, B2).

**Rules:**

- **One tag, many messages.** The message is written by code (B1), not the chat model. It always says why, and where it can, what would resolve it, like "A reviewer can answer this on the review page."
- **In chat, the tag comes from the `[undetermined: ...]` marker** (B1). On part pages and in the 3D viewer, it comes straight from the database.
- **If the uncertainty is the main answer, say it in the text too.** When the user asks about a part's material and the answer is that the sources disagree, the reply includes one plain sentence saying so, plus the tag. A tag alone is fine when the uncertainty is a side detail in a longer answer.
- **Shown next to the source, not instead of it.** The tag sits where the value would be, and the source badge and link stay (A8). The tag looks different from source badges, so a user can tell "where this came from" apart from "we couldn't determine the value."
- **Shows up everywhere facts appear:** chat answers, part pages, numbers on the 2D drawing, and the field list in the 3D viewer.

### B4. 2D drawing view

- Shows the PNG of the drawing in the side panel next to the chat (B2), and on the part page, with zoom.
- Draws a box around the exact spot the cited fact came from, using the saved word positions.
- For the blurry scans, shows the scan next to what the two AI models read from its corner box, with each field's badge, and highlights the whole field box a cited fact came from (A2).

### B5. 3D view

**Approach:** build each 3D model ahead of time with CadQuery, from the part's filled-in template. Save two files per model, ship them with the app, and show the GLB in the browser with React Three Fiber (built on Three.js).

Why this way:

- CadQuery is made for building parts, so holes, pockets, and angled edges are easy.
- All the "turn files into data" work stays in one place, the setup loader.
- It shows clearly that the 3D shape came from the drawing's measurements.
- The built models are fixed files that can be checked and versioned, not shapes the browser recalculates every time.

#### Files for each model

| File | What it's for |
|---|---|
| `models/D-013_A.glb` | **Shown in the browser.** GLB is the format Three.js recommends: small, fast to load, and supports colors and named pieces. |
| `models/D-013_A_reconstruction_from_drawing.step` | **Download for real CAD programs**, so an engineer can open the reconstruction in their own CAD tool and check it. |
| `templates/D-013.json` | The filled-in template the model was built from (already the source of truth). |

- **One pair of files per example.** A part with `options` gets `D-013_A` and `D-013_B`, so switching examples just loads the other GLB.
- **Model color: neutral grey for every part.** The color never suggests a material, since the material can be Undetermined or a list. Only features get other colors (next point).
- **Named pieces in the GLB.** Each feature or feature group is its own named, colored piece, like "8 × M3 threaded holes." Hovering or clicking one shows its values, its `method` badge (A8), and highlights where it came from on the 2D drawing. Features that came from a person's answer can use a different color than `ai_agreed` ones.
- **The STEP download says what it is.** The file name includes `reconstruction_from_drawing`, the download button says "Download reconstruction (STEP). Not the original CAD model," and a short "reconstruction from drawing, not the original CAD model" note is written into the STEP file's description field where CadQuery allows it. (That's an honesty note about what the file is, not a license notice. License attribution lives only in `ATTRIBUTION.md`, per the write-up checklist.)

#### Built files ship with the app

- The finished GLB and STEP files are included in the submission, so **the app runs without CadQuery installed.** This removes CadQuery's large install from what a reviewer needs.
- The start command treats CadQuery as optional. If it's installed, the setup loader rebuilds any model whose template has changed. If not, the app uses the shipped files.
- **After a person answers a field on the review page:** the chat's facts update right away, since they come from the template. The 3D model is rebuilt right away if CadQuery is installed. If it isn't, the 3D view shows "Model out of date: rebuild needed. Showing the version from before this change," until the setup loader is run with CadQuery.

#### Shape templates

A **template** is a fill-in-the-blanks form for one kind of shape. A **filled-in template is the part's measurements file.** Templates are filled in by two AI models, with a person answering anything they're unsure about (see "How templates get filled" below). The builder code then turns the filled-in template into a 3D model.

**Flat part template** (all 3 required parts use this one). A flat part is a 2D outline pushed up to a thickness, with features cut into it. The fields follow standard CAD features, so anyone who has used CAD will recognize them.

**Outline**

- **shape:** rectangle, circle, ring, or obround (a rectangle with round ends, like a pill);
- **corners** (rectangles only): each corner is sharp, rounded (with a radius), or chamfered (cut at an angle, with a size);
- **thickness.**

**Edge treatments**

- **fillet** (rounded edge) or **chamfer** (angled edge) along the top or bottom edges, with a size and which edges.

**Features.** Every feature has:

- **`face`:** which side it's cut into: `top` or `bottom`, or a side face (`front`, `back`, `left`, or `right` on rectangles; `outer` or `inner` edge on round parts). Example: D-014 has some countersinks on the back face.
- **position:** measured from one fixed starting point, the lower-left corner for rectangles or the center for round parts. Drawings often measure from somewhere else, like a center line or another hole. When that happens, the value is converted and marked as derived, with the original numbers it came from.

Feature types:

- **holes:** diameter; through, or a depth; and a type:
  - plain;
  - threaded: thread size (like M5) and thread depth;
  - countersunk: countersink diameter and angle (like Ø9 × 90°);
  - counterbored: counterbore diameter and depth;
- **slots:** width, length, direction, through or a depth;
- **pockets:** rectangular or circular, with size, depth, and corner radius. A pocket covering a whole area also handles a **step**, where part of the plate is thinner;
- **cutouts:** a pocket that goes all the way through, like a window opening.

**Patterns**, so positions that aren't written individually don't have to be invented:

- **row:** count, spacing, direction ("4 slots, 82 mm apart");
- **grid:** rows and columns, with spacing in each direction;
- **circle:** count, radius, starting angle, and either even spacing or listed angles ("8 holes evenly spaced on a 115.5 mm radius");
- **mirror:** a copy of a feature across a center line.

**Stored with the part but not drawn as shape** (the same way standard CAD handles them):

- **threads:** the hole is built at its drill size and labeled with the thread. This is what CAD calls a "cosmetic thread." For example, an M5 threaded hole is built as a Ø4.2 hole labeled "M5 thread";
- **tolerances and fits** (like ±0.2 or H7): stored on the feature and shown in its label. The model uses the plain size;
- **finish notes** (like "deburr and break sharp edges"): stored as notes.

**Also:** material and weight on the drawing, for the weight check.

Every field points to the number(s) on the drawing it came from (`fact_id`s from A7), says it came from a pattern, or is marked derived.

**Not covered by the flat template:** custom curved outlines (could be added later), grooves that follow a path (like an o-ring groove around a frame), bent sheet metal, and welded parts made of several pieces.

**Round part template** (bonus work, only if time is left): a cross-section profile spun around a center line, for tubes, grooved rings, and similar parts.

#### Decision: every field is known, options, or unknown

These are different situations and are handled differently.

| State | Meaning | Example | What the app does |
|---|---|---|---|
| `known` | One value, clearly on the drawing | D-025's outside diameter, Ø250 | Uses it |
| `options` | The drawing itself prints more than one value, and we can't tell which applies | D-013's thickness is printed as "6,0" stacked over "3,0" | **Builds one example per option** and lets the user switch |
| `unknown` | We can't tell the value: unreadable, not written anywhere, or we can't tell what a number measures | A blurry digit on a scan | **Never guesses.** See below |

**Rules for `options`:**

- Every option must point to a number actually printed on the drawing. Options are never made up.
- Each example is a complete 3D model built from one choice per `options` field.
- At most 4 examples per part. If a part would need more, it's marked "too many possible readings to build in 3D," and only the drawing is shown. (In the clean drawings, no part has more than one `options` field, so the most any part needs is 2 examples.)

**Rules for `unknown`:**

- **If the shape depends on the field** (outline or thickness), no 3D model is built. The app says why, for example: "Can't build 3D: thickness is unreadable," and shows the 2D drawing.
- **If it's a small detail** (one hole's size), the model is built without that feature, and the 3D view lists it, for example: "Not shown: hole near the right end, size unreadable."
- `unknown` never becomes `options`. In particular, when the two AI models disagree on a field, that field is `unknown` (waiting for a person), not two options.

Example of a filled-in template:

```json
{
  "part": "D-013",
  "template": "flat_part",
  "filled_by": "two_models",
  "review": {"status": "not_reviewed", "by": null, "at": null},
  "outline": {"state": "known", "type": "rectangle",
              "length": {"value": 270.0, "fact_id": "F-0630"},
              "width":  {"value": 25.0,  "fact_id": "F-0632"}},
  "thickness": {"state": "options",
                "options": [{"value": 6.0, "fact_id": "F-0640"},
                            {"value": 3.0, "fact_id": "F-0641"}]},
  "features": [
    {"state": "known", "kind": "slot", "face": "top", "width": 5.5, "length": 10.0, "through": true,
     "pattern": {"type": "row", "count": 4, "spacing": 82.0}, "fact_ids": ["F-0620", "F-0631"]}
  ],
  "material": {"value": "3.3315 (EN-AW 5005)", "fact_id": "F-0611"},
  "weight_on_drawing": {"value": 87.5, "unit": "g", "fact_id": "F-0613"}
}
```

(Positions and counts shown are illustrative; the real file is filled in from the drawing. `F-xxxx` IDs are shorthand for stable names, A9.)

#### Switching between examples

- When a part has `options`, the 3D view shows buttons such as **"Example A / Example B."**
- Next to them, the app says exactly what differs ("only the thickness: 6 mm vs 3 mm") and highlights the number each example used on the 2D drawing.
- Both are labeled "possible reading." Neither is marked correct by default.
- **A reviewer can pick one** on the review page (B6). That's saved as a `human_decision` with who and when. After that, the chat answers with the chosen value and the 3D view opens on that example, but the other example stays viewable. This is a second demo of the correction feature.
- **The chat explains it**, for example: "The drawing shows two numbers for the thickness, 6 and 3, and I can't tell which applies. You can switch between both in the 3D view."

#### Weight check

A rule-based check that the 3D model matches the drawing:

1. CadQuery calculates the model's volume.
2. Multiply by the material's density from the density table (below).
3. Compare to the weight printed on the drawing.

**How each example is judged:**

- The check is run for **every example** and shown next to the switch, for example: "Example A: 105 g calculated, drawing says 87.5 g."
- Within about 5%: "matches." Further off: "doesn't match," with the difference shown.
- **Limit:** a correct weight doesn't prove holes are in the right places. It catches size and thickness mistakes, not position mistakes.

**Which material it uses:**

1. **The drawing's material first**, since the 3D model is built from the drawing.
2. **The parts list's material** if the drawing has none, or if the drawing's material is unreadable or `unsure`, or if the weight doesn't work out with the drawing's material. If the parts list cell lists several materials (B3, rule 5), **each one is tried in turn**, and the result says which one, if any, made the weight work out, for example "Weight matches using parts list material: Steel."
3. **Always say which one was used**, for example "Weight check based on parts list material (Aluminium)."
4. **If the drawing has a trusted material, the weight fails with it, but works with the parts list's material**, the result is shown but also flagged for a person on the review page, with the message "Weight only matches using the parts list's material. The drawing's material, or the model's size, may be wrong." A weight mismatch can come from a wrong material *or* a wrong size, like the stacked thickness, so the app doesn't silently decide which.

**Weight check results.** Every part with a 3D model gets exactly one of these:

| Result | When | How it looks |
|---|---|---|
| **Passed** | At least one example matches using the **first material tried**: the drawing's, or the parts list's when the drawing has no trusted material | Green "Weight check passed," saying which material was used |
| **Flagged for review** | The drawing **has** a trusted material and no example matches with it, but at least one matches using a **parts list** material | Amber "Weight check flagged: only matches using the parts list's material." Sent to the review page. |
| **FAILED** | No example matches with **any** candidate material (the drawing's or any listed in the parts list), **or** there is **no material at all** to check with | **Big red "FAILED weight check: needs manual approval."** Sent to the review page. |
| **Skipped** | The drawing has no printed weight, or it's `unsure` | Grey "Weight check skipped: no weight on the drawing" |

**After a person reviews it,** the result keeps its original color and wording, plus who approved it, so it never looks like a check that passed on its own. For example: "FAILED weight check · approved by [name] on [date]." Approving a FAILED part **requires a short note** saying why, like "Thickness confirmed from the side view; drawing weight looks wrong." The note is saved with the decision (A9).

**Weight check results never hide the 3D model.** A flagged or FAILED part is still built and shown in the 3D view before anyone reviews it, like any other AI reconstruction. The result appears next to the example switch, in the part page header, on the part's row in the parts list, and in the Model provenance panel. The model's label stays "AI reconstruction. Not reviewed by a person" until someone reviews it.

**The density table** (`densities.json`):

- Built **once, before shipping**, by looking up each material name that appears in the data (and in the name mappings, A10) on the web.
- Each entry saves the density, the **source page it came from, and the date** it was looked up. It ships with the app.
- Labeled **"outside source, not the dataset"** wherever it's shown, and listed in the write-up under outside data used.
- If a specific alloy has no entry, the check uses its family's density through the `kind_of` mapping (A10), for example EN-AW 5005 → Aluminium, and says so.
- Typical values for reference: aluminium about 2.7 g/cm³, stainless steel about 8.0 g/cm³.

**A FAILED result hints the real shape may be something else.** For example, the stacked numbers might describe a part that's thicker in one area than another (a step) rather than two separate versions.

Rough estimates for the required parts (the code will recalculate these properly):

| Part | Example A | Example B | Weight on drawing |
|---|---|---|---|
| D-013 | 6 mm: ~105 g | 3 mm: ~52 g | 87.5 g (neither matches well) |
| D-025 | 3 mm: ~78 g | 2 mm: ~52 g | 77.3 g (A matches) |
| D-026 (stainless) | 25 mm: ~9.8 kg | 15 mm: ~5.9 kg | 7.8 kg (neither matches well; its drawing material is garbled, so the parts list's materials are used, and steel and stainless steel weigh about the same, so this would likely be FAILED) |

#### The required 3 parts

All three use the flat part template and go through the same two-model filling as every other part. Each has one `options` field (the stacked thickness), so each gets 2 examples. Before submission, a person reviews all three field by field (see "Accuracy check" below), so the required demos are checked, and the review results become the accuracy measurement.

- **D-013, Recoater Plate:** a flat bar, 270 × 25 mm, with 4 slots, 2 M5 threaded holes, and 8 M3 threaded holes, in row patterns. Some hole positions aren't dimensioned individually and come from the repeating pattern. Thickness options: 6 or 3 mm.
- **D-025, Bygge Base Ring:** a flat ring, Ø250 outside and Ø224 inside, with 8 countersunk Ø3.4 holes in a circle pattern on a 115.5 mm radius. Fully dimensioned, so the easiest. Thickness options: 3 or 2 mm.
- **D-026, Build Plate:** a Ø250 disc with 3 counterbored Ø5.3 holes in a circle pattern on a 105 mm radius. Thickness options: 25 or 15 mm.
- **Backup: D-019, silicone gasket:** a thin 1 mm ring with 6 holes.

The filled-in template is also the source of the chat's measurement facts for these parts (A7, level 2). The 3D view shows key measurements as labels on the model, such as "270 mm" along the long edge.

#### Labels, always visible

Every 3D model says how much a person was involved. Exactly one of these applies:

- **"AI reconstruction from 2D drawing D-0XX. Not reviewed by a person."** Every field came from the two models, with no human oversight.
- **"AI reconstruction from 2D drawing D-0XX, with human input on N fields. Not fully reviewed."** A person answered the fields the models were unsure about, but nobody has checked the rest.
- **"Reconstruction from 2D drawing D-0XX, reviewed by [name] on [date]."** A person approved the whole design (B6), or confirmed every field one by one.

All three also say **"Not the original CAD model."** Any `options` or `unknown` fields are listed under the label. The part's page also shows which fields are `ai_agreed` and which are `human_decision`.

#### Shapes in the dataset

From looking at all 30 drawings:

| Shape type | Drawings | Template |
|---|---|---|
| Simple flat parts: plates, rings, discs, strips, with holes | D-013, D-014, D-015, D-016, D-017, D-019, D-025, D-026, D-027, D-028; D-001 (scan) | Flat part. Easy. D-016's rounded corners, D-017's chamfered edges, D-028's pill shape, and D-014's back-side countersinks are all covered by the standard fields. |
| Flat parts with a custom outline: L-shape, triangle, three-lobed plate | D-018, D-029; D-011, D-030 (scans) | Flat part with a custom outline. The curves are harder to fill in correctly. |
| Flat parts with extra machining: grooves, pockets, holes in side faces | D-005, D-012; D-003 (scan) | Partly. Pockets, cutouts, and side-face holes are covered. D-005's o-ring grooves aren't, so they'd be left out and listed. |
| Round parts: tubes, grooved rings, stepped discs | D-024; D-020, D-023 (scans) | Round part. |
| Shaft with grooves that follow a curved path | D-007 | Not supported. |
| Bent sheet metal: sheets folded into flanges | D-002, D-004, D-006, D-008, D-010 | Not supported. |
| Welded boxes and ducts | D-009, D-021; D-022 (scan) | Not supported. |

**With the flat template as defined, up to 10 parts can be built:** the 3 required (D-013, D-025, D-026) plus D-014, D-015, D-016, D-017, D-019, D-027, and D-028. D-012, and D-005 with its grooves left out, probably fit as well. "Up to" because a part with an unsure outline or thickness waits for a person's answer before it's built.

**Unsupported shapes get an honest message**, for example: "No 3D model: bent sheet metal isn't supported. Here's the 2D drawing."

#### How templates get filled

The same two-model setup as matching (A4) and labeling (A7), run once per drawing in the setup loader, with results saved. A person's job is to **answer what the models are unsure about and approve**, not to write the form.

1. **Both models fill in the template separately.** Claude Code and Codex each get the page image, the list of numbers the parser found (each with an ID and position), and the blank template.
2. **Every field must be backed by the drawing.** Each value must use number IDs from the list, come from a pattern, or be marked derived. The code rejects anything else. Each field also gets `sure` or `unsure`.
3. **The state must match too.** If both models say a field is `options` (like the stacked thickness) and list the same values, it's `options`. Both models must agree on the state and the values.
4. **Decide each field:**

| Claude Code | Codex | Result |
|---|---|---|
| sure, value X | sure, value X | **Used**, marked `ai_agreed` |
| sure, value X | sure, value Y | **Retry round** (A4 step 3b). A match after the retry is used, marked `ai_agreed_after_retry`. Otherwise it **needs a person**, labeled "models disagree" |
| unsure (either or both) | anything | **Needs a person.** Labeled "model unsure," with what it was unsure about. No retry |
| invalid answer | anything | **Needs a person.** Labeled "invalid AI answer" |

5. **Run the weight check.** A Flagged or FAILED result sends the part to a person even if every field was `ai_agreed` or `ai_agreed_after_retry`. This is a rule-based check on the AI's work. **It doesn't stop the model from being built or shown;** it only adds the result's warning and sends the part to the review page.
6. **Build what can be built.** Only missing information can stop a model from being built, never a warning or flag. Fields waiting for a person stay `unknown` until answered:
   - if the outline or thickness is waiting, the part isn't built yet, and the app says "3D waiting for human input on: thickness";
   - if only small details are waiting, the model is built without them, and they're listed as "not shown, waiting for human input."
7. **A person answers on the review page** (B6, "Needs human input" tab). For each waiting field, they see the drawing with the relevant numbers highlighted, both models' answers and reasons, and the weight check. They can pick one model's answer, enter a value (pointing to the number on the drawing), mark the field `options`, or mark it `unknown`. Their answer is saved as `human_decision` with who and when, and the part is rebuilt.
8. **A person can approve the whole part** with "Approve whole design" on its part review page (B6), once no field is waiting for a value. That changes its label to "reviewed by [name]" (see Labels above).

**Accuracy check.** For the 3 required parts, Jason goes through every AI field against the drawing before submission and confirms or rejects each one (B6). There's no hand-made answer key. This gives a real accuracy number, for example "41 of 44 AI fields were right; the weight check caught 1 of the 3 wrong ones." It also means the required demos have been checked.

#### The 3D viewer screen

Modeled on the reference screenshot (`refrence_ui/ui_3d_visualizer.png`). Everything here shows data the plan already produces. Only the parts list and the section view are new work.

**Parts list (left panel)**

- A list of **every part**, not just the 30 drawings. That's every part record (A6): parts with a drawing, and the parts-list-only rows like screws, motors, and cables. It has a **search box** (by part name or material).
- **Filters:** machine section, material, what the part has ("2D + 3D," "2D only," "parts list only"), and review status. The section filter uses the section name mappings (A10), so a drawing in "Optical" and a row in "Optics" show up under the same section.
- Each row shows the part name (chosen the same way as in the header below), section, "2D + 3D," "2D only," or "parts list only," and its status tag. Search matches either name.
- Clicking a row opens that part on the right.

**Header (top of the part view)**

- Part name, drawing ID, and materials. The **part name shown** is the drawing's title if it's `sure`, otherwise the parts list name, otherwise the drawing's file name. This only picks the label; both names stay in the record and appear in the Detail tab.
- A **status tag:** "AI RECONSTRUCTION," "AI + HUMAN INPUT," or "REVIEWED," matching the label levels above. Parts without 3D show "2D ONLY." Parts with no drawing show "PARTS LIST ONLY."

**Tabs**

- **3D model:** the viewer.
- **2D drawing:** the drawing viewer (B4).
- **Detail:** every fact for the part, with its source badge or Undetermined tag.
- **History:** the part's full history (see "History view" below).

**Tabs a part doesn't have are hidden.** A part with a drawing but no 3D has no 3D tab. A **parts-list-only part** (no drawing) has only **Detail** and **History**. Its Detail tab shows a **parts list row card:**

- the original values exactly as written in the spreadsheet;
- the cleaned values next to them, with the cleanup rules that changed them (A3);
- the "recorded in the snapshot, may be out of date" note on supplier, price, order number, and links;
- its recorded connections, if any.

This is also what opens when someone clicks a parts list citation in chat.

**This screen is the part page.** Every part has one, and it's where chat citations, part cards, and the parts list all lead.

**Drawing thumbnails (beside the 3D view)**

- A small preview of each page of the part's drawing, like the reference's "Sheets" list. Clicking one opens it in the 2D tab.
- This also handles drawings with more than one page (D-003 has 3, D-021 has 2).

**Toolbar**

- **Dimensions:** show or hide the measurement labels on the model.
- **Callouts:** show or hide the feature labels, like "8 × M3 threaded holes."
- **Specs:** show or hide the specs & materials panel.
- **Section:** a basic cut-away view with a slider that slices the model so you can see inside, for hole depths, countersinks, counterbores, and pockets. The cut face shows as hollow (an empty shell). Making it look solid is **not planned**.
- **Fit:** reset the camera to show the whole part.
- **Full screen.**
- The **Example A / Example B switch**, when the part has `options`.

**Overall size readout**

- The part's overall size in mm, like "270 × 25 × 6 mm," measured from the model. It updates when switching examples.

**Specs & materials panel (floating, toggled by Specs)**

- The material's **one display value** (B3), or the Undetermined tag with its message. Under it, what each source says word for word (drawing and parts list), each with its source badge.

**Feature list (beside the model)**

- Every feature of the part (hole groups, slots, pockets, cutouts) with the color it has in 3D.
- Hovering or clicking an item highlights it on the model and shows its values, badge, and spot on the 2D drawing. This works both ways: hovering a feature on the model highlights it in the list.

**Right-side panels**

- **Model provenance:** how this model was made. Source drawing and its fingerprint, template used, how each field was filled (`ai_agreed`, `ai_agreed_after_retry`, or `human_decision`), review status with who and when, weight check result for each example, and any "not shown" or "waiting for human input" items. It ends with "Reconstruction from 2D drawing. Not the original CAD model."
- **Bill of materials:** the linked parts list row(s), with supplier, cost, quantity, Design / Order / V&V status, and "recorded in the snapshot, may be out of date." If the link is `unresolved`, the Undetermined tag says so.
- **Installed in:** the part's machine section, its recorded connections from the "Interface with" column (A5) and from diagram labels (A12), and the section's diagram, whole, with the matching label's text listed next to it (A12). Parts with no recorded connections show "No connections recorded."
- The **STEP download button** lives in the Model provenance panel.

**History view**

Everything shown here is already saved (A6, A8, A9). This just gives it a place to be seen, so the original evidence and the full record of changes are always visible.

- **History tab, for the whole part:** a timeline, oldest first, of everything that happened to the part:
  - the original extracted values, with their sources;
  - parts list cleanup changes, with the rule that made each one;
  - the link to a parts list row, and how it was made;
  - both AI models' answers for every AI item, including both rounds when there was a retry;
  - every human decision: answers, corrections (accepted and rejected), confirmations, rejections, chosen examples, and "Approve whole design," with who and when;
  - "source changed since approval" events, when a drawing's or row's fingerprint changed (A9);
  - the current value of each field.
- **One fact's history:** clicking any fact's source badge (or its Undetermined tag) shows the same timeline for just that one fact: original value → AI answers → human decisions → current value.
- **Nothing is hidden.** Rejected answers and replaced values stay in the timeline, shown as rejected or replaced.

**Left out on purpose**

- **Explode and Play.** In the reference, these pull an assembly apart and animate it. Each of our models is a single part, not an assembly, so there's nothing to pull apart.
- **A solid cut face in the section view.** Not planned; the basic hollow cut is enough to see inside.

#### Backup plan

Since the built models ship with the app, a CadQuery install problem only affects rebuilding, not running the app. If CadQuery can't be installed at all for development, build the same flat shapes directly in Three.js, which can take a 2D outline with holes and give it thickness.

### B6. Fix-wrong-info feature (corrections)

**Rule: original facts are never edited or deleted.**

Corrections are human decisions, so they're saved in `decisions/` (A9) and survive rebuilds and shipping. Each one looks like:

```json
{
  "correction_id": "C-001",
  "fact_id": "D-019/drawing/title",
  "old_value": "Description",
  "new_value": "Silicone gasket for f-theta lens",
  "reason": "Title field was never filled in; the note and a parts list row point to this",
  "proposed_by": "chat user",
  "check_result": "Similar name found in parts list row 'Silicone gasket f-theta ring'; note says 'silicone pakning'",
  "status": "pending",
  "reviewed_by": null,
  "created_at": "...",
  "reviewed_at": null
}
```

**Flow:**

1. **In chat,** the user says something is wrong. The AI calls `propose_correction`, and it's saved as `pending`. The chat confirms it's waiting for review, with a link straight to the correction on the review page.
2. **The app checks it automatically.** Does the new value show up in the drawing text? Does the parts list agree? The result is saved in `check_result`.
3. **On the review page,** a person sees the original drawing spot, the matching parts list row, the check result, and Accept / Reject buttons.
4. **After acceptance,** answers use the new value but say "originally recorded as X, corrected to Y on [date]." The original drawing and full history stay viewable.

**Demo:** ask "What is D-019?" before and after accepting the D-019 title correction, and show that the answer changes.

**The review page has four tabs:**

1. **Corrections:** user-proposed fixes from chat (above).
2. **Needs human input:** drawings the AI models couldn't agree on how to link (A4 step 4), 3D template fields the models weren't both sure about (B5), every section and material name mapping waiting for approval (A10), and parts whose weight check was **Flagged** or **FAILED** (B5), plus any item whose evidence changed since it was approved (A9).
3. **AI interpretations:** every AI item (A8): scan readings, links, labels, diagram label readings, 3D template fields, and whole 3D parts, whether `ai_agreed` or `ai_agreed_after_retry`. For each item it shows the evidence (the drawing spot, the parts list row), both models' answers and reasons (both rounds, if there was a retry), and the current review status. Filters: drawing, type, method, review status, and weight check result, so a reviewer can work through everything "not reviewed" or go straight to the FAILED parts. A person can:
   - **Confirm**, which sets the status to `human_confirmed`, with who and when. The item is then shown as reviewed everywhere: badges, chat answers, and 3D labels;
   - **Reject**, which sets the status to `human_rejected`, keeps the AI answer in the history, and optionally lets them enter the right value as a correction;
   - **Approve whole design** (see below), to approve one entire part at once.
4. **Possible readings:** parts with `options` fields (B5). For each, it shows the examples side by side, the number each one used on the drawing, and each example's weight check. A person can pick one, saved as a `human_decision`, or leave it open.

**The review area is separate from the part page.** Review lives only in the Review area of the left sidebar (B8). The regular part page (B5) is for looking at a part: 3D, 2D, Detail, and History, with **no review buttons or review popups** on it. At most, it shows a small "Review this part" link when the part has items waiting, which jumps to the review area.

**Approve whole design.** In the review area, each part has a **part review page**. It reuses the same views as the part page, so the reviewer sees the part exactly as everyone else does, with the review controls added around them. It shows everything about that one part on one screen:

- the 2D drawing;
- the 3D model, with the example switch if it has `options`;
- the weight check for each example;
- every field of its template, each with its badge;
- its link to the parts list row;
- the AI labels on its drawing, and its scan readings if it's a scan;
- any diagram label readings that point to it.

If the whole thing looks good, the reviewer clicks **"Approve whole design."**

- **One part at a time.** The button approves only that part. There is deliberately no "approve everything" button across parts, so every approval means someone actually looked at that part.
- **What it covers:** every AI item belonging to that part, including its template fields, its link, the labels on its drawing, its scan readings, diagram label readings that point to it, and the 3D model as a whole.
- **It's only available when no field is waiting for a value.** A Flagged or FAILED weight check doesn't block it, since approving is how those get cleared. But if any field still needs human input, the button is disabled and says why, like "2 fields still need input: thickness, hole size near right end." Approving can't fill in a value nobody has given.
- **A FAILED weight check needs a note.** Approving a part whose weight check FAILED requires the reviewer to type a short reason (B5, weight check).
- **`options` can stay open.** Approving means "this reconstruction correctly reflects the drawing," and a drawing that prints two thicknesses really does have two readings. The reviewer can pick one first if they want, but they don't have to.
- **How it's saved:** one `approve_design` decision for the part, plus a confirmation for each item, all with the same reviewer and time, in `decisions/` (A9). Because each item has its own confirmation, a later change to one item only re-opens that item.
- **What changes:** every item on the part shows "reviewed by [name] on [date]," and the 3D label changes to the reviewed version (B5). If one item is later re-opened because its evidence changed, the part label says "Reviewed by [name] on [date], except 1 item that changed since review."

All four tabs follow the same rule: nothing is overwritten, and every decision is saved with who made it and when. The full record for any part or fact can be seen in its History view (B5).

### B7. Files page (optional)

(The README page from A11 is required and built separately. If the files page is built, it links to it.)

A simple list of every source file from `manifest.json`: the 30 drawings, the parts list, the diagrams, and the README. Each shows its section and a "degraded scan" tag where it applies. Clicking a file opens it. (README and diagram citations don't depend on this page; they open their own pages, A11 and A12.)

### B8. Navigation

A **left sidebar with icons**, like the reference screenshots:

- **Chat** (B1 to B3)
- **Parts:** the parts list and part pages (B5)
- **Review:** the review area with its tabs (B6)
- **Files:** the README page (A11) and the diagram pages (A12), plus the full files page if it's built (B7)

The side panel (B2) opens on top of whichever screen is showing, so a part can be looked at from the chat without leaving it.

#### Links

**Every page and item has its own link, all in the same style,** built from the stable names in A9 so links never break after a rebuild:

| What | Link |
|---|---|
| A part | `/part/D-013` |
| A parts-list-only part | `/part/bom/electric/12v-psu` (from its stable name, A9) |
| A specific tab | `/part/D-013/2d`, `/part/D-013/3d`, `/part/D-013/detail`, `/part/D-013/history` |
| A cited spot | `/part/D-013/2d?fact=D-013/drawing/material` (opens with that spot highlighted) |
| A 3D example | `/part/D-013/3d?example=B` |
| A review item | `/review/needs-input/D-013/template/thickness` |
| A part's review page | `/review/part/D-013` |
| A README passage | `/readme#physical-system/p1` |
| A diagram | `/diagram/zaxis` |

- Citations, part cards, history entries, and the chat's "waiting for review" links all use these.
- The browser's back and forward buttons work as expected.
- The side panel uses the same links, so opening a part from the chat and opening it from the parts list show exactly the same thing.
- The backend sends the frontend's main page for any of these addresses (a few lines in FastAPI), and the frontend shows the right view.

---

## Testing

### The benchmark: 20 questions with known answers

The main test is a **fixed set of 20 questions, with the right answers worked out by hand from the source files.** (It's post-MVP; see `mvp.md`.) It's the benchmark for the whole project, and it answers the assignment's design question "How do you know whether the system improved?": rerun the benchmark after any change and compare the scores.

**Rules:**

- **Written from the source files, then frozen.** The questions and answers are worked out by looking at the source files directly, **not** at the system's answers, so they test the system rather than describe it. They can be written after the system is built. Once written, questions aren't changed to make the system look better. If one turns out to be wrong, it's fixed and the change is noted.
- **Kept separate from the system.** Benchmark questions and answers are never used in prompts, the database, or any AI step. Otherwise the score would be meaningless.
- **Stored in one file:** `benchmark/questions.json`.

**Each question lists what a correct answer must contain:**

```json
{
  "id": "Q07",
  "question": "What is the recoater plate made of?",
  "expected_behavior": "answer",
  "must_include": ["EN-AW 5005"],
  "must_cite": ["D-013/drawing/material"],
  "must_show_parts": ["D-013"],
  "must_not_include": [],
  "notes": "Parts list says Aluminium; kind_of mapping (A10) should show the more specific name."
}
```

- `expected_behavior` is `answer`, `undetermined` (the right answer is Undetermined, with the reason), or `no_evidence` (the right answer is "there's no evidence for this").
- `must_include` and `must_not_include` are key values or phrases, like "250 × 150 mm" or "may be out of date."
- `must_cite` lists the sources a correct answer must cite.
- `must_show_parts` lists the parts whose drawing (and 3D model, if any) must open, and no others (B2).

**What the 20 questions cover:**

- how the machine is organized (sections, parts per section);
- drawing-to-parts-list links;
- shared materials across parts, including "Which parts are aluminium?" and "Which parts are EN-AW 5005?" (the first includes all aluminium alloys; the second only parts where a source says EN-AW 5005);
- supplier and price questions (answers must include "may be out of date"), and "What did the machine cost in total?" (must give the sum of recorded prices and say how many rows have no price recorded);
- questions about blurry drawings;
- questions where the right answer is Undetermined or "no evidence";
- at least one question naming a part with a 3D model;
- a thickness question on a part with `options` (gives both values and points to the example switch);
- a measurement question where the right answer is "I can't tell which edge this measures," with the drawing shown;
- a hole-count question answered from a callout;
- "What is the timing belt made of?" ("Materials recorded: Steel, Elastomer," without claiming how they're used);
- a question about a specific part where the right answer is "I don't know" (its drawing must still open);
- "What is the machine's build volume?" (250 × 150 mm, citing the README);
- "What does the cylinder clamp ring attach to?" (the main platform, citing the Z-axis diagram, as an AI interpretation);
- "Is the original CAD assembly available?" (the README mentions it, but the answer must say it isn't in this dataset);
- the D-019 question, which changes after the correction (see below).

**Scoring.** A script, `uv run meridian benchmark`, runs all 20 questions through the real chat and checks each answer automatically:

- does it contain every `must_include` value, and none of the `must_not_include` ones?
- does it cite every `must_cite` source, with no invalid citations or markers?
- where the right answer is Undetermined, does it use the `[undetermined: ...]` marker (B1) instead of stating a value?
- did exactly the `must_show_parts` parts open?
- did it behave as expected (answer, Undetermined, or no evidence)?

Each question passes or fails, with the failed checks listed. The script also records **time and cost per question** and **which chat provider and model** was used. A person reads through the answers once as a sanity check, since automatic checks can't judge wording.

**When to run it:**

- **Before and after the D-019 correction.** That question's expected answer has a "before" and an "after" version, so the run shows the correction actually changed the answer.
- **Twice in a row with nothing changed**, to measure how much answers vary between runs (reproducibility).
- **After any change** that could affect answers: a new chat model, a prompt change, a batch of review decisions, or a rebuild. Each run's results are saved with the date, so the scores can be compared over time.

**What goes in the write-up:** the score for each run, the questions that failed and why, time and cost per question, and the model used.

### Other checks

- **Rebuild test:** delete the database and all generated files, rebuild from scratch, and confirm that every human decision is still applied and no approved item asks for approval again.
- **Changed-evidence test:** change one drawing's fingerprint and confirm that only the decisions based on that drawing go back to "Needs human input."
- Save chat transcripts and screenshots so reviewers can see results without running a paid AI service. **Record which chat provider and model produced them**, since results can differ by model.

**Reading the blurry scans (from A2):**

- Jason checks the corner box fields the models read against the scan images, with Confirm and Reject (B6). Report how many were confirmed, how many rejected, and how many were left Undetermined.
- How often the two models agreed, and how often the retry round was needed.

**Matching measurements (from A4):**

- How many drawings were matched by `exact_match`, `ai_agreed`, `human_decision`, or left `unresolved`.
- How often Claude Code and Codex agreed, and how often they disagreed.
- **Retry round:** how many disagreements it resolved, how often both models swapped answers, and how often one held while the other switched. Spot-check `ai_agreed_after_retry` results separately from `ai_agreed` ones, to see whether the retry actually fixes mistakes or just produces agreement.
- Spot-check results: how many `ai_agreed` links Jason confirmed and how many he rejected.
- Comparison with simple name matching (about 11 of 26 clearly right) to show why the extra steps were worth it.
- Time and cost of one full matching run.

**Name mappings (from A10):**

- How many name pairs were matched by exact match, by the AI models, and by a person, and how many relationships of each type.
- For sections: how strongly the link counts supported each mapping.

**Parts list cleanup (from A3):**

- How many values each cleanup rule changed, from `cleanup_report.json`.
- How many items were flagged rather than fixed.
- The zero-total trap is checked by the benchmark question "What did the machine cost in total?" (above).

**AI review (from A8):**

- How many AI items a human reviewed, and how many were confirmed or rejected.

**3D models (from B5):**

- Weight check result for every example of every 3D part, and how many parts ended up Passed, Flagged, FAILED, or Skipped.
- For the 3 required parts: how many AI-filled fields Jason confirmed and rejected, and whether the weight check caught the rejected ones.
- For every 3D part: how many fields were `ai_agreed`, how many needed a person, and why (disagreement, unsure, invalid).

**Diagram labels (from A12):**

- How many of the roughly 30 labels the two models agreed on, and how many were left unmatched.
- A person checks every agreed label's part match and connection phrase against the diagram, and reports how many were right.

**Labeling measurements (from A7):**

- How many numbers and notes got an `ai_agreed` label, and how many were left unlabeled.
- How often the two models agreed, and how many labels were only kept thanks to the retry round.
- For the 3 required 3D parts: how many AI labels matched the template values Jason confirmed.
- Time and cost of one full labeling run.

---

## Write-up checklist (from the assignment)

- [ ] How to set up and launch: install uv, then `uv run meridian` (or `start.sh` / `start.bat`); adding an API key for the chat
- [ ] Short explanation of the design and key decisions
- [ ] Example questions, including one that opens a drawing and 3D model
- [ ] Known limitations and analysis of important errors
- [ ] Models, services, and outside data used (including the chat model used for the saved transcripts, and the density table and its sources); which files are sent to an outside service, on which side (engineer or customer), and why that's acceptable (the decision under Tools)
- [ ] Measurements: quality, repeatability, cost, speed, failure cases
- [ ] Saved screenshots and transcripts: chat, 2D/3D views (including the 3D viewer screen with its panels, example switch, and section view), correction before and after
- [ ] Attribution: keep `ATTRIBUTION.md` and the license file (`dataset/context/OpenLPBF-LICENSE.md`) in the submission unchanged, and add one short note to the attribution section saying the 3D models (GLB and STEP) were reconstructed from the supplied drawings, with the date. Nothing more is needed in the app or inside the files.

---

## Order of work

> **For the actual build, follow the workstreams and timeline in `mvp.md`.** The order below is the full-design order, kept for reference.

1. Setup loader: parse drawings, clean the parts list, split the README into citable passages, and build part records, including hole callouts and `method` labels on every field (A1, A3, A6, A7 level 1, A8, A11)
2. Basic chat answering from the database with sources, with `tools.py` returning already-resolved display values (B1, B3)
3. The parser for citation and Undetermined markers, attached part cards, and the side panel (B1, B2, B4)
4. Drawing-to-parts-list matching and connections (A4 steps 1–3, A5), plus the `decisions/` folder and loader logic for applying saved decisions (A9). Then diagram label readings (A12), and section and material name mappings (A10), which need the links and use the diagrams as extra evidence. Unsure links and unapproved mappings stay unresolved until the review page exists in step 8.
5. Blurry drawings (A2)
6. 3D models (B5): flat part template, two-model template filling, weight check, example switch for `options`. Start with the 3 required parts, then run it on the other flat parts. Filled-in templates also feed the chat (A7 level 2). Then the 3D viewer screen: panels and toolbar first (they only show existing data), then the parts list and the basic section view
7. AI labels for measurements and notes on all drawings (A7 level 3), checked against the person-checked templates from step 6
8. Corrections and review page (B6), with all four tabs: corrections, needs human input, AI interpretations, and possible readings
9. Testing and measurements: run the benchmark (before and after the correction, twice for reproducibility), plus the other checks
10. Write-up
11. Only if time is left: files page (B7), then bonus items (round part template and custom outlines (B5), other suppliers, connection graph, richer corrections). The MCP server (B1) is deferred and not on this list.

Get a rough version of every step working before polishing any one of them.

---

## Open questions and risks

Every earlier open question is recorded in **`gaps.md`**, and all of them are now resolved and written into this plan.

- **Missing `fixtures/public_questions.json`.** Ask the recruiter whether it was left out by accident.
- **What the stacked thickness numbers mean.** They might be two versions of a part or a step in one part. The app doesn't decide; it shows both examples with their weight checks, and a reviewer can pick.
- **CadQuery install size.** Lower risk now that built models ship with the app. Still lock the version, and test early that CadQuery can export both GLB and STEP files the way the plan needs.
- **Reading the blurry scans.** Some fields may be unreadable no matter what. That's fine as long as the app says so. AI misreadings look like plausible text, so the "copy exactly, don't fix" prompt rule and the two-model agreement matter here.
- **Matching names.** Some drawings may have no clear parts list row. Mark these as "no match" rather than forcing one.
- **Claude Code and Codex setup.** Both need to be installed and logged in, but only to redo the AI prep steps: reading scans (A2), matching (A4), labeling (A7), name mappings (A10), diagram labels (A12), or template filling (B5). The app runs from the saved results. Check the exact commands for non-interactive, read-only runs in each tool's docs when building this.
- **Blurry scans in matching.** For the 8 scans, the title and notes may be unreadable, so the models may only have the file name and folder. Expect more of these to go to human review.
- **Page images as input.** Reading scans (A2), labeling (A7), diagram labels (A12), and template filling (B5) all need both tools to accept an image in non-interactive mode. Test this with one drawing early, before building the rest.
- **Outside AI service.** Answers may vary a little between runs, and the service costs money. Measure both and report them.
