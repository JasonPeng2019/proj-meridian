"""Focused proposal/verification and legacy receipt checks; no provider calls."""
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ai import pipeline, runner


def item(key="link", value=None, confidence="sure", state="known", refs=None):
    return {"key": key, "state": state, "value_json": json.dumps(value if value is not None else ["BOM:a/b"]),
            "confidence": confidence, "fact_ids": refs or ["BOM:a/b"], "reason": "Cited source says this",
            "changed_because": ""}


def output(*items):
    return {"valid": True, "answer": {"items": list(items)}}


def job():
    return {"id": "link:D-001", "drawing": "D-001", "kind": "link", "keys": ["link"], "images": [], "prompt": "read evidence",
            "sources": ["BOM:a/b", "BOM:a/c"], "row_ids": ["BOM:a/b", "BOM:a/c"]}


def test_consensus_requires_both_sure_and_same_state():
    a = {"confidence": "sure", "state": "known", "value": [3, 6]}
    assert runner.compare(a, dict(a)) == "agreed"
    assert runner.compare(a, {**a, "state": "options"}) == "disagree"
    assert runner.compare(a, {**a, "confidence": "unsure"}) == "unsure"
    assert runner.compare(a, None) == "invalid"
    assert runner.compare({**a, "value": 250}, {**a, "value": 250.0}) == "agreed"
    f = [{"kind": "hole", "x": {"state": "known", "value": 5, "fact_ids": ["one"]}}]
    g = [{"kind": "hole", "x": {"state": "known", "value": 5.0, "fact_ids": ["two"], "expression": "n0"}}]
    assert runner.compare({**a, "value": f}, {**a, "value": g}) == "agreed"


def test_invented_ids_and_rows_are_rejected():
    assert pipeline.decode_answer(output(item(value=["BOM:invented/name"])), job()) == {}
    assert pipeline.decode_answer(output(item(refs=["D-001/invented"])), job()) == {}
    assert pipeline.decode_answer(output(item(), item()), job()) == {}
    assert pipeline.decode_answer({"valid": False}, job()) == {}
    unknown = {**item(), "state": "unknown", "value_json": "null", "confidence": "unsure"}
    decoded = pipeline.decode_answer(output(unknown), job())
    assert runner.compare(decoded["link"], decoded["link"]) == "unsure"
    broken = {"job": job(), "rounds": [{r: {"valid": False, "answer": None} for r in ("claude", "codex")}],
              "answers": {"claude": {}, "codex": {}}, "states": {"link": "invalid"}}
    assert pipeline.assemble([broken], {}, {})["links"]["D-001"]["state"] == "needs_review"
    assert pipeline.assemble([broken], {}, {})["links"]["D-001"]["method"] == "unresolved"


def test_numeric_grounding_and_safe_derivation():
    nums = {"a": 270.0, "b": 10.0}
    pipeline.validate_geometry({"x": {"state": "known", "value": 125, "expression": "n0/2-n1", "fact_ids": ["a", "b"]}}, nums, set(nums), [])
    with pytest.raises(ValueError):
        pipeline.validate_geometry({"diameter": 7, "fact_ids": ["a"]}, nums, set(nums), [])
    with pytest.raises(ValueError):
        pipeline.expression_value("__import__('os')", [])
    with pytest.raises(ValueError):
        pipeline.validate_geometry({"x": {"value": 126, "expression": "n0/2-n1", "fact_ids": ["a", "b"]}}, nums, set(nums), [])


