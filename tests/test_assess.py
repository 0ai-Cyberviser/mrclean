from __future__ import annotations

from datetime import datetime, timezone
import unittest

from mrclean.assess import CandidateAssessor, gate_dispatch_candidates
from mrclean.dispatch import DispatchAction, DispatchCandidate
from mrclean.monitor import ScanResult


def _scan_result(
    *,
    category: str = "needs_attention",
    pending_checks: tuple[str, ...] = (),
    workspace_notes: tuple[str, ...] = (),
    changed_files: tuple[str, ...] = ("a.py",),
    updated_at: str = "2026-04-15T18:00:00Z",
) -> ScanResult:
    return ScanResult(
        repository="example/repo",
        number=32,
        title="Fix CI",
        url="https://github.com/example/repo/pull/32",
        branch="fix-ci",
        updated_at=updated_at,
        merge_state_status="UNSTABLE",
        category=category,
        failing_checks=("build-linux",) if category != "healthy" else (),
        pending_checks=pending_checks,
        changed_files=changed_files,
        workspace_path="/repo",
        workspace_branch="fix-ci" if not workspace_notes else "other-branch",
        workspace_notes=workspace_notes,
        superseded_by=33 if category == "superseded_candidate" else None,
        plan=None,
    )


def _candidate(*, status: str = "ready", workspace_ready: bool = True, workspace_reason: str = "workspace matches PR branch") -> DispatchCandidate:
    return DispatchCandidate(
        repository="example/repo",
        number=32,
        title="Fix CI",
        url="https://github.com/example/repo/pull/32",
        branch="fix-ci",
        category="needs_attention",
        status=status,
        priority=0,
        workspace_ready=workspace_ready,
        workspace_reason=workspace_reason,
        changed_files=("a.py",),
        actions=(DispatchAction("edit_patch", "edit", True, "allowed"),),
    )


class CandidateAssessorTests(unittest.TestCase):
    def test_assess_marks_ready_failure_as_actionable(self) -> None:
        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (_scan_result(),),
            (_candidate(),),
        )[0]

        self.assertEqual(report.outcome, "actionable")
        self.assertEqual(report.false_positive_risk, "low")
        self.assertEqual(report.runtime_risk, "low")
        self.assertGreaterEqual(report.confidence, 90)

    def test_assess_marks_pending_checks_as_hold(self) -> None:
        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (_scan_result(category="pending", pending_checks=("build-linux",)),),
            (_candidate(status="deferred"),),
        )[0]

        self.assertEqual(report.outcome, "hold")
        self.assertEqual(report.false_positive_risk, "high")
        self.assertIn("Wait for pending checks", report.recommended_action)

    def test_assess_marks_workspace_mismatch_as_hold(self) -> None:
        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (
                _scan_result(
                    workspace_notes=("local checkout is on 'main', expected 'fix-ci'",),
                    changed_files=(),
                ),
            ),
            (_candidate(status="inspect_only", workspace_ready=False, workspace_reason="branch mismatch"),),
        )[0]

        self.assertEqual(report.outcome, "hold")
        self.assertEqual(report.runtime_risk, "high")
        self.assertEqual(report.false_positive_risk, "high")
        self.assertIn("Switch to the PR branch", report.recommended_action)

    def test_assess_marks_superseded_branch_as_hold(self) -> None:
        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (_scan_result(category="superseded_candidate"),),
            (_candidate(),),
        )[0]

        self.assertEqual(report.outcome, "hold")
        self.assertIn("newer sibling PR", report.findings[0].summary)

    def test_gate_dispatch_candidates_deprioritizes_and_defers_hold(self) -> None:
        candidate = _candidate(status="ready")
        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (_scan_result(category="superseded_candidate"),),
            (candidate,),
        )[0]

        gated = gate_dispatch_candidates((candidate,), (report,))[0]

        self.assertEqual(gated.status, "deferred")
        self.assertEqual(gated.assessment_outcome, "hold")
        self.assertGreater(gated.priority, candidate.priority)
        self.assertFalse(gated.actions[0].allowed)

    def test_assess_detects_security_check_failures_as_zero_day_indicators(self) -> None:
        result = ScanResult(
            repository="example/repo",
            number=42,
            title="Security fix",
            url="https://github.com/example/repo/pull/42",
            branch="security-patch",
            updated_at="2026-04-15T18:00:00Z",
            merge_state_status="CLEAN",
            category="needs_attention",
            failing_checks=("semgrep", "codeql", "build"),
            pending_checks=(),
            changed_files=("auth.py",),
            workspace_path="/repo",
            workspace_branch="security-patch",
            workspace_notes=(),
        )

        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (result,),
            (_candidate(),),
        )[0]

        # Should detect security check failures
        security_findings = [f for f in report.findings if f.code in ("security_check_failure", "multi_security_failure")]
        self.assertGreater(len(security_findings), 0)
        self.assertIn("critical", [f.severity for f in security_findings])

    def test_assess_detects_fuzzing_failures_as_zero_day_indicators(self) -> None:
        result = ScanResult(
            repository="example/repo",
            number=43,
            title="Fuzzing crash fix",
            url="https://github.com/example/repo/pull/43",
            branch="fix-crash",
            updated_at="2026-04-15T18:00:00Z",
            merge_state_status="CLEAN",
            category="needs_attention",
            failing_checks=("oss-fuzz", "cifuzz"),
            pending_checks=(),
            changed_files=("parser.c",),
            workspace_path="/repo",
            workspace_branch="fix-crash",
            workspace_notes=(),
        )

        report = CandidateAssessor(now=datetime(2026, 4, 15, 18, 30, tzinfo=timezone.utc)).assess(
            (result,),
            (_candidate(),),
        )[0]

        # Should detect fuzzing failures
        fuzzing_findings = [f for f in report.findings if f.code == "fuzzing_failure"]
        self.assertEqual(len(fuzzing_findings), 1)
        self.assertEqual(fuzzing_findings[0].severity, "critical")
        self.assertIn("memory corruption", fuzzing_findings[0].summary.lower())


if __name__ == "__main__":
    unittest.main()
