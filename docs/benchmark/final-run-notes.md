# Final benchmark: pre-run notes

**Status: awaiting stable expansion and CAD packaging; no new scores.** The primary prep run completed all 45 jobs, and the original three reconstructions were refined to retain 14, 8 and 3 supported cuts respectively. Prep completion is not proof of correct geometry or a benchmark pass. The final capture and judging will run only after expansion and CAD artifacts stabilize.

The canonical [question draft](../Question-benchmark/benchmark_draft.md), derived case expectations and current [scorer](../../backend/evaluation/benchmark.py) remain frozen. Keep expected answers out of chat/prep inputs. Preserve previous reports, including [run 41997526697](run-41997526697/README.md): that capture is a historical baseline from before the latest UI, prompt and prep changes, not a measurement of the final implementation.

## Current presentation versus the frozen rubric

The latest user requirement keeps ordinary answers concise: detailed verification, weight failures, omissions and review requirements live in Debug. If a simple status helps, customer answers use **Human reviewed**, **AI reviewed** or **Unavailable**. Explicit requests for model comparison or verification still receive the requested diagnostics and assumptions. Missing/conflicting evidence still requires honest abstention and valid source citations.

The frozen draft predates that steering. Q12's expected prose calls out an unreviewed blurry-scan reading; older judge expectations also penalized Q04 for omitting a reconstruction/failed-check caveat on an ordinary material answer. Those expectations may conflict with the current presentation requirement. The scorer has **no blanket literal requirement for the old AI-warning sentence**: Q12's numerical/citation rules and abstention alternative remain separate from the meaning judge's uncertainty assessment. Document any disagreement without silently changing scores or teaching the app the draft's wording.

Q17 explicitly asks whether the model matches the drawing, so its requested comparison still needs the relevant failed-check evidence, assumptions and manual-review detail; the existing literal `FAILED` and review-caveat checks remain unchanged. Other known tensions also remain: Q05's missing-price wording/Undetermined checks, Q20's literal prohibited “in stock” phrase even in negation, and Q14's possible-readings versus alternative-thickness framing. Report strict rules and independent meaning judgments separately; a presentation change does not authorize a rubric exception.

## Approval and review prerequisites

A genuine Jason Peng mapping decision now exists for **`names/material/3-3315-en-aw-5005 -> aluminium`**, accepted as **`same`** on 2026-11-05 at 09:43:39 UTC ([decision record](../../decisions/HD-156ca4ef74714ddcb83c9ed98165aa6c.json)). Preserve that exact relationship; do not relabel it `kind_of`, extend it to other alloys, or infer blanket mapping approval. Re-evaluate its source-fingerprint applicability against the final snapshot. Optical/Optics and other general-material mapping prerequisites remain pending; Q08's actual drawing links and deduplication also need the final-state check. Q09's exact printed-grade search does not require general Aluminium approval.

**Human judge spot-checks: 0; pending.** Mapping review and automated Q11 workflow acceptance do not count as judge spot-checks. Retain Q11's clean isolated before/after state in both passes, with automated acceptance attributed only to **Automated verification**, never Jason.

## Final execution boundary

After packaging stabilizes, capture the unchanged 21-case set twice against `gpt-6-luna` (42 answers), sequentially on the queued GitHub-hosted workflow. Freeze code/settings/evidence and record fingerprints, responses, facts, attachments, tokens and latency. Then judge those saved answers locally with independent **Claude Opus regular mode**, sequentially through the existing adapter. Keep missing prerequisites explicit, retain monetary cost as unknown without a receipt, and require all applicable rules plus judge score 2 for a combined pass. Save actual human spot-check status without manufacturing review. This note performs no capture, judging, rescoring or evidence changes.
