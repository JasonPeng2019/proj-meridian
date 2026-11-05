"""Mocked provider checks; parsing never creates a human decision."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import review_parser as parser_module
from backend.app.review_parser import ParserUnavailable, ReviewParser
from backend.app.store import Store


@pytest.fixture
def store():
    value = Store.__new__(Store)
    value.root = Path("parser-fixture-no-files")
    value.revision = "revision-one"
    value.fields = {"D-TEST/template/thickness": {"state": "unknown", "value": None}}
    value.templates = {"D-TEST": {"thickness": value.fields["D-TEST/template/thickness"]}}
    value.owners = {}
    value.fingerprint = lambda target: "source-one"
    value.review_items = lambda: [{"id": target, "target": target, "type": "template"} for target in value.fields]
    value.rebuild_models = lambda: None
    value.saved = []

    def append(target, action, parsed, **metadata):
        event = {"applies_to": target, "type": action, "value": parsed, "by": "Actual fixture reviewer", **metadata}
        value.saved.append(event)
        value.revision = "revision-two"
        return event

    value.append = append
    return value


@pytest.fixture
def provider(monkeypatch):
    response = SimpleNamespace(status="completed", id="response-fixture", _request_id="request-fixture")
    response.output_text = json.dumps({"status": "ready", "value_json": "4.5", "summary": "Thickness: 4.5 mm.", "questions": []})
    calls = []
    constructors = []

    class Client:
        def __init__(self, **kwargs):
            constructors.append(kwargs)
            self.responses = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def create(self, **kwargs):
            calls.append(kwargs)
            return response

    monkeypatch.setattr(parser_module, "AsyncOpenAI", Client)
    monkeypatch.setattr(parser_module, "api_key", lambda: "fixture-key-no-provider-access")
    return response, calls, constructors


def parse(parser, store, statement="four and a half millimetres thick"):
    return asyncio.run(parser.parse(store, "D-TEST/template/thickness", statement))


def test_single_strict_luna_request_and_preview_never_saves(store, provider):
    response, calls, constructors = provider
    before = copy.deepcopy(store.fields)
    result = parse(ReviewParser(), store)
    assert result["status"] == "ready" and result["value"] == 4.5 and result["receipt"]
    assert store.fields == before and store.saved == []
    assert len(calls) == 1 and calls[0]["model"] == "gpt-6-luna"
    assert calls[0]["store"] is False and calls[0]["text"]["format"]["strict"] is True
    assert constructors[0]["max_retries"] == 0 and constructors[0]["timeout"] == 45
    assert "four and a half" in calls[0]["input"][0]["content"]


@pytest.mark.parametrize("field", ["weight_g", "mass_g"])
def test_mass_context_and_explicit_conversion_preserve_original_input(store, provider, field):
    target = f"D-TEST/drawing/{field}"
    store.fields = {target: {"value": 500}}
    provider[0].output_text = json.dumps({"status": "ready", "value_json": "1000", "summary": "1 kg converted to 1000 g.", "questions": []})
    parser = ReviewParser()
    result = asyncio.run(parser.parse(store, target, "1 kg"))
    assert result["value"] == 1000
    context = json.loads(provider[1][0]["input"][0]["content"])["context"]
    assert "grams" in context["expected"]
    assert "453.59237" in provider[1][0]["instructions"]
    _, provenance = parser.resolve(store, target, result["receipt"])
    assert provenance["original_input"] == "1 kg"
    assert not store.saved


def test_ambiguous_statement_returns_questions_without_token(store, provider):
    provider[0].output_text = json.dumps({"status": "needs_clarification", "value_json": None, "summary": "The thickness is ambiguous.", "questions": ["Is the thickness 4 or 5 mm?"]})
    result = parse(ReviewParser(), store, "four or five")
    assert result["status"] == "needs_clarification" and result["questions"]
    assert "receipt" not in result and "value" not in result and not store.saved


@pytest.mark.parametrize("output", ["not JSON", "{}", '{"status":"ready","value_json":"4.5","summary":"", "questions":[]}', '{"status":"ready","value_json":"broken","summary":"Thickness", "questions":[]}'])
def test_malformed_model_output_is_an_error_without_fallback(store, provider, output):
    provider[0].output_text = output
    with pytest.raises(ParserUnavailable, match="invalid response"):
        parse(ReviewParser(), store)
    assert not store.saved


def test_semantically_invalid_parsed_value_needs_clarification(store, provider):
    provider[0].output_text = json.dumps({"status": "ready", "value_json": "-4", "summary": "Thickness: -4 mm.", "questions": []})
    result = parse(ReviewParser(), store)
    assert result["status"] == "needs_clarification" and "receipt" not in result
    assert "greater than zero" in result["questions"][0]


def test_actual_provider_feature_aliases_are_normalized_without_human_format_repair(store, provider):
    target = "D-TEST/template/features_review"
    store.fields = {target: {"state": "unknown", "value": None}}
    wrong_format = [{"type": "hole", "face": "top", "centre": {"x": 0, "y": 0}, "through": True, "diameter": 4.5, "hole_type": "plain"}]
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps(wrong_format), "summary": "One plain top through hole, 4.5 mm diameter, at (0, 0) mm.", "questions": []})
    result = asyncio.run(ReviewParser().parse(store, target, "One plain through hole on the top face, diameter 4.5 mm, centred at x=0 mm and y=0 mm."))
    assert result["status"] == "ready"
    feature = result["value"][0]
    assert feature["kind"] == "hole" and feature["x"]["value"] == 0 and feature["y"]["value"] == 0
    assert feature["diameter"]["value"] == 4.5 and feature["through"] is True
    assert "type" not in feature and "centre" not in feature
    assert not store.saved


@pytest.mark.parametrize("feature", [
    {"kind": "hole", "type": "slot"},
    {"kind": "hole", "x": 2, "centre": {"x": 0, "y": 0}},
    {"kind": "hole", "centre": {"x": 0, "y": 0}, "center": {"x": 1, "y": 0}},
])
def test_conflicting_feature_aliases_need_clarification(store, provider, feature):
    target = "D-TEST/template/features_review"
    store.fields = {target: {"state": "unknown", "value": None}}
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps([feature]), "summary": "A feature.", "questions": []})
    result = asyncio.run(ReviewParser().parse(store, target, "A hole at the source position."))
    assert result["status"] == "needs_clarification" and "conflicting" in result["questions"][0]
    assert "receipt" not in result and not store.saved


def test_preview_is_bound_to_item_revision_source_and_value(store, provider):
    parser = ReviewParser()
    token = parse(parser, store)["receipt"]
    parsed, provenance = parser.resolve(store, "D-TEST/template/thickness", token)
    assert parsed == 4.5 and provenance["original_input"] == "four and a half millimetres thick"
    with pytest.raises(ValueError, match="value was changed"):
        parser.resolve(store, "D-TEST/template/thickness", token, 5)
    with pytest.raises(ValueError, match="another item"):
        parser.resolve(store, "D-OTHER/template/thickness", token)
    store.revision = "new-revision"
    with pytest.raises(ValueError, match="evidence changed"):
        parser.resolve(store, "D-TEST/template/thickness", token)
    store.revision = "revision-one"
    store.fingerprint = lambda target: "new-source"
    with pytest.raises(ValueError, match="evidence changed"):
        parser.resolve(store, "D-TEST/template/thickness", token)


def test_preview_expiration_and_consumption(store, provider):
    parser = ReviewParser()
    token = parse(parser, store)["receipt"]
    parser._previews[token]["expires"] = 0
    with pytest.raises(ValueError, match="expired"):
        parser.resolve(store, "D-TEST/template/thickness", token)
    token = parse(parser, store)["receipt"]
    parser.discard(token)
    with pytest.raises(ValueError, match="already saved"):
        parser.resolve(store, "D-TEST/template/thickness", token)


def test_endpoints_preview_then_save_source_provenance_under_actual_reviewer(store, provider, monkeypatch):
    from backend.app import main
    parser = ReviewParser()
    monkeypatch.setattr(main, "get_store", lambda: store)
    monkeypatch.setattr(main, "review_parser", parser)
    client = TestClient(main.app)
    preview = client.post("/api/review-parse", json={"item_id": "D-TEST/template/thickness", "input": "four and a half millimetres thick"})
    assert preview.status_code == 200 and not store.saved
    token = preview.json()["receipt"]
    tampered = client.post("/api/review/D-TEST/template/thickness", json={"action": "set_value", "parser_token": token, "value": 99})
    assert tampered.status_code == 400 and not store.saved
    saved = client.post("/api/review/D-TEST/template/thickness", json={"action": "set_value", "parser_token": token, "note": "Inspected source."})
    assert saved.status_code == 200
    event = store.saved[0]
    assert event["by"] == "Actual fixture reviewer" and event["value"] == 4.5
    assert event["input_parser"] == {"original_input": "four and a half millimetres thick", "model": "gpt-6-luna", "response_id": "response-fixture", "request_id": "request-fixture", "purpose": "format_only"}
    repeated = client.post("/api/review/D-TEST/template/thickness", json={"action": "set_value", "parser_token": token})
    assert repeated.status_code == 400 and len(store.saved) == 1


def test_endpoint_provider_failure_has_clear_error_and_no_save(store, provider, monkeypatch):
    from backend.app import main
    monkeypatch.setattr(main, "get_store", lambda: store)
    monkeypatch.setattr(main, "review_parser", ReviewParser())
    monkeypatch.setattr(parser_module, "api_key", lambda: None)
    response = TestClient(main.app).post("/api/review-parse", json={"item_id": "D-TEST/template/thickness", "input": "4.5 mm"})
    assert response.status_code == 502 and "API key" in response.json()["detail"]
    assert not store.saved
