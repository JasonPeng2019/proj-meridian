# Final captured benchmark: run 42020759881

**22/42 combined passes (52.4%); 18 failures and 2 pending outcomes.** This is the saved two-pass evaluation of commit `b40ec11790494d169831e25492fbcd97756f942f`, captured on 2026-11-05 at 11:43:28–11:48:08 UTC. All 42 answers were captured; all 42 independent meaning judgments are valid and merged. Chat used **`gpt-6-luna`**; one resource-gated local process judged sequentially with **Claude Opus regular mode** (receipt model `claude-opus-5-5`). Four rate-limit backoffs recovered without concurrent judge jobs.

The coordinator reports this workflow also passed 194 tests, nine packaged models/twelve variants, variant rendering, fresh recovery and live correction checks. Those engineering checks do not imply benchmark success. [Run 41997526697](../run-41997526697/README.md) remains a historical baseline from different code/prep/UI.

## Scores and stability

| Measure | Result |
|---|---:|
| Rules: pass / fail / prerequisite pending | 31 / 7 / 4 |
| Rule pass rate, all executions | 31/42 (73.8%) |
| Rule pass rate, applicable executions | 31/38 (81.6%) |
| Judge scores 2 / 1 / 0 | 27 / 12 / 3 |
| Combined: pass / fail / pending | 22 / 18 / 2 |
| Pass 1: rule / combined passes | 16/21 / 10/21 |
| Pass 2: rule / combined passes | 15/21 / 12/21 |

Combined success requires every applicable rule plus judge score 2. Pending cases remain in all-execution denominators. Thirty-three executions satisfy literal predicates if prerequisite coverage is ignored; that is not the rule-pass count.

| Category | Executions | Rule pass | Judge 2 / 1 / 0 | Combined pass |
|---|---:|---:|---:|---:|
| Machine organization | 6 | 4 | 5 / 1 / 0 | 3 (50.0%) |
| Linking drawings to the parts list, and one value per field | 12 | 7 | 9 / 3 / 0 | 6 (50.0%) |
| Uncertainty and honesty | 14 | 12 | 6 / 6 / 2 | 6 (42.9%) |
| Holes, 3D, and checks | 4 | 2 | 2 / 2 / 0 | 2 (50.0%) |
| Costs, the README, and current information | 6 | 6 | 5 / 0 / 1 | 5 (83.3%) |

Across 21 paired cases, **20/21 (95.2%)** have identical rule results, **18/21 (85.7%)** identical judge scores and **17/21 (81.0%)** identical combined outcomes. These compare outcomes, not answer bytes. Q09 changes rule outcome; Q02, Q06 and Q20 change judge score; all four change combined outcome. Consistently pending Q03 is included in stability, not counted as a pass.

## Prerequisites and failure analysis

