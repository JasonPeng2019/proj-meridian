"""Focused proposal/verification and legacy receipt checks; no provider calls."""
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ai import pipeline, runner
from backend.ai import dimensions


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


def image_dimension_fixture():
    drawing = {"id": "D-011", "sha256": "a" * 64, "page_sizes": [[100, 200]],
               "images": ["images/D-011-p1.png"], "numbers": [], "fields": {}, "degraded": True}
    number = {"text": "2 x ⌀6,5 THRU ALL", "token": "6,5", "value": 6.5,
              "unit": "mm", "box": [10, 20, 35, 8]}
    return drawing, number


def test_image_dimensions_use_original_images_and_preserve_verified_source_provenance(monkeypatch):
    drawing, number = image_dimension_fixture()
    original = copy.deepcopy(drawing)
    current = dimensions.job(drawing)
    source = "D-011/drawing/source"
    calls = mock_readers(monkeypatch, [output(item("page_1", [number], refs=[source]))],
                         [output(verdict("page_1", refs=[source]))])
    result = pipeline.run_retry(pipeline.execute(current))
    evidence = pipeline.assemble([result], {drawing["id"]: drawing}, {})["dimension_evidence"]["D-011"]
    attached = dimensions.attach(drawing, evidence)
    field = attached["numbers"][0]
    assert [call["reader"] for call in calls] == ["codex", "claude"]
    assert calls[0]["images"] == calls[1]["images"] == current["images"]
    assert evidence["source_sha256"] == drawing["sha256"]
    assert field["value"] == 6.5 and field["page"] == 1 and field["box"] == number["box"]
    assert field["name"].startswith("D-011/drawing/visual-n/p1-")
    assert field["original"] == number["text"] and field["fact_ids"] == [source]
    assert field["method"] == "ai_verified" and field["review"] == {"status": "not_reviewed"}
    assert field["readers"]["codex"]["role"] == "proposer"
    assert field["readers"]["claude"]["role"] == "verifier"
    assert drawing == original and dimensions.attach(attached, evidence) == attached
    template = pipeline.template_job(attached)
    assert template["numbers"][field["name"]] == 6.5
    assert field["name"] in template["sources"]
    assert '"readers"' not in template["prompt"] and '"proposal_fingerprint"' not in template["prompt"]
    assert dimensions.attach(drawing, {**evidence, "source_sha256": "b" * 64}) == original
    tampered = copy.deepcopy(evidence)
    tampered["fields"][0]["value"] = 65
    assert dimensions.attach(drawing, tampered) == original
    unverified = copy.deepcopy(evidence)
    unverified["pages"]["page_1"]["method"] = "ai_unsure"
    assert dimensions.attach(drawing, unverified) == original


@pytest.mark.parametrize("mutation", [
    {"value": 13}, {"value": True}, {"value": float("inf")}, {"token": "7"},
    {"token": "6.5"}, {"unit": "in"}, {"box": [-1, 0, 1, 1]},
    {"box": [90, 0, 20, 1]}, {"box": [0, 0, 1, 0]}, {"box": [0, 0, 1, float("nan")]},
])
def test_image_dimensions_reject_conversions_unsupported_tokens_and_invalid_source_boxes(mutation):
    drawing, number = image_dimension_fixture()
    current = dimensions.job(drawing)
    answer = item("page_1", [{**number, **mutation}], refs=current["sources"])
    assert pipeline.decode_answer(output(answer), current) == {}


def test_image_dimensions_rejected_page_stays_unindexed_and_repairs_once(monkeypatch):
    drawing, number = image_dimension_fixture()
    current = dimensions.job(drawing)
    source = current["sources"]
    first = output(item("page_1", [{**number, "value": 65}], refs=source))
    repair = output({**item("page_1", [number], refs=source),
                     "changed_because": "Original printed decimal comma was missed; corrected from the same label."})
    calls = mock_readers(monkeypatch, [first, repair],
                         [output(verdict("page_1", "reject", True, source)), output(verdict("page_1", refs=source))])
    result = pipeline.execute(current)
    assert dimensions.assemble(result)["fields"] == []
    pipeline.run_retry(result)
    assert result["states"] == {"page_1": "verified_after_retry"} and len(calls) == 4
    assert dimensions.assemble(result)["fields"][0]["value"] == 6.5
    assert pipeline.run_retry(result) is result and len(calls) == 4


