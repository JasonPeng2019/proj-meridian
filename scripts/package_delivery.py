"""Build a complete, hash-manifested source/data ZIP on the queued runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

from backend.paths import ROOT, inside, configure_environment

PRIVATE = {".git", ".codex", ".vscode", ".runtime", ".cache", ".tmp", ".verification", ".venv", "node_modules", "__pycache__", ".secrets"}


def allowed(name: str) -> bool:
    path = PurePosixPath(name)
    return ('\\' not in name and not path.is_absolute() and ".." not in path.parts and not PRIVATE.intersection(path.parts)
            and not any(part.startswith('.env') and part != '.env.example' for part in path.parts)
            and not name.endswith(('.pyc', '.log')))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output: Path) -> Path:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Delivery archives are built on queued GitHub Actions, not the laptop")
    output = inside(output)
    output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split('\0')
    # A remote frontend build can replace old content-addressed tracked assets.
    names = {name for name in tracked if name and allowed(name) and (ROOT / name).is_file()}
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'frontend/dist').rglob('*') if p.is_file())
    files = {}
    for name in sorted(names):
        path = inside(ROOT / name)
        if path.is_symlink() or not allowed(name):
            raise ValueError("Unsafe delivery input path")
        files[name] = digest(path)
    for required in ('README.md', 'start.sh', 'start.bat', '.python-version', 'Dockerfile', 'compose.yaml',
                     'uv.lock', 'frontend/dist/index.html', 'generated/records.json', 'generated/ai_results.json',
                     'generated/drawings.json', 'generated/bom.json', 'generated/readme.json', 'generated/models/manifest.json'):
        if required not in files:
            raise ValueError("Delivery is incomplete: " + required)
    manifest = {"schema_version": 1, "commit": commit, "files": files,
                "catalog": "Prebuilt JSON catalog; no database server required",
                "includes": ["source evidence", "prepared records", "AI preparation receipts", "review decisions",
                             "drawing images", "GLB/STEP models", "offline recovery caches", "built frontend", "source and tests"],
                "excludes": ["credentials", "personal chat history", "local environments and caches", "editor/agent state"]}
    archive = output / f'meridian-v1-{commit[:8]}.zip'
    if archive.exists():
        raise ValueError("Delivery archive already exists")
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name in files:
            bundle.write(inside(ROOT / name), 'Meridian/' + name)
        bundle.writestr('Meridian/DELIVERY-MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    (output / 'source-checksums.sha256').write_text(digest(archive) + '  ' + archive.name + '\n', encoding='utf-8')
    (output / 'package.json').write_text(json.dumps({"commit": commit, "archive": archive.name,
         "sha256": digest(archive), "file_count": len(files), "size_bytes": archive.stat().st_size}, indent=2) + '\n', encoding='utf-8')
    print(archive.relative_to(ROOT).as_posix())
    return archive


def extract(archive: Path, destination: Path) -> Path:
    archive, destination = inside(archive), inside(destination)
    if destination.exists():
        raise ValueError("Use a fresh extraction directory")
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            path = PurePosixPath(item.filename)
            if not path.parts or path.parts[0] != 'Meridian' or not allowed(item.filename):
                raise ValueError("Unsafe archive member")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive symlinks are forbidden")
            inside(destination / item.filename)
        bundle.extractall(destination)
    app = destination / 'Meridian'
    manifest = json.loads((app / 'DELIVERY-MANIFEST.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(app).as_posix(): digest(p) for p in app.rglob('*')
              if p.is_file() and p.name != 'DELIVERY-MANIFEST.json'}
    if actual != manifest['files']:
        raise ValueError("Extracted delivery does not match its file manifest")
    return app


if __name__ == '__main__':
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist/delivery')
    args = parser.parse_args()
    build(inside(args.output))
