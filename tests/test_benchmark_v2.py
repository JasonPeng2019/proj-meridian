"""Behavioral regressions for evidence-aware scoring; no providers or CAD."""
from __future__ import annotations

import copy
import hashlib
import json
import os

import pytest

from backend.paths import ROOT
from backend.evaluation.benchmark import compile_draft, judge_payload, score_rules
from backend.evaluation.contracts import VERSION
from scripts import rescore_benchmark as replay


OPTICS = [
    "Sunny Galvo Adapter Plate", "F-theta seal ring", "Galvo box bracket",
    "Galve support bracket", "Silicone gasket f-theta ring", "Laser source",
    "Collimator", "Sunny Galvo", "F-Theta", "Water chiller for collimator",
]
GRADES = [
    ("D-012", "Recoater Mount Block"), ("D-013", "Recoater Plate"),
    ("D-014", "Recoater Linear Plate"), ("D-024", "ByggeBase"),
    ("D-025", "Bygge Base Ring"), ("D-028", "Varmeelement Plade"),
]


@pytest.fixture(scope="module")
def cases():
    return {c["id"]: c for c in compile_draft(ROOT / "docs/Question-benchmark/benchmark_draft.md")["cases"]}


def fact(name, value, **extra):
    return {"fact": name, "display": {"state": "value", "value": value}, **extra}


def card(key, name):
    return {"key": key, "id": key + "/part", "display_name": name}


def answer(text, facts, cards):
    return {"text": text, "facts": facts, "parts_to_show": cards,
            "warnings": [], "model": "gpt-6-luna"}


def predicate(result, name):
    return next(check for check in result["checks"] if check["rule"] == name)


def optics_answer(heading="10 parts-list items", names=None):
    names = OPTICS if names is None else names
    name = "summary/optics"
    return answer(heading + ": " + "; ".join(names) + f". [cite: {name}]",
                  {name: fact(name, {"count": 10, "names": OPTICS})},
                  [card("bom/optics/" + str(i), n) for i, n in enumerate(names)])


def test_q02_complete_canonical_rows_pass_without_section_approval(cases):
    assert score_rules(cases["Q02"], optics_answer())["status"] == "pass"


def test_q02_correct_final_total_does_not_erase_contradictory_opening(cases):
    response = optics_answer("9 parts-list items")
    response["text"] += " The seal ring brings the total to 10."
    result = score_rules(cases["Q02"], response)
    assert result["status"] == "fail"
    assert not predicate(result, "consistent_bom_count")["passed"]


def test_q02_count_and_unrelated_drawing_name_cannot_replace_missing_bom_row(cases):
    response = optics_answer(names=[n for n in OPTICS if n != "F-theta seal ring"] + ["SealRing"])
    result = score_rules(cases["Q02"], response)
    assert result["status"] == "fail"
    assert predicate(result, "complete_bom_list")["detail"]["missing"] == ["F-theta seal ring"]


def grade_answer():
    facts, cards, lines = {}, [], []
    for key, name in GRADES:
        identity, material = key + "/part", key + "/drawing/material"
        facts[identity], facts[material] = fact(identity, name), fact(material, "3.3315 (EN-AW 5005)")
        cards.append(card(key, name))
        lines.append(f"- {name} [cite: {identity}, {material}]")
    return answer("Materials recorded as EN-AW 5005 for six parts:\n" + "\n".join(lines), facts, cards)


def test_q09_named_cited_identities_pass_without_repeating_ids_in_prose(cases):
    response = grade_answer()
    assert score_rules(cases["Q09"], response)["status"] == "pass"


def test_q09_named_visible_cards_can_identify_material_list(cases):
    response = grade_answer()
    response["text"] = "Six matching parts are shown below. [cite: " + ", ".join(response["facts"]) + "]"
    assert score_rules(cases["Q09"], response)["status"] == "pass"


def test_q09_citation_dump_with_unnamed_cards_is_not_a_list(cases):
    response = grade_answer()
    response["text"] = "[cite: " + ", ".join(response["facts"]) + "]"
    for item in response["parts_to_show"]:
        item.pop("display_name")
    result = score_rules(cases["Q09"], response)
    assert result["status"] == "fail"
    assert not predicate(result, "complete_material_list")["passed"]


