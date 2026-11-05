# Reconstructed model scope

The verified pack contains **9 parts, 12 example variants and 24 STEP/GLB exports**. These are AI reconstructions of the supplied drawings. Each retains some omitted scope; none represents human approval of the complete engineering design. Existing human field decisions remain separate from whole-design approval.

All dimensions below are nominal millimetres. A and B are documented thickness alternatives, not an automatic selection or approval. Threaded features use the stated drill bores and thread labels; helical thread geometry is not modeled. Hole counts describe physical axes: a countersink and counterbore on the same through hole do not create additional holes.

| Part | Primary body and examples | Physical holes and slots retained | Omitted scope |
| --- | --- | --- | --- |
| D-012 | Rectangular plate, 25 × 120 × 15. A only. | Two Ø5 through drill bores for M6-6H threads, on the main face. | Two transverse M6 holes require unsupported side-face cuts. Unspecified edge finishing is omitted. The mounting configuration is partial. |
| D-013 | Rectangular plate, 270 × 25. A: 3 thick; B: 6 thick. | Ten threaded-hole bores: eight Ø2.5 for M3-6H and two Ø4.2 for M5-6H. Four through slots, 5.5 wide × 10 long, with their long axes along Y. Fourteen physical cuts in each example. | Four small visible corner chamfers lack determined setbacks/angles. Unspecified deburring and edge breaks are omitted. |
| D-014 | Rectangular plate, 96 × 167 × 8. A only. | Eighteen through holes: eight Ø4.2 M5-6H drill bores; eight Ø6.6 bores with top-face Ø13.4 × 90° countersinks; two Ø6.6 bores with bottom-face Ø14.4 × 90° countersinks. | Only unspecified edge finishing is omitted. Dimensioned functional hole geometry is retained. |
| D-015 | Rectangular strip, 270 × 14 × 1. A only. | **Body only; no holes modeled.** | Eight Ø3.4 through holes lack established centre coordinates, pitch and offsets. Unspecified edge breaks are omitted. This is not the complete perforated wiper part. |
| D-017 | Rectangular plate, 180 × 110 × 10. A only. | One Ø42 through bore. | Four countersunk holes, eight M5 threaded holes and two Ø6 H7 holes lack sufficient location and/or drill/depth evidence. Four small 1 × 45° outer-corner chamfers and unresolved bore-edge/general edge treatments are omitted. Mounting and alignment features remain incomplete. |
| D-019 | Ring, outside Ø141 / inside Ø118 × 1. A only. | **Body only; no bolt holes modeled.** The central opening belongs to the ring outline. | Six Ø4.5 through holes lack a dimensioned bolt-circle radius; it is not inferred from the ring diameters. Unspecified edge breaks are omitted. |
| D-025 | Ring, outside Ø250 / inside Ø224. A: 2 thick; B: 3 thick. | Eight Ø3.4 through bores, each with a top-face Ø6.9 × 90° countersink, evenly distributed at radius 115.5. | Only unspecified edge finishing is omitted. Both examples retain all eight countersunk bores. |
| D-026 | Disk, Ø250. A: 15 thick; B: 25 thick. | Three Ø5.3 through bores at radius 105. B also retains all three bottom-face Ø10 counterbores, depth 15.4. | **A omits only the counterbore steps:** depth 15.4 exceeds its 15 thickness. All three primary through bores remain. The depth is never clamped. B retains the full steps. Unspecified edge finishing is omitted in both examples. |
| D-027 | Ring, outside Ø330 / inside Ø264 × 15. A only. | Nine through holes at radius 148.5: six plain Ø9 bores and three Ø11 bores. Each Ø11 bore has a top-face Ø24.4 × 90° countersink and a bottom-face Ø20 counterbore, depth 4. | Only unspecified edge finishing is omitted. Dimensioned functional cuts are retained. The three composite bores are counted once each. |

