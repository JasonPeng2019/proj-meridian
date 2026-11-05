"""R17 persistence slice of M15; grounded Responses sending remains unavailable.

M03 calls create_chat_service(history_dir=settings.chat_history_dir, tools=tools,
client=client). Only the frozen list/create/read/send methods are route boundaries.
ConversationStore.server_thread is a SERVER-ONLY capability for B06: hold it across
read/context/user/tool/assistant work, recording only actual server tool returns.
No request accepts saved messages, assistant replies, or tool ledger entries.

Each JSON file contains the complete frozen ConversationState. Reads reload disk;
ordinary same-directory replacement commits history and its ledger together. A
persistent OS lock per thread serializes store instances/processes, with bounded
lock waits and no growing in-memory lock registry. This is a local single-server
store, not a database or a distributed/network-filesystem coordination protocol.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import errno
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import TypeVar
from uuid import uuid4

from pydantic import ValidationError

from ..contracts import (
    APIError, CHAT_CONTEXT_TURNS, CONVERSATION_TITLE_LIMIT, ChatResponse, ChatTurn,
    ContractModel, ConversationContext, ConversationCreateRequest,
    ConversationDetail, ConversationLedger, ConversationListRequest,
    ConversationListResponse, ConversationRequest, ConversationSendRequest,
    ConversationSendResponse, ConversationService, ConversationState,
    ConversationSummary, ErrorCode, ErrorResponse, FactTools, SavedAssistantMessage,
    SavedUserMessage, ToolLedgerEntry,
)


ModelT = TypeVar("ModelT", bound=ContractModel)


class ChatServiceError(RuntimeError):
    """M03 returns response at status_code; causes stay private to the server."""

    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False):
        self.response = ErrorResponse(error=APIError(code=code, message=message, retryable=retryable))
        self.status_code = {
            ErrorCode.INVALID_REQUEST: 400, ErrorCode.NOT_FOUND: 404,
            ErrorCode.STALE_CONFLICT: 409, ErrorCode.UNSUPPORTED: 501,
        }.get(code, 500)
        super().__init__(message)


def _validated(model: type[ModelT], value: ModelT) -> ModelT:
    # Revalidate mutated/model_construct/model_copy instances and detach nested
    # mutable data. Never accept another request type's extra history/ledger.
    try:
        return model.model_validate(value.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ChatServiceError(ErrorCode.INVALID_REQUEST, "Invalid conversation input.") from error


def _storage_error() -> ChatServiceError:
    # No OS messages, filenames, paths, saved contents or ledger in public errors.
    return ChatServiceError(ErrorCode.INTERNAL_ERROR,
                            "Conversation storage is unreadable or invalid; existing history has been preserved.")


def _title(text: str) -> str:
    return " ".join(text.split())[:CONVERSATION_TITLE_LIMIT]


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON field")
        result[name] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-JSON numeric constant")


class ConversationStore:
    """Private local JSON state and server append boundaries, without a key/client."""

    def __init__(self, history_dir: Path, *, lock_timeout: float = 5.0):
        if not math.isfinite(lock_timeout) or lock_timeout <= 0:
            raise ValueError("lock_timeout must be a positive finite number")
        self._directory = Path(history_dir).resolve()
        self._lock_timeout = lock_timeout

    def _directory_exists(self, *, create: bool = False) -> bool:
        try:
            if create:
                self._directory.mkdir(parents=True, exist_ok=True)
            if not self._directory.exists():
                return False
            if not self._directory.is_dir():
                raise ValueError("History location is not a directory")
            return True
        except (OSError, ValueError) as error:
            raise _storage_error() from error

    def _path(self, conversation_id: str) -> Path:
        # Frozen ID validation precedes every call. The prefix also avoids
        # Windows device filenames (CON.json, AUX.json, etc.).
        return self._directory / f"conversation-{conversation_id}.json"

    @contextmanager
    def _lock(self, conversation_id: str) -> Iterator[None]:
        path = self._directory / f".conversation-{conversation_id}.lock"
        try:
            if path.is_symlink():
                raise ValueError("History lock is a symlink")
            with path.open("a+b") as handle:
                if os.name == "nt":
                    import msvcrt

                    if os.fstat(handle.fileno()).st_size == 0:
                        handle.write(b"\0")
                        handle.flush()
                else:
                    import fcntl

                deadline = time.monotonic() + self._lock_timeout
                while True:
                    try:
                        if os.name == "nt":
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as error:
                        if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ChatServiceError(ErrorCode.STALE_CONFLICT,
                                                   "This conversation is busy; retry shortly.", retryable=True) from error
                        time.sleep(min(0.025, remaining))
                try:
                    yield
                finally:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, ValueError) as error:
            raise _storage_error() from error

    def _read(self, conversation_id: str) -> ConversationState:
        path = self._path(conversation_id)
        try:
            if path.is_symlink():
                raise ValueError("History file is a symlink")
            data = json.loads(path.read_bytes(), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant)
            state = ConversationState.model_validate(data)
            summary = state.detail.conversation
            users = [message for message in state.detail.messages if message.role == "user"]
            if (summary.conversation_id != conversation_id
                    or summary.title != (_title(users[0].text) if users else "New chat")):
                raise ValueError("Stored conversation identity/title mismatch")
            return state
        except FileNotFoundError as error:
            raise ChatServiceError(ErrorCode.NOT_FOUND, "Conversation not found.") from error
        except (OSError, ValueError) as error:
            raise _storage_error() from error

    def _write(self, state: ConversationState) -> None:
        temporary: Path | None = None
        try:
            payload = state.model_dump_json(indent=2) + "\n"
            descriptor, name = tempfile.mkstemp(prefix=".conversation-", suffix=".tmp", dir=self._directory)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(state.detail.conversation.conversation_id))
        except (OSError, ValueError) as error:
            raise _storage_error() from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as error:
                    raise _storage_error() from error

    def list_conversations(self, request: ConversationListRequest) -> ConversationListResponse:
        _validated(ConversationListRequest, request)
        summaries: list[ConversationSummary] = []
        if self._directory_exists():
            try:
                # iterdir surfaces permission/read failures; glob may silently
                # treat an unreadable directory as an empty conversation list.
                paths = sorted(path for path in self._directory.iterdir() if path.suffix.lower() == ".json")
                for path in paths:
                    name = path.name.removeprefix("conversation-").removesuffix(".json")
                    try:
                        selected = ConversationRequest(conversation_id=name)
                    except ValidationError as error:
                        raise _storage_error() from error
                    if path.name != self._path(name).name:
                        raise _storage_error()
                    summaries.append(self.read_conversation(selected).conversation)
            except OSError as error:
                raise _storage_error() from error
        summaries.sort(key=lambda item: item.conversation_id)
        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return ConversationListResponse(conversations=summaries)

    def create_conversation(self, request: ConversationCreateRequest) -> ConversationDetail:
        metadata = _validated(ConversationCreateRequest, request).model_dump()
        self._directory_exists(create=True)
        for _ in range(8):
            conversation_id = "conv_" + uuid4().hex
            with self._lock(conversation_id):
                path = self._path(conversation_id)
                if path.exists() or path.is_symlink():
                    continue  # Never overwrite an existing thread, even on an ID collision.
                now = datetime.now(timezone.utc)
                detail = ConversationDetail(**metadata, conversation=ConversationSummary(
                    conversation_id=conversation_id, title="New chat", created_at=now, updated_at=now), messages=[])
                state = ConversationState(**metadata, detail=detail,
                                          ledger=ConversationLedger(conversation_id=conversation_id))
                self._write(state)
                return detail
        raise ChatServiceError(ErrorCode.INTERNAL_ERROR, "Could not allocate a new conversation ID.")

    @contextmanager
    def server_thread(self, request: ConversationRequest) -> Iterator[ConversationWriter]:
        """SERVER ONLY: serialize a complete exchange; never map this to an API.

        Every append commits immediately, preserving saved user/tool work if a
        later provider step fails. No arbitrary replace/import/save capability.
        B06 must run blocking store work off the async route's event loop and
        bound its own provider/tool work while holding this thread's lock.
        """
        selected = _validated(ConversationRequest, request)
        if not self._directory_exists():
            raise ChatServiceError(ErrorCode.NOT_FOUND, "Conversation not found.")
        path = self._path(selected.conversation_id)
        try:
            if not path.exists() and not path.is_symlink():
                raise ChatServiceError(ErrorCode.NOT_FOUND, "Conversation not found.")
        except OSError as error:
            raise _storage_error() from error
        with self._lock(selected.conversation_id):
            writer = ConversationWriter(self, self._read(selected.conversation_id))
            try:
                yield writer
            finally:
                writer._active = False

    def read_conversation(self, request: ConversationRequest) -> ConversationDetail:
        with self.server_thread(request) as thread:
            return thread.snapshot().detail

    def read_context(self, request: ConversationRequest, body: ConversationSendRequest) -> ConversationContext:
        """SERVER ONLY: project an unsaved current user message, without a write."""
        body = _validated(ConversationSendRequest, body)
        with self.server_thread(request) as thread:
            return thread.context(body)


class ConversationWriter:
    """Server-only append capability valid only inside store.server_thread()."""

    def __init__(self, store: ConversationStore, state: ConversationState):
        self._store, self._state, self._active = store, state, True

    def _check_active(self) -> None:
        if not self._active:
            raise RuntimeError("Conversation writer is outside its serialization boundary")

    def snapshot(self) -> ConversationState:
        """Private history/ledger snapshot; do not return this from a route."""
        self._check_active()
        return self._state.model_copy(deep=True)

    def context(self, body: ConversationSendRequest) -> ConversationContext:
        """Call BEFORE append_user: saved text + current user, once, tail of 10."""
        self._check_active()
        body = _validated(ConversationSendRequest, body)
        turns = [ChatTurn(role=message.role, text=(message.text if message.role == "user" else message.response.text))
                 for message in self._state.detail.messages]
        return ConversationContext(
            conversation_id=self._state.ledger.conversation_id,
            turns=(turns + [ChatTurn(role="user", text=body.message)])[-CHAT_CONTEXT_TURNS:])

    def _candidate(self) -> tuple[ConversationState, datetime]:
        self._check_active()
        state = self._state.model_copy(deep=True)
        # Keep ordering deterministic even if the wall clock moves backwards.
        now = max(datetime.now(timezone.utc), state.detail.conversation.updated_at + timedelta(microseconds=1))
        state.detail.conversation.updated_at = now
        return state, now

    def _commit(self, candidate: ConversationState) -> None:
        candidate = _validated(ConversationState, candidate)
        self._store._write(candidate)
        self._state = candidate

    def append_user(self, body: ConversationSendRequest) -> SavedUserMessage:
        body = _validated(ConversationSendRequest, body)
        state, now = self._candidate()
        if not any(message.role == "user" for message in state.detail.messages):
            state.detail.conversation.title = _title(body.message)
        user = SavedUserMessage(id="msg_" + uuid4().hex, role="user", text=body.message, created_at=now)
        state.detail.messages.append(user)
        self._commit(state)
        return user.model_copy(deep=True)

    def record_tool(self, entry: ToolLedgerEntry) -> None:
        """Record an ACTUAL successful server call, never client/model claims."""
        entry = _validated(ToolLedgerEntry, entry)
        state, _ = self._candidate()
        if (not state.detail.messages or state.detail.messages[-1].role != "user"
                or entry.user_message_id != state.detail.messages[-1].id):
            raise ChatServiceError(ErrorCode.INVALID_REQUEST, "Tool result does not belong to the current saved user message.")
        state.ledger.entries.append(entry)
        self._commit(state)

    def append_assistant(self, response: ChatResponse) -> SavedAssistantMessage:
        """B06 supplies its validated grounded reply for this thread, never a request body."""
        response = _validated(ChatResponse, response)
        state, now = self._candidate()
        if not state.detail.messages or state.detail.messages[-1].role != "user":
            raise ChatServiceError(ErrorCode.INVALID_REQUEST, "A reply requires a current saved user message.")
        assistant = SavedAssistantMessage(id="msg_" + uuid4().hex, role="assistant", response=response, created_at=now)
        state.detail.messages.append(assistant)
        self._commit(state)
        return assistant.model_copy(deep=True)


class ChatService(ConversationStore):
    send_available = False

    async def send(self, request: ConversationRequest, body: ConversationSendRequest) -> ConversationSendResponse:
        selected = _validated(ConversationRequest, request)
        _validated(ConversationSendRequest, body)
        self.read_conversation(selected)  # Unknown/corrupt threads still fail plainly.
        raise ChatServiceError(ErrorCode.UNSUPPORTED,
                               "Chat sending is unavailable until the grounded Responses service is integrated (B06).")


def create_chat_service(*, history_dir: Path, tools: FactTools, client: object | None) -> ConversationService:
    """Frozen M02 factory. M03 passes Settings.chat_history_dir; no key is loaded.

    Tools/client are reserved injection inputs for B06 and are never accessed in
    this early slice. Their presence does not make send available.
    """
    return ChatService(history_dir)
