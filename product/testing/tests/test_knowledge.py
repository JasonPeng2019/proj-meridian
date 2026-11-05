"""PLAN V1 integration additions; run remotely with test/prep extras.

Module suites retain the detailed extraction/prep/decision matrices. These
synthetic cases cross saved M11 -> M12 -> M14 boundaries. Only the external
reader executables are scripted; no resolver/assembly/decision code is replaced.
"""
import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from test_source_runtime import MARKERS, ROOT, source_bundle
from test_prepare_m1 import drawing
from test_vision_jobs_m1 import known, unknown, sol, opus, runner
from backend import contracts as c
from backend.ai import prepare, vision_jobs
from backend.ai.matching import LINKS_REF
from backend.app.tools import FactTools
from backend.loader.decisions import DecisionStore
from backend.loader.records import RecordRegistry, RecordsError, read_records
from scripts import check_milestone as milestone


PART = "D-001/part"
TITLE = "D-001/drawing/title"
MATERIAL = "D-001/drawing/material"
HUMAN = "Synthetic milestone reviewer (automated test only)"


@pytest.fixture
def workspace(monkeypatch):
    for name in ("MERIDIAN_INPUTS_PATH", "MERIDIAN_TEST_INPUTS_PATH", "MERIDIAN_CHAT_HISTORY_DIR",
                 "MERIDIAN_SECRETS_DIR", "MERIDIAN_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    directory = ROOT / "testing/tmp/milestone-integration"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=directory) as path:
        yield Path(path)


def persisted_runtime(workspace, monkeypatch):
    """Reuse fixture producers plus the real subprocess transport and publisher.

    The PDF is explicitly inert synthetic bytes. Scripted readings exercise
    provenance/flow, never optical correctness or any actual engineering value.
    """
    inputs, manifest = source_bundle(workspace, bom_material="Synthetic family")
    payload = json.loads(inputs.read_text("utf-8"))
    original = c.DrawingEvidence.model_validate(payload["drawings"][0])
    scanned = drawing(workspace, scan=True).model_copy(update={"source_sha256": original.source_sha256})
    payload["drawings"] = [scanned.model_dump(mode="json")]
    inputs.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    # from_paths checks this original's real byte hash, independently of the
    # manifest/extraction metadata. Nothing touches the production source tree.
    pdf = workspace / scanned.source_path
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes((manifest.parent.parent / scanned.source_path).read_bytes())
    job = vision_jobs.build_scan_job(scanned, image_root=workspace, crop_dir=workspace / "runtime/corner-crops")
    values = {TITLE: "SYNTHETIC Bracket", MATERIAL: "Alloy X"}
    fields = {name: known(values[name], [name]) if name in values else unknown([name])
              for name in job.request.field_names}
    steps = [sol(fields), opus(fields)]
    row = c.BOMRow.model_validate(payload["bom"][0])
    # Explicit synthetic provider answers, in the mandated material/section
    # order. Production M10 validates references and builds these actual jobs.
    for kind, source, target, refs, relation in (
        ("material", "Alloy X", "Synthetic family", [MATERIAL, row.fields["material"].name], "kind_of"),
        ("section", "Synthetic Cell", "Synthetic Cell", ["D-001/source", row.fields["section"].name], "same"),
    ):
        mapping = {c.mapping_name(kind, source, target): known(
            {"relationship": relation, "to_name": target}, [LINKS_REF, *refs], state="relationship")}
        steps += [sol(mapping), opus(mapping)]
    # The existing subprocess peer asserts these fakes never reach either CLI
    # environment and checks requested model/effort/processing/image settings.
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-M23-DO-NOT-PASS")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "SYNTHETIC-M23-DO-NOT-PASS")
    external, scenario = runner(workspace, job, steps)
    sources = [inputs, manifest, pdf, workspace / scanned.image,
               manifest.parent / "context/openlpbf-bom.csv"]
    originals = {path: path.read_bytes() for path in sources}
    prepared = prepare.prepare(inputs, manifest=manifest, output=workspace / "prepared.json",
                               runner=external, image_root=workspace)
    data = prepared.model_dump(mode="json")
    data["batch"].update(MARKERS)  # Explicit fixture attribution, never real AI/human credit.
    prepared = prepare.PreparedKnowledge.model_validate(data)
    (workspace / "prepared.json").write_text(prepared.model_dump_json(), encoding="utf-8")
    assert {path: path.read_bytes() for path in sources} == originals
    store = DecisionStore(workspace / "decisions", allow_synthetic=True)
    registry = reload_registry(workspace, store)
    registry.save()
    return registry, store, prepared, json.loads(scenario.read_text("utf-8"))


def reload_registry(workspace, store):
    return RecordRegistry.from_paths(prepared_path=workspace / "prepared.json", inputs_path=workspace / "inputs.json",
        records_path=workspace / "generated/records.json", decisions=store,
        manifest_path=workspace / "source/dataset/manifest.json")


def test_saved_external_prep_reaches_effective_records_and_unapproved_facts(workspace, monkeypatch):
    registry, store, saved, scenario = persisted_runtime(workspace, monkeypatch)
    assert not saved.source_only and len(saved.batch.records) == 3
    assert saved.batch.counts.model_dump() == dict(count_unit="field", total_fields=10, first_pass_verified=4,
        retry_verified=0, unresolved=6, unverified_fallback=0, execution_failed_attempts=0)
    calls = scenario["calls"]
    assert [call["role"] for call in calls] == ["determination", "verification"] * 3
    assert all(call["credential_environment_clean"] for call in calls)
    for offset, record in zip(range(0, 6, 2), saved.batch.records):
        determined = record.rounds[0].determination
        verified = record.rounds[0].verification
        assert calls[offset + 1]["prompt"]["candidate"] == determined.output.model_dump(mode="json")
        assert calls[offset + 1]["prompt"]["original_evidence"] == calls[offset]["prompt"]["original_evidence"]
        assert verified.output.candidate_sha256 == determined.output.candidate_sha256
        assert verified.output.source_sha256 == determined.output.source_sha256
        assert (determined.requested.model, determined.requested.reasoning, determined.requested.service_tier) == (
            "gpt-6.1-sol", "max", "fast")
        assert (verified.requested.model, verified.requested.reasoning, verified.requested.service_tier) == (
            "claude-opus-5-5", "xhigh", "regular")
        assert calls[offset + 1]["start"] >= calls[offset]["end"]
    field = registry.part_for(PART).drawing.fields["title"]
    assert field.original is None and field.value == "SYNTHETIC Bracket" and field.correction is None
    assert registry.part_for(PART).drawing.source_sha256 == hashlib.sha256(
        (workspace / "dataset/drawings/D-001.pdf").read_bytes()).hexdigest()
    assert registry.part_for(PART).link.bom_rows == ["BOM:synthetic-cell/synthetic-bracket"]
    assert registry.approved_mappings == [] and all(item.status == "pending" for item in registry.review_items)
    tools = FactTools(registry)
    assert tools.get_facts(PART).facts[TITLE].display.value == "SYNTHETIC Bracket"
    material = tools.get_facts(PART).facts[MATERIAL]
    assert material.display.state == "undetermined" and material.display.reason == "unmapped_names"
    scan_source = next(source for source in material.sources if source.name == MATERIAL)
    assert scan_source.says is None  # The raw unreadable original is never replaced by AI text.
    assert scan_source.provenance.rounds[0].determination.output.fields[MATERIAL].value == "Alloy X"
    assert any(source.says == "Synthetic family" for source in material.sources)
    assert tools.parts_with_material("Synthetic family").parts == []
    assert read_records(workspace / "generated/records.json").prepared == saved
    again = reload_registry(workspace, DecisionStore(store.directory, allow_synthetic=True))
    assert FactTools(again).get_facts(PART) == tools.get_facts(PART)
    assert all(store.history(mapping.name) == [] for mapping in saved.mappings)


def test_saved_prep_rejects_source_changes_without_overwriting_effective_snapshot(workspace, monkeypatch):
    registry, store, _, _ = persisted_runtime(workspace, monkeypatch)
    output = workspace / "generated/records.json"
    before = output.read_bytes()
    source = workspace / "dataset/drawings/D-001.pdf"
    source.write_bytes(source.read_bytes() + b"\nSynthetic source revision, deliberately not re-extracted.")
    with pytest.raises(RecordsError):
        registry()
    with pytest.raises(RecordsError):
        reload_registry(workspace, store)
    assert output.read_bytes() == before
    assert list(store.directory.glob("*.json")) == []


@pytest.mark.parametrize("exit_code,case,expected", [
    (0, "<testcase classname='test_example' name='ok'/>", "PASS"),
    (1, "<testcase classname='test_example' name='bad'><failure/></testcase>", "FAIL"),
    (0, "<testcase classname='test_example' name='skip'><skipped/></testcase>", "SKIPPED"),
    (5, "", "MISSING"),
    (0, "<testcase classname='test_other' name='ok'/>", "MISSING"),
])
def test_runner_reads_actual_junit_outcomes(workspace, exit_code, case, expected):
    path = workspace / "report.xml"
    path.write_text("<testsuites><testsuite>" + case + "</testsuite></testsuites>", encoding="utf-8")
    assert milestone.pytest_result(path, ("testing/tests/test_example.py",), exit_code)["outcome"] == expected


@pytest.mark.parametrize("outcome,expected_code", [("PASS", 0), ("FAIL", 1), ("MISSING", 1), ("SKIPPED", 2)])
def test_runner_cumulative_exit_and_later_pending(workspace, monkeypatch, outcome, expected_code):
    invoked = []

    def scripted_check(check, directory):
        invoked.append(check.name)
        return {"name": check.name, "gate": check.gate, "kind": "software", "required": True,
                "outcome": outcome, "reason": "Synthetic runner orchestration test only."}

    monkeypatch.setattr(milestone, "run_check", scripted_check)
    report, code = milestone.qualify("V2", workspace / "reports")
    assert invoked == ["launch", "contracts", "knowledge", "core", "geometry"]
    assert code == expected_code
    later = [check for check in report["checks"] if check["name"] in {"V3_software", "V4_software", "V5_software"}]
    assert len(later) == 3 and all(check["outcome"] == "PENDING" and not check["required"] for check in later)
    assert report["outcome"] != "PASS"
    assert any(check["name"] == "final20_benchmark" and check["outcome"] == "PENDING" for check in report["checks"])
    if outcome == "PASS":
        _, future_code = milestone.qualify("V3", workspace / "future")
        assert future_code == 2


def test_missing_required_file_and_local_cad_cannot_launch_or_pass(workspace, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(milestone.subprocess, "run", lambda *a, **kw: pytest.fail("Must not launch a missing/local-CAD suite"))
    absent = milestone.Check("absent", "V1", ("testing/tests/M23-deliberately-absent.py",))
    assert milestone.run_check(absent, workspace)["outcome"] == "MISSING"
    cad = next(check for check in milestone.CHECKS if check.name == "geometry")
    assert milestone.run_check(cad, workspace)["outcome"] == "SKIPPED"
