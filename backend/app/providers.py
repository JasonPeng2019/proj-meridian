"""Provider credentials and Anthropic transport for Meridian's existing tool loop."""
from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace

import httpx
from dotenv import load_dotenv

from backend.paths import ROOT, inside

OPENAI_MODEL = "gpt-6-luna"
ANTHROPIC_MODEL = "claude-sonnet-5-5"


def provider_name() -> str:
    load_dotenv(ROOT / ".env", override=False)
    provider = os.environ.get("CHAT_PROVIDER", "auto").strip().lower() or "auto"
    if provider not in {"auto", "openai", "anthropic"}:
        raise ValueError("CHAT_PROVIDER must be openai, anthropic, or auto.")
    if provider == "auto":
        # Explicit environment/.env keys take precedence over the legacy local key file.
        if os.environ.get("ANTHROPIC_API_KEY", "").strip() and not os.environ.get("OPENAI_API_KEY", "").strip():
            return "anthropic"
        return "openai"
    return provider


def model_name(provider: str | None = None) -> str:
    if (provider or provider_name()) == "openai":
        return OPENAI_MODEL
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or ANTHROPIC_MODEL


def api_key() -> str | None:
    if os.environ.get("MERIDIAN_NO_KEY") == "1":
        return None
    provider = provider_name()
    key = os.environ.get("ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", "").strip()
    if key:
        return key
    if provider == "openai":
        path = inside(".codex/.secrets/OpenAI_API_Keys.txt")
        if path.exists():
            matches = re.findall(r"sk-[A-Za-z0-9_-]+", path.read_text(encoding="utf-8-sig"))
            if len(matches) == 1:
                return matches[0]
    return None


def _messages(items):
    messages = []

    def append(role, content):
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": list(blocks)})

    for item in items:
        if isinstance(item, dict) and "role" in item:
            append(item["role"], item["content"])
        elif getattr(item, "type", None) == "anthropic_message":
            # Preserve complete provider blocks, including signed thinking, in this turn only.
            append("assistant", item.content)
        elif isinstance(item, dict) and item.get("type") == "function_call_output":
            append("user", [{"type": "tool_result", "tool_use_id": item["call_id"], "content": item["output"]}])
        # Function-call objects mirror the tool_use blocks already included above.
    return messages


class AnthropicClient:
    """Expose the small Responses interface used by chat and the review-input parser.

    This translates transport formats only. It never grades or repairs chat text.
    """
    def __init__(self, *, api_key, timeout=90, max_retries=0, transport=None):
        if max_retries:
            raise ValueError("Automatic provider retries are disabled.")
        self._http = httpx.AsyncClient(
            timeout=timeout, transport=transport, follow_redirects=False,
            headers={"Authorization": f"Bearer {api_key}", "anthropic-version": "2026-10-21"},
        )
        self.responses = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._http.aclose()

    async def create(self, *, model, instructions, input, max_output_tokens, tools=None, text=None, **_):
        payload = {"model": model, "system": instructions, "messages": _messages(input),
                   "max_tokens": max_output_tokens, "stream": False}
        if tools:
            payload["tools"] = [{"name": tool["name"], "description": tool["description"],
                                 "input_schema": tool["parameters"]} for tool in tools]
        if text:
            payload["output_config"] = {"format": {"type": "json_schema", "schema": text["format"]["schema"]}}
        response = await self._http.post("https://api.anthropic.com/v1/messages", json=payload)
        response.raise_for_status()
        data = response.json()
        content = data.get("content", [])
        output = [SimpleNamespace(type="anthropic_message", content=content)]
        output.extend(SimpleNamespace(type="function_call", name=block["name"], call_id=block["id"],
                                      arguments=json.dumps(block["input"]))
                      for block in content if block.get("type") == "tool_use")
        usage = data.get("usage", {})
        input_tokens = sum(usage.get(name, 0) or 0 for name in
                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        output_tokens = usage.get("output_tokens", 0) or 0
        return SimpleNamespace(
            output=output, output_text="".join(block.get("text", "") for block in content if block.get("type") == "text"),
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens+output_tokens),
            status="completed" if data.get("stop_reason") in {"end_turn", "stop_sequence"} else "incomplete",
            id=data.get("id"), _request_id=response.headers.get("request-id"),
        )
