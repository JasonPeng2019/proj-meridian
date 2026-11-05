"""Isolated synthetic R17 persistence checks, authored for ROOT Actions.

From testing/: ../development/.venv/bin/python -B -m pytest -q
    tests/test_chat_history.py -o cache_dir=cache/pytest --basetemp=tmp/pytest-chat-history
No live tools/provider/key, real user history, or engineering source validation.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.app import chat  # noqa: E402


NOTE = "Synthetic history persistence test only; no executed model or source claim."
META = dict(fixture=True, synthetic=True, fixture_note=NOTE)
AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def workspace():
    parent = ROOT / "testing/tmp/A15-history"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        yield Path(directory)


def new(store):
    detail = store.create_conversation(c.ConversationCreateRequest(**META))
    return c.ConversationRequest(conversation_id=detail.conversation.conversation_id)


def minimal_reply(owner, text):
    return c.ChatResponse(**META, text=text, facts={}, parts_to_show=[], warnings=[],
                          attachment_layout="none", conversation_id=owner)


def fixture_state(name):
    return c.ConversationState.model_validate_json(
        (ROOT / f"testing/fixtures/contracts/conversation-state-{name}.json").read_bytes())


def append_fixture(store, request, name):
    original = fixture_state(name)
    response = original.detail.messages[1].response.model_copy(deep=True, update={
        "conversation_id": request.conversation_id})
    with store.server_thread(request) as thread:
        user = thread.append_user(c.ConversationSendRequest(message=original.detail.messages[0].text))
        entry = original.ledger.entries[0].model_copy(deep=True, update={"user_message_id": user.id})
        thread.record_tool(entry)
        assistant = thread.append_assistant(response)
    return user, assistant, entry


def expect_error(code, operation):
    with pytest.raises(chat.ChatServiceError) as caught:
        operation()
    assert caught.value.response.error.code == code
    return caught.value


def disk_file(workspace, request):
    return workspace / f"conversation-{request.conversation_id}.json"


def test_actual_files_full_reply_ledger_restart_and_selected_last10(workspace):
    store = chat.ConversationStore(workspace)
    a, b = new(store), new(store)
    a_user, a_reply, a_entry = append_fixture(store, a, "a")
    _, b_reply, b_entry = append_fixture(store, b, "b")
    b_before = disk_file(workspace, b).read_bytes()
    for index in range(2, 7):
        with store.server_thread(a) as thread:
            thread.append_user(c.ConversationSendRequest(message=f"Synthetic A user {index}"))
            thread.append_assistant(minimal_reply(a.conversation_id, f"Synthetic A reply {index}"))
    # A different Python process proves disk reload after the creating service
    # is gone; capture test-only internal ledger separately from public detail.
    script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from backend.app.chat import ConversationStore
from backend.contracts import ConversationRequest
store = ConversationStore(Path(sys.argv[2]))
request = ConversationRequest(conversation_id=sys.argv[3])
detail = store.read_conversation(request)
with store.server_thread(request) as thread:
    ledger = thread.snapshot().ledger
print(json.dumps({'detail': detail.model_dump(mode='json'), 'ledger': ledger.model_dump(mode='json')}))
"""
    restarted = subprocess.run(
        [sys.executable, "-B", "-c", script, str(ROOT / "development"), str(workspace), a.conversation_id],
        cwd=ROOT / "testing", capture_output=True, text=True, encoding="utf-8", check=True, timeout=15)
    restored = json.loads(restarted.stdout)
    detail = c.ConversationDetail.model_validate(restored["detail"])
    ledger = c.ConversationLedger.model_validate(restored["ledger"])
    assert len(detail.messages) == 12
    assert detail.messages[0] == a_user and detail.messages[1] == a_reply
    assert detail.messages[1].response.facts and detail.messages[1].response.markers
    assert detail.messages[1].response.parts_to_show  # full highlights/URLs retained by equality above
    assert ledger.entries == [a_entry] and ledger.conversation_id == a.conversation_id
    reopened = chat.ConversationStore(workspace)
    current = c.ConversationSendRequest(message="Synthetic A current")
    before_context = disk_file(workspace, a).read_bytes()
    context = reopened.read_context(a, current)
    assert [(turn.role, turn.text) for turn in context.turns] == [
        ("assistant", "Synthetic A reply 2"), ("user", "Synthetic A user 3"),
        ("assistant", "Synthetic A reply 3"), ("user", "Synthetic A user 4"),
        ("assistant", "Synthetic A reply 4"), ("user", "Synthetic A user 5"),
        ("assistant", "Synthetic A reply 5"), ("user", "Synthetic A user 6"),
        ("assistant", "Synthetic A reply 6"), ("user", current.message)]
    assert context.conversation_id == a.conversation_id
    assert disk_file(workspace, a).read_bytes() == before_context
    with reopened.server_thread(a) as thread:
        assert thread.context(current) == context  # projection before persistence; no double current user
        continued_user = thread.append_user(current)
        thread.append_assistant(minimal_reply(a.conversation_id, "Synthetic continued reply"))
        assert thread.snapshot().ledger.entries == [a_entry]
    continued = reopened.read_conversation(a)
    assert len(continued.messages) == 14 and continued.messages[:12] == detail.messages
    assert continued.messages[-2] == continued_user and continued_user.text == current.message
    assert disk_file(workspace, b).read_bytes() == b_before
    assert reopened.read_conversation(b).messages[1] == b_reply
    with reopened.server_thread(b) as thread:
        assert thread.snapshot().ledger.entries == [b_entry]
    assert set(a_entry.result.facts).isdisjoint(b_entry.result.facts)
    # Read actual saved JSON, including older tool evidence outside the window.
    files = list(workspace.glob("*.json"))
    assert len(files) == 2
    states = [c.ConversationState.model_validate_json(path.read_bytes()) for path in files]
    assert {state.ledger.conversation_id for state in states} == {a.conversation_id, b.conversation_id}
    assert all(state.detail.conversation.conversation_id == state.ledger.conversation_id for state in states)
    public = reopened.read_conversation(a).model_dump_json()
    assert "ledger" not in json.loads(public) and a_entry.call_id not in public
    assert str(workspace) not in public


