"""Focused B01/M06 checks; run from testing/ on Actions, with no readers/network.

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../development python -m unittest discover -s tests -p test_bom_m1.py -v

Synthetic CSVs only test rules; source assertions inspect the supplied CSV and
manifest directly, never a benchmark expected-answer file or contract fixture.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from backend.contracts import BOMRow, Confidence, Method, bom_part_name
from backend.loader.bom import (
    DEFAULT_BOM_PATH, HEADER_KEYS, SNAPSHOT_NOTE, TEMPORARY_LINK_NOTE, load_bom,
)


TESTING = Path(__file__).resolve().parents[1]


class BOMM1Tests(unittest.TestCase):
    def setUp(self):
        temporary = TESTING / "tmp" / "A06-bom"
        temporary.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.directory.cleanup)

    def source(self, records):
        path = Path(self.directory.name) / "synthetic.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(HEADER_KEYS))
            writer.writeheader()
            writer.writerows(records)
        return path

    def test_supplied_rows_headers_original_cells_and_manifest_hash(self):
        before = DEFAULT_BOM_PATH.read_bytes()
        manifest = json.loads((DEFAULT_BOM_PATH.parents[1] / "manifest.json").read_text("utf-8"))
        # Find the asset independent of the manifest's top-level metadata.
        def asset(value):
            if isinstance(value, dict):
                if value.get("id") == "OPENLPBF-BOM":
                    return value
                for child in value.values():
                    found = asset(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = asset(child)
                    if found:
                        return found
            return None

        entry = asset(manifest)
        self.assertIsNotNone(entry)
        self.assertEqual(hashlib.sha256(before).hexdigest(), entry["sha256"])
        self.assertEqual(len(before), entry["bytes"])
        raw = list(csv.reader(io.StringIO(before.decode("utf-8-sig"), newline="")))
        rows = load_bom()
        self.assertEqual(len(rows), 192)
        self.assertEqual(raw[0], list(HEADER_KEYS))
        self.assertEqual(len(rows), len(raw) - 1)
        for ordinal, (cells, row) in enumerate(zip(raw[1:], rows, strict=True), 1):
            self.assertIsInstance(row, BOMRow)
            self.assertEqual(row.display_id, f"BOM-{ordinal:03d}")
            self.assertEqual(len(row.fields), 20)
            for header, original in zip(raw[0], cells, strict=True):
                field = row.fields[HEADER_KEYS[header]]
                self.assertEqual(field.original, original)
                self.assertIn(f"Original header: {header}", field.note)
                self.assertTrue(field.name.startswith(row.name + "/"))
                self.assertIsNone(field.correction)
                self.assertIsNone(field.review)
            self.assertTrue(row.snapshot_note)
            self.assertEqual(BOMRow.model_validate_json(row.model_dump_json()), row)
        self.assertEqual(DEFAULT_BOM_PATH.read_bytes(), before)
        self.assertEqual([r.model_dump() for r in load_bom()], [r.model_dump() for r in rows])

    def test_supplied_zero_traps_lists_and_recorded_connections(self):
        rows = load_bom()
        for row in rows:
            fields = row.fields
            if not fields["cost"].original.strip() or not fields["amount"].original.strip():
                self.assertIsNone(fields["total_cost"].value)
                self.assertIn("blank_cost_or_amount -> total not recorded", fields["total_cost"].cleanup)
            for key in ("cost", "total_cost"):
                self.assertEqual(fields[key].currency, "DKK")
                self.assertTrue(fields[key].snapshot_note)
            for key in ("material", "interface_with"):
                self.assertTrue(fields[key].value is None or isinstance(fields[key].value, list))
            for reference in row.connections:
                self.assertEqual(reference.original, fields["interface_with"].original)
                self.assertEqual(reference.name, fields["interface_with"].name)
                self.assertIn(reference.target_name, fields["interface_with"].value)
                if reference.resolved:
                    targets = [r for r in rows if r.name == reference.target_row]
                    self.assertEqual(len(targets), 1)
                    self.assertEqual(reference.target_part, bom_part_name(targets[0].section, targets[0].display_name))
                else:
                    self.assertIsNone(reference.target_row)
                    self.assertIsNone(reference.target_part)
                    self.assertTrue(reference.note)
        left = next(row for row in rows if row.display_name == "Left Side Box")
        self.assertEqual(left.fields["total_cost"].original, "DKK0.00")
        self.assertIsNone(left.fields["cost"].value)
        self.assertIsNone(left.fields["total_cost"].value)
        self.assertTrue(all(ref.resolved for ref in left.connections))
        # Source record ordinals exclude the header, not embedded CSV newlines.
        with DEFAULT_BOM_PATH.open(encoding="utf-8-sig", newline="") as handle:
            original_rows = list(csv.DictReader(handle))
        self.assertEqual(
            [original_rows[82][key] for key in ("Name", "Part family", "Interface with")],
            ["Laser source", "Optics", "GLAMS"],
        )
        self.assertEqual(
            [original_rows[104][key] for key in ("Name", "Part family")],
            ["GLAMS", "Electric"],
        )
        self.assertEqual(
            [index for index, raw in enumerate(original_rows, 1) if raw["Name"].strip().lower() == "glams"],
            [105],
        )
        laser, target = rows[82], rows[104]
        self.assertEqual(laser.name, "BOM:optics/laser-source")
        self.assertEqual(target.name, "BOM:electric/glams")
        self.assertEqual(target.display_id, "BOM-105")
        glams = next(ref for ref in laser.connections if ref.target_name == "GLAMS")
        self.assertTrue(glams.resolved)
        self.assertEqual(glams.target_row, "BOM:electric/glams")
        self.assertEqual(glams.target_part, "BOM:electric/glams/part")
        self.assertEqual(glams.name, "BOM:optics/laser-source/interface_with")
        self.assertEqual(glams.original, original_rows[82]["Interface with"])
        self.assertEqual(glams.original, laser.fields["interface_with"].original)
        self.assertIn("Unique normalized BOM name match", glams.note)

    def test_core_cleanup_and_snapshot_without_m3_repairs(self):
        image = "photo.jpg (https://v5.airtableusercontent.com/expired)"
        raw_note = "first\r\nsecond\\nthird"
        row = load_bom(self.source([{
            "Name": " Part ", "Part family": " Test ", "Material": " Steel, Elastomer ",
            "Amount": " 2 ", "Cost": "DKK58.15", "Total cost": "DKK116.30",
            "Order": "Recieved", "Notes": raw_note, "Image": image,
            "Supplier Order": "00123", "Supplier": " Historical supplier ",
        }]))[0]
        self.assertEqual(row.name, "BOM:test/part")
        self.assertEqual(row.fields["name"].original, " Part ")
        self.assertIn("trim_whitespace", row.fields["name"].cleanup)
        self.assertEqual(row.fields["material"].value, ["Steel", "Elastomer"])
        self.assertIn("meaning is not specified", row.fields["material"].note)
        self.assertEqual(row.fields["amount"].value, 2)
        self.assertEqual(row.fields["cost"].value, 58.15)
        self.assertEqual(row.fields["total_cost"].value, 116.30)
        self.assertEqual(row.fields["supplier_order"].value, "00123")
        self.assertEqual(row.fields["notes"].original, raw_note)
        self.assertEqual(row.fields["notes"].value, raw_note)
        self.assertEqual(row.fields["order"].value, "Recieved")
        self.assertEqual(row.fields["image"].value, image)
        self.assertIn(TEMPORARY_LINK_NOTE, row.fields["image"].note)
        self.assertIsNone(row.fields["link"].value)
        self.assertIn("Not recorded", row.fields["link"].note)
        self.assertIn("No connections recorded", row.fields["interface_with"].note)
        for key in ("supplier", "supplier_order", "link", "cost", "total_cost", "order", "design", "validation"):
            self.assertTrue(row.fields[key].snapshot_note)
            self.assertIn(SNAPSHOT_NOTE, row.fields[key].note)

    def test_missing_cost_or_amount_is_unrecorded_but_explicit_zero_is_retained(self):
        records = [
            {"Name": "No cost", "Part family": "Test", "Amount": "1", "Total cost": "DKK0.00"},
            {"Name": "No amount", "Part family": "Test", "Cost": "DKK5.00", "Total cost": "DKK0.00"},
            {"Name": "Zero", "Part family": "Test", "Amount": "1", "Cost": "DKK0.00", "Total cost": "DKK0.00"},
        ]
        rows = load_bom(self.source(records))
        for row in rows[:2]:
            total = row.fields["total_cost"]
            self.assertEqual(total.original, "DKK0.00")
            self.assertIsNone(total.value)
            self.assertEqual(total.method, Method.CLEANUP_RULE)
            self.assertIn("not free", total.note)
        self.assertEqual(rows[2].fields["cost"].value, 0)
        self.assertEqual(rows[2].fields["total_cost"].value, 0)

    def test_collisions_ambiguity_forward_missing_and_directed_references(self):
        records = [
            {"Name": "Source", "Part family": "Test", "Interface with": "Target, Bolt, Missing, Dup"},
            {"Name": "Target", "Part family": "Test"},
            {"Name": "Bolt", "Part family": "A"},
            {"Name": "BOLT", "Part family": "B"},
            {"Name": "Dup", "Part family": "Test"},
            {"Name": "Dup!", "Part family": "Test"},
            {"Name": "Dup", "Part family": "Test"},
        ]
        rows = load_bom(self.source(records))
        self.assertEqual(len(rows), len(records))
        self.assertEqual(len({r.display_id for r in rows}), len(rows))
        self.assertEqual({r.name for r in rows[4:]}, {"BOM:test/dup"})
        for row in rows[4:]:
            self.assertTrue(row.identity_conflict)
            self.assertEqual(row.fields["name"].confidence, Confidence.UNSURE)
            self.assertIn("collision", row.fields["name"].note)
        self.assertFalse(rows[2].identity_conflict)
        self.assertIn("Ambiguous normalized part name", rows[2].fields["name"].note)
        refs = rows[0].connections
        self.assertEqual([ref.resolved for ref in refs], [True, False, False, False])
        self.assertEqual(refs[0].target_row, rows[1].name)
        self.assertIn("Ambiguous", refs[1].note)
        self.assertIn("BOM-003", refs[1].note)
        self.assertIn("BOM-004", refs[1].note)
        self.assertIn("unresolved", refs[2].note)
        self.assertIn("Ambiguous", refs[3].note)
        self.assertEqual(rows[1].connections, [])  # no invented reverse link

    def test_stable_identity_and_fingerprint_survive_reordering(self):
        records = [
            {"Name": "Part A", "Part family": "Test", "Cost": "DKK1.00", "Amount": "2"},
            {"Name": "Part B", "Part family": "Test", "Cost": "DKK2.00", "Amount": "2"},
        ]
        first = load_bom(self.source(records))
        second = load_bom(self.source(list(reversed(records))))
        self.assertEqual({r.name: r.source_sha256 for r in first}, {r.name: r.source_sha256 for r in second})
        self.assertNotEqual(first[0].display_id, second[1].display_id)
        records[0]["Cost"] = "DKK3.00"
        changed = load_bom(self.source(records))
        self.assertEqual(first[0].name, changed[0].name)
        self.assertNotEqual(first[0].source_sha256, changed[0].source_sha256)
        self.assertEqual(first[1].source_sha256, changed[1].source_sha256)


if __name__ == "__main__":
    unittest.main()
