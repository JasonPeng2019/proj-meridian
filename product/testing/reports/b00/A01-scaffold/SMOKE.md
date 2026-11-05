# B00 / A01-scaffold / M01 smoke evidence

Date: 2026-11-05, America/New_York (UTC-05:00). Scope: the complete M01
setup bundle only. No product milestone or verification gate is claimed.
Branch: `lane/9835572aa8594664acdb2346c2fcc64e/A01-scaffold/work`.
Starting revision: `a279e45b98554f7c39d0d8cf47667bae860a5180`.
The committed candidate revision is the full tip recorded in root `RESULT.json`.

All commands ran in this assigned worktree. `development/` and
`development/frontend/` below are working directories relative to its root.
Dependencies were installed only in `development/.venv` and
`development/frontend/node_modules`; inherited uv/npm cache locations were
retained. The empty-secrets check used `testing/tmp/A01-scaffold/` in this
worktree. No real secrets directory, key contents, or CLI auth files were read.

## Tools and installed versions

| Command | Working directory | Exit | Observed version |
| --- | --- | --- | --- |
| `uv --version` | root | 0 | uv 0.11.19, build 7b2cff1c3, 2026-06-03, x86_64-pc-windows-msvc |
| `python --version` | root | 0 | Python 3.12.10 |
| `node --version` | root | 0 | v24.19.0 |
| `npm --version` | root | 0 | 11.17.0 |
| `uv run python -c "import sys, importlib.metadata as m; print(sys.version); [print(n + '==' + m.version(n)) for n in ('fastapi', 'uvicorn', 'pydantic', 'openai', 'PyYAML')]"` | development | 0 | Python 3.12.10 (MSC v.1943, 64-bit AMD64); FastAPI 0.162.0; Uvicorn 0.54.0; Pydantic 2.14.2; OpenAI 2.54.0; PyYAML 6.0.3 |
| `npm list --depth=0` | development/frontend | 0 | Vite 8.3.6; React/React DOM 19.3.1; TypeScript 7.0.2; Tailwind 3.4.19; PostCSS 8.5.32; Autoprefixer 10.6.2; @vitejs/plugin-react 6.2.1 |

Other top-level frontend packages from that `npm list` command:
@radix-ui/react-slot 1.5.0, @types/node 24.19.2,
@types/react and @types/react-dom 19.3.0, class-variance-authority 0.7.1,
clsx 2.1.1, lucide-react 0.577.0, tailwind-merge 2.6.1,
tailwindcss-animate 1.0.7. The committed lockfiles record transitive versions.

## Focused checks

| Exact command | Working directory | Exit | Actual outcome |
| --- | --- | --- | --- |
| `uv lock` | development | 0 | Wrote `uv.lock`; resolved 71 packages, including optional extras, on Python 3.12.10. |
| `uv sync` | development | 0 | Created `.venv`, built the editable project and installed 25 runtime packages. CAD/prep/test extras were not installed. |
| `uv run meridian` | development | 1 | Expected B00 behavior: `Meridian server is not implemented yet. A03 supplies backend/app/main.py in B02.` Exited promptly (about one second); no server or fixtures served. |
| `uv run python ../testing/reports/b00/A01-scaffold/smoke_checks.py` | development | 0 | Empty temporary secrets directory resolved correctly; missing/empty-key state explained; exact Luna/prep/reviewer configuration and fake-key CLI environment separation checked. Runtime imports did not import CadQuery, which is also absent from the environment. No prep CLI or Node subprocess was invoked by runtime imports. All 51 tracked input files matched their Git blob bytes. |
| `npm install --no-fund --no-audit` | development/frontend | 1 | Initial attempt failed; the tool captured no diagnostic output. This attempt is not counted as a successful install. |
| `npm install --no-fund --no-audit --loglevel=info` | development/frontend | 0 | Retry completed: 45 packages added, 39 removed, 50 changed. Subsequent checks exposed a broken native binding left in this install. |
| `npm run build` | development/frontend | 1 | First build failed: native Rolldown binding was not a valid Win32 application. No passing build claimed for this attempt. |
| `npm run dev -- --help` | development/frontend | 1 | First dev-command resolution failed with the same native-binding error. |
| `npm ci --no-fund --no-audit` | development/frontend | 0 | Clean installation from the lockfile added 114 packages in 15 seconds; repaired the binding failure without changing dependency requirements. |
| `npm run build` | development/frontend | 0 | Final build: Vite 8.3.6, 16 modules transformed, built in 2.07 seconds. Emitted index.html (0.40 kB), CSS (5.04 kB), JS (220.33 kB). |
| `npm run dev -- --help` | development/frontend | 0 | Final command resolved to `vite --host 127.0.0.1 --help`, printed Vite 8.3.6 dev-server options and exited. This verifies command resolution, not a browser/HTTP journey. |
| `& .\development\start.bat` | root, PowerShell | 1 | Windows wrapper correctly changes directory and propagates the same expected B00 message/exit. |
| `git diff --check` | root | 0 | No whitespace errors in the tracked diff. |
| `git diff --cached --check` | root | 0 | No whitespace errors after staging the 27 owned source/report files. |
| `git grep --cached -I -l -E 'sk-[A-Za-z0-9_-]{16,}' -- development/backend development/frontend development/ai_settings.yaml development/.env.example testing/reports/b00/A01-scaffold` | root | 1 | Expected no-match result: no key-shaped literal in the staged scaffold/report files. This is a limited literal scan, not an authentication or external secret audit. |
| `git diff --cached --quiet -- development/inputs development/docs development/README.md development/USER_TODO.md testing/tests testing/frontend testing/fixtures` | root | 0 | No changes in the listed forbidden source paths. The staged path list was also inspected: all 27 files are A01-owned. |

