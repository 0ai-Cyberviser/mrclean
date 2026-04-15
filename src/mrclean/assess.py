from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .dispatch import DispatchCandidate
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
