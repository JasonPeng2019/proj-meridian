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

Final run results and screenshots are recorded after integration verification.
