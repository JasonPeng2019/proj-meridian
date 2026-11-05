"""Remote-only scripted subprocess behavior; no provider/account/source claims.

From testing/: ../development/.venv/bin/python -B -m pytest -q -p no:cacheprovider
    --basetemp=tmp/A08-pytest tests/test_runner_m1.py
Every process is a synthetic Python peer, never Codex or Claude Code.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import pytest
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))

from backend.ai.runner import (  # noqa: E402
    _answer, _observed,
    CliReservation, EvidenceBundle, EvidenceError, EvidenceInput, JobDefinition,
    Runner, RunnerError, SerialQueue, with_field_validation,
)
from backend.contracts import (  # noqa: E402
    DeterminationRequest, PrepProvenance, PrepSourceIdentity, VerificationRequest,
    contract_digest, prep_counts,
)


LENGTH, WIDTH = "SYNTHETIC/template/length", "SYNTHETIC/template/width"
REFERENCES = {LENGTH: "SYNTHETIC/number/length", WIDTH: "SYNTHETIC/number/width"}
PEER = ROOT / "testing/fixtures/runner/scripted_cli.py"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=")
NOTE = "Invented runner fixture. No real drawing, model execution or engineering review."


def test_codex_progress_is_not_mistaken_for_the_final_json(workspace):
    answer = {"fields": {LENGTH: raw_field()}}
    messages = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Inspecting the attached evidence."}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}},
    ]
    final = workspace / "final.json"
    write(final, answer)
    assert _answer(messages, "determination", final) == answer
    assert _answer(messages, "determination", workspace / "missing.json") == answer
    messages[-1]["item"]["text"] = "Malformed final {"
    with pytest.raises(ValueError):
        _answer(messages, "determination", final)


def test_codex_final_event_must_match_its_last_message_file(workspace):
    answer = {"fields": {LENGTH: raw_field()}}
    final = workspace / "final.json"
    write(final, {"fields": {LENGTH: raw_field(9)}})
    with pytest.raises(ValueError, match="differ"):
        _answer([{"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}}],
                "determination", final)


def test_claude_local_error_marker_is_not_an_inference_model():
    events = [
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5", "fastMode": False},
        {"type": "assistant", "message": {"model": "<synthetic>", "content": [
            {"type": "text", "text": "SYNTHETIC fixture: OAuth authentication failed before inference."}]}},
        {"type": "result", "is_error": True},
    ]
    effective, observed = _observed(events, "verification")
    assert effective["model"] == observed["model"] == "claude-opus-5-5"
    assert observed["fastMode"] is False
    # A real, different model remains a conflict even on a failed run.
    events[1]["message"]["model"] = "claude-sonnet-5-5"
    effective, observed = _observed(events, "verification")
    assert effective is None
    assert observed["model"] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    # The sentinel is special only for an actual CLI error, never a success.
    events[1]["message"]["model"] = "<synthetic>"
    events[2]["is_error"] = False
    effective, observed = _observed(events, "verification")
    assert effective is None and "<synthetic>" in observed["model"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def raw_field(value=7, name=LENGTH, **updates):
    result = {"state": "known", "value": value, "options": [], "basis": None,
        "confidence": "sure", "source_ids": [REFERENCES[name]], "reason": NOTE}
    result.update(updates)
    return result


def determination(values=None, **step):
    return {"role": "determination", "answer": {"fields": {
        name: raw_field(value, name) for name, value in (values or {LENGTH: 7}).items()}}, **step}


def verification(verdicts=None, **step):
    return {"role": "verification", "answer": {"fields": {
        name: {"verdict": verdict, "reason": "Explicit synthetic evidence check only.",
               "source_ids": [REFERENCES[name]], "alternative": None}
        for name, verdict in (verdicts or {LENGTH: "verified"}).items()}}, **step}


def disagree(**updates):
    step = verification({LENGTH: "disagrees"}, **updates)
    step["answer"]["fields"][LENGTH]["alternative"] = raw_field(7)
    return step


class Budget:
    def __init__(self):
        self.active = 0
        self.entries = []
        self.lock = threading.Lock()

    @contextmanager
    def reserve(self):
        with self.lock:
            self.active += 1
            assert self.active == 1
            self.entries.append([time.time(), None])
            entry = self.entries[-1]
        try:
            yield CliReservation(total_cli_processes=4, owner_counted=True)
        finally:
            with self.lock:
                entry[1] = time.time()
                self.active -= 1


@pytest.fixture
def workspace():
    directory = ROOT / "testing/tmp/A08-detverify"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=directory) as temporary:
        yield Path(temporary)


class Case:
    def __init__(self, workspace, steps, values=None, images=0):
        self.path = workspace
        self.source_file = workspace / "synthetic-evidence.json"
        self.scenario_file = workspace / "scenario.json"
        self.runtime = workspace / "runtime"
        self.values = values or {LENGTH: 7}
        write(self.source_file, {"synthetic": True, "note": NOTE,
             "numbers": {REFERENCES[name]: value for name, value in self.values.items()}})
        self.bundle = EvidenceBundle(inputs={"typed-source": EvidenceInput(path=self.source_file)})
        for index in range(images):
            image = workspace / f"synthetic-{index}.png"
            image.write_bytes(PNG)
            self.bundle.inputs[f"image-{index}"] = EvidenceInput(path=image, image=True)
        self.budget = Budget()
        self.definition = JobDefinition(job="synthetic-template", determination_instructions=NOTE + " Determine.",
            verification_instructions=NOTE + " Verify supplied candidate against original evidence.",
            value_schemas={name: {"type": "number"} for name in self.values},
            evidence=lambda request: self.bundle, validate_candidate=self.validate,
            validation_version="synthetic-source-validator/v1")
        self.config = yaml.safe_load((ROOT / "development/ai_settings.yaml").read_text(encoding="utf-8"))["prep"]
        write(self.scenario_file, {"steps": steps, "calls": [], "active": 0})
        self.runner = self.make_runner()

    def validate(self, candidate, source):
        # This test callback actually reads the isolated original fixture.
        # Unknown/unsupported values are not declared evidence-valid by a model.
        source_values = read(self.source_file)["numbers"]
        validity = {}
        for name, item in candidate.fields.items():
            expected = source_values.get(REFERENCES[name])
            number_shape = isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
            shape = number_shape if item.state == "known" else item.state in {"unknown", "options"}
            supported = (item.state == "options" and item.options == expected) if isinstance(expected, list) else (
                item.state == "known" and item.value == expected)
            validity[name] = (shape, supported and item.source_ids == [REFERENCES[name]])
        return with_field_validation(candidate, validity)

    def source(self):
        return PrepSourceIdentity(inputs={key: item.sha256 for key, item in self.bundle.inputs.items()},
            source_ids={**{REFERENCES[name]: "typed-source" for name in self.values},
                        **{f"SYNTHETIC/image/{key}": key for key in self.bundle.inputs if key.startswith("image-")}})

    def request(self, job_id="synthetic-case"):
        return self.definition.request(job_id, self.source())

    def make_runner(self, **updates):
        arguments = dict(jobs={self.definition.job: self.definition}, prep_settings=self.config,
            workspace_root=ROOT, runtime_root=self.runtime, reserve_cli_slot=self.budget.reserve,
            executables={cli: [sys.executable, "-B", str(PEER), "--script-role", role, "--scenario", str(self.scenario_file)]
                         for cli, role in (("codex", "determination"), ("claude", "verification"))},
            environment={**os.environ, "OPENAI_API_KEY": "SYNTHETIC-DO-NOT-PASS", "ANTHROPIC_AUTH_TOKEN": "SYNTHETIC-DO-NOT-PASS",
                         "OPENAI_BASE_URL": "https://synthetic.invalid", "ANTHROPIC_BASE_URL": "https://synthetic.invalid",
                         "MERIDIAN_SECRETS_DIR": "SYNTHETIC-DO-NOT-PASS"},
            min_interval_seconds=0, rate_cooldown_seconds=0, timeout_seconds=5)
        arguments.update(updates)
        return Runner(**arguments)

    @property
    def calls(self):
        return read(self.scenario_file)["calls"]

    def receipts(self):
        return [read(path) for path in sorted(self.runtime.glob("runs/**/receipt.json"))]


def test_exact_order_candidate_original_evidence_null_and_partial_observations(workspace):
    case = Case(workspace, [determination(), verification()])
    record = case.runner(case.request())
    assert record.outcome == "first_pass_verified"
    assert [call["role"] for call in case.calls] == ["determination", "verification"]
    sol, opus = record.rounds[0].determination, record.rounds[0].verification
    assert case.calls[1]["prompt"]["candidate"] == sol.output.model_dump(mode="json")
    assert case.calls[1]["prompt"]["original_evidence"] == case.calls[0]["prompt"]["original_evidence"]
    assert json.loads(case.calls[1]["prompt"]["original_evidence"]["typed-source"]["content"])["numbers"][REFERENCES[LENGTH]] == 7
    assert sol.effective is None
    assert opus.effective.model == "claude-opus-5-5"
    assert opus.effective.reasoning is None and opus.effective.provider is None
    assert opus.effective.read_only is None and opus.effective.service_tier == "standard"
    assert sol.cache.settings_basis == opus.cache.settings_basis == "requested"
    assert sol.cache.effective_sha256 is None
    assert opus.cache.effective_sha256 == contract_digest(opus.effective)
    assert opus.output.candidate_sha256 == sol.output.candidate_sha256
    assert case.calls[1]["start"] >= case.calls[0]["end"]
    assert case.budget.active == 0 and len(case.budget.entries) == 2
    for call, reservation in zip(case.calls, case.budget.entries):
        assert reservation[0] <= call["start"] <= call["end"] <= reservation[1]
        field = call["schema"]["properties"]["fields"]["properties"][LENGTH]
        assert call["schema"]["$defs"]["SourceId"]["enum"] == [REFERENCES[LENGTH]]
        assert field["properties"]["source_ids"]["items"] == {"$ref": "#/$defs/SourceId"}
        if call["role"] == "verification":
            alternative = field["properties"]["alternative"]["anyOf"][0]
            assert alternative["properties"]["source_ids"]["items"] == {"$ref": "#/$defs/SourceId"}
        assert "candidate_sha256" not in call["schema"]["properties"]
        assert "evidence_valid" not in field["properties"]
    assert all(item["actual_cli_invocations"] == 1 for item in case.receipts())
    assert any(item["usage"].get("total_cost_usd") == 0.001 for item in case.receipts())
    assert all("SYNTHETIC-DO-NOT-PASS" not in path.read_text(encoding="utf-8")
               for path in case.runtime.rglob("*.json"))
    assert PrepProvenance.model_validate_json((case.runner.last_run_dir / "result.json").read_bytes()) == record


def test_claude_synthetic_oauth_message_retains_execution_failure_and_unverified_sol(workspace):
    case = Case(workspace, [determination(), verification(action="oauth_synthetic")])
    record = case.runner(case.request())
    opus = record.rounds[0].verification
    assert opus.status == "execution_failed" and opus.failure.classification == "oauth"
    assert opus.failure.execution_failure and opus.failure.exit_code == 1
    assert record.mode == "single_model_unverified" and record.outcome == "unverified_fallback"
    assert record.field_results[LENGTH].accepted.value == 7
    assert record.field_results[LENGTH].status == "unverified_fallback"
    assert [call["role"] for call in case.calls] == ["determination", "verification"]
    assert record.next_launch_attempt_opus is True


def test_one_disagreement_correction_and_reverification_with_mixed_field_counts(workspace):
    first_verifier = verification({LENGTH: "disagrees", WIDTH: "verified"})
    first_verifier["answer"]["fields"][LENGTH]["alternative"] = raw_field(7)
    case = Case(workspace, [determination({LENGTH: 9, WIDTH: 2}), first_verifier,
        determination({LENGTH: 7, WIDTH: 2}), verification({LENGTH: "verified", WIDTH: "verified"})],
        values={LENGTH: 7, WIDTH: 2})
    record = case.runner(case.request())
    assert record.outcome == "retry_verified" and len(record.rounds) == 2
    assert [call["role"] for call in case.calls] == ["determination", "verification"] * 2
    first, second = record.rounds
    assert case.calls[2]["prompt"]["previous_candidate"] == first.determination.output.model_dump(mode="json")
    assert case.calls[2]["prompt"]["verifier_feedback"] == first.verification.output.model_dump(mode="json")
    assert case.calls[3]["prompt"]["candidate"] == second.determination.output.model_dump(mode="json")
    assert second.determination.cache.feedback_sha256 == first.verification.output.verification_sha256
    assert record.field_results[LENGTH].accepted.value == 7
    assert record.field_results[LENGTH].status == "retry_verified"
    assert record.field_results[WIDTH].status == "first_pass_verified"
    counts = prep_counts([record])
    assert (counts.first_pass_verified, counts.retry_verified, counts.unverified_fallback) == (1, 1, 0)


@pytest.mark.parametrize("last_step", [disagree(), verification({LENGTH: "unsure"}), verification(action="oauth"), verification(action="malformed")])
def test_remaining_disagreement_unsure_invalid_or_execution_failure_never_falls_back(workspace, last_step):
    case = Case(workspace, [determination({LENGTH: 9}), disagree(), determination(), last_step])
    record = case.runner(case.request())
    assert len(record.rounds) == 2 and len(case.calls) == 4
    assert record.mode == "determine_verify" and record.outcome == "unresolved"
    assert record.field_results[LENGTH].accepted is None
    assert record.rounds[0].verification.output.fields[LENGTH].alternative.value == 7
    assert prep_counts([record]).unverified_fallback == 0


@pytest.mark.parametrize("action", ["malformed", "blind_guess", "exit_after_answer"])
def test_invalid_or_blind_verifier_output_is_terminal_not_fallback(workspace, action):
    case = Case(workspace, [determination(), verification(action=action)])
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and len(record.rounds) == 1
    assert record.rounds[0].verification.status == "invalid_output"
    assert record.rounds[0].verification.failure.execution_failure is False
    assert record.field_results[LENGTH].accepted is None and len(case.calls) == 2


@pytest.mark.parametrize("mutation", ["missing", "extra", "foreign_ref", "empty_reason", "echoed_hash"])
def test_explicit_complete_cited_verdicts_required(workspace, mutation):
    verifier = verification()
    fields = verifier["answer"]["fields"]
    if mutation == "missing":
        fields.clear()
    elif mutation == "extra":
        fields[WIDTH] = fields[LENGTH].copy()
    elif mutation == "foreign_ref":
        fields[LENGTH]["source_ids"] = ["SYNTHETIC/NOT-AN-ORIGINAL-ID"]
    elif mutation == "empty_reason":
        fields[LENGTH]["reason"] = "   "
    else:
        verifier["answer"]["candidate_sha256"] = "0" * 64
    case = Case(workspace, [determination(), verifier])
    record = case.runner(case.request())
    assert record.outcome == "unresolved"
    assert record.rounds[0].verification.status == "invalid_output"
    assert not record.rounds[0].verification.failure.execution_failure


@pytest.mark.parametrize("kind", ["unknown", "unsure", "unsupported"])
def test_only_sure_valid_source_backed_candidates_can_fall_back(workspace, kind):
    sol = determination({LENGTH: 91 if kind == "unsupported" else 7})
    if kind == "unknown":
        sol["answer"]["fields"][LENGTH].update(state="unknown", value=None, confidence="unsure")
    elif kind == "unsure":
        sol["answer"]["fields"][LENGTH]["confidence"] = "unsure"
    case = Case(workspace, [sol, verification(action="oauth")])
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.mode == "determine_verify"
    assert record.field_results[LENGTH].accepted is None
    assert prep_counts([record]).unverified_fallback == 0


@pytest.mark.parametrize("invalid", ["host_flags", "foreign_ref", "manufactured_options"])
def test_invalid_determination_never_reaches_opus(workspace, invalid):
    sol = determination()
    field = sol["answer"]["fields"][LENGTH]
    if invalid == "host_flags":
        field.update(schema_valid=True, evidence_valid=True)
    elif invalid == "foreign_ref":
        field["source_ids"] = ["SYNTHETIC/FOREIGN"]
    else:
        field.update(state="options", value=None, options=[7, 9], basis=None)
    case = Case(workspace, [sol])
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.rounds[0].verification is None
    assert record.rounds[0].determination.status == "invalid_output"
    assert len(case.calls) == 1


def test_validator_cannot_repair_or_replace_model_values(workspace):
    case = Case(workspace, [determination()])
    def repair(candidate, source):
        candidate.fields[LENGTH].value = 8
        return candidate
    case.definition = replace(case.definition, validate_candidate=repair)
    case.runner = case.make_runner()
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.rounds[0].verification is None
    assert record.rounds[0].determination.failure.classification == "evidence_invalid"


def test_real_execution_failure_is_unverified_and_next_launch_retries_opus(workspace):
    case = Case(workspace, [determination(), verification(action="oauth"), verification()])
    job = case.request()
    first = case.runner(job)
    assert first.mode == "single_model_unverified" and first.outcome == "unverified_fallback"
    assert first.next_launch_attempt_opus is True
    assert first.rounds[0].verification.output is None
    assert first.rounds[0].verification.failure.troubleshooting
    assert first.rounds[0].verification.failure.diagnostic_sha256
    counts = prep_counts([first])
    assert (counts.first_pass_verified, counts.retry_verified, counts.unverified_fallback, counts.execution_failed_attempts) == (0, 0, 1, 1)
    second = case.runner(job)
    assert second.outcome == "first_pass_verified" and second.mode == "determine_verify"
    assert [call["role"] for call in case.calls] == ["determination", "verification", "verification"]
    assert case.calls[2]["prompt"]["candidate"] == first.rounds[0].determination.output.model_dump(mode="json")
    assert any(receipt["kind"] == "cache_reuse" for receipt in case.receipts())
    assert second.rounds[0].determination.started_at == first.rounds[0].determination.started_at
    # The failed round remains retained, not overwritten by later success.
    retained = [read(path) for path in case.runtime.glob("runs/*/result.json")]
    assert {item["mode"] for item in retained} == {"determine_verify", "single_model_unverified"}


def test_rate_limit_sets_shared_cooldown_without_an_automatic_retry(workspace):
    case = Case(workspace, [determination(), verification(action="rate_limit"), verification()])
    case.runner = case.make_runner(rate_cooldown_seconds=0.05, min_interval_seconds=0.01)
    first = case.runner(case.request())
    assert first.outcome == "unverified_fallback" and len(case.calls) == 2
    deadline = read(case.runtime / "rate.json")["verification"]
    second = case.runner(case.request())
    assert second.outcome == "first_pass_verified" and len(case.calls) == 3
    assert case.calls[-1]["start"] >= deadline


def test_determiner_execution_failure_does_not_invent_a_verifier(workspace):
    case = Case(workspace, [determination(action="network")])
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.rounds[0].verification is None
    assert record.rounds[0].determination.status == "execution_failed" and len(case.calls) == 1


def test_changed_source_before_job_is_unresolved_without_any_subprocess(workspace):
    case = Case(workspace, [])
    job = case.request()
    case.source_file.write_text("SYNTHETIC CHANGED EVIDENCE", encoding="utf-8")
    record = case.runner(job)
    assert record.outcome == "unresolved" and case.calls == []
    assert not case.budget.entries


def test_changed_source_during_stage_is_not_published_or_cached(workspace):
    case = Case(workspace, [determination(), verification(action="mutate_source", source_path=str(workspace / "synthetic-evidence.json"))])
    with pytest.raises(EvidenceError, match="changed"):
        case.runner(case.request())
    assert not list(case.runtime.glob("cache/objects/**/*.json"))
    assert not (case.runner.last_run_dir / "result.json").exists()


def test_successful_cache_reuse_retains_original_timings_and_makes_no_calls(workspace):
    case = Case(workspace, [determination(), verification()])
    job = case.request()
    first = case.runner(job)
    second = case.runner(job)
    assert second == first and len(case.calls) == 2
    assert len(case.budget.entries) == 2
    reused = [receipt for receipt in case.receipts() if receipt["kind"] == "cache_reuse"]
    assert len(reused) == 2 and all(item["actual_cli_invocations"] == 0 for item in reused)


def test_source_fingerprint_change_invalidates_both_stages(workspace):
    case = Case(workspace, [determination(), verification(), determination({LENGTH: 8}), verification()])
    first = case.runner(case.request())
    source = read(case.source_file)
    source["numbers"][REFERENCES[LENGTH]] = 8
    write(case.source_file, source)
    second = case.runner(case.request())
    assert second.outcome == "first_pass_verified" and len(case.calls) == 4
    assert first.source != second.source
    assert first.rounds[0].verification.candidate_sha256 != second.rounds[0].verification.candidate_sha256


@pytest.mark.parametrize("change", ["prompt", "validation_version", "value_schema", "command_settings"])
def test_prompt_schema_validation_and_model_command_settings_invalidate_cache(workspace, change):
    case = Case(workspace, [determination(), verification(), determination(), verification()])
    old_request = case.request()
    case.runner(old_request)
    if change == "prompt":
        case.definition = replace(case.definition, determination_instructions=NOTE + " New instructions.")
    elif change == "validation_version":
        case.definition = replace(case.definition, validation_version="synthetic-source-validator/v2")
    elif change == "value_schema":
        case.definition = replace(case.definition, value_schemas={LENGTH: {"type": "integer"}})
    else:
        case.config["readers"]["sol"]["command"]["environment_template"] = {"NO_COLOR": "1"}
    case.runner = case.make_runner()
    if change != "command_settings":
        with pytest.raises(RunnerError, match="fresh request"):
            case.runner(old_request)
    assert case.runner(case.request()).outcome == "first_pass_verified"
    assert len(case.calls) == 4


def test_stale_verifier_candidate_cache_rejected_even_with_recomputed_content_hash(workspace):
    case = Case(workspace, [determination(), verification(), verification()])
    job = case.request()
    first = case.runner(job)
    for path in case.runtime.glob("cache/objects/**/*.json"):
        data = read(path)
        if data["attempt"]["role"] == "verification":
            output = data["attempt"]["output"]
            output["candidate_sha256"] = "0" * 64
            output["verification_sha256"] = contract_digest({key: value for key, value in output.items() if key != "verification_sha256"})
            data.pop("content_sha256")
            data["content_sha256"] = contract_digest(data)
            write(path, data)
    second = case.runner(job)
    assert second.outcome == "first_pass_verified" and len(case.calls) == 3
    assert second.rounds[0].verification.candidate_sha256 == first.rounds[0].determination.output.candidate_sha256


def test_history_blind_reader_cache_is_ignored(workspace):
    case = Case(workspace, [determination(), verification()])
    historical = case.runtime / "cache/old-blind-reader.json"
    historical.parent.mkdir(parents=True)
    write(historical, {"mode": "dual_reader", "agreed": True, "value": 7})
    before = historical.read_bytes()
    assert case.runner(case.request()).outcome == "first_pass_verified"
    assert len(case.calls) == 2 and historical.read_bytes() == before


def test_frozen_determiner_verifier_callback_signatures(workspace):
    case = Case(workspace, [determination(), verification()])
    job = case.request()
    sol = case.runner.determine(DeterminationRequest(job=job, round=1))
    opus = case.runner.verify(VerificationRequest(job=job, round=1, candidate=sol.output))
    assert sol.role == "determination" and opus.role == "verification"
    assert opus.output.candidate_sha256 == sol.output.candidate_sha256


@pytest.mark.parametrize("lease", [CliReservation(5, True), CliReservation(3, False), CliReservation(3, True, 2)])
def test_resource_refusal_never_becomes_execution_fallback(workspace, lease):
    case = Case(workspace, [])
    @contextmanager
    def refused():
        yield lease
    case.runner = case.make_runner(reserve_cli_slot=refused)
    with pytest.raises(RunnerError, match="reservation"):
        case.runner(case.request())
    assert case.calls == []


def test_two_owners_share_one_serial_prep_queue(workspace):
    case = Case(workspace, [determination(sleep=0.02), verification(), determination(), verification()])
    second = case.make_runner()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(owner, case.request(str(index))) for index, owner in enumerate((case.runner, second))]
        records = [future.result(timeout=15) for future in futures]
    assert all(record.outcome == "first_pass_verified" for record in records)
    assert [call["role"] for call in case.calls] == ["determination", "verification"] * 2
    assert all(left["end"] <= right["start"] for left, right in zip(case.calls, case.calls[1:]))
    assert case.budget.active == 0


@pytest.mark.parametrize("role", ["determination", "verification"])
def test_progress_and_empty_final_file_do_not_mask_execution_timeout(workspace, role):
    steps = ([determination(action="timeout_progress")] if role == "determination" else
             [determination(), verification(action="timeout_progress")])
    case = Case(workspace, steps)
    case.runner = case.make_runner(timeout_seconds=0.5)
    record = case.runner(case.request())
    attempt = getattr(record.rounds[0], role)
    assert attempt.status == "execution_failed"
    assert attempt.failure.classification == "timeout" and attempt.output is None
    assert record.outcome == ("unresolved" if role == "determination" else "unverified_fallback")
    assert case.budget.active == 0
    receipt = next(item for item in case.receipts() if item.get("role") == role)
    assert receipt["timed_out"] and not receipt["transport"]["candidate_emitted"]
    assert receipt["transport"]["stdout_bytes"] > 0


def test_timeout_kills_owned_child_and_releases_slot_with_truthful_fallback(workspace):
    case = Case(workspace, [determination(), verification(sleep=2)])
    case.runner = case.make_runner(timeout_seconds=0.5)
    record = case.runner(case.request())
    assert record.outcome == "unverified_fallback"
    assert record.rounds[0].verification.failure.classification == "timeout"
    assert case.budget.active == 0
    timed_out = next(item for item in case.receipts() if item["role"] == "verification")
    assert timed_out["timed_out"] and timed_out["process_started"]
    if os.name != "nt":
        with pytest.raises(ProcessLookupError):
            os.kill(timed_out["child_pid"], 0)


@pytest.mark.parametrize("images", [1, 2])
def test_both_stages_receive_all_original_image_bytes(workspace, images):
    case = Case(workspace, [determination(), verification()], images=images)
    record = case.runner(case.request())
    assert record.outcome == "first_pass_verified"
    assert len(case.calls[0]["images"]) == images
    assert all(value == case.bundle.inputs["image-0"].sha256 for value in case.calls[0]["images"])
    assert case.calls[0]["prompt"]["original_evidence"] == case.calls[1]["prompt"]["original_evidence"]


@pytest.mark.parametrize("action", ["skip_image_read", "wrong_image"])
def test_image_paths_or_wrong_image_bytes_are_not_evidence_delivery(workspace, action):
    case = Case(workspace, [determination(), verification(action=action)], images=1)
    record = case.runner(case.request())
    assert record.outcome == "unresolved"
    assert record.rounds[0].verification.failure.classification == "evidence_invalid"
    assert record.field_results[LENGTH].accepted is None


@pytest.mark.parametrize("role,observed", [
    ("determination", {"model": "SYNTHETIC-WRONG-MODEL"}),
    ("determination", {"reasoning_effort": "high"}),
    ("determination", {"sandbox": "workspace-write"}),
    ("verification", {"model": "claude-opus-5-5", "effortLevel": "high"}),
    ("verification", {"model": "claude-opus-5-5", "fastMode": True}),
    ("verification", {"model": "claude-opus-5-5", "fallbackModel": ["SYNTHETIC-WRONG-MODEL"]}),
])
def test_reported_setting_conflicts_remain_visible_and_unresolved(workspace, role, observed):
    steps = [determination(observed=observed)] if role == "determination" else [determination(), verification(observed=observed)]
    case = Case(workspace, steps)
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.mode == "determine_verify"
    attempt = record.rounds[0].determination if role == "determination" else record.rounds[0].verification
    assert attempt.status == "invalid_output" and not attempt.failure.execution_failure
    receipt = next(item for item in case.receipts() if item["role"] == role)
    assert receipt["observed"]


def test_only_actual_printed_alternatives_can_be_verified(workspace):
    sol = determination()
    sol["answer"]["fields"][LENGTH].update(state="options", value=None, options=[7, 9], basis="printed_alternatives")
    case = Case(workspace, [sol, verification()], values={LENGTH: [7, 9]})
    record = case.runner(case.request())
    assert record.outcome == "first_pass_verified"
    assert record.field_results[LENGTH].accepted.options == [7, 9]


def test_output_limit_is_invalid_not_fallback(workspace):
    case = Case(workspace, [determination(), verification(action="output_limit")])
    case.runner = case.make_runner(max_output_bytes=2048)
    record = case.runner(case.request())
    assert record.outcome == "unresolved"
    assert record.rounds[0].verification.status == "invalid_output"


def test_disallowed_model_and_pipeline_settings_fail_before_launch(workspace):
    case = Case(workspace, [])
    case.config["readers"]["sol"]["reasoning_effort"] = "high"
    with pytest.raises(ValueError):
        case.make_runner()
    case.config["readers"]["sol"]["reasoning_effort"] = "max"
    case.config["pipeline"]["version"] = "dual-reader/v0"
    with pytest.raises(RunnerError):
        case.make_runner()
    assert not case.calls


def test_queue_serializes_separate_python_owner_processes(workspace):
    script = ROOT / "testing/fixtures/runner/queue_probe.py"
    log = workspace / "queue-events.jsonl"
    command = [sys.executable, "-B", str(script), str(workspace / "queue.lock"), str(log)]
    children = [subprocess.Popen(command, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0, (stdout, stderr)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["start", "end", "start", "end"]
    assert events[0]["pid"] == events[1]["pid"] != events[2]["pid"] == events[3]["pid"]


@pytest.mark.parametrize("mutation", ["pipeline", "role", "settings_basis", "effective_sha256", "requested", "source"])
def test_cache_identity_cannot_promote_old_roles_or_fabricated_observations(workspace, mutation):
    case = Case(workspace, [determination(), verification(), verification()])
    job = case.request()
    case.runner(job)
    for path in case.runtime.glob("cache/objects/**/*.json"):
        data = read(path)
        if data["attempt"]["role"] != "verification":
            continue
        cache = data["attempt"]["cache"]
        if mutation == "pipeline":
            cache["pipeline_version"] = "dual-reader/v0"
        elif mutation == "role":
            cache["role"] = "determination"
        elif mutation == "settings_basis":
            cache["settings_basis"] = "confirmed"
        elif mutation == "effective_sha256":
            cache["effective_sha256"] = "0" * 64
        elif mutation == "requested":
            cache["settings"]["reasoning"] = "high"
        else:
            cache["source_sha256"] = "0" * 64
        data.pop("content_sha256")
        data["content_sha256"] = contract_digest(data)
        write(path, data)
    record = case.runner(job)
    assert record.outcome == "first_pass_verified" and len(case.calls) == 3


def test_missing_opus_executable_records_actual_launch_failure(workspace):
    case = Case(workspace, [determination()])
    original = case.runner.executables
    case.runner = case.make_runner(executables={**original, "claude": [str(workspace / "missing-native-claude")]})
    record = case.runner(case.request())
    assert record.outcome == "unverified_fallback"
    assert record.rounds[0].verification.failure.classification == "missing_cli"
    assert record.rounds[0].verification.effective is None
    receipt = next(item for item in case.receipts() if item["role"] == "verification")
    assert receipt["actual_cli_invocations"] == 1 and receipt["process_started"] is False


def test_cli_homes_and_runtime_cannot_write_outside_owned_split(workspace):
    case = Case(workspace, [])
    with pytest.raises(RunnerError, match="inside workspace"):
        case.make_runner(cli_homes={"codex": ROOT.parent / "UNOWNED-CODEX-HOME"})
    with pytest.raises(RunnerError, match="inside workspace"):
        case.make_runner(runtime_root=ROOT.parent / "UNOWNED-RUNTIME")
    assert case.calls == []


def test_disagreement_emitted_before_failed_exit_is_retained_not_fallback(workspace):
    case = Case(workspace, [determination({LENGTH: 9}), disagree(action="exit_after_answer")])
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.mode == "determine_verify"
    assert len(record.rounds) == 1 and len(case.calls) == 2
    opus = record.rounds[0].verification
    assert opus.status == "invalid_output" and not opus.failure.execution_failure
    assert opus.output.fields[LENGTH].verdict == "disagrees"
    assert opus.output.fields[LENGTH].alternative.value == 7
    assert record.field_results[LENGTH].accepted is None


def test_unsupported_domain_validation_remains_unresolved(workspace):
    case = Case(workspace, [determination()])
    def unsupported(candidate, source):
        raise NotImplementedError("Synthetic unsupported validation")
    case.definition = replace(case.definition, validate_candidate=unsupported)
    case.runner = case.make_runner()
    record = case.runner(case.request())
    assert record.outcome == "unresolved" and record.rounds[0].verification is None
    assert record.rounds[0].determination.failure.classification == "evidence_invalid"
    assert "unsupported" in record.rounds[0].determination.failure.message


def test_diagnostics_do_not_publish_raw_provider_credentials_or_paths(workspace):
    marker = "SYNTHETIC-PRIVATE-DIAGNOSTIC-MARKER"
    case = Case(workspace, [determination(), verification(action="oauth", stderr="OAuth token=" + marker)])
    record = case.runner(case.request())
    assert record.outcome == "unverified_fallback"
    assert record.rounds[0].verification.failure.diagnostic_sha256
    assert all(marker not in path.read_text(encoding="utf-8") for path in case.runtime.rglob("*.json"))


def test_batch_counts_keep_fallback_out_of_verified_buckets(workspace):
    case = Case(workspace, [determination(), verification(), determination(), verification(action="oauth")])
    batch = case.runner.run_many([case.request("first"), case.request("second")])
    assert batch.counts.model_dump() == {"count_unit": "field", "total_fields": 2,
        "first_pass_verified": 1, "retry_verified": 0, "unresolved": 0,
        "unverified_fallback": 1, "execution_failed_attempts": 1}


def test_standalone_verifier_revalidates_candidate_instead_of_trusting_flags(workspace):
    case = Case(workspace, [determination({LENGTH: 9})])
    job = case.request()
    sol = case.runner.determine(DeterminationRequest(job=job, round=1))
    forged = with_field_validation(sol.output, {LENGTH: (True, True)})
    opus = case.runner.verify(VerificationRequest(job=job, round=1, candidate=forged))
    assert opus.status == "invalid_output" and not opus.failure.execution_failure
    assert len(case.calls) == 1


def test_partial_source_support_keeps_fallback_and_unresolved_field_counts_separate(workspace):
    case = Case(workspace, [determination({LENGTH: 7, WIDTH: 99}),
        verification({LENGTH: "verified", WIDTH: "unsure"}, action="oauth")], values={LENGTH: 7, WIDTH: 2})
    record = case.runner(case.request())
    assert record.mode == "single_model_unverified" and record.outcome == "unresolved"
    assert record.field_results[LENGTH].status == "unverified_fallback"
    assert record.field_results[WIDTH].status == "unresolved"
    assert record.field_results[WIDTH].accepted is None
    counts = prep_counts([record])
    assert (counts.total_fields, counts.first_pass_verified, counts.retry_verified,
            counts.unverified_fallback, counts.unresolved) == (2, 0, 0, 1, 1)


def test_rendered_arguments_cannot_silently_diverge_from_declared_pins(workspace):
    case = Case(workspace, [])
    argv = case.config["readers"]["sol"]["command"]["argv_template"]
    argv[argv.index("model_reasoning_effort={reasoning_effort}")] = "model_reasoning_effort=high"
    case.runner = case.make_runner()
    with pytest.raises(RunnerError, match="overrides"):
        case.runner(case.request())
    assert not case.calls and not case.budget.entries
