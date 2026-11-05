# Human CAD feasibility compared with generator coverage

**Estimate from reviewing all 30 supplied drawings: 23 can support useful dimensioned CAD, including partial models. The shipped generator produced 9 of those 23, about 39%.**

This is an AI desk review of the available drawings, not a measured human CAD trial or a human engineering approval. It answers what a human CAD engineer could reasonably construct without the generator's shape restrictions. It does not change any source, template, model, review decision or availability status.

| Available evidence | Drawings | Meaning |
|---|---:|---|
| A: strong candidates for substantially complete nominal CAD | 10 | Main body and functional features are sufficiently specified under the interpretation rules below. D-020 is borderline; D-026 qualifies for its 25 mm variant. |
| B: additional candidates for useful partial CAD | 13 | A dimensioned main body or useful major geometry is available, but some feature positions or local details are missing. |
| C: essential data or design choices missing | 7 | An essential contour or sheet gauge is not fixed. A visual approximation is possible, but would require estimates or chosen dimensions. |
| **Total supplied drawings** | **30** | All 33 pages were visually reviewed, including three D-003 pages and two D-021 pages. |

The 23 candidate count uses the same allowance for partial models that the existing generator uses. It must not be described as 23 fully specified, manufacturing-ready parts. The 181 catalog entries without attached drawings are outside this drawing audit; no additional supplier data or standard-part CAD libraries were retrieved.

## How the classifications were made

- Use printed dimensions, directly derived dimensions and conventional interpretation of clearly repeated or symmetric patterns. Repetition and symmetry assumptions are identified where material.
- Allow cosmetic threads and omission of unspecified minor edge finishing. They do not by themselves make a nominal solid impossible.
- Preserve printed thickness alternatives rather than pretending a human already chose one. At least one internally consistent documented variant must be available for A.
- Do not obtain exact dimensions by measuring pixels or tracing an undimensioned outline. Do not use an unconfirmed mating-part relationship to fill missing dimensions.
- Separate final assembled geometry from manufacturing instructions. Missing bend allowance alone does not make a dimensioned finished sheet-metal body impossible to model.
- A pipeline with no parsed numeric source IDs is an extraction limitation. It does not prove the original image lacks readable dimensions.

## Comparison with what was generated

The shipped pack has 9 parts and 12 thickness variants: D-012, D-013, D-014, D-015, D-017, D-019, D-025, D-026 and D-027.

Six generated parts are in category A: D-012, D-013, D-014, D-025, D-026 and D-027. D-012 still omits its documented transverse M6 holes, so availability does not mean the human-feasible geometry was all captured. Five generated parts retain the documented dimensioned functional cuts within a supported variant: D-013, D-014, D-025, D-026 at 25 mm and D-027. Their existing omission notes still apply.

The other three generated parts are B: D-015 and D-019 are body-only; D-017 includes its central opening but omits other mounting/alignment holes. Four generated parts therefore retain substantial functional omissions when D-012 is included. Comparing nine generated models to ten A candidates would overstate complete-model coverage.

Four A candidates were not generated at all:

| Drawing | Human-usable data | Current generator limitation |
|---|---|---|
| D-011, Recoater Arm | Dimensioned L-shaped plate, elbow radii, thickness alternatives and hole patterns | Custom curved outline; scan dimensions are not accepted numeric geometry in the current extraction pipeline |
| D-020, Seal Ring | Ring, groove section, bolt circle and blind-hole dimensions, with the placement caveat below | Stepped/grooved annular body; scan extraction |
| D-023, Build Cylinder | Dimensioned axisymmetric section and axial steps | Revolved/stepped sleeve and taper; scan extraction |
| D-028, Heating Element Plate | Dimensioned capsule outline and three holes; 2/3 mm thickness alternatives | Obround outline is outside the rectangle/circle/ring subset |

The fourteen additional candidates beyond the shipped nine are D-001, D-002, D-003, D-004, D-005, D-007, D-010, D-011, D-016, D-018, D-020, D-023, D-024 and D-028. Ten of those fourteen would still be partial models under this assessment.

## Drawing-by-drawing assessment

All dimensions below are nominal millimetres. Source links open the supplied PDFs. Image/source hashes and the generated-pack comparison are retained in [the structured audit](human-cad-feasibility.json).

