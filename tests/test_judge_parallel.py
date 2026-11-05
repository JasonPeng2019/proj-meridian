"""Bounded meaning-judge scheduling with mocked readers, never provider calls."""
import json
import threading
import time

import pytest

from backend.ai import runner
from backend.evaluation.benchmark import JUDGE
from scripts import judge_benchmark as judge


def payload(index):
    return {"cache_key": f"{index:064x}", "judge": dict(JUDGE), "chat_model": "gpt-6-luna", "case_id": f"Q{index:02d}"}


def response(valid=True, reason="Exact original judge reason"):
    return {"valid": valid, "answer": {"score": 2, "unsupported_claims": [], "reason": reason},
            "cache_key": "reader-cache", "latency_ms": 7, "cache_hit": False, "metadata": {"unchanged": True}}


@pytest.fixture
def mocked(monkeypatch, tmp_path):
    thresholds, concurrency = [], []
    monkeypatch.setattr(judge, "wait_for_headroom", lambda min_free_gb=3: thresholds.append(min_free_gb))
    monkeypatch.setattr(runner, "set_concurrency", lambda workers: concurrency.append(workers))
    monkeypatch.setattr(runner, "CACHE", tmp_path / "mock-reader-cache")
    return thresholds, concurrency


def test_distinct_content_keys_run_in_parallel_but_duplicates_never_overlap(tmp_path, monkeypatch, mocked):
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active, calls = set(), []
    peak = 0

    def read(reader, prompt, schema, images, job):
        nonlocal peak
        current = json.loads(prompt.removeprefix(judge.PROMPT))
        key = current["cache_key"]
        with lock:
            assert key not in active
            active.add(key)
            calls.append(key)
            peak = max(peak, len(active))
        assert reader == "claude" and images == [] and schema == judge.SCHEMA
        assert current["judge"] == JUDGE
        barrier.wait(timeout=5)
        with lock:
            active.remove(key)
        return response()

    monkeypatch.setattr(runner, "run_reader", read)
    output = tmp_path / "results.jsonl"
    assert judge.judge_payloads([payload(1), payload(1), payload(2), payload(2)], output, workers=2) == 2
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert peak == 2 and len(calls) == len(set(calls)) == 2
    assert {row["cache_key"] for row in rows} == {payload(1)["cache_key"], payload(2)["cache_key"]}
    assert all(row["score"] == 2 and row["reason"] == "Exact original judge reason" for row in rows)
    assert mocked == ([3.35, 3.35], [2])


def test_every_spawn_has_serial_resource_admission_with_worker_adjusted_ram(tmp_path, monkeypatch, mocked):
    lock = threading.Lock()
    admissions = peak = 0
    thresholds = []

    def headroom(min_free_gb=3):
        nonlocal admissions, peak
        with lock:
            admissions += 1
            peak = max(peak, admissions)
            thresholds.append(min_free_gb)
        time.sleep(0.01)
        with lock:
            admissions -= 1

    monkeypatch.setattr(judge, "wait_for_headroom", headroom)
    monkeypatch.setattr(runner, "run_reader", lambda *args: response())
    assert judge.judge_payloads([payload(index) for index in range(1, 10)], tmp_path / "results.jsonl", workers=8) == 9
    assert peak == 1 and thresholds == [pytest.approx(5.45)] * 9
    assert mocked[1] == [8]


def test_cached_valid_results_reuse_and_invalid_results_retry_append_only(tmp_path, monkeypatch, mocked):
    output = tmp_path / "results.jsonl"
    original = "".join(json.dumps({"cache_key": payload(index)["cache_key"], "valid": index == 1}) + "\n" for index in (1, 2))
    output.write_text(original, encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "run_reader", lambda *args: calls.append(args) or response())
    assert judge.judge_payloads([payload(1), payload(2)], output, workers=2) == 1
    updated = output.read_text(encoding="utf-8")
    assert updated.startswith(original)
    rows = [json.loads(line) for line in updated.splitlines()]
    assert len(rows) == 3 and rows[-1]["cache_key"] == payload(2)["cache_key"] and rows[-1]["valid"]
    assert len(calls) == len(mocked[0]) == 1


def test_duplicate_invalid_key_retries_serially_until_valid_then_reuses_cache(tmp_path, monkeypatch, mocked):
    calls = []
    answers = iter([response(False), response(True)])
    monkeypatch.setattr(runner, "run_reader", lambda *args: calls.append(args) or next(answers))
    output = tmp_path / "results.jsonl"
    assert judge.judge_payloads([payload(1)] * 3, output, workers=4) == 2
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["valid"] for row in rows] == [False, True]
    assert len(calls) == 2


def test_default_single_worker_preserves_original_input_order_and_limit(tmp_path, monkeypatch, mocked):
    calls = []

    def read(reader, prompt, *args):
        current = json.loads(prompt.removeprefix(judge.PROMPT))
        calls.append(current["case_id"])
        return response(False)

    monkeypatch.setattr(runner, "run_reader", read)
    assert judge.judge_payloads([payload(1), payload(2), payload(1)], tmp_path / "results.jsonl", limit=2) == 2
    assert calls == ["Q01", "Q02"] and mocked == ([3, 3], [1])


def test_concurrent_result_writes_are_complete_json_lines_with_original_prefix(tmp_path, monkeypatch, mocked):
    output = tmp_path / "results.jsonl"
    prefix = json.dumps({"cache_key": payload(99)["cache_key"], "valid": True}) + "\n"
    output.write_text(prefix, encoding="utf-8")
    monkeypatch.setattr(runner, "run_reader", lambda *args: response(reason="Retained reason " * 2000))
    assert judge.judge_payloads([payload(index) for index in range(1, 25)], output, workers=8) == 24
    text = output.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert text.startswith(prefix) and len(rows) == 25
    assert len({row["cache_key"] for row in rows}) == 25
    assert all(row.get("reason") == "Retained reason " * 2000 for row in rows[1:])


@pytest.mark.parametrize("workers", [0, 9, -1, True, "2"])
def test_invalid_worker_limits_are_rejected_without_reader_calls(tmp_path, monkeypatch, workers):
    monkeypatch.setattr(runner, "run_reader", lambda *args: pytest.fail("Invalid worker count spawned a reader"))
    with pytest.raises(ValueError, match="one to eight"):
        judge.judge_payloads([payload(1)], tmp_path / "results.jsonl", workers=workers)


def test_reader_failure_propagates_without_inventing_a_judgment(tmp_path, monkeypatch, mocked):
    def fail(*args):
        raise RuntimeError("Original reader failure")

    monkeypatch.setattr(runner, "run_reader", fail)
    output = tmp_path / "results.jsonl"
    with pytest.raises(RuntimeError, match="Original reader failure"):
        judge.judge_payloads([payload(1)], output, workers=1)
    assert not output.exists()
