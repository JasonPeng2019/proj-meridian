"""Expansion's evidence and append-only integration safeguards; no provider or CAD calls."""
import copy
import json

import pytest

from scripts import expand_models as expansion


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def drawing(did):
    return {"id": did, "image": f"images/{did}.png", "fields": {"material": {"name": did + "/drawing/material", "value": None, "method": "parsed"}}, "numbers": []}


def test_expansion_job_adds_strict_eligibility_and_leaves_raw_evidence_unchanged():
    raw = drawing("D-001")
    before = copy.deepcopy(raw)
    job = expansion.expansion_job(raw)
    assert raw == before
    assert job["kind"] == "template" and "cad_eligibility" in job["keys"]
    assert "bounding rectangle" in job["prompt"]
    assert "unlabeled number" in job["prompt"]


def test_fused_evidence_is_rejected(tmp_path, monkeypatch):
    raw = drawing("D-001")
    raw["fields"]["material"]["method"] = "ai_verified"
    write(tmp_path / "drawings.json", {"D-001": raw})
    monkeypatch.setattr(expansion, "GENERATED", tmp_path)
    with pytest.raises(ValueError, match="raw parsed evidence"):
        expansion.raw_drawings()


def test_append_preserves_original_templates_scans_links_mappings_metrics(tmp_path, monkeypatch):
    initial = {"templates": {"D-013": {"original": True}}, "scans": {"D-001": {"historical": True}},
               "links": {"D-013": {"bom_rows": ["unchanged"]}}, "mappings": [{"review": "pending"}],
               "metrics": {"historical_calls": 123}}
    drawings = {did: drawing(did) for did in ("D-001", "D-002", "D-013")}
    write(tmp_path / "ai_results.json", initial)
    write(tmp_path / "drawings.json", drawings)
    monkeypatch.setattr(expansion, "GENERATED", tmp_path)
    monkeypatch.setattr(expansion.runner, "CACHE", tmp_path / "ai_cache")
    monkeypatch.setattr(expansion, "require_settings", lambda: None)
    monkeypatch.setattr(expansion.runner, "bootstrap_auth", lambda: None)
    calls = []
    monkeypatch.setattr(expansion.pipeline, "execute", lambda job, force=False: {"job": job, "rounds": []})
    monkeypatch.setattr(expansion.pipeline, "run_retry", lambda result, force=False: result)
    def assess(result, raw):
        did = result["job"]["drawing"]
        calls.append(did)
        return {"part": did, "cad_ready": False}, {"drawing": did, "status": "blocked", "reason": "No thickness"}, {"provider_calls": 0}
    monkeypatch.setattr(expansion, "assess", assess)
    summary = expansion.expand()
    actual = json.loads((tmp_path / "ai_results.json").read_text(encoding="utf-8"))
    assert calls == ["D-001", "D-002"]
    assert actual["templates"]["D-013"] == initial["templates"]["D-013"]
    for key in ("scans", "links", "mappings"):
        assert actual[key] == initial[key]
    assert actual["metrics"]["historical_calls"] == 123
    assert len(actual["metrics"]["model_expansions"]) == 1
    assert summary["blocked"] == calls
    assert json.loads((tmp_path / "ai_cache/artifacts/ai_results.json").read_text(encoding="utf-8")) == actual
