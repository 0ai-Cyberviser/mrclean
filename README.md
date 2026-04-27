# MrClean

MrClean is a policy-first automation agent scaffold for repository cleanup work.
It is aimed at the exact problem of letting AI models operate on repos and PRs
without guardrails: monitor signals, draft narrow actions, and run every action
through explicit policy checks before anything gets pushed or closed.

Owner: Johnny Watters (`0ai-Cyberviser`)
Primary contact: `0ai@cyberviserai.com`
Secondary contact: `cyberviser@proton.me`

## What it does

- Loads a simple TOML config for models, repos, and automation rules
- Builds cleanup plans for failing CI, stale PRs, and repo maintenance tasks
- Applies safety policy before allowing pushes, PR closure, or risky edits
- Ships with a deterministic stub model client so the project runs without an
  external model provider on day one
- Scans live GitHub PR state through the `gh` CLI and only drafts fix plans for
  PRs that actually need attention
- Supports repository-level PR author filters so upstream repo monitoring can
  stay scoped to the operator's own PRs instead of scanning every open branch
- Detects older PRs that appear superseded by a newer branch failing the same
  monitored checks, so the operator can close stale work intentionally
- Reads configured local checkouts to attach real changed-file context and
  branch-mismatch warnings to scan results
- **Zero-Day Detection**: Automatically identifies potential security vulnerabilities
  by detecting failures in security checks (semgrep, codeql, snyk) and fuzzing
  tools (oss-fuzz, cifuzz), flagging them as critical findings
- **Multi-Model Routing**: Intelligently routes different tasks to appropriate AI
  models based on task type and priority, optimizing for both cost and quality

For detailed information on these enhancements, see [ENHANCEMENTS.md](ENHANCEMENTS.md).

## Project layout

- `src/mrclean/config.py`: config loading and validation
- `src/mrclean/policies.py`: policy engine and action gating
- `src/mrclean/models.py`: model client abstraction
- `src/mrclean/github.py`: GitHub CLI integration for PR and check inspection
- `src/mrclean/workspace.py`: local git workspace inspection for branch and diff context
- `src/mrclean/monitor.py`: repo scanner that turns live PR state into cleanup plans
- `src/mrclean/watch.py`: polling queue that emits appeared, updated, and resolved events
- `src/mrclean/dispatch.py`: dry-run executor that turns queue items into guarded action candidates
- `src/mrclean/assess.py`: deterministic risk assessment for false positives, stale signals, and runtime blockers
- `src/mrclean/runner.py`: safe local runner for inspect and prep commands from dispatch candidates
- `src/mrclean/proposals.py`: bounded edit proposal generation from prepared candidates
- `src/mrclean/intents.py`: validated machine-readable edit intents for a later executor
- `src/mrclean/materialize.py`: local intent resolution against the checkout with hashes and previews
- `src/mrclean/drafts.py`: guarded file-write bundle generation with hash preconditions
- `src/mrclean/previews.py`: unified diff rendering from guarded draft bundles
- `src/mrclean/apply.py`: hash-checked local apply transactions with rollback
- `src/mrclean/agent.py`: MrClean planning agent
- `src/mrclean/logger.py`: structured workflow execution logging with persistence
- `src/mrclean/learning.py`: pattern analysis and historical insights from workflow logs
- `src/mrclean/cli.py`: `init`, `validate`, `plan`, `scan`, `watch`, `dispatch`, `assess`, `run`, `propose`, `intent`, `materialize`, `draft`, `preview`, `apply`, `workflow`, and `learn` commands
- `mrclean.toml.example`: starting config

## Quick start

```bash
cd /home/oai/mrclean
PYTHONPATH=src python -m mrclean validate mrclean.toml.example

# Generate shell completion (Kali Linux compatible)
PYTHONPATH=src python -m mrclean completion bash > /etc/bash_completion.d/mrclean
# or for zsh
PYTHONPATH=src python -m mrclean completion zsh > ~/.zsh/completion/_mrclean

# Use colored output (auto-enabled on Kali terminals)
PYTHONPATH=src python -m mrclean --kali-mode scan mrclean.toml.example --repo 0ai-Cyberviser/Hancock

# Original commands still work
PYTHONPATH=src python -m mrclean plan mrclean.toml.example \
  --repo 0ai-Cyberviser/Hancock \
  --goal "stabilize failing CI and keep patches narrow" \
  --check build-linux \
  --changed-file hancock_agent.py
PYTHONPATH=src python -m mrclean scan mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean watch mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub \
  --interval 30
PYTHONPATH=src python -m mrclean dispatch mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean assess mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean run mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean propose mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean intent mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub --json
PYTHONPATH=src python -m mrclean materialize mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean draft mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
export MRCLEAN_ARTIFACT_SIGNING_KEY="replace-with-a-review-artifact-secret"
PYTHONPATH=src python -m mrclean preview mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub \
  --output reviewed-preview.json
PYTHONPATH=src python -m mrclean apply my-write-enabled.toml \
  --preview-file reviewed-preview.json --execute
```