def test_q09_missing_named_part_fails_even_with_six_materials_in_fact_ledger(cases):
    response = grade_answer()
    response["text"] = "\n".join(line for line in response["text"].splitlines() if "Varmeelement" not in line)
    response["parts_to_show"] = response["parts_to_show"][:-1]
    result = score_rules(cases["Q09"], response)
    assert result["status"] == "fail"
    assert predicate(result, "complete_material_list")["detail"]["missing"] == ["D-028"]


def weight_answer(quantity):
    key = "D-023/drawing/weight_g"
    return answer(f"The drawing lists {quantity}. [cite: {key}]",
                  {key: fact(key, 3195.5)}, [card("D-023", "Powder part")])


@pytest.mark.parametrize("quantity", ["3195.5 g", "3,195.5 grams", "3196 g", "3.1955 kg", "3.196 kilograms", "3.20 kg"])
def test_q12_supported_gram_and_equivalent_kilogram_answers(cases, quantity):
    assert score_rules(cases["Q12"], weight_answer(quantity))["status"] == "pass"


@pytest.mark.parametrize("quantity", ["3195.5 kg", "3.1955 g", "3.1 kg", "3195.5 mm", "3000 g", "3195.5"])
def test_q12_wrong_value_or_missing_wrong_unit_fails(cases, quantity):
    result = score_rules(cases["Q12"], weight_answer(quantity))
    assert result["status"] == "fail"
    assert not predicate(result, "weight_value_and_unit")["passed"]


def test_q12_naked_unknown_cannot_be_promoted_to_a_weight(cases):
    response = weight_answer("3195.5 g")
    response["facts"]["D-023/drawing/weight_g"]["display"] = {"state": "undetermined"}
    result = score_rules(cases["Q12"], response)
    assert result["status"] == "fail"
    assert not predicate(result, "clean_output")["passed"]


def width_answer():
    key, number = "D-017/template/outline/width", "D-017/drawing/n/110.0@1-1"
    source = {"name": number, "box": [10, 20, 30, 40], "says": "110,0", "page": 1}
    return answer(f"The template width is 110 mm, the overall vertical span. [cite: {key}]",
                  {key: fact(key, 110, sources=[source])}, [card("D-017", "Galvo Montage Plade")])


def test_q13_interpreted_width_with_source_number_box_passes(cases):
    assert score_rules(cases["Q13"], width_answer())["status"] == "pass"


def test_q13_bare_number_with_box_cannot_establish_width_axis(cases):
    response = width_answer()
    original = response["facts"].pop("D-017/template/outline/width")
    key = "D-017/drawing/n/110.0@1-1"
    response["facts"][key] = fact(key, 110, sources=original["sources"])
    response["text"] = f"It is 110 mm wide. [cite: {key}]"
    result = score_rules(cases["Q13"], response)
    assert result["status"] == "fail"
    assert predicate(result, "dimension_highlight_metadata")["passed"]
    assert not predicate(result, "interpreted_dimension_or_abstention")["passed"]


def test_q13_interpreted_dimension_still_requires_source_highlight_box(cases):
    response = width_answer()
    response["facts"]["D-017/template/outline/width"]["sources"][0]["box"] = None
    result = score_rules(cases["Q13"], response)
    assert result["status"] == "fail"
    assert not predicate(result, "dimension_highlight_metadata")["passed"]


def aluminium_reference():
    return {"parts": [{"key": key, "id": key + "/part", "display_name": name}
                      for key, name in [
                          ("bom/recoater/recoater-arm", "Recoater Arm"),
                          ("bom/gas-flow/gas-blower", "Gas blower"),
                          ("D-025", "Bygge Base Ring"),
                          ("D-024", "ByggeBase"),
                          ("bom/box/window-frame", "Window Frame"),
                      ]]}


def aluminium_answer(reference):
    parts = reference["parts"]
    facts = {p["id"]: fact(p["id"], p["display_name"]) for p in parts}
    text = "5 matching parts, counting catalog records; physical identities are unresolved:\n"
    text += "\n".join(f"- {p['display_name']} [cite: {p['id']}]" for p in parts)
    return answer(text, facts, [card(p["key"], p["display_name"]) for p in parts])


