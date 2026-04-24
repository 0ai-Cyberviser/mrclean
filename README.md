# MrClean

MrClean is the **policy-first GitHub estate maintenance agent** for CyberViser / 0AI.

It is built to manage pull requests, repository configuration, labels, workflow failures, stale work, security/fuzzing signals, and repo hygiene across authorized GitHub repositories without letting blind automation mutate protected branches or close work unsafely.

Owner: Johnny Watters (`0ai-Cyberviser`)
Primary contact: `0ai@cyberviserai.com`
Secondary contact: `cyberviser@proton.me`

## Mission

MrClean is intended to become the ultimate GitHub maintenance control plane for the CyberViser / 0AI ecosystem:

- monitor all configured repositories and PRs
- classify workflow failures, stale PRs, superseded branches, and policy drift
- summarize what needs attention across the GitHub estate
- keep labels, repo hygiene, and security baselines consistent
- generate safe maintenance plans and reviewable patches
- preserve dry-run, preview, signature, branch, and policy gates before writes

See [`docs/github-estate-maintainer.md`](docs/github-estate-maintainer.md) for the full estate-maintainer blueprint.

## What it does today

- Loads TOML config for models, repos, and automation rules
- Builds cleanup plans for failing CI, stale PRs, and repo maintenance tasks
- Applies safety policy before allowing pushes, PR closure, or risky edits
- Ships with a deterministic stub model client so the project runs without an external model provider on day one
- Scans live GitHub PR state through the `gh` CLI and only drafts fix plans for PRs that actually need attention
- Supports repository-level PR author filters so upstream repo monitoring can stay scoped to the operator's own PRs instead of scanning every open branch
- Detects older PRs that appear superseded by a newer branch failing the same monitored checks, so the operator can close stale work intentionally
- Reads configured local checkouts to attach real changed-file context and branch-mismatch warnings to scan results
- Detects potential security-critical CI signals from security scanners and fuzzing checks
- Supports multi-model routing by task type and priority

For detailed information on the v0.4.1 enhancements, see [ENHANCEMENTS.md](ENHANCEMENTS.md).

## Target GitHub automation capabilities

MrClean's estate-maintainer roadmap includes:

| Lane | Purpose |
|---|---|
| PR command center | Cross-repo PR queue, failing checks, stale work, superseded work, merge readiness |
| Repo policy audit | Branch protection, rulesets, README, LICENSE, SECURITY.md, CODEOWNERS, Dependabot, CodeQL |
| Label sync | Standard taxonomy for type/risk/status/agent labels |
| Workflow intelligence | Root-cause summaries for CI, Pages, lint, test, dependency, security, and fuzzing failures |
| Security escalation | Critical routing for CodeQL, Semgrep, dependency, secret-scan, fuzzing, and sanitizer failures |
| Dataset maintenance | Coordinate PeachTree, PeachFuzz, and Hancock dataset/update work |
| Safe write pipeline | Intent → materialize → draft → preview → signed artifact → apply, never blind writes |

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
- `src/mrclean/cli.py`: command interface
- `mrclean.toml.example`: starting config

## Quick start

```bash
cd /home/oai/mrclean
PYTHONPATH=src python -m mrclean validate mrclean.toml.example

# Generate shell completion
PYTHONPATH=src python -m mrclean completion bash > /etc/bash_completion.d/mrclean
PYTHONPATH=src python -m mrclean completion zsh > ~/.zsh/completion/_mrclean

# Scan a repo queue
PYTHONPATH=src python -m mrclean --kali-mode scan mrclean.toml.example --repo 0ai-Cyberviser/Hancock

# Watch/dispatch/assess failing PRs
PYTHONPATH=src python -m mrclean watch mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub --interval 30
PYTHONPATH=src python -m mrclean dispatch mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean assess mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub

# Generate bounded plans and reviewable patches
PYTHONPATH=src python -m mrclean run mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean propose mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean intent mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub --json
PYTHONPATH=src python -m mrclean materialize mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean draft mrclean.toml.example --repo 0ai-Cyberviser/CyberViser-ViserHub

# Save a signed review artifact, then apply only with explicit write-enabled policy
export MRCLEAN_ARTIFACT_SIGNING_KEY="replace-with-a-review-artifact-secret"
PYTHONPATH=src python -m mrclean preview mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub \
  --output reviewed-preview.json
PYTHONPATH=src python -m mrclean apply my-write-enabled.toml \
  --preview-file reviewed-preview.json --execute
```

