"""Privacy and safe extraction checks for deliverable archives."""
import json
import zipfile

import pytest

from scripts.package_delivery import allowed, extract


@pytest.mark.parametrize('name', ['.env', '.env.production', '.codex/config.toml', '.codex/.secrets/key.txt',
                                '.runtime/chats/test.json', '.venv/bin/python', '../outside', '/outside',
                                'Meridian/../../outside', 'Meridian\\..\\outside', 'frontend/node_modules/test'])
def test_private_or_escaping_paths_are_excluded(name):
    assert not allowed(name)


@pytest.mark.parametrize('name', ['.env.example', 'generated/records.json', 'decisions/HD-test.json',
                                'frontend/dist/index.html', 'README.md', 'generated/ai_cache/artifacts/cad/file.glb'])
def test_required_runtime_data_and_example_config_are_allowed(name):
    assert allowed(name)


def test_archive_escape_is_rejected_before_any_extraction(tmp_path):
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('Meridian/../../outside', 'no')
    destination = tmp_path / 'extracted'
    with pytest.raises(ValueError, match='Unsafe archive'):
        extract(path, destination)
    assert not destination.exists()


def test_incomplete_manifest_is_rejected(tmp_path):
    path = tmp_path / 'mismatch.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('Meridian/DELIVERY-MANIFEST.json', json.dumps({'files': {}}))
        z.writestr('Meridian/unlisted.txt', 'unlisted')
    with pytest.raises(ValueError, match='file manifest'):
        extract(path, tmp_path / 'extracted')
