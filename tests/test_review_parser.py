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
    value.rebuild_models = lambda *args, **kwargs: None
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


def test_anthropic_review_input_uses_selected_model_and_preserves_preview_controls(store, provider, monkeypatch):
    monkeypatch.setattr(parser_module, "provider_name", lambda: "anthropic")
    monkeypatch.setattr(parser_module, "AnthropicClient", parser_module.AsyncOpenAI)
    parser = ReviewParser()
    result = parse(parser, store)
    assert result["status"] == "ready" and result["value"] == 4.5
    assert result["model"] == "claude-sonnet-5-5"
    assert provider[1][0]["model"] == "claude-sonnet-5-5" and len(provider[1]) == 1
    value, provenance = parser.resolve(store, "D-TEST/template/thickness", result["receipt"], None)
    assert value == 4.5 and provenance["model"] == "claude-sonnet-5-5"
    assert provenance["purpose"] == "format_only" and store.saved == []


def test_single_strict_luna_request_and_preview_never_saves(store, provider):
    response, calls, constructors = provider
    before = copy.deepcopy(store.fields)
    result = parse(ReviewParser(), store)
    assert result["status"] == "ready" and result["value"] == 4.5 and result["receipt"]
    assert result["model"] == "gpt-6-luna"
    assert store.fields == before and store.saved == []
    assert len(calls) == 1 and calls[0]["model"] == "gpt-6-luna"
    assert calls[0]["store"] is False and calls[0]["text"]["format"]["strict"] is True
    assert constructors[0]["max_retries"] == 0 and constructors[0]["timeout"] == 45
    assert "four and a half" in calls[0]["input"][0]["content"]


def test_two_explicit_reviewed_alternatives_are_one_unsaved_format_preview(store, provider):
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps({"state": "options", "options": [3, 6]}),
                                        "summary": "3 mm or 6 mm remain unresolved alternatives; neither is selected.", "questions": []})
    parser = ReviewParser()
    statement = "3 mm or 6 mm; keep both possible, I cannot select one."
    result = parse(parser, store, statement)
    assert result["status"] == "ready" and result["value"] == {"state": "options", "options": [3, 6]}
    assert not store.saved and len(provider[1]) == 1
    context = json.loads(provider[1][0]["input"][0]["content"])["context"]
    assert "exactly two" in context["expected"] and "neither selected" in context["expected"]
    value, provenance = parser.resolve(store, "D-TEST/template/thickness", result["receipt"])
    assert value == result["value"] and provenance["original_input"] == statement
    assert provenance["purpose"] == "format_only"


def test_alternative_units_are_converted_individually_in_the_reviewable_preview(store, provider):
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps({"state": "options", "options": [3, 6]}),
                                        "summary": "0.3 cm converted to 3 mm; the other reading is 6 mm. Neither is selected.", "questions": []})
    parser = ReviewParser()
    statement = "Either 0.3 cm or 6 mm; preserve both readings."
    result = parse(parser, store, statement)
    assert result["value"] == {"state": "options", "options": [3, 6]} and "converted" in result["summary"]
    assert "convert each stated unit to mm" in provider[1][0]["instructions"].lower()
    _, provenance = parser.resolve(store, "D-TEST/template/thickness", result["receipt"])
    assert provenance["original_input"] == statement and not store.saved


@pytest.mark.parametrize("statement", ["9.8–10.2 mm", "9.8 - 10.2 mm", "9.8 to 10.2 mm", "10 ±0.2 mm", "10 +/- 0.2 mm", "Lower limit 9.8 mm and upper limit 10.2 mm"])
def test_parser_does_not_turn_ranges_or_tolerances_into_two_options(store, provider, statement):
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps({"state": "options", "options": [9.8, 10.2]}),
                                        "summary": "Interpreted endpoints.", "questions": []})
    result = parse(ReviewParser(), store, statement)
    assert result["status"] == "needs_clarification" and "receipt" not in result
    assert "range or tolerance" in result["questions"][0] and not store.saved


