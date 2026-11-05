"""Contract examples/negative cases for ROOT Actions, not persistence/UI tests."""
from __future__ import annotations

import copy

from pydantic import ValidationError

from development.backend import contracts as c


def rejected(factory, label: str) -> None:
    try:
        factory()
    except (ValidationError, ValueError):
        return
    raise AssertionError("Invalid history contract accepted: " + label)


def check_history(fixtures: dict) -> None:
    first, other = (fixtures[f"conversation-read-{name}.json"] for name in ("a", "b"))
    state, other_state = (fixtures[f"conversation-state-{name}.json"] for name in ("a", "b"))
    context = fixtures["conversation-context-a.json"]
    sent = fixtures["conversation-send-response.json"]
    body = fixtures["conversation-send-request.json"]
    new = fixtures["conversation-new.json"]
    listing = fixtures["conversation-list.json"]
    assert [item.conversation_id for item in listing.conversations] == [
        new.conversation.conversation_id, other.conversation.conversation_id, first.conversation.conversation_id]
    assert new.messages == [] and new.conversation.title == "New chat"
    assert new.conversation.created_at == new.conversation.updated_at
    assert first.conversation.title == first.messages[0].text
    assert state.detail == first and other_state.detail == other
    assert len(first.messages) == 12 > c.CHAT_CONTEXT_TURNS
    assert first.messages[1].response.facts and first.messages[1].response.markers
    assert first.messages[1].response.parts_to_show == fixtures["chat-response.json"].parts_to_show
    assert first.messages[1].response.text == fixtures["chat-response.json"].text
    # Full saved reply (including nested source citations) survives a JSON round trip.
    assert c.ConversationState.model_validate_json(state.model_dump_json()) == state
    assert c.ConversationDetail.model_validate_json(first.model_dump_json()) == first
    turns = [c.ChatTurn(role=message.role, text=message.text if message.role == "user" else message.response.text)
             for message in first.messages]
    expected = (turns + [c.ChatTurn(role="user", text=body.message)])[-10:]
    assert context.turns == expected and len(context.turns) == 10
    assert context.turns[-1].text == body.message
    assert first.messages[1].response.text not in {turn.text for turn in context.turns}
    assert all("Synthetic B" not in turn.text and "Synthetic thread B" not in turn.text for turn in context.turns)
    # Windowing doesn't erase old tool evidence; another thread has a disjoint ledger.
    facts = set(state.ledger.entries[0].result.facts)
    other_facts = set(other_state.ledger.entries[0].result.facts)
    assert facts and other_facts and facts.isdisjoint(other_facts)
    assert facts == set(first.messages[1].response.facts)
    assert not facts.intersection(other.messages[1].response.facts)
    assert sent.conversation.conversation_id == first.conversation.conversation_id
    assert sent.conversation.title == first.conversation.title
    assert sent.conversation.updated_at > first.conversation.updated_at
    assert sent.messages[0].text == body.message
    assert {message.id for message in sent.messages}.isdisjoint(message.id for message in first.messages)
    assert len(c.ConversationDetail(conversation=sent.conversation, messages=[*first.messages, *sent.messages]).messages) == 14
    for invalid in ("../outside", "/absolute", "literal%2Fescape", "", "a" * 129):
        rejected(lambda: c.ConversationRequest(conversation_id=invalid), "unsafe/empty ID")
    rejected(lambda: c.ConversationContext(conversation_id="synthetic-thread-a", turns=turns + [turns[0]]), "oversized model context")
    rejected(lambda: c.ConversationContext(conversation_id="synthetic-thread-a", turns=[]), "empty context")
    rejected(lambda: c.ConversationContext(conversation_id="synthetic-thread-a", turns=[turns[1]]), "missing current user")
    for injected in ("history", "facts", "ledger", "messages", "conversation_id"):
        rejected(lambda: c.ConversationSendRequest.model_validate({"message": "Synthetic request", injected: {}}), "client-injected " + injected)
    rejected(lambda: c.ConversationCreateRequest(title="Client title"), "client title override")
    rejected(lambda: c.ConversationSendRequest(message=" \n\t "), "blank send")
    assert c.ConversationSendRequest(message="  Synthetic full text\n").message == "  Synthetic full text\n"
    # Legacy history remains parseable for compatibility, with no ledger channel.
    legacy = c.ChatRequest(message="Synthetic", history=[c.ChatTurn(role="assistant", text="[cite: fabricated]")])
    assert legacy.conversation_id is None
    rejected(lambda: c.ChatRequest(message="Synthetic", ledger={}), "legacy injected ledger")

    def mutate(model, value, change, label):
        data = copy.deepcopy(value.model_dump(mode="json"))
        change(data)
        rejected(lambda: model.model_validate(data), label)

    mutate(c.ConversationDetail, first, lambda data: data["messages"].append(data["messages"][0]), "duplicate message ID/order")
    mutate(c.ConversationDetail, first, lambda data: data["messages"][1]["response"].update(conversation_id="synthetic-thread-b"), "cross-thread reply")
    mutate(c.ConversationSummary, first.conversation, lambda data: data.update(updated_at="1999-01-01T00:00:00Z"), "reversed dates")
    mutate(c.ConversationSummary, first.conversation, lambda data: data.update(created_at="2000-01-01T00:00:00"), "naive timestamp")
    mutate(c.ConversationState, state, lambda data: data["ledger"].update(conversation_id="synthetic-thread-b"), "cross-thread ledger")
    mutate(c.ConversationState, state, lambda data: data["ledger"]["entries"][0].update(user_message_id="synthetic-b-u1"), "foreign call owner")
    mutate(c.ConversationState, state, lambda data: data["ledger"]["entries"].append(data["ledger"]["entries"][0]), "duplicate call")
    mutate(c.ConversationState, state, lambda data: data["ledger"]["entries"][0].update(tool_name="machine_summary"), "wrong tool result")
    mutate(c.ConversationListResponse, listing, lambda data: data["conversations"].reverse(), "oldest-first list")
    mutate(c.ConversationListResponse, listing, lambda data: data["conversations"].insert(0, data["conversations"][0]), "duplicate list ID")
    mutate(c.ConversationDetail, first, lambda data: data.update(ledger={}), "public read leaked ledger")
    # Internal state must not become any API request/response, directly or by reference.
    for endpoint in c.API_ENDPOINTS:
        for name in (endpoint.request, endpoint.response):
            if name in c.CONTRACT_MODELS:
                schema = c.CONTRACT_MODELS[name].model_json_schema()
                assert not {"ConversationState", "ConversationLedger", "ToolLedgerEntry", "ConversationContext"}.intersection(schema.get("$defs", {}))
                assert name not in {"ConversationState", "ConversationLedger", "ToolLedgerEntry", "ConversationContext"}
    print("PASS history contracts: full synthetic saved replies, isolated ledger shapes, last10 example including current user, strict request boundaries; no service/storage/provider/UI execution")