`scan` requires GitHub CLI authentication via `gh auth login` or an existing authenticated `gh` session.

## AI model providers

MrClean supports multiple AI model providers for generating cleanup plans and edit proposals.

### OpenAI

```toml
[model]
provider = "openai"
name = "gpt-4"
```

Set `OPENAI_API_KEY`. Optionally set `OPENAI_BASE_URL` for custom endpoints.

### Anthropic Claude

```toml
[model]
provider = "anthropic"
name = "claude-3-5-sonnet-20241022"
```

Set `ANTHROPIC_API_KEY`.

### Google Gemini

```toml
[model]
provider = "gemini"
name = "gemini-1.5-pro"
```

Set `GOOGLE_API_KEY` or `GEMINI_API_KEY`.

### GitHub Copilot

```toml
[model]
provider = "copilot"
name = "gpt-4"
```

Set `GITHUB_COPILOT_API_KEY` or `COPILOT_API_KEY`. Optionally set `GITHUB_COPILOT_BASE_URL`.

### Stub provider

```toml
[model]
provider = "stub"
name = "deterministic-stub"
```

No API key required. Returns deterministic placeholder responses for testing without external dependencies.

## Kali Linux terminal features

MrClean includes optimizations for Kali Linux terminals:

- auto-detected color support
- Kali-themed output
- bash and zsh completion scripts
- UTF-8 success/error/warning/info symbols
- `--no-color` for piping or scripting
- `--kali-mode` to force Kali-optimized styling

## Existing command behavior

Set `authors = ["your-github-login"]` in a `[[repositories]]` block when you want MrClean to monitor only specific PR authors in an upstream repo. This matters for repos like `google/oss-fuzz` where scanning every open PR would make the queue noisy and unsafe. For app-authored PRs, use the real login such as `app/copilot-swe-agent`.

When multiple open PRs in one repo are failing the same monitored checks, MrClean keeps the newest PR in `needs_attention` and marks older siblings as `superseded_candidate`. Those stale-close recommendations still go through the same dry-run and close-PR policy gates.

When a repository has `local_path` configured, `scan` also inspects the local checkout. Changed files are only attached when the checkout is already on the same branch as the PR head; otherwise MrClean emits a workspace note instead of pretending it has the right diff.

`watch`, `dispatch`, `assess`, `run`, `propose`, `intent`, `materialize`, `draft`, `preview`, and `apply` form the safe automation pipeline. `apply` is the first real write path and stays disabled by default unless policy and `--execute` explicitly allow it.

## Design stance

MrClean is intentionally conservative.

- No force-push by default
- No local apply by default
- Signed preview artifacts required by default for real writes
- No writes to protected branches
- No PR closure unless explicitly enabled
- No wide patches when the file count crosses policy limits
- Dry-run stays on by default

That is the point of the project: automate repo cleanup without pretending blind automation is safe by default.

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

Any future model integration should preserve those defaults unless an operator changes policy intentionally.

## License

MrClean is distributed under the [MIT License](LICENSE). See [OWNERSHIP.md](OWNERSHIP.md) for repository-control and maintainer details.

- Repository administration and release approval: Johnny Watters (`0ai-Cyberviser`)
- Current and prior published releases remain under MIT
- Maintainers may require additional rights confirmation before merging a contribution
- Project contacts: `0ai@cyberviserai.com` · `cyberviser@proton.me`