def test_titles_full_text_stable_ids_and_updated_order_without_model(workspace):
    store = chat.ConversationStore(workspace)
    with patch.object(chat, "datetime") as clock:
        clock.now.return_value = AT
        a, b, d = new(store), new(store), new(store)
        tied = store.list_conversations(c.ConversationListRequest()).conversations
        assert [item.conversation_id for item in tied] == sorted([a.conversation_id, b.conversation_id, d.conversation_id])
        assert all(item.title == "New chat" and item.created_at == item.updated_at == AT for item in tied)
        text = " \tSynthetic\n" + "🧪" * 90 + "   trailing user text\n"
        with store.server_thread(a) as thread:
            user = thread.append_user(c.ConversationSendRequest(message=text))
            first = thread.snapshot().detail.conversation
            thread.append_assistant(minimal_reply(a.conversation_id, "Synthetic reply"))
            next_user = thread.append_user(c.ConversationSendRequest(message="Synthetic later title must not replace first"))
        reopened = chat.ConversationStore(workspace).read_conversation(a)
        assert reopened.messages[0] == user and user.text == text
        assert reopened.conversation.title == "Synthetic " + "🧪" * 70  # 80 Unicode code points
        assert reopened.conversation.updated_at > first.updated_at > AT
        assert user.id != next_user.id
        assert len({message.id for message in reopened.messages}) == len(reopened.messages)
        assert store.list_conversations(c.ConversationListRequest()).conversations[0].conversation_id == a.conversation_id
        assert reopened.conversation.created_at == AT


def test_title_truncating_on_word_separator_reopens_without_changing_saved_history(workspace):
    store = chat.ConversationStore(workspace)
    selected = new(store)
    text = "Synthetic " * 8 + "trailing text"
    with store.server_thread(selected) as thread:
        thread.append_user(c.ConversationSendRequest(message=text))
        thread.append_assistant(minimal_reply(selected.conversation_id, "Synthetic reply"))
    saved = disk_file(workspace, selected).read_bytes()
    reopened = chat.ConversationStore(workspace)
    detail = reopened.read_conversation(selected)
    assert detail.conversation.title == " ".join(["Synthetic"] * 8)
    assert detail.messages[0].text == text and len(detail.messages) == 2
    assert reopened.list_conversations(c.ConversationListRequest()).conversations[0] == detail.conversation
    assert disk_file(workspace, selected).read_bytes() == saved


