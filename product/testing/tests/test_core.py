"""PLAN V2 persisted prep -> governed API -> scripted Responses additions.

Run remotely with test/prep extras; analytic CAD is already in test_cad_build.
These synthetic decisions never use Jason's settings/journal or claim real
reader correctness, model fidelity, paid Luna behavior, or release acceptance.
"""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from test_knowledge import (HUMAN, MATERIAL, PART, TITLE, persisted_runtime, reload_registry, workspace)
from backend import contracts as c
from backend.app.main import create_app
from backend.app.tools import FactTools
from backend.loader.decisions import DecisionStore
from backend.settings import Settings, load_settings


OLD = "SYNTHETIC Bracket"
NEW = "Synthetic M23 revised title"


def settings_at(workspace):
    data = deepcopy(load_settings().data)
    data["reviewer_name"] = HUMAN
    data["chat"]["credentials"]["secrets_dir"] = "absent-synthetic-secrets"
    return Settings(root=workspace, data=data)


class Responses:
    """Script only Responses; every tool, journal, fact and API action is real."""
    def __init__(self):
        self.responses = self
        self.requests = []
        self.expected = OLD
        self.proposing = False
        self.proposal = None
        self.failure = False

    async def create(self, **request):
        assert request["model"] == "gpt-6-luna" and request["store"] is False
        assert not ({"previous_response_id", "conversation"} & request.keys())
        self.requests.append(deepcopy(request))
        if self.failure:
            raise RuntimeError("SYNTHETIC-PRIVATE-PROVIDER-FAILURE")
        if len(self.requests) % 2:
            name = "propose_correction" if self.proposing else "get_facts"
            arguments = (dict(fact_id=TITLE, new_value=NEW, reason="Synthetic automated proposal only.")
                         if self.proposing else dict(part_id=PART))
            output = [dict(type="function_call", id="synthetic-call", call_id="lookup-" + str(len(self.requests)),
                           status="completed", name=name, arguments=json.dumps(arguments))]
        else:
            returned = request["input"][-1]
            assert returned["type"] == "function_call_output"
            if self.proposing:
                self.proposal = c.ProposeCorrectionResult.model_validate_json(returned["output"])
                assert self.proposal.item.status == self.proposal.decision.status == "pending"
                text = "Synthetic proposal queued for review."
            else:
                result = c.GetFactsResult.model_validate_json(returned["output"])
                assert result.part_id == PART and result.facts[TITLE].display.value == self.expected
                text = f"Synthetic recorded title: {self.expected} [cite: {TITLE}]."
            output = [dict(type="message", id="synthetic-answer", role="assistant", status="completed",
                           content=[dict(type="output_text", text=text, annotations=[])])]
        return dict(id="synthetic-response", model="gpt-6-luna", status="completed", error=None,
                    incomplete_details=None, output=output, usage=None)


def send(client, selected, message):
    result = client.post(f"/api/conversations/{selected}/messages", json={"message": message})
    assert result.status_code == 200, result.text
    return c.ConversationSendResponse.model_validate(result.json()).messages[1].response


