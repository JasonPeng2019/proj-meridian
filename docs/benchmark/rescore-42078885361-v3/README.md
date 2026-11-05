# Corrected evaluation, version 3

The unchanged [42 saved answers](../run-42078885361/README.md) score **38/42 (90.5%)** under rubric v3, compared with 34/42 under v2. Both passes score 19/21. All 42 receive full semantic credit from the configured independent Claude Opus regular-mode judge. Four technical citation-state failures remain; they are not waived.

No chat API calls, extraction, CAD, frontend builds or engineering decisions were performed locally for this replay. The original questions, answers, facts, review receipts and earlier reports remain unchanged. Reference inputs were reconstructed from the capture artifact and the original 482 decisions, with every required input checked against its capture-time hash. Fresh v3 judgments were generated; v2 scores were not relabeled. The judge used at most eight resource-gated CLI readers.

## Corrections

- **Q08:** a count may describe an explicitly enumerated subgroup rather than the whole catalog. Both answers identify 30 primary entries and two additional entries with known Aluminium BOM evidence but unresolved combined material. Their group counts are accepted only when distinct cited catalog identities support the enumeration and the source-linked remainder is explicit. Compact grouped bullets and one-part-per-line lists are both supported. Wrong group counts, contradictory global totals, duplicate identities, omitted remainder identities and missing independent catalog coverage still fail. The semantic judge separately checks meaning and whether a claimed physical-part count is justified.
- **Q11b:** the question asks for the current title. A correct, cited title does not require the old `Description` placeholder or unsolicited change history. The old placeholder as the current title and a fabricated Jason approval still fail.
- Citation diagnostics now distinguish missing fact identifiers from an Undetermined marker applied to a known fact. This changes diagnosis, not the acceptance boundary.

## The four remaining failures

Each occurs once in each pass. Retrieval supplied the needed facts and their states.

| Case | Model behavior | Classification |
|---|---|---|
| Q10 | Describes the drawing material as unclear but uses `[cite: D-026/drawing/material]` for a field whose display state is Undetermined. | Model output-protocol error: wrong state marker. The natural-language uncertainty is correct. |
| Q15 | Correctly says no torque is supplied, then uses `[undetermined: D-013/drawing/callout/p1-1]` on the known M5-hole callout. | Model output-protocol error: uncertainty about torque is incorrectly attached to a known hole specification. |

The Q15 callout **exists in the returned fact ledger and was retrieved**. An earlier explanation incorrectly called it missing because the old diagnostic combined missing identifiers and state mismatches under `invalid`. The saved trace disproves that diagnosis. Neither remaining failure establishes missing retrieval or an incorrect engineering answer; neither justifies treating a citation-state mismatch as a pass. No output validator or answer-repair retry was introduced.

## Verification and evidence

All **21 semantic controls passed**, including deliberately wrong counts, fabricated approvals, unsupported grades, missing list entries, incorrect units, invented torque, false model completeness and current-stock claims. Positive controls include a concise current title and the complete partitioned material list. Controls are synthetic fixtures; their expected labels are stored separately from judge inputs. Production approval state is not assumed by the fabricated-approval control.

Regression tests additionally check both captured list presentations, subgroup and total errors, duplicates, missing remainder identities, concise/correct versus stale titles, uncertainty-state markers and genuinely missing fact identifiers. Tests and frontend compilation run on GitHub Actions; [verification.json](verification.json) records the result. No additional geometry or browser run is required for these evaluator-only changes.

[report.json](report.json) contains merged scores and per-execution v2/v3 comparisons. [evaluation.json](evaluation.json) binds the original capture hashes, catalog snapshot, oracle implementation and evaluator source. [reference.json](reference.json), [judge-inputs.jsonl](judge-inputs.jsonl) and [judge-results.jsonl](judge-results.jsonl) preserve the scoring inputs and judgments. [control-report.json](control-report.json) preserves all control outcomes. The frozen draft remains unapproved ground truth; **human judge spot-checks: zero**. Remaining link coverage gaps are reported separately, without inventing reviews.

The older capture's [40/42 corrected replay](../rescore-42020759881-v2/README.md) remains valid for that different set of answers and evidence. It is not replaced by this new capture's result. Token usage for the saved chats is unchanged; this replay adds only independent CLI judge usage.
