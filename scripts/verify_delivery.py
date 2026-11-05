"""Exercise README uv startup from the actual ZIP on a clean hosted runner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import httpx

from backend.paths import ROOT, inside, configure_environment
from scripts.package_delivery import extract, digest
from scripts import verify_release as release


def wait(url, proc=None):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError('Packaged launcher exited; see delivery-startup.log')
        try:
            response = httpx.get(url + '/api/status', timeout=2)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.5)
    raise RuntimeError('Packaged runtime startup timed out')


def inspect(app, url):
    release.CLONE = app
    expected = release.model_inventory(json.loads((app / 'generated/models/manifest.json').read_text(encoding='utf-8')))
    with httpx.Client(base_url=url, timeout=30) as client:
        result = release.inspect(client, expected)
        page = client.get('/').text
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page)
        assert assets and all(client.get(asset).status_code == 200 for asset in assets)
        result['frontend_assets_checked'] = assets
        return result


def main():
    configure_environment()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Delivery verification runs on the queued runner')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['native'])
    parser.add_argument('--archive', required=True)
    args = parser.parse_args()
    out = inside(ROOT / 'dist/delivery')
    work = inside(ROOT / '.verification/delivery-extracted')
    if args.mode == 'native':
        app = extract(inside(args.archive), work)
        assert not (app / '.git').exists() and not (app / '.env').exists()
        assert not (app / '.codex').exists() and not (app / 'frontend/node_modules').exists()
        env = os.environ.copy()
        for key in ('VIRTUAL_ENV', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'MERIDIAN_DEBUG_UI', 'UV_PYTHON_DOWNLOADS'):
            env.pop(key, None)
        env.update(MERIDIAN_ROOT=str(app), MERIDIAN_NO_KEY='1', UV_MANAGED_PYTHON='1',
                   PYTHONPYCACHEPREFIX=str(app / '.cache/pycache'))
        before = {name: digest(app / name) for name in json.loads((app / 'DELIVERY-MANIFEST.json').read_text())['files']}
        with (out / 'delivery-startup.log').open('w', encoding='utf-8') as log:
            command = ['cmd', '/c', 'start.bat'] if os.name == 'nt' else ['sh', './start.sh']
            proc = subprocess.Popen(command, cwd=app, env=env, stdout=log, stderr=log,
                                    start_new_session=os.name != 'nt',
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                wait('http://127.0.0.1:8001', proc)
                result = inspect(app, 'http://127.0.0.1:8001')
                executable = app / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
                absent = subprocess.check_output([str(executable), '-c',
                    "import importlib.util,json;print(json.dumps({n:importlib.util.find_spec(n) is None for n in ('cadquery','pytest','playwright')}))"], cwd=app, env=env, text=True)
                result['optional_dependencies_absent'] = json.loads(absent)
                assert all(result['optional_dependencies_absent'].values())
            finally:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, check=True)
                else:
                    os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=20)
        assert all(digest(app / name) == value for name, value in before.items()), 'Startup changed supplied data/source files'
        result['automatic_python_download'] = any((app / '.runtime/python').glob('cpython-*'))
        assert result['automatic_python_download']
        result['packaged_files_unchanged'] = True
    result['passed'] = True
    (out / ('verification-' + args.mode + '.json')).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'mode': args.mode, 'passed': True, 'parts': result['status']['parts'],
                      'drawings': result['status']['drawings'], 'model_files_checked': result['asset_hashes_checked']}))


if __name__ == '__main__':
    main()
