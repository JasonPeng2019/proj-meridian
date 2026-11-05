"""Source-derived summaries use isolated records, never benchmark answer fixtures."""
import json

import pytest

from backend.app.chat import collect_evidence, validate_markers
from backend.app.store import Store
from backend.app.tools import KnowledgeTools


def field(name, value, **extra):
    return {"name": name, "value": value, "original": value, "confidence": "sure", "method": "parsed", **extra}


@pytest.fixture
def summary_store(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    rows = []
    for key, price, quantity, total, currency in [
        ("a", .1, 3, .3, "DKK"), ("b", 2, None, None, "DKK"),
        ("c", None, 2, None, "DKK"), ("d", None, None, None, "DKK"),
        ("e", 5, 2, 10, "EUR"), ("f", 5, 2, 9, "DKK"),
    ]:
        name = "BOM:optics/" + key
        values = {"name": key.upper(), "part_family": "Optics", "material": "Aluminium", "amount": quantity,
                  "cost": {"amount": price, "currency": currency} if price is not None else None,
                  "total_cost": {"amount": total, "currency": currency} if total is not None else None}
        rows.append({"name": name, "display_name": key.upper(), "section": "Optics", "sha256": key,
                     "source_path": "fixture/bom.csv", "source_row": len(rows) + 2,
                     "fields": {k: field(name + "/" + k, v) for k, v in values.items()}})
    records = []
    for number, section, material in [(1, "Optical", "7075-T6, Plate (SS)"), (2, "Optics", "Aluminium")]:
        did = f"D-{number:03d}"
        callouts = [field(did + "/drawing/callout/hole", "3 x M4 THRU", feature="threaded_hole", count=3, thread="M4", through=True),
                    field(did + "/drawing/callout/slot", "2 x 4 X 8 THRU ALL", feature="slot", count=2, width_mm=4, length_mm=8, through=True)]
        records.append({"id": did + "/part", "key": did, "display_name": "Plate " + str(number), "section": section,
                        "has_drawing": True, "has_3d": False, "bom": [rows[0]], "link": {"method": "exact_match"},
                        "drawing": {"id": did, "section": section, "source_path": "fixture/" + did + ".pdf", "source_filename": did + ".pdf", "sha256": did,
                                    "fields": {"material": field(did + "/drawing/material", material)},
                                    "numbers": [field(did + "/drawing/n/42", 42)], "callouts": callouts}})
    for row in rows[1:]:
        records.append({"id": row["name"] + "/part", "key": row["name"], "display_name": row["display_name"],
                        "section": row["section"], "drawing": None, "has_drawing": False, "bom": [row]})
    mappings = [{"name": "names/section/optical-optics", "kind": "section", "left": "Optical", "right": "Optics", "relationship": "same", "method": "ai_agreed"},
                {"name": "names/material/alloy-aluminium", "kind": "material", "left": "7075-T6, Plate (SS)", "right": "Aluminium", "relationship": "kind_of", "method": "ai_agreed"}]
    data = {"records.json": records, "bom.json": rows,
            "ai_results.json": {"mappings": mappings, "templates": {"D-001": {"outline": {"width": {"state": "unknown", "value": None, "method": "unresolved", "confidence": "unsure"}}}}}}
    for name, value in data.items():
        (generated / name).write_text(json.dumps(value), encoding="utf-8")
    return Store(tmp_path)


def test_inventory_counts_source_sections_and_unique_rows(summary_store):
    summary = KnowledgeTools(summary_store).machine_summary()
    assert summary["drawing_count"] == 2
    assert summary["bom_row_count"] == 6
    assert [(g["section"], g["drawing_count"]) for g in summary["drawing_sections"]] == [("Optical", 1), ("Optics", 1)]
    assert [(g["family"], g["bom_row_count"]) for g in summary["bom_families"]] == [("Optics", 6)]
    shared = summary["bom_families"][0]["parts"][0]
    assert shared["name"] == "A"
    assert shared["linked_drawing_ids"] == ["D-001/part", "D-002/part"]
    assert summary["facts"][0]["badge"] == "Computed from recorded source facts"


def test_recorded_total_arithmetic_and_missing_breakdown(summary_store):
    summary = KnowledgeTools(summary_store).cost_summary()
    assert summary["totals_by_currency"] == [{"currency": "DKK", "amount": 9.3}, {"currency": "EUR", "amount": 10}]
    assert "amount" not in summary  # currencies are never added together
    assert summary["row_count"] == 6 and summary["rows_included"] == 3
    assert summary["rows_missing_total"] == 3
    assert summary["rows_missing_price"] == 2 and summary["rows_missing_quantity"] == 2
    assert summary["rows_missing_both_price_and_quantity"] == 1
    assert summary["rows_missing_price_only"] == summary["rows_missing_quantity_only"] == 1
    assert summary["facts"][0]["snapshot_note"]
    assert "not the complete machine cost" in summary["note"]


def test_summary_preconditions_do_not_recompute_or_use_untrusted_totals(summary_store):
    tools = KnowledgeTools(summary_store)
    summary_store.fields["BOM:optics/a/total_cost"]["review"] = {"status": "human_rejected"}
    summary_store.fields["BOM:optics/f/total_cost"]["value"] = {"amount": "NaN", "currency": "DKK"}
    result = tools.cost_summary()
    assert result["rows_included"] == 1
    assert result["amount"] == 10 and result["currency"] == "EUR"
    assert result["rows_missing_total"] == 5  # trusted unit prices do not fill totals
    for invalid in (None, True, "bad", float("inf")):
        assert tools.money(field("test", {"amount": invalid, "currency": "DKK"})) is None
    assert tools.money(field("test", {"amount": 0, "currency": "DKK"})) is not None


def test_aggregate_provenance_is_registered_and_citable(summary_store):
    tools, ledger = KnowledgeTools(summary_store), {}
    result = tools.machine_summary()
    collect_evidence(result, ledger, tools)
    collect_evidence(tools.cost_summary(), ledger, tools)
    assert "BOM:optics/a/name" in ledger
    assert "D-001/source-inventory" in ledger
    assert ledger["D-001/source-inventory"]["badge"] == "From source inventory"
    assert not validate_markers("[cite: machine/summary/inventory, BOM/summary/recorded-cost]", ledger, summary_store)["warnings"]
    assert validate_markers("[cite: machine/summary/inventory]", {}, summary_store)["warnings"]
    assert tools.get_overview()["cost_summary"]["rows_included"] == 3


def test_pending_mapping_is_citable_status_without_approved_relationship(summary_store):
    tools, ledger = KnowledgeTools(summary_store), {}
    result = tools.mapping_status("Optical", "section")
    fact = result["facts"][0]
    assert fact["display"]["value"]["approved_relationship"] is None
    assert fact["review_item"] == "names/section/optical-optics"
    assert len(tools.parts_in_section("Optical")["parts"]) == 1
    collect_evidence(result, ledger, tools)
    assert not validate_markers("[cite: names/section/optical-optics]", ledger, summary_store)["warnings"]
    mapping = summary_store.mappings[0]
    mapping["review"] = {"status": "human_confirmed", "by": "Fixture reviewer", "at": "2020-01-01"}
    approved = tools.mapping_status("Optics", "section")["facts"][0]
    assert approved["display"]["value"]["approved_relationship"] == "same"
    assert not approved["review_item"]
    assert len(tools.parts_in_section("Optical")["parts"]) == 7
    mapping["review"]["status"] = "human_rejected"
    assert tools.mapping_status("Optics", "section")["facts"][0]["display"]["state"] == "value"


def test_grade_tokens_preserve_exact_grade_and_do_not_infer_family(summary_store):
    tools = KnowledgeTools(summary_store)
    result = tools.parts_with_material("7075")
    assert [p["key"] for p in result["parts"]] == ["D-001"]
    match = result["parts"][0]["material_matches"][0]
    assert match["recorded_material"] == "7075-T6, Plate (SS)"
    assert match["grade_token_match"]["derivation"]["source_fact_ids"] == ["D-001/drawing/material"]
    assert not tools.recorded_grade_match("Aluminium", "7075")
    assert tools.recorded_grade_match("3.3315 (EN-AW 5005)", "5005")
    assert tools.recorded_grade_match("3.3315 (EN-AW 5005)", "EN-AW 5005")
    assert tools.recorded_grade_match("3.3315 (EN-AW 5005)", "EN AW 5005")
    assert not tools.recorded_grade_match("3.3315 (EN-AW 5005)", "EN-AW 500")
    # Remove the independently recorded generic BOM material from this part:
    # only an actual approved specific-to-general mapping can now include it.
    summary_store.part("D-001")["bom"] = []
    assert "D-001" not in [p["key"] for p in tools.parts_with_material("Aluminium")["parts"]]
    summary_store.mappings[1]["review"] = {"status": "human_confirmed"}
    assert "D-001" in [p["key"] for p in tools.parts_with_material("Aluminium")["parts"]]
    assert "D-002" not in [p["key"] for p in tools.parts_with_material("7075-T6, Plate (SS)")["parts"]]


def test_requested_width_stays_undetermined_without_labeled_evidence(summary_store):
    tools, ledger = KnowledgeTools(summary_store), {}
    for part in ("D-001", "D-002"):
        result = tools.get_field(part, "width")
        collect_evidence(result, ledger, tools)
        fact = result["facts"][0]
        assert fact["display"]["state"] == "undetermined"
        assert fact["fact"] in summary_store.fields
        answer = validate_markers("[undetermined: " + fact["fact"] + "]", ledger, summary_store)
        assert not answer["warnings"]
        assert answer["parts_to_show"][0]["key"] == part
    assert "42" not in str(result["facts"][0]["display"])


def test_hole_callout_counts_do_not_include_slots_or_untrusted_counts(summary_store):
    tools = KnowledgeTools(summary_store)
    result = tools.get_field("D-001", "holes")
    assert result["facts"][0]["display"]["value"]["count"] == 3
    assert result["facts"][1]["callout"]["thread"] == "M4"
    assert result["facts"][2]["callout"]["count"] == 2
    summary_store.fields["D-001/drawing/callout/hole"]["confidence"] = "unsure"
    assert tools.get_field("D-001", "holes")["facts"][0]["display"]["state"] == "undetermined"


def test_shared_bom_citation_attaches_every_proven_link_only(summary_store):
    tools, ledger = KnowledgeTools(summary_store), {}
    result = tools.get_bom_row("BOM:optics/a")
    collect_evidence(result, ledger, tools)
    answer = validate_markers("[cite: BOM:optics/a/name]", ledger, summary_store)
    assert [p["key"] for p in answer["parts_to_show"]] == ["D-001", "D-002"]
    summary_store.part("D-002")["link"]["method"] = "unresolved"
    assert [p["key"] for p in tools.get_bom_row("BOM:optics/a")["linked_parts"]] == ["D-001"]


def test_source_row_names_survive_linked_drawing_name_and_section(summary_store):
    tools = KnowledgeTools(summary_store)
    summary_store.part("D-001")["display_name"] = "Other drawing name"
    result = tools.parts_in_section("Optics")
    assert result["bom_row_count"] == 6
    assert result["bom_rows"][0]["name"] == "A"
    assert result["bom_rows"][0]["section"] == "Optics"
    ledger = {}
    summary = tools.machine_summary()
    collect_evidence(summary, ledger, tools)
    answer = validate_markers("[cite: machine/summary/bom-family/0]", ledger, summary_store)
    assert len(answer["parts_to_show"]) == 7


def test_specific_thread_query_uses_only_that_explicit_callout(summary_store):
    tools = KnowledgeTools(summary_store)
    result = tools.get_field("D-001", "M4 threaded holes")
    assert result["facts"][0]["display"]["value"]["count"] == 3
    assert result["facts"][0]["display"]["value"]["thread"] == "M4"
    assert len(result["facts"]) == 2
    assert tools.get_field("D-001", "M5 threaded holes")["facts"][0]["display"]["state"] == "undetermined"
    assert tools.get_field("D-001", "slots")["facts"][0]["display"]["value"]["count"] == 2


def test_part_lookup_tolerates_measurement_words_without_losing_exact_name(summary_store):
    tools = KnowledgeTools(summary_store)
    assert tools.find_part("Plate 1 M4 holes tightening torque")["parts"][0]["key"] == "D-001"
    assert tools.find_part("show drawing D-002 width")["parts"][0]["key"] == "D-002"


def test_unknown_dimension_exposes_boxes_without_assigning_an_edge(summary_store):
    tools = KnowledgeTools(summary_store)
    summary_store.fields["D-002/drawing/n/42"]["box"] = [1, 2, 3, 4]
    result = tools.get_field("D-002", "width")
    assert result["facts"][0]["display"]["state"] == "undetermined"
    assert any(s["name"] == "D-002/drawing/n/42" and s["box"] for s in result["facts"][0]["sources"])


def test_mapping_uncertainty_does_not_replace_printed_grade_fact(summary_store):
    tools, ledger = KnowledgeTools(summary_store), {}
    result = tools.parts_with_material("7075")
    collect_evidence(result, ledger, tools)
    assert ledger["D-001/drawing/material"]["display"]["state"] == "value"
    assert ledger["D-001/resolved/material"]["display"]["state"] == "undetermined"


def test_model_verification_is_citable_and_correction_attribution_required(summary_store):
    part = summary_store.part("D-001")
    part["model"] = {"weight_check": {"state":"FAILED"}, "models":{"A":{"selections":{"thickness":4},"volume_mm3":20}}, "omitted":["Unknown holes"]}
    tools, ledger = KnowledgeTools(summary_store), {}
    collect_evidence(tools.get_facts("D-001"), ledger, tools)
    assert ledger["D-001/model/verification"]["display"]["value"]["weight_check"]["state"] == "FAILED"
    fact = ledger["D-001/drawing/material"]
    fact["correction"] = {"original":"Old", "corrected":"New", "by":"Fixture reviewer", "at":"2020-01-01T00:00:00Z"}
    assert validate_markers("New [cite: D-001/drawing/material]", ledger, summary_store)["warnings"]
    assert not validate_markers("New (originally Old; Fixture reviewer, 2020-01-01) [cite: D-001/drawing/material]", ledger, summary_store)["warnings"]
