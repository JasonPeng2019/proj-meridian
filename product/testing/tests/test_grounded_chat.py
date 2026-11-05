"""Scripted M15 sends for GitHub Actions only; every example is invented.

From testing/: ../development/.venv/bin/python -B -m pytest -q
tests/test_grounded_chat.py tests/test_chat_history.py -o cache_dir=cache/pytest
--basetemp=tmp/pytest-grounded-chat. No live provider/key or corpus assertions.
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

import pytest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.app import chat  # noqa: E402


NOTE = "Invented scripted M15 example only; no real engineering value, API run or human decision."
META = dict(fixture=True, synthetic=True, fixture_note=NOTE)


@pytest.fixture
def workspace():
    parent = ROOT / "testing/tmp/A15-grounded-chat"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        yield Path(directory)


def new(service):
    detail = service.create_conversation(c.ConversationCreateRequest(**META))
    return c.ConversationRequest(conversation_id=detail.conversation.conversation_id)


def body(message="Synthetic question"):
    return c.ConversationSendRequest(**META, message=message)


def state(workspace, selected):
    return c.ConversationState.model_validate_json(
        (workspace / f"conversation-{selected.conversation_id}.json").read_bytes())


def fixture(filename, model):
    return model.model_validate_json((ROOT / "testing/fixtures/contracts" / filename).read_bytes())


def part(number=901, *, bom=False):
    return c.PartSummary(**META, id=f"BOM:synthetic/widget-{number}/part" if bom else f"D-{number}/part",
                         display_name=f"Synthetic widget {number}", section="Synthetic section",
                         has_drawing=not bom, has_3d=not bom, examples=[] if bom else ["A", "B"],
                         thumbnail=None if bom else f"/api/parts/D-{number}%2Fpart/image?page=1&thumb=1",
                         model_state="unsupported" if bom else "available")


def fact(p=None, field="material", *, unknown=False, options=False, name=None):
    name = name or (p.id.removesuffix("/part") + ("/drawing/" if p.has_drawing else "/") + field
                    if p else "README/synthetic/p1")
    target = c.SourceTarget(kind="readme" if p is None else "drawing" if p.has_drawing else "bom",
                            name=name, part_id=p.id if p else None,
                            drawing_id=p.id.split("/")[0] if p and p.has_drawing else None,
                            page=1 if p and p.has_drawing else None,
                            box=(10, 20, 80, 16) if p and p.has_drawing else None)
    display = (c.UndeterminedDisplay(reason="source_conflict", message="Synthetic sources disagree; no trusted value.")
               if unknown else c.OptionsDisplay(values=["Synthetic alloy Z9", "Synthetic resin R8"],
                                               message="Synthetic alternatives; no option selected.")
               if options else c.ValueDisplay(value="Synthetic alloy Z9"))
    return c.FactResult(**META, fact=name, part_id=p.id if p else None, display=display,
                        rule="Synthetic resolver result; never Luna adjudication", badge="From synthetic fixture",
                        sources=[c.FactSource(name=name, says=None if unknown else "Synthetic raw source",
                                              method="parsed", target=target)], review=None)


def found(parts, facts=(), *, unique=True):
    return c.FindPartResult(**META, parts=parts, facts={f.fact: f for f in facts},
                            unique_part_id=parts[0].id if unique and len(parts) == 1 else None)


def call(name, arguments=None, call_id="synthetic_call"):
    return dict(type="function_call", name=name, arguments=json.dumps(arguments or {}, ensure_ascii=False),
                call_id=call_id, id="fc_" + call_id, status="completed")


def message(text):
    return dict(type="message", role="assistant", id="synthetic_message", status="completed",
                content=[dict(type="output_text", text=text, annotations=[])])


def response(*outputs, text=None, usage=(11, 3, 14), model=c.CHAT_MODEL, **updates):
    result = dict(id="synthetic_response", model=model, status="completed", error=None, incomplete_details=None,
                  output=[*outputs, *([message(text)] if text is not None else [])],
                  usage=dict(zip(("input_tokens", "output_tokens", "total_tokens"), usage)) if usage else None)
    result.update(updates)
    return result


class LoopClient:
    """An async-only, loop-bound Responses stand-in. It cannot call a network."""

    def __init__(self, *script, handler=None):
        self.loop = asyncio.get_running_loop()
        self.loop_thread = threading.get_ident()
        self.responses = self
        self.script, self.handler, self.requests = list(script), handler, []
        self.signal = self.loop.create_future()
        self.loop.call_soon(self.signal.set_result, True)

    async def create(self, **request):
        assert asyncio.get_running_loop() is self.loop, "Injected client changed event loops"
        assert threading.get_ident() == self.loop_thread
        self.requests.append(deepcopy(request))
        await asyncio.shield(self.signal)
        if self.handler:
            return await self.handler(request)
        assert self.script, "Unexpected provider call"
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

def client(*script, handler=None):
    return LoopClient(*script, handler=handler)


class Tools:
    def __init__(self, **returns):
        self.returns = {name: list(values) for name, values in returns.items()}
        self.calls = []
        self.forbidden_thread = None

    def __getattr__(self, name):
        assert name in {"find_part", "get_facts", "get_connections", "parts_in_section", "parts_with_material",
                        "machine_summary", "cost_summary", "propose_correction"}, "Unfrozen tool access"

        def execute(**arguments):
            assert threading.get_ident() != self.forbidden_thread, "Blocking tool ran on the async loop"
            self.calls.append((name, deepcopy(arguments)))
            assert self.returns.get(name), "Unexpected tool call"
            returned = self.returns[name].pop(0)
            if isinstance(returned, Exception):
                raise returned
            return returned

        return execute


def service(workspace, tools, provider):
    return chat.create_chat_service(history_dir=workspace, tools=tools, client=provider)


def test_responses_luna_only_exact_tools_replay_usage_and_full_saved_reply(workspace):
    p = part()
    f = fact(p)

    async def scenario():
        reasoning = dict(type="reasoning", id="rs_synthetic", summary=[], encrypted_content="synthetic-encrypted")
        provider = client(response(reasoning, call("find_part", {"text": "Synthetic widget"}, "find")),
                          response(call("get_facts", {"part_id": p.id}, "facts"), usage=(7, 2, 9)),
                          response(text=f"🧪 Synthetic alloy Z9 [cite: {f.fact}].", usage=(9, 5, 14)))
        tools = Tools(find_part=[found([p], [fact(p, name=p.id)])],
                      get_facts=[c.GetFactsResult(**META, part_id=p.id, facts={f.fact: f})])
        tools.forbidden_thread = threading.get_ident()
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        with patch.object(chat.os, "replace", wraps=chat.os.replace) as replace:
            result = await svc.send(selected, body("Synthetic widget material?"))
        assert replace.call_count == 4  # user, two actual tool returns, assistant
        assert not provider.script and len(provider.requests) == 3
        assert tools.calls == [("find_part", {"text": "Synthetic widget"}), ("get_facts", {"part_id": p.id})]
        for request in provider.requests:
            assert request["model"] == "gpt-6-luna" and request["store"] is False
            assert request["parallel_tool_calls"] is False and request["truncation"] == "disabled"
            assert not ({"previous_response_id", "conversation", "reasoning", "service_tier"} & request.keys())
            definitions = {tool["name"]: tool for tool in request["tools"]}
            expected = {"find_part": {"text"}, "get_facts": {"part_id"}, "get_connections": {"part_id"},
                        "parts_in_section": {"section"}, "parts_with_material": {"material"},
                        "machine_summary": set(), "cost_summary": set(),
                        "propose_correction": {"fact_id", "new_value", "reason"}}
            assert definitions.keys() == expected.keys()
            for name, keys in expected.items():
                assert set(definitions[name]["parameters"]["properties"]) == keys
                assert set(definitions[name]["parameters"]["required"]) == keys
                assert definitions[name]["parameters"]["additionalProperties"] is False
                assert definitions[name]["strict"] is (name != "propose_correction")
            assert "never decide" in request["instructions"] and "pending" in request["instructions"]
        assert provider.requests[0]["input"] == [{"role": "user", "content": "Synthetic widget material?"}]
        assert provider.requests[1]["input"][1] == reasoning
        output = provider.requests[1]["input"][-1]
        assert output["type"] == "function_call_output" and output["call_id"] == "find"
        assert json.loads(output["output"])["parts"][0]["id"] == p.id
        reply = result.messages[1].response
        assert reply.text.startswith("🧪") and reply.facts == {f.fact: f} and not reply.warnings
        assert reply.observation.model == c.CHAT_MODEL and reply.observation.provider == "openai"
        assert (reply.observation.input_tokens, reply.observation.output_tokens, reply.observation.total_tokens) == (27, 10, 37)
        assert reply.observation.latency_ms >= 0 and reply.observation.cost_usd is None
        attachment = reply.parts_to_show[0]
        assert attachment.id == p.id and attachment.reason == "citation" and reply.attachment_layout == "cards"
        assert attachment.highlights == [f.sources[0].target] and attachment.thumbnail == p.thumbnail
        assert attachment.drawing_url == c.image_api_path(p.id)
        assert attachment.model_urls == {"A": "/api/models/D-901_A.glb", "B": "/api/models/D-901_B.glb"}
        no_key = service(workspace, None, None)
        detail = await asyncio.to_thread(no_key.read_conversation, selected)
        assert detail.messages == list(result.messages) and detail.messages[1].response == reply
        saved = await asyncio.to_thread(state, workspace, selected)
        assert len(saved.ledger.entries) == 2 and all(entry.user_message_id == result.messages[0].id for entry in saved.ledger.entries)
        assert saved.ledger.entries[-1].result.facts == {f.fact: f}
        public = detail.model_dump_json()
        assert "ledger" not in json.loads(public) and str(workspace) not in public
        assert result.fixture and result.synthetic

    asyncio.run(scenario())


def test_json_tool_returns_and_multiple_final_messages_keep_source_links(workspace):
    p, f = part(), fact(part())

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic widget"})),
                          response(message(f"Synthetic material [cite: {f.fact}]."), message("Thank you!")))
        tools = Tools(find_part=[found([p], [f]).model_dump(mode="json")])
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert reply.text == f"Synthetic material [cite: {f.fact}].\n\nThank you!"
        assert reply.facts == {f.fact: f} and reply.markers[0].valid
        assert reply.parts_to_show[0].drawing_url == c.image_api_path(p.id)
        saved = await asyncio.to_thread(state, workspace, selected)
        assert saved.ledger.entries[0].result == found([p], [f])
        assert (await asyncio.to_thread(svc.read_conversation, selected)).messages[-1].response == reply

    asyncio.run(scenario())


def test_raw_unicode_markers_unseen_ids_authentic_unknowns_and_debug_warnings(workspace):
    p = part()
    known = fact(p, name="D-901/drawing/μ Ø @1 -> synthetic")
    unknown = fact(p, "weight_g", unknown=True)
    options = fact(p, "options", options=True)
    raw = (f"🧪 Synthetic material [cite: {known.fact}, invented-unseen]. "
           f"Synthetic weight is [undetermined: {unknown.fact}]. "
           f"Wrong marker [undetermined: {known.fact}]. Wrong options [undetermined: {options.fact}]. "
           f"Wrong encoded [cite: {c.encode_id(known.fact)}]. "
           f"Synthetic weight is 42 g [cite: {unknown.fact}]. "
           "Broken [cite: ] and [undetermined: one, two] and [CITE: invented] and [cite missing bracket")

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic"}, "find")), response(text=raw))
        tools = Tools(find_part=[found([p], [known, unknown, options])])
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert reply.text == raw
        assert set(reply.facts) == {known.fact, unknown.fact}
        assert reply.facts[unknown.fact].display.state == "undetermined"
        assert reply.facts[known.fact].review is None and reply.facts[unknown.fact].correction is None
        codes = [warning.code for warning in reply.warnings]
        assert c.WarningCode.INVALID_CITATION in codes and c.WarningCode.INVALID_UNDETERMINED in codes
        assert c.WarningCode.UNSUPPORTED_VALUE in codes and codes.count(c.WarningCode.MALFORMED_MARKER) == 4
        assert c.WarningCode.UNCITED_ANSWER not in codes
        assert len(reply.markers) == 6
        for marker in reply.markers:
            assert raw[marker.start:marker.end] == marker.raw
        assert reply.markers[0].start == raw.index("[cite:") and reply.markers[0].start == len("🧪 Synthetic material ")
        assert reply.markers[0].names == [known.fact, "invented-unseen"] and not reply.markers[0].valid
        assert reply.markers[1].valid and not reply.markers[2].valid and not reply.markers[3].valid
        assert [item.id for item in reply.parts_to_show] == [p.id]
        assert reply.parts_to_show[0].highlights == [known.sources[0].target, unknown.sources[0].target]
        assert (await asyncio.to_thread(svc.read_conversation, selected)).messages[-1].response == reply

    asyncio.run(scenario())


@pytest.mark.parametrize("count", [1, 3, 4, 5])
def test_attachments_follow_valid_citation_order_once_and_skip_unused_candidates(workspace, count):
    parts = [part(901 + index, bom=index == 1) for index in range(count + 1)]
    facts = [fact(p) for p in parts]
    cited = list(reversed(facts[:count]))
    text = "Synthetic fixtures [cite: " + ", ".join(f.fact for f in cited + cited[:1]) + "]."

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic widgets"})), response(text=text))
        svc = service(workspace, Tools(find_part=[found(parts, facts, unique=False)]), provider)
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert [item.id for item in reply.parts_to_show] == [f.part_id for f in cited]
        assert parts[-1].id not in {item.id for item in reply.parts_to_show}
        assert reply.attachment_layout == ("cards" if count <= 3 else "list")
        for item in reply.parts_to_show:
            assert item.reason == "citation"
            if item.id.startswith("BOM:"):
                assert not item.has_drawing and not item.has_3d and item.thumbnail is None
                assert item.drawing_url is None and not item.model_urls

    asyncio.run(scenario())


@pytest.mark.parametrize("lookup", ["unique", "multiple", "no-unique", "forged-unique"])
def test_only_current_turn_unique_find_can_fallback_including_abstention(workspace, lookup):
    p = part()
    found_result = found([p, part(902)] if lookup == "multiple" else [p], [fact(p, name=p.id)],
                         unique=lookup == "unique")
    if lookup == "forged-unique":
        found_result.unique_part_id = "D-999/part"
    passage = fact()

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic widget"}, "find")),
                          response(call("machine_summary", call_id="summary")),
                          response(text=f"I cannot establish a value [cite: {passage.fact}]."),
                          response(text="I cannot determine the value from available evidence."))
        summary = fixture("machine-summary.json", c.MachineSummaryResult)
        summary.facts[passage.fact] = passage
        svc = service(workspace, Tools(find_part=[found_result], machine_summary=[summary]), provider)
        selected = await asyncio.to_thread(new, svc)
        first = (await svc.send(selected, body())).messages[1].response
        assert first.facts == {passage.fact: passage}
        assert [item.id for item in first.parts_to_show] == ([p.id] if lookup == "unique" else [])
        if first.parts_to_show:
            assert first.parts_to_show[0].reason == "single_match" and first.parts_to_show[0].has_3d
            assert first.parts_to_show[0].explanation == "Shown because your question named this part."
        second = (await svc.send(selected, body("Synthetic follow-up"))).messages[1].response
        assert second.parts_to_show == [] and second.attachment_layout == "none"

    asyncio.run(scenario())


def test_restored_full_ledger_last10_including_current_and_two_thread_isolation(workspace):
    pa, pb = part(), part(902)
    fa, fb = fact(pa), fact(pb)

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic A"}, "a_find")),
                          response(text=f"Synthetic A source [cite: {fa.fact}]."),
                          *[response(text=f"Synthetic A reply {index} [cite: {fa.fact}].") for index in range(2, 7)],
                          response(call("find_part", {"text": "Synthetic B"}, "b_find")),
                          response(text=f"Synthetic B source [cite: {fb.fact}]."))
        tools = Tools(find_part=[found([pa], [fa]), found([pb], [fb])])
        svc = service(workspace, tools, provider)
        a, b = await asyncio.to_thread(new, svc), await asyncio.to_thread(new, svc)
        for index in range(1, 7):
            await svc.send(a, body(f"Synthetic A user {index}"))
        await svc.send(b, body("Synthetic B user"))
        old = await asyncio.to_thread(svc.read_conversation, a)
        b_path = workspace / f"conversation-{b.conversation_id}.json"
        b_bytes = await asyncio.to_thread(b_path.read_bytes)
        restored_client = client(response(text=f"Synthetic old A fact [cite: {fa.fact}]. Forged B [cite: {fb.fact}]."))
        restored = service(workspace, Tools(), restored_client)
        result = await restored.send(a, body("Synthetic A current"))
        expected = [{"role": item.role, "content": item.text if item.role == "user" else item.response.text}
                    for item in old.messages[-9:]] + [{"role": "user", "content": "Synthetic A current"}]
        assert restored_client.requests[0]["input"] == expected and len(expected) == 10
        assert sum(item["content"] == "Synthetic A current" for item in expected) == 1
        assert all("Synthetic B" not in item["content"] for item in expected)
        reply = result.messages[1].response
        assert reply.facts == {fa.fact: fa} and [item.id for item in reply.parts_to_show] == [pa.id]
        assert any(w.code == c.WarningCode.INVALID_CITATION and w.names == [fb.fact] for w in reply.warnings)
        no_key = service(workspace, None, None)
        after = await asyncio.to_thread(no_key.read_conversation, a)
        assert len(after.messages) == 14 and after.messages[:12] == old.messages
        assert await asyncio.to_thread(b_path.read_bytes) == b_bytes
        saved_a, saved_b = await asyncio.to_thread(state, workspace, a), await asyncio.to_thread(state, workspace, b)
        assert len(saved_a.ledger.entries) == len(saved_b.ledger.entries) == 1
        assert saved_a.ledger.entries[0].result.facts == {fa.fact: fa}
        assert saved_b.ledger.entries[0].result.facts == {fb.fact: fb}
        assert len((await asyncio.to_thread(no_key.list_conversations, c.ConversationListRequest())).conversations) == 2
        with pytest.raises(chat.ChatServiceError) as caught:
            await no_key.send(a, body())
        assert caught.value.response.error.code == c.ErrorCode.MISSING_KEY
        assert (await asyncio.to_thread(no_key.read_conversation, a)) == after

    asyncio.run(scenario())


def test_latest_return_for_same_fact_overrides_old_authorization_state(workspace):
    p = part()
    old, current = fact(p), fact(p, unknown=True)

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic widget"}, "find")),
                          response(text=f"Synthetic alloy Z9 [cite: {old.fact}]."),
                          response(call("get_facts", {"part_id": p.id}, "refresh")),
                          response(text=f"Synthetic current value [undetermined: {current.fact}]."))
        tools = Tools(find_part=[found([p], [old])], get_facts=[c.GetFactsResult(**META, part_id=p.id, facts={current.fact: current})])
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        first = await svc.send(selected, body())
        second = await svc.send(selected, body())
        assert first.messages[1].response.facts[old.fact].display.state == "value"
        assert second.messages[1].response.facts[current.fact].display.state == "undetermined"
        assert second.messages[1].response.markers[0].valid
        saved = await asyncio.to_thread(state, workspace, selected)
        assert saved.detail.messages[1] == first.messages[1]  # Historical reply is never rewritten.
        assert [entry.result.facts[old.fact].display.state for entry in saved.ledger.entries] == ["value", "undetermined"]

    asyncio.run(scenario())


@pytest.mark.parametrize("text,uncited", [("Which part do you mean?", False), ("Hello!", False),
                                         ("I cannot determine that from available evidence.", False),
                                         ("Synthetic machine is made of invented metal.", True),
                                         ("The material is steel and the weight is unknown.", True)])
def test_substantive_uncited_warning_is_debug_payload_only(workspace, text, uncited):
    async def scenario():
        svc = service(workspace, Tools(), client(response(text=text)))
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert reply.text == text and not reply.facts and not reply.parts_to_show
        assert any(w.code == c.WarningCode.UNCITED_ANSWER for w in reply.warnings) is uncited

    asyncio.run(scenario())


def test_direct_facts_hydrate_actual_card_without_retroactive_citation_authorization(workspace):
    p, f = part(), fact(part())
    whole = fact(p, name=p.id)

    async def scenario():
        provider = client(response(call("get_facts", {"part_id": p.id}, "facts")),
                          response(text=f"Synthetic value [cite: {f.fact}]. Premature whole-part [cite: {whole.fact}]."))
        tools = Tools(get_facts=[c.GetFactsResult(**META, part_id=p.id, facts={f.fact: f})],
                      find_part=[found([p], [whole])])
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert reply.facts == {f.fact: f}
        assert reply.markers[0].valid and not reply.markers[1].valid
        assert [p.id] == [item.id for item in reply.parts_to_show]
        assert tools.calls[-1] == ("find_part", {"text": p.id})
        saved = await asyncio.to_thread(state, workspace, selected)
        assert [entry.tool_name for entry in saved.ledger.entries] == ["get_facts", "find_part"]
        assert saved.ledger.entries[-1].call_id.startswith("server_")
        assert whole.fact in saved.ledger.entries[-1].result.facts

    asyncio.run(scenario())


def test_exact_summary_group_connection_and_pending_correction_tools(workspace):
    p = part()
    f = fact(p)
    machine = fixture("machine-summary.json", c.MachineSummaryResult)
    cost = fixture("cost-summary.json", c.CostSummaryResult)
    proposal = fixture("proposal-result.json", c.ProposeCorrectionResult)
    group = c.PartGroupResult(**META, parts=[p], facts={f.fact: f}, message="Synthetic group only.")
    connections = c.GetConnectionsResult(**META, part_id=p.id, connections=[], facts={}, message="No synthetic connections.")
    correction_arguments = dict(fact_id=proposal.decision.applies_to, new_value=proposal.decision.value,
                                reason="Invented test proposal; never a human approval")

    async def scenario():
        calls = [call("machine_summary", call_id="machine"), call("cost_summary", call_id="cost"),
                 call("parts_in_section", {"section": "Synthetic"}, "section"),
                 call("parts_with_material", {"material": "Synthetic"}, "material"),
                 call("get_connections", {"part_id": p.id}, "connections"),
                 call("propose_correction", correction_arguments, "proposal")]
        provider = client(response(*calls), response(text=f"Synthetic summaries [cite: {cost.fact}, {next(iter(machine.facts))}]."))
        tools = Tools(machine_summary=[machine], cost_summary=[cost], parts_in_section=[group],
                      parts_with_material=[group], get_connections=[connections], propose_correction=[proposal])
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert [name for name, _ in tools.calls] == [item["name"] for item in calls]
        assert tools.calls[:2] == [("machine_summary", {}), ("cost_summary", {})]
        assert tools.calls[-1] == ("propose_correction", correction_arguments)
        assert cost.fact in reply.facts and reply.facts[cost.fact] == cost.facts[cost.fact]
        saved = await asyncio.to_thread(state, workspace, selected)
        returned_proposal = saved.ledger.entries[-1].result
        assert returned_proposal.item.status == returned_proposal.decision.status == "pending"
        assert returned_proposal == proposal and proposal.decision.by == "Synthetic proposer (fixture only)"
        outputs = [item for item in provider.requests[-1]["input"] if item.get("type") == "function_call_output"]
        assert len(outputs) == 6 and json.loads(outputs[-1]["output"])["decision"]["status"] == "pending"
        assert json.loads(outputs[1]["output"])["recorded_total"] == cost.recorded_total

    asyncio.run(scenario())


@pytest.mark.parametrize("problem", ["transport", "failed", "incomplete", "wrong-model", "empty", "bad-output"])
def test_provider_failure_is_plain_and_durable_user_tool_work_can_reload_and_continue(workspace, problem):
    p, f = part(), fact(part())
    failures = {
        "transport": RuntimeError("PRIVATE-SYNTHETIC-TOKEN/PATH must never be echoed"),
        "failed": response(error={"message": "PRIVATE-SYNTHETIC-TOKEN/PATH"}, status="failed"),
        "incomplete": response(status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
        "wrong-model": response(model="unapproved-synthetic-model", text="Synthetic forbidden answer"),
        "empty": response(),
        "bad-output": response(output=[{"type": "message"}]),
    }

    async def scenario():
        provider = client(response(call("find_part", {"text": "Synthetic"}, "find")), failures[problem])
        tools = Tools(find_part=[found([p], [f])])
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        with pytest.raises(chat.ChatServiceError) as caught:
            await svc.send(selected, body("Synthetic failed question"))
        error = caught.value
        assert error.status_code == 502 and error.response.error.code == c.ErrorCode.PROVIDER_ERROR
        assert error.response.error.details["provider"] == "openai"
        assert error.response.error.details["model"] == c.CHAT_MODEL
        assert error.response.error.details["latency_ms"] >= 0
        assert error.response.error.details["usage_scope"] == "returned_responses_only"
        assert "PRIVATE-SYNTHETIC" not in error.response.model_dump_json() and str(workspace) not in str(error)
        assert len(provider.requests) == 2 and all(request["model"] == c.CHAT_MODEL for request in provider.requests)
        saved = await asyncio.to_thread(state, workspace, selected)
        assert len(saved.detail.messages) == 1 and saved.detail.messages[0].role == "user"
        assert saved.detail.messages[0].text == "Synthetic failed question"
        assert len(saved.ledger.entries) == 1 and saved.ledger.entries[0].result.facts == {f.fact: f}
        no_key = service(workspace, None, None)
        assert (await asyncio.to_thread(no_key.read_conversation, selected)) == saved.detail
        retry_client = client(response(text=f"Synthetic restored fact [cite: {f.fact}].", usage=None))
        retry = service(workspace, Tools(), retry_client)
        result = await retry.send(selected, body("Synthetic retry"))
        assert result.messages[1].response.facts == {f.fact: f}
        assert result.messages[1].response.observation.input_tokens is None
        assert result.messages[1].response.observation.output_tokens is None
        assert result.messages[1].response.observation.total_tokens is None
        assert result.messages[1].response.observation.cost_usd is None
        assert retry_client.requests[0]["input"] == [dict(role="user", content="Synthetic failed question"),
                                                     dict(role="user", content="Synthetic retry")]
        reloaded = await asyncio.to_thread(retry.read_conversation, selected)
        assert len(reloaded.messages) == 3 and reloaded.messages[0] == saved.detail.messages[0]

    asyncio.run(scenario())


@pytest.mark.parametrize("name,arguments", [
    ("approve_design", "{}"), ("get_bom_row", "{}"),
    ("get_facts", '{"part_id":"D-901/part","history":[]}'),
    ("machine_summary", '{"ledger":[]}'), ("find_part", '{"text":""}'),
    ("find_part", '{"text":"Synthetic","text":"Duplicate"}'),
    ("find_part", '{"text":NaN}'), ("find_part", '[]'),
    ("propose_correction", '{"fact_id":"Synthetic","new_value":1}'),
])
def test_invalid_provider_tool_calls_never_execute_or_authorize(workspace, name, arguments):
    async def scenario():
        invalid = call(name)
        invalid["arguments"] = arguments
        provider = client(response(invalid))
        tools = Tools()
        svc = service(workspace, tools, provider)
        selected = await asyncio.to_thread(new, svc)
        with pytest.raises(chat.ChatServiceError) as caught:
            await svc.send(selected, body())
        assert caught.value.response.error.code == c.ErrorCode.PROVIDER_ERROR
        assert not tools.calls and len(provider.requests) == 1
        saved = await asyncio.to_thread(state, workspace, selected)
        assert len(saved.detail.messages) == 1 and saved.ledger.entries == []

    asyncio.run(scenario())


@pytest.mark.parametrize("problem", ["tool-exception", "wrong-result", "forged-approval"])
def test_failed_tool_returns_cannot_enter_ledger_or_fabricate_approval(workspace, problem):
    async def scenario():
        if problem == "forged-approval":
            proposal = fixture("proposal-result.json", c.ProposeCorrectionResult)
            proposal.decision.status = "accepted"
            name = "propose_correction"
            arguments = dict(fact_id="Synthetic/fact", new_value="Synthetic", reason="Synthetic only")
            returned = proposal
        else:
            name, arguments = "find_part", {"text": "Synthetic"}
            returned = RuntimeError("PRIVATE-SYNTHETIC-PATH") if problem == "tool-exception" else c.GetFactsResult(**META, part_id="Synthetic", facts={})
        tools = Tools(**{name: [returned]})
        svc = service(workspace, tools, client(response(call(name, arguments))))
        selected = await asyncio.to_thread(new, svc)
        with pytest.raises(chat.ChatServiceError) as caught:
            await svc.send(selected, body())
        assert caught.value.response.error.code == c.ErrorCode.INTERNAL_ERROR
        assert "PRIVATE-SYNTHETIC" not in caught.value.response.model_dump_json()
        saved = await asyncio.to_thread(state, workspace, selected)
        assert len(saved.detail.messages) == 1 and not saved.ledger.entries

    asyncio.run(scenario())


def test_bounded_responses_tool_count_duplicate_calls_and_provider_timeout(workspace):
    machine = fixture("machine-summary.json", c.MachineSummaryResult)

    async def scenario():
        provider = client(*[response(call("machine_summary", call_id=f"count_{i}")) for i in range(2)])
        tools = Tools(machine_summary=[machine, machine])
        svc = service(workspace, tools, provider)
        svc.MAX_RESPONSES = 2
        selected = await asyncio.to_thread(new, svc)
        with pytest.raises(chat.ChatServiceError, match="response limit"):
            await svc.send(selected, body())
        assert len(provider.requests) == len(tools.calls) == 2
        limited = service(workspace, Tools(machine_summary=[machine, machine]), client(response(
            *[call("machine_summary", call_id=f"limit_{i}") for i in range(3)])))
        limited.MAX_TOOL_CALLS = 2
        other = await asyncio.to_thread(new, limited)
        with pytest.raises(chat.ChatServiceError, match="tool-call limit"):
            await limited.send(other, body())
        assert len((await asyncio.to_thread(state, workspace, other)).ledger.entries) == 2
        duplicate = service(workspace, Tools(), client(response(call("machine_summary", call_id="count_0"))))
        with pytest.raises(chat.ChatServiceError, match="repeated a tool call ID"):
            await duplicate.send(selected, body())
        assert len((await asyncio.to_thread(state, workspace, selected)).ledger.entries) == 2

        async def hang(_):
            await asyncio.Event().wait()

        timed = service(workspace, Tools(), client(handler=hang))
        timed.PROVIDER_TIMEOUT = 0.03
        third = await asyncio.to_thread(new, timed)
        with pytest.raises(chat.ChatServiceError) as caught:
            await asyncio.wait_for(timed.send(third, body()), 2)
        assert caught.value.response.error.code == c.ErrorCode.PROVIDER_ERROR and caught.value.response.error.retryable
        assert caught.value.response.error.details["input_tokens"] is None
        assert len((await asyncio.to_thread(state, workspace, third)).detail.messages) == 1

    asyncio.run(scenario())


def test_repeated_loop_bound_sends_same_thread_serialization_other_thread_and_process_lock(workspace):
    async def scenario():
        entered, release, second_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        order = []

        async def handle(request):
            turns = [item for item in request["input"] if "role" in item]
            current = turns[-1]["content"]
            order.append(current)
            if current == "Synthetic first":
                entered.set()
                await release.wait()
            if current == "Synthetic second":
                second_entered.set()
                assert turns == [dict(role="user", content="Synthetic first"),
                                 dict(role="assistant", content="Synthetic first reply"),
                                 dict(role="user", content="Synthetic second")]
            return response(text=current + " reply")

        provider = client(handler=handle)
        svc = service(workspace, Tools(), provider)
        second_service = service(workspace, Tools(), provider)
        a, b = await asyncio.to_thread(new, svc), await asyncio.to_thread(new, svc)
        loop_thread = threading.get_ident()
        original_write = chat.ConversationStore._write

        def checked_write(store, saved):
            assert threading.get_ident() != loop_thread, "Disk write blocked event loop"
            return original_write(store, saved)

        with patch.object(chat.ConversationStore, "_write", checked_write):
            first = asyncio.create_task(svc.send(a, body("Synthetic first")))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                second = asyncio.create_task(second_service.send(a, body("Synthetic second")))
                independent = await asyncio.wait_for(svc.send(b, body("Synthetic independent")), 2)
                assert independent.messages[0].text == "Synthetic independent"
                # A separate process must see the lock while the first send is
                # suspended inside its async provider, throughout the exchange.
                script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from backend.app.chat import ConversationStore, ChatServiceError
from backend.contracts import ConversationRequest
try:
    ConversationStore(Path(sys.argv[2]), lock_timeout=0.05).read_conversation(ConversationRequest(conversation_id=sys.argv[3]))
except ChatServiceError as error:
    print(error.response.error.code)
else:
    raise AssertionError('Send released its cross-process lock during provider await')
"""
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-B", "-c", script, str(ROOT / "development"), str(workspace), a.conversation_id,
                    cwd=ROOT / "testing", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await asyncio.wait_for(process.communicate(), 3)
                assert process.returncode == 0, stderr.decode()
                assert stdout.decode().strip() == "stale_conflict"
                await asyncio.sleep(0.03)  # The loop must remain responsive while second waits on its OS lock.
                assert not second_entered.is_set() and not second.done()
            finally:
                release.set()
            await asyncio.wait_for(asyncio.gather(first, second), 3)
            await svc.send(a, body("Synthetic third"))
        assert order == ["Synthetic first", "Synthetic independent", "Synthetic second", "Synthetic third"]
        saved = await asyncio.to_thread(svc.read_conversation, a)
        assert [m.text if m.role == "user" else m.response.text for m in saved.messages] == [
            "Synthetic first", "Synthetic first reply", "Synthetic second", "Synthetic second reply", "Synthetic third", "Synthetic third reply"]
        assert len((await asyncio.to_thread(svc.read_conversation, b)).messages) == 2
        assert all(request["model"] == c.CHAT_MODEL for request in provider.requests)

    asyncio.run(scenario())


