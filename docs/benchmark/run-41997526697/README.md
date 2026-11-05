# Meridian benchmark baseline: run 41997526697

This is the **pre-UI-refresh, pre-next-prep baseline** for commit `ec186b257cc381a40025a9ab4c06cd100f6b5c2b`. It measures the saved code, settings and evidence at that commit, not the current UI or forthcoming prep results. Actions run **41997526697** captured answers on 2026-11-05, 08:52:27–08:55:57 UTC: two sequential passes, 21 cases each, 42/42 responses, zero execution errors. Q11a/b are separate cases. Chat used `gpt-6-luna`; all 42 independent meaning judgments used Claude Opus regular mode (reported model `claude-opus-5-5`).

The [frozen draft](benchmark_draft.md) remains unapproved ground truth. Its SHA-256 is `62098867c412942326997b292999c7208b1b7ec00652a2b8657c210f71921fe5`. [manifest.json](manifest.json) preserves code/settings/input hashes and capture-time status; its historical “judge pending” text predates the completed local judging. [report.json](report.json) contains the merged results, with **zero missing judges**. No canonical text, literal rule or saved score was changed for this write-up.

## Results

| Measure | Result |
|---|---:|
| Rule pass | 33/42 (78.6%) |
| Rule fail / prerequisite pending | 5 / 4 |
| Rule pass among applicable executions | 33/38 (86.8%) |
| Judge scores 2 / 1 / 0 | 32 / 9 / 1 |
| Combined pass | 26/42 (61.9%) |
| Combined fail / pending | 14 / 2 |
| Pass 1: rule / combined passes | 16/21 / 12/21 |
| Pass 2: rule / combined passes | 17/21 / 14/21 |

A combined pass requires every applicable rule and judge score 2. All-execution percentages retain pending cases in the denominator. Q03 and Q08 have pending prerequisites in both passes; Q08 also has judge score 1, so its combined result is fail rather than pending. Thirty-five executions satisfy the literal predicates when prerequisite coverage is ignored; that is not the rule-pass count.

| Category | Executions | Rule pass | Judge 2 / 1 / 0 | Combined pass |
|---|---:|---:|---:|---:|
| Machine organization | 6 | 4 (66.7%) | 4 / 2 / 0 | 2 (33.3%) |
| Linking drawings to the parts list, and one value per field | 12 | 8 (66.7%) | 9 / 3 / 0 | 7 (58.3%) |
| Uncertainty and honesty | 14 | 14 (100%) | 10 / 3 / 1 | 10 (71.4%) |
| Holes, 3D, and checks | 4 | 3 (75.0%) | 4 / 0 / 0 | 3 (75.0%) |
| Costs, the README, and current information | 6 | 4 (66.7%) | 5 / 1 / 0 | 4 (66.7%) |

Across the two passes, **20/21 cases (95.2%) have the same rule result**, **18/21 (85.7%) the same judge score**, and **19/21 (90.5%) the same combined result**. These are outcome comparisons, not identical-answer claims. Rule results differ on Q17; judge scores differ on Q04, Q10 and Q20; combined outcomes differ on Q04 and Q17. The combined stability count includes Q03's consistently pending result and does not establish its prerequisite coverage.

## Usage, latency and cost

The 42 benchmark answers used **632,450 input + 9,594 output = 642,044 tokens**. Two additional Q11 proposal chats used **30,464 input + 515 output = 30,979 tokens**; including that setup gives **673,023 chat tokens**. Every answer has usage and latency recorded in [executions.jsonl](executions.jsonl). Median answer latency was **3,616.5 ms**, range **1,955–10,468 ms**; summed answer latency was **177,964 ms**. Summed case wall time was **198,202 ms**, including workflow setup/review overhead.