`scan` requires GitHub CLI authentication via `gh auth login` or an existing
authenticated `gh` session.

## Integrated Workflow: Monitor-Audit-Review-Test-Log-Learn-Repeat

MrClean provides an integrated `workflow` command that harnesses all phases into a continuous improvement cycle:

```bash
# Run a single workflow cycle
PYTHONPATH=src python -m mrclean workflow mrclean.toml.example

# Continuous monitoring with 5-minute intervals
PYTHONPATH=src python -m mrclean workflow mrclean.toml.example \
  --iterations 0 --interval 300

# Enable learning insights display
PYTHONPATH=src python -m mrclean workflow mrclean.toml.example \
  --show-learning

# Auto-apply mode for high-confidence items (requires policy configuration)
PYTHONPATH=src python -m mrclean workflow mrclean.toml.example \
  --auto-apply --iterations 0 --interval 600
```

### Workflow Phases

1. **MONITOR**: Scan configured repositories for failing CI and issues
2. **AUDIT**: Assess false positive risk, runtime issues, and security concerns
3. **REVIEW**: Generate proposals for actionable items
4. **TEST**: Execute safe inspection commands
5. **LOG**: Persist all workflow execution data to `~/.mrclean/logs/`
6. **LEARN**: Analyze patterns from historical data
7. **REPEAT**: Continue monitoring at configured intervals

### Learning Analytics

Analyze historical workflow logs to identify patterns and improve decision-making:

```bash
# View global learning insights
PYTHONPATH=src python -m mrclean learn

# Analyze specific repository patterns
PYTHONPATH=src python -m mrclean learn --repository 0ai-Cyberviser/Hancock

# Export insights as JSON
PYTHONPATH=src python -m mrclean learn --json > insights.json
```

Learning analytics include:
- False positive pattern detection
- Security vulnerability indicators (zero-day detection patterns)
- Check reliability scores
- Common failure patterns
- Success rates per repository

All workflow data is logged to `~/.mrclean/logs/` in structured JSONL format for analysis and debugging.

## AI Model Providers

MrClean supports multiple AI model providers for generating cleanup plans and edit proposals:

### OpenAI (GPT models)
```toml
[model]
provider = "openai"
name = "gpt-4"
```
Set `OPENAI_API_KEY` environment variable. Optionally set `OPENAI_BASE_URL` for custom endpoints.

### Anthropic Claude
```toml
[model]
provider = "anthropic"  # or "claude"
name = "claude-3-5-sonnet-20241022"
```
Set `ANTHROPIC_API_KEY` environment variable.

### Google Gemini
```toml
[model]
provider = "gemini"  # or "google" or "google_gemini"
name = "gemini-1.5-pro"
```
Set `GOOGLE_API_KEY` or `GEMINI_API_KEY` environment variable.

### GitHub Copilot
```toml
[model]
provider = "copilot"  # or "github_copilot"
name = "gpt-4"
```
Set `GITHUB_COPILOT_API_KEY` or `COPILOT_API_KEY` environment variable. Optionally set `GITHUB_COPILOT_BASE_URL` for custom endpoints.

### Stub Provider (Default)
```toml
[model]
provider = "stub"
name = "deterministic-stub"
```
No API key required. Returns deterministic placeholder responses for testing without external dependencies.

## Kali Linux Terminal Features

MrClean includes optimizations for Kali Linux terminals:

- **Auto-detected color support**: Automatically enables ANSI colors when running in compatible terminals
- **Kali-themed output**: Uses Kali's signature blue and dragon orange colors
- **Shell completion**: Bash and Zsh completion scripts with auto-complete for commands and options
- **UTF-8 symbols**: Success (✓), error (✗), warning (⚠), and info (ℹ) symbols for better readability
- **--no-color flag**: Disable colors for piping or scripting
- **--kali-mode flag**: Force Kali-optimized styling

Install shell completion:
```bash
# Bash (Kali default)
mrclean completion bash | sudo tee /etc/bash_completion.d/mrclean
source ~/.bashrc

# Zsh
mrclean completion zsh > ~/.zsh/completion/_mrclean
```

Set `authors = ["your-github-login"]` in a `[[repositories]]` block when you
want MrClean to monitor only specific PR authors in an upstream repo. This
matters for repos like `google/oss-fuzz` where scanning every open PR would
make the queue noisy and unsafe. For app-authored PRs, use the real login such
as `app/copilot-swe-agent`.

When multiple open PRs in one repo are failing the same monitored checks,
MrClean keeps the newest PR in `needs_attention` and marks older siblings as
`superseded_candidate`. Those stale-close recommendations still go through the
same dry-run and close-PR policy gates.

When a repository has `local_path` configured, `scan` also inspects the local
checkout. Changed files are only attached when the checkout is already on the
same branch as the PR head; otherwise MrClean emits a workspace note instead of
pretending it has the right diff.

`watch` builds on the same queue and only emits changes: new queue entries,
updated entries, and items resolved out of the queue. Use `--iterations 1` for
a single polling cycle in scripts, or leave it running for continuous
monitoring. It also emits assessment deltas, so a PR can produce an update even
when the raw scan data is unchanged but the risk gate shifts between
`actionable`, `verify`, and `hold`.