@pytest.mark.parametrize("action", ["reject", "accept"])
def test_api_correction_changes_only_accepted_future_answers_and_survives_restart(workspace, monkeypatch, action):
    registry, store, prepared, _ = persisted_runtime(workspace, monkeypatch)
    settings = settings_at(workspace)
    immutable = {path: path.read_bytes() for path in (
        workspace / "prepared.json", workspace / "inputs.json", workspace / "dataset/drawings/D-001.pdf")}
    original = registry.part_for(PART).drawing.fields["title"].model_dump()
    provider = Responses()
    app = create_app(settings, registry=registry, decision_store=store, inputs_root=workspace, client=provider)
    with TestClient(app) as client:
        selected = client.post("/api/conversations", json={}).json()["conversation"]["conversation_id"]
        before = send(client, selected, "What is the synthetic recorded title?")
        assert before.facts[TITLE].display.value == OLD and before.markers[0].valid
        assert before.parts_to_show[0].id == PART and before.parts_to_show[0].reason == "citation"
        image = client.get(before.parts_to_show[0].drawing_url)
        assert image.status_code == 200 and image.content == (workspace / "images/D-001-p1.png").read_bytes()

        provider.proposing = True
        send(client, selected, "Queue the synthetic revised title.")
        proposal = provider.proposal
        assert proposal.decision.by == "Chat proposal" and store.latest_accepted(TITLE) is None
        assert proposal.decision.based_on == registry.hashes_for(TITLE)
        listed = client.get("/api/review", params={"kind": "correction"})
        assert listed.status_code == 200 and [item["id"] for item in listed.json()] == [proposal.item.id]
        provider.proposing = False
        pending = send(client, selected, "Read the title while the proposal is pending.")
        assert pending.facts[TITLE].display.value == OLD
        assert client.get(c.part_api_path(PART)).json()["facts"][TITLE]["display"]["value"] == OLD

        response = client.post(c.review_api_path(proposal.item.id), json={
            "action": action, "note": "Synthetic milestone review only; not an actual human approval."})
        assert response.status_code == 200, response.text
        reviewed = c.ReviewActionResponse.model_validate(response.json())
        expected = NEW if action == "accept" else OLD
        assert reviewed.item.status == ("accepted" if action == "accept" else "rejected")
        assert [event.status for event in reviewed.decisions] == ["pending", reviewed.item.status]
        assert reviewed.decisions[-1].type == c.DecisionType.CORRECTION
        assert reviewed.decisions[-1].by == HUMAN and reviewed.decisions[-1].synthetic
        assert reviewed.refresh.facts[TITLE].display.value == expected
        assert reviewed.refresh.part_ids == [PART]
        assert reviewed.refresh.models[PART].state == "missing" and not reviewed.refresh.models[PART].examples
        provider.expected = expected
        after = send(client, selected, "Read the title after the synthetic review.")
        assert after.facts[TITLE].display.value == expected
        assert before.facts[TITLE].display.value == OLD  # Earlier saved answers do not change retroactively.
        field = registry.part_for(PART).drawing.fields["title"]
        assert field.original is None and field.value == OLD and field.provenance.model_dump() == original["provenance"]
        assert registry.document.prepared == prepared
        if action == "accept":
            assert after.facts[TITLE].correction.corrected == NEW
            assert after.facts[TITLE].correction.original == OLD
            raw_source = next(source for source in after.facts[TITLE].sources if source.name == TITLE)
            assert raw_source.says is None
            assert raw_source.provenance.rounds[0].determination.output.fields[TITLE].value == OLD
        else:
            assert after.facts[TITLE].correction is None
        # Real API/provider error behavior must not retry with another model or
        # fabricate an assistant answer, and must redact private provider text.
        provider.failure = True
        previous_calls = len(provider.requests)
        failed = client.post(f"/api/conversations/{selected}/messages", json={"message": "Synthetic error probe"})
        assert failed.status_code == 502 and failed.json()["error"]["code"] == "provider_error"
        assert "SYNTHETIC-PRIVATE" not in failed.text and len(provider.requests) == previous_calls + 1
        saved = client.get(f"/api/conversations/{selected}").json()
        assert len(saved["messages"]) == 9 and saved["messages"][-1]["role"] == "user"
        assert all(request["model"] == "gpt-6-luna" for request in provider.requests)

    restarted_store = DecisionStore(store.directory, allow_synthetic=True)
    again = reload_registry(workspace, restarted_store)
    no_key = create_app(settings, registry=again, decision_store=restarted_store, inputs_root=workspace, client=None)
    with TestClient(no_key) as client:
        assert client.get("/api/status").json()["chat_state"] == "missing_key"
        assert client.get(f"/api/conversations/{selected}").json() == saved
        assert client.get(c.part_api_path(PART)).json()["facts"][TITLE]["display"]["value"] == expected
        blocked = client.post(f"/api/conversations/{selected}/messages", json={"message": "Synthetic no-key send"})
        assert blocked.status_code == 503 and blocked.json()["error"]["code"] == "missing_key"
        assert client.get(f"/api/conversations/{selected}").json() == saved
    assert restarted_store.history(TITLE) == store.history(TITLE)
    assert {path: path.read_bytes() for path in immutable} == immutable


def test_api_mapping_approval_is_required_for_actual_registry_resolution(workspace, monkeypatch):
    registry, store, prepared, _ = persisted_runtime(workspace, monkeypatch)
    tools = FactTools(registry)
    assert registry.approved_mappings == [] and tools.parts_with_material("Synthetic family").parts == []
    app = create_app(settings_at(workspace), registry=registry, decision_store=store, inputs_root=workspace, client=None)
    with TestClient(app) as client:
        before = client.get(c.part_api_path(PART)).json()["facts"][MATERIAL]
        assert before["display"]["state"] == "undetermined" and before["display"]["reason"] == "unmapped_names"
        response = client.get("/api/review", params={"kind": "name_mapping"})
        assert response.status_code == 200, response.text
        item = next(item for item in response.json() if item["applies_to"].startswith("names/material/"))
        accepted = client.post(c.review_api_path(item["id"]), json={"action": "approve_mapping", "note": HUMAN})
        assert accepted.status_code == 200, accepted.text
        event = accepted.json()["decisions"][-1]
        assert event["type"] == "name_mapping" and event["by"] == HUMAN
        assert event["value"] == {"relationship": "kind_of", "to_name": "Synthetic family"}
        assert client.get(c.part_api_path(PART)).json()["facts"][MATERIAL]["display"]["value"] == "Alloy X"
    assert [part.id for part in tools.parts_with_material("Synthetic family").parts] == [PART]
    assert [part.id for part in tools.parts_with_material("Alloy X").parts] == [PART]
    assert registry.document.prepared == prepared
    again = reload_registry(workspace, DecisionStore(store.directory, allow_synthetic=True))
    assert again.approved_mappings == registry.approved_mappings
    assert FactTools(again).get_facts(PART).facts[MATERIAL].display.value == "Alloy X"
