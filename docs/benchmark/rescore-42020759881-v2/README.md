# Corrected benchmark evaluation, version 2

The same 42 saved chat answers now score **40/42 (95.2%)**, compared with the original **22/42**. All 21 cases remain. Eighteen previously failing or pending results now pass. The two actual count errors still fail.

This regrade uses the answers captured in [run-42020759881](../run-42020759881/README.md). It measures the effect of repairing the evaluation. The chat answers, original questions, original scores and original evidence remain unchanged. It does not measure a newly improved chat model.

| Measure | Original evaluation | Corrected evaluation |
|---|---:|---:|
| Automatic checks pass | 31 | 40 |
| Automatic checks fail | 7 | 2 |
| Automatic checks pending | 4 | 0 |
| Independent judge gives full credit | 27 | 40 |
| Combined pass | 22 | 40 |
| Combined fail | 18 | 2 |
| Combined pending | 2 | 0 |

Pass 1 scores 19/21. Pass 2 scores 21/21. Nineteen of the 21 paired cases receive the same combined result in both passes.

## What changed

The [case audit](../rubric-v2-audit.md) examines every previously failing or pending case. The [versioned contracts](../../../backend/evaluation/contracts.py) define what each question actually asks.

- Equivalent wording, valid unknown-price markers, faithful English translations and correct unit conversions are accepted.
- A named, grounded part card can identify a list item. Drawing IDs do not have to be repeated in prose.
- The judge receives the saved part cards, including drawing/model availability, alongside the source facts.
- Dimension questions use current interpreted evidence rather than the draft's older forced-abstention assumption.
- Concise customer answers do not need unsolicited review warnings, weight tables or instructions for using the viewer. An accuracy question must still receive an honest assessment of model limits.
- Correct behavior under an unapproved mapping is scored now. Missing approval coverage remains visible separately.
- List membership is checked against an independent deterministic catalog query, rather than shrinking the expected list to whatever chat retrieved. Count contradictions are checked explicitly.
- The judge scores substantive correctness and completeness. Awkward style alone does not fail a correct answer.

## The two remaining failures

**Pass 1, Q02: Optics parts list.** The answer opens with nine items, then adds the seal ring and says the total is ten. Ten is the correct total. The contradictory opening is an answer defect.

**Pass 1, Q08: aluminium parts.** The answer says 29 parts, while its positive list contains 30 entries and the current exact/approved-mapping search has 33 matching records. It also places three linked parts under Undetermined without preserving their known BOM Aluminium entries clearly enough. Their combined drawing material can remain unresolved while the BOM evidence remains known.

The 33 search records are 29 distinct matching BOM rows plus four unlinked drawings covered by the approved 5005 mapping. They do not establish an exact count of distinct physical parts. Pending alloy-family mappings are not used to require additional matches.

## Checks on the repaired evaluation

All **17 independent judge controls passed**: 14 deliberately incorrect answers were rejected and three correct negated statements were accepted. The controls cover contradictory counts, fabricated mapping approval, a free-price claim from a zero placeholder, false attachment absence, steel-only material, an omitted grade match, an invented alloy grade, wrong weight units, swapped dimension axes, unsupported thickness selection, invented torque, a false complete-model claim and an unsupported current-stock claim.

These controls are synthetic test data. Their expected labels are stored separately and are never supplied to the judge. They are not engineering decisions or human approvals.

There are **65 passing focused local tests**, including replay provenance and capture-preservation tests. Broader Python checks and frontend compilation run on GitHub-hosted Actions; details are in [verification.json](verification.json). CAD, extraction and browser regeneration were unnecessary for this evaluator change.

The judge is the configured Opus CLI at regular speed, protocol 2. All 59 judgments ran sequentially with the existing local resource gate. No chat API recapture was performed. No human judge spot-check or new engineering approval is claimed.

## Evidence and replay

- [report.json](report.json) contains every revised result and its old/new comparison.
- [evaluation.json](evaluation.json) fingerprints the original capture, pinned reference inputs, reconstructed reference, oracle implementation and evaluation code.
- [reference.json](reference.json) contains answer-independent list expectations from hash-matching original prepared data and decisions.
- [judge-inputs.jsonl](judge-inputs.jsonl) and [judge-results.jsonl](judge-results.jsonl) retain the fresh 42 judgments. Legacy judge results were not relabeled or reused as protocol-2 judgments.
- [control-report.json](control-report.json), [control-expectations.json](control-expectations.json), [control-inputs.jsonl](control-inputs.jsonl) and [control-judge-results.jsonl](control-judge-results.jsonl) retain the 17 controls.

Replay uses `python -m scripts.rescore_benchmark --capture docs/benchmark/run-42020759881 --output <new-directory> --reference-root <original-catalog-snapshot>`, followed by `scripts.judge_benchmark` and a second replay with `--judge-results`. The reference snapshot must contain the five original generated JSON inputs and original decision set whose hashes are listed in `evaluation.json`. Those generated files came from the downloaded artifact of Actions run 42020759881. Current regenerated data are rejected if their bytes differ. Use a fresh output directory when evaluation code, reference behavior or capture inputs change.

Four executions retain approval/link coverage gaps: Q03 and Q08 in both passes. They are reported separately from answer correctness. The original draft remains a draft, and the human spot-check count remains zero.
