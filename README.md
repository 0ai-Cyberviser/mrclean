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
- Detects older PRs that appear superseded by a newer branch failing the same
  monitored checks, so the operator can close stale work intentionally
- Reads configured local checkouts to attach real changed-file context and
  branch-mismatch warnings to scan results

## Project layout

- `src/mrclean/config.py`: config loading and validation
- `src/mrclean/policies.py`: policy engine and action gating
- `src/mrclean/models.py`: model client abstraction
- `src/mrclean/github.py`: GitHub CLI integration for PR and check inspection
- `src/mrclean/workspace.py`: local git workspace inspection for branch and diff context
- `src/mrclean/monitor.py`: repo scanner that turns live PR state into cleanup plans
- `src/mrclean/watch.py`: polling queue that emits appeared, updated, and resolved events
- `src/mrclean/dispatch.py`: dry-run executor that turns queue items into guarded action candidates
- `src/mrclean/runner.py`: safe local runner for inspect and prep commands from dispatch candidates
- `src/mrclean/proposals.py`: bounded edit proposal generation from prepared candidates
- `src/mrclean/agent.py`: MrClean planning agent
- `src/mrclean/cli.py`: `init`, `validate`, `plan`, `scan`, `watch`, `dispatch`, `run`, and `propose` commands
- `mrclean.toml.example`: starting config

## Quick start

```bash
cd /home/oai/mrclean
PYTHONPATH=src python -m mrclean validate mrclean.toml.example
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
PYTHONPATH=src python -m mrclean run mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
PYTHONPATH=src python -m mrclean propose mrclean.toml.example \
  --repo 0ai-Cyberviser/CyberViser-ViserHub
```

`scan` requires GitHub CLI authentication via `gh auth login` or an existing
authenticated `gh` session.

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
monitoring.

`dispatch` stays dry-run and policy-first. It converts the current queue into
execution candidates, marks whether each item is `ready`, `inspect_only`, or
`deferred`, and shows which actions are blocked by policy or by a workspace
mismatch before any real write step exists.

`run` is still non-mutating. It executes only safe prep commands from dispatch
results, such as GitHub inspection and local diff/status gathering. Actions
like `push_commit` and `close_pr` remain blocked behind policy and are never run
by this local runner.

`propose` builds on `run`: it gathers the same safe local context, then asks the
configured model client for a bounded edit proposal. If `provider = "openai"`
and `OPENAI_API_KEY` is present, MrClean uses the installed OpenAI client.
Otherwise it falls back to the deterministic stub client and still returns a
proposal without disabling any protections.

## Design stance

MrClean is intentionally conservative.

- No force-push by default
- No writes to protected branches
- No PR closure unless explicitly enabled
- No wide patches when the file count crosses policy limits
- Dry-run stays on by default

That is the point of the project: automate repo cleanup without pretending blind
automation is safe by default.

## Protections

The protection model is part of the project, not an optional layer.

- Pushes are disabled by default
- Force-push is disabled by default
- Protected branches stay blocked by policy
- PR closure is disabled unless explicitly enabled
- Risky actions are blocked while dry-run is enabled
- Wide patches are rejected once they exceed policy file-count limits

Any future model integration should preserve those defaults unless an operator
changes policy intentionally.

## License

MrClean is released under the MIT License. See [LICENSE](/home/oai/mrclean/LICENSE).
