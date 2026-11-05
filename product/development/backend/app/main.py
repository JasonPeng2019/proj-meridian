"""M0 composition and real early M15 history; no prep or credential loading.

The non-history data is explicitly synthetic M02 scaffold data. Grounded sends,
review mutations and later milestone services remain unavailable until integrated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .. import contracts as c
from ..settings import Settings, load_settings
from .chat import ChatService, ChatServiceError


_DEFAULT_SERVICE = object()
_FIXTURES = Path(__file__).resolve().parents[3] / "testing/fixtures/contracts"
_NOTE = "M0 uses invented M02 fixtures, not dataset evidence, executed AI or human review."


class _FixtureAsset(c.Payload):
    file: c.NonEmpty
    media_type: Literal["model/gltf-binary"]
    sha256: c.SHA256
    size_mm: c.Vector3
    gltf_units: Literal["meters"]


def _error(status: int, code: c.ErrorCode, message: str) -> JSONResponse:
    payload = c.ErrorResponse(error=c.APIError(code=code, message=message))
    return JSONResponse(payload.model_dump(mode="json"), status_code=status)


def _unavailable(message: str) -> None:
    raise ChatServiceError(c.ErrorCode.UNSUPPORTED, message)


def _within(root: Path, name: str) -> Path | None:
    """Resolve assets without exposing a directory, traversal or symlink escape."""
    base = root.resolve()
    target = (base / name).resolve()
    return target if target.is_relative_to(base) and target.is_file() else None


def create_app(
    settings: Settings | None = None,
    *,
    chat_service: c.ConversationService | None | object = _DEFAULT_SERVICE,
    fixture_dir: Path | None = None,
) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    fixtures = Path(fixture_dir) if fixture_dir is not None else _FIXTURES
    service = ChatService(settings.chat_history_dir) if chat_service is _DEFAULT_SERVICE else chat_service
    application = FastAPI(title="Meridian M0", docs_url=None, redoc_url=None, openapi_url=None)
    application.state.chat_service = service

    @application.exception_handler(ChatServiceError)
    async def service_error(request: Request, error: ChatServiceError):
        return JSONResponse(error.response.model_dump(mode="json"), status_code=error.status_code)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        # Do not echo invalid bodies, saved text, ledger entries or private paths.
        return _error(422, c.ErrorCode.INVALID_REQUEST, "Invalid request body, path or query.")

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        code = c.ErrorCode.NOT_FOUND if error.status_code == 404 else c.ErrorCode.INVALID_REQUEST
        return _error(error.status_code, code, "Route or asset not found." if error.status_code == 404 else "Request is not supported at this route.")

    @application.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        return _error(500, c.ErrorCode.INTERNAL_ERROR, "Server operation failed; no reply or decision was fabricated.")

    def history() -> c.ConversationService:
        if service is None:
            _unavailable("Conversation service is unavailable; no replacement history or reply was fabricated.")
        return service

    def fixture(name: str, model):
        path = _within(fixtures, name)
        if path is None:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Required M0 fixture bundle or asset is missing.")
        try:
            result = model.model_validate_json(path.read_bytes())
            if not result.fixture or not result.synthetic:
                raise ValueError("Undeclared fixture")
            return result
        except (OSError, ValueError, ValidationError) as error:
            raise ChatServiceError(c.ErrorCode.INTERNAL_ERROR, "M0 fixture bundle is unreadable or invalid.") from error

    def records() -> list[c.PartRecord]:
        return [fixture(name, c.PartRecord) for name in ("D-013.json", "D-025.json", "bom-only.json")]

    def part(part_id: str) -> c.PartRecord:
        for record in records():
            if record.id == part_id:
                return record
        raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Part not found in the declared M0 fixtures.")

    @application.get("/api/status", response_model=c.StatusResponse)
    def status(query: Annotated[c.StatusRequest, Query()]):
        try:
            configured = settings.chat_key_present
        except OSError:
            configured = False
        configuration = "Server key file is present (authentication untested)." if configured else "Chat unavailable: server key file is missing, empty or unreadable."
        return c.StatusResponse(
            chat_available=configured, chat_state="configured" if configured else "missing_key",
            message=f"{configuration} Sending is unavailable: the grounded chat service is unfinished until B06. History list/new/read needs no key. {_NOTE}",
            debug_enabled=settings.debug_enabled, cad_available=None,
        )

    @application.get("/api/conversations", response_model=c.ConversationListResponse)
    def conversations(query: Annotated[c.ConversationListRequest, Query()]):
        return history().list_conversations(query)

    @application.post("/api/conversations", response_model=c.ConversationDetail)
    def new_conversation(body: c.ConversationCreateRequest):
        return history().create_conversation(body)

    @application.get("/api/conversations/{conversation_id}", response_model=c.ConversationDetail)
    def read_conversation(conversation_id: c.ConversationId):
        return history().read_conversation(c.ConversationRequest(conversation_id=conversation_id))

    # Synchronous route handlers run in Starlette's worker pool. The early async
    # send does synchronous disk reads, so run its coroutine there too. No storage
    # call blocks the ASGI event loop. Revisit this bridge for B06 loop-bound clients.
    @application.post("/api/conversations/{conversation_id}/messages", response_model=c.ConversationSendResponse)
    def send_conversation(conversation_id: c.ConversationId, body: c.ConversationSendRequest):
        return asyncio.run(history().send(c.ConversationRequest(conversation_id=conversation_id), body))

    @application.post("/api/chat", response_model=c.ChatResponse)
    def compatibility_chat(body: c.ChatRequest):
        try:
            message = c.ConversationSendRequest(message=body.message)
        except ValidationError as error:
            raise ChatServiceError(c.ErrorCode.INVALID_REQUEST, "Message must contain non-whitespace text.") from error
        selected = body.conversation_id
        if selected is None:
            selected = history().create_conversation(c.ConversationCreateRequest()).conversation.conversation_id
        else:
            history().read_conversation(c.ConversationRequest(conversation_id=selected))
        # Compatibility history is deliberately ignored, never forwarded or saved.
        result = asyncio.run(history().send(c.ConversationRequest(conversation_id=selected),
                                           message))
        return result.messages[1].response

    @application.get("/api/parts", response_model=c.PartsResponse)
    def parts(query: Annotated[c.PartsRequest, Query()]):
        if any(value is not None for key, value in query.model_dump().items() if key != "q"):
            _unavailable("Part filters beyond text search are unavailable in M0.")
        result = []
        for record in records():
            if query.q.casefold() not in f"{record.id} {record.display_name} {record.section or ''}".casefold():
                continue
            result.append(c.PartSummary(
                fixture=True, synthetic=True, fixture_note=record.fixture_note,
                id=record.id, display_name=record.display_name, section=record.section,
                has_drawing=record.has_drawing, has_3d=record.has_3d, examples=record.examples,
                thumbnail=c.image_api_path(record.id, thumb=True) if record.has_drawing else None,
                model_state=record.model.state, review_items=record.review_items,
            ))
        return result

    # Greedy IDs preserve encoded slashes. Suffix routes precede the detail route;
    # IDs have already been decoded by ASGI and must never be unquoted again.
    @application.get("/api/parts/{id:path}/image")
    def image(id: str, page: Annotated[int, Query(ge=1)] = 1,
              thumb: Annotated[int, Query(ge=0, le=1)] = 0):
        query = c.ImageRequest(id=id, page=page, thumb=thumb)
        record = part(id)
        if record.drawing is None or query.page > record.drawing.pages:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Drawing page is unavailable.")
        path = _within(fixtures, record.drawing.image) if query.page == 1 else None
        if path is None:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Synthetic drawing image is absent from the M0 fixture bundle.")
        return FileResponse(path, media_type="image/png", headers={"X-Meridian-Fixture": "synthetic"})

    @application.get("/api/parts/{id:path}", response_model=c.PartDetailResponse)
    def detail(id: str):
        record = part(id)
        facts = fixture("tool-facts.json", c.GetFactsResult).facts if id == "D-013/part" else {}
        return c.PartDetailResponse(**record.model_dump(), facts=facts)

    @application.get("/api/models/{drawing_id}_{example}.glb")
    def model(drawing_id: str, example: str):
        try:
            query = c.ModelRequest(drawing_id=drawing_id, example=example)
        except ValidationError as error:
            raise ChatServiceError(c.ErrorCode.INVALID_REQUEST, "Invalid model identity.") from error
        record = part(c.drawing_part_name(query.drawing_id))
        if query.example not in record.examples:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Model example is unavailable.")
        metadata = fixture("sample-glb.json" if example == "A" else "sample-B-glb.json", _FixtureAsset)
        path = _within(fixtures, metadata.file)
        if path is None:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Synthetic model asset is missing.")
        return FileResponse(path, media_type="model/gltf-binary", headers={"X-Meridian-Fixture": "synthetic"})

    @application.get("/api/review", response_model=c.ReviewListResponse)
    def review(query: Annotated[c.ReviewListRequest, Query()]):
        if any(value is not None for key, value in query.model_dump().items() if key not in {"status", "part_id"}):
            _unavailable("Later review filters are unavailable in M0.")
        item = fixture("review-item.json", c.ReviewItem)
        return [item] if (query.status in {"all", item.status} and query.part_id in {None, item.part_id}) else []

    @application.post("/api/review/{item_id:path}", response_model=c.ReviewActionResponse)
    def review_action(item_id: str, body: c.ReviewActionRequest):
        _unavailable("Review actions are unavailable until the real review service is integrated; no decision was recorded.")

    @application.get("/{path:path}")
    def frontend(path: str):
        head = path.split("/", 1)[0]
        if head == "api":
            raise HTTPException(404)
        bundle = settings.path("frontend_dist")
        asset = _within(bundle, path) if path else None
        if asset is not None:
            return FileResponse(asset)
        # Missing assets and later API endpoints must never return index.html.
        if head in {"assets", "images", "models", "sources", "generated"} or Path(path).suffix:
            raise HTTPException(404)
        index = _within(bundle, "index.html")
        if index is None:
            return _error(503, c.ErrorCode.UNSUPPORTED, "Built frontend bundle is missing. Install the matching remote frontend artifact before opening Meridian.")
        return FileResponse(index, media_type="text/html")

    return application


app = create_app()
