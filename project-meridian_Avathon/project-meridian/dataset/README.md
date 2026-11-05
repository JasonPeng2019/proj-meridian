# Dataset orientation

This corpus represents one OpenLPBF v2 research-grade metal laser
powder-bed-fusion machine. Use the files as evidence that may be incomplete or
inconsistent, not as a prebuilt knowledge model.

## Contents

- `drawings/` contains 30 selected fabrication drawings from the Box, Powder,
  Recoater, Optical, Gas Flow, and Z-axis subsystems.
- `context/openlpbf-bom.csv` is the full pinned bill of materials. It includes
  custom and purchased components, materials, quantities, suppliers, supplier
  order numbers and links, DKK costs, lifecycle and validation states, notes,
  design intent, and free-text `Interface with` relationships.
- `context/openlpbf-upstream-readme.md` and `context/diagrams/` provide upstream
  project and system context.
- `context/OpenLPBF-LICENSE.md` is the included CERN-OHL-P-2.0 license.
- `context/openlpbf-source-metadata.json` is a Project Meridian index mapping
  each alias to its upstream path. It is project-generated rather than upstream
  material and is dedicated to the public domain under CC0-1.0.
- `manifest.json` is the authoritative asset inventory and provenance record.

## Evidence caveats

Eight drawings are deterministic scan-like derivatives and do not include
their pristine counterparts. Their public provenance and modification notices
are recorded in the manifest and `../ATTRIBUTION.md`. Systems should expose
uncertainty or abstain when degradation prevents a supported reading.

The BOM preserves a source snapshot, including blanks, spelling variations,
duplicates, inconsistent values, and potentially stale supplier links and
prices. A recorded supplier, order number, cost, or status is evidence about
that snapshot, not a claim about current availability or endorsement.

Drawing and BOM statements can agree, complement one another, or conflict.
Keep their provenance distinct so users can inspect the basis for an answer or
a proposed correction.
