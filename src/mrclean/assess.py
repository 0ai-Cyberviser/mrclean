from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .dispatch import DispatchAction, DispatchCandidate
from .monitor import ScanResult


@dataclass(slots=True)
class AssessmentFinding:
    code: str
    severity: str
    summary: str
    evidence: str


@dataclass(slots=True)
class AssessmentReport:
    repository: str
    number: int
    title: str
    url: str
    branch: str
    category: str
    dispatch_status: str
    outcome: str
    false_positive_risk: str
    runtime_risk: str
    confidence: int
    recommended_action: str
    findings: tuple[AssessmentFinding, ...]


class CandidateAssessor:
    def __init__(self, *, now: datetime | None = None, stale_after: timedelta = timedelta(days=3)) -> None:
        self.now = now or datetime.now(timezone.utc)
        self.stale_after = stale_after

    def assess(
        self,
        results: tuple[ScanResult, ...],
        candidates: tuple[DispatchCandidate, ...],
    ) -> tuple[AssessmentReport, ...]:
        candidate_map = {(candidate.repository, candidate.number): candidate for candidate in candidates}
        reports = [
            self._assess_item(item, candidate_map.get((item.repository, item.number)))
            for item in results
        ]
        reports.sort(key=lambda item: (_outcome_rank(item.outcome), item.false_positive_risk, item.repository.lower(), item.number))
        return tuple(reports)

    def _assess_item(self, item: ScanResult, candidate: DispatchCandidate | None) -> AssessmentReport:
        findings: list[AssessmentFinding] = []
        false_positive_score = 0
        runtime_score = 0
        confidence = 100

        # Check for potential zero-day indicators
        zero_day_indicators = self._check_zero_day_indicators(item)
        if zero_day_indicators:
            findings.extend(zero_day_indicators)
            runtime_score += 3
            confidence -= 30

        if item.pending_checks:
            findings.append(
                AssessmentFinding(
                    code="pending_checks",
                    severity="high",
                    summary="Checks are still pending.",
                    evidence=", ".join(item.pending_checks),
                )
            )
            false_positive_score += 3
            confidence -= 25

        if item.category == "superseded_candidate":
            findings.append(
                AssessmentFinding(
                    code="superseded_branch",
                    severity="medium",
                    summary="A newer sibling PR is failing the same monitored checks.",
                    evidence=f"superseded by PR #{item.superseded_by}" if item.superseded_by else "older sibling detected",
                )
            )
            false_positive_score += 3
            confidence -= 20

        if item.workspace_notes:
            findings.append(
                AssessmentFinding(
                    code="workspace_mismatch",
                    severity="high",
                    summary="Local workspace is not ready for reliable validation.",
                    evidence="; ".join(item.workspace_notes),
                )
            )
            false_positive_score += 1
            runtime_score += 2
            confidence -= 25
        elif not item.workspace_path:
            findings.append(
                AssessmentFinding(
                    code="missing_workspace",
                    severity="medium",
                    summary="No local checkout is configured for this repository.",
                    evidence="local_path is missing",
                )
            )
            false_positive_score += 1
            runtime_score += 1
            confidence -= 15

        if item.category == "needs_attention" and not item.changed_files:
            findings.append(
                AssessmentFinding(
                    code="missing_changed_files",
                    severity="medium",
                    summary="No branch-scoped changed files were attached to the failing PR.",
                    evidence="changed_files is empty",
                )
            )
            false_positive_score += 1
            runtime_score += 1
            confidence -= 10

        if len(item.failing_checks) > 1:
            findings.append(
                AssessmentFinding(
                    code="multi_check_failure",
                    severity="medium",
                    summary="Multiple monitored checks are failing.",
                    evidence=", ".join(item.failing_checks),
                )
            )
            runtime_score += 2
            confidence -= 10

        if item.merge_state_status and item.merge_state_status.upper() not in {"CLEAN", "HAS_HOOKS", "UNSTABLE"}:
            findings.append(
                AssessmentFinding(
                    code="merge_state",
                    severity="medium",
                    summary="Merge state indicates extra review before patching.",
                    evidence=item.merge_state_status,
                )
            )
            runtime_score += 1
            confidence -= 10

        updated_at = _parse_timestamp(item.updated_at)
        if updated_at is not None and self.now - updated_at > self.stale_after:
            findings.append(
                AssessmentFinding(
                    code="stale_signal",
                    severity="low",
                    summary="The PR signal is stale.",
                    evidence=item.updated_at,
                )
            )
            false_positive_score += 1
            confidence -= 10

        dispatch_status = candidate.status if candidate is not None else "unknown"
        if candidate is not None and candidate.status == "blocked":
            findings.append(
                AssessmentFinding(
                    code="dispatch_blocked",
                    severity="high",
                    summary="Dispatch already blocked action on this candidate.",
                    evidence=candidate.workspace_reason,
                )
            )
            runtime_score += 1
            confidence -= 10
        elif candidate is not None and candidate.status == "inspect_only":
            findings.append(
                AssessmentFinding(
                    code="inspect_only",
                    severity="medium",
                    summary="Only inspection is safe from the current workspace.",
                    evidence=candidate.workspace_reason,
                )
            )
            false_positive_score += 1
            runtime_score += 1
            confidence -= 10

        false_positive_risk = _risk_label(false_positive_score)
        runtime_risk = _risk_label(runtime_score)
        outcome = _assessment_outcome(false_positive_score, runtime_score, dispatch_status)
        confidence = max(0, min(100, confidence))

        return AssessmentReport(
            repository=item.repository,
            number=item.number,
            title=item.title,
            url=item.url,
            branch=item.branch,
            category=item.category,
            dispatch_status=dispatch_status,
            outcome=outcome,
            false_positive_risk=false_positive_risk,
            runtime_risk=runtime_risk,
            confidence=confidence,
            recommended_action=_recommended_action(item, dispatch_status, false_positive_risk, runtime_risk),
            findings=tuple(findings),
        )

    def _check_zero_day_indicators(self, item: ScanResult) -> list[AssessmentFinding]:
        """Detect potential zero-day vulnerabilities based on check patterns and signals."""
        indicators: list[AssessmentFinding] = []

        # Security-focused checks that might indicate zero-day issues
        security_checks = {"semgrep", "socket", "codeql", "snyk", "dependabot", "security", "vulnerability"}
        fuzzing_checks = {"oss-fuzz", "cifuzz", "fuzzing", "fuzz-pr", "libfuzzer", "afl"}

        # Check for new security check failures
        failing_security = [c for c in item.failing_checks if any(sec in c.lower() for sec in security_checks)]
        if failing_security:
            indicators.append(
                AssessmentFinding(
                    code="security_check_failure",
                    severity="critical",
                    summary="Security-focused checks are failing, potential vulnerability detected.",
                    evidence=", ".join(failing_security),
                )
            )

        # Check for fuzzing failures which often reveal zero-days
        failing_fuzzing = [c for c in item.failing_checks if any(fuzz in c.lower() for fuzz in fuzzing_checks)]
        if failing_fuzzing:
            indicators.append(
                AssessmentFinding(
                    code="fuzzing_failure",
                    severity="critical",
                    summary="Fuzzing checks failing, possible memory corruption or crash detected.",
                    evidence=", ".join(failing_fuzzing),
                )
            )

        # Check for unexpected combination of failing checks
        if len(item.failing_checks) >= 3 and any(any(sec in c.lower() for sec in security_checks) for c in item.failing_checks):
            indicators.append(
                AssessmentFinding(
                    code="multi_security_failure",
                    severity="high",
                    summary="Multiple checks failing including security checks may indicate complex vulnerability.",
                    evidence=f"{len(item.failing_checks)} checks failing",
                )
            )

        return indicators


