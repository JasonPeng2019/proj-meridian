"""Focused B00 smoke checks only. Never inspect the real secrets directory."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
from contextlib import redirect_stderr
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "development"))


def reader_templates() -> None:
    """Static YAML/record comparison only; never format or execute a reader."""
    from backend.settings import load_settings

    data = load_settings().data
    report = ROOT / "testing/reports/qualification/A08-runner/qualification.json"
    qualification = json.loads(report.read_text(encoding="utf-8"))
    attempts = {attempt["id"]: attempt for attempt in qualification["attempts"]}
    replacements = {
        "sol": {
            "gpt-6.1-sol": "{model}",
            "model_reasoning_effort=max": "model_reasoning_effort={reasoning_effort}",
            "service_tier=fast": "service_tier={service_tier}",
            "fixture.png": "{image}",
            "schema.json": "{output_schema_file}",
            "sol-2.last-message.json": "{last_message_file}",
        },
        "opus": {
            "claude-opus-5-5": "{model}",
            "xhigh": "{effort}",
            "claude-settings.json": "{claude_settings_file}",
        },
    }
    for reader, attempt_id, executable in (("sol", "sol-2", "codex"), ("opus", "opus-1", "claude")):
        command = data["prep"]["readers"][reader]["command"]
        reference = command["qualification"]
        assert reference["report"] == report.relative_to(ROOT).as_posix()
        assert (ROOT / reference["notes"]).is_file()
        assert reference["commit"] == "0e66458" and reference["attempt"] == attempt_id
        assert reference["scope"] == "synthetic_image_cli_capability_only"
        assert reference["limitations"]
        assert command["prompt_transport"] == "stdin"
        expected = [executable]
        previous = ""
        for argument in attempts[attempt_id]["argv"][1:]:
            if argument.startswith('sqlite_home='):
                value = 'sqlite_home="{codex_state_dir}"'
            elif argument.startswith('log_dir='):
                value = 'log_dir="{codex_log_dir}"'
            elif previous == "--json-schema":
                value = "{output_schema_json}"
            else:
                value = replacements[reader].get(argument, argument)
            expected.append(value)
            previous = argument
        assert command["argv_template"] == expected, reader
        # Check the complete command metadata, not just standalone path arguments.
        payload = json.dumps(command)
        assert not re.search(r"(?:[A-Za-z]:[\\/]|sk-[A-Za-z0-9_-]{16,}|https?://)", payload)
        for argument in command["argv_template"]:
            assert isinstance(argument, str)
            assert not Path(argument).is_absolute() and not PureWindowsPath(argument).is_absolute()
        assert not any("model_providers.openai" in arg or arg == "--bare" for arg in expected)
    opus = data["prep"]["readers"]["opus"]["command"]
    assert opus["prompt_image"] == "{image}"
    expected_settings = dict(qualification["claude_process_settings"]["value"])
    expected_settings.update(model="{model}", effortLevel="{effort}")
    assert opus["settings_template"] == expected_settings
    for name, value in opus["environment_template"].items():
        assert qualification["execution_environment"]["overrides"][name] == value
    print("PASS: YAML reader templates match sol-2/opus-1 flags; stdin, placeholders, no absolute paths/key-like literals")


def launch_settings() -> None:
    """Remote-only behavior checks use isolated history paths and no server/key."""
    from backend.settings import load_settings
    from backend.launcher import main

    settings = load_settings()
    assert settings.data["ui"] == {"debug_enabled": False, "debug_env": "MERIDIAN_DEBUG"}
    with patch.dict(os.environ):
        os.environ.pop("MERIDIAN_DEBUG", None)
        os.environ.pop("MERIDIAN_CHAT_HISTORY_DIR", None)
        assert not settings.debug_enabled
        assert settings.chat_history_dir == ROOT / "development/chat_history"
        # Path resolution only: no actual user history is opened or created.
        os.environ["MERIDIAN_CHAT_HISTORY_DIR"] = "../testing/tmp/A01-scaffold/chat_history"
        assert settings.chat_history_dir == ROOT / "testing/tmp/A01-scaffold/chat_history"
        for value, expected in (("0", False), ("1", True), ("true", False)):
            os.environ["MERIDIAN_DEBUG"] = value
            assert settings.debug_enabled is expected
        for flag, environment, expected in (("--debug", "0", True), ("--no-debug", "1", False)):
            os.environ["MERIDIAN_DEBUG"] = environment
            with patch.object(sys, "argv", ["meridian", flag]), patch(
                "backend.launcher.importlib.util.find_spec", return_value=None
            ), redirect_stderr(io.StringIO()):
                assert main() == 1
            assert settings.debug_enabled is expected
    ignored = subprocess.check_output(
        ["git", "check-ignore", "--no-index", "development/chat_history/probe.json"], cwd=ROOT,
    ).decode().strip()
    assert ignored == "development/chat_history/probe.json"
    print("PASS: Debug default/env/flag precedence and isolated history path; native Git excludes private history")


def configuration() -> None:
    from backend.settings import load_settings, prep_cli_environment

    temporary_root = ROOT / "testing/tmp/A01-scaffold"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root) as empty_secrets:
        # The real configured location is never inspected, even with stat().
        os.environ["MERIDIAN_SECRETS_DIR"] = empty_secrets
        settings = load_settings()
        assert settings.secrets_dir == Path(empty_secrets).resolve()
        assert settings.chat_key_path.name == "OpenAI_API_Keys.txt"
        assert not settings.chat_key_present
        assert settings.chat_unavailable_reason.startswith("Chat unavailable:")
        data = settings.data
        assert data["chat"]["provider"] == "openai"
        assert data["chat"]["api"] == "responses"
        assert data["chat"]["model"] == "gpt-6-luna"
        assert data["chat"]["fallback_models"] == []
        assert data["reviewer_name"] == "Jason Peng"
        assert data["prep"]["max_concurrent_jobs"] == 1
        assert data["prep"]["reserved_reader_slots"] == 2
        assert data["prep"]["max_cli_processes"] == 4
        pipeline = data["prep"]["pipeline"]
        assert pipeline["version"] == "determine-verify/v1"
        assert pipeline["execution"] == "sequential"
        assert pipeline["stages"] == [
            {"role": "determiner", "reader": "sol"},
            {"role": "verifier", "reader": "opus"},
        ]
        assert pipeline["verifier_input"] == "exact_candidate_and_original_evidence"
        assert pipeline["require_candidate_source_binding"]
        assert pipeline["require_per_field_verdict_reason_evidence"]
        assert pipeline["max_disagreement_retries"] == 1
        assert pipeline["retain_all_rounds"]
        assert pipeline["unresolved_states"] == ["disagrees", "unsure", "invalid"]
        sol = data["prep"]["readers"]["sol"]
        opus = data["prep"]["readers"]["opus"]
        assert (sol["model"], sol["reasoning_effort"], sol["service_tier"]) == (
            "gpt-6.1-sol", "max", "fast"
        )
        assert (opus["model"], opus["effort"], opus["fastMode"], opus["fallbackModel"]) == (
            "claude-opus-5-5", "xhigh", False, []
        )
        assert sol["read_only"] and opus["read_only"]
        failure = data["prep"]["opus_execution_failure"]
        assert failure["action"] == "continue_sol_only"
        assert failure["provenance"] == "single_model_unverified"
        assert failure["debug_label"] == "UNVERIFIED"
        assert failure["retain_failed_attempt"]
        assert failure["require_valid_source_backed_candidate"]
        assert failure["eligible_only_after_invocation_troubleshooting"]
        assert not failure["eligible_after_disagreement_or_invalid_output"]
        assert failure["retry_opus_on_each_launch"]
        assert not failure["count_as_verified"]
        assert data["prep"]["authentication"] == "cli_accounts_only"
        assert not data["prep"]["pass_app_key_to_cli"]
        for name in ("evidence_root", "dataset", "attribution", "license"):
            assert settings.path(name).exists(), name
        isolated = prep_cli_environment({"OPENAI_API_KEY": "fake-smoke-value", "PATH": "retained"})
        assert isolated == {"PATH": "retained"}
    print("PASS: empty temporary secrets directory; chat unavailable; exact configuration; CLI key isolation")


def runtime_import() -> None:
    for module in ("backend", "backend.settings", "backend.launcher", "backend.app", "backend.ai", "backend.loader", "backend.cad"):
        importlib.import_module(module)
    assert not any(name == "cadquery" or name.startswith("cadquery.") for name in sys.modules)
    print("PASS: runtime imports do not load CadQuery; no CLI or Node subprocess invoked")


def inputs_unchanged() -> None:
    entries = subprocess.check_output(
        ["git", "ls-files", "-s", "-z", "--", "development/inputs"], cwd=ROOT
    ).decode("utf-8").split("\0")
    inventory = []
    for entry in filter(None, entries):
        metadata, name = entry.split("\t", 1)
        expected = metadata.split()[1]
        payload = (ROOT / name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        assert actual == expected, name
        inventory.append(f"{name}\0{expected}\n")
    assert inventory
    print(f"PASS: {len(inventory)} input files byte-identical to Git blobs; inventory SHA256="
          + hashlib.sha256("".join(inventory).encode()).hexdigest())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates-only", action="store_true", help="YAML/qualified argv inspection only")
    args = parser.parse_args()
    reader_templates()
    if not args.templates_only:
        launch_settings()
        configuration()
        runtime_import()
        inputs_unchanged()
