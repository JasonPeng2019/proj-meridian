"""Focused checks of the evidence/consensus boundary; no provider calls."""
import copy
import json
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


def test_unsure_and_invalid_do_not_retry(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unsure/invalid answers must never trigger a retry")
    monkeypatch.setattr(runner, "retry_pair", forbidden)
    for status in ("unsure", "invalid", "agreed"):
        result = {"states": {"link": status}, "rounds": []}
        assert pipeline.run_retry(result) is result


def test_one_retry_preserves_both_rounds_and_requires_changed_evidence(monkeypatch):
    current = job()
    first = {"claude": output(item()), "codex": output(item(value=["BOM:a/c"], refs=["BOM:a/c"]))}
    answers = {r: pipeline.decode_answer(v, current) for r, v in first.items()}
    result = {"job": current, "states": {"link": "disagree"}, "rounds": [copy.deepcopy(first)], "answers": answers}
    second = {"claude": output(item()), "codex": output(item())}
    second["codex"]["answer"]["items"][0]["changed_because"] = "I confused row c; row b has the exact drawing filename."
    calls = []
    monkeypatch.setattr(runner, "retry_pair", lambda *a, **kw: calls.append(a) or second)
    pipeline.run_retry(result)
    assert result["states"]["link"] == "agreed_after_retry"
    assert len(result["rounds"]) == 2
    assert result["rounds"][0] == first
    pipeline.run_retry(result)
    assert len(calls) == 1
    assert pipeline.decode_answer(output(item()), current, retry=True,
                                  previous=pipeline.decode_answer(first["codex"], current)) == {}


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
