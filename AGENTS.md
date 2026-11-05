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

Launch coding subagents as `gpt-6.1-sol`, high reasoning, on priority/Fast mode. The project Codex configuration specifies these settings for root coding sessions as well.

## Resource limits

Keep local work lightweight: edits, source inspection, static validation and Git operations. Run frontend builds, PDF regeneration, CAD generation, full tests and browser verification on GitHub-hosted Actions runners. CLI coding/prep agents remain outside Actions.

Dataset-prep CLI readers have a hard cap of four concurrent processes. Coding agents are excluded from that four-reader limit. Do not raise the prep cap from the command line or configuration.

Run heavy stages in succession, never simultaneously. Queue Actions runs in the shared `meridian-heavy` concurrency group. Do not add a parallel matrix or launch concurrent heavy subprocesses. Limit numerical/CAD worker threads. If heavy local work is unavoidable, run one heavy process at a time and wait for it to exit before starting another.