def test_image_dimensions_reject_duplicate_tokens_and_wrong_source():
    drawing, number = image_dimension_fixture()
    current = dimensions.job(drawing)
    assert pipeline.decode_answer(output(item("page_1", [number, number], refs=current["sources"])), current) == {}
    assert pipeline.decode_answer(output(item("page_1", [number], refs=["D-020/drawing/source"])), current) == {}


def test_single_page_dimension_jobs_preserve_exact_existing_job_and_cache_identity():
    drawing, _ = image_dimension_fixture()
    assert dimensions.jobs(drawing) == [dimensions.job(drawing)]


def test_multi_page_dimension_jobs_preserve_original_pages_images_and_merge_all_fields(monkeypatch):
    drawing, _ = image_dimension_fixture()
    drawing.update(page_sizes=[[100, 200], [200, 300], [300, 400]],
                   images=[f"images/D-011-p{page}.png" for page in (1, 2, 3)])
    original = copy.deepcopy(drawing)
    current_jobs = dimensions.jobs(drawing)
    base = dimensions.job(drawing)
    proposals, verifications = [], []
    for page, current in enumerate(current_jobs, start=1):
        key = f"page_{page}"
        assert current["id"] == base["id"] + ":" + key
        assert current["keys"] == [key] and current["images"] == [base["images"][page - 1]]
        assert current["page_sizes"] == drawing["page_sizes"]
        assert current["image_original_pages"] == [page]
        assert json.loads(current["prompt"].rsplit("\n", 1)[1])["image_original_pages"] == [page]
        assert f"return ONLY key {key}" in current["prompt"]
        # These page-2/page-3 boxes exceed page 1's dimensions. Validation must
        # index the ORIGINAL page-size table, never the single supplied image.
        number = {"text": str(page * 10), "token": str(page * 10), "value": page * 10,
                  "unit": "mm", "box": [page * 100 - 50, page * 100 + 50, 20, 8]}
        proposals.append(output(item(key, [number], refs=current["sources"])))
        verifications.append(output(verdict(key, refs=current["sources"])))
    calls = mock_readers(monkeypatch, proposals, verifications)
    results = [pipeline.execute(current) for current in current_jobs]
    assert all(list(result["states"].values()) == ["verified"] for result in results)
    evidence = pipeline.assemble(list(reversed(results)), {drawing["id"]: drawing}, {})["dimension_evidence"][drawing["id"]]
    assert set(evidence["pages"]) == {"page_1", "page_2", "page_3"}
    assert [field["page"] for field in evidence["fields"]] == [1, 2, 3]
    assert [field["value"] for field in evidence["fields"]] == [10, 20, 30]
    for page, field in enumerate(evidence["fields"], start=1):
        assert field["name"].startswith(f"D-011/drawing/visual-n/p{page}-")
        assert field["box"] == [page * 100 - 50, page * 100 + 50, 20, 8]
        assert calls[(page - 1) * 2]["images"] == calls[(page - 1) * 2 + 1]["images"] == current_jobs[page - 1]["images"]
    assert len(dimensions.attach(drawing, evidence)["numbers"]) == 3 and drawing == original
    duplicate = pipeline.assemble([*results, results[1]], {drawing["id"]: drawing}, {})["dimension_evidence"][drawing["id"]]
    assert duplicate == evidence
    stale = copy.deepcopy(results[1])
    stale["job"]["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="different original drawings"):
        pipeline.assemble([results[0], stale], {drawing["id"]: drawing}, {})


def test_dimensioned_corner_clips_require_explicit_corners_and_sourced_setbacks():
    current = {**job(), "kind": "template", "keys": ["features"], "numbers": {"BOM:a/b": 1}}
    scalar = {"state": "known", "value": 1, "fact_ids": ["BOM:a/b"]}
    clip = {"kind": "corner_chamfer", "corners": ["x_min_y_min", "x_max_y_max"],
            "x_setback": scalar, "y_setback": scalar, "fact_ids": ["BOM:a/b"]}
    assert pipeline.decode_answer(output(item("features", [clip])), current)["features"]["value"] == [clip]
    for mutation in ({"corners": []}, {"corners": ["top"]}, {"corners": ["x_min_y_min"] * 2},
                     {"x_setback": 1}, {"y_setback": {**scalar, "value": 2}}, {"face": "top"},
                     {"through": True}, {"fact_ids": []}):
        assert pipeline.decode_answer(output(item("features", [{**clip, **mutation}])), current) == {}


def test_side_holes_need_sourced_z_and_keep_global_frame():
    current = {**job(), "kind": "template", "keys": ["features"],
               "numbers": {"BOM:a/b": 10, "BOM:a/c": 5}}
    scalar = lambda value, **extra: {"state": "known", "value": value, "fact_ids": ["BOM:a/b"], **extra}
    hole = {"kind": "hole", "face": "x_min", "x": scalar(-5, expression="-n0/2"), "y": scalar(0),
            "z": scalar(5, expression="n0/2"),
            "diameter": {"state": "known", "value": 5, "fact_ids": ["BOM:a/c"]},
            "hole_type": "plain", "through": True}
    assert pipeline.decode_answer(output(item("features", [hole])), current)["features"]["value"] == [hole]
    for mutation in ({"z": None}, {"z": 5}, {"z": scalar(0)}, {"z": scalar(4, expression="n0/2")},
                     {"kind": "slot"}, {"hole_type": "counterbored"}, {"pattern": {}}):
        assert pipeline.decode_answer(output(item("features", [{**hole, **mutation}])), current) == {}


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


def test_conventional_pattern_placement_requires_explicit_basis_reason_and_sources():
    current, _, _, hole = partial_feature_job()
    feature = {**hole, "placement_basis": "drawing_pattern_interpretation",
               "placement_reason": "Printed four-hole count and radius with cardinal axes establish the circle; angles are interpreted.",
               "fact_ids": ["BOM:a/b", "BOM:a/c"],
               "pattern": {"type": "circle", "count": {"state": "known", "value": 4, "fact_ids": ["count"]},
                           "radius": {"state": "known", "value": 10, "fact_ids": ["BOM:a/b"]},
                           "start_angle": {"state": "known", "value": 0, "fact_ids": ["BOM:a/b"]}}}
    current["numbers"]["count"] = 4
    current["sources"].append("count")
    assert pipeline.decode_answer(output(item("features", [feature])), current)["features"]["value"] == [feature]
    for mutation in ({"placement_basis": "guessed"}, {"placement_reason": ""}, {"fact_ids": []}, {"fact_ids": ["invented"]}):
        assert pipeline.decode_answer(output(item("features", [{**feature, **mutation}])), current) == {}
    ungrounded = copy.deepcopy(feature)
    ungrounded["pattern"]["radius"]["value"] = 11
    assert pipeline.decode_answer(output(item("features", [ungrounded])), current) == {}
    # Existing untagged receipts and directly dimensioned placements retain their compatibility.
    assert pipeline.decode_answer(output(item("features", [hole])), current)
    assert pipeline.decode_answer(output(item("features", [{**hole, "placement_basis": "dimensioned"}])), current)


def test_step_variant_fallback_is_explicit_boolean_cited_and_never_changes_depth():
    current, _, _, hole = partial_feature_job()
    current["numbers"].update({"step-diameter": 8, "step-depth": 15.4})
    current["sources"] += ["step-diameter", "step-depth"]
    feature = {**hole, "face": "bottom", "hole_type": "counterbored", "fact_ids": ["BOM:a/b", "step-depth"],
               "counterbore_diameter": {"state": "known", "value": 8, "fact_ids": ["step-diameter"]},
               "counterbore_depth": {"state": "known", "value": 15.4, "fact_ids": ["step-depth"]},
               "allow_primary_hole_without_unresolved_step": True,
               "step_conflict_reason": "Printed 15.4 counterbore depth exceeds the documented 15 thickness alternative."}
    decoded = pipeline.decode_answer(output(item("features", [feature])), current)
    assert decoded["features"]["value"][0]["counterbore_depth"]["value"] == 15.4
    assert decoded["features"]["value"][0]["face"] == "bottom"
    for mutation in ({"allow_primary_hole_without_unresolved_step": "true"}, {"step_conflict_reason": ""},
                     {"through": False}, {"hole_type": "plain"}, {"fact_ids": []}):
        assert pipeline.decode_answer(output(item("features", [{**feature, **mutation}])), current) == {}
    ungrounded = copy.deepcopy(feature)
    ungrounded["counterbore_depth"]["value"] = 15
    assert pipeline.decode_answer(output(item("features", [ungrounded])), current) == {}


def test_template_prompt_explains_pattern_interpretation_faces_and_variant_fallback():
    current = pipeline.template_job({"id": "D-001", "image": "drawings/test.png"})
    prompt = current["prompt"]
    assert "360/count" in prompt and "drawing_pattern_interpretation" in prompt
    assert "viewed from +Z" in prompt and "face='top' or 'bottom'" in prompt
    assert "step_conflict_reason" in prompt and "never clamp its depth" in prompt
    assert "Opus must verify this EXACT layout" in prompt
    assert "Every slot MUST include a structured direction" in prompt


def slot_fixture():
    scalar = lambda value: {"state": "known", "value": value, "fact_ids": ["BOM:a/b"]}
    return {"kind": "slot", "face": "top", "x": scalar(0), "y": scalar(0),
            "width": scalar(5), "length": scalar(10), "through": True,
            "placement_reason": "Long axes follow Y", "fact_ids": ["BOM:a/b"]}


@pytest.mark.parametrize("key,direction", [
    ("direction", {"state": "known", "value": 90, "fact_ids": ["BOM:a/b"]}),
    ("direction", "Y"), ("direction", "vertical"), ("direction", "x"), ("direction", "horizontal"),
    ("angle", {"state": "known", "value": 90, "fact_ids": ["BOM:a/b"]}), ("angle", "y")])
def test_structured_slot_direction_accepts_grounded_cardinals_and_existing_aliases(key, direction):
    current = {**job(), "kind": "template", "keys": ["features"], "numbers": {"BOM:a/b": 10, "BOM:a/c": 5}}
    feature = {**slot_fixture(), key: direction}
    feature["width"]["fact_ids"] = ["BOM:a/c"]
    decoded = pipeline.decode_answer(output(item("features", [feature])), current)
    assert decoded["features"]["value"][0][key] == direction


@pytest.mark.parametrize("direction", ["diagonal", 45, True, {"state": "known", "value": 45, "fact_ids": ["BOM:a/b"]},
                                       {"state": "unknown", "value": 90, "fact_ids": ["BOM:a/b"]}])
def test_slot_direction_rejects_arbitrary_or_unresolved_orientation(direction):
    current = {**job(), "kind": "template", "keys": ["features"], "numbers": {"BOM:a/b": 10, "BOM:a/c": 5}}
    feature = {**slot_fixture(), "direction": direction}
    feature["width"]["fact_ids"] = ["BOM:a/c"]
    assert pipeline.decode_answer(output(item("features", [feature])), current) == {}


def test_missing_slot_direction_triggers_only_one_features_repair_and_preserves_other_fields(monkeypatch):
    current = {**job(), "kind": "template", "keys": ["length", "features"], "numbers": {"BOM:a/b": 10, "BOM:a/c": 5}}
    slot = slot_fixture()
    slot["width"]["fact_ids"] = ["BOM:a/c"]
    first = output(item("length", 10), item("features", [slot]))
    repaired = {**slot, "direction": "y"}
    second = output({**item("features", [repaired]), "changed_because": "The supported Y-axis orientation was only in prose; the structured direction was missing."})
    calls = mock_readers(monkeypatch, [first, second], [output(verdict("length"), verdict("features")), output(verdict("features"))])
    result = pipeline.execute(current)
    original_length = copy.deepcopy(result["answers"]["codex"]["length"])
    assert result["states"] == {"length": "verified", "features": "invalid"}
    pipeline.run_retry(result)
    assert result["feedback_rounds"][0]["keys"] == ["features"]
    assert result["states"] == {"length": "verified", "features": "verified_after_retry"}
    assert result["answers"]["codex"]["length"] == original_length
    assert result["rounds"][0]["codex"]["answer"] == first["answer"]
    assert len(calls) == 4
    pipeline.run_retry(result)
    assert len(calls) == 4


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