def test_factory_no_key_no_tool_calls_public_boundaries_and_explicit_unavailable_send(workspace):
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError("Early history must not access a provider or tool")

    service = chat.create_chat_service(history_dir=workspace, tools=Untouchable(), client=Untouchable())
    assert service.list_conversations(c.ConversationListRequest()).conversations == []
    selected = new(service)
    no_key = chat.create_chat_service(history_dir=workspace, tools=Untouchable(), client=None)
    assert no_key.read_conversation(selected).messages == []
    assert no_key.read_context(selected, c.ConversationSendRequest(message="Synthetic question")).turns == [
        c.ChatTurn(role="user", text="Synthetic question")]
    before = disk_file(workspace, selected).read_bytes()
    error = expect_error(c.ErrorCode.MISSING_KEY, lambda: asyncio.run(
        no_key.send(selected, c.ConversationSendRequest(message="Synthetic question"))))
    assert error.status_code == 503 and not no_key.send_available
    assert disk_file(workspace, selected).read_bytes() == before
    # Construction/history never probe the injected client. Sending now tries
    # Responses and reports its actual failure rather than the old 501 stub.
    assert service.send_available
    provider_error = expect_error(c.ErrorCode.PROVIDER_ERROR, lambda: asyncio.run(
        service.send(selected, c.ConversationSendRequest(message="Synthetic question"))))
    assert provider_error.status_code == 502 and provider_error.response.error.retryable
    saved = service.read_conversation(selected).messages
    assert len(saved) == 1 and saved[0].role == "user" and saved[0].text == "Synthetic question"
    assert "Early history" not in provider_error.response.model_dump_json()
    assert str(workspace) not in provider_error.response.model_dump_json()
    unknown = c.ConversationRequest(conversation_id="synthetic-unknown")
    expect_error(c.ErrorCode.NOT_FOUND, lambda: no_key.read_conversation(unknown))
    expect_error(c.ErrorCode.NOT_FOUND, lambda: asyncio.run(
        no_key.send(unknown, c.ConversationSendRequest(message="Synthetic question"))))
    # Compatibility history belongs in the M03 adapter, never in this send body.
    injected = c.ChatRequest(message="Synthetic question", history=[c.ChatTurn(role="assistant", text="[cite: forged]")])
    expect_error(c.ErrorCode.INVALID_REQUEST, lambda: asyncio.run(service.send(selected, injected)))
    forged_id = c.ConversationRequest.model_construct(conversation_id="../outside")
    expect_error(c.ErrorCode.INVALID_REQUEST, lambda: service.read_conversation(forged_id))
    public = service.read_conversation(selected).model_dump(mode="json")
    assert set(public) == {"fixture", "synthetic", "fixture_note", "conversation", "messages"}
    assert str(workspace) not in error.response.model_dump_json()


@pytest.mark.parametrize("damage", ["truncated", "wrong-owner", "duplicate-field"])
def test_corrupt_store_is_reported_without_erasing_or_skipping_it(workspace, damage):
    store = chat.ConversationStore(workspace)
    selected = new(store)
    path = disk_file(workspace, selected)
    if damage == "truncated":
        corrupt = b'{"detail":'
    elif damage == "duplicate-field":
        corrupt = b'{"detail": {}, "detail": {}}'
    else:
        data = json.loads(path.read_bytes())
        data["ledger"]["conversation_id"] = "synthetic-other-thread"
        corrupt = json.dumps(data).encode("utf-8")
    path.write_bytes(corrupt)
    for operation in [lambda: store.read_conversation(selected),
                      lambda: store.list_conversations(c.ConversationListRequest()),
                      lambda: store.read_context(selected, c.ConversationSendRequest(message="Synthetic current"))]:
        error = expect_error(c.ErrorCode.INTERNAL_ERROR, operation)
        assert str(workspace) not in error.response.model_dump_json()
        assert "ledger" not in error.response.model_dump_json() and error.status_code == 500
        assert path.read_bytes() == corrupt