- **Q03/Q08:** Optical/Optics approval remains pending. Only the 5005/Aluminium mapping has human approval, recorded as `same`; other alloy mappings and all four flagged drawing links remain pending. Q03 abstains faithfully (judge 2 twice) and remains combined pending. Q08 omits Galvo Bundplade and does not adequately qualify unresolved deduplication; both judges give 1, so combined results fail despite pending prerequisites. Pass 1 also has a count/list inconsistency; pass 2 reports 33 projected matches without distinguishing that from verified physical-part identity.
- **Q05, both passes:** judge 2 for faithful missing-cost treatment. Strict rules fail because the prose lacks the exact phrase “not recorded” and the total-cost citation has an Undetermined marker, although cleanup deliberately makes that zero placeholder undetermined. These known rubric conflicts remain strict failures.
- **Q09, pass 2:** all six names and citations appear, but required IDs **D-024 and D-028** are absent from the answer prose. The strict completeness rule fails; judge 2 does not override it. Citation-marker text is excluded from literal key-value matching.
- **Q13, both passes:** strict abstention failure and judge 0. New prep supplies an AI-verified template width of 110 mm, whereas the frozen case requires Undetermined. The judge also questions whether the vertical dimension is width or height and flags unreviewed certainty/attachment support. Agent visual QA found overall dimensions 180 × 110 mm; it is not a human review. This source-state/rubric and axis-language issue remains unresolved, with scores preserved.
- **Q17, both passes:** the failed weight check, geometry and omissions are disclosed, but manual approval and numerical weight comparisons are omitted. The explicit comparison request still warrants these details under current UI steering. Strict review-caveat checks fail; judges give 1 twice.
- **Q02/Q06/Q20, pass 1:** Q02 contradicts its opening count of 9 with the eventual 10 (judge 1). Q06 and Q20 add attachment-absence claims that their cited whole-part facts do not establish (judge 1 and 0). The supplier/stock content itself is faithful; Q20 passes the literal rules in this run. The judge payload contains the returned fact ledger, not a separate attachment inventory; review these citation/evidence limitations without inferring a corrected score.
- **Q10/Q12/Q14, both passes:** judges give 1. Q10's material answer is correct, but its added conflict/translation claims are disputed; the judge regards the English rendering of Danish “rustfri og alu” as unsupported despite current English-translation steering. Q12 omits the older unreviewed-AI warning while the latest customer prompt suppresses routine diagnostics. Q14 omits explicit A/B switching and frames thickness options as competing readings, as the app's uncertainty instructions permit. These judge/prompt tensions need actual human spot-checks; no rule or score was changed to resolve them.

## Usage, latency and monetary evidence

The 42 answers used **948,233 input + 10,003 output = 958,236 tokens**. Two additional Q11 proposal chats used **70,915 input + 677 output = 71,592 tokens**, giving **1,029,828 chat tokens including setup**. Median answer latency was **4,370.5 ms**, range **2,300–26,268 ms**; summed answer latency was **228,969 ms**. Summed case wall time, including correction setup/review overhead, was **265,667 ms**.

Judge receipts report **84 uncached input**, **1,496,841 cache-creation input**, **525,777 cache-read input**, and **24,928 output tokens**. Summed judge-call latency was **410,535 ms**. `metadata.total_cost_usd` totals **USD 12.5787794**, matching summed `modelUsage.costUSD`, with cost basis **list**. This is CLI-reported metadata, not an invoice or verified account charge. Chat monetary cost and the all-in dollar total remain **unknown** because no chat monetary receipt is returned.

## Evidence and human review

The [frozen draft](benchmark_draft.md) remains unapproved ground truth; its SHA-256 is `62098867c412942326997b292999c7208b1b7ec00652a2b8657c210f71921fe5`. Exact questions, expected answers, strict rules and the default judge prompt were preserved. Expected answers were sent only to the independent judge, not to chat/prep. [manifest.json](manifest.json) preserves input/code/settings fingerprints and capture-time status; its historical judge-pending message predates the merged [report.json](report.json).

[executions.jsonl](executions.jsonl) and the per-pass files retain responses, citations, facts, attachments, usage and latency. [judge-inputs.jsonl](judge-inputs.jsonl) and [judge-results.jsonl](judge-results.jsonl) retain exact cache-key-linked inputs, decisions and provider metadata. Q11 acceptance occurred only in isolated clones as **Automated verification**, not Jason Peng. The capture reports production evidence and append-only decisions unchanged.

**Human judge spot-checks: 0; pending.** Suggested unchecked decisions: [pass 1 Q10](pass-1/Q10.json), [pass 1 Q12](pass-1/Q12.json), [pass 1 Q13](pass-1/Q13.json), [pass 1 Q20](pass-1/Q20.json), and [pass 2 Q09](pass-2/Q09.json). Find each decision via its `judge_cache_key` in the merged report. Agent QA and automated workflow acceptance do not count as human review. This consolidation changed only this capture directory and ignored judge runtime/cache outputs; it did not modify app code, source evidence, canonical expectations or previous reports.
