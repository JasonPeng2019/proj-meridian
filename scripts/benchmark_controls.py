"""Create deliberately incorrect answers to check the meaning judge's boundaries.

Controls are synthetic test data, never chat output or engineering approvals.
Expected labels are saved separately and never passed to the model judge.
"""
from __future__ import annotations

import argparse
import copy
import json

from backend.paths import configure_environment, inside
from backend.evaluation.benchmark import fingerprint, load_judgments
from scripts.run_benchmark import write, jsonl


def controls(payloads: list[dict]) -> tuple[list[dict], list[dict]]:
    baseline = {p["case_id"]: p for p in reversed(payloads)}
    inputs, expected = [], []
    def add(cid, name, text=None, mutate=None, accepted=(0, 1)):
        payload = copy.deepcopy(baseline[cid])
        payload.pop("cache_key")
        if text is not None:
            payload["answer"] = text
        if mutate:
            mutate(payload)
        payload["cache_key"] = fingerprint(payload)
        inputs.append(payload)
        expected.append({"control": name, "case_id": cid, "cache_key": payload["cache_key"],
                         "accepted_scores": list(accepted), "synthetic": True})

    add("Q02", "contradictory_bom_count", mutate=lambda p: p.update(answer=p["answer"].replace("10", "9", 1)))
    add("Q03", "fabricated_mapping_approval", "Yes, these are the same section. Jason approved the equivalence. [cite: names/section/optical -> optics]")
    add("Q05", "zero_placeholder_is_not_free", "DTU supplied it for free. Its actual price was DKK 0.00. [cite: BOM:recoater/recoater-arm/supplier]")
    add("Q06", "availability_flags_can_disprove_absence", mutate=lambda p: [c.update(has_drawing=True) for c in p["returned_parts"]])
    add("Q07", "multi_material_is_not_steel_only", "The T5 belt is made only of steel. [cite: BOM:recoater/t5-timing-belt-300-teeth/material]")
    add("Q08", "wrong_material_match_count", mutate=lambda p: p.update(answer="There are 34 matching parts.\n" + p["answer"]))
    def omit_grade(p):
        p["answer"] = "The five EN-AW 5005 parts are Recoater Mount Block, Recoater Plate, Recoater Linear Plate, ByggeBase and Bygge Base Ring. [cite: D-012/part, D-013/part, D-014/part, D-024/part, D-025/part]"
        p["returned_parts"] = [c for c in p["returned_parts"] if c["key"] != "D-028"]
    add("Q09", "one_grade_match_omitted", mutate=omit_grade)
    add("Q10", "unreadable_grade_is_not_aisi316", "The build plate is definitely AISI 316 stainless steel. [cite: D-026/drawing/material]")
    add("Q12", "wrong_weight_unit", "It weighs 3195.5 kg. [cite: D-023/drawing/weight_g]")
    add("Q13", "vertical_dimension_is_not_horizontal", "The horizontal overall span is 110 mm. [cite: D-017/template/outline/width]")
    add("Q14", "unselected_thickness_is_not_confirmed", "It is definitely 2 mm thick; the 3 mm alternative is wrong. [cite: D-025/template/thickness]")
    add("Q15", "invented_tightening_torque", "Tighten the M5 screws to 5 Nm. [cite: D-013/part]")
    add("Q17", "partial_model_is_not_exact_or_verified", "The model exactly matches the drawing, including every hole and counterbore. Its weight check passed. [cite: D-026/model/verification]")
    add("Q20", "snapshot_does_not_establish_current_stock", "Max Photonics supplies it today and it is in stock, available for immediate delivery. [cite: BOM:optics/laser-source/supplier]")
    # Positive controls use meanings the old literal scorer wrongly rejected.
    add("Q05", "negated_free_is_not_a_free_claim", "DTU is the recorded supplier; this snapshot may be out of date. No price is recorded. The zero placeholder does not mean it was free. [cite: BOM:recoater/recoater-arm/supplier] [undetermined: BOM:recoater/recoater-arm/total_cost]", accepted=(2,))
    add("Q20", "negated_stock_is_not_a_stock_claim", "The recorded supplier is Max Photonics; this snapshot may be out of date. It cannot establish whether the part is currently in stock or available. [cite: BOM:optics/laser-source/supplier]", accepted=(2,))
    add("Q15", "unit_in_denial_is_not_torque_advice", "The evidence supplies no tightening torque in Nm, so I cannot determine a setting for the screws. [cite: D-013/part]", accepted=(2,))
    return inputs, expected


def main():
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--judge-results")
    args = parser.parse_args()
    root = inside(args.evaluation)
    payloads = [json.loads(line) for line in (root / "judge-inputs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    inputs, expected = controls(payloads)
    jsonl(root / "control-inputs.jsonl", inputs)
    write(root / "control-expectations.json", expected)
    if args.judge_results:
        judgments = load_judgments(inside(args.judge_results), {p["cache_key"] for p in inputs})
        rows = [{**e, "actual_score": judgments.get(e["cache_key"], {}).get("score"),
                 "passed": judgments.get(e["cache_key"], {}).get("score") in e["accepted_scores"]} for e in expected]
        write(root / "control-report.json", {"controls": rows, "passed": sum(r["passed"] for r in rows), "total": len(rows)})
        print(json.dumps({"passed": sum(r["passed"] for r in rows), "total": len(rows)}))
        if not all(r["passed"] for r in rows):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
