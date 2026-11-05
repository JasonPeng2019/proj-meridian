# Project workspace boundary

The only permitted write root for this project is:

`C:\Users\Jason\Documents\Jason\Take-Homes-Codex\active\Avathon`

All local project-related files and writes MUST remain inside this directory or its descendants. NOTHING may be written above or outside this repo.

On GitHub-hosted Actions runners, the equivalent project write root is the resolved `GITHUB_WORKSPACE`. Project outputs, caches, temporary files, virtual environments and verification clones stay under that checkout. Runner-managed tool provisioning and system dependencies may use the disposable runner's standard locations. This remote exception does not relax the local Windows boundary.

This includes source, tests, fixtures, generated data, models, decisions, documentation, screenshots, transcripts, logs, temporary files, dependency caches, virtual environments, browser profiles, downloaded browsers, worktrees, fresh-clone checks, archives, and tool session state.

- Run every project command with a working directory inside this root.
- Resolve output paths before writing. Reject paths, symlinks, or junctions that escape the root.
- Before recursive deletion or moving files, verify the resolved absolute targets remain inside the intended project directory.
- Configure process-local caches, TEMP/TMP, CLI state, and other mutable tool directories inside this root before invoking those tools.
- Do not perform global installations or change global tool configuration. Installed tools and existing credentials may be read without modifying them.
- Do not repurpose HOME, USERPROFILE, or CODEX_HOME as shell variables. Configure documented tool environment variables only for project processes.
- Keep secrets ignored by Git and out of logs, browser code, and artifacts.
- Preserve supplied evidence unchanged. Keep human decisions append-only. Never author human approvals attributed to Jason Peng without his actual review action.
- These rules apply to every agent and subprocess working on this project.

## Implementation coordination

Parallel agents are authorized. Each agent owns only its assigned folders; the coordinator owns root configuration, shared contracts, Git, integration, and release artifacts. Do not change shared manifests or lockfiles without coordinating.

App chat MUST use `gpt-6-luna`. Dataset prep uses Claude Opus at regular speed and `gpt-6.1-sol` with xhigh reasoning and priority/Fast service. Do not silently substitute models or tiers.

Dataset prep runs Sol as proposer, then Opus verifies that exact proposal against the original evidence; allow one bounded feedback retry. Preserve legacy independent-reader receipts without relabelling them. Retain supported cuts independently, document omitted features, and assess all drawings within the MVP template limits. Never invent geometry or human approvals to increase the model count.

Jason has authorized delegated review of obvious engineering inputs. Record those append-only decisions with the actual inspecting actor, `review_kind: delegated`, and Jason as delegating authority; show `Jason Peng` and `Human reviewed` in the live app and Debug History, per his explicit attribution instruction. Count authorized confirm/reject outcomes under the configured reviewer authority, separately from prep-model verification. Do not claim Jason personally inspected an item. Unsupported-template dispositions preserve unknown geometry and do not approve a design. The live product must consume the same decision files and refresh when their revision changes.

Launch coding subagents as `gpt-6.1-sol`, high reasoning, on priority/Fast mode. The project Codex configuration specifies these settings for root coding sessions as well.

## Resource limits

Default UI screens must stay focused and concise. Show the task, core values and essential uncertainty/check state; put full source text, raw records, fingerprints, reasoning, extra filters and calculations behind tabs or explicit disclosure. Avoid duplicate navigation and repeated warning panels. Keep evidence and review controls accessible in Debug.

Keep routine local work lightweight: edits, source inspection, static validation and Git operations. Build the frontend remotely and download its verified static bundle for local use; Node is unnecessary for serving it. Run full verification, PDF/CAD regeneration and browser checks on GitHub-hosted Actions runners. Use `scripts/local_build.ps1` only when a local fallback build is necessary. CLI coding/prep agents remain outside Actions.

Dataset-prep CLI readers have a hard cap of four concurrent processes. Coding agents are excluded from that reader-specific limit, but use a conservative overall budget of at most four active local CLI workers for this project and reduce it when RAM/CPU headroom is limited. Do not raise the prep cap from the command line or configuration.

Run heavy stages in succession, never simultaneously. Queue Actions runs in the shared `meridian-heavy` concurrency group. Do not add a parallel matrix or launch concurrent heavy subprocesses. Limit numerical/CAD worker threads. Local builds must wait for enough free RAM and low enough CPU load, cap workers/Node heap, and hold the shared lock until every child exits. Do not parallelize local heavy work without measured resource headroom. Never stop unrelated user processes to free resources.

“Manual” workflow runs mean the coordinator dispatches and monitors them autonomously, not that Jason must click, confirm or run them. Lightweight push checks cancel superseded runs. The coordinator triggers heavy checks at integration checkpoints and paid API checks when needed. Use GitHub Actions secrets; if secrets cannot be used there, run the necessary API checks locally in sequence with resource headroom. Human review of engineering evidence still means actual human review; workflow dispatch authorization must never be misrepresented as a design approval.

Customer launches hide the engineering Debug tab by default. Use `meridian --debug-ui` (or `MERIDIAN_DEBUG_UI=1`) to show it; `--hide-debug` overrides that environment setting. Keep raw records, model calculations, fingerprints, AI reader receipts and history in Debug. Latest customer UI requirement: weight failures, manual-review requirements, detailed verification and omissions live in Debug only. Regular part views show only the simple review/availability status (Human reviewed, AI reviewed, or Unavailable), core values and source access. Do not repeat engineering warnings or per-field review labels in customer screens.

For the current UI comparison, keep the existing app and installed frontend on port 8000. Serve the Embedder public-homepage design on port 8001 using `scripts/serve_ui_preview.py` and a pinned, verified remote artifact. Do not replace `frontend/dist` with that redesign until Jason requests replacing the comparison baseline. Backend and evidence work can continue independently. The chosen reference is the public homepage at embedder.com, not its signed-in app. Apply that visual style to the original pre-package UI layout (baseline commit 9d066dc), preserving its original Meridian mark and native controls; do not use the rejected shadcn layout or replacement logo.

Human free-text review entries go through the app backend format-only parser using `gpt-6-luna`; no local coding CLI is spawned for parsing. Parse into a validated preview, ask for missing information, then save only after the reviewer confirms the preview. Preserve the original wording and parser provenance with the append-only decision. Formatting assistance does not verify evidence or author a human approval. Keep existing structured choices and legacy decision replay compatible.

Authorized delegated input dispositions display `Human reviewed` in normal review labels, just as requested by Jason. Attribute these to Jason Peng in Debug History and normal review displays. Preserve the original executor and authorization in unchanged append-only receipts; this does not imply whole-design approval.
