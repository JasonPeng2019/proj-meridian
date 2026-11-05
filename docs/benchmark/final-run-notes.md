# Final benchmark: pre-run notes

**Status: final capture and judging completed.** See [run 42020759881](run-42020759881/README.md) for the actual results. The notes below preserve the pre-run state and caveats; they are not a final model inventory or score report. At that pre-run point, the primary prep run had completed all 45 jobs and the original three reconstructions were refined to retain 14, 8 and 3 supported cuts. Final integration subsequently verified nine parts/twelve variants before the unchanged two-pass capture.

The canonical [question draft](../Question-benchmark/benchmark_draft.md), derived case expectations and current [scorer](../../backend/evaluation/benchmark.py) remain frozen. Keep expected answers out of chat/prep inputs. Preserve previous reports, including [run 41997526697](run-41997526697/README.md): that capture is a historical baseline from before the latest UI, prompt and prep changes, not a measurement of the final implementation.

## Current presentation versus the frozen rubric

The latest user requirement keeps ordinary answers concise: detailed verification, weight failures, omissions and review requirements live in Debug. If a simple status helps, customer answers use **Human reviewed**, **AI reviewed** or **Unavailable**. Explicit requests for model comparison or verification still receive the requested diagnostics and assumptions. Missing/conflicting evidence still requires honest abstention and valid source citations.

The frozen draft predates that steering. Q12's expected prose calls out an unreviewed blurry-scan reading; older judge expectations also penalized Q04 for omitting a reconstruction/failed-check caveat on an ordinary material answer. Those expectations may conflict with the current presentation requirement. The scorer has **no blanket literal requirement for the old AI-warning sentence**: Q12's numerical/citation rules and abstention alternative remain separate from the meaning judge's uncertainty assessment. Document any disagreement without silently changing scores or teaching the app the draft's wording.

Q17 explicitly asks whether the model matches the drawing, so its requested comparison still needs the relevant failed-check evidence, assumptions and manual-review detail; the existing literal `FAILED` and review-caveat checks remain unchanged. Other known tensions also remain: Q05's missing-price wording/Undetermined checks, Q20's literal prohibited “in stock” phrase even in negation, and Q14's possible-readings versus alternative-thickness framing. Report strict rules and independent meaning judgments separately; a presentation change does not authorize a rubric exception.

## Approval and review prerequisites

A genuine Jason Peng mapping decision now exists for **`names/material/3-3315-en-aw-5005 -> aluminium`**, accepted as **`same`** on 2026-11-05 at 09:43:39 UTC ([decision record](../../decisions/HD-156ca4ef74714ddcb83c9ed98165aa6c.json)). Preserve that exact relationship; do not relabel it `kind_of`, extend it to other alloys, or infer blanket mapping approval. Re-evaluate its source-fingerprint applicability against the final snapshot. Optical/Optics and other general-material mapping prerequisites remain pending; Q08's actual drawing links and deduplication also need the final-state check. Q09's exact printed-grade search does not require general Aluminium approval.

**Human judge spot-checks: 0; pending.** Mapping review and automated Q11 workflow acceptance do not count as judge spot-checks. Retain Q11's clean isolated before/after state in both passes, with automated acceptance attributed only to **Automated verification**, never Jason.

## Current projected-data preflight

Read-only inspection on 2026-11-05 found **211 projected part cards: 30 drawing cards plus 181 standalone BOM cards**, representing 192 distinct BOM rows. Eleven BOM rows link to eleven drawing cards; no BOM row is shared by multiple drawings in this projection. The existing model manifest still contains only D-013, D-025 and D-026. Extra expansion candidates remain unintegrated. This snapshot's `generated/records.json` SHA-256 is `aa7e5e96e6656583a214abe390a30be2a39c0eb631497ac55e499116257d0909`; recheck after expansion rather than carrying these counts forward as final results.

Both actual human decisions replay, with **zero source-changed decision events**. The 5005/Aluminium mapping projects as `human_confirmed`, relationship `same`; the prior-proposal/unchanged-source compatibility record preserves that acceptance across regenerated AI receipt fingerprints. The [other decision](../../decisions/HD-6532a09332a04a35b2dcf6593773e0db.json) retains D-013 thickness options **3 mm and 6 mm**, selecting neither. Neither decision is blanket design approval. Of 11 mapping records, only the 5005 mapping is confirmed; **10 remain pending**, including Optical/Optics, 6061/Aluminium and 7075/Aluminium. Q03's approval prerequisite therefore remains unmet.

The current deterministic **Aluminium search returns 33 projected cards**, covering all 29 distinct Aluminium BOM rows plus four unlinked drawing cards admitted by the approved 5005 mapping: D-013, D-024, D-025 and D-028. Linked drawing/BOM evidence appears on one card, not twice. This is the current projection count, not a verified physical-part total: unresolved drawing-to-row identity can still represent duplicates.

| Q08 flagged drawing | Current link | In Aluminium search? |
|---|---|---|
| D-016, Galvo Bundplade | Unresolved; no BOM row attached | No |
| D-017, Galvo Montage Plade | Unresolved; no BOM row attached | No |
| D-018, Galvo Mount Side x2 | Unresolved; no BOM row attached | No |
| D-025, Bygge Base Ring | Unresolved; no BOM row attached | Yes, through the approved 5005 mapping |

Thus Q08's full-material-mapping and four-link prerequisites remain pending; source-supported partial search coverage does not satisfy them. In contrast, exact **EN-AW 5005** search currently returns **six drawings: D-012, D-013, D-014, D-024, D-025 and D-028**, each supported by its own printed `3.3315 (EN-AW 5005)` material fact and exact-grade token. This establishes retrieval availability for Q09, not an answer/judge pass.

The coordinator reports the existing geometry check **42014475161** passed and cached UI suite **42015799070** passed **171 tests**. Those integration checks cover their saved versions; they are not a final expanded-model benchmark. Expansion, final packaging, the new 42-answer capture and its Opus judging remain pending. This preflight used only existing local records and in-memory projection; no expected answers were sent to the app or prep, and no providers, builds, tests, CAD generation or Git operations ran.

## Final execution boundary

After packaging stabilizes, capture the unchanged 21-case set twice against `gpt-6-luna` (42 answers), sequentially on the queued GitHub-hosted workflow. Freeze code/settings/evidence and record fingerprints, responses, facts, attachments, tokens and latency. Then judge those saved answers locally with independent **Claude Opus regular mode**, sequentially through the existing adapter. Keep missing prerequisites explicit, retain monetary cost as unknown without a receipt, and require all applicable rules plus judge score 2 for a combined pass. Save actual human spot-check status without manufacturing review. This note performs no capture, judging, rescoring or evidence changes.
