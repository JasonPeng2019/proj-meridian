"""M14 resolver tests using isolated explicit synthetic source/mapping fixtures.

Remote only; no API/model execution, extraction, CAD, real correction or review.
"""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from test_source_runtime import MARKERS, NOTE, ROOT, source_bundle, workspace
from backend import contracts as c
from backend.app.tools import FactTools
from backend.loader.records import RecordRegistry


class SyntheticMappings:
    """Test boundary supplying already-approved fixture mappings to M14.

    M12's durable hash/current-decision checks remain the real registry's job;
    these fixtures test resolver direction/meaning without inventing AI jobs.
    """
    def __init__(self, registry, mappings):
        self.registry, self.mappings = registry, mappings

    def __getattr__(self, name):
        return getattr(self.registry, name)

    @property
    def approved_mappings(self):
        return self.mappings


def mapping(source, target, relationship):
    return c.NameMapping(**MARKERS, name=c.mapping_name("material", source, target), kind="material",
        from_name=source, to_name=target, relationship=relationship,
        evidence="general_engineering_knowledge", evidence_note=NOTE, method="human_decision",
        review=c.ReviewState(status="human_confirmed", by="Synthetic test reviewer", at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                             based_on={"synthetic-source": "1" * 64}, decision_id="synthetic-mapping"))


def tools_for(workspace, *, mappings=(), **kwargs):
    inputs, manifest = source_bundle(workspace, **kwargs)
    registry = RecordRegistry.from_inputs(inputs, manifest)
    return FactTools(SyntheticMappings(registry, list(mappings)) if mappings else registry)


def material(tools):
    return tools.get_facts("D-001/part").facts["D-001/drawing/material"]


@pytest.mark.parametrize("drawing,bom,confidence,expected,rule", [
    ("Synthetic X", "Synthetic X", "sure", "Synthetic X", "rule 2"),
    ("Unreadable synthetic text", "Synthetic Y", "unsure", "Synthetic Y", "rule 1"),
    (None, "Synthetic Y", "sure", "Synthetic Y", "rule 1"),
])
def test_b3_equal_and_sole_trusted_sources_preserve_both_originals(workspace, drawing, bom, confidence, expected, rule):
    tools = tools_for(workspace, drawing_material=drawing, bom_material=bom, drawing_confidence=confidence)
    fact = material(tools)
    assert fact.display.state == "value" and fact.display.value == expected
    assert rule in fact.rule
    assert {source.target.kind for source in fact.sources} == {"drawing", "bom"}
    assert drawing in [source.says for source in fact.sources]
    assert tools.resolve_facts(tools.registry.records[0]) == tools.get_facts("D-001/part").facts
    assert fact.review is None


@pytest.mark.parametrize("relationship,expected_state,expected_reason", [
    (None, "undetermined", "unmapped_names"),
    ("different", "undetermined", "source_conflict"),
    ("same", "value", None),
    ("kind_of", "value", None),
])
def test_b3_approved_mapping_relationships_and_unmapped_conflicts(workspace, relationship, expected_state, expected_reason):
    maps = [mapping("Synthetic grade X", "Synthetic family", relationship)] if relationship else []
    tools = tools_for(workspace, drawing_material="Synthetic grade X", bom_material="Synthetic family", mappings=maps)
    fact = material(tools)
    assert fact.display.state == expected_state
    if expected_reason:
        assert fact.display.reason == expected_reason
        assert "Synthetic grade X" in fact.display.message and "Synthetic family" in fact.display.message
        assert tools.parts_with_material("Synthetic family").parts == []
    else:
        assert fact.display.value == "Synthetic grade X"
        assert any(source.name == maps[0].name for source in fact.sources)


def test_material_family_search_is_directional(workspace):
    tools = tools_for(workspace, drawing_material=None, bom_material="Synthetic family",
                      mappings=[mapping("Synthetic grade X", "Synthetic family", "kind_of")])
    assert len(tools.parts_with_material("Synthetic family").parts) == 1
    assert tools.parts_with_material("Synthetic grade X").parts == []


def test_b3_material_list_keeps_recorded_meaning_and_refines_compatible_item(workspace):
    tools = tools_for(workspace, drawing_material="Synthetic grade X", bom_material="Synthetic family,Synthetic elastomer",
                      mappings=[mapping("Synthetic grade X", "Synthetic family", "kind_of")])
    fact = material(tools)
    assert fact.display.value == ["Synthetic grade X", "Synthetic elastomer"]
    assert fact.display.label == "Materials recorded:"
    assert len(tools.parts_with_material("Synthetic elastomer").parts) == 1
    assert len(tools.parts_with_material("Synthetic family").parts) == 1
    assert "composition or variant meaning is unspecified" in fact.rule


