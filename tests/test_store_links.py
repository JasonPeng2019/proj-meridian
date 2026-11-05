"""In-memory integration checks; never create production human decisions."""
import unittest

from backend.app.store import Store
from backend.app.tools import KnowledgeTools
from backend.loader.records import connections
from backend.paths import GENERATED


class StoreLinkChecks(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.extraction = (GENERATED / "records.json").read_bytes()

    def tearDown(self):
        self.assertEqual(self.extraction, (GENERATED / "records.json").read_bytes())

    def event(self, target, kind, value=None):
        return {"applies_to": target, "type": kind, "value": value, "status": "accepted",
                "by": "Automated in-memory check, not a human review", "at": "2000-01-01T00:00:00Z"}

    def test_canonical_drawing_aliases_and_title_overlay(self):
        store = self.store
        part = store.part("D-019")
        target = "D-019/drawing/title"
        self.assertIs(store.fields[target], part["drawing"]["fields"]["title"])
        self.assertIs(store.fields[target], part["drawing"]["page_fields"]["1"]["title"])
        original = store.raw_fields[target]["value"]
        store._apply(self.event(target, "correction", "In-memory corrected title"))
        self.assertEqual(part["display_name"], "In-memory corrected title")
        self.assertEqual(part["drawing"]["fields"]["title"]["value"], "In-memory corrected title")
        self.assertEqual(store.fields[part["id"]]["value"], "In-memory corrected title")
        self.assertEqual(store.raw_fields[target]["value"], original)

    def test_accept_link_projects_row_fields_connections_and_sidebar(self):
        store = self.store
        row = next(p["bom"][0] for p in store.records if not p.get("drawing") and p["bom"][0]["fields"]["interface_with"]["value"])
        key = "bom/" + row["name"][4:]
        target = "D-019/link"
        # A previous BOM correction must survive changing its part ownership.
        material = row["fields"]["material"]["name"]
        store._apply(self.event(material, "set_value", ["In-memory material"]))
        store._apply(self.event(target, "link", [row["name"]]))
        part = store.part("D-019")
        self.assertNotIn(key, store.parts)
        self.assertEqual(part["bom"][0]["name"], row["name"])
        self.assertEqual(part["link"]["bom_rows"], [row["name"]])
        self.assertEqual(part["link"]["value"], [row["name"]])
        self.assertIs(part["bom"][0], store.rows[row["name"]])
        self.assertIs(store.owners[material], part)
        self.assertEqual(store.fields[material]["value"], ["In-memory material"])
        self.assertEqual(part["connections"], connections(row, list(store.rows.values())))
        self.assertIn(material, {f["fact"] for f in KnowledgeTools(store).get_bom_row(row["name"])["facts"]})

    def test_reject_link_removes_linked_claims_and_restores_standalone(self):
        store = self.store
        row = next(p["bom"][0] for p in store.records if not p.get("drawing"))
        target = "D-019/link"
        store._apply(self.event(target, "link", [row["name"]]))
        store._apply(self.event(target, "reject"))
        part = store.part("D-019")
        self.assertEqual(part["bom"], [])
        self.assertEqual(part["connections"], [])
        self.assertEqual(part["link"]["method"], "unresolved")
        self.assertEqual(part["link"]["value"], [])
        self.assertIn("bom/" + row["name"][4:], store.parts)
        self.assertEqual(next(i for i in store.review_items() if i["id"] == target)["type"], "link")
        material = row["fields"]["material"]["name"]
        self.assertIs(store.owners[material], store.part("bom/" + row["name"][4:]))

    def test_template_rejection_becomes_unknown(self):
        store = self.store
        target = "D-025/template/thickness"
        store.templates.setdefault("D-025", {})["thickness"] = {"state": "options", "options": [3, 6], "method": "ai_agreed", "confidence": "sure"}
        store._index()
        store.fields[target]["selected"] = 3
        store._apply(self.event(target, "reject"))
        self.assertEqual(store.fields[target]["state"], "unknown")
        self.assertNotIn("selected", store.fields[target])
        self.assertEqual(KnowledgeTools(store).display(target)["display"]["state"], "undetermined")
        store._apply(self.event(target, "set_value", 6))
        self.assertEqual(KnowledgeTools(store).display(target)["display"], {"state": "value", "value": 6})


if __name__ == "__main__":
    unittest.main()
