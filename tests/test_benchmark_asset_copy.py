"""Prepared benchmark clones must not inherit stale tracked export caches."""
import pytest

from scripts.run_benchmark import copy_prepared_tree, files_hash


def test_prepared_tree_replaces_stale_clone_files_without_touching_source(tmp_path):
    source = tmp_path / "prepared"
    source.mkdir()
    (source / "current.glb").write_bytes(b"current export")
    clone = tmp_path / "clone"
    target = clone / "generated"
    target.mkdir(parents=True)
    (target / "historical.glb").write_bytes(b"old tracked export")
    baseline = files_hash(source)
    copy_prepared_tree(source, target, clone)
    assert files_hash(target) == baseline == files_hash(source)
    assert not (target / "historical.glb").exists()


def test_prepared_tree_cannot_delete_clone_root_or_sibling(tmp_path):
    source, clone = tmp_path / "source", tmp_path / "clone"
    source.mkdir()
    clone.mkdir()
    with pytest.raises(ValueError):
        copy_prepared_tree(source, clone, clone)
    with pytest.raises(ValueError):
        copy_prepared_tree(source, tmp_path / "other", clone)
