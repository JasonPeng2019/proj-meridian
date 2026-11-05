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


@pytest.mark.parametrize("pause", [False, True])
def test_append_preserves_original_templates_scans_links_mappings_metrics(tmp_path, monkeypatch, pause):
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
        if pause:
            (tmp_path / "ai_cache").mkdir(parents=True, exist_ok=True)
            (tmp_path / "ai_cache/model_expansion.pause").touch()
        return {"part": did, "cad_ready": False}, {"drawing": did, "status": "blocked", "reason": "No thickness"}, {"provider_calls": 0}
    monkeypatch.setattr(expansion, "assess", assess)
    summary = expansion.expand()
    actual = json.loads((tmp_path / "ai_results.json").read_text(encoding="utf-8"))
    if pause:
        assert calls == ["D-001"]
        assert summary["paused"] and summary["remaining"] == 1
        assert actual == initial
        journals = list((tmp_path / "ai_cache/model_expansion").glob("*.json"))
        receipt = json.loads(journals[0].read_text(encoding="utf-8"))
        assert receipt["prepared_templates"]["D-001"]["cad_ready"] is False
        return
    assert calls == ["D-001", "D-002"]
    assert actual["templates"]["D-013"] == initial["templates"]["D-013"]
    for key in ("scans", "links", "mappings"):
        assert actual[key] == initial[key]
    assert actual["metrics"]["historical_calls"] == 123
    assert len(actual["metrics"]["model_expansions"]) == 1
    assert summary["blocked"] == calls
    assert json.loads((tmp_path / "ai_cache/artifacts/ai_results.json").read_text(encoding="utf-8")) == actual


def test_resume_replays_only_fingerprinted_blocked_receipts_without_providers(tmp_path, monkeypatch):
    raw = drawing("D-001")
    write(tmp_path / "drawings.json", {"D-001": raw})
    image = tmp_path / raw["image"]
    image.parent.mkdir(parents=True)
    image.write_bytes(b"preserved evidence image")
    monkeypatch.setattr(expansion, "GENERATED", tmp_path)
    monkeypatch.setattr(expansion.pipeline, "GENERATED", tmp_path)
    monkeypatch.setattr(expansion.runner, "CACHE", tmp_path / "ai_cache")
    monkeypatch.setattr(expansion.runner, "run_reader", lambda *a, **k: pytest.fail("Resume must not call a provider"))
    keys = ["outline_type", "thickness", "features", "cad_eligibility"]
    job = expansion.expansion_job(raw)
    items = [{"key": key, "state": "unknown", "value_json": "null", "confidence": "unsure",
              "fact_ids": ["D-001/drawing/source"], "reason": "Essential outline unsupported", "changed_because": ""} for key in keys]
    proposal = {"valid": True, "answer": {"items": items}}
    round_job = {**job, "keys": keys}
    decoded = expansion.pipeline.decode_answer(proposal, round_job)
    fingerprint = expansion.runner.fingerprint({"protocol": expansion.pipeline.PROTOCOL, "keys": keys,
                  "proposal": proposal["answer"], "locally_valid_keys": sorted(decoded), "invalid_keys": []})
    verifier = {"valid": True, "answer": {"proposal_fingerprint": fingerprint, "items": [
        {"key": key, "decision": "needs_input", "reason": "Essential contour unsupported", "repairable": False,
         "fact_ids": ["D-001/drawing/source"]} for key in keys]}}
    calls = []
    for reader, role, response, schema in (("codex", "proposal", proposal, expansion.pipeline.schema(keys)),
                                            ("claude", "verification", verifier, expansion.pipeline.verification_schema(keys))):
        identity = {"protocol": 2, "reader": expansion.runner.reader_settings(reader), "prompt": "original frozen task",
                    "schema": schema, "images": [expansion.digest(image)]}
        key = expansion.runner.fingerprint(identity)
        folder = tmp_path / "ai_cache" / key
        write(folder / "request.json", {**identity, "job": f"{job['id']}:{expansion.pipeline.PROTOCOL}:{role}:0"})
        write(folder / "result.json", {**response, "cache_key": key})
        calls.append({"reader": reader, "cache_key": key})
    journal = {"protocol": expansion.EXPANSION_PROTOCOL, "raw_drawings_sha256": expansion.digest(tmp_path / "drawings.json"),
               "assessments": {"D-001": {"status": "blocked", "protocol": expansion.pipeline.PROTOCOL,
                                         "states": {key: "needs_input" for key in keys}}},
               "usage": [{"drawing": "D-001", "calls": calls}]}
    write(tmp_path / "journal.json", journal)
    templates, assessments, _ = expansion.restore_blocked(tmp_path / "journal.json", {"D-001": raw})
    assert not templates["D-001"]["cad_ready"] and assessments["D-001"]["status"] == "blocked"
    image.write_bytes(b"changed image")
    with pytest.raises(ValueError, match="fingerprint changed"):
        expansion.restore_blocked(tmp_path / "journal.json", {"D-001": raw})
