"""Staged prep must not replace an active dataset before remote verification."""
import hashlib
import json

import pytest

from backend.app import main
from backend.app.store import Store
from scripts import prep_candidate


def test_live_requests_keep_complete_snapshot_during_publication(tmp_path, monkeypatch):
    generated = tmp_path / 'generated'
    generated.mkdir()
    (generated / 'records.json').write_text('[]', encoding='utf-8')
    store = Store(tmp_path)
    monkeypatch.setattr(main, '_store', store)
    monkeypatch.setattr(main, '_snapshot_signature', None)
    monkeypatch.setattr(main, '_snapshot_store', None)
    assert main.get_store() is store
    lock = generated / '.publish.lock'
    lock.write_text('fixture installer', encoding='utf-8')
    # A partially promoted JSON file must never be read by the live request.
    (generated / 'records.json').write_text('{incomplete', encoding='utf-8')
    assert main.get_store() is store
    (generated / 'records.json').write_text('[] ', encoding='utf-8')
    lock.unlink()
    assert main.get_store() is not store


def test_cold_start_waits_for_complete_release(tmp_path, monkeypatch):
    (tmp_path / 'generated').mkdir()
    (tmp_path / 'generated/.publish.lock').write_text('fixture', encoding='utf-8')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, '_store', None)
    with pytest.raises(main.HTTPException) as exc:
        main.get_store()
    assert exc.value.status_code == 503


def test_candidate_activation_is_remote_only_and_source_bound(tmp_path, monkeypatch):
    generated = tmp_path / 'generated'
    batch = generated / 'ai_cache/detail-reprepare/fixture'
    candidate = batch / 'candidate/generated'
    candidate.mkdir(parents=True)
    source = generated / 'drawings.json'
    source.write_text('{}', encoding='utf-8')
    live = generated / 'ai_results.json'
    live.write_text('{"live":true}', encoding='utf-8')
    ai = candidate / 'ai_results.json'
    ai.write_text('{"candidate":true}', encoding='utf-8')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    checkpoint = {'complete': True, 'candidate': str(candidate), 'candidate_sha256': digest(ai),
                  'source_hashes': {str(source): digest(source)}}
    (batch / 'checkpoint.json').write_text(json.dumps(checkpoint), encoding='utf-8')
    monkeypatch.setattr(prep_candidate, 'GENERATED', generated)
    monkeypatch.setattr(prep_candidate, 'ROOT', tmp_path)
    monkeypatch.setenv('GITHUB_ACTIONS', 'false')
    before = live.read_bytes()
    with pytest.raises(RuntimeError, match='disposable Actions'):
        prep_candidate.activate(batch)
    assert live.read_bytes() == before
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    source.write_text('{"changed":true}', encoding='utf-8')
    with pytest.raises(ValueError, match='Pinned source changed'):
        prep_candidate.activate(batch)
    assert live.read_bytes() == before
    source.write_text('{}', encoding='utf-8')
    prep_candidate.activate(batch)
    assert live.read_bytes() == ai.read_bytes()


def test_incomplete_candidate_never_activates(tmp_path, monkeypatch):
    generated = tmp_path / 'generated'
    batch = generated / 'ai_cache/detail-reprepare/fixture'
    batch.mkdir(parents=True)
    (batch / 'checkpoint.json').write_text('{"complete":false}', encoding='utf-8')
    monkeypatch.setattr(prep_candidate, 'GENERATED', generated)
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    with pytest.raises(ValueError, match='incomplete'):
        prep_candidate.activate(batch)
