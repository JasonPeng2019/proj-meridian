# Testing workspace

Run every test from this directory or an isolated copy beneath it. Application source remains in `../development/`. Test suites live in `tests/` (backend) and `frontend/` (browser); test evidence belongs in `reports/verification/`, release captures in `releases/`, and private execution data in `tmp/`, `cache/`, or `runs/`.

Harness validation is infrastructure work: its focused checks and reports live in `harness/` and `reports/harness/`, separate from product verification. Bundled test sources in the harness copy may be imported read-only; execute them here with temporary files and caches redirected here.

Use fake provider responses and temporary decision journals for deterministic tests. Do not read the real application API key or write synthetic decisions into the actual dataset journal. Human review items go to `../development/USER_TODO.md` and do not stop testing or coding.
