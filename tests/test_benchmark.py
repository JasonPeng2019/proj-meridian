"""Isolated parser/rule/judge-contract tests; no provider or production mutation."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from backend.paths import ROOT
from backend.evaluation.benchmark import (CASE_IDS, JUDGE, compile_draft, contains, fingerprint,
                                          judge_payload, load_judgments, report_results, score_rules)


@pytest.fixture
def fixture():
    return compile_draft(ROOT / "docs/Question-benchmark/benchmark_draft.md")


def case(fixture, cid):
    return next(c for c in fixture["cases"] if c["id"] == cid)


def response(text, names=(), part="D-013", **extra):
    return {"text": text, "facts": {name: {"fact": name, "display": {"state": "value", "value": "test"}} for name in names},
            "parts_to_show": [{"key": part, "id": part + "/part"}] if part else [], "warnings": [], "model": "gpt-6-luna", **extra}


def check(result, name):
    return next(c for c in result["checks"] if c["rule"] == name)


def test_compiler_is_derived_and_hashes_exact_canonical_bytes(fixture):
    raw = (ROOT / "docs/Question-benchmark/benchmark_draft.md").read_bytes()
    assert [c["id"] for c in fixture["cases"]] == CASE_IDS
    assert len(fixture["cases"]) == 21
    assert fixture["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert case(fixture, "Q11a")["question"] == case(fixture, "Q11b")["question"]
    assert len(case(fixture, "Q02")["must_include"]) == 11  # count plus ten names
    assert len(case(fixture, "Q09")["must_include"]) == 6
    assert case(fixture, "Q06")["must_show_parts"] == ["BOM:box/front-door-hinge/part"]
    assert case(fixture, "Q17")["needs_3d"]


def test_compiler_rejects_missing_case_without_silent_partial_benchmark(tmp_path):
    source = (ROOT / "docs/Question-benchmark/benchmark_draft.md").read_text(encoding="utf-8")
    path = tmp_path / "changed.md"
    path.write_text(source.replace("**Q20.", "**Q21."), encoding="utf-8")
    with pytest.raises(ValueError, match="21 cases"):
        compile_draft(path)


@pytest.mark.parametrize(("text", "value", "expected"), [
    ("DKK 168,591.52", "168591.52", True), ("DKK 168591.52", "168,591.52", True),
    ("3195.5 g", "3", False), ("30 drawings", "3", False), ("Z-axis: 8", "Z-axis 8", True),
    ("EN-AW 5005", "en aw 5005", True), ("D-012", "D-013", False),
    ("15.0 mm", "15", True), ("2.000", "2", True), ("2.1", "2", False),
])
def test_token_normalization_preserves_numeric_boundaries(text, value, expected):
    assert contains(text, value) is expected


def test_key_values_do_not_count_citation_marker_contents(fixture):
    c = case(fixture, "Q09")
    names = [did + "/part" for did in c["must_include"]]
    r = response("See the drawings [cite: " + ", ".join(names) + "]", names)
    assert not check(score_rules(c, r), "key_values")["passed"]


def test_negative_literal_rule_remains_separate_from_negated_meaning(fixture):
    c = case(fixture, "Q05")
    text = "DTU, may be out of date; cost not recorded, not free. [cite: " + ", ".join(c["must_cite"]) + "]"
    r = response(text, c["must_cite"], "D-011")
    scored = score_rules(c, r)
    assert not check(scored, "literal_prohibited_values")["passed"]
    assert "free" in check(scored, "literal_prohibited_values")["detail"]
    assert "Literal prohibited" in c["rule_notes"][0]


def test_invalid_and_naked_undetermined_citations_fail_clean_output(fixture):
    c = case(fixture, "Q04")
    name = c["must_cite"][0]
    r = response(f"EN-AW 5005 [cite: {name}]", [name])
    r["facts"][name]["display"] = {"state": "undetermined"}
    assert not check(score_rules(c, r), "clean_output")["passed"]
    r["text"] += " [cite: invented/name]"
    assert "invented/name" in check(score_rules(c, r), "clean_output")["detail"]["invalid"]


def test_q12_abstention_alternative_requires_valid_fact_state(fixture):
    c = case(fixture, "Q12")
    name = c["must_cite"][0]
    r = response(f"[undetermined: {name}] The scan is unreadable.", [name], "D-023")
    r["facts"][name]["display"] = {"state": "undetermined"}
    assert score_rules(c, r)["status"] == "pass"
    r["facts"][name]["display"] = {"state": "value", "value": 3195.5}
    assert score_rules(c, r)["status"] == "fail"


def test_q11_before_requires_marker_on_the_title(fixture):
    c = case(fixture, "Q11a")
    name = c["behavior_fact"]
    r = response("The title is Undetermined.", [name], "D-019")
    assert not check(score_rules(c, r), "behavior")["passed"]
    r["text"] += f" [undetermined: {name}]"
    r["facts"][name]["display"] = {"state": "undetermined"}
    assert score_rules(c, r)["status"] == "pass"


def test_part_attachment_checks_are_exact_except_documented_compact_lists(fixture):
    c = case(fixture, "Q04")
    name = c["must_cite"][0]
    r = response(f"EN-AW 5005 [cite: {name}]", [name])
    assert score_rules(c, r)["status"] == "pass"
    r["parts_to_show"].append({"key": "D-014", "id": "D-014/part"})
    assert not check(score_rules(c, r), "parts_shown")["passed"]
    compact = case(fixture, "Q01")
    r["parts_to_show"] = [{"key": str(i)} for i in range(4)]
    assert check(score_rules(compact, r), "parts_shown")["passed"]


def test_m3_callout_citation_is_grounded_in_m3_feature(fixture):
    c = case(fixture, "Q16")
    name = "D-013/template/holes/0"
    r = response(f"8 [cite: {name}]", [name])
    assert not check(score_rules(c, r), "citations")["passed"]
    r["facts"][name]["display"]["value"] = {"thread": "M3", "count": 8}
    assert score_rules(c, r)["status"] == "pass"


def test_no_attachment_instruction_does_not_mean_no_cards(fixture):
    c = case(fixture, "Q20")
    r = response("Max Photonics, may be out of date [cite: BOM:optics/laser-source/supplier]", c["must_cite"], "bom/optics/laser-source")
    assert score_rules(c, r)["status"] == "pass"


def test_unicode_abstention_and_source_box_provenance(fixture):
    c = case(fixture, "Q15")
    r = response("I can’t determine a torque; the drawing gives no tightening torque. [cite: D-013/part]", c["must_cite"])
    assert score_rules(c, r)["status"] == "pass"
    c = case(fixture, "Q13")
    name = "D-017/unrecorded/width"
    r = response(f"[undetermined: {name}]", [name], "D-017")
    r["facts"][name].update(display={"state":"undetermined"}, sources=[{"name":"D-017/drawing/n/42", "box":[1,2,3,4]}])
    assert score_rules(c, r)["status"] == "pass"


def test_pending_precondition_does_not_become_a_combined_pass(fixture):
    c = case(fixture, "Q04")
    name = c["must_cite"][0]
    e = {"pass": 1, "case_id": c["id"], "response": response(f"EN-AW 5005 [cite: {name}]", [name]),
         "preconditions": [{"name": "test_mapping", "status": "pending"}]}
    manifest = {"source_sha256": fixture["source_sha256"], "code_sha256": "code", "settings_sha256": "settings"}
    payload = judge_payload(c, e, manifest)
    judgments = {payload["cache_key"]: {"score": 2}}
    report = report_results(fixture, manifest, [e], judgments)["report"]
    assert report["results"][0]["combined"] == "pending_precondition"
    assert report["summary"]["combined_pass"] == 0
    assert report["human_judge_spot_check"]["decisions_checked"] == 0


def test_judge_key_changes_with_every_scored_input(fixture):
    c = case(fixture, "Q04")
    e = {"pass": 1, "case_id": c["id"], "response": response("example")}
    m = {"source_sha256": "draft", "code_sha256": "code", "settings_sha256": "settings"}
    original = judge_payload(c, e, m)
    assert fingerprint({k: v for k, v in original.items() if k != "cache_key"}) == original["cache_key"]
    for field in ("source_sha256", "code_sha256", "settings_sha256"):
        assert judge_payload(c, e, {**m, field: "changed"})["cache_key"] != original["cache_key"]
    changed = copy.deepcopy(e)
    changed["response"]["facts"]["new"] = {"display": {"value": 5}}
    assert judge_payload(c, changed, m)["cache_key"] != original["cache_key"]
    changed["response"]["text"] = "different answer"
    assert judge_payload(c, changed, m)["cache_key"] != original["cache_key"]


def test_import_rejects_stale_model_conflicting_scores_and_ignores_invalid(tmp_path):
    path = tmp_path / "judgments.jsonl"
    row = {"cache_key": "key", "score": 2, "unsupported_claims": [], "reason": "Faithful", "judge": JUDGE}
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert load_judgments(path, {"key"})["key"]["score"] == 2
    with pytest.raises(ValueError, match="stale"):
        load_judgments(path, {"different"})
    path.write_text(json.dumps({**row, "judge": {**JUDGE, "model": "gpt-6-luna"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        load_judgments(path, {"key"})
    path.write_text(json.dumps(row) + "\n" + json.dumps({**row, "score": 0}), encoding="utf-8")
    with pytest.raises(ValueError, match="Conflicting"):
        load_judgments(path, {"key"})
    path.write_text(json.dumps({**row, "score": None, "valid": False}) + "\n" + json.dumps(row), encoding="utf-8")
    assert load_judgments(path, {"key"})["key"]["score"] == 2


def test_report_keeps_judge_pending_and_reports_repeatability(fixture):
    c = case(fixture, "Q04")
    n = c["must_cite"][0]
    r = response(f"EN-AW 5005 [cite: {n}]", [n], usage={"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}, latency_ms=80)
    executions = [{"pass": p, "case_id": c["id"], "response": r, "wall_latency_ms": 100} for p in (1, 2)]
    m = {"source_sha256": "draft", "code_sha256": "code", "settings_sha256": "settings"}
    report = report_results(fixture, m, executions, {})["report"]
    assert report["summary"]["rules_pass"] == 2
    assert report["summary"]["judge_pending"] == 2
    assert report["summary"]["combined_pass"] == 0
    assert report["repeatability"]["same_rule_results"] == 1
    assert report["repeatability"]["combined_pairs_pending_judge"] == 1
    assert report["provider_cost"]["amount_usd"] is None
    assert report["measured_usage"]["total_tokens"] == 14