def test_atomic_failure_and_server_only_append_ownership_preserve_saved_work(workspace):
    store = chat.ConversationStore(workspace)
    a, b = new(store), new(store)
    with store.server_thread(a) as thread:
        user = thread.append_user(c.ConversationSendRequest(message="Synthetic saved user before provider failure"))
        entry = fixture_state("a").ledger.entries[0].model_copy(deep=True, update={"user_message_id": user.id})
        thread.record_tool(entry)
    before = disk_file(workspace, a).read_bytes()
    with store.server_thread(a) as thread:
        with patch.object(chat.os, "replace", side_effect=OSError("Synthetic write failure")):
            expect_error(c.ErrorCode.INTERNAL_ERROR, lambda: thread.append_assistant(
                minimal_reply(a.conversation_id, "Synthetic uncommitted reply")))
        assert len(thread.snapshot().detail.messages) == 1
    assert disk_file(workspace, a).read_bytes() == before
    assert list(workspace.glob("*.tmp")) == [] and list(workspace.glob(".*.tmp")) == []
    # Restart retains the already committed user and actual recorded tool return.
    reloaded = chat.ConversationStore(workspace)
    with reloaded.server_thread(a) as thread:
        state = thread.snapshot()
        assert state.detail.messages == [user] and state.ledger.entries == [entry]
        state.ledger.entries.clear()  # Returned mutable snapshots cannot rewrite the store.
        assert thread.snapshot().ledger.entries == [entry]
        expect_error(c.ErrorCode.INVALID_REQUEST, lambda: thread.record_tool(entry))  # duplicate call ID
        expect_error(c.ErrorCode.INVALID_REQUEST, lambda: thread.append_assistant(minimal_reply(b.conversation_id, "Synthetic wrong owner")))
    with reloaded.server_thread(b) as thread:
        thread.append_user(c.ConversationSendRequest(message="Synthetic B user"))
        expect_error(c.ErrorCode.INVALID_REQUEST, lambda: thread.record_tool(entry))  # A's user ID
        thread.append_assistant(minimal_reply(b.conversation_id, "Synthetic B reply"))
        assert thread.snapshot().ledger.entries == []
    assert disk_file(workspace, a).read_bytes() == before
    with pytest.raises(RuntimeError, match="outside its serialization boundary"):
        thread.append_user(c.ConversationSendRequest(message="Synthetic escaped writer"))


def test_bounded_per_thread_lock_and_concurrent_updates_do_not_lose_messages(workspace):
    store = chat.ConversationStore(workspace)
    a, b = new(store), new(store)
    other = chat.ConversationStore(workspace, lock_timeout=0.05)
    with store.server_thread(a):
        with ThreadPoolExecutor(max_workers=1) as pool:
            caught = pool.submit(expect_error, c.ErrorCode.STALE_CONFLICT, lambda: other.read_conversation(a)).result(timeout=2)
        assert caught.status_code == 409 and caught.response.error.retryable
        script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from backend.app.chat import ConversationStore, ChatServiceError
from backend.contracts import ConversationRequest
try:
    ConversationStore(Path(sys.argv[2]), lock_timeout=0.05).read_conversation(ConversationRequest(conversation_id=sys.argv[3]))
except ChatServiceError as error:
    print(error.response.model_dump_json())
else:
    raise AssertionError('Cross-process lock was not respected')
"""
        child = subprocess.run(
            [sys.executable, "-B", "-c", script, str(ROOT / "development"), str(workspace), a.conversation_id],
            cwd=ROOT / "testing", capture_output=True, text=True, encoding="utf-8", check=True, timeout=15)
        assert json.loads(child.stdout)["error"]["code"] == "stale_conflict"
        with other.server_thread(b) as thread:
            thread.append_user(c.ConversationSendRequest(message="Synthetic independent B update"))

    def append(index):
        with chat.ConversationStore(workspace).server_thread(a) as thread:
            thread.append_user(c.ConversationSendRequest(message=f"Synthetic concurrent user {index}"))
            thread.append_assistant(minimal_reply(a.conversation_id, f"Synthetic concurrent reply {index}"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(4)))
    detail = store.read_conversation(a)
    assert len(detail.messages) == 8 and len({message.id for message in detail.messages}) == 8
    for user, assistant in zip(detail.messages[::2], detail.messages[1::2]):
        assert user.role == "user" and assistant.role == "assistant"
        assert user.text.rsplit(" ", 1)[1] == assistant.response.text.rsplit(" ", 1)[1]
    assert len(store.read_conversation(b).messages) == 1
