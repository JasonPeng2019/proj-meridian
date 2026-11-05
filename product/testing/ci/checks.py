"""Small remote entry points; capability results never count as product gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "testing/reports/ci"


def write(name, data):
    REPORTS.mkdir(parents=True, exist_ok=True)
    data = {"commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"), **data}
    (REPORTS / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def source_hash():
    frontend = ROOT / "development/frontend"
    paths = [*sorted((frontend / "src").rglob("*"))]
    paths += [frontend / name for name in ("index.html", "package.json", "package-lock.json", "vite.config.ts")]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            payload = path.read_bytes()
            if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".html", ".svg"}:
                payload = payload.replace(b"\r\n", b"\n")
            digest.update(path.relative_to(frontend).as_posix().encode() + b"\0" + payload)
    return digest.hexdigest()


def foundation():
    commands = [
        [sys.executable, str(ROOT / "testing/reports/b00/A01-scaffold/smoke_checks.py")],
        [sys.executable, str(ROOT / "testing/smoke/A02-contracts/check_contracts.py")],
    ]
    suites = ROOT / "testing/tests"
    available = suites.exists() and any(suites.rglob("test_*.py"))
    if available:
        commands.append([sys.executable, "-m", "pytest", str(suites), "--junitxml=" + str(REPORTS / "pytest.xml")])
    results = []
    REPORTS.mkdir(parents=True, exist_ok=True)
    for index, command in enumerate(commands):
        result = subprocess.run(command, cwd=ROOT / "testing", capture_output=True, text=True)
        (REPORTS / f"python-{index}.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
        results.append({"command": command, "exit_code": result.returncode})
        print(result.stdout, end="")
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            write("foundation.json", {"outcome": "FAIL", "checks": results})
            raise SystemExit(result.returncode)
    write("foundation.json", {"outcome": "PASS", "scope": "B00 foundation plus available tests",
                               "product_gate_suites_present": bool(available), "checks": results})


def manifest():
    dist = ROOT / "development/frontend/dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("Frontend build is missing")
    files = {p.relative_to(dist).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(dist.rglob("*")) if p.is_file()}
    write("frontend-build.json", {"schema": "meridian-frontend-build/v1", "source_sha256": source_hash(), "files": files})


def pdf():
    import fitz
    evidence = ROOT / "development/inputs/project-meridian"
    inventory = json.loads((evidence / "dataset/manifest.json").read_text())
    output = ROOT / "testing/runs/pdf-regeneration"
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for asset in inventory["assets"]:
        source = (evidence / asset["path"]).resolve()
        if source.suffix.lower() != ".pdf":
            continue
        assert source.is_relative_to(evidence.resolve())
        assert hashlib.sha256(source.read_bytes()).hexdigest() == asset["sha256"]
        identifier = asset["id"]
        folder = (output / identifier).resolve()
        assert folder.is_relative_to(output.resolve())
        folder.mkdir(parents=True, exist_ok=True)
        pages = []
        with fitz.open(source) as document:
            for number, page in enumerate(document):
                page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False).save(folder / f"page-{number+1}.png")
                pages.append({"page": number + 1, "width": page.rect.width, "height": page.rect.height,
                              "words": page.get_text("words")})
        record = {"id": identifier, "source_sha256": asset["sha256"], "pages": pages}
        (folder / "positioned-text.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
        records.append({"id": identifier, "pages": len(pages)})
    assert records, "No PDF assets were extracted"
    write("pdf-regeneration.json", {"outcome": "PASS", "scope": "Raw positioned PDF capability; no interpreted domain facts or AI",
                                    "assets": records})


def live():
    from openai import OpenAI
    if not os.environ.get("OPENAI_API_KEY"):
        write("live.json", {"outcome": "BLOCKED", "reason": "HARNESS_V2_OPENAI_API_KEY is not available"})
        raise SystemExit("No Actions secret: ROOT may use the authorized serial local API fallback")
    started = time.monotonic()
    try:
        answer = OpenAI(max_retries=0, timeout=60).responses.create(
            model="gpt-6-luna", input="Reply with exactly MERIDIAN_LIVE_OK", max_output_tokens=128, store=False)
        text = answer.output_text.strip()
        passed = text == "MERIDIAN_LIVE_OK"
        write("live.json", {"outcome": "PASS" if passed else "FAIL", "scope": "Luna API capability, not product chat verification",
                            "requested_model": "gpt-6-luna", "effective_model": answer.model,
                            "answer": text, "usage": answer.usage.model_dump() if answer.usage else None,
                            "seconds": time.monotonic() - started})
        if not passed:
            raise SystemExit("Unexpected Luna capability response")
    except Exception as error:
        write("live.json", {"outcome": "FAIL", "error_type": type(error).__name__,
                            "status_code": getattr(error, "status_code", None)})
        raise SystemExit("Live API probe failed; see the sanitized report") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["foundation", "manifest", "pdf", "live"])
    globals()[parser.parse_args().stage]()