| Drawing | Class | Evidence and remaining gaps |
|---|---|---|
| [D-001, Door](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-001.pdf) | B | 492 x 515 x 3 body and 287 x 200 opening. Hole positions/pitches, opening placement and corner radii are not fixed. |
| [D-002, Left Wall](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-002.pdf) | B | 775 x 578.90, 23 flange depth and 2 sheet gauge establish a useful formed body. Opening and hole/nut locations are missing. |
| [D-003, Main Platform](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-003.pdf) | B | Three sheets establish 600 x 775 x 20, R3 corners, large opening/recess and slots. Numerous threaded-hole sizes/depths are given without a complete positional definition. |
| [D-004, Top Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-004.pdf) | B | 775 x 650 x 3 and 25 flanges support the main body. Large opening centers and hole-pattern coordinates are incomplete. |
| [D-005, Window Clamp Frame](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-005.pdf) | B | Envelope, window seat, opening and section data support a useful frame. Hole pitches, corner radii and complete local groove/relief placement are missing. |
| [D-006, Canister Wall](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-006.pdf) | C | Envelope/gauge are given, but essential irregular lower/right contour vertices, slopes and transitions are not dimensioned. A traced contour would be an estimate. |
| [D-007, Dispenser Shaft](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-007.pdf) | B | Stepped shaft diameters, lengths and groove section/spacing are present. Curved longitudinal groove path, axial endpoints and runout are not defined. |
| [D-008, Powder Bracket](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-008.pdf) | C | Overall spans and gauge alternatives exist, but essential profiled/sloping web geometry and slot definition are missing. |
| [D-009, Powder Canister](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-009.pdf) | C | Some envelope and interface dimensions exist. Wall gauge is free-choice; shoulder/taper/neck breakpoints and outlet slot dimensions are not fixed. |
| [D-010, Motor Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-010.pdf) | B | Main envelope, 2 sheet gauge and opposing flange extents support a formed body. Hole positions, local corner radii and relief details are incomplete. |
| [D-011, Recoater Arm](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-011.pdf) | A | 348 x 195 L envelope, 25-wide legs, R35/R60 elbow and 12/15 thickness alternatives. Hole offsets/pitches are present. Four M5 holes use the clearly regular row with its single 82 pitch label. |
| [D-012, Recoater Mount Block](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-012.pdf) | A | 120 x 25 x 15 with orthogonal M6 pairs at +/-40 and +/-30 around centerlines. A human can build all four bores; the generator omitted the side pair. |
| [D-013, Recoater Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-013.pdf) | A | Body, thickness alternatives, four slots and both threaded-hole groups are dimensioned. Uses the regular-row interpretation of the 35.7 pitch. Small corner finishing is unspecified. |
| [D-014, Recoater Linear Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-014.pdf) | A | Body and M5/countersink pattern sizes, positions and opening faces are specified. Only unspecified minor edge finishing remains. |
| [D-015, Silicone Wiper](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-015.pdf) | B | Exact 270 x 14 x 1 strip, eight 3.4 holes. Hole pitch, end offsets and transverse row offset are absent. |
| [D-016, Galvo Bottom Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-016.pdf) | B | 200 x 283.5 x 10, lower R15 corners and located 145 opening. Small mounting-hole positions are missing. |
| [D-017, Galvo Mounting Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-017.pdf) | B | Body and central 42 opening have dimensions. Other mounting-hole coordinates and dowel-hole horizontal locations are missing. |
| [D-018, Galvo Mount Side](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-018.pdf) | B | 95 x 120 x 10 sloping envelope, two 15 extents and upper R15 support most of the body. Lower fillet radius and six M4 edge-hole positions are missing. |
| [D-019, Silicone Gasket](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-019.pdf) | B | Exact 141/118 annulus, thickness 1 and six 4.5 holes. Bolt-circle radius is absent. |
| [D-020, Seal Ring](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-020.pdf) | A, borderline | 141/118.6 ring, 9.8-10.2 thickness limits, groove section and blind M4 bolt circle are supplied. Requires conventional equal spacing and symmetric axial groove placement; an explicit groove-center offset is not printed. |
| [D-021, Blower Outlet](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-021.pdf) | C | Two pages explain the welded assembly, some interface dimensions and G2 nipple. Sheet gauge is free-choice and the full duct transition contour is not specified. |
| [D-022, Inlet Box](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-022.pdf) | C | Much of the enclosure envelope is dimensioned. Gauge is explicitly free-choice; perforation pitch/offsets and some mounting positions remain unspecified. |
| [D-023, Build Cylinder](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-023.pdf) | A | Axisymmetric section provides bore/fit diameters, 280 axial length, step locations and entry taper. Nominal functional geometry can be revolved. Minor exterior surfaces are labelled nonfunctional. |
| [D-024, Build Base](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-024.pdf) | B | Stepped body and major bore dimensions/locations are available. Multiple small M4/Helicoil-hole offsets and pitches are incomplete. |
| [D-025, Build Base Ring](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-025.pdf) | A | 250/224 annulus, 2/3 thickness alternatives, R115.5 eight-hole circle and countersinks. Uses the shown regular eightfold arrangement. |
| [D-026, Build Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-026.pdf) | A, 25 mm variant | 250 disk, R105 three-hole pattern and counterbores are specified. A blind counterbore 15.4 deep fits the 25 thickness but conflicts with the printed 15 alternative. |
| [D-027, Cylinder Clamping Ring](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-027.pdf) | A | 330/264 annulus, thickness 15, R148.5 and 60/120-degree hole arrangements with opposite-face sink/bore details. Functional geometry is supplied. |
| [D-028, Heating Element Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-028.pdf) | A | Capsule outline: height 11, R5.5 ends and 19 between end centers. End holes 4.5 and central hole 8; thickness 2/3 alternatives. Tangency and symmetry establish the remaining nominal locations. |
| [D-029, Z-axis Bottom Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-029.pdf) | C | Thickness and bore/thread details exist, but the three-lobed exterior has no controlling dimensions. Hole-center coordinates are also absent. |
| [D-030, Z-axis Motor Plate](../../project-meridian_Avathon/project-meridian/dataset/drawings/D-030.pdf) | C | Bore/thread/local recess details exist, but the three-lobed outline and hole positions are unspecified. Total plate gauge is also unclear; the local 4 depth is not a reliable total-thickness dimension. |

## Uncertainty in the estimate

D-020 is the main A/B borderline. Requiring an explicitly dimensioned groove-center offset moves it from A to B: the strong-candidate count becomes 9, the partial count becomes 14, and the useful-candidate count stays 23. D-018 remains B because its dimensioned sloping envelope supports useful partial geometry even though the lower local fillet is unresolved. C is reserved for more substantial missing principal contour or gauge choices.

A human can also trace or design the missing details in C drawings, and may construct visual approximations for all 30. That would be a different standard from a reconstruction supported by documented dimensions. No exact claim of human impossibility is made for any drawing.

The generator's [existing scope report](model-scope.md) remains the record of actual exported geometry. This feasibility review does not expand that scope or approve those exports.
