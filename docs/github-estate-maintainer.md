# MrClean GitHub Estate Maintainer Blueprint

MrClean is intended to be the policy-first automation agent for maintaining the full CyberViser / 0AI GitHub estate. This blueprint defines the target operating model, safe automation lanes, configuration surface, and implementation roadmap.

## Mission

MrClean should continuously maintain repositories, pull requests, workflows, labels, issues, rulesets, release hygiene, and security configuration across owned or authorized GitHub repositories while preserving strict guardrails.

The agent should be able to answer and act on questions like:

- Which PRs need attention right now?
- Which failing checks are stale, flaky, security-critical, or superseded?
- Which repositories are missing branch protection, labels, SECURITY.md, CODEOWNERS, or CI?
- Which labels, workflows, and policy files drifted from the CyberViser standard?
- Which PRs can be safely updated, labeled, commented on, closed, or queued for human review?
- Which repositories need dataset, fuzzing, security, or docs maintenance?

## Non-negotiable safety model

MrClean should remain conservative by default.

- dry-run enabled by default
- no force-push by default
- no branch deletion by default
- no direct push to protected branches
- no PR closure unless explicitly enabled
- no write action without policy evaluation
- signed preview artifacts required before local apply
- repo-specific allowlists for write-capable automation
- explicit operator approval for destructive actions
- full audit trail for every recommendation and action

## Capability lanes

### 1. PR command center

Track all open PRs across configured repos and classify them into actionable queues.

Recommended states:

- `needs_attention`
- `ci_failed`
- `security_critical`
- `fuzzing_failed`
- `merge_conflict`
- `stale_candidate`
- `superseded_candidate`
- `awaiting_review`
- `ready_to_merge`
- `blocked_by_policy`
- `human_review_required`

Actions:

- summarize PR status
- detect failed workflows/checks
- identify changed files
- label PRs by type and risk
- comment with status summaries
- recommend next action
- open follow-up issues
- close stale/superseded PRs only when policy allows

### 2. Repository policy audit

Audit each configured repository for required baseline controls.

Checks:

- default branch is expected
- branch protection/rulesets exist
- required status checks are configured
- SECURITY.md exists
- LICENSE exists
- README exists
- CODEOWNERS exists when required
- Dependabot config exists when required
- CodeQL or equivalent security scanning exists when required
- issue templates and PR templates exist
- labels match standard taxonomy
- GitHub Pages settings are expected for site repos

### 3. Label and issue taxonomy sync

Maintain consistent labels across repos.

Baseline labels:

- `type:bug`
- `type:docs`
- `type:feature`
- `type:security`
- `type:fuzzing`
- `type:dataset`
- `type:ci`
- `risk:low`
- `risk:medium`
- `risk:high`
- `risk:critical`
- `status:blocked`
- `status:needs-review`
- `status:ready`
- `agent:mrclean`
- `agent:hancock`
- `agent:peachfuzz`
- `agent:peachtree`

### 4. Workflow failure intelligence

Group and summarize workflow failures across repositories.

Signals:

- lint failure
- test failure
- Pages deployment failure
- dependency install failure
- security scan failure
- fuzzing crash/failure
- branch protection failure
- merge conflict
- flaky rerun candidate

Output:

- one-line status
- probable root cause
- affected files
- recommended fix path
- whether a PR can be generated safely

### 5. Security and fuzzing escalation

Raise priority when checks indicate risk.

Critical signals:

- CodeQL/semgrep/security scanner failures
- dependency vulnerabilities
- fuzzing crashes
- sanitizer failures
- secret scanning findings
- suspicious workflow permission changes
- privileged GitHub Actions token usage
- unexpected changes to security policy files

### 6. Dataset and documentation maintenance

Coordinate with PeachTree, PeachFuzz, and Hancock.

Tasks:

- identify repos with new dataset-worthy changes
- open dataset update PRs
- summarize fuzzing crash triage into sanitized records
- detect stale docs or broken ecosystem links
- keep repo README files aligned with CyberViser site copy

## Proposed command surface

```bash
mrclean estate inventory mrclean.toml
mrclean estate audit mrclean.toml --format markdown --output reports/estate-audit.md
mrclean prs queue mrclean.toml --all --format json
mrclean prs summarize mrclean.toml --repo 0ai-Cyberviser/Hancock
mrclean labels plan mrclean.toml --repo 0ai-Cyberviser/Hancock
mrclean labels apply mrclean-write.toml --repo 0ai-Cyberviser/Hancock --execute
mrclean workflows failures mrclean.toml --all --since 7d
mrclean policy report mrclean.toml --all
mrclean maintain plan mrclean.toml --all --output reports/maintenance-plan.md
```

## Configuration model

```toml
[estate]
owner = "0ai-Cyberviser"
mode = "dry-run"
report_dir = "reports/mrclean"

[estate.defaults]
require_security_md = true
require_license = true
require_readme = true
require_codeowners = false
require_dependabot = true
require_codeql = true
require_branch_protection = true

[automation]
allow_label_sync = true
allow_issue_comments = true
allow_pr_comments = true
allow_open_issues = true
allow_close_stale_prs = false
allow_merge = false
allow_branch_delete = false

[[repositories]]
name = "0ai-Cyberviser/Hancock"
base_branch = "main"
role = "agent-runtime"
labels = ["agent:hancock", "type:security", "type:fuzzing"]
monitored_checks = ["Test", "CodeQL", "semgrep", "oss-fuzz", "cifuzz"]

[[repositories]]
name = "0ai-Cyberviser/PeachTree"
base_branch = "main"
role = "dataset-engine"
labels = ["agent:peachtree", "type:dataset"]
monitored_checks = ["Test", "Lint"]

[[repositories]]
name = "0ai-Cyberviser/peachfuzz"
base_branch = "main"
role = "fuzzing-engine"
labels = ["agent:peachfuzz", "type:fuzzing"]
monitored_checks = ["Test", "Fuzz", "Regression"]
```

## Report shape

```json
{
  "schema_version": "mrclean.estate.v1",
  "generated_at": "2026-04-24T00:00:00Z",
  "repository": "0ai-Cyberviser/Hancock",
  "summary": {
    "open_prs": 3,
    "failing_prs": 1,
    "security_critical": 0,
    "stale_candidates": 1,
    "policy_findings": 2
  },
  "findings": [
    {
      "code": "missing_dependabot_config",
      "severity": "medium",
      "recommended_action": "open_issue",
      "policy_allowed": true
    }
  ]
}
```

## Implementation roadmap

### Phase 1: Estate inventory and reporting

- Add `estate inventory` command
- List configured repos and ownership metadata
- Read open PRs, issues, labels, and workflow summaries through GitHub CLI/API
- Emit JSON and Markdown reports

### Phase 2: PR queue and workflow intelligence

- Add cross-repo PR queue
- Group failed checks by category
- Detect stale/superseded PRs across repos
- Generate human-readable PR status summaries

### Phase 3: Label and policy sync

- Add label taxonomy planner
- Generate label create/update/delete plan
- Apply only when write policy and `--execute` allow it
- Add repository baseline policy audit

### Phase 4: Agentic maintenance PRs

- Generate safe maintenance PRs for docs/config drift
- Open follow-up issues for risky or ambiguous changes
- Add signed preview artifacts for all generated edits

### Phase 5: Full CyberViser automation mesh

- Integrate Hancock for security triage explanations
- Integrate PeachTree for dataset update planning
- Integrate PeachFuzz for fuzzing failure analysis
- Generate weekly estate health reports

## Operating principle

MrClean should automate the boring, repetitive, and high-signal maintenance work, but it should never silently perform destructive operations. The default output should be a clear plan, a policy decision, and a reviewable artifact.
