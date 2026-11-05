"""Synthetic subprocess peer for remote runner tests; never invokes an AI CLI.

All answers and model metadata here are explicitly scripted test fixtures.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def write(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


parser = argparse.ArgumentParser()
parser.add_argument("--script-role", required=True)
parser.add_argument("--scenario", required=True)
options, argv = parser.parse_known_args()
role = options.script_role
scenario_path = Path(options.scenario)
scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
prompt = json.loads(sys.stdin.read())
index = len(scenario["calls"])
if index >= len(scenario["steps"]):
    raise SystemExit("Unexpected extra synthetic subprocess invocation")
step = scenario["steps"][index]
assert step["role"] == role == prompt["role"], "Stage order differs from the scripted requirement"
expected_model = "gpt-6.1-sol" if role == "determination" else "claude-opus-5-5"
assert argv[argv.index("--model") + 1] == expected_model
assert ("--image" in argv) == (role == "determination" and any("image_file" in item for item in prompt["original_evidence"].values()))
assert not any(name.upper().endswith(("API_KEY", "API_KEYS", "AUTH_TOKEN")) for name in os.environ)
assert os.environ.get("OPENAI_BASE_URL") is None
assert os.environ.get("ANTHROPIC_BASE_URL") is None
assert os.environ.get("MERIDIAN_SECRETS_DIR") is None
assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
workspace = scenario_path.parent.resolve()
for name in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CACHE_HOME"):
    assert Path(os.environ[name]).resolve().is_relative_to(workspace)
if role == "determination":
    assert "read-only" in argv
    assert "model_reasoning_effort=max" in argv
    assert "service_tier=fast" in argv
else:
    assert argv[argv.index("--effort") + 1] == "xhigh"
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text(encoding="utf-8"))
    assert settings["fastMode"] is False and settings["fallbackModel"] == []
    assert settings["disableAllHooks"] is True
    assert os.environ["CLAUDE_CODE_DISABLE_FAST_MODE"] == "1"
    assert "--bare" not in argv
active = scenario.get("active", 0) + 1
assert active == 1, "Prep subprocesses overlapped"
scenario["active"] = active
call = {"role": role, "round": prompt["round"], "pid": os.getpid(), "start": time.time(),
        "prompt": prompt, "schema": json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        if role == "determination" else json.loads(argv[argv.index("--json-schema") + 1]),
        "images": [], "credential_environment_clean": True}
for position, argument in enumerate(argv[:-1]):
    if argument == "--image":
        call["images"].append(hashlib.sha256(Path(argv[position + 1]).read_bytes()).hexdigest())
scenario["calls"].append(call)
write(scenario_path, scenario)
time.sleep(step.get("sleep", 0))
action = step.get("action", "success")
if action == "mutate_source":
    Path(step["source_path"]).write_text("SYNTHETIC MUTATION", encoding="utf-8")
if action == "timeout_progress":
    if role == "determination":
        Path(argv[argv.index("--output-last-message") + 1]).write_text("", encoding="utf-8")
        emit({"type": "thread.started", "thread_id": "SYNTHETIC-PROGRESS-NOT-A-CANDIDATE"})
        emit({"type": "item.completed", "item": {"type": "agent_message", "phase": "commentary",
            "text": "SYNTHETIC progress only; no final answer has been emitted."}})
    else:
        emit({"type": "system", "subtype": "init", "model": expected_model})
        emit({"type": "assistant", "message": {"model": expected_model, "content": [
            {"type": "text", "text": "SYNTHETIC progress only; no verdict has been emitted."}]}})
    time.sleep(2)
    exit_code = 0
elif action == "oauth_synthetic":
    emit({"type": "system", "subtype": "init", "model": expected_model, "fastMode": False})
    emit({"type": "assistant", "message": {"model": "<synthetic>", "content": [
        {"type": "text", "text": "SYNTHETIC OAuth authentication failure before inference"}]}})
    emit({"type": "result", "is_error": True, "structured_output": None,
          "errors": ["SYNTHETIC OAuth authentication failure"]})
    exit_code = 1
elif action in {"oauth", "rate_limit", "invocation", "network"}:
    messages = {"oauth": "Synthetic OAuth authentication failure", "rate_limit": "Synthetic rate limit 429",
                "invocation": "Synthetic unknown option", "network": "Synthetic network connection reset"}
    print(step.get("stderr", messages[action]), file=sys.stderr)
    exit_code = 7
elif action == "malformed":
    if role == "determination":
        Path(argv[argv.index("--output-last-message") + 1]).write_text("{ definitely not JSON", encoding="utf-8")
        emit({"type": "turn.completed"})
    else:
        emit({"type": "result", "structured_output": "{ not an object", "is_error": False})
    exit_code = 0
elif action == "output_limit":
    print("X" * 10000)
    exit_code = 0
else:
    answer = step["answer"]
    if action == "blind_guess":
        answer = {"fields": {name: {key: value for key, value in item.items() if key not in {"schema_valid", "evidence_valid"}}
                             for name, item in prompt["candidate"]["fields"].items()}}
    if role == "determination":
        if step.get("observed"):
            emit({"type": "session_meta", "payload": step["observed"]})
        emit({"type": "thread.started", "thread_id": "SYNTHETIC-NOT-A-REAL-CLI"})
        emit({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}})
        Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps(answer), encoding="utf-8")
        emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    else:
        observed = step.get("observed", {"model": expected_model})
        emit({"type": "system", "subtype": "init", **observed})
        emit({"type": "assistant", "message": {"model": observed.get("model", expected_model), "content": []}})
        if action != "skip_image_read":
            for number, item in enumerate(prompt["original_evidence"].values()):
                if "image_file" in item:
                    identifier = "synthetic-read-" + str(number)
                    emit({"type": "assistant", "message": {"model": expected_model, "content": [{"type": "tool_use", "id": identifier,
                        "name": "Read", "input": {"file_path": item["image_file"]}}]}})
                    image = Path(item["image_file"]).read_bytes()
                    if action == "wrong_image":
                        image = b"SYNTHETIC WRONG IMAGE"
                    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": identifier,
                        "content": [{"type": "image", "source": {"type": "base64", "data": base64.b64encode(image).decode("ascii")}}]}]}})
        emit({"type": "assistant", "message": {"model": observed.get("model", expected_model), "content": [
            {"type": "tool_use", "name": "StructuredOutput", "input": answer}]}})
        emit({"type": "result", "is_error": False, "structured_output": answer,
            "usage": {"input_tokens": 6, "output_tokens": 4, "service_tier": "standard", "speed": "standard"},
            "total_cost_usd": 0.001, "fast_mode_state": "off"})
    exit_code = 9 if action == "exit_after_answer" else 0
scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
scenario["calls"][index]["end"] = time.time()
scenario["active"] -= 1
write(scenario_path, scenario)
raise SystemExit(exit_code)
