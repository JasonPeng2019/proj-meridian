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
    write("foundation.json", {"outcome": "PASS", "scope": "B00 foundation only; module and product gates are dispatched separately",
                               "checks": results})


def modules():
    """Run the available focused Python module suite in the queued remote slot."""
    suites = ROOT / "testing/tests"
    if not suites.exists() or not any(suites.rglob("test_*.py")):
        write("modules.json", {"outcome": "BLOCKED", "reason": "No focused Python module tests are present"})
        raise SystemExit("No module tests are implemented yet")
    REPORTS.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", str(suites), "-q", "-p", "no:cacheprovider",
               "--basetemp=" + str(ROOT / "testing/tmp/pytest-modules"),
               "--junitxml=" + str(REPORTS / "modules.xml")]
    result = subprocess.run(command, cwd=ROOT / "testing", capture_output=True, text=True,
                            timeout=900)
    (REPORTS / "modules-output.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    write("modules.json", {"outcome": "PASS" if result.returncode == 0 else "FAIL",
                           "scope": "Available focused Python module tests; not a V1-V5 gate verdict",
                           "command": command, "exit_code": result.returncode})
    raise SystemExit(result.returncode)


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


def extract():
    """Publish deterministic producer outputs for prep, without invoking AI."""
    sys.path.insert(0, str(ROOT / "development"))
    from backend.loader.bom import load_bom
    from backend.loader.drawings import load_drawings

    evidence = ROOT / "development/inputs/project-meridian"
    output = ROOT / "testing/runs/deterministic-inputs"
    output.mkdir(parents=True, exist_ok=True)
    drawings = load_drawings(evidence, output, dpi=144)
    rows = load_bom(evidence / "dataset/context/openlpbf-bom.csv")
    inventory = json.loads((evidence / "dataset/manifest.json").read_text(encoding="utf-8"))
    expected_ids = {asset["id"] for asset in inventory["assets"] if asset["path"].lower().endswith(".pdf")}
    assert {drawing.id for drawing in drawings} == expected_ids
    assert len(drawings) == 30 and len(rows) == 192
    payload = {"schema": "meridian-deterministic-inputs/v1",
               "commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
               "scope": "Deterministic source extraction/normalization; no AI or human review",
               "manifest_sha256": hashlib.sha256((evidence / "dataset/manifest.json").read_bytes()).hexdigest(),
               "drawings": [item.model_dump(mode="json") for item in drawings],
               "bom": [item.model_dump(mode="json") for item in rows]}
    (output / "inputs.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    modules = {name: hashlib.sha256((ROOT / "development/backend" / name).read_bytes()).hexdigest()
               for name in ("contracts.py", "loader/drawings.py", "loader/bom.py")}
    write("deterministic-inputs.json", {"outcome": "PASS", "scope": payload["scope"],
                                         "drawings": len(drawings), "bom_rows": len(rows),
                                         "pages": sum(item.pages for item in drawings),
                                         "manifest_sha256": payload["manifest_sha256"], "modules": modules})


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
    parser.add_argument("stage", choices=["foundation", "modules", "manifest", "pdf", "extract", "live"])
    globals()[parser.parse_args().stage]()
