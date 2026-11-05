"""Versioned answer contracts. The supplied draft and old captures stay immutable.

Rules check structure and simple values. The independent judge checks meaning,
including negation, completeness, translations and unsupported positive claims.
"""
from __future__ import annotations

VERSION = 2
POLICY = [
    "Answer the actual question using the captured evidence and its current review state.",
    "Equivalent wording, faithful English translations and equivalent units are allowed. Preserve exact alloy grades.",
    "A citation is evidence, not a substitute for an answer. A named, source-linked part card can identify a list item.",
    "Unknown values, unresolved links and unapproved mappings must not become known facts or human approvals.",
    "Customer answers may be concise. Do not demand unsolicited diagnostics, review warnings, UI tutorials or a weight table.",
    "Explicit questions about model accuracy still require a truthful assessment of its limits. Any extra claim must be supported.",
    "Negative statements such as 'not free' or 'cannot establish whether it is in stock' are not positive claims.",
    "Judge factual correctness and substantive completeness. Awkward style alone does not fail a correct answer.",
]

INTENTS = {
    "Q01": "Give 30 drawings and all six section counts from the drawing inventory. Do not merge differently named BOM sections without approval.",
    "Q02": "Identify all ten canonical Optics BOM rows, including F-theta seal ring. Any stated total must be ten and consistent throughout. Drawing titles must not replace different BOM row identities.",
    "Q03": "Use the captured section-mapping status: confirm equivalence only if approved as same; otherwise explain it is not established. Correct pending/rejected behavior passes; approval coverage is reported separately.",
    "Q04": "Report the drawing's literal EN-AW 5005 grade. An unresolved link does not prevent this answer. Do not invent a BOM match or material-family approval.",
    "Q05": "Name DTU as the recorded supplier and identify the price as missing/unknown, rather than free or an actual zero price. Snapshot wording must make clear this is recorded information, not a live supplier quote. Valid Undetermined markers on missing costs are correct.",
    "Q06": "Identify Front Door and Front Side Box as the recorded hinge connections. Availability claims may use captured part-card flags; do not infer a drawing or model exists from a whole-part citation alone.",
    "Q07": "Report both Steel and Elastomer as recorded materials. Do not present Steel as the sole material or infer the belt's construction from a material list.",
    "Q08": "List all current material-search matches from exact Aluminium evidence and approved material mappings, using the independent reference when present. Distinguish a BOM Aluminium entry from an unresolved combined drawing material. Do not require unapproved alloy-family mappings or silently merge unlinked drawings. Any count must match its declared scope; do not claim an exact verified physical-part total while identities remain unresolved. A matching-record list is sufficient; no unsolicited physical count is required.",
    "Q09": "Identify exactly the six EN-AW 5005 drawings D-012, D-013, D-014, D-024, D-025, D-028. Names with grounded identity citations/cards suffice; IDs need not be repeated in prose. Do not count a raw marker dump as an answer, or include a different alloy as a match. Exact printed grades need no family approval.",
    "Q10": "Report BOM materials Stainless steel and Steel. Keep unreadable drawing material unknown; do not assert AISI 316 as established. Faithful English translation of 'rustfri og alu' as 'stainless steel and aluminium' is allowed when attributed to the drawing note. An unresolved drawing field must not invalidate the known BOM list.",
    "Q11a": "Keep the D-019 title Undetermined before correction; Description is a placeholder, not an established title.",
    "Q11b": "Report Silicone gasket for f-theta lens and its original Description placeholder after the isolated correction. Attribute any review claim to the actual workflow reviewer, Automated verification, never fabricate Jason's approval.",
    "Q12": "Give the captured, supported weight 3195.5 g (or an accurate equivalent). Abstain only if the actual field is Undetermined. Do not require an unsolicited blurry-scan/review warning; do not invent human review.",
    "Q13": "Use the current evidence, not the draft's old assumption that all numbers are unlabeled. An interpreted template width of 110 mm is a supported answer when linked to its vertical overall-dimension source; the template convention uses length for the horizontal 180 mm side. Do not guess a width from a bare unlabeled number or equate the two axes. Abstain or clarify if no interpreted dimension establishes the requested axis.",
    "Q14": "Give both 2 mm and 3 mm thickness alternatives without selecting one as correct. Attach the available D-025 model with its alternatives. An unsolicited tutorial or literal Examples A/B sentence is unnecessary.",
    "Q15": "Say no tightening torque is supplied. Do not infer a numeric torque or import an outside recommendation. Mentioning the unit Nm in a denial is allowed.",
    "Q16": "Give eight M3 threaded holes and cite the M3 feature/callout, rather than an unrelated count or whole-part citation alone.",
    "Q17": "Attach D-026 with both 15 mm and 25 mm alternatives and truthfully assess the reconstruction. It is partial, not an exact approved manufacturing model: the 15 mm variant omits a counterbore step and edge finishing is omitted. Do not imply a complete match or a passing weight check. A concise supported limitation assessment suffices; numeric weights and the literal words FAILED/manual approval are not mandatory. If weights are volunteered, compare with the actual captured model/density table, not planning estimates.",
    "Q18": "Give the recorded DKK 168591.52 total, 116 rows with totals and 76 without. Identify snapshot/incomplete coverage. Missing prices do not prove the real total is strictly higher.",
    "Q19": "Give the README's 250 mm by 150 mm build envelope and cite that passage. Do not invent a third dimension.",
    "Q20": "Identify Max Photonics as the recorded supplier, distinguish the snapshot from today, and say current stock is unknown. A past Received order is not present stock. Negated stock/availability statements are allowed. Drawing/model absence may use captured card flags.",
}


def contract(case: dict) -> dict:
    return {"version": VERSION, "policy": POLICY, "intent": INTENTS[case["id"]]}


def catalog_reference(store) -> dict:
    """Independent of chat answers/retrieval; deterministic queries on pinned inputs.

    This is a chat evaluation oracle, not a substitute for the tools' own tests.
    It is recorded before chat runs and never supplied to the chat model.
    """
    from backend.app.tools import KnowledgeTools
    tools = KnowledgeTools(store)
    optics = tools.parts_in_section("Optics")
    aluminium = tools.parts_with_material("Aluminium")
    grade = tools.parts_with_material("EN-AW 5005")
    def identity(part):
        record = store.parts[part["key"]]
        return {k: part[k] for k in ("id", "key", "display_name")} | {
            "bom_rows": [r["name"] for r in record.get("bom", [])],
            "material_sources": [m["source_fact"]["fact"] for m in part.get("material_matches", [])]}
    return {
        "Q02": {"bom_row_count": optics["bom_row_count"], "bom_rows": [
            {k: r[k] for k in ("row_id", "name", "linked_drawing_ids")} for r in optics["bom_rows"]]},
        "Q08": {"scope": "current exact/approved-mapping catalog matches, not verified physical identities",
                "parts": [identity(p) for p in aluminium["parts"]]},
        "Q09": {"parts": [identity(p) for p in grade["parts"]]},
    }