def _risk_label(score: int) -> str:
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _assessment_outcome(false_positive_score: int, runtime_score: int, dispatch_status: str) -> str:
    if dispatch_status == "deferred" or false_positive_score >= 3:
        return "hold"
    if runtime_score >= 3 or dispatch_status in {"blocked", "inspect_only"}:
        return "verify"
    return "actionable"


def _recommended_action(
    item: ScanResult,
    dispatch_status: str,
    false_positive_risk: str,
    runtime_risk: str,
) -> str:
    if item.category == "superseded_candidate":
        return "Verify the newer sibling PR before closing or ignoring this branch."
    if item.pending_checks:
        return "Wait for pending checks or rerun them before patching."
    if item.workspace_notes:
        return "Switch to the PR branch in a clean local checkout, then reassess."
    if false_positive_risk == "high":
        return "Inspect CI logs and confirm the failure is reproducible before proposing edits."
    if runtime_risk == "high" or dispatch_status in {"blocked", "inspect_only"}:
        return "Stabilize the workspace or narrow the target files before running proposals."
    return "Safe to continue into run/propose with the current guardrails."


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _outcome_rank(outcome: str) -> int:
    order = {"actionable": 0, "verify": 1, "hold": 2}
    return order.get(outcome, 9)


def gate_dispatch_candidates(
    candidates: tuple[DispatchCandidate, ...],
    reports: tuple[AssessmentReport, ...],
) -> tuple[DispatchCandidate, ...]:
    report_map = {(report.repository, report.number): report for report in reports}
    gated: list[DispatchCandidate] = []

    for candidate in candidates:
        report = report_map.get((candidate.repository, candidate.number))
        outcome = report.outcome if report is not None else "unknown"
        status = candidate.status
        priority = candidate.priority + _priority_adjustment(outcome)
        actions = candidate.actions

        if outcome == "hold" and candidate.status in {"ready", "inspect_only"}:
            status = "deferred"
            actions = tuple(_gate_action(action) for action in candidate.actions)

        gated.append(
            DispatchCandidate(
                repository=candidate.repository,
                number=candidate.number,
                title=candidate.title,
                url=candidate.url,
                branch=candidate.branch,
                category=candidate.category,
                status=status,
                priority=priority,
                workspace_ready=candidate.workspace_ready,
                workspace_reason=candidate.workspace_reason,
                changed_files=candidate.changed_files,
                actions=actions,
                assessment_outcome=outcome,
                assessment_false_positive_risk=report.false_positive_risk if report is not None else "unknown",
                assessment_runtime_risk=report.runtime_risk if report is not None else "unknown",
                assessment_confidence=report.confidence if report is not None else 0,
                assessment_recommended_action=report.recommended_action if report is not None else "",
            )
        )

    gated.sort(key=lambda item: (item.priority, _candidate_status_rank(item.status), item.repository.lower(), item.number))
    return tuple(gated)


def _priority_adjustment(outcome: str) -> int:
    if outcome == "verify":
        return 1
    if outcome == "hold":
        return 10
    return 0


def _candidate_status_rank(status: str) -> int:
    order = {
        "ready": 0,
        "inspect_only": 1,
        "deferred": 2,
        "blocked": 3,
    }
    return order.get(status, 9)


def _gate_action(action: DispatchAction) -> DispatchAction:
    if action.kind in {"inspect_signal", "review_pr_scope"}:
        return action
    return DispatchAction(
        kind=action.kind,
        summary=action.summary,
        allowed=False,
        reason="blocked by assessment outcome 'hold'",
        command_hint=action.command_hint,
    )