Input verification computes each file's Git blob SHA-1 directly from its bytes
and compares it with `git ls-files -s -z -- development/inputs`.
The 51-entry path/blob inventory SHA-256 was
`2c35318c5a4e402a11883f0e37b66c4861b18eb3cfa67f9be175f198a4829b6f`.
The dataset, attribution, and license paths configured in `ai_settings.yaml`
all exist. No corpus files were rewritten or duplicated.

An initial version-query command included `hatchling` in the package tuple and
exited 1 with `PackageNotFoundError` after printing the runtime versions.
Hatchling is an isolated build requirement, not a runtime dependency. The
corrected exact version command above succeeded; no runtime package was added
to satisfy the diagnostic query.

## Build-output cleanup and source hygiene

`dist` was intentionally removed after the successful build. No ignore rule
was added for it, so a future release can commit the bundle. Recursive
PowerShell cleanup requests were rejected by the execution policy before
running (no process exit code). A clean dependency install used `npm ci`
instead. For `dist`, the narrower successful cleanup explicitly deleted only
these generated files through the patch tool:

```text
development/frontend/dist/assets/index-BaKCjCG9.css
development/frontend/dist/assets/index-DWEN12KF.js
development/frontend/dist/index.html
```

Then this exact PowerShell command block exited 0:

```powershell
Remove-Item -LiteralPath 'development/frontend/dist/assets'
Remove-Item -LiteralPath 'development/frontend/dist'
if (Test-Path -LiteralPath 'development/frontend/dist') { throw 'dist cleanup failed' }
Write-Output 'PASS: frontend/dist removed using explicit files and empty directories'
```

Before deleting, `Get-Item -LiteralPath 'development/frontend/dist'` established
that it was a regular directory at the exact assigned worktree path.
Only A01-owned source/report paths were staged. Existing root ignore rules
exclude `.env`, `.secrets`, `.venv`, `.runtime`, `node_modules`, Python bytecode,
and testing temporary/cache outputs; `.env.example` remains trackable.
The scaffold contains no key values. Settings import/load only reads the YAML;
the key-file helper exposes its location and presence, without reading contents
or modifying process credentials. The future server client owns private key
loading/format validation. Key presence is not an authentication claim.

## Bounded handoff and unperformed work

- `ai_settings.yaml` is the configured home for AI identities, prep settings,
  credential location, reviewer, evidence paths, and drawing layout. Both prep
  argv templates are explicitly `pending_A08`; this report does not qualify
  their image/JSON flags or execute either CLI. Opus failure policy records
  Sol-only provenance, separate counts and a fresh Opus attempt next launch.
