"""Scope and title regressions; original captures and questions stay unchanged."""
import copy
import json

import pytest

from backend.paths import ROOT
from backend.evaluation.benchmark import compile_draft, matching_counts, score_rules


@pytest.fixture(scope="module")
def cases():
    return {c["id"]: c for c in compile_draft(ROOT / "docs/Question-benchmark/benchmark_draft.md")["cases"]}


def captured(cid):
    return json.loads((ROOT / f"docs/benchmark/run-42078885361/pass-1/{cid}.json").read_text(encoding="utf-8"))


def check(result, name):
    return next(c for c in result["checks"] if c["rule"] == name)


def test_complete_captured_partition_has_30_main_and_two_additional_entries(cases):
    execution = captured("Q08")
    result = score_rules(cases["Q08"], execution["response"], reference=execution["evaluation_reference"])
    assert result["status"] == "pass"
    counts = check(result, "consistent_matching_count")["detail"]["counts"]
    assert counts == [{"stated": 30, "scope": "enumerated_group_with_explicit_remainder", "expected": 30, "passed": True}]


@pytest.mark.parametrize("heading", ["Materials recorded as aluminium—29 parts:", "In total, 30 parts:"])
def test_partition_does_not_excuse_wrong_group_count_or_wrong_total(cases, heading):
    execution = captured("Q08")
    response = copy.deepcopy(execution["response"])
    response["text"] = heading + "\n" + response["text"].split("\n", 1)[1]
    result = score_rules(cases["Q08"], response, reference=execution["evaluation_reference"])
    assert not check(result, "consistent_matching_count")["passed"]


def test_partition_requires_cited_remainder_even_if_all_cards_are_attached(cases):
    execution = captured("Q08")
    response = copy.deepcopy(execution["response"])
    response["text"] = response["text"].split("Two more")[0]
    result = score_rules(cases["Q08"], response, reference=execution["evaluation_reference"])
    assert not check(result, "consistent_matching_count")["passed"]


def test_duplicate_list_item_cannot_replace_a_reference_identity():
    parts = [{"id": f"D-{i:03}/part"} for i in range(1, 4)]
    text = "2 parts:\n- One [cite: D-001/part]\n- One again [cite: D-001/part]\n\nOne more [cite: D-003/part]"
    assert not matching_counts(text, parts)[0]["passed"]


def test_unrelated_remainder_cannot_complete_partition():
    parts = [{"id": f"D-{i:03}/part"} for i in range(1, 4)]
    text = "2 parts:\n- One [cite: D-001/part]\n- Two [cite: D-002/part]\n\nOne more [cite: D-999/part]"
    assert not matching_counts(text, parts)[0]["passed"]


def test_correct_current_title_does_not_require_old_placeholder(cases):
    execution = captured("Q11b")
    assert "Description" not in execution["response"]["text"]
    assert score_rules(cases["Q11b"], execution["response"])["status"] == "pass"


def test_old_placeholder_cannot_replace_current_title(cases):
    response = captured("Q11b")["response"]
    response["text"] = response["text"].replace("Silicone gasket for f-theta lens", "Description")
    assert not check(score_rules(cases["Q11b"], response), "key_values")["passed"]


def test_unknown_material_marker_still_fails_despite_qualified_prose(cases):
    result = score_rules(cases["Q10"], captured("Q10")["response"])
    assert check(result, "clean_output")["detail"]["unmarked_unknown"] == ["D-026/drawing/material"]
    assert result["status"] == "fail"


def test_valid_unknown_marker_accepts_existing_material_answer(cases):
    response = captured("Q10")["response"]
    response["text"] = response["text"].replace(
        ", D-026/drawing/material]", "] [undetermined: D-026/drawing/material]")
    assert score_rules(cases["Q10"], response)["status"] == "pass"


def test_missing_source_marker_still_fails_correct_torque_abstention(cases):
    result = score_rules(cases["Q15"], captured("Q15")["response"])
    assert "D-013/drawing/callout/p1-1" in check(result, "clean_output")["detail"]["invalid"]
    assert result["status"] == "fail"