@pytest.mark.parametrize("choices", [[3], [3, 6, 9], [3, 3]])
def test_new_formatter_requires_exactly_two_distinct_alternatives(store, provider, choices):
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps({"state": "options", "options": choices}),
                                        "summary": "Possible thickness readings.", "questions": []})
    result = parse(ReviewParser(), store, "Keep these possible readings unresolved.")
    assert result["status"] == "needs_clarification" and "receipt" not in result and not store.saved


def test_parser_cannot_silently_choose_a_range_midpoint(store, provider):
    provider[0].output_text = json.dumps({"status": "ready", "value_json": "10", "summary": "Thickness 10 mm.", "questions": []})
    result = parse(ReviewParser(), store, "Thickness range 9.8–10.2 mm")
    assert result["status"] == "needs_clarification" and not store.saved and "receipt" not in result


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


def feature_store(store):
    target = "D-TEST/template/features_review"
    store.fields = {target: {"state": "unknown", "value": None}}
    store.templates = {"D-TEST": {"outline": {"state": "known", "type": "rectangle", "length": 40, "width": 20},
                                  "thickness": {"state": "known", "value": 4}}}
    return target


def test_side_hole_format_preview_preserves_explicit_xyz_and_does_not_save(store, provider):
    target = feature_store(store)
    feature = {"type": "hole", "face": "x_min", "center": {"x": -20, "y": 0, "z": 2},
               "diameter": 3, "through": False, "depth": 12, "hole_type": "plain"}
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps([feature]),
                                        "summary": "Plain side hole at (-20, 0, 2) mm, diameter 3 mm, blind depth 12 mm.", "questions": []})
    parser = ReviewParser()
    statement = "One plain hole on x_min at global x=-20, y=0, z=2 mm, diameter 3 mm, blind depth 12 mm."
    result = asyncio.run(parser.parse(store, target, statement))
    assert result["status"] == "ready" and result["value"][0]["z"]["value"] == 2
    assert result["value"][0]["depth"]["value"] == 12
    assert "center" not in result["value"][0] and not store.saved
    _, provenance = parser.resolve(store, target, result["receipt"])
    assert provenance["original_input"] == statement and provenance["purpose"] == "format_only"
    assert len(provider[1]) == 1 and provider[1][0]["model"] == "gpt-6-luna"
    assert "not plate thickness" in provider[1][0]["instructions"]


def test_corner_clip_format_preview_remains_a_reviewable_unsaved_value(store, provider):
    target = feature_store(store)
    feature = {"kind": "corner_chamfer", "corners": ["x_min_y_min"], "x_setback": 1, "y_setback": 2}
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps([feature]),
                                        "summary": "Full-thickness clip at x_min_y_min, setbacks X=1 mm and Y=2 mm.", "questions": []})
    result = asyncio.run(ReviewParser().parse(store, target, "Full-thickness straight corner clip at x_min_y_min only; x setback 1 mm, y setback 2 mm."))
    assert result["status"] == "ready" and result["value"][0]["corners"] == ["x_min_y_min"]
    assert result["value"][0]["y_setback"]["value"] == 2
    assert "receipt" in result and not store.saved
    context = json.loads(provider[1][0]["input"][0]["content"])["context"]
    assert "corner_chamfer" in context["expected"]


@pytest.mark.parametrize("feature", [
    {"kind": "hole", "face": "x_min", "x": -20, "y": 0, "diameter": 3, "through": True, "hole_type": "plain"},
    {"kind": "hole", "face": "x_min", "x": -19, "y": 0, "z": 2, "diameter": 3, "through": True, "hole_type": "plain"},
    {"kind": "corner_chamfer", "corners": ["x_min_y_min"], "x_setback": 1},
    {"kind": "hole", "face": "x_min", "x": -20, "y": 0, "z": 2, "center": {"z": 3}},
])
def test_incomplete_new_feature_formats_return_clarification_without_receipt(store, provider, feature):
    target = feature_store(store)
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps([feature]),
                                        "summary": "Interpreted feature proposal.", "questions": []})
    result = asyncio.run(ReviewParser().parse(store, target, "A reviewed source feature, with missing details."))
    assert result["status"] == "needs_clarification" and "receipt" not in result and not store.saved


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