- The proposal A1 field-label/location table is configured. Proposal A2 scan
  crop measurements remain null and explicitly pending A05's measurement
  from clean source drawings; no coordinates or rendering resolution were
  invented. This is an implementation handoff, not a human decision.
- The launcher will hand off to `backend.app.main:app` when A03 supplies it.
  No server endpoint, missing-key HTTP behavior, fixture serving or paid AI
  call was implemented or tested in B00. A04 takes `App.tsx` in B02.
- `start.sh` was not exercised on macOS/Linux; those operating systems were
  unavailable in this Windows lane. Full E1 release behavior requires A03 and
  shipped release outputs and is not claimed by this setup smoke.
- No test suites, CadQuery qualification, live API/CLI calls, frontend browser
  journeys, or wheel/sdist release builds were run. CAD/prep qualification
  belongs to the parallel A13/A08 slices. No human decision/USER_TODO entry
  is required for this scaffold.

Final B00 result: **PASS for M01's bounded setup checks**, with the expected
not-yet-implemented server exit. Recovered failed attempts remain recorded
above; this does not claim that every attempted command succeeded.

## B00 repair — 2026-11-05

Scope: A01 follow-up on current integration base
`0d859eebb01e7d9840465113284a7e38d7dc6e7b`, branch
`lane/01044dfacea84d41a122b6c913e71475/A01-scaffold-fix/work`.
The final candidate is the full branch tip in ignored root `RESULT.json`.
The latest resource override supersedes the original local-check instructions:
**no installs, runtime tests, builds, smoke scripts or live readers were run**
in this repair. The historical B00 outcomes above are not new repair results.
Remote runtime acceptance is pending ROOT Actions on the exact integrated
revision, including A02's refreshed contracts. No source-validation PASS,
determine/verify qualification, UI review or product gate is claimed.

Changes:

- Added `src/vite-env.d.ts` referencing `vite/client` for the reported TS2882
  CSS import, and `typecheck: tsc --noEmit -p tsconfig.json`. The existing
  `build: vite build` and lockfile are unchanged. `tsconfig.json` includes the
  whole `src` tree, including `contracts.ts`; A02's file was not edited.
- Replaced both pending reader templates with the exact successful B00
  `sol-2`/`opus-1` argv, using plain executable names and placeholders for
  model/settings, image, schema, output and state/log paths. Prompts travel on
  stdin. Claude's image path belongs in that prompt for its Read tool, not an
  invented image flag. Claude settings/environment templates preserve the
  qualified regular mode, empty fallback list and hook/tool restrictions.
- Qualification references commit `0e66458` and both A08 reports. Their
  synthetic image capability is historical evidence only: it does not qualify
  the new candidate-bound verification sequence or engineering source truth.
  Effective Codex model/effort/tier/sandbox and Opus effort/fallback list are
  not exposed. Reserved `model_providers.openai` overrides must not be used;
  `--bare` is avoided because it excludes account OAuth. The nonfatal Codex
  catalog timeout and built-in provider retry defaults remain limitations.
- Configured `determine-verify/v1`: Sol determiner then Opus verifier,
  sequential execution, exact candidate/original-evidence binding and explicit
  field verdict/reason/evidence requirements, one disagreement correction and
  reverification, retained rounds, persistent disagreement/unsure/invalid
  unresolved. Only a troubleshot Opus execution failure permits valid
  source-backed `single_model_unverified` continuation, labelled UNVERIFIED
  in Debug, outside verified counts, with Opus retried on each launch. The
  one-job/two-reserved-reader-slot/four-total-process caps are explicit.
- Added central `ui.debug_enabled: false` and `Settings.debug_enabled` for
  A03 status. Export `MERIDIAN_DEBUG=1` to enable; unset/`0` disables it.
  `uv run meridian --debug` / `--no-debug` override the environment; both
  launch wrappers already forward flags. `.env.example` documents these
  settings and is not automatically loaded. Review belongs inside Debug;
  ordinary navigation remains Chat/Parts. No UI/contracts were edited.
