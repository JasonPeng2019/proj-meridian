# Project workspace boundary

The only permitted write root for this project is:

`C:\Users\Jason\Documents\Jason\Take-Homes-Codex\active\Avathon`

All project-related files and writes MUST remain inside this directory or its descendants. NOTHING may be written above or outside this repo.

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
