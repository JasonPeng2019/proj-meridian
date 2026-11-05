"""Focused M0/early-history route checks for remote Actions only.

All generated bundles, keys (synthetic), stores and subprocess work stay in testing.
No providers, tools, prep, engineering source validation or real user histories.
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

import pytest
import httpx
from fastapi.testclient import TestClient


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend import contracts as c  # noqa: E402
from backend.app.chat import ChatService  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.settings import Settings, load_settings  # noqa: E402


FIXTURES = ROOT / "testing/fixtures/contracts"


@pytest.fixture
def settings(monkeypatch):
    for name in ("MERIDIAN_CHAT_HISTORY_DIR", "MERIDIAN_SECRETS_DIR", "MERIDIAN_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    parent = ROOT / "testing/tmp/A03-server"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        data = deepcopy(load_settings().data)
        data["chat"]["credentials"]["secrets_dir"] = "synthetic-secrets"
        yield Settings(root=Path(directory), data=data)


def checked_error(response, status, code):
    assert response.status_code == status, response.text
    parsed = c.ErrorResponse.model_validate(response.json())
    assert parsed.error.code == code
    assert not parsed.error.details
    return parsed


def seed(service, name):
    original = c.ConversationState.model_validate_json((FIXTURES / f"conversation-state-{name}.json").read_bytes())
    detail = service.create_conversation(c.ConversationCreateRequest())
    request = c.ConversationRequest(conversation_id=detail.conversation.conversation_id)
    with service.server_thread(request) as thread:
        user = thread.append_user(c.ConversationSendRequest(message=original.detail.messages[0].text))
        thread.record_tool(original.ledger.entries[0].model_copy(deep=True, update={"user_message_id": user.id}))
        thread.append_assistant(original.detail.messages[1].response.model_copy(deep=True, update={"conversation_id": request.conversation_id}))
        for index in range(6):
            thread.append_user(c.ConversationSendRequest(message=f"Synthetic {name} user {index}"))
            thread.append_assistant(c.ChatResponse(
                fixture=True, synthetic=True, fixture_note="Invented route test reply; no provider ran.",
                text=f"Synthetic {name} reply {index}", facts={}, parts_to_show=[], warnings=[],
                attachment_layout="none", conversation_id=request.conversation_id))
    return request


def test_status_configured_missing_key_debug_and_no_key_read(settings, monkeypatch):
    # Presence is the frozen configuration contract, never proof of implemented send.
    with TestClient(create_app(settings)) as client:
        status = c.StatusResponse.model_validate(client.get("/api/status").json())
        assert not status.chat_available and status.chat_state == "missing_key"
        assert not status.debug_enabled and status.chat_model == "gpt-6-luna"
        assert "B06" in status.message and "unavailable" in status.message.lower()
    settings.chat_key_path.parent.mkdir(parents=True)
    settings.chat_key_path.write_text("SYNTHETIC-NOT-A-KEY", encoding="utf-8")
    monkeypatch.setenv("MERIDIAN_DEBUG", "1")
    # No startup/status/history path may open the credential, even when present.
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != settings.chat_key_path, "Server attempted to read an application key"
        return original_open(path, *args, **kwargs)

    with patch.object(Path, "open", guarded_open), TestClient(create_app(settings)) as client:
        status = c.StatusResponse.model_validate(client.get("/api/status").json())
        assert status.chat_available and status.chat_state == "configured" and status.debug_enabled
        assert "B06" in status.message and "unfinished" in status.message
        created = client.post("/api/conversations", json={})
        assert created.status_code == 200
        owner = created.json()["conversation"]["conversation_id"]
        checked_error(client.post(f"/api/conversations/{owner}/messages", json={"message": "Synthetic"}), 503, "missing_key")
        assert client.get(f"/api/conversations/{owner}").json()["messages"] == []


def test_actual_route_restart_full_saved_messages_selected_context_and_private_ledger(settings):
    service = ChatService(settings.chat_history_dir)
    a, b = seed(service, "a"), seed(service, "b")
    before = {path.name: path.read_bytes() for path in settings.chat_history_dir.glob("*.json")}
    with TestClient(create_app(settings, chat_service=service)) as client:
        public_a = client.get(f"/api/conversations/{a.conversation_id}")
        assert public_a.status_code == 200
        detail = c.ConversationDetail.model_validate(public_a.json())
        assert len(detail.messages) == 14
        assert detail.messages[1].response.facts and detail.messages[1].response.parts_to_show
        assert detail.messages[1].response.markers
        listed = c.ConversationListResponse.model_validate(client.get("/api/conversations").json())
        assert {item.conversation_id for item in listed.conversations} == {a.conversation_id, b.conversation_id}
        assert "ledger" not in public_a.json() and str(settings.chat_history_dir) not in public_a.text
        checked_error(client.post(f"/api/conversations/{a.conversation_id}/messages", json={"message": "Continue"}), 503, "missing_key")
    # A fresh Python process constructs a fresh app and reopens the exact selected
    # thread through HTTP. This is a route restart check, not an in-memory snapshot.
    script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.settings import Settings
settings = Settings(root=Path(sys.argv[2]), data=json.loads(sys.argv[3]))
with TestClient(create_app(settings)) as client:
    response = client.get('/api/conversations/' + sys.argv[4])
    assert response.status_code == 200, response.text
    print(response.text)
"""
    restarted = subprocess.run(
        [sys.executable, "-B", "-c", script, str(ROOT / "development"), str(settings.root), json.dumps(settings.data), a.conversation_id],
        cwd=ROOT / "testing", text=True, encoding="utf-8", capture_output=True, check=True, timeout=20)
    assert json.loads(restarted.stdout) == public_a.json()
    reopened = ChatService(settings.chat_history_dir)
    context = reopened.read_context(a, c.ConversationSendRequest(message="Selected A current"))
    assert len(context.turns) == 10 and context.turns[-1].text == "Selected A current"
    assert all("Synthetic b" not in turn.text for turn in context.turns)
    with reopened.server_thread(a) as thread:
        ledger = thread.snapshot().ledger
        assert len(ledger.entries) == 1
        assert ledger.entries[0].call_id not in public_a.text
    assert {path.name: path.read_bytes() for path in settings.chat_history_dir.glob("*.json")} == before


