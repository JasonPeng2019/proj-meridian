# Remote verification

Publish and dispatch only branch `harness-v2` in `JasonPeng2019/proj-meridian`.
The repository's `main` is a separate project. Select the branch and exact SHA
when reading a run or downloading its artifacts.

Pushes run the bounded foundation checks and build the frontend. Older push
runs on this branch are cancelled. ROOT dispatches heavy checks itself:

```powershell
gh workflow run verify.yml --repo JasonPeng2019/proj-meridian --ref harness-v2 -f task=modules
gh workflow run verify.yml --repo JasonPeng2019/proj-meridian --ref harness-v2 -f task=pdf
gh workflow run verify.yml --repo JasonPeng2019/proj-meridian --ref harness-v2 -f task=extract
gh workflow run verify.yml --repo JasonPeng2019/proj-meridian --ref harness-v2 -f task=capability
gh workflow run verify.yml --repo JasonPeng2019/proj-meridian --ref harness-v2 -f task=gate -f gate=V1
```

Heavy runs share one queue. CAD and headless rendering use separate sequential
jobs. Module tests require authored `testing/tests/test_*.py` files and do not
claim a product gate. Gates require the implemented M23 runner and actual
checkpoint suites. Missing suites fail explicitly. PDF capability is raw text
and image extraction; synthetic CAD capability does not verify a real part.
`task=extract` runs the committed drawing/BOM producers across all 30 drawings
and 192 rows, saving typed inputs and images for later prep without AI calls.

Optional `task=live` uses only `HARNESS_V2_OPENAI_API_KEY` and `gpt-6-luna`.
It never runs on pushes. Prep readers use independent CLI authentication.

Artifacts include revision-tagged reports, screenshots and generated assets.
From `product/testing/`, install a successful branch-matching frontend with:

```powershell
python -B ../development/scripts/frontend_artifact.py --run <successful-checks-run-id>
```

The installer verifies source and asset hashes. It performs no local build.
Local coding stays within four total CLI processes, reduced for other active
work or CPU/RAM pressure. Any necessary heavy local fallback uses one serial
slot after checking available resources. Do not launch editor windows.