D-014 and D-027 therefore contain their dimensioned functional cuts. D-015 and D-019 are body-only reconstructions; their availability must not be read as a claim that the missing hole patterns have been reconstructed. D-012 and D-017 retain useful cuts but omit functional mounting/alignment features.

## Why the other 21 drawings are blocked

These are generator eligibility decisions. A separate [human CAD feasibility audit](human-cad-feasibility.md) estimates that 23 drawings support useful dimensioned CAD, including partial models, while this pack contains nine. An unsupported template or missing parsed numeric ID does not by itself mean a human lacks usable drawing data.

The assessment covers all 30 drawings: three preserved primary templates, six additional ready templates and 21 blocked drawings. A missing essential contour, thickness or source-grounded dimension prevents a body from being generated. Minor edge finishing may be omitted honestly; an enclosing rectangle or guessed contour cannot replace the essential shape.

| Drawings | Main blocking reasons |
| --- | --- |
| D-001, D-003, D-011, D-016, D-018, D-029, D-030 | Essential rounded, L-shaped, diagonal or lobed contours exceed the rectangle/circle/ring generator. Several also lack accepted parsed numeric evidence for required dimensions. D-016's R15 corners and D-018's sloping/R15 transitions are part of the main outline, rather than minor edge breaks. |
| D-028 | Obround outline with R5.5 ends and centres 19 apart. A 30 × 11 rectangle would replace its essential contour, even though the 2/3 thickness alternatives are visible. |
| D-002, D-004, D-006, D-008, D-010 | Bent/flanged walls, plates or brackets, including D-010's opposing Z-bends. These are not single constant-thickness flat extrusions of a supported outline. |
| D-009, D-021, D-022 | Hollow, tapered or welded assemblies with nonplanar construction. Some thickness instructions are qualitative or free-choice; required geometry cannot be inferred. |
| D-005, D-020 | Essential window seats, O-ring grooves or stepped annular profiles prevent treating the part as one uniform flat body. |
| D-007, D-023, D-024 | Grooved shaft, stepped/tapered sleeve or turned body with multiple axial diameters and shoulders. A flat disk/ring would omit the defining geometry. |

## Verification and traceability

The CAD stage of [Actions run 42020313541](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42020313541) passed 194 tests and independent geometry probes for all 9 parts / 12 variants. Checks covered exported STEP/GLB bounds, volume, physical cut locations and stepped-hole depths; all 24 export hashes and all nine effective template/BOM hashes were checked. This establishes the documented reconstruction scope, not complete equivalence to original CAD or human design approval.

That run's later fresh-clone stage correctly rejected caches that had not yet been shipped; its overall conclusion was therefore failure. The verified model/cache pack was subsequently installed in commit `b40ec11`. See the [run checkpoint](run-42020313541/checkpoint.json) for the stage-level result; release/recovery verification is tracked separately.

The subsequent [final Actions run 42020759881](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42020759881) passed the full sequence: 194 tests, 1,380 STEP/GLB probe points, fresh-clone recovery of all nine parts/twelve variants in 9.924 seconds, every variant rendered, customer/Debug browser sweeps and the isolated live correction workflow. See its [checkpoint](run-42020759881/checkpoint.json). Original evidence and production decisions remained unchanged.

Canonical records:

- [Verified model manifest](../../generated/models/manifest.json): exported examples, geometry, provenance and omitted scope.
- [Candidate inventory](../../generated/ai_cache/model_expansion/model-candidates-20261105T104806207369Z.json): the nine candidates and twelve example variants.
- [All 30 drawing assessments](../../generated/model_assessments.json): per-drawing readiness and blocking reasons.
- [Expansion receipt index](../../generated/ai_cache/model_expansion/receipt-index-20261105T104806207369Z.json) and [receipt cache-key index](../../generated/ai_cache/model_expansion/receipt-cache-keys-20261105T104806207369Z.json): proposal, verification and bounded-retry lineage.
- [D-013 slot-direction repair receipt](../../generated/ai_cache/template_repair/20261105T104514698384Z/checkpoint.json): the verified structured directions used for its four slots.