def test_q08_complete_independent_reference_passes_with_separate_coverage_gaps(cases):
    reference = aluminium_reference()
    gaps = [{"name": "approved_material_mappings", "status": "pending"},
            {"name": "four_flagged_drawing_links_verified", "status": "pending"}]
    result = score_rules(cases["Q08"], aluminium_answer(reference), gaps, reference)
    assert result["status"] == "pass"
    assert result["all_checks_pass"]
    assert result["coverage_gaps"] == gaps


def test_q08_reference_membership_does_not_shrink_to_what_chat_retrieved(cases):
    reference = aluminium_reference()
    response = aluminium_answer(reference)
    missing = reference["parts"][-1]
    response["text"] = "\n".join(line for line in response["text"].splitlines() if "Window Frame" not in line)
    response["parts_to_show"] = response["parts_to_show"][:-1]
    response["facts"].pop(missing["id"])
    gap = [{"name": "approved_material_mappings", "status": "pending"}]
    result = score_rules(cases["Q08"], response, gap, reference)
    assert result["status"] == "fail"
    assert result["coverage_gaps"] == gap
    assert predicate(result, "complete_material_list")["detail"]["missing"] == [missing["key"]]


def test_q08_missing_independent_oracle_cannot_be_scored_as_complete(cases):
    result = score_rules(cases["Q08"], aluminium_answer(aluminium_reference()))
    assert result["status"] == "fail"
    assert not predicate(result, "independent_list_reference")["passed"]


def test_setup_pending_cannot_hide_an_actual_wrong_answer(cases):
    result = score_rules(cases["Q12"], weight_answer("3195.5 kg"),
                         [{"name": "isolated_weight_fixture", "status": "pending"}])
    assert result["status"] == "fail"
    assert not result["all_checks_pass"]


def test_q08_correct_list_and_final_count_do_not_erase_wrong_opening_count(cases):
    reference = aluminium_reference()
    response = aluminium_answer(reference)
    response["text"] = "There are 4 parts.\n" + response["text"]
    result = score_rules(cases["Q08"], response, reference=reference)
    assert result["status"] == "fail"
    assert not predicate(result, "consistent_matching_count")["passed"]


def test_judge_cache_key_changes_with_attachment_evidence_or_reference(cases):
    manifest = {"source_sha256": "source", "code_sha256": "code", "settings_sha256": "settings"}
    execution = {"response": grade_answer(), "evaluation_reference": aluminium_reference()}
    original = judge_payload(cases["Q09"], execution, manifest)
    changed = copy.deepcopy(execution)
    changed["response"]["parts_to_show"][0]["has_3d"] = True
    assert judge_payload(cases["Q09"], changed, manifest)["cache_key"] != original["cache_key"]
    changed = copy.deepcopy(execution)
    changed["evaluation_reference"]["parts"].pop()
    assert judge_payload(cases["Q09"], changed, manifest)["cache_key"] != original["cache_key"]
    assert original["returned_parts"] == execution["response"]["parts_to_show"]
    assert original["evaluation_contract"]["version"] == VERSION


@pytest.fixture
def saved_capture(tmp_path, monkeypatch):
    """Minimal isolated capture, retaining canonical question/compiler provenance."""
    capture = tmp_path / "capture"
    capture.mkdir()
    draft = (ROOT / "docs/Question-benchmark/benchmark_draft.md").read_bytes()
    (capture / "benchmark_draft.md").write_bytes(draft)
    fixture = compile_draft(capture / "benchmark_draft.md")
    case = next(c for c in fixture["cases"] if c["id"] == "Q12")
    manifest = {"source_sha256": hashlib.sha256(draft).hexdigest(), "code_sha256": "captured-code",
                "settings_sha256": "captured-settings", "expected_executions": 1}
    execution = {"pass": 1, "case_id": "Q12", "question": case["question"],
                 "response": weight_answer("3195.5 g")}
    values = {"cases.json": fixture, "manifest.json": manifest,
              "report.json": {"results": [{"pass": 1, "case_id": "Q12", "combined": "fail"}]}}
    for name, data in values.items():
        (capture / name).write_text(json.dumps(data), encoding="utf-8")
    (capture / "executions.jsonl").write_text(json.dumps(execution) + "\n", encoding="utf-8")
    (capture / "judge-results.jsonl").write_text('{"score": 0, "historical": true}\n', encoding="utf-8")
    monkeypatch.setattr(replay, "reference_for_capture", lambda manifest, reference_root=ROOT: ({}, {"generated/test.json": "pinned"}))
    return capture


