# User TODO

Human review is asynchronous. Coding, integration, testing, and dataset preparation continue while these items are pending. This file does not grant approval; real review actions retain their reviewer, time, evidence, and application decision history.

ROOT adds or updates concrete items as preparation and implementation expose them. Workers propose entries in their handoffs. Use one stable ID per item, link the evidence, state the current pending/provisional behavior, and explain the user's exact next action. Mark complete only after the user acts.

No dataset decisions have been generated yet. Do not prefill engineering answers or fabricate review tasks from illustrative proposal values.

## Pending

### BENCH-001 — Review preliminary benchmark expectations

- Question: Review the preliminary 20-question expected-answer draft, especially Q08's four unresolved links, Q17's approximate masses, and the conditional mapping/correction scenarios.
- Affected modules: M02/M14 summary tools, M23 benchmark scoring, M24 final results.
- Evidence: [benchmark_draft.md](docs/benchmark_draft.md), PLAN R16/E14. The draft's "checked" labels describe its author's earlier checks; this session has not independently reproduced all expected values.
- Current state: Preliminary, pending asynchronous human review. Coding and source-grounded automated verification continue. Isolated benchmark decisions never enter the production journal.
- User action: Review/correct the draft when convenient. Once actual judge decisions exist, spot-check about five and record the observation; no such spot-check is claimed yet.

### DRAW-019-TITLE — Review the D-019 correction demonstration

- Question: What supported corrected title should be recorded for D-019 after inspecting its drawing in Debug/Review?
- Affected modules: M05 source evidence, M16 review, M23/M24 correction demonstration.
- Evidence: [raw PDF run 42000021167](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42000021167), D-019 positioned text and page image; A05's handoff identifies the printed placeholder `Description` and separate note `1mm silicone pakning`.
- Current state: Pending and unreviewed. The placeholder is retained as original evidence; the usable title stays unavailable. No title is inferred from its note and no human decision is fabricated.
- User action: Inspect the source and record a supported correction through Debug/Review when convenient. Coding, preparation and isolated synthetic correction tests continue meanwhile.

## Completed

None yet.


- [ ] **AUTH-OPUS-20261105 ? Refresh Claude Code CLI-account login asynchronously.** The real D001 run40a435fd26894f6cab5612c36e0e028e completed valid Sol determination, then Opus exited with a confirmed OAuth error before inference (3.438sec). Evidence: testing/runs/prep-detail-v2/runs/40a435fd26894f6cab5612c36e0e028e/round-1/verification/receipt.json. Existing global and copied account credentials show an expired09:00UTC access token; the CLI failed authentication and cleared its owned private OAuth state. No keys/tokens were printed or committed, and external credential files were not changed. Reauthenticate the CLI account when convenient. Coding and data preparation continue now with valid Sol-only output explicitly UNVERIFIED when Opus execution fails; every new job still tries Opus first. This TODO does not block any coding or preparation.
