"""A review batch must never dismiss actionable geometry as unsupported."""
import json
from types import SimpleNamespace

import pytest

from backend.app.store import prediction_fingerprint
from scripts import delegated_review


def test_batch_writes_atomic_bound_receipts_then_replays_once(tmp_path, monkeypatch):
    store = delegated_review.DelegatedStore.__new__(delegated_review.DelegatedStore)
    store.decisions_dir = tmp_path / 'decisions'
    store.raw_fields = {name: {'state': 'known', 'value': number, 'method': 'ai_verified'}
                        for number, name in enumerate(('D-001/template/length', 'D-001/template/width'))}
    store.fingerprint = lambda _: 'source'
    store.context = {'action': 'confirm', 'source_fact_ids': ['D-001/drawing/source']}
    reloads = []
    monkeypatch.setattr(delegated_review.Store, 'reload', lambda *_args, **_kwargs: reloads.append(True))
    store.batch_writing = True
    events = [store.append(name, 'confirm') for name in store.raw_fields]
    assert reloads == []
    assert len(list(store.decisions_dir.glob('*.json'))) == 2
    for event in events:
        saved = json.loads((store.decisions_dir / (event['decision_id'] + '.json')).read_text())
        assert saved == event
        assert event['based_on']['sha256'] == 'source'
        assert event['prediction_sha256'] == prediction_fingerprint(store.raw_fields[event['applies_to']])
        assert event['review_kind'] == 'delegated' and event['by'] == delegated_review.ACTOR
    store.batch_writing = False
    store.reload()
    assert reloads == [True]


@pytest.mark.parametrize('change,allowed', [
    ('none', True), ('supported', False), ('uncertain_body', False),
    ('known_input', False), ('stale_prediction', False), ('stale_body', False),
])
def test_disposition_preflight_requires_current_unknown_input_and_unsupported_body(tmp_path, monkeypatch, change, allowed):
    target = 'D-001/template/outline'
    field = {'state': 'unknown', 'value': None}
    body = {'state': 'known', 'value': {'supported': False}}
    operation = {'target': target, 'action': 'defer_unsupported', 'based_on': 'source',
                 'prediction_sha256': prediction_fingerprint(field),
                 'template_capability_sha256': 'current-body',
                 'source_fact_ids': ['D-001/drawing/source'], 'note': 'Source-inspected formed body.'}
    if change == 'supported':
        body['value']['supported'] = True
    elif change == 'uncertain_body':
        body = {'state': 'unknown', 'value': None}
    elif change == 'known_input':
        field = {'state': 'known', 'value': 'rectangle'}
        operation['prediction_sha256'] = prediction_fingerprint(field)
    elif change == 'stale_prediction':
        operation['prediction_sha256'] = 'old-proposal'
    elif change == 'stale_body':
        operation['template_capability_sha256'] = 'old-body'
    decisions = tmp_path / 'decisions'
    decisions.mkdir()
    store = SimpleNamespace(
        revision='revision', decisions_dir=decisions, fields={target: field},
        raw_fields={target: field}, templates={'D-001': {'cad_eligibility': body}},
        mappings=[], rows={}, fingerprint=lambda _: 'source',
        template_capability_fingerprint=lambda _: 'current-body',
        review_items=lambda: [], accuracy=lambda: {},
    )
    monkeypatch.setattr(delegated_review, 'DelegatedStore', lambda: store)
    monkeypatch.setattr(delegated_review, 'source_record', lambda *_: {'source': True})
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'revision': 'revision', 'operations': [operation]}), encoding='utf-8')
    if allowed:
        delegated_review.run(plan)
        assert json.loads((tmp_path / 'dry-run.json').read_text())['operation_count'] == 1
    else:
        with pytest.raises(ValueError):
            delegated_review.run(plan, apply=True)
        assert not (tmp_path / 'applied.json').exists()
    assert list(decisions.iterdir()) == []
