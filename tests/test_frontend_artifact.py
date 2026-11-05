"""Artifact swaps verify provenance/content; no Node, network or builds are used."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import frontend_artifact as artifact


def setup_download(tmp_path, monkeypatch, *, source_ok=True, files_ok=True):
    monkeypatch.setattr(artifact, "ROOT", tmp_path)
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").write_text("old", encoding="utf-8")
    tree = b"100644 blob source-snapshot frontend/src/App.jsx\n"
    monkeypatch.setattr(artifact, "git", lambda *args: b"" if args[0] == "diff" else tree)
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[2] == "view":
            return SimpleNamespace(stdout=json.dumps({"conclusion": "success", "headSha": "commit"}))
        stage = artifact.inside(argv[argv.index("--dir") + 1])
        (stage / "frontend/dist").mkdir(parents=True)
        (stage / "docs/ci").mkdir(parents=True)
        (stage / "frontend/dist/index.html").write_text("remote bundle", encoding="utf-8")
        data = {"commit": "commit", "source_sha256": hashlib.sha256(tree).hexdigest() if source_ok else "different-source",
                "files": {"index.html": hashlib.sha256(b"remote bundle").hexdigest() if files_ok else "invalid-content"}}
        (stage / "docs/ci/frontend-build.json").write_text(json.dumps(data), encoding="utf-8")
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(artifact.subprocess, "run", fake_run)
    return calls


def test_download_installs_matching_bundle_and_retains_previous(tmp_path, monkeypatch):
    calls = setup_download(tmp_path, monkeypatch)
    artifact.fetch(123)
    assert (tmp_path / "frontend/dist/index.html").read_text() == "remote bundle"
    assert next((tmp_path / ".runtime").glob("frontend-backup-*/index.html")).read_text() == "old"
    assert all(argv[0] == "gh" for argv in calls)


@pytest.mark.parametrize("source_ok,files_ok", [(False, True), (True, False)])
def test_bad_provenance_or_content_cannot_replace_local_bundle(tmp_path, monkeypatch, source_ok, files_ok):
    setup_download(tmp_path, monkeypatch, source_ok=source_ok, files_ok=files_ok)
    with pytest.raises(RuntimeError):
        artifact.fetch(123)
    assert (tmp_path / "frontend/dist/index.html").read_text() == "old"
