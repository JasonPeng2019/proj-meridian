"""The prep gate screens body capability before expensive numeric extraction."""
import hashlib

import pytest

from scripts.detail_reprepare import screen_job, verify_original_sources


def test_qualitative_screen_requests_only_body_capability():
    drawing = {'id': 'D-TEST', 'images': ['images/fixture.png'], 'fields': {}}
    job = screen_job(drawing)
    assert job['keys'] == ['cad_eligibility'] and job['numbers'] == {}
    assert job['kind'] == 'template' and job['images']
    assert 'D-TEST/drawing/source' in job['sources']
    assert 'Do not transcribe numeric dimensions' in job['prompt']
    assert 'Missing numeric evidence or hole positions alone' in job['prompt']


def test_source_bytes_must_match_extraction_before_cached_routing(tmp_path):
    source = tmp_path / 'fixture.pdf'
    source.write_bytes(b'not rendered; source-binding fixture')
    drawing = {'source_path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    verify_original_sources({'D-TEST': drawing})
    source.write_bytes(b'changed source, same extraction metadata')
    with pytest.raises(ValueError, match='original PDF changed'):
        verify_original_sources({'D-TEST': drawing})