def test_replay_preserves_capture_and_reports_new_judgment_as_pending(saved_capture, tmp_path):
    before = {p.name: p.read_bytes() for p in saved_capture.iterdir()}
    output = tmp_path / "revised"
    result = replay.rescore(saved_capture, output)
    assert {p.name: p.read_bytes() for p in saved_capture.iterdir()} == before
    assert result["results"][0]["combined"] == "pending_judge"
    assert result["comparison"] == [{"pass": 1, "case_id": "Q12", "original": "fail", "revised": "pending_judge"}]
    provenance = result["evaluation_provenance"]
    assert provenance["capture_hashes"] == {name: hashlib.sha256(data).hexdigest() for name, data in before.items()}
    assert provenance["reference_input_hashes"] == {"generated/test.json": "pinned"}
    assert result["human_judge_spot_check"]["decisions_checked"] == 0
    assert (output / "evaluation.json").is_file()
    assert (output / "judge-inputs.jsonl").is_file()


@pytest.mark.parametrize("nested", [False, True])
def test_replay_rejects_output_equal_to_or_inside_original_capture(saved_capture, nested):
    output = saved_capture / "revised" if nested else saved_capture
    with pytest.raises(ValueError, match="immutable capture"):
        replay.rescore(saved_capture, output)
    assert not (saved_capture / "revised").exists()


def test_replay_rejects_outside_workspace_output_before_writing(saved_capture):
    outside = ROOT.parent / "forbidden-benchmark-output"
    with pytest.raises(ValueError, match="escapes"):
        replay.rescore(saved_capture, outside)


def test_replay_rejects_reusing_output_after_capture_changes(saved_capture, tmp_path):
    output = tmp_path / "revised"
    replay.rescore(saved_capture, output)
    receipt = (output / "evaluation.json").read_bytes()
    executions = saved_capture / "executions.jsonl"
    row = json.loads(executions.read_text(encoding="utf-8"))
    row["response"]["text"] = row["response"]["text"].replace("3195.5 g", "3000 g")
    executions.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different evaluation"):
        replay.rescore(saved_capture, output)
    assert (output / "evaluation.json").read_bytes() == receipt


def test_replay_binds_oracle_output_even_when_source_hashes_are_unchanged(saved_capture, tmp_path, monkeypatch):
    output = tmp_path / "revised"
    replay.rescore(saved_capture, output)
    before = (output / "evaluation.json").read_bytes()
    monkeypatch.setattr(replay, "reference_for_capture", lambda manifest, reference_root=ROOT:
                        ({"Q08": {"parts": [{"key": "changed"}]}}, {"generated/test.json": "pinned"}))
    with pytest.raises(ValueError, match="different evaluation"):
        replay.rescore(saved_capture, output)
    assert (output / "evaluation.json").read_bytes() == before


def test_replay_binds_oracle_implementation_even_if_output_is_unchanged(saved_capture, tmp_path, monkeypatch):
    output = tmp_path / "revised"
    monkeypatch.setattr(replay, "oracle_code_hashes", lambda: {"backend/app/tools.py": "original"})
    replay.rescore(saved_capture, output)
    monkeypatch.setattr(replay, "oracle_code_hashes", lambda: {"backend/app/tools.py": "changed"})
    with pytest.raises(ValueError, match="different evaluation"):
        replay.rescore(saved_capture, output)


def test_replay_rejects_capture_hardlink_before_any_output_write(saved_capture, tmp_path):
    output = tmp_path / "revised"
    replay.rescore(saved_capture, output)
    target = output / "report.json"
    target.unlink()
    os.link(saved_capture / "report.json", target)
    before = {p.name: p.read_bytes() for p in saved_capture.iterdir()}
    receipt = (output / "evaluation.json").read_bytes()
    with pytest.raises(ValueError, match="hardlinks"):
        replay.rescore(saved_capture, output)
    assert (output / "evaluation.json").read_bytes() == receipt
    assert {p.name: p.read_bytes() for p in saved_capture.iterdir()} == before


def test_reference_reconstruction_rejects_changed_pinned_inputs_before_store_use(monkeypatch):
    monkeypatch.setattr(replay, "sha", lambda path: "new-hash")
    with pytest.raises(ValueError, match="Original catalog input changed: generated/records.json"):
        replay.reference_for_capture({"input_hashes": {"generated": {"records.json": "old-hash"}}})
