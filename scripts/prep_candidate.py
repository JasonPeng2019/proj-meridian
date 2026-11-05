"""Activate a staged prep candidate only on a disposable Actions checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from backend.paths import GENERATED, ROOT, configure_environment, inside


def digest(path):
    return hashlib.sha256(inside(path).read_bytes()).hexdigest()


def validate(batch):
    batch = inside(batch)
    if not batch.is_relative_to(GENERATED / 'ai_cache/detail-reprepare'):
        raise ValueError('Candidate must be an existing detail-prep batch')
    checkpoint = json.loads((batch / 'checkpoint.json').read_text(encoding='utf-8'))
    if checkpoint.get('complete') is not True:
        raise ValueError('Candidate prep is incomplete')
    candidate = inside(checkpoint['candidate'].replace('\\', '/'))
    if candidate != batch / 'candidate/generated':
        raise ValueError('Candidate location differs from its batch')
    if digest(candidate / 'ai_results.json') != checkpoint.get('candidate_sha256'):
        raise ValueError('Candidate data changed after prep')
    for name, expected in checkpoint['source_hashes'].items():
        if digest(inside(name.replace('\\', '/'))) != expected:
            raise ValueError('Pinned source changed since candidate prep: ' + name)
    return candidate


def activate(batch):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Candidate activation is limited to the disposable Actions checkout; use the verified artifact installer locally')
    candidate = validate(batch)
    for target in (GENERATED / 'ai_results.json', GENERATED / 'ai_cache/artifacts/ai_results.json'):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate / 'ai_results.json', target)
    print(json.dumps({'candidate_activated_on_actions': str(candidate.relative_to(ROOT)),
                      'ai_results_sha256': digest(GENERATED / 'ai_results.json')}))


if __name__ == '__main__':
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    activate(parser.parse_args().batch)
