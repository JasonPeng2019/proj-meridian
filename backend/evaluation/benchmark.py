"""Canonical-draft compiler and conservative rule scorer.

Question text and expected answers are read from the draft, never maintained here.
Case-specific code only resolves prose instructions into explicit predicates.
Literal negative checks deliberately remain literal, including negated wording.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any

JUDGE = {"reader": "claude", "model": "opus", "fast_mode": False, "protocol": 1}
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


def score_rules(case: dict, response: dict, preconditions: list[dict] | None = None) -> dict:
    text = response.get("text", "")
    # Markers are presentation metadata, not answer values (e.g. drawing IDs).
    shown_text = MARKER.sub("", text)
    found = markers(text)
    cited = found["cite"] | found["undetermined"]
    facts = response.get("facts", {})
    cards = response.get("parts_to_show", [])
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: Any = None):
        checks.append({"rule": name, "passed": bool(passed), "detail": detail})

    abstain = case["allows_abstention"] and "D-023/drawing/weight_g" in found["undetermined"]
    check("key_values", abstain or all(contains(shown_text, v) for v in case["must_include"]),
          {"required": case["must_include"], "missing": [] if abstain else [v for v in case["must_include"] if not contains(shown_text, v)], "abstention_alternative": abstain})
    prohibited = [v for v in case["must_not_include"] if contains(shown_text, v)]
    check("literal_prohibited_values", not prohibited, prohibited)
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
    if case["behavior"] == "undetermined":
        target = case["behavior_fact"]
        relevant = {target} if target else {n for n in facts if n.startswith("D-017/") and n != "D-017/part"}
        check("behavior", bool(relevant & found["undetermined"]), {"expected": "undetermined", "targets": sorted(relevant)})
    elif case["behavior"] == "no_evidence":
        check("behavior", bool(re.search(r"no evidence|not (?:recorded|provided|specified|given)|(?:do(?:es)? not|doesn't|don't) (?:give|provide|specify)|cannot determine|can't determine|(?:gives?|provides?|specifies?) no (?:tightening )?torque", shown_text.replace("’", "'"), re.I)) and not prohibited, "Explicit absence of torque evidence required; no inferred numeric torque")
    else:
        check("behavior", abstain or not any(n in found["undetermined"] for n in case["must_cite"]), "Answer targets must not be undetermined except draft alternatives")
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
    if case["id"] == "Q17":
        check("failed_weight_review_caveat", contains(shown_text, "FAILED") and bool(re.search(r"manual (?:approval|review)|needs? (?:human )?(?:approval|review)|waiting for review", shown_text, re.I)), "FAILED and manual-review caveat")
    pending = [p for p in preconditions or [] if p.get("status") != "met"]
    passed = all(c["passed"] for c in checks)
    return {"status": "pending_precondition" if pending else "pass" if passed else "fail", "all_checks_pass": passed,
            "checks": checks, "preconditions": preconditions or [], "rule_notes": case["rule_notes"]}


def judge_payload(case: dict, execution: dict, manifest: dict) -> dict:
    response = execution.get("response", {})
    payload = {"schema_version": 1, "source_sha256": manifest["source_sha256"],
               "code_sha256": manifest["code_sha256"], "settings_sha256": manifest["settings_sha256"],
               "case_id": case["id"], "category": case["category"], "question": case["question"],
               "expected_answer": case["expected_answer"], "returned_facts": response.get("facts", {}),
               "answer": response.get("text", ""), "chat_model": response.get("model", "gpt-6-luna"), "judge": JUDGE,
               "evaluation_context": {"preconditions": execution.get("preconditions", []), "rule_notes": case["rule_notes"],
                                      "workflow": execution.get("workflow", {})}}
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
        rules = score_rules(case, execution.get("response", {}), execution.get("preconditions", []))
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
    report = {"schema_version": 1, "manifest": manifest, "ground_truth_status": fixture["ground_truth_status"],
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
