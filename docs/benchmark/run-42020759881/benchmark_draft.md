# Benchmark: Draft Questions and Scoring

**Status: draft for Jason to check.** The expected answers below come from the source files directly, not from the system's answers. Almost all were worked out from the data with code during planning. Each one is marked:

- ✅ **checked:** worked out from the data with code (or OCR, for the scans) during planning;
- ⚠️ **verify:** one part of the answer depends on something only known after the system runs (here, four drawing links in Q08).

Stable names follow `proposal.md` A9. "From" is the first milestone (`mvp.md`) where the feature needed to answer correctly exists. Before that milestone, the right behavior is to say there's no evidence.

---

## The 20 questions

Each question has the **exact expected answer** (the wording can differ, but these facts must be there), plus what the rule-based checks look for.

### Machine organization

**Q01. How many drawings are there, and which machine sections do they cover?** ✅ *(From M1, needs `machine_summary()`)*
- **Answer:** "There are 30 drawings: Z-axis 8, Box 5, Powder 5, Recoater 5, Optical 5, and Gas Flow 2."
- **Must include:** `30`, `Z-axis 8`, `Box 5`, `Powder 5`, `Recoater 5`, `Optical 5`, `Gas Flow 2`
- **Shows:** compact parts list

**Q02. Which parts list items belong to the Optics section?** ✅ *(From M1)*
- **Answer:** "10 items: Sunny Galvo Adapter Plate, F-theta seal ring, Galvo box bracket, Galve support bracket, Silicone gasket f-theta ring, Laser source, Collimator, Sunny Galvo, F-Theta, and Water chiller for collimator."
- **Must include:** `10` and all 10 names
- **Shows:** compact parts list

**Q03. Are the "Optical" drawing section and the "Optics" parts list section the same thing?** ✅ *(From M1, once the mapping is approved)*
- **Answer:** "Yes. They're the same section; the two sources just name it differently."
- **Must include:** `same`
- **Must cite:** `names/section/optical -> optics`

### Linking drawings to the parts list, and one value per field

**Q04. What is the recoater plate made of?** ✅ *(From M1)*
- **Answer:** "EN-AW 5005 aluminium." (Drawing D-013 says "3.3315 (EN-AW 5005)," and both parts list rows it could link to, "Recoater head" and "Recoater stage plate," say "Aluminium." If the link is still unresolved, the answer is "3.3315 (EN-AW 5005)" from the drawing alone, and that also passes.)
- **Must include:** `EN-AW 5005`
- **Must cite:** `D-013/drawing/material`
- **Shows:** D-013