def test_options_preview_save_and_restart_preserve_both_values_and_prior_receipts(tmp_path, provider, monkeypatch):
    from backend.app import main
    from backend.app.tools import KnowledgeTools

    monkeypatch.setattr("backend.app.store.settings", lambda: {"reviewer_name": "Automated options fixture reviewer"})
    generated = tmp_path / "generated"
    generated.mkdir()
    target = "D-TEST/template/thickness"
    template = {"thickness": {"state": "options", "value": 4, "selected": 4, "options": [4, 8],
                               "bounds": [3.9, 4.1], "lower": 3.9, "upper": 4.1, "method": "ai_verified"}}
    part = {"id": "D-TEST/part", "key": "D-TEST", "display_name": "Options fixture", "bom": [],
            "drawing": {"id": "D-TEST", "sha256": "fixture-source", "fields": {}, "page_sizes": [[100, 200]]},
            "link": {"method": "exact_match", "value": []}}
    for name, data in {"records.json": [part], "ai_results.json": {"templates": {"D-TEST": template}}}.items():
        (generated / name).write_text(json.dumps(data), encoding="utf-8")
    live = Store(tmp_path)
    prior = live.append(target, "choose_option", 4, by="Automated options fixture reviewer")
    old_receipt_path = live.decisions_dir / (prior["decision_id"] + ".json")
    old_receipt_bytes = old_receipt_path.read_bytes()
    monkeypatch.setattr(live, "rebuild_models", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "get_store", lambda: live)
    monkeypatch.setattr(main, "review_parser", ReviewParser())
    provider[0].output_text = json.dumps({"status": "ready", "value_json": json.dumps({"state": "options", "options": [3, 6]}),
                                        "summary": "3 mm or 6 mm remain alternatives; neither selected.", "questions": []})
    client = TestClient(main.app)
    item_id = "options:" + target
    statement = "Keep 3 mm or 6 mm as two unresolved alternatives."
    preview = client.post("/api/review-parse", json={"item_id": item_id, "input": statement})
    assert preview.status_code == 200 and preview.json()["status"] == "ready"
    assert len(live.events) == 1 and live.fields[target]["selected"] == 4
    saved = client.post("/api/review/" + item_id, json={"action": "set_value", "parser_token": preview.json()["receipt"]})
    assert saved.status_code == 200
    restarted = Store(tmp_path)
    field = restarted.fields[target]
    assert field["state"] == "options" and field["options"] == [3, 6]
    assert not ({"value", "selected", "bounds", "lower", "upper"} & set(field))
    assert KnowledgeTools(restarted).display(target)["display"] == {"state": "options", "values": [3, 6]}
    item = next(item for item in restarted.review_items() if item["id"] == item_id)
    assert item["type"] == "possible_reading" and item.get("selected") is None
    assert len(restarted.events) == 2 and old_receipt_path.read_bytes() == old_receipt_bytes
    new_event = next(event for event in restarted.events if event["type"] == "set_value")
    assert new_event["input_parser"]["original_input"] == statement
    assert new_event["input_parser"]["purpose"] == "format_only" and len(provider[1]) == 1


def test_endpoint_provider_failure_has_clear_error_and_no_save(store, provider, monkeypatch):
    from backend.app import main
    monkeypatch.setattr(main, "get_store", lambda: store)
    monkeypatch.setattr(main, "review_parser", ReviewParser())
    monkeypatch.setattr(parser_module, "api_key", lambda: None)
    response = TestClient(main.app).post("/api/review-parse", json={"item_id": "D-TEST/template/thickness", "input": "4.5 mm"})
    assert response.status_code == 502 and "API key" in response.json()["detail"]
    assert not store.saved
