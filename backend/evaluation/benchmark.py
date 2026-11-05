"""Immutable draft compiler and versioned, evidence-aware answer scorer.

Question text and expected answers are read from the draft, never maintained here.
Case-specific code only resolves prose instructions into explicit predicates.
The legacy compiler preserves frozen capture identities. Current evaluation uses
the versioned contracts, rather than treating draft wording as a string oracle.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from backend.evaluation.contracts import VERSION, contract

JUDGE = {"reader": "claude", "model": "opus", "fast_mode": False, "protocol": VERSION}
CASE_IDS = [f"Q{i:02}" for i in range(1, 11)] + ["Q11a", "Q11b"] + [f"Q{i:02}" for i in range(12, 21)]
MARKER = re.compile(r"\[(cite|undetermined):\s*([^\]]+)\]", re.I)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def tokens(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"(?<=\d)[,\u202f\u00a0](?=\d{3}(?:\D|$))", "", text)
    # Number tokens have boundaries: '3' does not match 3195.5 or 30.
    return [format(Decimal(token).normalize(), "f") if token[0].isdigit() else token
            for token in re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+", text, re.UNICODE)]


def contains(text: str, value: str) -> bool:
    hay, needle = tokens(text), tokens(value)
    return bool(needle) and any(hay[i:i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))


def line(body: str, label: str) -> str:
    found = re.search(rf"^- \*\*{re.escape(label)}:\*\*\s*(.*)$", body, re.M)
    return found.group(1) if found else ""


def compile_draft(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    # Delimit by the next question/section, retaining each full answer and caveat.
    headers = list(re.finditer(r"^\*\*(Q\d{2}[ab]?)\. (.+?)\*\*(.*)$", text, re.M))
    cases = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else text.index("\n## Two tools", match.end())
        body = text[match.end():end].split("\n### ")[0].strip()
        categories = list(re.finditer(r"^### (.+)$", text[:match.start()], re.M))
        cid, question = match.group(1), match.group(2)
        # Q11's lifecycle annotations are outside the exact question.
        question = re.sub(r"\s*\*?\(.*$", "", question).strip()
        must_include = re.findall(r"`([^`]+)`", line(body, "Must include"))
        answer = line(body, "Answer")
        if cid == "Q02":
            names = re.search(r"10 items:\s*(.+?)\.\"", answer)
            if not names:
                raise ValueError("Q02 answer format changed; update the compiler explicitly")
            must_include += [name.strip() for name in re.split(r",\s*(?:and\s+)?|\s+and\s+", names.group(1))]
        if cid == "Q09":
            must_include += re.findall(r"D-\d{3}", answer)
        citation_text = line(body, "Must cite")
        must_cite = re.findall(r"`([^`]+)`", citation_text)
        show = line(body, "Shows")
        show_parts = list(dict.fromkeys(re.findall(r"D-\d{3}", show)))
        if "parts-list-only" in show:
            row = next((c.rsplit("/", 1)[0] for c in must_cite if c.startswith("BOM:")), None)
            if not row:
                raise ValueError(f"{cid} missing BOM attachment identity")
            show_parts = [row + "/part"]
        behavior = line(body, "Behavior")
        cases.append({"id": cid, "category": categories[-1].group(1), "question": question,
                      "expected_answer": body, "answer_excerpt": answer,
                      "must_include": list(dict.fromkeys(must_include)),
                      "must_not_include": re.findall(r"`([^`]+)`", line(body, "Must not include")),
                      "must_cite": must_cite, "citation_instruction": citation_text,
                      "must_show_parts": show_parts, "compact_list": "compact parts list" in show,
                      "show_instruction": show, "needs_3d": "with 3D" in show,
                      "behavior": "undetermined" if "`undetermined`" in behavior else "no_evidence" if "`no_evidence`" in behavior else "answer",
                      "behavior_fact": next(iter(re.findall(r"`([^`]+/[^`]+)`", behavior)), None),
                      "allows_abstention": cid == "Q12", "milestone": re.search(r"From (M\d)", match.group(3)).group(1),
                      "rule_notes": notes(cid)})
    if [c["id"] for c in cases] != CASE_IDS:
        raise ValueError("Canonical draft must contain Q01–Q20 with Q11a/b (21 cases), in order")
    return {"schema_version": 1, "source": path.name, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "ground_truth_status": "draft; not approved by Jason", "cases": cases}


def notes(cid: str) -> list[str]:
    """Legacy capture annotations only; current requirements live in contracts.py."""
    result = []
    if cid in {"Q05", "Q20"}:
        result.append("Literal prohibited-word rules are unchanged: even negated occurrences fail. Semantic judge evaluates the actual claim separately. No Jason-approved exception exists.")
    if cid == "Q11b":
        result.append("Automated verification workflow acceptance substitutes its true reviewer attribution for the draft's Jason attribution; this is not a human approval. Key values/citations remain unchanged.")
    if cid == "Q08":
        result.append("Four flagged drawing links require verification; unresolved links keep this case pending. Actual links/deduplication are recorded in preconditions.")
    if cid == "Q18":
        result.append("Missing recorded prices show incomplete evidence, not proof that the real cost is strictly greater; judge must not demand that unsupported draft inference.")
    if cid == "Q09":
        result.append("Exact printed EN-AW grade notation is a literal source match, not a general-material mapping. No family-mapping approval is needed for this exact-grade query.")
    if cid == "Q20":
        result.append("No Shows instruction exists in the draft; an attached supplier part is permitted, not required to be absent.")
    if cid == "Q17":
        result.append("Approximate planning weights are not literal checks; compare actual tool density table and model variants. FAILED/manual-review disclosure remains required.")
    return result


def markers(text: str) -> dict[str, set[str]]:
    result = {"cite": set(), "undetermined": set()}
    for match in MARKER.finditer(text):
        result[match.group(1).casefold()].update(n.strip() for n in match.group(2).split(",") if n.strip())
    return result


def matching_counts(text: str, expected_parts: list[dict]) -> list[dict]:
    """Check totals or explicitly enumerated groups, never infer a new oracle.

    A subgroup count is supported only by distinct cited reference identities in
    its adjacent bullet list, plus an explicit, source-linked remainder. Meaning
    and claims about physical identity remain the independent judge's job.
    """
    text = text.replace("*", "")
    expected = {p["id"] for p in expected_parts}

    def identities(fragment):
        refs = markers(fragment)
        cited = refs["cite"] | refs["undetermined"]
        return {p["id"] for p in expected_parts if any(
            name == p["id"] or name.startswith(p["id"].rsplit("/", 1)[0] + "/") for name in cited)}

    rows = []
    for match in re.finditer(r"\b(\d+)\s+(?:matching\s+)?parts\b", MARKER.sub(lambda m: " " * len(m[0]), text), re.I):
        count = int(match[1])
        row = {"stated": count, "scope": "catalog", "expected": len(expected), "passed": count == len(expected)}
        if not row["passed"]:
            end = text.find("\n", match.end())
            heading = text[text.rfind("\n", 0, match.start()) + 1:end if end >= 0 else len(text)]
            tail = text[end + 1:] if end >= 0 else ""
            lines = tail.splitlines(keepends=True)
            while lines and not lines[0].strip():
                lines.pop(0)
            bullets = []
            while lines and re.match(r"^\s*[-+]\s+", lines[0]):
                bullets.append(lines.pop(0))
            groups = [identities(line) for line in bullets]
            listed = set().union(*groups) if groups else set()
            remainder = "".join(lines)
            explicit_remainder = bool(re.search(r"\b(?:more|additional|remaining|other)\b", MARKER.sub("", remainder), re.I))
            total_claim = bool(re.search(r"\b(?:total|altogether|in all)\b", heading, re.I))
            if (not total_claim and count == len(listed)
                    and groups and all(groups)
                    and explicit_remainder and expected - listed
                    and expected - listed <= identities(remainder)):
                row.update(scope="enumerated_group_with_explicit_remainder", expected=len(listed), passed=True)
        rows.append(row)
    return rows


def score_rules(case: dict, response: dict, preconditions: list[dict] | None = None,
                reference: dict | None = None) -> dict:
    text = response.get("text", "")
    # Markers alone cannot substitute for an answer. Rendered identity cards can.
    shown_text = MARKER.sub("", text)
    found = markers(text)
    cited = found["cite"] | found["undetermined"]
    facts = response.get("facts", {})
    cards = response.get("parts_to_show", [])
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: Any = None):
        checks.append({"rule": name, "passed": bool(passed), "detail": detail})

    cid = case["id"]
    reference = reference or {}
    abstain = case["allows_abstention"] and "D-023/drawing/weight_g" in found["undetermined"]
    # Meaning (negation, translations, snapshot qualification, unknown prices)
    # is tested by the independent judge, not by prohibited-word substring tests.
    required = case["must_include"] if cid not in {"Q02", "Q03", "Q05", "Q08", "Q09", "Q12", "Q13", "Q17", "Q20"} else []
    if cid == "Q05":
        required = ["DTU"]
    if cid == "Q20":
        required = ["Max Photonics"]
    if cid == "Q17":
        required = ["25", "15"]
    if cid == "Q11b":
        required = ["Silicone gasket for f-theta lens"]
    missing = [v for v in required if not contains(shown_text, v)]
    check("key_values", abstain or not missing, {"required": required, "missing": missing})

    def value(name):
        return facts.get(name, {}).get("display", {}).get("value")

    def card_id(card):
        return card.get("id") or (str(card.get("key", "")) + "/part")

    if cid == "Q02":
        names = [r["name"] for r in reference.get("bom_rows", [])] or case["must_include"][1:]
        check("complete_bom_list", all(contains(shown_text, n) for n in names),
              {"missing": [n for n in names if not contains(shown_text, n)]})
        expected = reference.get("bom_row_count", 10)
        counts = re.findall(r"\b(\d+)\s+(?:parts[ -]list items|parts[ -]list rows|parts|items)\b|\btotal\s+(?:to|of|is)\s+(\d+)\b", shown_text.replace("*", ""), re.I)
        stated = [int(a or b) for a, b in counts]
        check("consistent_bom_count", all(n == expected for n in stated), {"expected": expected, "stated": stated})
    if cid in {"Q08", "Q09"}:
        expected_parts = reference.get("parts", [])
        if cid == "Q08":
            check("independent_list_reference", bool(expected_parts), "List coverage requires an answer-independent catalog snapshot")
        if cid == "Q09" and not expected_parts:
            expected_parts = [{"id": did + "/part", "key": did} for did in case["must_include"]]
        def identified(p):
            identity = p["id"]
            # A real named card is visible in the answer; a naked marker is not.
            card = any(card_id(c) == identity and c.get("display_name") for c in cards)
            name = p.get("display_name") or value(identity)
            prose = contains(shown_text, p["key"]) or bool(isinstance(name, str) and contains(shown_text, name))
            linked = identity in cited or any(n.startswith(p["key"] + "/") for n in cited)
            return bool(card or (prose and linked))
        if expected_parts:
            check("complete_material_list", all(identified(p) for p in expected_parts),
                  {"expected_count": len(expected_parts), "missing": [p["key"] for p in expected_parts if not identified(p)]})
        if cid == "Q08" and expected_parts:
            counts = matching_counts(text, expected_parts)
            check("consistent_matching_count", all(row["passed"] for row in counts),
                  {"matching_records": len(expected_parts), "counts": counts})
    if cid == "Q12" and not abstain:
        # Accept grams or kilograms, including sensible rounding of a conversion.
        weight = value("D-023/drawing/weight_g")
        quantities = [(n.replace(",", ""), unit.casefold()) for n, unit in
                      re.findall(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*(kg|kilograms?|g|grams?)\b", shown_text.replace("*", ""), re.I)]
        def matches_precision(n, unit):
            stated = Decimal(n)
            expected = Decimal(str(weight)) / (1000 if unit.startswith("k") else 1)
            return expected.quantize(Decimal(1).scaleb(stated.as_tuple().exponent), rounding=ROUND_HALF_UP) == stated
        matches = isinstance(weight, (float, int)) and any(matches_precision(n, u) for n, u in quantities)
        check("weight_value_and_unit", matches, {"source_grams": weight, "stated": quantities})
    missing_cites = []
    for expected in case["must_cite"]:
        if expected.startswith("README/") and "..." in expected:
            valid = any(n.startswith(expected.split("...")[0]) for n in cited)
        else:
            valid = expected in cited
        if not valid:
            missing_cites.append(expected)
    if case["id"] == "Q18":
        valid = any("summary" in n and any(v in n for v in ("cost", "total")) for n in cited)
        if not valid:
            missing_cites.append("the cost summary (stable summary citation)")
    if case["id"] == "Q16":
        # Stable template names vary with generated schema. Inspect cited evidence,
        # never accept '8' alone or an unrelated whole-part citation.
        valid = any(n.startswith("D-013/") and ("/template/" in n or "/drawing/" in n)
                    and contains(canonical(facts.get(n, {})), "M3") for n in cited)
        if not valid:
            missing_cites.append("D-013 cited M3 template feature or drawing callout")
    check("citations", not missing_cites, missing_cites)
    invalid = [n for n in cited if n not in facts]
    invalid += [n for n in found["undetermined"] if facts.get(n, {}).get("display", {}).get("state") != "undetermined"]
    naked_unknown = [n for n in found["cite"] if facts.get(n, {}).get("display", {}).get("state") == "undetermined" and n not in found["undetermined"]]
    malformed = re.findall(r"\[(?:cite|undetermined)\b[^\]]*(?:\]|$)", MARKER.sub("", text), re.I)
    check("clean_output", not response.get("warnings") and not invalid and not naked_unknown and not malformed and bool(text.strip()) and bool(cited),
          {"warnings": response.get("warnings", []), "invalid": invalid, "unmarked_unknown": naked_unknown, "malformed": malformed, "has_evidence_markers": bool(cited)})
    if cid == "Q13":
        known = [n for n in cited if n.startswith("D-017/template/outline/") and n.endswith(("/width", "/length"))
                 and facts.get(n, {}).get("display", {}).get("state") == "value"]
        unknown = [n for n in found["undetermined"] if n.startswith("D-017/")]
        check("interpreted_dimension_or_abstention", bool(known or unknown),
              "An interpreted dimension, or an honest unknown; raw number boxes alone cannot establish an axis")
    elif case["behavior"] == "undetermined":
        target = case["behavior_fact"]
        relevant = {target} if target else {n for n in facts if n.startswith("D-017/") and n != "D-017/part"}
        check("behavior", bool(relevant & found["undetermined"]), {"expected": "undetermined", "targets": sorted(relevant)})
    elif case["behavior"] == "no_evidence":
        check("behavior", bool(re.search(r"no evidence|not (?:recorded|provided|specified|given)|(?:do(?:es)? not|doesn't|don't) (?:give|provide|specify)|cannot determine|can't determine|(?:gives?|provides?|specifies?) no (?:tightening )?torque", shown_text.replace("’", "'"), re.I)), "Explicit absence of torque evidence required")
        check("no_invented_torque", not re.search(r"\d+(?:\.\d+)?\s*(?:N\s*[.·]?\s*m|newton[ -]met(?:er|re)s?)\b", shown_text, re.I), "A denial may mention Nm; an unsupported numeric torque fails")
    else:
        unknown_targets = [n for n in case["must_cite"] if n in found["undetermined"]]
        allowed_unknowns = cid in {"Q05", "Q10"} or abstain
        check("behavior", allowed_unknowns or not unknown_targets, "Unknown fields do not invalidate separately known source fields")
    if case["compact_list"]:
        check("parts_shown", len({p.get("key") or p.get("id") for p in cards}) >= 4, {"compact_list_threshold": 4, "count": len(cards)})
    elif case["show_instruction"]:
        wanted = set(case["must_show_parts"])
        actual = {p.get("key") if str(p.get("key", "")).startswith("D-") else p.get("id") for p in cards}
        check("parts_shown", actual == wanted, {"expected": sorted(wanted), "actual": sorted(actual, key=str)})
    if case["needs_3d"]:
        check("3d_examples", bool(cards) and all(p.get("has_3d") and p.get("model_url") and len(p.get("examples", [])) >= 2 for p in cards), "Attached model URL and both A/B variants")
    if case["id"] == "Q13":
        check("dimension_highlight_metadata", any(str(s.get("name", "")).startswith("D-017/drawing/n/") and s.get("box")
              for n in cited for s in facts.get(n, {}).get("sources", [])), "Cited evidence must expose unlabeled number drawing boxes; browser rendering is verified separately")
    # Correct behavior under a pending mapping is testable now. Keep its coverage
    # debt separate from hard setup prerequisites such as the Q11 lifecycle.
    coverage = [p for p in preconditions or [] if p.get("status") != "met" and p.get("name") in {
        "approved_optical_optics_mapping", "approved_material_mappings", "four_flagged_drawing_links_verified"}]
    pending = [p for p in preconditions or [] if p.get("status") != "met" and p not in coverage]
    passed = all(c["passed"] for c in checks)
    return {"status": "fail" if not passed else "pending_precondition" if pending else "pass", "all_checks_pass": passed,
            "checks": checks, "preconditions": preconditions or [], "coverage_gaps": coverage,
            "evaluation_contract": contract(case)}


def judge_payload(case: dict, execution: dict, manifest: dict) -> dict:
    response = execution.get("response", {})
    payload = {"schema_version": VERSION, "source_sha256": manifest["source_sha256"],
               "code_sha256": manifest["code_sha256"], "settings_sha256": manifest["settings_sha256"],
               "case_id": case["id"], "category": case["category"], "question": case["question"],
               "evaluation_contract": contract(case), "returned_facts": response.get("facts", {}),
               "returned_parts": response.get("parts_to_show", []),
               "answer": response.get("text", ""), "chat_model": response.get("model", "gpt-6-luna"), "judge": JUDGE,
               "evaluation_context": {"preconditions": execution.get("preconditions", []),
                                      "workflow": execution.get("workflow", {}),
                                      "independent_reference": execution.get("evaluation_reference", {})}}
    return {**payload, "cache_key": fingerprint(payload)}


def load_judgments(path: Path | None, expected_keys: set[str]) -> dict:
    result = {}
    if path is None:
        return result
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        if row.get("cache_key") not in expected_keys:
            raise ValueError(f"Unknown/stale judge cache key at line {number}")
        # Failed reader attempts are retained in append-only judge logs. They
        # never supply a score and may be followed by a successful retry.
        if row.get("valid") is False and row.get("score") is None:
            continue
        if row.get("judge") != JUDGE or type(row.get("score")) is not int or row["score"] not in (0, 1, 2):
            raise ValueError(f"Invalid independent judge identity/score at line {number}")
        if not isinstance(row.get("unsupported_claims"), list) or not all(isinstance(v, str) for v in row["unsupported_claims"]) or not isinstance(row.get("reason"), str):
            raise ValueError(f"Invalid judge schema at line {number}")
        key = row["cache_key"]
        decision = lambda item: {k: item[k] for k in ("score", "unsupported_claims", "reason", "judge")}
        if key in result and canonical(decision(result[key])) != canonical(decision(row)):
            raise ValueError(f"Conflicting judge result at line {number}")
        result[key] = row
    return result


def report_results(fixture: dict, manifest: dict, executions: list[dict], judgments: dict) -> dict:
    cases = {c["id"]: c for c in fixture["cases"]}
    results, payloads = [], []
    for execution in executions:
        case = cases[execution["case_id"]]
        rules = score_rules(case, execution.get("response", {}), execution.get("preconditions", []), execution.get("evaluation_reference"))
        if execution.get("error"):
            rules["status"] = "fail"
            rules["all_checks_pass"] = False
        payload = judge_payload(case, execution, manifest)
        payloads.append(payload)
        judge = judgments.get(payload["cache_key"])
        if execution.get("error") or rules["status"] == "fail" or (judge and judge["score"] != 2):
            combined = "fail"
        elif rules["status"] == "pending_precondition":
            combined = "pending_precondition"
        elif judge is None:
            combined = "pending_judge"
        else:
            combined = "pass"
        results.append({"pass": execution["pass"], "case_id": case["id"], "category": case["category"], "rules": rules,
                        "judge": judge, "judge_cache_key": payload["cache_key"], "combined": combined,
                        "error": execution.get("error"), "latency_ms": execution.get("response", {}).get("latency_ms"),
                        "wall_latency_ms": execution.get("wall_latency_ms"), "usage": execution.get("response", {}).get("usage"),
                        "workflow_setup_usage": execution.get("workflow_setup", {}).get("usage"),
                        "pending_precondition_abstention": bool(markers(execution.get("response", {}).get("text", ""))["undetermined"]) if rules["status"] == "pending_precondition" else None,
                        "cost": {"status": "unknown", "amount_usd": None, "reason": "No provider monetary receipt returned by chat API"}})

    def stats(rows):
        n = len(rows)
        eligible = [r for r in rows if r["rules"]["status"] != "pending_precondition"]
        return {"executions": n, "rules_pass": sum(r["rules"]["status"] == "pass" for r in rows),
                "rules_pass_rate_all": sum(r["rules"]["status"] == "pass" for r in rows) / n if n else None,
                "rules_applicable_executions": len(eligible),
                "rule_predicates_pass_including_pending": sum(r["rules"]["all_checks_pass"] for r in rows),
                "pending_preconditions": sum(r["rules"]["status"] == "pending_precondition" for r in rows),
                "executions_with_coverage_gaps": sum(bool(r["rules"].get("coverage_gaps")) for r in rows),
                "judge_scores": {str(v): sum(r["judge"] is not None and r["judge"]["score"] == v for r in rows) for v in (0, 1, 2)},
                "judge_pending": sum(r["judge"] is None for r in rows), "combined_pass": sum(r["combined"] == "pass" for r in rows),
                "combined_pass_rate_all": sum(r["combined"] == "pass" for r in rows) / n if n else None,
                "combined_pending": sum(r["combined"].startswith("pending") for r in rows)}

    repeatability = []
    for cid in CASE_IDS:
        pair = [r for r in results if r["case_id"] == cid]
        if len(pair) != 2:
            continue
        a, b = pair
        rules_same = [{k: c[k] for k in ("rule", "passed")} for c in a["rules"]["checks"]] == [{k: c[k] for k in ("rule", "passed")} for c in b["rules"]["checks"]]
        judged = a["judge"] is not None and b["judge"] is not None
        repeatability.append({"case_id": cid, "same_rule_result": rules_same and a["rules"]["status"] == b["rules"]["status"],
                              "same_judge_score": a["judge"]["score"] == b["judge"]["score"] if judged else None,
                              "same_combined_result": a["combined"] == b["combined"] if judged else None})
    token_totals = {k: sum((r["usage"] or {}).get(k, 0) or 0 for r in results) for k in ("input_tokens", "output_tokens", "total_tokens")}
    expected_executions = manifest.get("expected_executions", 42)
    report = {"schema_version": VERSION, "evaluation_version": VERSION, "manifest": manifest, "ground_truth_status": fixture["ground_truth_status"],
              "capture_completeness": {"expected_executions": expected_executions, "captured_executions": len(executions),
                                       "missing_executions": max(0, expected_executions - len(executions)),
                                       "complete": len(executions) == expected_executions},
              "summary": stats(results), "categories": {c: stats([r for r in results if r["category"] == c]) for c in dict.fromkeys(r["category"] for r in results)},
              "passes": {str(p): stats([r for r in results if r["pass"] == p]) for p in (1, 2)}, "results": results,
              "repeatability": {"paired_cases": len(repeatability), "same_rule_results": sum(r["same_rule_result"] for r in repeatability),
                                "same_combined_results": sum(r["same_combined_result"] is True for r in repeatability),
                                "combined_pairs_pending_judge": sum(r["same_combined_result"] is None for r in repeatability), "cases": repeatability},
              "measured_usage": token_totals, "usage_missing_executions": sum(r["usage"] is None for r in results),
              "workflow_setup_usage": {k: sum((r["workflow_setup_usage"] or {}).get(k, 0) or 0 for r in results) for k in ("input_tokens", "output_tokens", "total_tokens")},
              "total_wall_latency_ms": sum(r["wall_latency_ms"] or 0 for r in results),
              "provider_cost": {"status": "unknown", "amount_usd": None},
              "human_judge_spot_check": {"status": "pending", "decisions_checked": 0, "reviewer": None,
                                         "note": "No human review is inferred from benchmark execution or automated acceptance."}}
    return {"report": report, "judge_payloads": payloads}
