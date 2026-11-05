"""Local chat transcripts; provider context contains dialogue, never saved tool state."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.paths import inside

MAX_QUESTION = 16_000
MAX_MESSAGES = 200
MAX_BYTES = 8 * 1024 * 1024
_LOCK = threading.RLock()
_ID = re.compile(r"[0-9a-f]{32}")
_SECRET_KEY = re.compile(r"^(?:api[_-]?key|openai[_-]?api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token)$", re.I)
_HIDDEN_KEY = re.compile(r"^(?:reasoning|reasoning_content|chain_of_thought|encrypted_content)$", re.I)
_RESPONSE_KEYS = {"text", "facts", "parts_to_show", "warnings", "session_id", "model", "usage", "latency_ms", "tool_trace", "revision"}


def redact(value: Any) -> Any:
    """Keep credentials accidentally pasted into dialogue out of the saved copy."""
    if isinstance(value, dict):
        return {str(k): "[redacted]" if _SECRET_KEY.fullmatch(str(k)) else redact(v)
                for k, v in value.items() if not _HIDDEN_KEY.fullmatch(str(k))}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[redacted]", value)
        value = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]+", r"\1[redacted]", value)
        value = re.sub(r"(?i)(\b(?:[A-Z_]*API[_-]?KEY|password|access_token|refresh_token|secret)\s*[:=]\s*)[\"']?[^\s,;\"']+", r"\1[redacted]", value)
        # Also cover nonstandard provider keys supplied through the environment.
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            secret = os.environ.get(name, "")
            if len(secret) >= 8:
                value = value.replace(secret, "[redacted]")
    return value


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Conversations:
    def __init__(self, directory: str | Path = ".runtime/chats"):
        # Resolve again for every operation so a replaced directory/junction is rejected.
        self.directory = inside(directory)

    def _directory(self) -> Path:
        directory = inside(self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        return inside(directory)

    def _path(self, conversation_id: str) -> Path:
        if not isinstance(conversation_id, str) or not _ID.fullmatch(conversation_id):
            raise ValueError("Invalid chat ID")
        directory = self._directory()
        path = inside(directory / f"{conversation_id}.json")
        if path != directory / f"{conversation_id}.json":
            raise ValueError("Chat path escapes its storage directory")
        return path

    def get(self, conversation_id: str) -> dict:
        with _LOCK:
            path = self._path(conversation_id)
            if not path.is_file():
                raise KeyError("Chat not found")
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Saved chat exceeds the size limit")
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("id") != conversation_id
                    or not isinstance(data.get("messages"), list)
                    or len(data["messages"]) > MAX_MESSAGES):
                raise ValueError("Saved chat is invalid")
            for message in data["messages"]:
                if (not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}
                        or not isinstance(message.get("content"), str)):
                    raise ValueError("Saved chat is invalid")
            return redact(data)

    def list(self) -> list[dict]:
        with _LOCK:
            items = []
            for path in self._directory().glob("*.json"):
                if not _ID.fullmatch(path.stem):
                    continue
                try:
                    data = self.get(path.stem)
                    items.append({key: data[key] for key in ("id", "title", "created_at", "updated_at")} | {"message_count": len(data["messages"])})
                except (KeyError, ValueError, OSError):
                    # A malformed unrelated transcript must not hide the other chats.
                    continue
            return sorted(items, key=lambda item: (item["updated_at"], item["id"]), reverse=True)

    def dialogue(self, conversation_id: str, turns: int = 9) -> list[dict]:
        return [{"role": item["role"], "content": item["content"]}
                for item in self.get(conversation_id)["messages"][-turns * 2:]]

    def append_turn(self, conversation_id: str, question: str, response: dict, *, create: bool = False) -> dict:
        if not question.strip() or len(question) > MAX_QUESTION:
            raise ValueError(f"Enter a question of at most {MAX_QUESTION:,} characters")
        with _LOCK:
            path = self._path(conversation_id)
            timestamp = now()
            if path.exists():
                data = self.get(conversation_id)
            elif create:
                data = {"id": conversation_id, "title": " ".join(redact(question).split())[:100],
                        "created_at": timestamp, "updated_at": timestamp, "messages": []}
            else:
                raise KeyError("Chat not found")
            saved_response = redact({key: value for key, value in response.items() if key in _RESPONSE_KEYS})
            saved_response["session_id"] = conversation_id
            data["messages"].extend([
                {"role": "user", "content": redact(question), "created_at": timestamp},
                {"role": "assistant", "content": saved_response["text"], "response": saved_response, "created_at": timestamp},
            ])
            data["messages"] = data["messages"][-MAX_MESSAGES:]
            data["updated_at"] = timestamp
            encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            while len(encoded) > MAX_BYTES and len(data["messages"]) > 2:
                del data["messages"][:2]
                encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(encoded) > MAX_BYTES:
                raise ValueError("This answer exceeds the saved chat size limit")
            temporary = inside(path.parent / f".{conversation_id}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Revalidate destination immediately before the atomic replacement.
                os.replace(temporary, self._path(conversation_id))
            finally:
                if temporary.exists():
                    inside(temporary).unlink()
            return data

    def delete(self, conversation_id: str) -> None:
        with _LOCK:
            path = self._path(conversation_id)
            if not path.is_file():
                raise KeyError("Chat not found")
            path.unlink()
