"""Offline chat persistence checks: no provider, evidence mutation or CAD work."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.paths import ROOT
from backend.app.conversations import Conversations

SID = "a" * 32
OTHER = "b" * 32


def answer(text="Saved answer."):
    return {"text": text, "session_id": SID, "facts": {"part/material": {"display": {"value": "Steel"}}},
            "parts_to_show": [{"key": "part", "drawing_url": "/part/part/2d", "model_url": "/part/part/3d"}],
            "warnings": [], "tool_trace": [{"tool": "get_facts", "arguments": {"key": "part"}}],
            "model": "gpt-6-luna", "usage": {"input_tokens": 10}, "revision": "old"}


@pytest.fixture
def chats(tmp_path):
    return Conversations(tmp_path / "chats")


def test_transcript_restarts_with_response_attachments_and_dialogue_only(chats):
    first = chats.append_turn(SID, "  What is the material?  ", answer(), create=True)
    restarted = Conversations(chats.directory)
    saved = restarted.get(SID)
    assert saved == first
    assert saved["title"] == "What is the material?"
    assert saved["created_at"].endswith("Z")
    assert saved["messages"][1]["response"] == answer()
    assert restarted.dialogue(SID) == [{"role": "user", "content": "  What is the material?  "},
                                        {"role": "assistant", "content": "Saved answer."}]
    restarted.append_turn(SID, "And the drawing?", answer("Attached."))
    assert restarted.get(SID)["title"] == first["title"]
    assert restarted.get(SID)["updated_at"] >= first["updated_at"]
    restarted.append_turn(OTHER, "A different question", answer(), create=True)
    assert [item["id"] for item in restarted.list()] == [OTHER, SID]
    assert restarted.list()[1]["message_count"] == 4


def test_secrets_and_hidden_reasoning_are_never_saved(chats, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unusual-provider-key-value")
    response = answer("The key sk-test_secret_123456789 is sensitive.")
    response.update(reasoning="PRIVATE REASONING", api_key="SECRET VALUE")
    response["facts"]["secret"] = {"api_key": "SECRET VALUE", "reasoning": "PRIVATE REASONING"}
    chats.append_turn(SID, "OPENAI_API_KEY=unusual-provider-key-value Bearer bearer-secret", response, create=True)
    raw = (chats.directory / f"{SID}.json").read_text(encoding="utf-8")
    for secret in ("unusual-provider-key-value", "sk-test_secret_123456789", "bearer-secret", "SECRET VALUE", "PRIVATE REASONING"):
        assert secret not in raw
    assert "[redacted]" in raw
    assert chats.get(SID)["messages"][1]["response"]["usage"]["input_tokens"] == 10


def test_delete_is_explicit_and_targets_only_selected_chat(chats):
    chats.append_turn(SID, "First", answer(), create=True)
    chats.append_turn(OTHER, "Second", answer(), create=True)
    unrelated = chats.directory / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    chats.delete(SID)
    with pytest.raises(KeyError):
        chats.get(SID)
    with pytest.raises(KeyError):
        chats.append_turn(SID, "A deleted chat", answer())
    assert chats.get(OTHER)["title"] == "Second"
    assert unrelated.read_text(encoding="utf-8") == "keep"
    with pytest.raises(ValueError):
        chats.delete("../keep")


def test_paths_limits_and_atomic_replacement(chats, monkeypatch):
    with pytest.raises(ValueError, match="escapes"):
        Conversations(ROOT.parent / "outside-chats")
    for invalid in ("../" + SID, SID + "/x", "A" * 32, "", "x" * 32):
        with pytest.raises(ValueError):
            chats.get(invalid)
    with pytest.raises(ValueError, match="16,000"):
        chats.append_turn(SID, "x" * 16001, answer(), create=True)
    chats.append_turn(SID, "Original", answer(), create=True)
    before = chats.get(SID)
    def fail_replace(*args):
        raise OSError("Simulated write failure")
    monkeypatch.setattr("backend.app.conversations.os.replace", fail_replace)
    with pytest.raises(OSError, match="Simulated"):
        chats.append_turn(SID, "Uncommitted", answer())
    assert chats.get(SID) == before
    assert not list(chats.directory.glob("*.tmp"))


def test_rejects_symlink_to_another_chat(chats):
    chats.append_turn(OTHER, "Keep me", answer(), create=True)
    link = chats.directory / f"{SID}.json"
    try:
        link.symlink_to(chats.directory / f"{OTHER}.json")
    except OSError:
        pytest.skip("Creating symlinks requires Windows developer mode or privilege")
    with pytest.raises(ValueError):
        chats.delete(SID)
    assert chats.get(OTHER)["title"] == "Keep me"


def test_retains_complete_recent_turns_and_serializes_writers(chats, monkeypatch):
    monkeypatch.setattr("backend.app.conversations.MAX_MESSAGES", 8)
    chats.append_turn(SID, "Original title", answer(), create=True)
    def append(number):
        Conversations(chats.directory).append_turn(SID, f"Question {number}", answer())
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(3)))
    assert len(chats.get(SID)["messages"]) == 8
    chats.append_turn(SID, "Latest", answer())
    saved = chats.get(SID)
    assert saved["title"] == "Original title"
    assert len(saved["messages"]) == 8
    assert saved["messages"][0]["role"] == "user"
    monkeypatch.setattr("backend.app.conversations.MAX_BYTES", 100)
    with pytest.raises(ValueError, match="size limit"):
        chats.append_turn(OTHER, "Too big", answer(), create=True)
    assert not (chats.directory / f"{OTHER}.json").exists()


@pytest.mark.parametrize("selected_provider", ["openai", "anthropic"])
def test_reopened_chat_refetches_tools_without_replaying_saved_evidence(chats, monkeypatch, selected_provider):
    import backend.app.chat as chat_module
    chats.append_turn(SID, "Previous question", answer(), create=True)
    requests, tools_called = [], []
    class FakeTools:
        def __init__(self, store):
            self.store = store
        def find_part(self, query):
            tools_called.append((query, self.store.revision))
            return {"parts": [], "revision": self.store.revision}
    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            requests.append(copy.deepcopy(kwargs))
            if len(requests) == 1:
                return SimpleNamespace(usage=None, output=[SimpleNamespace(type="function_call", name="find_part", arguments='{"query":"part"}', call_id="call-1")])
            return SimpleNamespace(usage=None, output=[], output_text="Current answer.")
    monkeypatch.setattr(chat_module, "api_key", lambda: "offline-test-key")
    monkeypatch.setattr(chat_module, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(chat_module, "AnthropicClient", FakeClient)
    monkeypatch.setattr(chat_module, "provider_name", lambda: selected_provider)
    monkeypatch.setattr(chat_module, "KnowledgeTools", FakeTools)
    monkeypatch.setattr(chat_module, "api_tools", lambda: [{"name": "find_part"}])
    store = SimpleNamespace(fields={}, revision="fresh-revision")
    result = asyncio.run(chat_module.Chat(Conversations(chats.directory)).answer(store, "Follow-up", SID))
    assert result["session_id"] == SID
    assert tools_called == [("part", "fresh-revision")]
    assert requests[0]["input"] == [{"role": "user", "content": "Previous question"},
                                    {"role": "assistant", "content": "Saved answer."},
                                    {"role": "user", "content": "Follow-up"}]
    assert requests[0]["model"] == ("gpt-6-luna" if selected_provider == "openai" else "claude-sonnet-5-5")
    assert "Steel" not in str(requests[0]["input"])
    assert len(chats.get(SID)["messages"]) == 4
    fresh = asyncio.run(chat_module.Chat(chats).answer(store, "Start another chat"))
    assert fresh["session_id"] != SID
    assert chats.get(fresh["session_id"])["title"] == "Start another chat"
    before = len(requests)
    with pytest.raises(KeyError, match="Chat not found"):
        asyncio.run(chat_module.Chat(chats).answer(store, "Unknown chat", "c" * 32))
    assert len(requests) == before


def test_history_routes_do_not_require_provider_or_evidence(chats, monkeypatch):
    import backend.app.main as main
    chats.append_turn(SID, "Saved question", answer(), create=True)
    monkeypatch.setattr(main, "chat", SimpleNamespace(conversations=chats))
    monkeypatch.setenv("MERIDIAN_NO_KEY", "1")
    client = TestClient(main.app)
    assert client.get("/api/chats").json()[0]["id"] == SID
    assert client.get(f"/api/chats/{SID}").json()["messages"][1]["response"]["parts_to_show"]
    assert client.delete(f"/api/chats/{SID}").json() == {"deleted": SID}
    assert client.get(f"/api/chats/{SID}").status_code == 404
    assert client.get("/api/chats/invalid").status_code == 400
    assert client.get("/api/chats").json() == []


@pytest.mark.parametrize("provider_text", [
    "Here is Luna's complete answer with more than eight words and no citations.",
    "The thickness has two possible readings, 3 mm and 6 mm. [cite: unavailable/source]",
])
def test_luna_answer_is_returned_unchanged_without_output_validation_or_retries(chats, monkeypatch, provider_text):
    import backend.app.chat as chat_module
    requests = []
    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            requests.append(copy.deepcopy(kwargs))
            return SimpleNamespace(usage=None, output=[], output_text=provider_text)
    monkeypatch.setattr(chat_module, "api_key", lambda: "offline-test-key")
    monkeypatch.setattr(chat_module, "AsyncOpenAI", FakeClient)
    store = SimpleNamespace(fields={}, revision="fixture-revision")
    result = asyncio.run(chat_module.Chat(chats).answer(store, "What does the source say?"))
    assert len(requests) == 1
    assert requests[0]["model"] == "gpt-6-luna"
    assert result["text"] == provider_text and not result["warnings"]
    saved = chats.get(result["session_id"])["messages"][-1]
    assert saved["content"] == provider_text
