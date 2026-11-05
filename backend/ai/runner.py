"""Two read-only CLI readers, content-addressed caching, and one governed retry."""
from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from backend.paths import ROOT, GENERATED, configure_environment, inside

CACHE = GENERATED / "ai_cache"
_semaphore = threading.Semaphore(4)
_write_lock = threading.Lock()
_bootstrap_lock = threading.Lock()
_bootstrapped = False


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path = inside(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        temporary = inside(path.with_suffix(path.suffix + ".tmp"))
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def bootstrap_auth() -> None:
    """Read existing credentials once; every mutable child state stays in Avathon."""
    global _bootstrapped
    with _bootstrap_lock:
        if _bootstrapped:
            return
        configure_environment()
        pairs = [(Path.home() / ".codex/auth.json", inside(".runtime/codex/auth.json")),
                 (Path.home() / ".claude/.credentials.json", inside(".runtime/claude/.credentials.json"))]
        for source, destination in pairs:
            if source.is_file() and not destination.exists():
                shutil.copyfile(source, destination)
        _bootstrapped = True


def codex_command() -> list[str]:
    command = shutil.which("codex")
    if not command:
        raise RuntimeError("Codex CLI is not installed; shipped results remain usable")
    path = Path(command)
    if path.suffix.lower() in (".cmd", ".ps1", ".bat"):
        package = path.parent / "node_modules/@openai/codex"
        native = list(package.glob("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe"))
        if native:
            return [str(native[0])]
        script = package / "bin/codex.js"
        if script.is_file():
            return [shutil.which("node") or "node", str(script)]
    return [command]


def reader_settings(reader: str) -> dict:
    if reader == "claude":
        return {"model": "opus", "fast_mode": False, "mode": "regular", "reader": "claude"}
    return {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh", "service_tier": "fast", "reader": "codex"}


def parse_response(reader: str, stdout: str, final_path: Path) -> tuple[dict | None, dict]:
    metadata: dict = {}
    try:
        if reader == "claude":
            envelope = json.loads(stdout)
            metadata = {key: envelope.get(key) for key in ("usage", "modelUsage", "total_cost_usd", "duration_ms", "is_error")}
            if envelope.get("is_error"):
                return None, {**metadata, "error": str(envelope.get("result", "Reader failed"))[:600]}
            result = envelope.get("structured_output")
            if result is None:
                result = envelope.get("result")
                result = json.loads(result) if isinstance(result, str) else result
        else:
            result = json.loads(final_path.read_text(encoding="utf-8")) if final_path.exists() else None
            events = []
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                    if event.get("type") in ("turn.completed", "error", "turn.failed"):
                        events.append(event)
                except json.JSONDecodeError:
                    pass
            metadata = {"events": events}
        return result if isinstance(result, dict) else None, metadata
    except (json.JSONDecodeError, OSError, TypeError):
        return None, {**metadata, "error": "Malformed AI output; no repair attempted"}


def run_reader(reader: str, prompt: str, schema: dict, images: list[str], job: str,
               timeout: int = 900, force: bool = False) -> dict:
    bootstrap_auth()
    image_paths = [inside(p) for p in images]
    image_bytes = [p.read_bytes() for p in image_paths]
    identity = {"protocol": 2, "reader": reader_settings(reader), "prompt": prompt, "schema": schema,
                "images": [hashlib.sha256(data).hexdigest() for data in image_bytes]}
    digest = fingerprint(identity)
    folder = inside(CACHE / digest)
    result_file = folder / "result.json"
    if result_file.exists() and not force:
        cached = json.loads(result_file.read_text(encoding="utf-8"))
        return {**cached, "cache_hit": True}
    folder.mkdir(parents=True, exist_ok=True)
    # Freeze the exact image bytes the cache key describes before spawning either reader.
    frozen = []
    for index, (path, data) in enumerate(zip(image_paths, image_bytes)):
        snapshot = inside(folder / f"input-{index}{path.suffix}")
        if not snapshot.exists():
            snapshot.write_bytes(data)
        frozen.append(snapshot)
    image_paths = frozen
    write_json(folder / "request.json", {**identity, "job": job})
    write_json(folder / "schema.json", schema)
    final_file = inside(folder / "final.json")
    if final_file.exists():
        final_file.unlink()
    if reader == "claude":
        command = shutil.which("claude")
        if not command:
            raise RuntimeError("Claude CLI is not installed")
        image_instruction = "\nRead these supplied evidence images using Read before answering: " + ", ".join(str(p) for p in image_paths) if image_paths else ""
        argv = [command, "-p", "--model", "opus", "--safe-mode", "--restricted",
                "--tools", "Read", "--allowedTools", "Read", "--disallowedTools", "mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--permission-prompts", "none", "--no-session-persistence", "--no-chrome",
                "--output-format", "json", "--json-schema", json_text(schema),
                "--settings", '{"fastMode":false,"autoMemoryEnabled":false,"disableAllHooks":true}']
        # Large judge evidence must not exceed Windows' command-line limit.
        stdin = prompt + image_instruction
    else:
        argv = codex_command() + ["exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                "--ephemeral", "--sandbox", "read-only", "--model", "gpt-6.1-sol",
                "--config", 'model_reasoning_effort="xhigh"', "--config", 'service_tier="fast"',
                "--config", "features.fast_mode=true", "--config", "features.hooks=false",
                "--config", 'web_search="disabled"', "--config", "features.memories=false",
                "--output-schema", str(folder / "schema.json"), "--output-last-message", str(final_file),
                "--json", "--color", "never", "--cd", str(ROOT)]
        for path in image_paths:
            argv += ["--image", str(path)]
        argv += ["-"]
        stdin = prompt
    start = time.monotonic()
    with _semaphore:
        attempt = 0
        while True:
            attempt += 1
            # A retry must never consume a previous attempt's final message.
            if reader != 'claude' and final_file.exists():
                final_file.unlink()
            try:
                completed = subprocess.run(argv, cwd=ROOT, input=stdin, capture_output=True, text=True,
                                           encoding="utf-8", errors="replace", timeout=timeout, env=os.environ.copy())
                stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
            except subprocess.TimeoutExpired:
                stdout, stderr, returncode = "", f"Reader timed out after {timeout} seconds", -1
            except OSError as exc:
                stdout, stderr, returncode = "", str(exc), -1
            combined = stdout + "\n" + stderr
            parsed, _ = parse_response(reader, stdout, final_file)
            rate_limit = (returncode != 0 or parsed is None) and bool(re.search(
                r"(?:rate.limit|too many requests|retry.after|(?<![a-z0-9])429(?![a-z0-9]))", combined, re.I))
            if rate_limit and attempt <= 4:
                match = re.search(r"retry.after[^0-9]*(\d+)", combined, re.I)
                delay = min(180, int(match.group(1)) if match else 15 * (2 ** (attempt - 1)))
                print(f"{job}: {reader} rate limited; waiting {delay}s", flush=True)
                time.sleep(delay)
                continue
            break
    # Provider CLI responses should never contain credentials; redact defensive matches.
    for filename, text in (("stdout.txt", stdout), ("stderr.txt", stderr)):
        inside(folder / filename).write_text(re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[REDACTED]", text), encoding="utf-8")
    result, metadata = parse_response(reader, stdout, final_file)
    outcome = {"reader": reader, "settings": reader_settings(reader), "answer": result,
               "valid": result is not None and returncode == 0, "returncode": returncode,
               "metadata": metadata, "latency_ms": round((time.monotonic() - start) * 1000),
               "cache_key": digest, "cache_hit": False, "job": job,
               "error": None if result is not None and returncode == 0 else (metadata.get("error") or stderr[-800:] or "No valid JSON answer")}
    write_json(result_file, outcome)
    print(f"{job}: {reader} {'finished' if outcome['valid'] else 'FAILED'} ({outcome['latency_ms']/1000:.1f}s)", flush=True)
    return outcome


def pair(prompt: str, schema: dict, images: list[str], job: str, **kwargs) -> dict:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {reader: pool.submit(run_reader, reader, prompt, schema, images, job, **kwargs) for reader in ("claude", "codex")}
        return {reader: future.result() for reader, future in futures.items()}


def compare(a: dict | None, b: dict | None, value_key: str = "value") -> str:
    if not a or not b:
        return "invalid"
    if a.get("confidence") != "sure" or b.get("confidence") != "sure":
        return "unsure"
    # JSON numbers 250 and 250.0 denote the same value; spelling is significant for strings.
    return "agreed" if (a.get("state") == b.get("state") and
                          semantic_value(a.get(value_key)) == semantic_value(b.get(value_key))) else "disagree"


def semantic_value(value: Any) -> Any:
    """Evidence citation choices and feature ordering are not geometry disagreements."""
    if isinstance(value, dict):
        ignored = {"fact_ids", "expression", "readers", "method", "reason", "note", "confidence", "review"}
        return {key: semantic_value(content) for key, content in value.items() if key not in ignored}
    if isinstance(value, list):
        items = [semantic_value(content) for content in value]
        if items and all(isinstance(v, dict) and "kind" in v for v in items):
            items.sort(key=json_text)
        return items
    return value


def retry_prompt(prompt: str, own: dict, other: dict) -> str:
    return (prompt + "\n\nONE NEUTRAL RETRY: Another reader answered " + json_text(other)
            + ". Your first answer was " + json_text(own)
            + ". Keep or change your answer after inspecting evidence. Neither reader is presumed correct. "
            "Cite specific source IDs in your reason. If changing an answer, explain what was wrong with it. "
            "Do not merely copy the other reader. Return the same JSON schema.")


def retry_pair(prompt: str, schema: dict, images: list[str], job: str, readers: dict, **kwargs) -> dict:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {reader: pool.submit(run_reader, reader,
                   retry_prompt(prompt, readers[reader].get("answer") or {}, readers[other].get("answer") or {}),
                   schema, images, job + ":retry", **kwargs)
                   for reader, other in (("claude", "codex"), ("codex", "claude"))}
        return {reader: future.result() for reader, future in futures.items()}


def set_concurrency(value: int) -> None:
    global _semaphore
    _semaphore = threading.Semaphore(max(1, min(8, value)))
