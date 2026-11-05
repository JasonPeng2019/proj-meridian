# A07 decisions — B01 / M1 handoff

Scope: `development/backend/loader/decisions.py` and its focused synthetic test
suite. Frozen B00 contracts, configuration, other modules, shared generated
outputs, supplied sources and USER_TODO were not changed. M2 invalidation,
reapproval, confirmations and whole-design approval are deferred.

Managed invocation: Codex CLI `gpt-6.1-sol`, max reasoning, fast/priority, as
recorded by `.agent-workspace/invocation.json`. No additional CLI readers,
product model calls, build, PDF/CAD job or browser run was launched.

## Integration

- Construct `DecisionStore(configured_decisions_path)` outside `generated/`.
  Ordinary reads create no files. Each portable filename is the SHA256 of its
  stable journal owner; the JSON retains the actual owner and frozen payloads.
- `append_decision(Decision) -> Decision` accepts pending proposals only.
  Trusted server composition passes `store.human_appender(reviewer_from_settings)`
  to the frozen `ReviewDependencies.append_decision` callback. That callback also
  accepts proposals, but review events must identify the configured reviewer.
  M16 supplies server time. Chat/prep receives no human appender capability.
- Save a pending proposal before appending an action that references its
  `proposal_id`. Review events retain the proposal's exact `based_on` map.
  `supersedes` names an earlier event for the same stable name. A new action is
  always a separate event; identical decision-ID retries are idempotent and a
  conflicting reuse fails. Rejected/pending events never revoke an accepted value.
- A12 can use `latest_accepted(stable_name)` for links, template fields and
  mappings. `review_for(stable_name)` exposes the accepted review and its original
  evidence hashes. No current hash replaces the evidence actually reviewed.
- `apply_overlay(EvidenceField)` returns a copy with a frozen `Correction`.
  Its extracted `value`, verbatim `original`, method, confidence and AI provenance
  remain intact. `effective_value(field)` supplies the accepted value, including
  explicit null; `Correction.original` retains the accepted event's `old_value`.
- `journal(stable_name)` returns all events for the owning part/mapping/passage;
  `history(stable_name)` filters that history by the exact frozen stable name.
  The latest accepted event in append order wins. Reads reload saved histories;
  corrupt journals fail explicitly rather than disappearing during regeneration.

## Checks and limits

Local static syntax inspection passed using `python -B -` from `testing/`:
`ast.parse` accepted both owned Python files. There are seven authored test
functions, including five cases in the M1 decision-type parametrization.

Source/ownership integrity is checked against assigned base
`f74f65e5d0572cad22ab6edc544db1a72755b6d8`. The final local static record is
`static-checks.json` in this directory; it records actual commands, return codes,
owned file hashes and raw input-byte identity checks. `git diff --check --cached`
is run before committing. RESULT.json names the exact committed branch tip.

**Runtime tests: NOT RUN locally.** ROOT's assignment explicitly requests Actions
dispatch and publication without waiting for remote test results. No V1 gate,
runtime persistence/concurrency behavior, Windows lock execution, live AI output,
source engineering value or genuine human review is claimed verified here.
All test decisions are explicitly synthetic and use temporary directories below
`testing/tmp/A07-decisions`; production-mode stores reject synthetic payloads.

ROOT can run this focused deterministic check from `product/testing/` on the
published `harness-v2` candidate containing these exact module/test blobs:

```sh
python -B -m pytest -q tests/test_decisions_m1.py -o cache_dir=cache/pytest-A07-decisions --junitxml=reports/b01/A07-decisions/pytest.xml
```

The suite uses the actual store and frozen B00 pending fixture. It checks
persistence/reload, generated-output removal and rerun overlays, original and
reviewed-hash retention, pending/rejected non-effects, superseded histories,
reviewer capability enforcement, explicit-null values, each M1 decision type,
stable names, interrupted atomic replacement and competing store writers.
Only the filesystem replacement failure is simulated; domain logic is real.
Dependencies come from the existing locked `development/` test extra. There is
no shared-file change request and no human TODO required by this pure journal
slice. Remote runtime results remain for ROOT's integration decision.
