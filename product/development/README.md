# Project Meridian — early submission draft

Status: **2026-11-05, development snapshot; incomplete application.** The server, Chat/Parts shell, persistent past-chat storage/APIs/UI, evidence widgets, drawing/BOM extraction, decision journal and determine/verify job definitions are integrated. Full grounded chat sending, effective records, the actual new preparation run, source-derived CAD, Review/Parts integration and V1?V5 remain unfinished. This is not a stable M1 submission.

Scope and dependencies are in [PLAN](docs/PLAN.md) and [WORKFLOW](docs/WORKFLOW.md); module IDs M01–M27 differ from milestones M0–M3.

## Current setup

The [locked uv project](pyproject.toml) requires Python **3.12** (`>=3.12,<3.13`). From the product root, these are the configured setup/launch commands; they were **not executed for this draft**:

```powershell
cd development
uv sync --locked
uv run meridian
```

[The launcher](backend/launcher.py) now has its M03 server implementation and targets `127.0.0.1:8000`; the `start.bat` / `start.sh` wrappers forward launch flags. Use a matching remote frontend bundle, as described below. The installed local bundle from checks run 42027497046 has been matched to frontend source and file hashes without a local build. This snapshot exposes the history screen and shell; ordinary Parts/Review producer integration and grounded sends are pending. CAD/prep dependencies are optional extras. Normal startup does not initiate paid preparation.

Key location is configured in [ai_settings.yaml](ai_settings.yaml): `.secrets/OpenAI_API_Keys.txt`, defaulting to `../../../.secrets` relative to `development/`. Set `MERIDIAN_SECRETS_DIR` to an existing private directory for another checkout, especially a worktree. Relative overrides resolve from `development/`. [Settings](backend/settings.py) currently resolve the path and check nonempty-file presence; this does **not** validate credentials or establish that the grounded send loop is implemented. Server-side client integration remains part of the pending send work. Never place keys in browser assets, Git, logs or CLI subprocess environments. The key-free [.env.example](.env.example) documents variables; it is not automatically loaded.

Debug is configured hidden by default. The existing launcher accepts `uv run meridian --debug` or `--no-debug`; flags override `MERIDIAN_DEBUG=1` (enabled) / unset or `0` (disabled). The M03 status and M04 shell carry this setting to the integrated Chat/evidence UI. Ordinary Chat/Parts views must use only **Human reviewed**, **AI reviewed**, or **Unavailable**, honestly derived from evidence. Review controls, engineering review queues, verifier findings, disagreements, unverified/fallback provenance, weight details, history/accuracy diagnostics and hashes belong inside Debug. Source navigation and reconstruction identification remain in customer views.

## Architecture and model disclosure

The design uses local JSON artifacts and explicit contracts so original evidence stays separate from interpretations and accepted corrections.

| Layer | Current implementation / remaining integration |
| --- | --- |
| Evidence | Unchanged corpus under `inputs/project-meridian/`; [M05](backend/loader/drawings.py) extracts positioned drawing evidence/images; [M06](backend/loader/bom.py) preserves BOM cells and normalizes recorded relationships. |
| Contracts and decisions | [Python contracts](backend/contracts.py), [TypeScript contracts](frontend/src/contracts.ts), and [M07 journal](backend/loader/decisions.py) exist. Accepted overlays remain separate from originals; pending/rejected proposals do not change effective values. Integrated review actions are pending. |
| Preparation → records → CAD/tools | Planned M08–M14 pipeline: saved source-bound AI results/templates → assembled `generated/` records → supported reconstructions and deterministic fact tools. Capability probes and synthetic contract fixtures exist; the complete production path is unfinished. Decisions stay outside regenerated outputs in `decisions/`. |
| Service and UI | M03 FastAPI history routes, M04 [shell](frontend/src/App.tsx), M17 evidence widgets and M18 [Chat history screen](frontend/src/chat/Chat.tsx) are integrated. Full send, shared part views, 3D and Review remain pending. |

Application chat is configured for **OpenAI Responses, `gpt-6-luna` only**, using the server's `.secrets` key, with no alternate model/provider. The chat service has not run here.

Preparation is configured to run **sequentially** through separately authenticated CLI accounts: Codex `gpt-6.1-sol`, **max / priority** (`service_tier: fast`), determines a source-backed candidate; Claude Code `claude-opus-5-5`, **xhigh / regular**, verifies that exact candidate against original evidence with field verdicts, reasons and references. One disagreement retry permits Sol revision followed by Opus reverification; retain both rounds and leave remaining uncertainty unresolved. Only an actual Opus execution failure after troubleshooting permits valid source-backed Sol-only output, explicitly **single-model, unverified**, retaining failure evidence and excluded from verified counts. Try Opus again on each later launch. Disagreement, invalid output and absent effective-setting metadata do not authorize fallback. Requested settings and CLI-observed settings must remain distinct.

The application API key is never passed to these CLIs. This design sends selected source evidence/candidates to the respective external providers through their CLI accounts; future chat sends tool results and selected conversation context to OpenAI. **Full new determine-then-verify AI prep has not run**; historical blind-reader outputs/cache do not verify this pipeline.

## Past chats

Use **New chat** to create a conversation, or select a saved conversation in the Chat list. The list uses first-message titles and updated-time ordering; reopening displays the complete saved messages, citations and attachments. Selection survives browser reload. History storage and no-key create/list/read APIs are implemented and tested separately from the browser screen. Actual grounded sends still return an explicit unavailable response until the pending send service is integrated; this snapshot does not claim a live end-to-end conversation.