The 42 judge receipts report **84 uncached input tokens**, **1,568,063 cache-creation input tokens**, **124,520 cache-read input tokens**, and **22,533 output tokens**; summed local judge-call latency was **348,462 ms**. Their `metadata.total_cost_usd` totals **USD 13.020404**, equal to the summed `modelUsage.costUSD` entries. The provider labels that cost basis **list**: this is reported CLI metadata, not an invoice or verified account charge. Chat monetary cost remains **unknown** because its API responses provide no monetary receipt; there is no verified all-in dollar total. Per-case judge receipts are preserved in [judge-results.jsonl](judge-results.jsonl).

## Interpretation and unresolved issues

- **Q03/Q08 prerequisite coverage:** Optical/Optics and alloy/general-material mapping approvals remain pending, as do Q08's flagged drawing links. Q03 appropriately abstains and receives judge 2 in both passes. Q08 lists the 29 BOM rows but omits drawing-only coverage and some uncertainty details; both judges give 1. These runs do not establish the approved-mapping expected answers.
- **Q05 rubric conflict:** both answers explain the missing price correctly and receive judge 2. Literal rules reject “unrecorded” or “no unit cost was recorded” for missing the exact phrase “not recorded.” They also forbid an Undetermined marker on the required total-cost citation, although that field is deliberately undetermined because its recorded zero means missing price. Both strict failures remain saved.
- **Q17 wording:** pass 1 says the weight check “fails,” supplies the actual failed-check evidence and manual-review caveat, and receives judge 2. The literal `FAILED` check rejects the inflection; pass 2 passes. The draft's approximate planning weights were not substituted for the actual disclosed model/density values.
- **Q20 negation:** both answers decline to determine whether the laser is “in stock”; the literal prohibited phrase nevertheless fails. Judge 2 in pass 1 reflects the actual negation. Pass 2 receives judge 1 for an additional unsupported claim that no drawing or 3D attachment exists.
- **Q14 judge/rubric tension:** both answers report 2 mm and 3 mm, cite thickness and attach the views, passing all rules. Both judges give 1 for framing the values as possible competing readings rather than the draft's alternative thicknesses; pass 2 also omits explicit switching between A/B. The possible-reading framing is allowed by the MVP's uncertainty instructions. Human review should resolve that tension before changing the rubric or interpreting it as a clear app defect.
- **Other answer issues:** Q02 contradicts itself with an initial count of 9 followed by a list/final total of 10 (judge 1 twice). Q10 incorrectly labels parsed/cleaned BOM material evidence “AI-sourced only” (judge 1 then 0). Q04 pass 1 mentions the attached 3D model without its reconstruction/failed-check caveat (judge 1; pass 2 gets 2). These semantic concerns survive literal rule passes and merit correction/review.

## Human spot-check and provenance

**Human judge decisions checked: 0. Status: pending.** The following five individual decisions are recommended, unchecked samples; listing them is not a review or approval:

| Unchecked decision | What to inspect |
|---|---|
| [Pass 1 Q02](pass-1/Q02.json) | Whether the contradictory 9/10 count warrants score 1 |
| [Pass 1 Q05](pass-1/Q05.json) | Faithful missing-price wording versus two literal rule conflicts |
| [Pass 2 Q10](pass-2/Q10.json) | Incorrect AI-only provenance and the score-0 judgment |
| [Pass 2 Q14](pass-2/Q14.json) | Possible readings, alternative thicknesses and A/B completeness |
| [Pass 2 Q20](pass-2/Q20.json) | Negated stock wording versus the unsupported attachment claim |

Use each case's `judge_cache_key` in [report.json](report.json) to find its exact decision in [judge-results.jsonl](judge-results.jsonl); [judge-inputs.jsonl](judge-inputs.jsonl) preserves the evaluated answer and returned facts. Q11 review acceptance occurred only in isolated clones, under **Automated verification**, in both passes. It is a workflow test, not Jason Peng's approval. The capture manifest reports production evidence and append-only decisions unchanged. This report-only consolidation copied the final judge log and wrote this summary; it performed no new API calls, judging, builds, browser checks or evidence edits.
