from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logger import WorkflowLogEntry, load_session_logs


@dataclass(slots=True)
class LearningInsight:
    category: str
    pattern: str
    confidence: float
    occurrences: int
    success_rate: float
    evidence: list[str]


@dataclass(slots=True)
class RepositoryPattern:
    repository: str
    check_patterns: dict[str, int]
    outcome_patterns: dict[str, int]
    success_rate: float
    total_attempts: int


class PatternLearner:
    """Learn from historical workflow execution to improve future decisions."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = log_dir or Path.home() / ".mrclean" / "logs"
        self.entries: list[WorkflowLogEntry] = []
        self.loaded = False

    def load_history(self) -> None:
        """Load all historical workflow logs."""
        if not self.loaded:
            self.entries = load_session_logs(self.log_dir)
            self.loaded = True

    def analyze_repository_patterns(self, repository: str) -> RepositoryPattern:
        """Analyze patterns for a specific repository."""
        self.load_history()

        repo_entries = [e for e in self.entries if e.repository == repository]
        if not repo_entries:
            return RepositoryPattern(
                repository=repository,
                check_patterns={},
                outcome_patterns={},
                success_rate=0.0,
                total_attempts=0,
            )

        check_patterns: dict[str, int] = defaultdict(int)
        outcome_patterns: dict[str, int] = defaultdict(int)
        successful = 0
        total = 0

        for entry in repo_entries:
            outcome_patterns[entry.outcome] += 1

            if entry.phase == "monitor" and "failing_checks" in entry.details:
                for check in entry.details["failing_checks"]:
                    check_patterns[check] += 1

            if entry.phase == "apply":
                total += 1
                if entry.outcome in {"success", "completed", "applied"}:
                    successful += 1

        success_rate = successful / total if total > 0 else 0.0

        return RepositoryPattern(
            repository=repository,
            check_patterns=dict(check_patterns),
            outcome_patterns=dict(outcome_patterns),
            success_rate=success_rate,
            total_attempts=total,
        )

    def get_false_positive_indicators(self) -> list[LearningInsight]:
        """Identify patterns that commonly result in false positives."""
        self.load_history()

        # Track outcomes after audit phase
        audit_outcomes: dict[str, list[str]] = defaultdict(list)

        for entry in self.entries:
            if entry.phase == "audit":
                key = f"{entry.repository}:{entry.pr_number}"
                audit_outcomes[key].append(entry.outcome)

        # Find patterns where "hold" or "verify" outcomes were common
        insights = []
        hold_count = sum(1 for outcomes in audit_outcomes.values() if "hold" in outcomes)
        verify_count = sum(1 for outcomes in audit_outcomes.values() if "verify" in outcomes)
        total = len(audit_outcomes)

        if total > 0:
            if hold_count / total > 0.3:
                insights.append(
                    LearningInsight(
                        category="false_positive",
                        pattern="high_hold_rate",
                        confidence=min(0.9, hold_count / total),
                        occurrences=hold_count,
                        success_rate=1.0 - (hold_count / total),
                        evidence=[f"{hold_count}/{total} assessments resulted in hold"],
                    )
                )

            if verify_count / total > 0.4:
                insights.append(
                    LearningInsight(
                        category="false_positive",
                        pattern="high_verify_rate",
                        confidence=min(0.9, verify_count / total),
                        occurrences=verify_count,
                        success_rate=1.0 - (verify_count / total),
                        evidence=[f"{verify_count}/{total} assessments required verification"],
                    )
                )

        return insights

    def get_check_reliability_scores(self) -> dict[str, float]:
        """Calculate reliability scores for different check types based on outcomes."""
        self.load_history()

        check_outcomes: dict[str, list[bool]] = defaultdict(list)

        for entry in self.entries:
            if entry.phase == "monitor" and "failing_checks" in entry.details:
                checks = entry.details["failing_checks"]
                # Look for corresponding successful resolutions
                resolved = any(
                    e.phase == "apply"
                    and e.repository == entry.repository
                    and e.pr_number == entry.pr_number
                    and e.outcome in {"success", "completed", "applied"}
                    for e in self.entries
                )

                for check in checks:
                    check_outcomes[check].append(resolved)

        # Calculate reliability as ratio of successfully resolved issues
        reliability: dict[str, float] = {}
        for check, outcomes in check_outcomes.items():
            if outcomes:
                reliability[check] = sum(outcomes) / len(outcomes)

        return reliability

    def get_common_failure_patterns(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get the most common failing check combinations."""
        self.load_history()

        patterns: dict[str, int] = defaultdict(int)

        for entry in self.entries:
            if entry.phase == "monitor" and "failing_checks" in entry.details:
                checks = tuple(sorted(entry.details["failing_checks"]))
                if checks:
                    patterns[",".join(checks)] += 1

        return sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_security_vulnerability_insights(self) -> list[LearningInsight]:
        """Analyze security-related patterns from historical data."""
        self.load_history()

        security_keywords = {
            "semgrep",
            "codeql",
            "snyk",
            "dependabot",
            "security",
            "vulnerability",
        }
        fuzzing_keywords = {"oss-fuzz", "cifuzz", "fuzzing", "fuzz-pr", "libfuzzer"}

        security_detections = 0
        fuzzing_detections = 0
        critical_findings = 0

        for entry in self.entries:
            if entry.phase == "audit" and "findings" in entry.details:
                for finding in entry.details["findings"]:
                    if finding.get("severity") == "critical":
                        critical_findings += 1
                    if any(
                        keyword in finding.get("code", "").lower()
                        for keyword in security_keywords
                    ):
                        security_detections += 1
                    if any(
                        keyword in finding.get("code", "").lower()
                        for keyword in fuzzing_keywords
                    ):
                        fuzzing_detections += 1

        insights = []

        if security_detections > 0:
            insights.append(
                LearningInsight(
                    category="security",
                    pattern="security_check_failures",
                    confidence=0.8,
                    occurrences=security_detections,
                    success_rate=0.0,  # Would need resolution tracking
                    evidence=[f"{security_detections} security-related findings detected"],
                )
            )

        if fuzzing_detections > 0:
            insights.append(
                LearningInsight(
                    category="security",
                    pattern="fuzzing_failures",
                    confidence=0.85,
                    occurrences=fuzzing_detections,
                    success_rate=0.0,
                    evidence=[f"{fuzzing_detections} fuzzing-related failures detected"],
                )
            )

        if critical_findings > 0:
            insights.append(
                LearningInsight(
                    category="security",
                    pattern="critical_severity",
                    confidence=0.9,
                    occurrences=critical_findings,
                    success_rate=0.0,
                    evidence=[f"{critical_findings} critical severity findings"],
                )
            )

        return insights

    def get_summary_stats(self) -> dict[str, Any]:
        """Get summary statistics from all historical logs."""
        self.load_history()

        if not self.entries:
            return {
                "total_entries": 0,
                "repositories": [],
                "phases": {},
                "outcomes": {},
            }

        phases: dict[str, int] = defaultdict(int)
        outcomes: dict[str, int] = defaultdict(int)
        repositories = set()

        for entry in self.entries:
            phases[entry.phase] += 1
            outcomes[entry.outcome] += 1
            repositories.add(entry.repository)

        return {
            "total_entries": len(self.entries),
            "repositories": sorted(repositories),
            "phases": dict(phases),
            "outcomes": dict(outcomes),
            "date_range": (
                min(e.timestamp for e in self.entries),
                max(e.timestamp for e in self.entries),
            )
            if self.entries
            else None,
        }