def test_legacy_receipts_are_not_reinterpreted_or_retried(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy receipts must never become verified by reinterpretation")
    monkeypatch.setattr(runner, "run_reader", forbidden)
    for status in ("unsure", "invalid", "agreed", "disagree"):
        result = {"states": {"link": status}, "rounds": []}
        assert pipeline.run_retry(result) is result


def verdict(key="link", decision="accept", repairable=False, refs=None):
    return {"key": key, "decision": decision, "repairable": repairable,
            "fact_ids": refs if refs is not None else ["BOM:a/b"], "reason": "Original source supports this exact proposal"}


def mock_readers(monkeypatch, proposals, verifications):
    calls = []
    queues = {"codex": iter(proposals), "claude": iter(verifications)}
    def fake(reader, prompt, schema, images, job, **kwargs):
        calls.append({"reader": reader, "prompt": prompt, "schema": schema, "images": images, "job": job})
        raw = copy.deepcopy(next(queues[reader]))
        if reader == "claude" and raw.get("valid"):
            raw["answer"].setdefault("proposal_fingerprint", re.search(r"Copy this proposal_fingerprint exactly: ([0-9a-f]{64})", prompt)[1])
        return {**raw, "settings": runner.reader_settings(reader), "cache_hit": False, "cache_key": f"mock-{len(calls)}"}
    monkeypatch.setattr(runner, "run_reader", fake)
    monkeypatch.setattr(runner, "pair", lambda *a, **kw: pytest.fail("New prep must not use independent reader pair"))
    return calls


def test_proposal_is_verified_sequentially_against_original_evidence(monkeypatch):
    current = {**job(), "images": ["original-drawing.png"]}
    calls = mock_readers(monkeypatch, [output(item(confidence="unsure"))], [output(verdict())])
    result = pipeline.execute(current)
    assert [c["reader"] for c in calls] == ["codex", "claude"]
    assert result["states"] == {"link": "verified"}
    assert pipeline.PROTOCOL in calls[0]["prompt"] and pipeline.PROTOCOL in calls[1]["prompt"]
    assert current["prompt"] in calls[1]["prompt"] and calls[1]["images"] == current["images"]
    assert "EXACT PROPOSAL PACKET" in calls[1]["prompt"] and "locally_valid_keys" in calls[1]["prompt"]
    assembled = pipeline.assemble([result], {}, {})
    assert assembled["links"]["D-001"]["method"] == "ai_verified"
    assert assembled["metrics"]["verified"] == 1 and assembled["metrics"]["agreed"] == 0
    assert assembled["metrics"]["proposer_calls"] == assembled["metrics"]["verifier_calls"] == 1
    assert pipeline.run_retry(result) is result and len(calls) == 2


def test_one_feedback_retry_preserves_receipts_and_verifies_changed_proposal(monkeypatch):
    first = output(item(value=["BOM:a/c"], refs=["BOM:a/c"]))
    repair = output({**item(), "changed_because": "Original filename supports row b; I misread row c."})
    calls = mock_readers(monkeypatch, [first, repair], [output(verdict(decision="reject", repairable=True)), output(verdict())])
    result = pipeline.execute(job())
    first_round = copy.deepcopy(result["rounds"][0])
    pipeline.run_retry(result)
    assert result["states"] == {"link": "verified_after_retry"}
    assert result["rounds"][0] == first_round
    assert [c["reader"] for c in calls] == ["codex", "claude", "codex", "claude"]
    assert "ONE BOUNDED FEEDBACK REPAIR" in calls[2]["prompt"]
    assert result["feedback_rounds"][0]["keys"] == ["link"]
    field = pipeline.resolved(result, "link")
    assert field["method"] == "ai_verified_after_retry"
    assert field["readers"]["codex"]["role"] == "proposer"
    assert field["readers"]["claude"]["role"] == "verifier"
    assert field["readers"]["codex"]["rounds"][1]["feedback"][0]["verification"]["decision"] == "reject"
    assert field["readers"]["claude"]["rounds"][1]["answer"]["decision"] == "accept"
    pipeline.run_retry(result)
    assert len(calls) == 4
    assert pipeline.decode_answer(output(item()), job(), retry=True,
                                  previous=pipeline.decode_answer(first, job())) == {}


def test_invalid_proposal_cannot_be_accepted_and_gets_one_repair(monkeypatch):
    calls = mock_readers(monkeypatch, [output(item(refs=["invented"])), output(item())],
                         [output(verdict()), output(verdict())])
    result = pipeline.execute(job())
    assert result["states"] == {"link": "invalid"}
    assert not pipeline.agreed(result, "link")
    pipeline.run_retry(result)
    assert result["states"] == {"link": "verified_after_retry"}
    assert "invalid:" in calls[2]["prompt"]
    assert result["rounds"][0]["codex"]["validation"]["link"] is False


def test_nonrepairable_missing_evidence_stays_unknown(monkeypatch):
    unknown = {**item(), "state": "unknown", "value_json": "null", "confidence": "unsure"}
    calls = mock_readers(monkeypatch, [output(unknown)], [output(verdict(decision="needs_input"))])
    result = pipeline.run_retry(pipeline.execute(job()))
    assert result["states"] == {"link": "needs_input"} and len(calls) == 2
    assert pipeline.resolved(result, "link")["value"] is None
    assert pipeline.verification_state(pipeline.decode_answer(output(unknown), job())["link"], verdict()) == "needs_input"


def test_verdict_must_bind_exact_proposal_and_use_original_ids(monkeypatch):
    calls = mock_readers(monkeypatch, [output(item()), output(item())],
                         [{**output(verdict()), "answer": {"proposal_fingerprint": "other-proposal", "items": [verdict()]}},
                          output(verdict(refs=["invented"]))])
    result = pipeline.run_retry(pipeline.execute(job()))
    assert result["states"] == {"link": "invalid"}
    pipeline.run_retry(result)
    assert len(calls) == 4 and not pipeline.agreed(result, "link")


def test_mapping_can_be_verified_with_context_but_still_requires_human_approval(monkeypatch):
    current = {**job(), "id": "mapping:material", "name": "names/material/example", "kind": "mapping",
               "mapping_kind": "material", "keys": ["relationship"], "left": "Silicon Rubber", "right": "Silicone", "evidence": ["BOM:a/b"]}
    raw = output(item("relationship", "kind_of", confidence="unsure"))
    verification = verdict("relationship")
    verification["reason"] = "Rubber source context supports a probable spelling interpretation; this does not equate elemental silicon with silicone."
    mock_readers(monkeypatch, [raw], [output(verification)])
    result = pipeline.execute(current)
    mapping = pipeline.assemble([result], {}, {})["mappings"][0]
    assert mapping["relationship"] == "kind_of" and mapping["method"] == "ai_verified"
    assert mapping["review"] == {"status": "pending_approval"}
    assert "does not equate elemental silicon" in mapping["reason"]


@pytest.mark.parametrize("missing_main_dimension", [True, False])
def test_unknown_main_geometry_blocks_cad_while_minor_features_remain_partial(monkeypatch, missing_main_dimension):
    current = {**job(), "id": "template:D-001", "kind": "template", "keys": [k for k in pipeline.TEMPLATE_KEYS if k not in ("features_complete", "features_omitted")],
               "numbers": {"BOM:a/b": 10, "BOM:a/c": 5}}
    values = {"outline_type": "rectangle", "length": 10, "width": 10, "thickness": 5}
    if missing_main_dimension:
        del values["length"]
    proposals = [item(key, value, refs=["BOM:a/c"] if key == "thickness" else ["BOM:a/b"])
                 for key, value in values.items()]
    proposals += [{**item(key), "state": "unknown", "value_json": "null", "confidence": "unsure"}
                  for key in current["keys"] if key not in values]
    verifications = [verdict(key, decision="accept" if key in values else "needs_input") for key in current["keys"]]
    mock_readers(monkeypatch, [output(*proposals)], [output(*verifications)])
    result = pipeline.run_retry(pipeline.execute(current))
    assembled = pipeline.assemble([result], {"D-001": {"fields": {}}}, {})
    template = assembled["templates"]["D-001"]
    assert template["cad_ready"] is (not missing_main_dimension)
    assert template["blocking_fields"] == (["length"] if missing_main_dimension else [])
    assert template["features_review"]["state"] == "unknown" and template["features"] == []
    assert assembled["metrics"]["sent_to_review"] == (2 if missing_main_dimension else 1)


def test_ungrounded_geometry_is_invalid_even_when_verifier_accepts(monkeypatch):
    current = {**job(), "id": "template:D-001", "kind": "template", "keys": ["length"], "numbers": {"BOM:a/b": 10}}
    mock_readers(monkeypatch, [output(item("length", 11))], [output(verdict("length"))])
    result = pipeline.execute(current)
    assert result["states"] == {"length": "invalid"}
    assert pipeline.resolved(result, "length")["value"] is None


def partial_feature_job(complete=False, omissions=None):
    current = {**job(), "id": "template:D-001", "kind": "template", "keys": list(pipeline.TEMPLATE_KEYS),
               "numbers": {"BOM:a/b": 10, "BOM:a/c": 5}, "feature_protocol": pipeline.FEATURE_PROTOCOL}
    scalar = lambda value, ref: {"state": "known", "value": value, "fact_ids": [ref]}
    hole = {"kind": "hole", "face": "top", "x": scalar(0, "BOM:a/b"), "y": scalar(0, "BOM:a/b"),
            "diameter": scalar(5, "BOM:a/c"), "through": True, "hole_type": "plain"}
    missing = [{"description": "Threaded hole", "reason": "Thread callout does not establish drill diameter",
                "fact_ids": ["BOM:a/b"]}] if omissions is None else omissions
    values = {"outline_type": "rectangle", "length": 10, "width": 10, "thickness": 10,
              "features": [hole], "features_complete": complete, "features_omitted": missing}
    proposals = [item(key, value) for key, value in values.items()]
    proposals += [{**item(key), "state": "unknown", "value_json": "null", "confidence": "unsure"}
                  for key in current["keys"] if key not in values]
    verifications = [verdict(key, decision="accept" if key in values else "needs_input") for key in current["keys"]]
    return current, output(*proposals), output(*verifications), hole


@pytest.mark.parametrize("complete", [False, True])
def test_supported_cuts_survive_independent_omissions_and_preserve_completeness(monkeypatch, complete):
    current, proposals, verifications, hole = partial_feature_job(complete=complete, omissions=[] if complete else None)
    calls = mock_readers(monkeypatch, [proposals], [verifications])
    result = pipeline.run_retry(pipeline.execute(current))
    template = pipeline.assemble([result], {"D-001": {"fields": {}}}, {})["templates"]["D-001"]
    assert len(calls) == 2 and result["states"]["features"] == "verified"
    assert template["features"][0]["diameter"] == hole["diameter"]
    assert template["features_review"]["state"] == "known" and template["cad_ready"] is True
    assert template["features_complete"]["value"] is complete
    assert template["features_all_determined"] is complete
    assert template["features_status"] == ("complete" if complete else "partial")
    assert bool(template["omitted_feature_notes"]) is (not complete)
    if not complete:
        assert template["features_omitted"]["value"][0]["fact_ids"] == ["BOM:a/b"]
        assert "does not establish drill diameter" in template["omitted_feature_notes"][0]


def test_completeness_conflict_repairs_only_flag_without_losing_supported_cuts(monkeypatch):
    current, proposals, verifications, _ = partial_feature_job(complete=True)
    repair = output({**item("features_complete", False), "changed_because": "The cited threaded hole remains omitted; the inventory is incomplete."})
    calls = mock_readers(monkeypatch, [proposals, repair], [verifications, output(verdict("features_complete"))])
    result = pipeline.execute(current)
    assert result["states"]["features"] == "verified" and result["states"]["features_complete"] == "invalid"
    pipeline.run_retry(result)
    assert result["feedback_rounds"][0]["keys"] == ["features_complete"]
    assert result["states"]["features_complete"] == "verified_after_retry" and len(calls) == 4
    template = pipeline.assemble([result], {"D-001": {"fields": {}}}, {})["templates"]["D-001"]
    assert len(template["features"]) == 1 and template["features_status"] == "partial"
    assert template["features_all_determined"] is False


def test_omission_metadata_rejects_invented_sources_and_legacy_unknown_stays_unknown():
    current, _, _, hole = partial_feature_job()
    bad = [{"description": "Unresolved hole", "reason": "Missing diameter", "fact_ids": ["invented"]}]
    assert pipeline.decode_answer(output(item("features_omitted", bad)), current) == {}
    assert pipeline.decode_answer(output(item("features_complete", "false")), current) == {}
    unknown = {**item("features", [hole]), "state": "unknown", "confidence": "unsure"}
    decoded = pipeline.decode_answer(output(unknown), current)
    legacy = {"job": current, "answers": {"claude": decoded, "codex": decoded},
              "states": {"features": "unsure"}, "rounds": [{"claude": output(unknown), "codex": output(unknown)}]}
    assert pipeline.resolved(legacy, "features")["value"] is None


@pytest.mark.parametrize("supported", [True, False])
def test_optional_expansion_eligibility_gates_cad_and_preserves_reason(monkeypatch, supported):
    current = {**job(), "id": "template:D-001", "kind": "template", "keys": [*pipeline.TEMPLATE_KEYS, "cad_eligibility"],
               "numbers": {"BOM:a/b": 10}}
    eligibility = {"supported": supported, "constant_thickness": supported, "outline_exact": supported,
                   "reason": "Exact flat outline" if supported else "Main outline has an undimensioned step",
                   "essential_uncertainty": [] if supported else ["Step dimension"], "omitted_minor_features": []}
    values = {"outline_type": "rectangle", "length": 10, "width": 10, "thickness": 10, "features": [], "cad_eligibility": eligibility}
    proposals = [item(key, value) for key, value in values.items()]
    proposals += [{**item(key), "state": "unknown", "value_json": "null", "confidence": "unsure"}
                  for key in current["keys"] if key not in values]
    verifications = [verdict(key, decision="accept" if key in values else "needs_input") for key in current["keys"]]
    mock_readers(monkeypatch, [output(*proposals)], [output(*verifications)])
    template = pipeline.assemble([pipeline.execute(current)], {"D-001": {"fields": {}}}, {})["templates"]["D-001"]
    assert template["cad_ready"] is supported
    assert template["blocking_fields"] == ([] if supported else ["cad_eligibility"])
    assert template["cad_eligibility"]["value"] == eligibility
    malformed = copy.deepcopy(eligibility)
    malformed["supported"] = True
    malformed["outline_exact"] = False
    assert pipeline.decode_answer(output(item("cad_eligibility", malformed)), current) == {}


def test_cache_hash_covers_input_schema_and_model_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(runner, "bootstrap_auth", lambda: None)
    monkeypatch.setattr(runner, "codex_command", lambda: ["codex"])
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        Path(argv[argv.index("--output-last-message") + 1]).write_text('{"ok":true}', encoding="utf-8")
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    s = {"type": "object"}
    a = runner.run_reader("codex", "evidence A", s, [], "test")
    b = runner.run_reader("codex", "evidence A", s, [], "test")
    assert a["valid"] and b["cache_hit"] and len(calls) == 1
    assert runner.run_reader("codex", "evidence B", s, [], "test")["cache_key"] != a["cache_key"]
    assert runner.run_reader("codex", "evidence A", {**s, "required": []}, [], "test")["cache_key"] != a["cache_key"]
    old = runner.reader_settings
    monkeypatch.setattr(runner, "reader_settings", lambda reader: {**old(reader), "model": "test-model"})
    assert runner.run_reader("codex", "evidence A", s, [], "test")["cache_key"] != a["cache_key"]


def test_exact_datasheet_ambiguity_does_not_fall_through_to_title():
    drawing = {"source_filename": "Plate.pdf", "fields": {"title": {"value": "Plate"}}}
    rows = [{"name": name, "display_name": title, "fields": {"datasheet": {"value": "Plate.pdf"}}}
            for name, title in (("BOM:a/plate", "Plate"), ("BOM:a/stage", "Stage"))]
    assert pipeline.exact_link(drawing, rows) is None
    for row in rows:
        row["fields"]["datasheet"]["value"] = {"filename": "Plate.pdf", "url": "https://example.invalid/snapshot"}
    assert pipeline.exact_link(drawing, rows) is None
    assert pipeline.exact_link(drawing, rows[:1])["reason"] == "Unique datasheet filename"


def test_existing_section_never_marked_no_equivalent_merely_for_missing_links():
    drawings = {"D-001": {"id": "D-001", "section": "Gas Flow"}}
    rows = [{"name": "BOM:gas-flow/example", "section": "Gas-flow"},
            {"name": "BOM:electric/example", "section": "Electric"}]
    jobs = pipeline.mapping_jobs(drawings, rows, {})
    assert [(j["left"], j["right"]) for j in jobs] == [(None, "Electric")]
