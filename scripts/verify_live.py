"""Five representative questions twice; saved independently of prep and prompts."""
import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.paths import ROOT, configure_environment, inside

QUESTIONS = [
    ("reconstruction", "What is the Recoater Plate made of? Show its drawing and 3D reconstruction."),
    ("cross_part", "Which parts have Aluminium recorded in the BOM? Give a few examples across machine sections and cite their records."),
    ("procurement", "What supplier and cost are recorded for the timing belt? Can we order it now?"),
    ("uncertainty", "How thick is D-023, and is the original native CAD available in this dataset?"),
    ("machine", "What is the machine's build volume? Cite the supplied documentation."),
]

def main():
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="docs/verification/live-questions.json")
    args = parser.parse_args()
    output = inside(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    saved = {"at": datetime.now(timezone.utc).isoformat(), "purpose": "Independent live behavior observations; not used by prep or model prompts", "runs": []}
    with httpx.Client(base_url=args.url, timeout=180) as client:
        for run in range(2):
            for kind, question in QUESTIONS:
                response = client.post("/api/chat", json={"message": question})
                result = response.json()
                checks = {"http_ok": response.status_code == 200, "model_is_luna": result.get("model") == "gpt-6-luna", "no_citation_warnings": not result.get("warnings")}
                if kind == "reconstruction":
                    checks["drawing_and_3d_attached"] = any(p["key"] == "D-013" and p.get("has_3d") and p.get("thumbnail") for p in result.get("parts_to_show", []))
                if kind == "cross_part":
                    checks["multiple_records"] = len(result.get("parts_to_show", [])) >= 2
                if kind == "procurement":
                    text = result.get("text", "").casefold()
                    checks["snapshot_caveat"] = "snapshot" in text and "out of date" in text
                if kind == "uncertainty":
                    checks["no_evidence_part_attached"] = any(p["key"] == "D-023" for p in result.get("parts_to_show", []))
                if kind == "machine":
                    checks["readme_returned"] = any(name.startswith("README/") for name in result.get("facts", {}))
                saved["runs"].append({"run": run + 1, "kind": kind, "question": question, "checks": checks, "response": result})
                output.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"run {run+1} {kind}: {'PASS' if all(checks.values()) else 'CHECK'} {result.get('latency_ms')}ms {result.get('usage')}", flush=True)
    success = [r for r in saved["runs"] if r["checks"]["http_ok"]]
    times = [r["response"]["latency_ms"] for r in success]
    saved["summary"] = {"passed_scenarios": sum(all(r["checks"].values()) for r in saved["runs"]), "scenarios": len(saved["runs"]),
        "median_latency_ms": statistics.median(times) if times else None, "input_tokens": sum(r["response"].get("usage", {}).get("input_tokens", 0) for r in success),
        "output_tokens": sum(r["response"].get("usage", {}).get("output_tokens", 0) for r in success), "cost_usd": None,
        "cost_note": "Token use measured. Currency cost is not asserted without verified account billing rates.",
        "repeatability": [{"kind": kind, "same_attached_parts": [p["key"] for p in saved["runs"][i]["response"].get("parts_to_show", [])] == [p["key"] for p in saved["runs"][i+5]["response"].get("parts_to_show", [])]} for i,(kind,_) in enumerate(QUESTIONS)]}
    output.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(saved["summary"], indent=2))

if __name__ == "__main__":
    main()
