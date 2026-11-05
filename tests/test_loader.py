"""Small evidence checklist: run `python -m unittest discover -s tests -p test_loader.py`."""
import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import pymupdf as fitz

from backend.loader import build_records, parse_bom
from backend.loader.build import clean_cell, read_json, sha_file, write_json
from backend.loader.drawings import fields_for_page, unique_words
from backend.loader.records import assemble_records
from backend.paths import CORPUS, GENERATED, ROOT, inside


class LoaderChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = build_records()
        cls.drawings = read_json(GENERATED / "drawings.json", {})
        cls.bom = read_json(GENERATED / "bom.json", [])

    def test_corpus_coverage_and_source_fingerprints(self):
        self.assertEqual(len(self.drawings), 30)
        self.assertEqual(sum(d["pages"] for d in self.drawings.values()), 33)
        self.assertEqual(len(self.bom), 192)
        self.assertEqual(len({r["key"] for r in self.records}), len(self.records))
        for drawing in self.drawings.values():
            self.assertEqual(drawing["sha256"], sha_file(ROOT / drawing["source_path"]))
            self.assertEqual(len(drawing["images"]), drawing["pages"])
            for image in drawing["images"] + [drawing["corner_image"]]:
                self.assertTrue(inside(GENERATED / image).is_file())
            for field in list(drawing["fields"].values()) + drawing["numbers"] + drawing["callouts"]:
                width, height = drawing["page_sizes"][field["page"] - 1]
                x, y, w, h = field["box"]
                self.assertGreaterEqual(min(x, y, w, h), 0)
                self.assertLessEqual(x + w, width + .01)
                self.assertLessEqual(y + h, height + .01)

    def test_clean_extraction_is_positional_and_conservative(self):
        d = self.drawings["D-013"]
        self.assertEqual(d["fields"]["title"]["value"], "Recoater Plate")
        self.assertEqual(d["fields"]["material"]["value"], "3.3315 (EN-AW 5005)")
        self.assertEqual(d["fields"]["material"]["confidence"], "sure")
        self.assertEqual(self.drawings["D-019"]["fields"]["title"]["value"], "Description")
        self.assertEqual(self.drawings["D-019"]["fields"]["title"]["confidence"], "unsure")
        self.assertEqual(self.drawings["D-026"]["fields"]["material"]["confidence"], "unsure")
        for key in ["D-002", "D-004", "D-006", "D-010", "D-021", "D-029"]:
            self.assertIsNone(self.drawings[key]["fields"]["title"]["value"])
            self.assertTrue(self.drawings[key]["fields"]["notes"]["value"])
        self.assertEqual(len(d["words"]), len({(w["text"], tuple(w["box"])) for w in d["words"]}))
        slot = next(c for c in d["callouts"] if c["feature"] == "slot")
        self.assertEqual((slot["count"], slot["width_mm"], slot["length_mm"], slot["through"]), (4, 5.5, 10, True))
        m3 = next(c for c in d["callouts"] if c.get("thread") == "M3")
        self.assertEqual(m3["count"], 8)
        self.assertTrue(all(n["label"] is None for n in d["numbers"]))

    def test_scans_have_no_invented_measurements(self):
        scans = [d for d in self.drawings.values() if d["degraded"]]
        self.assertEqual(len(scans), 8)
        for scan in scans:
            self.assertEqual(scan["numbers"], [])
            self.assertEqual(scan["callouts"], [])
            self.assertEqual(scan["words"], [])
            self.assertTrue(all(f["source_quality"] == "degraded" for f in scan["fields"].values()))
            # Prep must always receive raw extraction, independently of any
            # cached scan readings already merged into application records.
            for fields in [scan["fields"], *scan["page_fields"].values()]:
                for field in fields.values():
                    self.assertEqual(field["method"], "parsed")
                    self.assertIsNone(field["value"])
                    self.assertIsNone(field["original"])
                    self.assertNotIn("readers", field)

    def test_originals_and_cleanup_zero_trap(self):
        affected = []
        for row in self.bom:
            self.assertTrue(row["name"].startswith("BOM:"))
            self.assertEqual(row["section"], row["original"]["Part family"].strip())
            for field in row["fields"].values():
                self.assertEqual(field["original"], row["original"][field["header"]])
                self.assertTrue(field["name"].startswith(row["name"] + "/"))
            fields = row["fields"]
            if fields["cost"]["value"] is None or fields["amount"]["value"] is None:
                self.assertIsNone(fields["total_cost"]["value"])
                affected.append(row["name"])
            if fields["material"]["value"] is not None:
                self.assertIsInstance(fields["material"]["value"], list)
        self.assertEqual(len(affected), 76)
        self.assertEqual(clean_cell(" Recieved ", "order")[0], "Received")
        self.assertEqual(clean_cell("Unknown status", "order")[2], ["unknown_status"])
        self.assertEqual(clean_cell("DKK53.00", "cost")[0], {"amount": 53., "currency": "DKK"})
        self.assertEqual(sum(bool(r["fields"]["interface_with"]["value"]) for r in self.bom), 9)

    def test_ai_merge_and_rebuild_never_author_human_decisions(self):
        with tempfile.TemporaryDirectory(dir=inside(ROOT / ".tmp")) as temporary:
            output = Path(temporary)
            drawings = {"D-001": deepcopy(self.drawings["D-001"]), "D-013": deepcopy(self.drawings["D-013"])}
            # Start from extracted scan, independent of an existing prep run.
            drawings["D-001"]["fields"]["title"].update(value=None, original=None, method="parsed", confidence="unsure")
            write_json(output / "drawings.json", drawings)
            raw_index_bytes = (output / "drawings.json").read_bytes()
            ai = {"scans": {"D-001": {"fields": {"title": {"value": "Printed scan title", "confidence": "sure", "method": "ai_read", "box": [0, 0, 0, 0]}}}},
                  "links": {"D-013": {"bom_rows": [self.bom[0]["name"]], "method": "ai_agreed"}}, "mappings": [], "templates": {}}
            write_json(output / "ai_results.json", ai)
            write_json(output / "models/manifest.json", {"D-013": {"examples": ["A"], "models": {"A": {"glb": "D-013_A.glb"}}}})
            records = assemble_records(drawings, self.bom, output)
            scan = next(r for r in records if r["key"] == "D-001")
            field = scan["drawing"]["fields"]["title"]
            self.assertEqual(field["value"], "Printed scan title")
            self.assertEqual(field["box"], drawings["D-001"]["fields"]["title"]["box"])
            self.assertEqual((output / "drawings.json").read_bytes(), raw_index_bytes)
            self.assertIsNone(drawings["D-001"]["fields"]["title"]["value"])
            self.assertEqual(drawings["D-001"]["fields"]["title"]["method"], "parsed")
            part = next(r for r in records if r["key"] == "D-013")
            self.assertTrue(part["has_3d"])
            self.assertEqual(part["link"]["review"], {"status": "not_reviewed"})
            before = (output / "records.json").read_bytes()
            assemble_records(drawings, self.bom, output)
            self.assertEqual(before, (output / "records.json").read_bytes())
            self.assertEqual((output / "drawings.json").read_bytes(), raw_index_bytes)
            self.assertFalse((output / "decisions").exists())
            ai["links"]["D-013"]["bom_rows"] = ["BOM:invented/does-not-exist"]
            write_json(output / "ai_results.json", ai)
            records = assemble_records(drawings, self.bom, output)
            part = next(r for r in records if r["key"] == "D-013")
            self.assertEqual(part["bom"], [])
            self.assertEqual(part["link"]["method"], "unresolved")

    def test_output_boundary_and_readme_sources(self):
        with self.assertRaises(ValueError):
            inside(ROOT.parent / "escaped.json")
        passages = read_json(GENERATED / "readme.json", [])
        self.assertTrue(passages)
        self.assertEqual(len({p["name"] for p in passages}), len(passages))
        self.assertTrue(all(p["name"].startswith("README/") and p["method"] == "parsed" for p in passages))

    def test_cached_ai_results_restore_offline(self):
        with tempfile.TemporaryDirectory(dir=inside(ROOT / ".tmp")) as temporary:
            output = Path(temporary)
            cached = {"links": {"D-013": {"method": "ai_agreed", "bom_rows": [self.bom[0]["name"]]}}}
            write_json(output / "ai_cache/artifacts/ai_results.json", cached)
            records = assemble_records({"D-013": self.drawings["D-013"]}, self.bom, output)
            self.assertEqual(read_json(output / "ai_results.json", {}), cached)
            self.assertEqual(records[0]["link"]["method"], "ai_agreed")
            self.assertEqual(records[0]["bom"][0]["name"], self.bom[0]["name"])


if __name__ == "__main__":
    unittest.main()
