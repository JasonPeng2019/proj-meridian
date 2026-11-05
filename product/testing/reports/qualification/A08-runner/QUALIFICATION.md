# A08-runner B00 qualification

**PASS — dual-reader synthetic-image qualification.** Sol and Opus each returned the sure, correct result below and passed the same JSON Schema. Two Sol CLI invocations (one rejected before inference, one explicit correction); one Opus CLI invocation. No model substitution or additional consensus reader.

| Attempt | CLI | Requested settings | Exit | Elapsed | Image / schema | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| sol-1 | codex-cli 0.162.0 | gpt-6.1-sol; max; fast/priority; read-only | 1 | 0.090s | No output; not evaluated | invocation/argument |
| sol-2 | codex-cli 0.162.0 | Same; rejected provider overrides removed | 0 | 8.297s | Correct / PASS | Success; nonfatal catalog timeout |
| opus-1 | Claude Code 2.1.317 | claude-opus-5-5; xhigh; fastMode=false; fallbackModel=[]; Read/plan | 0 | 7.882s | Correct / PASS | Success |

The generated 1200×600 PNG prints `MERIDIAN B00` and `VALUE 4827`. Its SHA-256 is `4dd9e6582e30ce932b76eba0eeba8b0e84482793bfd031bd5ab433a3ccb012ec`. Neither prompt nor the schema contains those expected values. Both outputs were:

```json
{"printed_text":"MERIDIAN B00","printed_number":4827,"certainty":"sure"}
```

Validation used `jsonschema` 4.26.0 / `Draft202012Validator`, without repair. The object requires `printed_text` (string), `printed_number` (integer), and `certainty` (`sure` or `unsure`), with additional properties forbidden. Codex's captured last message matches its final JSONL message. Claude called `Read` once on `fixture.png`, received the exact PNG bytes (matching SHA-256), then called `StructuredOutput`.

Sol's first command failed while loading configuration: this installed CLI reserves the built-in `openai` provider ID. The permitted correction removed all `model_providers.openai.*` overrides, retaining the same model, effort, tier, image and schema. The corrected command succeeded and emitted `failed to refresh available models: request timed out`; that catalog warning did not prevent inference or schema validation. No external automatic retry loop was used. Built-in provider retry defaults remained on the corrected call; no retry/reconnect event appeared.

Codex JSONL did **not expose** effective model, reasoning effort, service tier or sandbox. Those values are recorded as requested, with effective values marked `not exposed`. Claude's init and assistant messages reported `claude-opus-5-5`; usage reported `service_tier=standard`, `speed=standard`, and `fast_mode_state=off` (`disabled_by_env`). It reported `per_turn_effort_active=true`, but the effective named effort and fallback list were **not exposed**. Its actual used-model list contained only Opus.

Sol usage: 11,712 input tokens, 0 cached input, 0 cache-write input, 170 output, 138 reasoning output; cost not exposed. Opus usage: 4 input, 6,524 cache-creation input, 5,344 cache-read input, 597 output (341 thinking); CLI-reported cost $0.06521679999999999 (list basis). Failed Sol usage/cost not exposed. Complete exposed usage objects are retained in [qualification.json](qualification.json).

All nested CLI processes ran in `testing/tmp/A08-runner/`. Codex used an ephemeral read-only invocation with hooks and command execution disabled; no model tool call appeared. Claude used safe/restricted mode, an empty settings-source list, explicit hook disablement, strict MCP settings, plan permissions and only Read plus StructuredOutput. Its init confirmed those tools, no MCP servers, no skills/slash commands, and no subagent was spawned. `--bare` was deliberately avoided because installed help says it excludes account OAuth.

Existing `CODEX_HOME` and `CLAUDE_CONFIG_DIR` were inherited unchanged. No credential/auth-file contents or `.secrets` were inspected, copied or printed by the experiment scripts, and product API-key variables were removed from child environments. Controlled captures, inputs and temp/state paths are inside this worktree. Ephemeral/no-persistence modes were requested; no OS-wide trace of internal CLI-account maintenance writes was performed.

Exact credential-free argv, equivalent PowerShell command lines, cwd, stdin paths, timestamps, exit/timing fields, requested/effective settings, diagnostics, help/version evidence and artifact hashes are in [qualification.json](qualification.json). Scripts, prompts, schema, PNG and raw transcripts remain ignored under `testing/tmp/A08-runner/`; only these two reports are committed. Reproduction uses those temporary assets and the recorded environment; no credential export is needed.

Provenance is **dual-reader**, `single_model_fallback=false`, `missing_opus_output=false`. This synthetic result is qualification data only. No supplied drawing, engineering answer, product source, B01 runner, caching/agreement/retry implementation, or full-corpus E2 validation is included. Real-source validation remains **not performed**. Proposed USER_TODO: none.

Installed help was checked before inference. Relevant references: [Codex CLI](https://learn.chatgpt.com/docs/cli/reference), [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference), [Claude settings](https://code.claude.com/docs/en/settings-reference), [Claude environment variables](https://code.claude.com/docs/en/env-vars), [Claude non-interactive execution](https://code.claude.com/docs/en/headless). Local execution evidence controls the results above.
