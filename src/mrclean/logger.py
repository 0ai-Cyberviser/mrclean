from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assess import AssessmentReport
from .dispatch import DispatchCandidate
from .monitor import ScanResult


@dataclass(slots=True)
class WorkflowLogEntry:
    timestamp: str
    iteration: int
    phase: str
    repository: str
    pr_number: int
    category: str
    outcome: str
    details: dict[str, Any]


class WorkflowLogger:
    """Structured logger for monitor-audit-review-test-log-learn-repeat workflow."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = log_dir or Path.home() / ".mrclean" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_session = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.session_log = self.log_dir / f"workflow_{self.current_session}.jsonl"
        self.entries: list[WorkflowLogEntry] = []

    def log_monitor(
        self,
        iteration: int,
        result: ScanResult,
    ) -> None:
        """Log a monitoring phase result."""
        entry = WorkflowLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            phase="monitor",
            repository=result.repository,
            pr_number=result.number,
            category=result.category,
            outcome="detected" if result.category == "needs_attention" else "healthy",
            details={
                "title": result.title,
                "branch": result.branch,
                "failing_checks": list(result.failing_checks),
                "pending_checks": list(result.pending_checks),
                "changed_files_count": len(result.changed_files),
                "workspace_ready": bool(result.workspace_path and not result.workspace_notes),
            },
        )
        self._write_entry(entry)

    def log_audit(
        self,
        iteration: int,
        report: AssessmentReport,
    ) -> None:
        """Log an audit/assessment phase result."""
        entry = WorkflowLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            phase="audit",
            repository=report.repository,
            pr_number=report.number,
            category=report.category,
            outcome=report.outcome,
            details={
                "false_positive_risk": report.false_positive_risk,
                "runtime_risk": report.runtime_risk,
                "confidence": report.confidence,
                "recommended_action": report.recommended_action,
                "findings_count": len(report.findings),
                "findings": [
                    {
                        "code": f.code,
                        "severity": f.severity,
                        "summary": f.summary,
                    }
                    for f in report.findings
                ],
            },
        )
        self._write_entry(entry)

    def log_dispatch(
        self,
        iteration: int,
        candidate: DispatchCandidate,
    ) -> None:
        """Log a dispatch phase result."""
        entry = WorkflowLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            phase="dispatch",
            repository=candidate.repository,
            pr_number=candidate.number,
            category=candidate.category,
            outcome=candidate.status,
            details={
                "priority": candidate.priority,
                "workspace_ready": candidate.workspace_ready,
                "actions_count": len(candidate.actions),
                "allowed_actions": sum(1 for a in candidate.actions if a.allowed),
                "assessment_outcome": candidate.assessment_outcome,
                "assessment_confidence": candidate.assessment_confidence,
            },
        )
        self._write_entry(entry)

    def log_review(
        self,
        iteration: int,
        repository: str,
        pr_number: int,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        """Log a review phase (propose/intent/materialize/draft/preview)."""
        entry = WorkflowLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            phase="review",
            repository=repository,
            pr_number=pr_number,
            category="review",
            outcome=outcome,
            details=details,
        )
        self._write_entry(entry)

    def log_test(
        self,
        iteration: int,
        repository: str,
        pr_number: int,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        """Log a test/run phase result."""
        entry = WorkflowLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            phase="test",
            repository=repository,
            pr_number=pr_number,
            category="test",
            outcome=outcome,
            details=details,
        )
        self._write_entry(entry)

    def log_apply(
        self,
        iteration: int,
        repository: str,
        pr_number: int,
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        """Log an apply phase result."""
        entry = WorkflowLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            phase="apply",
            repository=repository,
            pr_number=pr_number,
            category="apply",
            outcome=outcome,
            details=details,
        )
        self._write_entry(entry)

    def _write_entry(self, entry: WorkflowLogEntry) -> None:
        """Write a log entry to the session log file."""
        self.entries.append(entry)
        with self.session_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def get_session_path(self) -> Path:
        """Get the path to the current session log file."""
        return self.session_log

    def get_metrics(self) -> dict[str, Any]:
        """Get aggregated metrics from the current session."""
        if not self.entries:
            return {}

        phases_count = {}
        outcomes_count = {}
        repositories = set()

        for entry in self.entries:
            phases_count[entry.phase] = phases_count.get(entry.phase, 0) + 1
            outcomes_count[entry.outcome] = outcomes_count.get(entry.outcome, 0) + 1
            repositories.add(entry.repository)

        return {
            "session": self.current_session,
            "total_entries": len(self.entries),
            "phases": phases_count,
            "outcomes": outcomes_count,
            "repositories": sorted(repositories),
            "log_file": str(self.session_log),
        }


def load_session_logs(log_dir: Path | None = None) -> list[WorkflowLogEntry]:
    """Load all workflow log entries from stored session logs."""
    log_dir = log_dir or Path.home() / ".mrclean" / "logs"
    if not log_dir.exists():
        return []

    entries = []
    for log_file in sorted(log_dir.glob("workflow_*.jsonl")):
        try:
            with log_file.open() as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        entries.append(WorkflowLogEntry(**data))
        except (json.JSONDecodeError, TypeError):
            continue

    return entries