**Q05. Who supplied the Recoater Arm, and what did it cost?** ✅ *(From M1)*
- **Answer:** "The recorded supplier is DTU (as recorded in the snapshot; may be out of date). Its cost isn't recorded: the parts list shows a total of DKK 0.00, but it has no unit cost, so that zero means 'not recorded,' not free."
- **Must include:** `DTU`, `not recorded`, `may be out of date`
- **Must not include:** `free`, `costs DKK 0`
- **Must cite:** `BOM:recoater/recoater-arm/supplier`, `BOM:recoater/recoater-arm/total_cost`
- **Shows:** D-011 (linked by its datasheet filename, `RecoaterArm.PDF`; it's a degraded scan)

**Q06. What does the front door hinge connect to?** ✅ *(From M1)*
- **Answer:** "The front door hinge connects to the Front Door and the Front Side Box."
- **Must include:** `Front Door`, `Front Side Box`
- **Must cite:** `BOM:box/front-door-hinge/interface_with`
- **Shows:** its parts-list-only card

**Q07. What is the T5 timing belt made of?** ✅ *(From M1)*
- **Answer:** "Materials recorded: Steel, Elastomer."
- **Must include:** `Steel`, `Elastomer`
- **Must not include:** `made of steel`
- **Must cite:** `BOM:recoater/t5-timing-belt-300-teeth/material`
- **Shows:** its parts-list-only card

**Q08. Which parts are aluminium?** ✅ / ⚠️ *(From M1)*
- **Answer:** these parts list rows (29), plus these drawings, counting a drawing and its linked row as one part:
  - **Parts list rows recorded as Aluminium:** Front Door, Print Platform, Window Frame, Back Door, 2020 internal profile, 2020 angle bracket, Recoater head, Recoater Clamp, Recoater Arm, Recoater stage plate, Recoater mount block, Timing pulley Ø6.35 T5, Timing belt idler Ø8 T5, Timing belt clamp plate, Build cylinder, Build base, Motor plate, Build cylinder clamp ring, Heating element plate, Thermocouple plate, Seal clamp plate, Sunny Galvo Adapter Plate, F-theta seal ring, Galvo box bracket, Powder roller, Powder roller housing, Powder Valve Fitting, Dispenser drum coupling, and Gas blower (recorded with "Polymer, Steel, Aluminium").
  - **Drawings with an aluminium alloy:** D-005 (6061), D-012, D-013, D-014, D-024, D-025, D-028 (EN-AW 5005), D-016, D-017, D-018 (7075-T6), D-027 (6063-T6); and from the scans, if they're read: D-011 (7075-T6), D-020 (6061), D-023 (EN AW-6082).
  - ⚠️ Most of these drawings link to one of the rows above (for example D-005 → Window Frame, D-027 → Build cylinder clamp ring). **D-016, D-017, D-018, and D-025 have no obvious row**, so they may count as separate parts. Check those four links after matching runs.
- **Must include:** `Recoater Arm`, `Gas blower`, `Bygge Base Ring` (D-025), `Galvo Bundplade` (D-016)
- **Shows:** compact parts list

**Q09. Which parts are EN-AW 5005?** ✅ *(From M1)*
- **Answer:** "Six parts: Recoater Mount Block (D-012), Recoater Plate (D-013), Recoater Linear Plate (D-014), ByggeBase (D-024), Bygge Base Ring (D-025), and Varmeelement Plade (D-028)."
- **Must include:** all 6 drawing IDs
- **Must not include:** `Recoater Arm`, `Window Frame` (recorded only as "Aluminium," or a different alloy)
- **Shows:** compact parts list

### Uncertainty and honesty

**Q10. What is the build plate made of?** ✅ *(From M1)*
- **Answer:** "Materials recorded: Stainless steel, Steel." (Drawing D-026's own material text is printed on top of the weight label and can't be read reliably, so it's only shown in the hover card.)
- **Must include:** `Stainless steel`, `Steel`
- **Must not include:** `AISI 316` as the answer's value
- **Must cite:** `BOM:build-plate/build-plate/material`
- **Shows:** D-026

**Q11a. What is the title of drawing D-019?** *(before the correction)* ✅ *(From M1)*
- **Answer:** the title is Undetermined: "The title field says 'Description,' which is a placeholder."
- **Behavior:** `undetermined` on `D-019/drawing/title`
- **Shows:** D-019

**Q11b. What is the title of drawing D-019?** *(after the correction is accepted)* ✅ *(From M1)*
- **Answer:** "Silicone gasket for f-theta lens (originally 'Description'; corrected by Jason Peng)."
- **Must include:** `Silicone gasket for f-theta lens`, `Description`
- **Must cite:** `D-019/drawing/title`
- **Shows:** D-019

**Q12. What does drawing D-023 weigh?** ✅ *(From M1)*
- **Answer:** "3195.5 g. This is an AI reading of a blurry scan and hasn't been reviewed."
- **Must include:** `3195.5`
- **Must cite:** `D-023/drawing/weight_g`
- **Shows:** D-023
- (Read from the scan with OCR during planning. If the two models don't agree on it, Undetermined also passes.)

**Q13. How wide is the Galvo Montage Plade (D-017)?** ✅ *(From M1)*
- **Answer:** Undetermined: "The drawing shows several measurements, but I can't tell which edge each one measures."
- **Behavior:** `undetermined`
- **Shows:** D-017, with its numbers highlighted

**Q14. How thick is the Bygge Base Ring (D-025)?** ✅ *(From M1)*
- **Answer:** "The drawing shows two thicknesses, 3 mm and 2 mm. You can switch between both in the 3D view (Examples A and B)."
- **Must include:** `3`, `2`
- **Must cite:** `D-025/template/thickness`
- **Shows:** D-025, with 3D

**Q15. What torque should the recoater plate's M5 screws be tightened to?** ✅ *(From M1)*
- **Answer:** "There's no evidence for this. The drawing and parts list don't give a tightening torque."
- **Behavior:** `no_evidence`
- **Must not include:** `Nm`
- **Must cite:** `D-013/part`
- **Shows:** D-013

### Holes, 3D, and checks

**Q16. How many M3 threaded holes does the recoater plate have?** ✅ *(From M1)*
- **Answer:** "8 (from the callout '8x Ø2,5 THRU ALL, M3 - 6H')."
- **Must include:** `8`
- **Must cite:** the template's M3 hole feature (M1), or the callout fact (M3)
- **Shows:** D-013

**Q17. Show me the build plate in 3D. Does its model match the drawing?** ✅ *(From M1; the weight check from M2)*
- **Answer:** "Here's D-026 in 3D, with two examples: 25 mm and 15 mm thick. The weight check FAILED: the drawing says 7,822.5 g, but the model comes out to about 9,800 g at 25 mm and about 5,900 g at 15 mm (using stainless steel, from the parts list, since the drawing's material can't be read reliably). It needs manual approval."
- **Must include:** `25`, `15`, `FAILED` (from M2)
- **Shows:** D-026, with 3D
- (Weights estimated during planning with a stainless density of 8.0 g/cm³; the exact figures depend on the density table.)

### Costs, the README, and current information

**Q18. What did the machine cost in total?** ✅ *(From M1, needs `cost_summary()`)*
- **Answer:** "The recorded total is DKK 168,591.52, from the 116 parts list rows that have a total recorded. 76 rows have no total recorded (75 with no unit cost and 1 with no amount), so the real cost is higher. These are prices as recorded in the snapshot and may be out of date."
- **Must include:** `168,591.52`, `116`, `76`, `may be out of date`
- **Must cite:** the cost summary

**Q19. What is the machine's build volume?** ✅ *(From M3)*
- **Answer:** "250 mm × 150 mm (from the README)."
- **Must include:** `250`, `150`
- **Must cite:** `README/physical-system/p...` (the passage)

**Q20. Who supplies the laser source today, and is it in stock?** ✅ *(From M1)*
- **Answer:** "The recorded supplier is Max Photonics, as recorded in the snapshot, so it may be out of date. The data can't tell whether it's currently in stock."
- **Must include:** `Max Photonics`, `may be out of date`
- **Must not include:** `in stock` (as a claim), `available`
- **Must cite:** `BOM:optics/laser-source/supplier`

## Two tools this needs

These questions add up across many parts, which the current tools can't do. The chat would have to call `get_facts` on all 192 parts.

- **`machine_summary()`:** drawings per section, and parts list rows per section. Used by Q01 and Q02.
- **`cost_summary()`:** the sum of recorded totals, how many rows have a recorded total, how many don't (and why), and the snapshot note. Used by Q18.

Both are plain code over the records, so the numbers are rule-based and the chat model just phrases them.

---

## How to score

Most of the scoring **can** be rule-based, because the chat's output is structured: citation markers, Undetermined markers, the facts the tools returned, and the parts shown. A model judge is only needed for one thing: whether the wording is faithful.

### Layer 1: rule-based checks (most of the score)

Each question lists what a correct answer must contain (the format is in `proposal.md`, Testing). The script checks the chat API response directly:

| Check | How |
|---|---|
| **Right sources retrieved** | Every `must_cite` name appears in the answer's citations or Undetermined markers. |
| **Right parts shown** | `parts_to_show` matches `must_show_parts`. For list questions, only the "4 or more → compact list" rule is checked. |
| **Right behavior** | `undetermined`: the expected fact has an `[undetermined: ...]` marker and no stated value. `answer`: no Undetermined marker on the expected fact. `no_evidence`: no `must_not_include` value appears. |
| **Key values present** | Every `must_include` value appears in the shown answer, after normalizing case, spaces, and number formatting (so "168,591.52" matches "168591.52"). |
| **Nothing wrong present** | No `must_not_include` value appears, like "free" in Q05 or "in stock" in Q20. |
| **Clean output** | No invalid citations or markers, and no "uncited answer" warning. |

### Layer 2: a model judge (only for meaning)

Some things a rule can't check, like whether "Materials recorded: Steel, Elastomer" was turned into "it's made of steel," or whether an answer claims more than its sources say.

- **Use the other model as the judge.** If the chat runs on Claude, judge with Codex, and the other way around, so a model isn't grading its own answers. The judge runs through the same CLI setup as the prep pipeline.
- **The judge gets:** the question, the expected answer from this file, **the facts the tools returned** (the ground truth for that answer), and the chat's answer.
- **It replies with JSON:**

```json
{"score": 2, "unsupported_claims": [], "reason": "..."}
```

- **Scores:**
  - **2:** correct and complete, no claims beyond the cited facts, and uncertainty worded correctly.
  - **1:** correct, but incomplete or awkwardly worded.
  - **0:** wrong, guessed, claims something the facts don't support, or contradicts a source.
- Judge results are cached, so re-scoring the same answer is free.

### Final score

- **A question passes** when every rule-based check passes **and** the judge gives a 2.
- **Report all three:** rule-based pass rate, judge scores, and the combined pass rate, broken down by category.
- **Run the benchmark twice** with nothing changed, and report how many questions got the same result both times. That's the reproducibility number.
- **Also report** time and cost per question, and which chat model was used.
- **Spot-check the judge:** Jason reads about 5 of its decisions to make sure it's grading sensibly, and the write-up says so.