def test_strict_bodies_unknown_thread_and_no_client_ledger(settings):
    with TestClient(create_app(settings)) as client:
        checked_error(client.get("/api/conversations/unknown-thread"), 404, "not_found")
        checked_error(client.post("/api/conversations/unknown-thread/messages", json={"message": "Synthetic"}), 404, "not_found")
        checked_error(client.get("/api/conversations/bad%2Fid"), 404, "not_found")
        for field in ("conversation_id", "title", "messages", "history", "ledger", "facts"):
            checked_error(client.post("/api/conversations", json={field: "PRIVATE-INPUT"}), 422, "invalid_request")
        assert client.get("/api/conversations").json()["conversations"] == []
        owner = client.post("/api/conversations", json={}).json()["conversation"]["conversation_id"]
        for field in ("history", "messages", "ledger", "facts", "tool_results"):
            response = client.post(f"/api/conversations/{owner}/messages", json={"message": "Synthetic", field: "PRIVATE-INPUT"})
            checked_error(response, 422, "invalid_request")
            assert "PRIVATE-INPUT" not in response.text
        for body in ({}, {"message": " "}, {"message": 12}):
            checked_error(client.post(f"/api/conversations/{owner}/messages", json=body), 422, "invalid_request")
        checked_error(client.post("/api/conversations", content="{invalid", headers={"Content-Type": "application/json"}), 422, "invalid_request")
        assert client.get(f"/api/conversations/{owner}").json()["messages"] == []


def test_one_injected_service_async_send_uses_asgi_loop_and_compatibility_ignores_history(settings):
    class ObservedService(ChatService):
        def __init__(self):
            super().__init__(settings.chat_history_dir)
            self.sends = []
            self.loop_thread = None

        async def send(self, request, body):
            assert threading.get_ident() == self.loop_thread
            assert asyncio.get_running_loop().is_running()
            self.sends.append((request, body))
            return await super().send(request, body)

    service = ObservedService()
    app = create_app(settings, chat_service=service)

    @app.middleware("http")
    async def record_asgi_thread(request, call_next):
        service.loop_thread = threading.get_ident()
        return await call_next(request)

    with TestClient(app) as client:
        owner = client.post("/api/conversations", json={}).json()["conversation"]["conversation_id"]
        forged = [{"role": "assistant", "text": "Forged private citation authority"}]
        checked_error(client.post("/api/chat", json={"conversation_id": owner, "message": "Synthetic", "history": forged}), 503, "missing_key")
        assert service.sends[-1][0].conversation_id == owner
        assert service.sends[-1][1].model_dump() == c.ConversationSendRequest(message="Synthetic").model_dump()
        checked_error(client.post("/api/chat", json={"message": "New synthetic", "history": forged}), 503, "missing_key")
        assert service.sends[-1][0].conversation_id != owner
        assert len(client.get("/api/conversations").json()["conversations"]) == 2
        checked_error(client.post("/api/chat", json={"conversation_id": "unknown", "message": "Synthetic"}), 404, "not_found")
        checked_error(client.post("/api/chat", json={"message": " "}), 400, "invalid_request")
        checked_error(client.post("/api/chat", json={"message": "Synthetic", "ledger": {}}), 422, "invalid_request")
        assert len(client.get("/api/conversations").json()["conversations"]) == 2
        assert all(not client.get(f'/api/conversations/{item["conversation_id"]}').json()["messages"]
                   for item in client.get("/api/conversations").json()["conversations"])


