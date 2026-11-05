# A02 / M02 prep observability correction — 2026-11-05

Bounded native resume on the existing A02-history branch, preserving `f97fd2c8252b732dfa4ac1fe1a65f91c4905034d` as the parent candidate. Contract/schema generation and static inspection succeeded. Runtime Python/TypeScript checks remain **pending ROOT Actions**; no live CLI, provider, source validation, storage or UI behavior was executed. The exact committed tip and current assignment identities are in root `RESULT.json`.

## Repair and exact A08 fields

Successful output no longer requires a complete effective identity. `PrepAttempt.requested: ReaderSettings` retains all previous role-specific pins. `PrepAttempt.effective: ObservedReaderSettings | null` contains only genuinely reported metadata; it may be null or partial on a successful stage. Unknown metadata is not `execution_failed`, `invalid_output`, disagreement, fallback, or a reason to invoke another model. Success still requires a validated output and no current failure. Source/candidate/output hashes, explicit verdicts, ordering and all other existing status checks remain in force.

| Field | Representation and rule |
| --- | --- |
| `effective.provider` | `codex_cli`, `claude_code`, or null; never fill from requested identity |
| `effective.model` | Reported model string or null |
| `effective.reasoning` | Reported effort/reasoning string or null |
| `effective.service_tier` | Reported tier or null; accepted equivalents are Codex `fast`/`priority`, Opus `regular`/`standard` |
| `effective.read_only` | Reported boolean or null; explicit false conflicts with the pinned read-only policy |
| `effective.settings` | Observed settings map; use null for unreported known settings such as `fallbackModel`; an absent key is also unknown |
| `cache.settings` | The complete pinned **requested** `ReaderSettings`, always; it is not evidence of effective settings |
| `cache.settings_basis` | Required `requested` for no/partial observations; `confirmed` only when all five core fields, every requested settings-map key and Opus fast/fallback policy settings have matching non-null observations |
| `cache.effective_sha256` | Required null when `effective` is null; otherwise `contract_digest()` of the normalized `ObservedReaderSettings.model_dump(mode="json")`, including unknown null fields |

`ObservedReaderSettings` defaults each core field to null, including `read_only` (no inherited true default). Complete genuinely confirmed metadata fits this same shape. Do not copy requested values to make it complete. Map actual CLI fields to these canonical fields; absence or the historical phrase `not exposed` becomes null. Explicitly conflicting reported values must remain visible and fail validation, not be changed to null. Retain meaningful observed setting metadata; do not place credentials, private paths or raw authentication in it. Optional engineering metadata remains Debug-only.

`prep_settings_basis(requested, effective, role)` is the shared pure validator/helper for A08. It keeps the existing Codex Sol max/fast-or-priority and Claude Opus xhigh/regular requested pins. Reported provider/model/reasoning/read-only conflicts are rejected even if other fields are unknown. Reported tiers must fit the role's equivalents above. Reported Opus `fastMode=true`, nonempty `fallbackModel`, non-read-only sandbox, or a reported setting conflicting with a requested setting is rejected. Unknown fields alone do not reject a stage. The cache must match the requested pins, derived basis and code-computed observation digest; requested versus confirmed basis cannot be substituted silently.

After parsing actual observations, A08 constructs the existing cache fields plus:

```python
requested = ReaderSettings.model_validate(requested_data)
effective = (ObservedReaderSettings.model_validate(observed_data)
             if observed_data is not None else None)
cache_settings = {
    "settings": requested,
    "settings_basis": prep_settings_basis(requested, effective, role),
    "effective_sha256": contract_digest(effective) if effective is not None else None,
}
```

Keep the existing pipeline/role/source/field-inventory/prompt/output-contract/candidate/feedback/mode fields in `PrepCacheIdentity`; the cache key remains `contract_digest(cache)`. Hash normalized observed models, not a hand-entered digest or an unnormalized partial dictionary. Required new cache fields mean older keys must be re-bound explicitly from retained truthful metadata. This is not a demand to rerun a successful stage or another model merely because its metadata was unreported. A08 alone owns implementation and actual CLI parsing/execution; this change does not implement that runner.

The historical actual qualification at `testing/reports/qualification/A08-runner/qualification.json` reports Codex effective model/effort/tier/sandbox as unexposed and Claude model/standard speed with unexposed effort/fallback. It is retained byte-for-byte as qualification history, not reclassified as current determine-then-verify evidence or a newly confirmed identity.

## Synthetic evidence and preserved scope

