# Reviewed-dataset benchmark: run 42078885361

**34/42 combined passes (81.0%)**, with 8 failures and no pending judgments. Both unchanged passes score 17/21. All 21 paired cases have identical rule outcomes, judge scores and combined outcomes. The prior capture's [corrected evaluation](../rescore-42020759881-v2/README.md) scored **40/42**, superseding its original 22/42 evaluation. This is a new answer capture against updated data, not another replay of those earlier answers. The evaluator and question-contract source hashes are identical to that corrected evaluation; the judge adapter additionally supports bounded concurrency. This comparison does not isolate model variability from changed production evidence/review state.

[Actions capture](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42078885361) used `gpt-6-luna` and commit `6182674ab519a459241a94d7966be4a37cc5edfd`. It captured all 42 executions against the reviewed candidate dataset. The independent local Claude Opus regular-mode judge scored 40 answers as 2 and two as 1. Up to eight resource-gated reader jobs were allowed; heavy builds, CAD and browsers remained sequential on Actions. Human spot-checks of judge decisions: **0; still pending**.

The frozen canonical draft, its exact questions and expected answers, capture fingerprints, responses, citations, provider usage and cache-key-linked judgments are retained in this directory. The draft remains unapproved ground truth. Automated Q11 acceptance happened only in isolated copies as `Automated verification`; it is not a production engineering approval. Production decisions were preserved. The reviewed dataset contains authorized delegated source reviews, without claiming Jason personally inspected the evidence.

## Remaining failures

Each appears in both passes; neither scores nor rules were changed to hide them.

- **Q08:** the answer states 30 parts while the captured matching projection contains 32 records. The semantic judge accepts its interpretation, but the count-consistency rule fails. The flagged D-016, D-018 and D-025 drawing-to-BOM links remain unresolved; this is also reported as a coverage gap. D-017 now has a source-backed delegated link decision.
- **Q10:** the answer cites `D-026/drawing/material` without the uncertainty marking required for that captured fact. Both semantic judgments are 2; the strict output rule fails.
- **Q11b:** the answer correctly gives the newly accepted title but omits the original printed `Description` placeholder required by the benchmark. Both the literal check and the semantic completeness judgment fail (judge score 1).
- **Q15:** the answer cites `D-013/drawing/callout/p1-1`, which is absent from the returned fact ledger even though CAD provenance references that source identifier. The judge accepts the factual answer, but the citation rule fails. The resulting source marker cannot resolve through the conversation ledger; no output validator or answer-repair retry was introduced.

## Usage and interpretation

The 42 measured answers use 861,860 input and 7,924 output tokens (869,784 total). Isolated correction setup adds 68,653 tokens, for 938,437 chat tokens including setup. Monetary chat cost remains unknown because the provider returned no monetary receipt. Judge receipts preserve their own usage and metadata separately.

[report.json](report.json) is the merged scoring report; [manifest.json](manifest.json) preserves capture-time fingerprints and historical status. Full capture and judge records are in [executions.jsonl](executions.jsonl), [judge-inputs.jsonl](judge-inputs.jsonl) and [judge-results.jsonl](judge-results.jsonl). The benchmark does not establish that all 30 drawings have complete 3D reconstructions or that a 99.8% reviewed-proposal agreement rate applies to the entire dataset.