def test_cancellation_drains_lock_acquisition_before_releasing(workspace):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            if request["input"][-1]["content"] == "Synthetic held":
                entered.set()
                await release.wait()
            return response(text="Synthetic completed reply")

        svc = service(workspace, Tools(), client(handler=handle))
        other = service(workspace, Tools(), client(response(text="Synthetic retry reply")))
        selected = await asyncio.to_thread(new, svc)
        first = asyncio.create_task(svc.send(selected, body("Synthetic held")))
        await asyncio.wait_for(entered.wait(), 2)
        waiting = asyncio.create_task(other.send(selected, body("Synthetic cancelled")))
        await asyncio.sleep(0.03)
        waiting.cancel()
        release.set()
        await asyncio.wait_for(first, 2)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiting, 2)
        # A cancelled acquisition cannot leave a late-acquired orphan OS lock.
        await asyncio.wait_for(other.send(selected, body("Synthetic after cancellation")), 2)
        saved = await asyncio.to_thread(other.read_conversation, selected)
        assert len(saved.messages) == 4
        assert all(m.role != "user" or m.text != "Synthetic cancelled" for m in saved.messages)

    asyncio.run(scenario())


def test_sdk_response_objects_and_partial_usage_are_preserved_without_sdk_client(workspace):
    from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText, ResponseUsage

    async def scenario():
        sdk_response = Response.model_construct(
            id="synthetic_sdk_response", model=c.CHAT_MODEL, status="completed", error=None, incomplete_details=None,
            output=[ResponseOutputMessage(id="synthetic_output", role="assistant", type="message", status="completed",
                                          content=[ResponseOutputText(text="Hello!", type="output_text", annotations=[])])],
            usage=ResponseUsage.model_construct(input_tokens=12, output_tokens=None, total_tokens=None))
        svc = service(workspace, Tools(), client(sdk_response))
        selected = await asyncio.to_thread(new, svc)
        reply = (await svc.send(selected, body())).messages[1].response
        assert reply.text == "Hello!" and reply.observation.input_tokens == 12
        assert reply.observation.output_tokens is None and reply.observation.total_tokens is None
        assert reply.observation.cost_usd is None

    asyncio.run(scenario())
