# M23 first V1/V2 runner slice

Implementation candidate only. Runtime qualification is **SKIPPED** in this
invocation by instruction; ROOT dispatches the exact committed candidate.
No V gate, source fidelity, real-reader accuracy, human review, live Luna,
three-model reconstruction, full MVP or benchmark PASS is claimed.

Ownership: `development/scripts/check_milestone.py`,
`testing/tests/test_knowledge.py`, `testing/tests/test_core.py`, and this handoff.
Base includes ROOT's `6ef48b34e8fd7e7e6d44bae07f3abccd771a5df9` source-binding
update, merged by fast-forward after native assignment acknowledgement. No CI,
backend, UI, AI/model source, generated product assets or user journal changed.
Goal remains ACTIVE; owned 8010 remains closed and unrelated 8000 is untouched.

## CLI and results

The existing Actions gate invocation calls the runner directly, accepting
`V1` through `V5`. `testing/ci/checks.py` supplies foundation/module commands;
it has no gate subcommand in this candidate and is unchanged.

From `product/testing/` on Actions (ROOT provisions dependencies, no local runs):

```sh
uv run --project ../development --locked --extra test --extra prep python -B ../development/scripts/check_milestone.py V1
uv run --project ../development --locked --extra test --extra prep --extra cad python -B ../development/scripts/check_milestone.py V2
```

Focused added cases, before cumulative qualification:

```sh
uv run --project ../development --locked --extra test --extra prep python -B -m pytest -q -p no:cacheprovider --basetemp=tmp/M23-first-slice --junitxml=reports/ci/M23-first-slice.xml tests/test_knowledge.py tests/test_core.py
```

Default JSON: `testing/reports/verification/V1.json` or `V2.json`, with child
commands, candidate Git/Actions identities, JUnit counts, missing suites and
logs in `<gate>-checks/`. `--report` accepts another path under `testing/`.
Exit **0** means all requested REQUIRED software checks passed; **1** means
failed/missing software; **2** means required software is skipped/pending.
Full-evidence `outcome` remains PENDING even after software PASS because this
slice does not ingest or qualify live/human/visual/semantic evidence.

Absent files, unreadable/empty JUnit, omitted suites and nonzero child exits
cannot pass. Required skips and xfails block software qualification. Unexpected
passes use pytest's strict xfail setting. CAD is remote-only (`GITHUB_ACTIONS`),
sets the existing `MERIDIAN_REQUIRE_CAD=1`, and cannot pass without CadQuery.
Each run discards its old JUnit before execution. Inherited app credentials,
runtime-input overrides and real history paths are removed from child envs.

V2 includes V1 automatically. Requests for V3/V4/V5 include earlier software
but remain nonzero/PENDING until their runner slices are implemented; mere
suite-file presence gives no credit. Later gate placeholders, the unimplemented
final20 benchmark, source-derived three-model fidelity, actual-reader/Luna
qualification, human spot checks, visuals and fresh-clone evidence stay visible.
Only V3/V4 schedule semantic evidence. This adds no semantic checkpoint.

## Independent expectations and reuse

PLAN's V1/V2 behavior table is the acceptance basis. Existing suites retain
the extraction/BOM, record variants, typed decisions, bounded prep retry/cache/
settings/rate-limit/fallback/environment, B3, chat ledger/attachment and analytic
CAD matrices; these are invoked instead of copying their implementation tests.
The CAD suite already checks numeric volumes/voids, variants, exports, unknown
fields, targeted rebuilds and stale assets through the actual builder.

Five added integration scenarios use an isolated synthetic source bundle and
the existing scripted **external subprocess** reader peer through the real M08,
M09/M10, M11 publisher, persisted M12 registry, M14 tools, M16 decisions and M03/
M15 API/Responses path. Expected values are declared synthetic inputs, never a
recording of current app output. No internal resolver, assembler or builder is
replaced. The subprocess peer asserts fixed settings and fake-key isolation;
saved provenance is checked for exact candidate/source binding and serial order.
There are ten small runner policy cases for JUnit outcomes, cumulative exits,
future gates, absent files and refusing local CAD.

Known scripted scan fields remain separate from their null originals; six
unknown scan fields stay unresolved. Mappings remain unusable until an explicit
synthetic approval. The API cases prove proposal/pending/reject/accept behavior,
future-answer changes, retained earlier answers/original evidence, typed journal
events, targeted refresh, honest missing-model state, Luna-only provider errors,
and saved-history/fact reload without a key. A changed original PDF rejects
saved prep reads/rebuilds without overwriting the previous records snapshot.

All new review actions identify `Synthetic milestone reviewer (automated test
only)` and use temporary stores under `testing/tmp/`. Inert PDF bytes, synthetic
PNGs, scripted readings and fake credentials establish no real source accuracy
or human approval. No real Jason state is read or changed.

## Checks and limitations

- PASS: static Python AST parsing of the three owned Python files; no imports
  or execution of production/test modules.
- PASS: scoped Git diff/whitespace inspection, recorded again at commit.
- SKIPPED: focused tests and cumulative V1/V2 commands above; ROOT remote-only.
- SKIPPED: V3–V5, benchmark, actual providers, real three-model source fidelity,
  fresh clone and human/visual/semantic evidence; outside this first slice.

ROOT received native interface notice `9eeb6868a7d44819a50216b3be7466eb` about
CI extras and acknowledged that CI dependency changes remain ROOT-owned.
`RESULT.json` records the exact final tip, checks and current native invocation;
it and all harness bookkeeping remain uncommitted.
