"""Single-provider tool loop and server-validated evidence markers."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
from openai import AsyncOpenAI

from backend.paths import ROOT, inside
from backend.app.store import Store
from backend.app.tools import KnowledgeTools, api_tools

MODEL = "gpt-6-luna"
SYSTEM = """You are Meridian, an engineering assistant for the pinned OpenLPBF v2 evidence.
Answer ONLY from returned structured tool evidence, never from memory or raw PDFs.
Use find_part then get_facts for a particular part. You may use multiple tools.
Values are resolved by code: use display exactly; do not choose sources or map names yourself.
Every factual claim needs [cite: stable-name] immediately after it. Several names may be comma separated.
When display.state is undetermined, put [undetermined: stable-name] where the value belongs, and explain why from its message. Never give it a guessed value.
When display.state is options, state both printed possibilities, call them possible readings, and mention the A/B viewer. Weight checks do not determine which is correct.
For every specific part discussed, cite its whole-part id as well, even when evidence is missing, to attach its drawing and 3D if present.
The application attaches the drawing and orbitable 3D using your citations. If has_drawing/has_3d are true, say they are attached below; do not claim they are unavailable merely because tools return structured facts instead of image/file bytes. Never say A/B examples distinguish which reading is correct; they visualize both possibilities.
Only cite stable names returned by tools this turn. Do not invent citations. Unlabeled drawing numbers do not tell you which edge or feature they measure.
For AI facts not human-reviewed say 'AI-sourced only, not yet reviewed; may contain errors.' For reviewed facts preserve who and when.
If review_item exists, say 'Waiting for review'; the interface supplies the link.
For corrections, state the original value, corrected value, reviewer and date from correction metadata. The printed sheet is original evidence, not rewritten.
Procurement/material/status/cost fields are recorded snapshot evidence. Supplier, price, order, link and availability answers must say 'as recorded in the snapshot, may be out of date.' Never claim current availability. A subtotal is not the complete machine cost.
Material lists must say 'Materials recorded', not 'made of' or 'versions'.
README-only citations do not attach drawings. Native CAD and images mentioned but not supplied are unavailable in this corpus.
The user can propose a correction, but only a human in the separate Review UI can accept or reject it. Call propose_correction only when explicitly requested to change a fact. Never claim you approved it.
If ambiguous, ask a short clarification. If unsupported, abstain. Be concise and useful.
"""

def api_key() -> str | None:
    if os.environ.get("MERIDIAN_NO_KEY") == "1":
        return None
    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    path = inside(".codex/.secrets/OpenAI_API_Keys.txt")
    if path.exists():
        matches = re.findall(r"sk-[A-Za-z0-9_-]+", path.read_text(encoding="utf-8-sig"))
        if len(matches) == 1:
            return matches[0]
    return None

def collect_evidence(result: Any, ledger: dict, tools: KnowledgeTools) -> None:
    if isinstance(result, dict):
        if "fact" in result and "display" in result:
            ledger[result["fact"]] = result
            for source in result.get("sources", []):
                if source.get("name") in tools.store.fields:
                    ledger.setdefault(source["name"], tools.display(source["name"]))
        name = result.get("name")
        if name in tools.store.fields and "/drawing/n/" in name and "value" in result:
            ledger.setdefault(name, tools.display(name))
        if "id" in result and result["id"] in tools.store.fields:
            ledger[result["id"]] = tools.display(result["id"])
        source = result.get("source")
        if isinstance(source, str) and source in tools.store.fields:
            ledger[source] = tools.display(source)
        for value in result.values():
            collect_evidence(value, ledger, tools)
    elif isinstance(result, list):
        for value in result:
            collect_evidence(value, ledger, tools)

def validate_markers(text: str, ledger: dict, store: Store, single_matches: list[str] | None = None) -> dict:
    warnings, parts, cited, unknown_markers = [], [], [], set()
    for kind, raw in re.findall(r"\[(cite|undetermined):\s*([^\]]+)\]", text):
        names = [v.strip() for v in raw.split(",") if v.strip()]
        for name in names:
            if name not in ledger or name not in store.fields:
                warnings.append(f"Invalid citation: {name} was not returned by a tool this turn.")
                continue
            fact = ledger[name]
            if kind == "undetermined":
                if fact.get("display", {}).get("state") != "undetermined":
                    warnings.append(f"Invalid Undetermined marker: {name} has a value.")
                    continue
                unknown_markers.add(name)
            cited.append(name)
            key = fact.get("part_key")
            if key and key not in parts:
                parts.append(key)
    for name in cited:
        if ledger[name].get("display", {}).get("state") == "undetermined" and name not in unknown_markers:
            warnings.append("This answer cites something the sources could not determine without its Undetermined marker: " + name)
    backup = False
    if not parts and single_matches and len(set(single_matches)) == 1:
        parts.append(single_matches[0])
        backup = True
    if not cited and len(text.split()) > 8 and not text.rstrip().endswith("?"):
        warnings.append("This answer has no cited sources.")
    summaries = []
    for key in parts:
        part = store.part(key)
        safe = quote(key, safe="/")
        summaries.append({**KnowledgeTools.summary(part), "thumbnail": f"/api/parts/{safe}/image?page=1&thumb=1" if part.get("has_drawing") else None,
                          "drawing_url": f"/part/{safe}/2d" if part.get("has_drawing") else None,
                          "model_url": f"/part/{safe}/3d" if part.get("has_3d") else None,
                          "shown_reason": "Shown because your question named this part." if backup else None})
    return {"text": text, "facts": ledger, "parts_to_show": summaries, "warnings": list(dict.fromkeys(warnings))}

class Chat:
    def __init__(self):
        self.sessions: dict[str, list[list[Any]]] = {}

    async def answer(self, store: Store, message: str, session_id: str | None = None) -> dict:
        key = api_key()
        if not key:
            raise ValueError("Add an API key to use the chat.")
        sid = session_id if session_id in self.sessions else uuid.uuid4().hex
        turns = self.sessions.setdefault(sid, [])
        # Previous turns carry only dialogue, not stale accepted evidence. Every new
        # factual answer fetches current tool values after any review action.
        history = [item for turn in turns[-9:] for item in turn]
        current: list[Any] = [{"role": "user", "content": message}]
        ledger: dict = {}
        single_matches = []
        tool_trace = []
        tools = KnowledgeTools(store)
        token_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        started = time.perf_counter()
        async with AsyncOpenAI(api_key=key, max_retries=0, timeout=90) as client:
            for _ in range(10):
                response = await client.responses.create(model=MODEL, reasoning={"effort": "low"}, service_tier="default", store=False,
                    instructions=SYSTEM, tools=api_tools(), input=history + current, max_output_tokens=6000)
                usage = response.usage
                if usage:
                    for name in token_totals:
                        token_totals[name] += getattr(usage, name, 0) or 0
                current.extend(response.output)
                calls = [item for item in response.output if item.type == "function_call"]
                if not calls:
                    text = response.output_text
                    if not text:
                        raise ValueError("The model returned no final answer.")
                    result = validate_markers(text, ledger, store, single_matches)
                    result.update(session_id=sid, model=MODEL, usage=token_totals, latency_ms=round((time.perf_counter() - started) * 1000), tool_trace=tool_trace, revision=store.revision)
                    turns.append([{"role": "user", "content": message}, {"role": "assistant", "content": text}])
                    del turns[:-10]
                    return result
                for call in calls:
                    try:
                        args = json.loads(call.arguments)
                        allowed = {tool["name"] for tool in api_tools()}
                        if call.name not in allowed:
                            raise ValueError("Unknown tool")
                        output = getattr(tools, call.name)(**args)
                        if call.name == "find_part" and len(output.get("parts", [])) == 1:
                            single_matches.append(output["parts"][0]["key"])
                        collect_evidence(output, ledger, tools)
                        tool_trace.append({"tool": call.name, "arguments": args, "facts_returned": list(ledger)})
                    except (ValueError, KeyError, TypeError) as exc:
                        output = {"error": str(exc)}
                    current.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(output, ensure_ascii=False)})
        raise ValueError("The chat reached its tool-call limit. Please ask a narrower question.")
