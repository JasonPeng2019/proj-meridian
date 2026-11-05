"""No real CLI agents: check process limits and large-input transport with stubs."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from backend.ai import runner


def test_claude_large_prompts_use_stdin_and_reader_concurrency_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CACHE", tmp_path)
    monkeypatch.setattr(runner, "bootstrap_auth", lambda: None)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "claude-stub")
    monkeypatch.setattr(runner, "_semaphore", threading.Semaphore(1))
    runner.set_concurrency(99)
    lock = threading.Lock()
    active = peak = 0

    def fake_run(argv, **kwargs):
        nonlocal active, peak
        assert len(kwargs["input"]) > 100_000
        assert all(len(arg) < 10_000 for arg in argv)
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.03)
        with lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout=json.dumps({"structured_output": {"ok": True}}), stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(runner.run_reader, "claude", "evidence " + str(i) + "x" * 110_000, schema, [], str(i)) for i in range(12)]
        assert all(f.result()["valid"] for f in futures)
    assert 1 < peak <= 8