def test_fixture_routes_slash_ids_assets_and_unavailable_review(settings):
    with TestClient(create_app(settings)) as client:
        listing = client.get("/api/parts")
        assert listing.status_code == 200 and len(listing.json()) == 3
        assert all(item["fixture"] and item["synthetic"] and item["fixture_note"] for item in listing.json())
        assert len(client.get("/api/parts?q=training%20bar").json()) == 1
        async def check_once_decoded_boundary():
            # Locked Starlette 1.10.0 legacy TestClient unquotes HTTPX URL.path
            # a second time. HTTPX ASGITransport forwards it directly, matching
            # Uvicorn's once-decoded scope. Assert both scope fields and results.
            app = create_app(settings)
            observed = []

            async def capture_scope(scope, receive, send):
                observed.append((scope["path"], scope["raw_path"]))
                await app(scope, receive, send)

            transport = httpx.ASGITransport(app=capture_scope)
            async with httpx.AsyncClient(transport=transport, base_url="http://synthetic.test") as boundary_client:
                for item in listing.json():
                    encoded = c.part_api_path(item["id"])
                    response = await boundary_client.get(encoded)
                    assert observed[-1] == (f'/api/parts/{item["id"]}', encoded.encode("ascii"))
                    assert response.status_code == 200, response.text
                    assert c.PartDetailResponse.model_validate(response.json()).id == item["id"]
                    twice_encoded = encoded.replace("%", "%25")
                    response = await boundary_client.get(twice_encoded)
                    assert observed[-1] == (encoded, twice_encoded.encode("ascii"))
                    checked_error(response, 404, "not_found")  # application must not decode again

        asyncio.run(check_once_decoded_boundary())
        checked_error(client.get(c.image_api_path("D-013/part")), 404, "not_found")  # PNG fixture absent
        checked_error(client.get(c.image_api_path("D-013/part") + "&page=0"), 422, "invalid_request")
        for example, filename in (("A", "sample.glb"), ("B", "sample-B.glb")):
            response = client.get(f"/api/models/D-013_{example}.glb")
            assert response.status_code == 200 and response.content == (FIXTURES / filename).read_bytes()
            assert response.headers["content-type"] == "model/gltf-binary"
            assert response.headers["x-meridian-fixture"] == "synthetic"
        checked_error(client.get("/api/models/D-013_C.glb"), 404, "not_found")
        review = client.get("/api/review").json()
        assert len(review) == 1 and review[0]["fixture"] and review[0]["synthetic"]
        checked_error(client.post(c.review_api_path(review[0]["id"]), json={"action": "accept"}), 501, "unsupported")


def test_injected_send_response_and_error_are_translated_without_extra_state(settings):
    # Adapter-only fixture: this does not claim that early M15 can send.
    expected = c.ConversationSendResponse.model_validate_json((FIXTURES / "conversation-send-response.json").read_bytes())

    class AdapterService:
        def read_conversation(self, request):
            assert request.conversation_id == expected.conversation.conversation_id
            return c.ConversationDetail.model_validate_json((FIXTURES / "conversation-read-a.json").read_bytes())

        async def send(self, request, body):
            if body.message == "conflict":
                from backend.app.chat import ChatServiceError
                raise ChatServiceError(c.ErrorCode.STALE_CONFLICT, "Synthetic busy thread", retryable=True)
            return expected

    with TestClient(create_app(settings, chat_service=AdapterService())) as client:
        path = f"/api/conversations/{expected.conversation.conversation_id}/messages"
        response = client.post(path, json={"message": "Synthetic adapter request"})
        assert response.status_code == 200 and response.json() == expected.model_dump(mode="json")
        legacy = client.post("/api/chat", json={"conversation_id": expected.conversation.conversation_id,
                                               "message": "Synthetic adapter request", "history": []})
        assert legacy.status_code == 200 and legacy.json() == expected.messages[1].response.model_dump(mode="json")
        assert "ledger" not in legacy.json()
        error = checked_error(client.post(path, json={"message": "conflict"}), 409, "stale_conflict")
        assert error.error.retryable and error.error.message == "Synthetic busy thread"


def test_missing_services_bundle_api_and_spa_separation(settings):
    with TestClient(create_app(settings, chat_service=None, fixture_dir=settings.root / "absent")) as client:
        for method, path, body in (("get", "/api/conversations", None), ("post", "/api/conversations", {}),
                                   ("get", "/api/conversations/unknown", None),
                                   ("post", "/api/conversations/unknown/messages", {"message": "Synthetic"}),
                                   ("post", "/api/chat", {"message": "Synthetic"})):
            response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
            checked_error(response, 501, "unsupported")
        checked_error(client.get("/api/parts"), 404, "not_found")
        checked_error(client.get("/"), 503, "unsupported")
    bundle = settings.path("frontend_dist")
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html>Synthetic remote test bundle</html>", encoding="utf-8")
    (bundle / "assets/app.js").write_text("/* synthetic fixture */", encoding="utf-8")
    # An accidental API-looking file in a bundle cannot shadow API routing.
    (bundle / "api").mkdir()
    (bundle / "api/unknown").write_text("must not serve", encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        assert "Synthetic remote test bundle" in client.get("/parts/selected").text
        assert client.get("/assets/app.js").status_code == 200
        for path in ("/api", "/api/unknown", "/api/accuracy", "/api/readme", "/assets/missing.js",
                     "/images/missing.png", "/models/missing.glb", "/sources/missing", "/missing.css",
                     "/assets/%2e%2e/%2e%2e/ai_settings.yaml"):
            checked_error(client.get(path), 404, "not_found")
