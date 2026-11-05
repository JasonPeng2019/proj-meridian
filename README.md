# Project Meridian, in plain English

Build a local app that lets an engineer ask questions about a metal 3D printer called **OpenLPBF v2**. The app should answer using the supplied engineering documents, show where its answers came from, and let a person review corrections.

Think of it as a chat assistant connected to a parts database, a drawing viewer, and a small 3D viewer.

This guide explains the assignment. The [original brief](project-meridian_Avathon/project-meridian/README.md) is the source for the requirements.

The project files are inside `project-meridian_Avathon/project-meridian/`:

| File or folder | What it gives you |
| --- | --- |
| [dataset/drawings/](project-meridian_Avathon/project-meridian/dataset/drawings/) | 30 engineering drawings: blueprints showing parts, measurements, and manufacturing details. |
| [openlpbf-bom.csv](project-meridian_Avathon/project-meridian/dataset/context/openlpbf-bom.csv) | The bill of materials, or **BOM**: a parts list with quantities, materials, suppliers, costs, status fields, notes, and connections to other parts. |
| [dataset/context/](project-meridian_Avathon/project-meridian/dataset/context/) | Background documentation and diagrams that help explain the machine. |
| [manifest.json](project-meridian_Avathon/project-meridian/dataset/manifest.json) | An inventory showing where each supplied file came from and which drawings were modified to look like poor scans. |
| [refrence_ui/](project-meridian_Avathon/project-meridian/refrence_ui/) | Reference images of a chat interface, document viewer, and 3D viewer. |
| [ATTRIBUTION.md](project-meridian_Avathon/project-meridian/ATTRIBUTION.md) | Source credits and license notices you need to preserve. |

The drawings cover six machine sections, called **subsystems**: Box, Powder, Recoater, Optical, Gas Flow, and Z-axis. You need to connect information across drawings and the BOM so users can understand parts and how they fit together.

Avathon lists **four required features**. Missing any one makes the submission incomplete.

1. **Chat that answers from facts you extracted and organized.**

   Read the drawings and BOM, pull out useful facts, and save them in a form your code can query. For example, a part record could connect its name, subsystem, material, measurements, drawing, matching BOM row, and related parts.

   Keep the source for each fact. A material read from a drawing and a material recorded in the BOM are separate claims, even if they agree. This is what the brief means by preserving **evidence** and **provenance**: users can see the source behind a statement.

   The chat should use those records to answer questions and cite the supporting drawing page, region, BOM row, or extracted text. Simply passing PDFs to a model and displaying relevant pages does not meet this requirement.

   When a fact is missing, unreadable, or disputed, explain that. Saying "I cannot determine this from the supplied evidence" is an expected behavior.

2. **A drawing viewer and rotatable 3D models for at least three parts.**

   Pick at least three parts and create 3D shapes from their 2D drawings. Users must be able to view each drawing and rotate its 3D model to inspect it from different angles. The brief calls this an **orbitable** model.

   Choose clean drawings of simple shapes, such as plates or rings, where the measurements support a reconstruction. Explain any assumptions or missing details.

   Label each model as a **reconstruction from 2D evidence**. The supplied files do not include the original CAD models. You only need to reconstruct at least three parts, not all 30 drawings.

3. **Chat must open the relevant visuals.**

   If someone asks about a part, that chat turn must open or attach its drawing. If that part has a 3D reconstruction, the same turn must also make it available by opening it, attaching it, or providing a direct link to its view.

   For example, asking "Show me this part and explain its dimensions" should produce an answer with evidence and access to the part's drawing and available 3D model.

4. **A correction proposed in chat and approved by a human.**

   Build a complete correction flow. A user proposes a change in chat. A separate review screen shows the proposed change, the evidence, and how it was checked. A person can accept or reject it.

   After acceptance, asking the same question must produce an updated answer. Keep the original evidence and a visible history of the change. A proposed change should affect answers only after acceptance.

   Here is a made-up example: the system extracted a plate thickness as 5 mm, but the drawing clearly says 3 mm. The user proposes 3 mm in chat, the reviewer checks the drawing and accepts it, and future answers use 3 mm. The old extraction and review decision remain available.

The hard part is making the information trustworthy. Eight drawings were deliberately made harder to read, and their clean versions are not included. The BOM also contains blanks, spelling differences, duplicates, and possible inconsistencies. Your app should expose these problems instead of filling gaps with guesses.

Supplier names, order numbers, costs, and status fields describe a saved version of the BOM. For example, say "The supplied BOM records this supplier and price" rather than claiming that the supplier currently has the part at that price. Costs are recorded in **DKK**, Danish kroner. A BOM status is a recorded status, not proof that your app has independently checked the part.

Useful chat questions should cover several kinds of work:

- Which subsystem does a part belong to, and where is its drawing?
- Which BOM row matches a drawing, and what supports that match?
- Which parts share a material, including parts from different subsystems?
- Which components connect to a given part? The BOM's `Interface with` field provides possible connections to interpret.
- What supplier, order number, or cost does the supplied BOM record?
- Does a drawing disagree with the BOM, or is the evidence too unclear to answer?
- What changed after a correction was accepted, and why?

Include at least one demo question naming a part you reconstructed, so the reviewer can see chat open both its drawing and 3D view. The brief mentions `fixtures/public_questions.json`, but that file is missing from this supplied copy. The brief says those example questions are optional examples; you can write your own.

You can choose the language, framework, database, and AI models. The brief specifies the behavior it wants, while leaving the internal design to you. A database with linked records can support the required relationships; an interactive knowledge graph is a bonus.

**A practical build order:**

1. Load the BOM and drawing inventory. Extract useful drawing facts, connect them to BOM rows, and save source references and uncertainty alongside them.
2. Make chat answer a small set of useful questions across multiple documents. Check answers against the source files.
3. Connect chat answers to the drawing viewer.
4. Build and label three supported 3D reconstructions, then connect them to chat.
5. Add the proposed, accepted, and rejected correction states, the review screen, and the history. Demonstrate an answer before and after acceptance.
6. Check clean and noisy documents, missing facts, conflicting sources, and unsupported questions. Record what works and what fails.

That order is a suggested approach, not an additional assignment requirement. A smaller working system with clear evidence is valued more than a large system whose answers are hard to check.

Once the required features work, the **bonuses** are finding potential suppliers beyond the BOM snapshot, building an interactive graph of parts and relationships, or expanding the correction system. Supplier suggestions need supporting evidence and a clear explanation of how current the information is. Bonus features are evaluated only after the required features are complete.

For the submission, provide the source code and everything needed to run the app locally with simple setup and a start script. Include:

- Setup and launch instructions, including any credentials or services the user must configure. Keep actual credentials out of the submission.
- A short explanation of the architecture, key choices, models, services, and external data used. Disclose if supplied files are sent to an external service.
- Example chat questions, including one that opens a reconstructed part's drawing and 3D model.
- Known limitations and an explanation of important errors.
- Measurements or observations about answer quality, repeatability, response time, cost, and failure cases.
- Saved outputs or screenshots showing chat, the drawing and 3D view for the reconstructed parts, and the correction before and after acceptance. These let reviewers inspect the result if a paid service is unavailable.
- The supplied source credits and license notices. The brief requires attribution if you publish code or results publicly.

Running locally means the app can be started on the reviewer's computer. The brief permits external model services, provided you document them and supply the saved review material described above.