`dispatch` stays dry-run and policy-first. It converts the current queue into
execution candidates, marks whether each item is `ready`, `inspect_only`, or
`deferred`, and shows which actions are blocked by policy or by a workspace
mismatch before any real write step exists. Assessment now feeds the queue
directly: `hold` items are deferred, pushed down the queue, and have their
non-inspection actions blocked until the operator resolves the signal-quality
problem.

`assess` is the second lane after audit. It sits between scan/dispatch and the
execution pipeline, and estimates false-positive risk, runtime risk, signal
staleness, branch drift, and likely operator error before MrClean proposes or
applies anything. Use it to decide whether a failing PR is truly actionable,
needs verification, or should be held until CI/workspace conditions improve.

`run` is still non-mutating. It executes only safe prep commands from dispatch
results, such as GitHub inspection and local diff/status gathering. Actions
like `push_commit` and `close_pr` remain blocked behind policy and are never run
by this local runner. It now requires an `actionable` assessment by default.
Use `--allow-verify` only after explicit review if you want to run a
verify-rated candidate.

`propose` builds on `run`: it gathers the same safe local context, then asks the
configured model client for a bounded edit proposal. If `provider = "openai"`
and `OPENAI_API_KEY` is present, MrClean uses the installed OpenAI client.
Otherwise it falls back to the deterministic stub client and still returns a
proposal without disabling any protections. It also requires an `actionable`
assessment by default. Use `--allow-verify` only when you intentionally want to
carry a verify-rated candidate further down the pipeline.

`intent` goes one step further and requires machine-readable JSON with a
validated edit schema. Paths must stay relative, operations are constrained to
`modify`/`create`/`delete`, duplicate file targets are rejected, and the edit
count still respects `policy.max_patch_files`.

`materialize` validates those intents against the local checkout. It checks that
the workspace still matches the target branch, resolves absolute file paths,
verifies operation semantics (`modify`/`delete` require an existing file,
`create` requires a missing file with an existing parent directory), blocks
paths outside the current branch diff, and emits hashes plus previews without
writing anything.

`draft` builds on `materialize` and still stays non-mutating. It converts ready
materialized edits into explicit `write_file` or `delete_file` operations,
captures the expected pre-edit file hash for each target, and emits content
hashes plus previews for generated file bodies. If the workspace is not ready,
the file is not readable as UTF-8 text, or the generated operation drifts from
the materialized file set, MrClean blocks the draft instead of pretending it is
safe to apply.

`preview` builds on `draft` and stays read-only as well. It rechecks the
current file hash against each draft bundle's expected precondition, then
renders a unified diff only when the on-disk file still matches the validated
draft input. If the file changed since draft generation, is missing, or is not
UTF-8 text, MrClean blocks the preview instead of showing a stale diff. Use
`--output` to save the exact reviewed preview artifact for a later apply step.
If `policy.artifact_signing_key_env` is set in the config and that environment
variable is present, MrClean signs the saved artifact with HMAC-SHA256 so apply
can verify it was not altered after review.

`apply` is the first real write path. It stays disabled by default and requires
both `policy.allow_local_apply = true` and `policy.dry_run = false`, plus an
explicit `--execute` flag on the CLI. It consumes a saved preview artifact via
`--preview-file`, verifies the artifact signature by default, rechecks the
expected pre-edit hash immediately before writing, and confirms the current
checkout still matches the configured repository root and target branch with no
uncommitted changes. Writes use atomic file replacement, and MrClean rolls back
partial local changes if a multi-file apply fails mid-transaction. It returns a
nonzero exit code when the transaction is blocked or rolled back. It does not
push, commit, or close PRs.

## Design stance

MrClean is intentionally conservative.

- No force-push by default
- No local apply by default
- Signed preview artifacts required by default for real writes
- No writes to protected branches
- No PR closure unless explicitly enabled
- No wide patches when the file count crosses policy limits
- Dry-run stays on by default

That is the point of the project: automate repo cleanup without pretending blind
automation is safe by default.

## Protections

The protection model is part of the project, not an optional layer.

- Pushes are disabled by default
- Local apply is disabled by default
- Force-push is disabled by default
- Reviewed preview artifacts are signed and verified by default
- Protected branches stay blocked by policy
- PR closure is disabled unless explicitly enabled
- Risky actions are blocked while dry-run is enabled
- Wide patches are rejected once they exceed policy file-count limits

Any future model integration should preserve those defaults unless an operator
changes policy intentionally.

## License

MrClean is distributed under the [MIT License](LICENSE). See [OWNERSHIP.md](OWNERSHIP.md) for repository-control and maintainer details.

- Repository administration and release approval: Johnny Watters (`0ai-Cyberviser`)
- Current and prior published releases remain under MIT
- Maintainers may require additional rights confirmation before merging a contribution
- Project contacts: `0ai@cyberviserai.com` · `cyberviser@proton.me`
