# Project Meridian: Evidence-Grounded Drawing Intelligence

[Avathon](https://www.avathon.com) is an industrial AI company that builds and
offers an autonomy platform for physical AI. We work with customers who
manufacture parts and equipment, where the operational knowledge lives in BOMs,
2D drawings, and 3D geometry that have to stay connected, inspectable, and
correctable. This challenge is a compressed version of that problem: turn
drawing and BOM evidence into a knowledge system an engineer can actually use.

## Mission

Create a simple locally runnable app that helps an engineer explore and question
the design evidence for OpenLPBF v2, an open research-grade metal laser
powder-bed-fusion machine.

The required product is a **chat interface over extracted knowledge**, not a
PDF dump or a search box over raw files. A user asks questions in chat; the
system answers from structured knowledge derived from the drawings and BOM;
asking about a part must **open or attach the drawing**, and a 3D
reconstruction when one exists. The app must also include a small
human-reviewed correction loop: propose in chat, accept or reject in a review
UI, show that answers change after acceptance, and keep the original evidence
visible.

The app should also help a user understand how the machine is organized,
connect drawing evidence to bill-of-materials (BOM) rows, and traverse
component and subsystem interfaces. Materials, validation states, recorded
costs, and recorded suppliers in the BOM are source evidence from a pinned
snapshot.

We are interested in the quality of your decisions and experiments, not the
amount of code. Stack, models, and UI framework are up to you.

## The dataset

`dataset/` describes one OpenLPBF v2 machine through:

- 30 selected fabrication drawings spanning six connected subsystems: **Box**,
  **Powder**, **Recoater**, **Optical**, **Gas Flow**, and **Z-axis**;
- the full pinned BOM, with custom and purchased components, materials,
  quantities, suppliers, supplier order numbers and links, costs in DKK,
  `Design`, `Order`, and `V&V` states, design intent, notes, and free-text
  `Interface with` relationships;
- upstream documentation and system diagrams that provide additional context.

Most supplied drawings retain their clean upstream presentation. Eight are
deterministic scan-like derivatives distributed without their pristine
counterparts. These noisy documents test robustness while retaining public
source provenance in the manifest. Treat clean and degraded documents alike as
evidence, not guaranteed truth; preserve uncertainty when text or geometry is
illegible.

The BOM is source evidence from a pinned snapshot, not guaranteed current
procurement truth. Fields may be blank, misspelled, duplicated, inconsistent,
or stale. Supplier links, prices, order numbers, and availability may have
changed, and inclusion is not an endorsement.

See `dataset/README.md` for an orientation, `ATTRIBUTION.md` for source and
license notices, and `dataset/manifest.json` for the asset inventory and
provenance.

## What to build

Build an end-to-end locally runnable app, not disconnected notebooks. Derive
useful structured knowledge from the supplied evidence, answer from that
knowledge, and make it possible to inspect why an answer was produced.

### Required

These are the product bar. A submission that misses any of them is incomplete.

**1. Chat over extracted knowledge.** The primary way to ask questions is chat.
Answers must come from knowledge you extracted and structured (drawing fields,
BOM rows, links, uncertainty), not from stuffing PDFs into a context window
and dumping retrieved pages. Cite the supporting evidence (page, crop, region,
BOM row, extracted text, or equivalent). If the evidence is missing, noisy, or
conflicting, say so and abstain rather than guess.

**2. 2D view plus orbitable 3D for at least 3 parts.** For a minimum of **3**
parts, the user must be able to inspect the 2D drawing and orbit a 3D
reconstruction built from that drawing. Label the 3D clearly as a
**reconstruction from 2D evidence**, not native CAD. You do not have
vendor solid models in this corpus; do not present the reconstruction as if
you do. Prefer clean, geometrically simple parts for this requirement. Noisy
or degraded drawings are for uncertainty testing, not a 3D requirement. You
do not need to reconstruct all 30 drawings.

**3. Chat must drive the visual.** Asking about a part in chat must open or
attach that part's drawing. If you have a 3D reconstruction for that part, the
same turn must make it available (open, attach, or deep-link). A chatbot that
cannot show the sheet fails this requirement, even if the text answer is
correct.

**4. One governed correction.** A user proposes a correction in chat. A
separate review UI lets a human inspect how it was checked and accept or
reject it. After acceptance, the same question must produce a changed answer.
The original evidence and a reviewable history remain visible; nothing is
silently rewritten.

### Bonus

If the required product is working, these are valued extras, not substitutes
for the bar above:

- **Potential part suppliers.** Go beyond the recorded BOM supplier snapshot:
  suggest who could make or supply a part, with the basis for the match and
  the same temporal caveats as other procurement claims.
- **Knowledge graph.** An interactive graph of parts, drawings, subsystems,
  materials, interfaces, and other relationships you extract, reachable from
  chat or a dedicated view.
- **Richer learning system.** Expand the single required correction into a
  broader loop: more update types, ingest of a new drawing, verification
  before acceptance, or measurements that show the system improved.

### Design questions worth considering

- How can drawing fields and BOM rows be linked while retaining both sources?
- How should free-text interface with evidence support traversal across
  components and subsystems?
- How should material, supplier, cost, and validation claims expose missing or
  conflicting values?
- What should happen when a noisy drawing is illegible or disagrees with the
  BOM?
- How do you reconstruct enough geometry to orbit a part without claiming
  native CAD?
- How should proposed corrections be reviewed, accepted or rejected, and
  audited without erasing prior knowledge?
- How do you know whether the system improved?

These are design questions. Choose and justify an approach rather than trying
to infer a required internal architecture.

## Questions the chat should handle

Your chat should support useful questions across more than one document. We
are especially interested in questions involving:

- machine, subsystem, drawing, and BOM organization;
- drawing-to-BOM evidence and component interfaces;
- shared materials across different parts;
- recorded supplier, order-number, and cost evidence with temporal caveats;
- clean-versus-noisy document behavior;
- uncertainty, disagreement, missing information, and appropriate abstention;
- the behavior and audit history before and after an accepted correction.

`fixtures/public_questions.json` contains examples, not a test contract. You
may add or substitute questions that better demonstrate your system. Include
at least one question that names a reconstructed part so we can see chat
open the drawing and 3D.

## Evidence and trust

We will ask you to show where important facts and relationships came from.
Useful evidence might be a page, crop, drawing region, BOM row, extracted text,
diagram, or another representation you consider appropriate. Distinguish a BOM
claim from a drawing claim and a recorded supplier from current availability.
Distinguish a 3D reconstruction from native CAD.

Avoid presenting guesses as facts. Make uncertainty, unsupported questions,
source conflicts, and abstention visible in a way that helps a user decide
what to trust. You decide how confidence, repeated observations, review, or
other techniques fit into the solution.

## Submission

Submit the source code and everything needed to run the app locally. Include:

- concise setup and launch instructions;
- a short explanation of the architecture and key decisions;
- examples of questions the app handles well, including at least one that
  opens a drawing (and 3D when present);
- known limitations and an analysis of important errors;
- the models, services, and external data used;
- measurements or observations about quality, reproducibility, cost, latency,
  and important failure modes;
- enough saved output or screenshots to review the result if a paid service is
  unavailable: chat turns, the 2D/3D view for the reconstructed parts, and the
  correction before/after.

Use any language, models, storage system, graph representation, or UI
framework. Keep credentials out of the submission and disclose if supplied
files are sent to an external service.

## What we want to evaluate

We will evaluate how effectively the solution:

- answers in chat from extracted knowledge rather than raw document dump;
- opens or attaches the drawing (and 3D when built) when a part is discussed;
- reconstructs orbitable 3D for at least 3 parts and labels it as
  reconstruction, not native CAD;
- extracts useful information while preserving source evidence;
- discovers and represents relationships across drawings and the BOM;
- answers multi-document questions and communicates uncertainty;
- handles conflicting, noisy, missing, and unsupported information;
- incorporates a chat-proposed, human-reviewed correction without silently
  rewriting accepted knowledge;
- provides an understandable and useful local experience;
- measures quality, cost, latency, reproducibility, and failure modes;
- can be reproduced and explained by its author.

Bonus work on supplier finding, a knowledge graph, or a richer learning
system is scored only after the required bar is met.

There is no preferred framework, graph technology, ontology, or model. We do expect a working self contained version of the code that can run with simple start script and all requirements built in and documented. 
A smaller coherent system with clear evidence and thoughtful evaluation is stronger than a broad system whose answers cannot be inspected.

## Dataset rights

The supplied files are third-party open hardware material. Preserve the notices
in `ATTRIBUTION.md` and the included license and do not publish the code or results publicly without attribution.
