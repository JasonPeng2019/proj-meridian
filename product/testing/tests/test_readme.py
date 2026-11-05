"""Minimal source-integrity and stable passage regression cases for M27."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))
from backend.loader.readme import ReadmeError, extract_passages, load_readme, search_passages


def test_paragraphs_keep_original_order_repeat_heading_ids_and_literal_search():
    source = "# Machine\n\nFirst **recorded** paragraph.\n\n## System\n\nLaser power is recorded.\n\n## System\n\nSecond section occurrence.\n"
    passages = extract_passages(source, "a" * 64)
    assert [p.name for p in passages] == ["README/machine/p1", "README/system/p1", "README/system/p2"]
    assert passages[0].text == "First recorded paragraph."
    assert search_passages(passages, "LASER recorded") == [passages[1]]
    assert all(p.snapshot_note and p.source_sha256 == "a" * 64 for p in passages)


def test_html_is_text_only_and_missing_images_and_native_cad_are_not_invented_assets():
    source = '# Context\n\n<p>Source statement <img src="misc/omitted.png" alt="Machine" /></p>\n<script>secret()</script>\n\n[Native file](CAD/part.step)\n\n![Diagram](missing.svg)'
    passages = extract_passages(source, "b" * 64)
    assert "secret()" not in " ".join(p.text for p in passages)
    assert passages[0].missing_images == ["misc/omitted.png"]
    assert "<img" not in passages[0].text
    assert passages[1].mentions_unavailable_native_cad
    assert passages[2].missing_images == ["missing.svg"]
    assert "CAD/part.step" in passages[1].text


def test_manifest_binds_exact_upstream_source_and_refuses_changes(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    original = b"# Original machine\n\nRead this source.\n"
    source = dataset / "machine.md"
    source.write_bytes(original)
    manifest = {"assets": [{"id": "OPENLPBF-README", "path": "dataset/machine.md",
                            "sha256": hashlib.sha256(original).hexdigest()}]}
    (dataset / "manifest.json").write_text(json.dumps(manifest))
    assert load_readme(tmp_path)[0].text == "Read this source."
    source.write_text("# Replaced source\n")
    with pytest.raises(ReadmeError, match="bytes"):
        load_readme(tmp_path)


@pytest.mark.parametrize("asset", [[], [{"id": "OPENLPBF-README", "path": "../outside.md", "sha256": "0" * 64}]])
def test_missing_identity_and_escaping_source_are_rejected(tmp_path, asset):
    (tmp_path / "dataset").mkdir()
    (tmp_path / "dataset/manifest.json").write_text(json.dumps({"assets": asset}))
    with pytest.raises(ReadmeError):
        load_readme(tmp_path)


def test_real_supplied_upstream_document_is_distinct_from_submission_readme():
    passages = load_readme(ROOT / "development/inputs/project-meridian")
    assert len(passages) > 10
    assert any("OpenLPBF" in p.text or "L-PBF" in p.text for p in passages)
    assert any(p.missing_images for p in passages)
    assert len({p.name for p in passages}) == len(passages)
