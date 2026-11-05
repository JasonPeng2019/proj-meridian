"""Focused B00 smoke checks only. Never inspect the real secrets directory."""

from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "development"))


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
        sol = data["prep"]["readers"]["sol"]
        opus = data["prep"]["readers"]["opus"]
        assert (sol["model"], sol["reasoning_effort"], sol["service_tier"]) == (
            "gpt-6.1-sol", "max", "fast"
        )
        assert (opus["model"], opus["effort"], opus["fastMode"], opus["fallbackModel"]) == (
            "claude-opus-5-5", "xhigh", False, []
        )
        assert sol["read_only"] and opus["read_only"]
        assert all(reader["command"]["qualification"] == "pending_A08" for reader in (sol, opus))
        failure = data["prep"]["opus_execution_failure"]
        assert failure["action"] == "continue_sol_only"
        assert failure["provenance"] == "single_model_fallback"
        assert failure["retry_opus_on_each_launch"]
        assert not failure["count_as_dual_reader_agreement"]
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
    assert importlib.util.find_spec("cadquery") is None
    print("PASS: runtime imports without CadQuery imported or installed; no CLI or Node subprocess invoked")


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
    configuration()
    runtime_import()
    inputs_unchanged()
