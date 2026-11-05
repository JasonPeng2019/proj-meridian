# A06-bom / B01 / M06 handoff

M1 implementation is complete; runtime validation is **pending ROOT's Actions
dispatch**. No local product test, PDF, CAD, browser, build, reader, or provider
execution was performed. This is not a V1 gate result.

## Producer boundary

`backend.loader.bom.load_bom(source: str | Path = DEFAULT_BOM_PATH) -> list[BOMRow]`
returns the frozen `backend.contracts.BOMRow`, `BOMField`, and
`ConnectionEvidence` types, with no alternate payload schema. The default input
is resolved relative to the module, independent of the launch directory.
`HEADER_KEYS` publishes the exact ordered original headers and internal field
keys; each serialized field's note also retains its original header. Every
field retains its original cell string, including empty strings and embedded
CRLF. No contract changes or other producer changes are needed.

`Part family` becomes `section`, `Design Intend` becomes `design_intent`, `V&V`
becomes `validation`, and `Count (Interface with)` becomes `interface_count`.
Other internal keys follow the explicit `HEADER_KEYS` mapping. DKK prices use
the contract's numeric `value` and `currency="DKK"`. Material/interface values
are lists or null. Lifecycle, procurement, and attachment fields retain snapshot
caveats; exported attachment URLs carry the likely-expired warning. No URLs are
fetched and no current procurement state is inferred.

Display IDs reflect 1-based CSV row positions. Stable names use only frozen
contract helpers. Row hashes cover compact UTF-8 JSON of ordered original
header/cell pairs, excluding the display position; reorder alone does not
invalidate a row fingerprint. Keep the returned list or a multi-map: duplicate
stable names are preserved and marked `identity_conflict`, never suffixed.
Name ambiguity across sections is also noted. Interface extraction happens
inside normalization's CSV pass. A final index lookup handles forward targets,
unique normalized name resolution, and collisions without re-reading cells.
Connections cite the exact original interface cell, remain directed, and point
to BOM `/part` IDs; drawing links are the matching/records owners' responsibility.

M3 status spelling changes, literal newline decoding, attachment splitting,
total consistency checks, broader odd-value flags, and cleanup reports are
deliberately deferred. Existing source spellings and attachment strings remain
inspectable in M1.

## Actual checks

All execution used the assigned worktree's `testing/` directory.

- `Get-FileHash ../development/inputs/project-meridian/dataset/context/openlpbf-bom.csv -Algorithm SHA256`
  (initial static inspection used the equivalent path from worktree root):
  `b9837f2249247e4465ae5f481f714912bba8ed33a7759cd773ab43092e1b6ae2`, matching
  the supplied manifest. Source remains 52,534 bytes.
- `python -` with a bounded stdin script using only `ast`, `csv`, `hashlib`,
  `io`, `json`, and `pathlib`: exit 0. Both authored Python files parse; the
  unchanged supplied CSV has 192 data rows, 20 headers and uniformly 20 cells.
  Results: `static-check.json`. This did not import or execute the product.
- `git diff --check`: exit 0 before staging. The final result record reports
  the staged whitespace check and committed tip/clean state separately.

The focused suite `testing/tests/test_bom_m1.py` contains six deterministic
checks: real-source originals/headers/manifest integrity and contract round
trips; source zero/list/connection behavior; synthetic core cleanup and snapshot
notes without M3 repairs; explicit zero versus missing-price totals;
duplicate/ambiguous/missing/forward targets without reverse-link invention;
and row identity/fingerprint behavior under reordering and source changes.
Synthetic cases live only in per-test directories beneath `testing/tmp/A06-bom`.
No benchmark expectations enter implementation or test evidence.

ROOT: dispatch this exact focused command on Actions from `product/testing/`,
with the candidate revision in the run metadata and the project's declared
Python/Pydantic dependencies installed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../development python -m unittest discover -s tests -p test_bom_m1.py -v
```

Record the actual remote outcome and downloadable report before claiming the
runtime acceptance checks pass. The native completion record remains BLOCKED
on that verification handoff, rather than labeling authored tests as executed.

## ROOT follow-up

- Dispatch the focused suite above and return its exact candidate identity and
  report. No shared code/config change is requested.
- Proposed asynchronous USER_TODO: inspect `BOM:optics/laser-source/interface_with`
  (original cell `GLAMS`) and identify the intended component, with supporting
  evidence, if resolving it is needed. The supplied CSV has no matching row;
  keep this reference unresolved until a supported human decision exists.
  This does not block coding or prep. Do not infer a replacement from the name.
- CWD `AGENTS.md` is absent. The explicit task card, PLAN, WORKFLOW, contracts,
  original MVP/proposal, requirements, dataset notices, and B00 contract handoff
  supplied the available instructions. The lane inbox contains no queue event
  to acknowledge. No human approval was fabricated.

Only `development/backend/loader/bom.py`, its focused test and this lane's report
artifacts are changed. Supplied sources, contracts, package/config, shared
generated output, PLAN/WORKFLOW and `USER_TODO.md` are untouched.
