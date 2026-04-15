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

## Project layout

- `src/mrclean/config.py`: config loading and validation
- `src/mrclean/policies.py`: policy engine and action gating
- `src/mrclean/models.py`: model client abstraction
- `src/mrclean/agent.py`: MrClean planning agent
- `src/mrclean/cli.py`: `init`, `validate`, and `plan` commands
- `mrclean.toml.example`: starting config

## Quick start

```bash
cd /home/oai/mrclean
PYTHONPATH=src python -m mrclean.cli validate mrclean.toml.example
PYTHONPATH=src python -m mrclean.cli plan mrclean.toml.example \
  --repo 0ai-Cyberviser/Hancock \
  --goal "stabilize failing CI and keep patches narrow" \
  --check build-linux \
  --changed-file hancock_agent.py
```

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
