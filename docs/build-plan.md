# Build and verification plan

“Manual” means the coordinator dispatches and monitors a workflow itself. It does not mean Jason must click, run commands, approve execution or confirm a checkpoint. Actual engineering reviews remain actual human decisions; never manufacture them.

## Routine pushes

`Meridian checks` runs remotely on pushes/PRs: focused Python tests without CAD/PDF regeneration/browser/API work, then frontend build. Each branch has a concurrency group that cancels superseded runs. Downloadable artifacts contain test reports and a frontend bundle with source and file hashes.

The frontend is static HTML/JS/CSS. The coordinator downloads the matching successful bundle using `python -m scripts.frontend_artifact fetch --run RUN_ID`; the downloader verifies its source fingerprint and every asset hash before installing under `frontend/dist`. The interactive local FastAPI app serves that bundle without Node or a local frontend build. Keep the previous bundle as a repository-local rollback copy.

## Integration checkpoints

The working and GitHub default branch is `v1`, tracking `origin/v1`. The coordinator dispatches `Meridian integration` through `gh workflow run verify.yml --repo JasonPeng2019/proj-meridian --ref v1`. One hosted runner executes full tests, PDF regeneration/cache recovery, real CadQuery generation and geometry roundtrips, then Playwright rendering/screenshots. CAD exits before the browser starts. Heavy runs queue in `meridian-heavy`, with no parallel matrix. Numerical/CAD workers are bounded for the standard hosted Linux runner.

The initial hosted Linux dependency, CAD and headless-rendering checks have already passed. Repeat them when integration changes justify it, not for every documentation edit. Artifacts provide GLB/STEP exports, built frontend, structured data, screenshots and reports for local inspection.

## Paid evaluation

The coordinator dispatches paid checks when needed, with the repository's existing `OPENAI_API_KEY` Actions secret. `benchmark=true` runs the canonical questions twice sequentially; `live_api=true` separately checks the isolated correction UI. Use [Question-benchmark/PLAN.md](Question-benchmark/PLAN.md) for the exact question, scoring and review-state requirements. Expected answers never enter chat or prep prompts. If GitHub secrets cannot be used, execute necessary API checks locally in sequence after checking resource headroom; this is a fallback the coordinator handles.

Independent CLI judging remains local, sequential by default, using hooks-disabled CLI settings and an ignored cache. At most four project CLI workers may be active; the dataset-reader cap is separately enforced at four. Use fewer when resources are tight.

## Local fallback and resource limits

Local work normally consists of edits, static checks, Git, artifact downloads and the interactive app. If a local build is necessary, the coordinator runs `scripts/local_build.ps1`. It holds a shared lock, waits for RAM/CPU headroom across two samples, and limits Node heap/esbuild workers. Heavy local tasks run in succession. Parallelize only when measured available RAM/CPU supports it. Never close unrelated editor windows or processes without authorization. Workspace-local VS Code settings exclude generated/cache/verification trees from indexing and watching.

All local project writes stay under the Avathon repository. Hosted project outputs, caches and verification copies stay under `GITHUB_WORKSPACE`, with runner-managed dependencies provisioned on the disposable VM.

## UI simplification checkpoint

Keep the default screens focused: one part viewer, one tab bar, concise core facts and one compact check summary. Filters, long chat details/attachment lists, AI readings, raw source records, hashes and calculations open on demand. The review comparison creates its two 3D viewers only after opening it. The coordinator builds on Actions, checks navigation and disclosure controls with Playwright (including no overflow, hidden default technical details and accessible weight calculations), inspects the screenshots, and downloads the verified frontend. Existing paid benchmark captures remain tied to their original code hashes; a presentation-only change does not require repeating paid question calls.

### Customer UI and engineering Debug

Keep Detail to Overview, Dimensions, one Notes section, and Supply & cost when applicable. Translate display labels and readable notes into English while retaining original evidence. Customer launches hide Debug by default. Engineers launch with `uv run meridian --debug-ui`; `--hide-debug` explicitly hides it. Debug collects raw records, calculations, hashes, provider receipts and history. Verify customer and engineering launches sequentially in Actions, download the verified frontend bundle, and serve it locally without Node.

### Prep workflow revision

Dataset preparation now runs Sol as proposer and Opus as verifier of the exact proposal, source IDs and fingerprint. Repairable feedback receives one bounded retry; invalid or unsupported essential geometry remains blocked. Existing independent-reader receipts are retained as legacy evidence. A targeted material-mapping rerun and an assessment of every additional drawing use the revised protocol. Model expansion preserves original evidence and decisions; Actions generates and roundtrip-checks each eligible model sequentially.

Latest UI steering moves all detailed verification, FAILED weight checks, review requirements and omissions into Debug. Customer part views use one simple Human reviewed / AI reviewed / Unavailable status, without repeated warning banners or per-row review labels. The Debug launch also exposes the engineering review workspace.