- Added `paths.chat_history: chat_history` relative to `development/`,
  optional `MERIDIAN_CHAT_HISTORY_DIR`, and `Settings.chat_history_dir` for
  A15. This resolves a path only; it implements no persistence and reads no
  key/history. M15 must retain full messages/citations/attachments and the
  server-owned per-thread ledger, send only the selected last 10 turns to
  Luna, never trust client history for citation authorization, and allow
  history reads without a key. Tests use isolated stores under `testing/`.
- Native `.gitignore` now excludes `/development/chat_history/`.
  **Outer Git delta for ROOT:** add `/product/development/chat_history/` to
  Avathon's publishing `.gitignore`; that file is outside this lane/CWD and
  was not changed. No real user history was opened or created.

The owned `smoke_checks.py` was legitimately updated: replace the obsolete
`pending_A08`/blind-reader assertions with exact successful-argv comparison
against the A08 JSON record, template path/literal checks, new pipeline/fallback
configuration, Debug environment/flag precedence and isolated history path/Git
exclusion checks. `--templates-only` supplies a separate YAML load/argv check.
It never invokes either reader. All checker execution remains remote.
ROOT owns workflow manifests and `testing/ci/checks.py`; neither was edited.
The existing foundation entry point already calls this A01 smoke file.

### Static inspection and remote handoff

Allowed local static inspection: Python `-B` parses owned Python files with
`ast.parse`, frontend package/tsconfig JSON with `json.loads`, and settings with
`yaml.safe_load`; it does not import application modules or execute the checker.
The exact invocation and inspection results are retained in
`B00-repair-static.json`. A static comparison also confirms both templates
preserve the qualified argv after documented substitutions, with no absolute
paths/key-like literals. Its first `python -c` attempt reported a Sol mismatch
because PowerShell removed embedded TOML quotes during native argument
transport. A JSON-normalization `python -c` attempt then exited 1 with
`SyntaxError: unexpected character after line continuation character` for the
same quoting issue. Piping the inspection/normalization programs on stdin
corrected both; both comparison results and the failure diagnostic are retained.
These were inspection-command transport failures, not reader executions.
`git diff --check` checks whitespace only.
These inspections cannot establish TypeScript or runtime correctness.

Commands ROOT must run on **Actions**, from the indicated working directory:

| Exact command | Working directory | Repair outcome |
| --- | --- | --- |
| `npm ci --no-fund --no-audit` (only if `node_modules` is absent) | development/frontend | NOT RUN locally; remote pending. |
| `npm run typecheck` | development/frontend | NOT RUN locally; remote must exit 0, including integrated A02 `contracts.ts`. Report any contracts error verbatim to A02; do not fix it in A01. |
| `npm run build` | development/frontend | NOT RUN locally; remote pending, build command unchanged. |
| `rm -rf -- dist` | development/frontend on disposable Linux Actions runner | NOT RUN locally; remove this generated frontend directory after preserving any required remote artifact. No build output is committed. |
| `uv sync --locked` | development | NOT RUN locally; remote pending, locked form of requested `uv sync`. |
| `uv run meridian` | development | NOT RUN locally; expected exit 1 with the not-implemented message while A03 is absent. Once A03 is integrated, use A03's launch checks instead of asserting this historical exit. |
| `uv run python ../testing/reports/b00/A01-scaffold/smoke_checks.py` | development | NOT RUN locally; remote pending. |
| `uv run python ../testing/reports/b00/A01-scaffold/smoke_checks.py --templates-only` | development | NOT RUN locally; remote YAML load/qualified-argv/path/literal checks pending. |
| `git diff --check` | root | Exit 0 during static repair inspection. |
| `git check-ignore --no-index development/chat_history/probe.json` | root | Exit 0; native ignore matches without creating history. |

Keep the environment, cache and any generated logs/test outputs inside the
Actions checkout's development/testing split. Bind retained Actions results to
the exact published `harness-v2` revision. The A02 candidate `ab9c786` report was
read via Git; its focused TS helper commands remain ROOT's CI integration task,
in addition to the full-tree `npm run typecheck` above. This A01 base still has
the earlier contracts; ROOT must validate after integrating both owners.

Repair handoff: scoped edits and remote checks authored; runtime validation
**pending**, not passed. No human decision or proposed USER_TODO is needed.
