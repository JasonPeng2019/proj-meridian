"""Review links must resolve to retained evidence, never arbitrary paths."""
from types import SimpleNamespace

from backend.app.review_sources import review_sources, source_record


def source_store():
    printed = {"name": "D-001/drawing/n/42@1", "value": 42, "page": 2, "box": [10, 20, 30, 5]}
    template = {"name": "D-001/template/length", "value": 42, "fact_ids": [printed["name"], "../../secret"]}
    part = {"key": "D-001", "drawing": {"id": "D-001", "source_path": "evidence/D-001.pdf"}}
    row = {"name": "BOM:box/door", "display_id": "BOM-001", "display_name": "Door", "fields": {"material": {"name": "BOM:box/door/material", "original": "Alu", "value": "Aluminium"}}}
    fields = {printed["name"]: printed, template["name"]: template}
    return SimpleNamespace(raw_fields=fields, fields=fields, owners={name: part for name in fields},
                           parts={"D-001": part}, rows={row["name"]: row}, mappings=[])


def test_computed_value_links_printed_region_and_whole_drawing():
    store = source_store()
    refs = review_sources(store, {"id": "length", "target": "D-001/template/length"})
    assert [ref["name"] for ref in refs] == ["D-001/drawing/n/42@1", "D-001/drawing/source"]
    assert refs[0]["page"] == 2 and refs[0]["box"] == [10, 20, 30, 5]
    assert source_record(store, "../../secret", detail=True) is None


def test_bom_source_preserves_original_and_cleaned_row():
    store = source_store()
    record = source_record(store, "BOM:box/door/material", detail=True)
    assert record["kind"] == "bom"
    assert record["row"]["fields"]["material"]["original"] == "Alu"
    assert record["row"]["fields"]["material"]["value"] == "Aluminium"


def test_mapping_receipts_link_both_sides_and_ignore_invalid_receipts():
    store = source_store()
    item = {"id": "mapping", "target": "names/material/alu", "readers": {
        "proposer": {"rounds": [{"answer": {"fact_ids": ["D-001/drawing/n/42@1", "BOM:box/door"]}}]},
        "invalid": {"rounds": [{"valid": False, "answer": {"fact_ids": ["../../secret"]}}]},
    }}
    assert {r["kind"] for r in review_sources(store, item)} == {"drawing", "bom"}


def test_cyclic_receipt_references_terminate_without_inventing_sources():
    store = source_store()
    store.fields["D-001/template/length"]["fact_ids"].append("D-001/template/length")
    assert len(review_sources(store, {"id": "length", "target": "D-001/template/length"})) == 2


def test_empty_reader_response_keeps_original_sources_and_other_valid_receipts():
    store = source_store()
    item = {"id": "length", "target": "D-001/template/length", "readers": {
        "empty_legacy": {"answer": None},
        "empty_round": {"rounds": [None, {"answer": None}]},
        "valid": {"rounds": [{"answer": {"fact_ids": ["BOM:box/door"]}}]},
    }}
    refs = review_sources(store, item)
    assert {r["name"] for r in refs} == {"D-001/drawing/n/42@1", "D-001/drawing/source", "BOM:box/door"}