`prep-observability.json` is one additional declared synthetic `PrepBatchResult`: Sol succeeds with `effective=null`; Opus succeeds with its reported model/standard tier/fast-mode-off and null provider/effort/read-only/fallback/image-input metadata. Both stages use cache basis `requested`, preserve a source-bound candidate and explicit verifier verdict, and derive one first-pass-verified field, zero execution failures and zero fallback fields. All hashes are computed by existing code over normalized fictional data. No actual CLI identity was invented or executed.

The old synthetic complete-metadata cases remain explicitly fictional examples. Their cache identities gain the two required fields; their existing outputs/verdicts/modes/counts remain unchanged. Nested D-013/template/review/proposal/summary-input fixtures gain those cache fields, and machine/cost summary snapshot digests are recomputed from the changed synthetic record serialization. Counts, monetary totals, source facts and review policy are unchanged. All ten history examples, existing chat/source fixtures, GLB assets and historical reports remain unchanged.

`check_observability()` adds Actions-only positive null/partial/complete examples and negative observed provider/model/effort/tier/read-only/sandbox/fast/fallback/setting conflicts. Conflicting observations receive a recomputed digest before validation, so the guard is tested independently of stale-hash rejection. Other negatives cover forged confirmation basis, unbound observation/request hashes, missing successful output and candidate/source mismatch. Existing prep disagreement/retry/fallback/source-binding, summary, Debug, history and status checks remain wired into the same focused checker. TypeScript checks add nullable observed metadata while keeping requested identities non-null.

Static preservation inspection against `f97fd2c` retains 168 pre-existing class declarations unchanged; only `PrepAttempt` and `PrepCacheIdentity` change. Every existing top-level helper and the entire handwritten TypeScript section, including history client/service/UI/panel props, are unchanged. Only shared M02 contracts, declared fixtures/checkers and these two new dated reports changed. No config, CI, implementation, docs, USER_TODO, source or historical report was edited.

## Inbox correction and actual local checks

The earlier empty-inbox statement did not cover ROOT's later-observed pending event `a318547336b84f0c9c754ec56da54393`; it is not evidence that event was handled. This resume's binding points to `.agent-workspace/QUEUE.json` for run `c3f9573dfab54a69a7b17b79495be2a7`. The actual initial bytes were read at `2026-11-05T10:43:51.576449+00:00`, SHA256 `9d78a1d2c6bb72af5f55573fe4f614c0794d13bbb52432a704c5502341455115`, and contained `assignments: []`. The historical event is absent from this fresh inbox. No event is fabricated or claimed acknowledged/completed. The repair is directly assigned in this fresh task card. Before final publication the inbox is read again, any present handled PENDING/ACKNOWLEDGED events are advanced only through `lane-queue.py`, and the final timestamp/hash/actual assignment states are recorded in RESULT evidence. Harness bookkeeping is not committed.

Actual lightweight local commands, using installed Python/Pydantic only:

```text
python -B testing/smoke/A02-contracts/check_contracts.py --write-types
python -B testing/smoke/A02-contracts/build_fixtures.py
python -B testing/smoke/A02-contracts/inspect_static.py --base-revision f97fd2c8252b732dfa4ac1fe1a65f91c4905034d --observability --report testing/reports/b01/A02-contracts/2026-11-05-observability-static.json
git diff --check
```

Generation emitted the TypeScript mirror from 136 concrete models and 33 declared synthetic JSON examples plus the existing two GLBs. Generation mode returns before runtime test assertions. Static evidence records AST/JSON inventory, preservation and file hashes only. No local test suites, builds, dependency installations, live models or actual source validation were run; unsupported source validation is not reported as passed.

## Exact pending ROOT Actions commands

After publishing these exact native source blobs on `harness-v2`, from the product root in the existing Actions dependency environment:

```sh
development/.venv/bin/python -B testing/smoke/A02-contracts/check_contracts.py
development/frontend/node_modules/.bin/tsc --strict --target ES2022 --module commonjs --lib ES2022,DOM --rootDir . --outDir testing/tmp/A02-contracts/compiled development/frontend/src/contracts.ts testing/tmp/A02-contracts/fixtures.ts testing/smoke/A02-contracts/check_props.ts
node testing/smoke/A02-contracts/check_helpers.cjs
```

ROOT owns remote verification/acceptance and the subsequent one-time A08 resume. This worker commits and publishes the exact native result immediately, without dispatching or waiting for remote checks. `RESULT.json` records exact per-file additions/deletions for this correction and its cumulative delta from the native assignment base; preservation of the completed history candidate is independently inspectable through the parent commit and static evidence.
