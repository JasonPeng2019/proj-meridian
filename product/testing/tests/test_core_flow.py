"""Real extracted corpus through M03/M12/M14/M15, with only Responses scripted.

CI must extract the corpus first and set MERIDIAN_TEST_INPUTS_PATH to inputs.json.
Without that setting this test explicitly skips; no fixture replaces the corpus.
This checks integration and persistence, not live Luna or extraction accuracy.
"""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.settings import Settings, load_settings  # noqa: E402


@pytest.fixture
def real_inputs():
    configured = os.environ.get("MERIDIAN_TEST_INPUTS_PATH")
    if not configured:
        pytest.skip("Real core flow requires CI extraction and MERIDIAN_TEST_INPUTS_PATH=.../inputs.json")
    path = Path(configured).resolve()
    assert path.is_file(), f"Configured extracted corpus is missing: {path}"
    return path


@pytest.fixture
def isolated_settings(monkeypatch):
    for name in ("MERIDIAN_CHAT_HISTORY_DIR", "MERIDIAN_SECRETS_DIR", "MERIDIAN_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    parent = ROOT / "testing/tmp/core-flow"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        data = deepcopy(load_settings().data)
        data["paths"]["chat_history"] = "chat_history"
        data["chat"]["credentials"]["secrets_dir"] = "unused-test-secrets"
        yield Settings(root=Path(directory), data=data)


class ScriptedAsyncResponses:
    """Call real tools through the chat loop; phrase their actual JSON value."""

    def __init__(self, part_id, fact_name):
        self.responses = self
        self.part_id, self.fact_name = part_id, fact_name
        self.requests = []
        self.loop = None
        self.observed_fact = None

    async def close(self):
        pass

    async def create(self, **request):
        loop = asyncio.get_running_loop()
        if self.loop is None:
            self.loop = loop
        assert loop is self.loop, "The API moved its Responses client to another loop"
        assert request["model"] == "gpt-6-luna" and request["store"] is False
        assert not ({"previous_response_id", "conversation"} & request.keys())
        self.requests.append(deepcopy(request))
        step = len(self.requests)
        if step == 1:
            name, arguments, call_id = "find_part", {"text": self.part_id}, "real_flow_find"
        elif step == 2:
            tool_output = request["input"][-1]
            assert tool_output["type"] == "function_call_output" and tool_output["call_id"] == "real_flow_find"
            found = c.FindPartResult.model_validate_json(tool_output["output"])
            assert self.part_id in {part.id for part in found.parts}
            name, arguments, call_id = "get_facts", {"part_id": self.part_id}, "real_flow_facts"
        elif step == 3:
            tool_output = request["input"][-1]
            assert tool_output["type"] == "function_call_output" and tool_output["call_id"] == "real_flow_facts"
            returned = c.GetFactsResult.model_validate_json(tool_output["output"])
            assert returned.part_id == self.part_id
            self.observed_fact = returned.facts[self.fact_name]
            assert self.observed_fact.display.state == "value" and self.observed_fact.sources
            # The answer comes from this actual tool return, never a seeded
            # expected engineering answer or an approved synthetic mapping.
            value = json.dumps(self.observed_fact.display.value, ensure_ascii=False)
            text = f"Recorded source value: {value} [cite: {self.fact_name}]."
            return self._response([dict(type="message", id="real_flow_answer", role="assistant", status="completed",
                                        content=[dict(type="output_text", text=text, annotations=[])])])
        else:
            raise AssertionError("Unexpected extra provider call in the bounded real-part flow")
        return self._response([dict(type="function_call", id="fc_" + call_id, call_id=call_id, status="completed",
                                    name=name, arguments=json.dumps(arguments))])

    @staticmethod
    def _response(output):
        return dict(id="scripted_real_flow_response", model=c.CHAT_MODEL, status="completed", error=None,
                    incomplete_details=None, output=output, usage=None)


def test_real_part_answer_drawing_and_saved_conversation_restart(real_inputs, isolated_settings):
    # These production modules arrive together in the integration checkpoint.
    # Keep their imports after the explicit missing-input skip above.
    from backend.app.main import create_app
    from backend.app.tools import FactTools
    from backend.loader.records import RecordRegistry

    manifest_path = ROOT / "development/inputs/project-meridian/dataset/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = RecordRegistry.from_inputs(real_inputs, manifest_path, decisions=None, records_path=None)
    tools = FactTools(registry)
    records = {record.id: record for record in registry.records}
    selected = None
    # Prefer clean source drawings and a usable source field, rather than the
    # whole-part label. The corpus determines both the part and expected value.
    for asset in sorted(manifest["assets"], key=lambda item: item["id"]):
        if asset.get("distribution") != "clean" or not asset["id"].startswith("D-"):
            continue
        record = records.get(c.drawing_part_name(asset["id"]))
        if record is None or record.drawing is None:
            continue
        facts = tools.get_facts(record.id).facts
        candidates = [fact for name, fact in sorted(facts.items())
                      if name != record.id and fact.part_id == record.id and fact.display.state == "value"
                      and any(source.target.kind == "drawing" for source in fact.sources)]
        if candidates:
            selected = record, candidates[0]
            break
    assert selected is not None, "Extracted real corpus has no usable drawing fact for the core product flow"
    record, expected_fact = selected
    assert not record.fixture and not record.synthetic
    provider = ScriptedAsyncResponses(record.id, expected_fact.fact)
    question = f"What is the recorded source value for {expected_fact.fact} on part {record.id}?"
    app = create_app(isolated_settings, registry=registry, inputs_root=real_inputs.parent, client=provider)

    with TestClient(app) as client:
        created = client.post("/api/conversations", json={})
        assert created.status_code == 200, created.text
        conversation_id = created.json()["conversation"]["conversation_id"]
        sent = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": question})
        assert sent.status_code == 200, sent.text
        result = c.ConversationSendResponse.model_validate(sent.json())
        reply = result.messages[1].response
        assert len(provider.requests) == 3 and provider.observed_fact == expected_fact
        assert result.messages[0].text == question and reply.conversation_id == conversation_id
        assert not reply.fixture and not reply.synthetic and not reply.warnings
        assert reply.facts == {expected_fact.fact: expected_fact}
        assert reply.markers[0].valid and reply.markers[0].names == [expected_fact.fact]
        assert reply.parts_to_show[0].id == record.id
        attachment = reply.parts_to_show[0]
        assert attachment.reason == "citation" and attachment.drawing_url == c.image_api_path(record.id)
        assert expected_fact.sources[0].target in attachment.highlights
        detail = client.get(c.part_api_path(record.id))
        assert detail.status_code == 200, detail.text
        assert detail.json()["id"] == record.id and detail.json()["drawing"]
        assert detail.json()["facts"][expected_fact.fact] == expected_fact.model_dump(mode="json")
        image = client.get(attachment.drawing_url)
        assert image.status_code == 200, image.text if image.status_code != 200 else ""
        assert image.headers["content-type"].startswith("image/png")
        assert image.content == (real_inputs.parent / record.drawing.image).read_bytes()
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert "X-Meridian-Fixture" not in image.headers
        saved = client.get(f"/api/conversations/{conversation_id}")
        assert saved.status_code == 200 and len(saved.json()["messages"]) == 2
        saved_json = saved.json()
        assert "ledger" not in saved_json

    # A new registry, app and service must reload JSON from disk. The missing
    # key cannot prevent reading the complete answer/citations/attachment.
    assert not isolated_settings.chat_key_path.exists()
    reloaded = RecordRegistry.from_inputs(real_inputs, manifest_path, decisions=None, records_path=None)
    restarted = create_app(isolated_settings, registry=reloaded, inputs_root=real_inputs.parent, client=None)
    with TestClient(restarted) as client:
        listed = client.get("/api/conversations")
        assert listed.status_code == 200, listed.text
        assert [item["conversation_id"] for item in listed.json()["conversations"]] == [conversation_id]
        reopened = client.get(f"/api/conversations/{conversation_id}")
        assert reopened.status_code == 200 and reopened.json() == saved_json
        restored = c.ConversationDetail.model_validate(reopened.json()).messages[1].response
        assert restored.facts == reply.facts and restored.markers == reply.markers
        assert restored.parts_to_show == reply.parts_to_show and len(provider.requests) == 3