Private JSON is stored at `development/chat_history/`, excluded by both Git boundaries. Override it with `MERIDIAN_CHAT_HISTORY_DIR` if needed; relative paths resolve from `development/`. Full messages and the server-owned per-thread tool ledger persist through service restart. Only the selected conversation's last **10 individual user/assistant messages, including the current user message**, are intended for Luna; another chat's context and citation authorization are never supplied. Reading history needs no API key or model call. No database or paid title generation is used.

## Accepted evidence and limitations

| Evidence already recorded | What it establishes |
| --- | --- |
| [A01 scaffold/config receipt](../testing/reports/ci/A01-scaffold-42009930140.json), candidate `51202ff` | Remote setup/config, Debug flags/history path, typecheck/build/contracts and focused regressions; no integrated UI or live prep credit. |
| [Drawing/BOM module receipt](../testing/reports/ci/B01-inputs-42003114928.json) | 12 focused remote checks, including actual source cases and synthetic coordinate cases; not a complete gate. |
| [Full deterministic extraction run 42004415297](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42004415297), `harness-v2` SHA `1ff300913aef189ad9b088f4b6f851730af9ac2c` | Accepted M05/M06 extraction of **30 drawings / 33 pages / 192 BOM rows**, without AI or human review. Typed extraction is not full engineering verification. |
| [Contracts/journal receipt](../testing/reports/ci/B01-contracts-decisions-42007163333.json) | Focused contracts/journal and regression checks; synthetic review actions are not real human approvals. |
| [History Linux receipt](../testing/reports/ci/A15-history-linux-42018990416.json), [Windows receipt](../testing/reports/ci/A15-history-windows-42019459097.json), [history API receipt](../testing/reports/ci/A03-server-42024538410.json) | Saved full history/private ledger, restart/context isolation, bounded OS locks and real no-key HTTP routes. No full Luna sending credit. |
| [History browser receipt](../testing/reports/ci/A18-history-ui-42027497211.json), [shell receipt](../testing/reports/ci/A04-shell-42023675585.json) | Actual deterministic Playwright UI interactions and source-matched typecheck/build. Browser API objects were scripted; full real-backend/provider journey remains pending. Earlier failing browser runs remain preserved in test reports. |
| [Vision receipt](../testing/reports/ci/A09-vision-42027501528.json), [relationship receipt](../testing/reports/ci/A10-matching-42029971659.json) | Source/candidate/domain validation under scripted tests; latest cumulative Python run passed 170/170, including 27 matching cases. No actual corpus model/source-accuracy or gate credit. |
| [Reader qualification](../testing/reports/qualification/A08-runner/QUALIFICATION.md), [CAD qualification](../testing/reports/qualification/A13-cad/QUALIFICATION.md), [remote render evidence](../testing/reports/ci/capability-41998597947/harness-v2-browser-41998597947/browser/report.json) | Historical synthetic image reading, invented geometry/export and headless rendering capability. None establishes source-derived dimensions, the three required reconstructed parts, or product readiness. |

**V1–V5: none passed; all remain unperformed.** V1 covers knowledge, V2 the governed backend, V3 complete M1, V4 M2 review integrity, V5 M3 consistency; semantic code reviews are scheduled only at V3/V4. Gate/rebuild/benchmark commands remain pending implementation and are not launch instructions for this version.

Real chat-to-drawing/3D demos, governed before/after corrections, human review coverage, source-engineering accuracy, prep verified/retry/unresolved/Sol-only counts, benchmark repeatability, latency, usage/cost, release screenshots/transcripts and a fresh-clone application check are **unavailable pending actual runs**. No measurements or human approvals are inferred from fixtures. [Benchmark questions](docs/benchmark_draft.md) are a preliminary evaluation draft, not observed answers. Human questions remain asynchronous in [USER_TODO](USER_TODO.md).

Builds, tests, PDF regeneration, CAD and browser verification run through GitHub Actions **only on `harness-v2` in `JasonPeng2019/proj-meridian`**, selecting the exact revision. Prefer the downloadable frontend bundle verified by [the installer](scripts/frontend_artifact.py); [remote instructions](docs/REMOTE_VERIFICATION.md) describe the implemented download command. The [install receipt](../testing/reports/ci/frontend-installed.json) records source-matched run 42027497046 with no local build; the bundle is the history/shell snapshot described above, not a complete product. Keep laptop work bounded: at most four CLI processes including prep children, one sequential prep job, reduced under load. Any separately authorized necessary heavy local fallback uses one shared serial slot after resource inspection. This documentation update used static inspection and the cited remote evidence; it did not execute a local build or test suite.

## Source and license attribution

The supplied corpus is curated from **DTUOpenAM/OpenLPBF_v2**, pinned at `98f76dad7b11d6f8fc7d59945d7fcf689df87ee7`. Preserve the supplied [attribution](inputs/project-meridian/ATTRIBUTION.md), [CERN-OHL-P-2.0 license](inputs/project-meridian/dataset/context/OpenLPBF-LICENSE.md), [manifest](inputs/project-meridian/dataset/manifest.json) and [orientation/caveats](inputs/project-meridian/dataset/README.md). The project-generated alias index `openlpbf-source-metadata.json` is separately **CC0-1.0**; that does not relicense upstream assets or application code.

Eight drawings are supplied scan-like derivatives modified **2026-09-02**; pristine counterparts are absent. Vendor datasheets, native CAD, logos and photographs were omitted. BOM costs, suppliers and lifecycle states describe a pinned snapshot, not current procurement facts. Drawing and BOM claims must retain separate provenance and uncertainty. No upstream notices were changed for this draft.

Reconstruction disclosure (draft dated **2026-11-05**): future delivered models must say **“Reconstruction from 2D drawing. Not the original CAD model.”** No source-derived reconstruction or engineering validation is claimed by this early guide.
