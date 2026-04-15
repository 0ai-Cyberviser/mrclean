from __future__ import annotations

from dataclasses import dataclass

from .assess import AssessmentReport, CandidateAssessor
from .dispatch import DispatchPlanner
from .monitor import RepositoryScanner, ScanResult


@dataclass(slots=True)
class WatchEvent:
    iteration: int
    kind: str
    repository: str
    number: int
    current: ScanResult | None = None
    previous: ScanResult | None = None
    current_assessment: AssessmentReport | None = None
    previous_assessment: AssessmentReport | None = None


class RepositoryWatcher:
    def __init__(
        self,
        scanner: RepositoryScanner,
        *,
        planner: DispatchPlanner | None = None,
        assessor: CandidateAssessor | None = None,
    ) -> None:
        self.scanner = scanner
        self.planner = planner
        self.assessor = assessor
        self._iteration = 0
        self._previous: dict[tuple[str, int], ScanResult] = {}
        self._previous_assessments: dict[tuple[str, int], AssessmentReport] = {}

    @property
    def iteration(self) -> int:
        return self._iteration

    def poll(
        self,
        repositories: tuple[str, ...] | None = None,
        include_healthy: bool = False,
    ) -> tuple[WatchEvent, ...]:
        self._iteration += 1
        current_results = self.scanner.scan(repositories=repositories, include_healthy=include_healthy)
        current = {(item.repository, item.number): item for item in current_results}
        current_assessments = self._build_assessments(current_results)

        events: list[WatchEvent] = []
        for key in sorted(current, key=lambda item: (item[0], item[1])):
            item = current[key]
            previous = self._previous.get(key)
            current_assessment = current_assessments.get(key)
            previous_assessment = self._previous_assessments.get(key)
            if previous is None:
                events.append(
                    WatchEvent(
                        iteration=self._iteration,
                        kind="appeared",
                        repository=item.repository,
                        number=item.number,
                        current=item,
                        current_assessment=current_assessment,
                    )
                )
                continue

            if _scan_signature(previous, previous_assessment) != _scan_signature(item, current_assessment):
                events.append(
                    WatchEvent(
                        iteration=self._iteration,
                        kind="updated",
                        repository=item.repository,
                        number=item.number,
                        current=item,
                        previous=previous,
                        current_assessment=current_assessment,
                        previous_assessment=previous_assessment,
                    )
                )

        for key in sorted(self._previous, key=lambda item: (item[0], item[1])):
            if key in current:
                continue
            previous = self._previous[key]
            events.append(
                WatchEvent(
                    iteration=self._iteration,
                    kind="resolved",
                    repository=previous.repository,
                    number=previous.number,
                    previous=previous,
                    previous_assessment=self._previous_assessments.get(key),
                )
            )

        self._previous = current
        self._previous_assessments = current_assessments
        return tuple(events)

    def _build_assessments(
        self,
        results: tuple[ScanResult, ...],
    ) -> dict[tuple[str, int], AssessmentReport]:
        if self.planner is None or self.assessor is None:
            return {}
        candidates = self.planner.build(results)
        reports = self.assessor.assess(results, candidates)
        return {(report.repository, report.number): report for report in reports}


def _scan_signature(item: ScanResult, assessment: AssessmentReport | None) -> tuple[object, ...]:
    return (
        item.title,
        item.url,
        item.branch,
        item.merge_state_status,
        item.category,
        item.failing_checks,
        item.pending_checks,
        item.changed_files,
        item.workspace_path,
        item.workspace_branch,
        item.workspace_notes,
        item.superseded_by,
        _plan_signature(item.plan),
        _assessment_signature(assessment),
    )


def _plan_signature(plan) -> tuple[object, ...] | None:
    if plan is None:
        return None
    return (
        plan.goal,
        tuple((action.kind, action.summary, action.branch, action.file_count, action.risky) for action in plan.actions),
        plan.policy_notes,
    )


def _assessment_signature(report: AssessmentReport | None) -> tuple[object, ...] | None:
    if report is None:
        return None
    return (
        report.dispatch_status,
        report.outcome,
        report.false_positive_risk,
        report.runtime_risk,
        report.confidence,
        report.recommended_action,
        tuple(
            (finding.code, finding.severity, finding.summary, finding.evidence)
            for finding in report.findings
        ),
    )
