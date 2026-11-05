# Meridian UI redesign

Meridian follows the visual design of the **public homepage at
https://embedder.com/**, as Jason explicitly selected on 2026-11-05. The reference
HTML and both stylesheets were downloaded for inspection under the ignored
`.verification/design-reference/embedder` directory. Their palette, typography
scale, fine rules and small corner radii guide
the implementation. Embedder branding, marketing text, photographs and proprietary
fonts are not shipped. The original chat welcome and prompts remain in place.
Geist is self-hosted with its open font license.

The pre-package UI from commit `9d066dc` is the layout baseline, as Jason
requested. The original sidebar, Meridian mark, chat, card catalog and native
part/viewer controls are retained. The shadcn component layer and its direct
dependencies have been removed. Radix Dialog provides source-overlay focus and
Escape behavior only; it supplies no visual layout.
The theme is obsidian `#15151d`, warm linen `#ede5d3`, pale mint `#a6c9c0` and
ivory `#fffdf7`. The original navigation rail remains. Parts keep their original card catalog,
with responsive columns and collapsed additional filters. Detail keeps its
standard sections, with restrained borders and no new component-kit panels. Engineering evidence,
review controls, receipts, checks and history stay in Debug.

The existing customer/Debug browser suite is retained. Additional checks cover
message submission, source/attachment navigation, Back retaining the conversation,
copying, dialog keyboard behavior, keyboard part-view buttons, drawing zoom/fit, asset
filtering/reset and screenshots at desktop, laptop and mobile sizes. The new chat
interaction check mocks its HTTP transport; it makes no paid API or answer-quality
claim. Existing history checks still exercise persistence, reload and deletion
against the backend. No engineering reviews are submitted by the browser suite.

Builds and browsers run on Actions in sequence. `scripts/serve_ui_preview.py`
serves a hash-verified, pinned remote frontend artifact on port 8001 without Node
or a local build. Port 8000 remains the existing main app. The preview initially
hides Debug; its `--debug-ui` option enables the engineering interface. Both use
the existing local backend data. The preview refuses missing prepared data and
does not regenerate CAD.

The restored original layout passed [Actions integration 42052001797](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42052001797):
317 Python tests, customer and Debug browser stages, and all 12 responsive
screen/viewport combinations. Chat send/copy, citations, attachments, Back,
history persistence, dialog focus/Escape, keyboard view switching, drawing
zoom/fit, model variants and catalog filters passed. Debug checks covered
search, independent scrolling, review scope, source overlays and review-input
preview/validation. No browser page errors were recorded.

The downloaded reports and screenshots are under
`.verification/ui-redesign-42052001797/docs/verification/`. Desktop/mobile chat,
parts, Detail, drawing, answer and engineering-workspace images were visually
inspected. That inspection caught a light weight-warning panel in Debug; the
final CSS change gives it the same dark surface and readable text as the rest
of the engineering UI.

The preview on port 8001 now runs with `--debug-ui` at Jason's request. Its
current pinned artifact, process ID and HTTP asset hashes are recorded under
`.runtime/ui-preview-8001.*`. Every served static asset was compared with the
successful Actions build manifest; the original app on port 8000 remained
available. No local frontend build, browser automation or CAD generation ran.


Jason reported that chat displayed `Unavailable` while still attaching the part.
The saved provider answer was present. The previous output validator tried to
find a Python dictionary representation of the corrected thickness inside normal
English, requested two answer repairs, then produced a warning. The frontend
replaced any answer carrying a warning with `Unavailable`.

Per Jason's explicit instruction, chat output validation and answer-repair
retries have been removed. Luna's final text is returned directly. Source-link
resolution only attaches known evidence; it does not grade or rewrite the
answer. The frontend always displays and copies the answer, including saved
messages with legacy warnings; those warnings remain available in Debug.
Regression checks cover unchanged uncited/unrecognized-reference answers with
one provider call, readable structured corrections, evidence attachments, and
answer visibility/copy despite legacy warning metadata.

A sequential live check through the local preview returned a GPT-6-luna answer
to the recoater dimensions/material/weight/density question in 7.694 seconds,
with `find_part` and `get_facts` tool calls and no output-validation warnings.
The labelled smoke conversation was deleted afterward. Its receipt is retained
at `.verification/chat-direct-luna-live.json`. This checks provider integration,
not answer quality.


Final verification passed in [Actions integration 42054114470](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42054114470)
for source commit `127b30c`: **319 Python tests**, both customer and Debug browser
stages, all 12 responsive screen/viewport checks, and the explicit legacy-warning
answer visibility/copy regression. No Debug browser page errors were recorded.
The final chat and dark weight-check screenshots were inspected from
`.verification/ui-redesign-42054114470/docs/verification/`.

Port 8001 serves the matching static bundle from successful checks run
`42054115045`, with Debug enabled. All nine served assets matched the artifact
manifest by SHA-256. API status reports chat available with `gpt-6-luna`.
The existing installed `frontend/dist` was not replaced by this preview.