def test_unreadable_material_and_unlabelled_measurements_never_gain_guessed_values(workspace):
    tools = tools_for(workspace, drawing_material="Unreadable synthetic text", bom_material="", drawing_confidence="unsure")
    fact = material(tools)
    assert fact.display.state == "undetermined" and fact.display.reason == "unsure_source"
    dimensions = tools.get_facts("D-001/part").facts["D-001/drawing/dimensions"]
    assert dimensions.display.state == "undetermined" and dimensions.display.reason == "unlabelled_measurement"
    assert "4" in dimensions.display.message
    assert any(source.target.box == (20, 20, 4, 4) for source in dimensions.sources)


def test_find_part_returns_whole_part_fact_with_drawing_target_and_no_context_leak(workspace):
    tools = tools_for(workspace)
    found = tools.find_part("D-001")
    assert found.unique_part_id == "D-001/part" and len(found.parts) == 1
    assert found.facts[found.unique_part_id].sources[0].target.drawing_id == "D-001"
    assert tools.find_part("Synthetic bracket").unique_part_id == found.unique_part_id
    assert tools.find_part("BOM-001").unique_part_id == found.unique_part_id
    assert tools.find_part("Absent synthetic part").parts == []
    assert tools.find_part("Absent synthetic part").unique_part_id is None
    assert found.parts[0].thumbnail.startswith("/api/parts/")
    assert tools.get_connections(found.unique_part_id).message == "No connections recorded."


@pytest.mark.parametrize("text", ["drawing D-001", "part D-001", "Show D-001/part"])
def test_find_part_recognizes_complete_drawing_ids_in_normal_tool_queries(workspace, text):
    tools = tools_for(workspace)
    result = tools.find_part(text)
    assert result.unique_part_id == "D-001/part"
    assert [part.id for part in result.parts] == ["D-001/part"]
    assert result.facts["D-001/part"].sources[0].target.drawing_id == "D-001"
    assert tools.find_part("drawing D-0019").parts == []
    assert tools.find_part("drawing D-999").parts == []


def test_machine_summary_keeps_drawing_and_bom_sections_separate_and_counts_actual_sources(workspace):
    tools = tools_for(workspace)
    result = tools.machine_summary()
    assert result.record_count == result.drawing_count == result.bom_row_count == 1
    assert result.drawing_sections[0].member_ids == ["D-001"]
    assert result.bom_sections[0].member_ids == ["BOM:synthetic-cell/synthetic-bracket"]
    assert result.drawing_sections[0].section == result.bom_sections[0].section == "Synthetic Cell"
    assert result.drawing_sections[0].fact != result.bom_sections[0].fact
    assert all(fact.fact == name for name, fact in result.facts.items())
    assert len(tools.parts_in_section("Synthetic Cell").parts) == 1


def test_cost_summary_uses_decimal_source_totals_and_never_fills_missing_costs(workspace):
    rows = [
        {"Name": "Synthetic bracket", "Part family": "Synthetic Cell", "Type": "Custom", "Datasheet": "SyntheticBracket.pdf",
         "Cost": "DKK0.10", "Amount": "2", "Total cost": "DKK0.20"},
        {"Name": "Synthetic item 2", "Part family": "Synthetic Cell", "Cost": "DKK0.10", "Amount": "1", "Total cost": "DKK0.10"},
        {"Name": "Synthetic missing cost", "Part family": "Synthetic Cell", "Cost": "", "Amount": "1", "Total cost": "DKK0.00"},
        {"Name": "Synthetic missing amount", "Part family": "Synthetic Cell", "Cost": "DKK1.00", "Amount": "", "Total cost": "DKK0.00"},
    ]
    tools = tools_for(workspace, rows=rows)
    result = tools.cost_summary()
    assert result.recorded_total == "0.30" and result.recorded_total_count == 2
    assert result.missing_total_count == 2 and result.row_count == 4
    assert {group.reason: group.count for group in result.missing_reasons} == {"missing_unit_cost": 1, "missing_amount": 1}
    assert result.snapshot_note and result.facts[result.fact].snapshot_note
    assert "may be out of date" in result.caveat and "complete machine cost is undetermined" in result.caveat
    assert result.records_sha256 == tools.machine_summary().records_sha256


def test_correction_tool_requires_real_callback_and_only_delegates_pending_result(workspace):
    tools = tools_for(workspace)
    with pytest.raises(NotImplementedError, match="Review proposal service"):
        tools.propose_correction("D-001/drawing/material", "Synthetic revision", "Synthetic evidence reason")
    expected = c.ProposeCorrectionResult.model_validate_json((ROOT / "testing/fixtures/contracts/proposal-result.json").read_bytes())
    calls = []
    def callback(request):
        calls.append(request)
        return expected
    hooked = FactTools(tools.registry, propose_correction=callback)
    assert hooked.propose_correction("D-001/drawing/material", "Synthetic revision", "Synthetic reason") == expected
    assert calls == [c.ProposeCorrectionRequest(fact_id="D-001/drawing/material", new_value="Synthetic revision", reason="Synthetic reason")]
    assert material(tools).display.value == "Synthetic polymer"
