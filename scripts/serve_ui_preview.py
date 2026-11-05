"""Serve a pinned remote UI bundle on its own port, keeping the main app intact."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fastapi.responses import FileResponse, Response
from backend.paths import ROOT, configure_environment, inside


def main():
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', required=True, help='Downloaded frontend artifact directory inside this repo')
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--debug-ui', action='store_true')
    args = parser.parse_args()
    stage = inside(args.artifact)
    dist = inside(stage / 'frontend/dist')
    receipt = json.loads(inside(stage / 'docs/ci/frontend-build.json').read_text(encoding='utf-8'))
    from scripts.frontend_artifact import hashes
    if not (dist / 'index.html').is_file() or hashes(dist) != receipt['files']:
        raise RuntimeError('Preview bundle failed its artifact hash verification')
    for file in dist.rglob('*'):
        inside(file)
    if not all((ROOT / 'generated' / name).is_file() for name in ['records.json', 'models/manifest.json']):
        raise RuntimeError('Preview requires the existing prepared records and CAD; it does not regenerate them')
    os.environ['MERIDIAN_DEBUG_UI'] = '1' if args.debug_ui else '0'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    from backend.app.main import app

    @app.middleware('http')
    async def pinned_frontend(request, call_next):
        path = request.url.path.lstrip('/')
        if path == 'api' or path.startswith(('api/', 'generated/')):
            return await call_next(request)
        try:
            candidate = inside(dist / path)
        except ValueError:
            return Response(status_code=404)
        if not candidate.is_relative_to(dist):
            return Response(status_code=404)
        return FileResponse(candidate if candidate.is_file() else dist / 'index.html')

    print(f"Pinned UI preview: http://127.0.0.1:{args.port} (source {receipt['commit']})", flush=True)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
