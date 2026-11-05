"""Meridian composition: source-backed records, grounded chat and local history.

MERIDIAN_INPUTS_PATH selects the actual saved extraction. Explicit fixture mode
remains available to isolated foundation tests; production never invents sources.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .. import contracts as c
from ..settings import Settings, load_settings
from .chat import ChatService, ChatServiceError, create_chat_service


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
    registry=None,
    inputs_root: Path | None = None,
    client: object | None = _DEFAULT_SERVICE,
    decision_store=None,
) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    fixtures = Path(fixture_dir) if fixture_dir is not None else _FIXTURES
    input_location = os.environ.get("MERIDIAN_INPUTS_PATH")
    if not input_location and fixture_dir is None:
        packaged_inputs = settings.path("generated") / "inputs" / "inputs.json"
        if packaged_inputs.is_file():
            input_location = str(packaged_inputs)
    if registry is None and input_location and fixture_dir is None:
        from ..loader.records import RecordRegistry
        from ..loader.decisions import DecisionStore
        input_file = Path(input_location).resolve()
        inputs_root = input_file.parent
        prepared = settings.path("generated") / "prepared.json"
        decision_store = DecisionStore(settings.path("decisions"))
        if prepared.is_file():
            registry = RecordRegistry.from_paths(prepared_path=prepared, inputs_path=input_file,
                records_path=settings.path("generated") / "records.json", decisions=decision_store,
                manifest_path=settings.path("dataset") / "manifest.json")
        else:
            registry = RecordRegistry.from_inputs(input_file,
                settings.path("dataset") / "manifest.json", decisions=decision_store)
    tools = None
    review_service = None
    review_error_type = None
    managed_client = None
    if registry is not None:
        from .tools import FactTools
        tools = FactTools(registry)
        if decision_store is not None and (Path(__file__).parent / "review.py").is_file():
            from .review import ReviewError, create_review_service
            review_error_type = ReviewError
            review_service = create_review_service(registry=registry, decisions=decision_store,
                dependencies=c.ReviewDependencies(
                    append_decision=decision_store.human_appender(settings.data["reviewer_name"]),
                    rebuild_records=registry, resolve_facts=tools.resolve_facts,
                    load_template=registry.load_template, rebuild_model=None))
            tools = FactTools(registry, propose_correction=review_service.propose_correction)
        if client is _DEFAULT_SERVICE:
            try:
                key_text = settings.chat_key_path.read_text(encoding="utf-8-sig")
                key = re.search(r"sk-[A-Za-z0-9_-]+", key_text)
            except OSError:
                key = None
            if key:
                from openai import AsyncOpenAI
                managed_client = AsyncOpenAI(api_key=key.group(), max_retries=0, timeout=45)
            client = managed_client
        service = (create_chat_service(history_dir=settings.chat_history_dir, tools=tools, client=client)
                   if chat_service is _DEFAULT_SERVICE else chat_service)
    else:
        service = ChatService(settings.chat_history_dir) if chat_service is _DEFAULT_SERVICE else chat_service

    @asynccontextmanager
    async def lifespan(application):
        try:
            yield
        finally:
            if managed_client is not None:
                await managed_client.close()

    application = FastAPI(title="Meridian", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    application.state.chat_service = service
    application.state.registry = registry
    application.state.fact_tools = tools
    application.state.review_service = review_service

    @application.exception_handler(ChatServiceError)
    async def service_error(request: Request, error: ChatServiceError):
        return JSONResponse(error.response.model_dump(mode="json"), status_code=error.status_code)

    if review_error_type is not None:
        application.add_exception_handler(review_error_type, service_error)

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
        if registry is not None:
            return registry.records
        return [fixture(name, c.PartRecord) for name in ("D-013.json", "D-025.json", "bom-only.json")]

    def part(part_id: str) -> c.PartRecord:
        for record in records():
            if record.id == part_id:
                return record
        raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Part not found in the declared M0 fixtures.")

    @application.get("/api/status", response_model=c.StatusResponse)
    def status(query: Annotated[c.StatusRequest, Query()]):
        if registry is not None:
            available = client is not None
            return c.StatusResponse(chat_available=available,
                chat_state="configured" if available else "missing_key",
                message="Ask about a part to see its source drawing and recorded facts." if available
                    else "Chat unavailable: configure the server's OpenAI key. Parts and past conversations remain available.",
                debug_enabled=settings.debug_enabled,
                cad_available=any(record.has_3d for record in records()))
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

    # Grounded sends stay on the server's loop with their AsyncOpenAI client;
    # M15 offloads its synchronous storage and tool operations itself.
    @application.post("/api/conversations/{conversation_id}/messages", response_model=c.ConversationSendResponse)
    async def send_conversation(conversation_id: c.ConversationId, body: c.ConversationSendRequest):
        return await history().send(c.ConversationRequest(conversation_id=conversation_id), body)

    @application.post("/api/chat", response_model=c.ChatResponse)
    async def compatibility_chat(body: c.ChatRequest):
        try:
            message = c.ConversationSendRequest(message=body.message)
        except ValidationError as error:
            raise ChatServiceError(c.ErrorCode.INVALID_REQUEST, "Message must contain non-whitespace text.") from error
        selected = body.conversation_id
        if selected is None:
            created = await asyncio.to_thread(history().create_conversation, c.ConversationCreateRequest())
            selected = created.conversation.conversation_id
        else:
            await asyncio.to_thread(history().read_conversation, c.ConversationRequest(conversation_id=selected))
        # Compatibility history is deliberately ignored, never forwarded or saved.
        result = await history().send(c.ConversationRequest(conversation_id=selected), message)
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
                fixture=record.fixture, synthetic=record.synthetic, fixture_note=record.fixture_note,
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
        if registry is not None:
            if inputs_root is None:
                _unavailable("Drawing image root is not configured.")
            image_name = Path(record.drawing.image)
            if query.page != 1:
                image_name = image_name.with_name(f"{record.drawing.id}-p{query.page}.png")
            path = _within(inputs_root, image_name.as_posix())
            if path is None:
                raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Source drawing image is unavailable.")
            return FileResponse(path, media_type="image/png")
        path = _within(fixtures, record.drawing.image) if query.page == 1 else None
        if path is None:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Synthetic drawing image is absent from the M0 fixture bundle.")
        return FileResponse(path, media_type="image/png", headers={"X-Meridian-Fixture": "synthetic"})

    @application.get("/api/parts/{id:path}", response_model=c.PartDetailResponse)
    def detail(id: str):
        record = part(id)
        facts = tools.resolve_facts(record) if tools is not None else (
            fixture("tool-facts.json", c.GetFactsResult).facts if id == "D-013/part" else {})
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
        if registry is not None:
            asset = next(item for item in record.model.examples if item.id == query.example)
            path = _within(settings.root, asset.glb)
            if path is None:
                raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Reconstruction asset is unavailable.")
            return FileResponse(path, media_type="model/gltf-binary")
        metadata = fixture("sample-glb.json" if example == "A" else "sample-B-glb.json", _FixtureAsset)
        path = _within(fixtures, metadata.file)
        if path is None:
            raise ChatServiceError(c.ErrorCode.NOT_FOUND, "Synthetic model asset is missing.")
        return FileResponse(path, media_type="model/gltf-binary", headers={"X-Meridian-Fixture": "synthetic"})

    @application.get("/api/review", response_model=c.ReviewListResponse)
    def review(query: Annotated[c.ReviewListRequest, Query()]):
        if review_service is not None:
            return review_service.list_review(query)
        if registry is not None:
            return [item for item in registry.review_items
                    if (query.status == "all" or item.status == query.status)
                    and (query.part_id is None or item.part_id == query.part_id)]
        if any(value is not None for key, value in query.model_dump().items() if key not in {"status", "part_id"}):
            _unavailable("Later review filters are unavailable in M0.")
        item = fixture("review-item.json", c.ReviewItem)
        return [item] if (query.status in {"all", item.status} and query.part_id in {None, item.part_id}) else []

    @application.post("/api/review/{item_id:path}", response_model=c.ReviewActionResponse)
    def review_action(item_id: str, body: c.ReviewActionRequest):
        if review_service is not None:
            return review_service.review_action(item_id, body, settings.data["reviewer_name"])
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
