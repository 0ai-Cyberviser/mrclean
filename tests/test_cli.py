from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mrclean.cli import main
from mrclean.monitor import ScanResult
from mrclean.previews import PreviewBundle, PreviewOperation, dump_preview_bundles
from mrclean.watch import WatchEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _example_config(local_path: str = "/repo", *, require_signature: bool = True) -> str:
    return f"""name = "mrclean"

[model]
provider = "openai"
name = "gpt-5.4-mini"

[policy]
dry_run = false
allow_local_apply = true
allow_push = false
allow_close_stale_prs = false
allow_force_push = false
require_signed_preview_artifacts = {"true" if require_signature else "false"}
artifact_signing_key_env = "MRCLEAN_ARTIFACT_SIGNING_KEY"
max_patch_files = 5
protected_branches = ["main", "master"]

[[repositories]]
name = "example/repo"
base_branch = "main"
local_path = "{local_path}"
"""


class CliTests(unittest.TestCase):
    def test_init_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            result = main(["init", str(config_path)])
            self.assertEqual(result, 0)

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = main(["validate", str(config_path)])
            self.assertEqual(result, 0)
            self.assertIn("config valid", buffer.getvalue())

    def test_module_entrypoint_executes_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "mrclean.cli", "validate", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            )
            self.assertEqual(completed.returncode, 0)
            self.assertIn("config valid", completed.stdout)

    def test_watch_command_renders_event_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            item = ScanResult(
                repository="example/repo",
                number=32,
                title="Fix CI",
                url="https://github.com/example/repo/pull/32",
                branch="fix-ci",
                updated_at="2026-04-15T18:00:00Z",
                merge_state_status="UNSTABLE",
                category="needs_attention",
                failing_checks=("build-linux",),
                pending_checks=(),
            )
            event = WatchEvent(
                iteration=1,
                kind="appeared",
                repository="example/repo",
                number=32,
                current=item,
            )

            class FakeWatcher:
                iteration = 0

                def __init__(self, scanner, planner=None, assessor=None) -> None:
                    self.iteration = 0

                def poll(self, repositories=None, include_healthy=False):
                    self.iteration = 1
                    return (event,)

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryWatcher", FakeWatcher):
                with redirect_stdout(buffer):
                    result = main(["watch", str(config_path), "--iterations", "1", "--interval", "0"])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("Iteration 1: appeared example/repo#32", output)
            self.assertIn("Failing checks: build-linux", output)

    def test_dispatch_command_renders_candidate_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return (
                        ScanResult(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            updated_at="2026-04-15T18:00:00Z",
                            merge_state_status="UNSTABLE",
                            category="needs_attention",
                            failing_checks=("build-linux",),
                            pending_checks=(),
                            changed_files=("a.py",),
                            workspace_path="/repo",
                            workspace_branch="fix-ci",
                            workspace_notes=(),
                            plan=None,
                        ),
                    )

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate, DispatchAction

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("a.py",),
                            actions=(
                                DispatchAction(
                                    kind="edit_patch",
                                    summary="edit",
                                    allowed=True,
                                    reason="allowed",
                                    command_hint="git -C /repo diff --stat",
                                ),
                            ),
                        ),
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with redirect_stdout(buffer):
                        result = main(["dispatch", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [ready]", output)
            self.assertIn("Workspace ready: yes", output)
            self.assertIn("edit_patch [allowed]", output)

    def test_assess_command_renders_assessment_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return (
                        ScanResult(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            updated_at="2026-04-15T18:00:00Z",
                            merge_state_status="UNSTABLE",
                            category="needs_attention",
                            failing_checks=("build-linux",),
                            pending_checks=(),
                            changed_files=(),
                            workspace_path="/repo",
                            workspace_branch="other-branch",
                            workspace_notes=("local checkout is on 'other-branch', expected 'fix-ci'",),
                            plan=None,
                        ),
                    )

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="inspect_only",
                            priority=0,
                            workspace_ready=False,
                            workspace_reason="branch mismatch",
                            changed_files=(),
                            actions=(),
                        ),
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with redirect_stdout(buffer):
                        result = main(["assess", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [assessment:hold]", output)
            self.assertIn("False-positive risk: high", output)
            self.assertIn("Runtime risk: high", output)

    def test_run_command_renders_execution_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return ()

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    return ()

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    from mrclean.runner import RunSession, ActionExecution

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(
                                ActionExecution(
                                    kind="inspect_signal",
                                    summary="inspect",
                                    command="gh pr view 32",
                                    status="executed",
                                    reason="command completed successfully",
                                    returncode=0,
                                    stdout="ok\n",
                                    stderr="",
                                ),
                            ),
                        ),
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=FakeRunner()):
                        with redirect_stdout(buffer):
                            result = main(["run", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [prepared]", output)
            self.assertIn("inspect_signal [executed]", output)
            self.assertIn("gh pr view 32", output)

    def test_run_command_blocks_verify_candidate_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return (
                        ScanResult(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            updated_at="2026-04-15T18:00:00Z",
                            merge_state_status="DIRTY",
                            category="needs_attention",
                            failing_checks=("build-linux", "fuzz-pr"),
                            pending_checks=(),
                            changed_files=("a.py",),
                            workspace_path="/repo",
                            workspace_branch="fix-ci",
                            workspace_notes=(),
                            plan=None,
                        ),
                    )

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate, DispatchAction

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("a.py",),
                            actions=(DispatchAction("edit_patch", "edit", True, "allowed", "git diff"),),
                        ),
                    )

            stderr = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with redirect_stdout(StringIO()), patch("sys.stderr", stderr):
                        result = main(["run", str(config_path), "--pr", "32"])

            self.assertEqual(result, 1)
            self.assertIn("requires verification before execution", stderr.getvalue())

    def test_propose_command_renders_proposal_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return ()

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("a.py",),
                            actions=(),
                        ),
                    )

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    from mrclean.runner import RunSession

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(),
                        ),
                    )

            class FakeProposalGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, candidate, session):
                    from mrclean.proposals import Proposal

                    return Proposal(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        candidate_status="ready",
                        run_status="prepared",
                        content="Summary\n- narrow fix",
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=FakeRunner()):
                        with patch("mrclean.cli.ProposalGenerator", FakeProposalGenerator):
                            with redirect_stdout(buffer):
                                result = main(["propose", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [proposal]", output)
            self.assertIn("Model: fake/fake-model", output)
            self.assertIn("Summary", output)

    def test_propose_command_allows_verify_with_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return (
                        ScanResult(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            updated_at="2026-04-15T18:00:00Z",
                            merge_state_status="DIRTY",
                            category="needs_attention",
                            failing_checks=("build-linux", "fuzz-pr"),
                            pending_checks=(),
                            changed_files=("a.py",),
                            workspace_path="/repo",
                            workspace_branch="fix-ci",
                            workspace_notes=(),
                            plan=None,
                        ),
                    )

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate, DispatchAction

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("a.py",),
                            actions=(DispatchAction("edit_patch", "edit", True, "allowed", "git diff"),),
                        ),
                    )

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    self.allow_verify = allow_verify
                    from mrclean.runner import RunSession

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(),
                        ),
                    )

            class FakeProposalGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, candidate, session):
                    from mrclean.proposals import Proposal

                    return Proposal(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        candidate_status=candidate.status,
                        run_status=session.run_status,
                        content="Summary\n- narrow fix",
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            fake_runner = FakeRunner()
            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=fake_runner):
                        with patch("mrclean.cli.ProposalGenerator", FakeProposalGenerator):
                            with redirect_stdout(buffer):
                                result = main(["propose", str(config_path), "--allow-verify"])

            self.assertEqual(result, 0)
            self.assertTrue(fake_runner.allow_verify)
            self.assertIn("example/repo#32 [proposal]", buffer.getvalue())

    def test_intent_command_renders_intent_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return ()

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("a.py",),
                            actions=(),
                        ),
                    )

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    from mrclean.runner import RunSession

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(),
                        ),
                    )

            class FakeIntentGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, candidate, session):
                    from mrclean.intents import EditIntent, IntentEdit

                    return EditIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        candidate_status="ready",
                        run_status="prepared",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            IntentEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=FakeRunner()):
                        with patch("mrclean.cli.IntentGenerator", FakeIntentGenerator):
                            with redirect_stdout(buffer):
                                result = main(["intent", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [intent]", output)
            self.assertIn("modify requirements-dev.txt", output)
            self.assertIn("pytest -q", output)

    def test_materialize_command_renders_materialized_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return ()

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("requirements-dev.txt",),
                            actions=(),
                        ),
                    )

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    from mrclean.runner import RunSession

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(),
                        ),
                    )

            class FakeIntentGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, candidate, session):
                    from mrclean.intents import EditIntent, IntentEdit

                    return EditIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        candidate_status="ready",
                        run_status="prepared",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            IntentEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            class FakeMaterializer:
                def __init__(self, config) -> None:
                    self.config = config

                def materialize(self, candidate, intent):
                    from mrclean.materialize import MaterializedIntent, MaterializedEdit

                    return MaterializedIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        workspace_path="/repo",
                        workspace_branch="fix-ci",
                        workspace_ready=True,
                        workspace_reason="workspace matches intent branch",
                        status="ready",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            MaterializedEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                                absolute_path="/repo/requirements-dev.txt",
                                status="ready",
                                validation_reason="ready",
                                exists=True,
                                in_branch_scope=True,
                                size_bytes=10,
                                sha256="abc123",
                                preview="pytest\n",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=FakeRunner()):
                        with patch("mrclean.cli.IntentGenerator", FakeIntentGenerator):
                            with patch("mrclean.cli.IntentMaterializer", FakeMaterializer):
                                with redirect_stdout(buffer):
                                    result = main(["materialize", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [materialized]", output)
            self.assertIn("modify requirements-dev.txt [ready]", output)
            self.assertIn("/repo/requirements-dev.txt", output)

    def test_draft_command_renders_draft_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return ()

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("requirements-dev.txt",),
                            actions=(),
                        ),
                    )

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    from mrclean.runner import RunSession

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(),
                        ),
                    )

            class FakeIntentGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, candidate, session):
                    from mrclean.intents import EditIntent, IntentEdit

                    return EditIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        candidate_status="ready",
                        run_status="prepared",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            IntentEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            class FakeMaterializer:
                def __init__(self, config) -> None:
                    self.config = config

                def materialize(self, candidate, intent):
                    from mrclean.materialize import MaterializedIntent, MaterializedEdit

                    return MaterializedIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        workspace_path="/repo",
                        workspace_branch="fix-ci",
                        workspace_ready=True,
                        workspace_reason="workspace matches intent branch",
                        status="ready",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            MaterializedEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                                absolute_path="/repo/requirements-dev.txt",
                                status="ready",
                                validation_reason="ready",
                                exists=True,
                                in_branch_scope=True,
                                size_bytes=10,
                                sha256="abc123",
                                preview="pytest\n",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                    )

            class FakeDraftGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, materialized):
                    from mrclean.drafts import DraftBundle, DraftOperation

                    return DraftBundle(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        status="ready",
                        summary="Update the dependency file narrowly.",
                        operations=(
                            DraftOperation(
                                path="requirements-dev.txt",
                                requested_operation="modify",
                                action="write_file",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                                absolute_path="/repo/requirements-dev.txt",
                                status="ready",
                                validation_reason="ready",
                                expected_sha256="abc123",
                                content_sha256="def456",
                                content_bytes=18,
                                content_preview="pytest\npytest-cov\n",
                                content="pytest\npytest-cov\n",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=FakeRunner()):
                        with patch("mrclean.cli.IntentGenerator", FakeIntentGenerator):
                            with patch("mrclean.cli.IntentMaterializer", FakeMaterializer):
                                with patch("mrclean.cli.DraftGenerator", FakeDraftGenerator):
                                    with redirect_stdout(buffer):
                                        result = main(["draft", str(config_path)])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [draft]", output)
            self.assertIn("write_file requirements-dev.txt [ready]", output)
            self.assertIn("expected sha256: abc123", output)

    def test_preview_command_renders_preview_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")
            output_path = Path(tmpdir) / "reviewed-preview.json"

            class FakeScanner:
                def __init__(self, config) -> None:
                    self.config = config

                def scan(self, repositories=None, include_healthy=False):
                    return ()

            class FakePlanner:
                def __init__(self, policy) -> None:
                    self.policy = policy

                def build(self, results):
                    from mrclean.dispatch import DispatchCandidate

                    return (
                        DispatchCandidate(
                            repository="example/repo",
                            number=32,
                            title="Fix CI",
                            url="https://github.com/example/repo/pull/32",
                            branch="fix-ci",
                            category="needs_attention",
                            status="ready",
                            priority=0,
                            workspace_ready=True,
                            workspace_reason="workspace matches PR branch",
                            changed_files=("requirements-dev.txt",),
                            actions=(),
                        ),
                    )

            class FakeRunner:
                def run(self, candidates, pr_number=None, limit=1, allow_verify=False):
                    from mrclean.runner import RunSession

                    return (
                        RunSession(
                            repository="example/repo",
                            number=32,
                            branch="fix-ci",
                            candidate_status="ready",
                            run_status="prepared",
                            executions=(),
                        ),
                    )

            class FakeIntentGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, candidate, session):
                    from mrclean.intents import EditIntent, IntentEdit

                    return EditIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        candidate_status="ready",
                        run_status="prepared",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            IntentEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            class FakeMaterializer:
                def __init__(self, config) -> None:
                    self.config = config

                def materialize(self, candidate, intent):
                    from mrclean.materialize import MaterializedIntent, MaterializedEdit

                    return MaterializedIntent(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        workspace_path="/repo",
                        workspace_branch="fix-ci",
                        workspace_ready=True,
                        workspace_reason="workspace matches intent branch",
                        status="ready",
                        summary="Fix the active CI issue narrowly.",
                        edits=(
                            MaterializedEdit(
                                path="requirements-dev.txt",
                                operation="modify",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                                absolute_path="/repo/requirements-dev.txt",
                                status="ready",
                                validation_reason="ready",
                                exists=True,
                                in_branch_scope=True,
                                size_bytes=10,
                                sha256="abc123",
                                preview="pytest\n",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                    )

            class FakeDraftGenerator:
                def __init__(self, config) -> None:
                    self.config = config

                def generate(self, materialized):
                    from mrclean.drafts import DraftBundle, DraftOperation

                    return DraftBundle(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        status="ready",
                        summary="Update the dependency file narrowly.",
                        operations=(
                            DraftOperation(
                                path="requirements-dev.txt",
                                requested_operation="modify",
                                action="write_file",
                                summary="Add pytest-cov.",
                                reason="Coverage workflow requires it.",
                                absolute_path="/repo/requirements-dev.txt",
                                status="ready",
                                validation_reason="ready",
                                expected_sha256="abc123",
                                content_sha256="def456",
                                content_bytes=18,
                                content_preview="pytest\npytest-cov\n",
                                content="pytest\npytest-cov\n",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                        model_provider="fake",
                        model_name="fake-model",
                        raw={"provider": "fake"},
                    )

            class FakePreviewer:
                def preview(self, draft):
                    from mrclean.previews import PreviewBundle, PreviewOperation

                    return PreviewBundle(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        status="ready",
                        summary="Update the dependency file narrowly.",
                        operations=(
                            PreviewOperation(
                                path="requirements-dev.txt",
                                requested_operation="modify",
                                action="write_file",
                                absolute_path="/repo/requirements-dev.txt",
                                status="ready",
                                validation_reason="ready",
                                expected_sha256="abc123",
                                current_sha256="abc123",
                                current_exists=True,
                                diff="--- a/requirements-dev.txt\n+++ b/requirements-dev.txt\n@@ -1 +1,2 @@\n pytest\n+pytest-cov\n",
                                diff_bytes=88,
                                content_sha256="def456",
                                content="pytest\npytest-cov\n",
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                    )

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryScanner", FakeScanner):
                with patch("mrclean.cli.DispatchPlanner", FakePlanner):
                    with patch("mrclean.cli.LocalRunner", return_value=FakeRunner()):
                        with patch("mrclean.cli.IntentGenerator", FakeIntentGenerator):
                            with patch("mrclean.cli.IntentMaterializer", FakeMaterializer):
                                with patch("mrclean.cli.DraftGenerator", FakeDraftGenerator):
                                    with patch("mrclean.cli.DraftPreviewer", return_value=FakePreviewer()):
                                        with patch.dict(
                                            os.environ,
                                            {"MRCLEAN_ARTIFACT_SIGNING_KEY": "preview-secret"},
                                            clear=False,
                                        ):
                                            with redirect_stdout(buffer):
                                                result = main(
                                                    [
                                                        "preview",
                                                        str(config_path),
                                                        "--output",
                                                        str(output_path),
                                                    ]
                                                )

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [preview]", output)
            self.assertIn("write_file requirements-dev.txt [ready]", output)
            self.assertIn("+++ b/requirements-dev.txt", output)
            self.assertIn("Wrote signed preview artifact", output)
            self.assertIn("\"signature\"", output_path.read_text(encoding="utf-8"))

    def test_apply_command_requires_execute_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_example_config(), encoding="utf-8")
            preview_path = Path(tmpdir) / "preview.json"
            preview_path.write_text("[]", encoding="utf-8")

            stderr = StringIO()
            with redirect_stdout(StringIO()), patch("sys.stderr", stderr):
                result = main(["apply", str(config_path), "--preview-file", str(preview_path)])

            self.assertEqual(result, 1)
            self.assertIn("--execute", stderr.getvalue())

    def test_apply_command_requires_preview_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_example_config(), encoding="utf-8")

            stderr = StringIO()
            with redirect_stdout(StringIO()), patch("sys.stderr", stderr):
                result = main(["apply", str(config_path), "--execute"])

            self.assertEqual(result, 1)
            self.assertIn("--preview-file", stderr.getvalue())

    def test_apply_command_renders_apply_batch_from_preview_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_example_config(require_signature=False), encoding="utf-8")
            preview_path = Path(tmpdir) / "preview.json"
            preview_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "mrclean.preview.v1",
                        "bundles": [
                            {
                                "repository": "example/repo",
                                "number": 32,
                                "branch": "fix-ci",
                                "status": "ready",
                                "summary": "Update the dependency file narrowly.",
                                "operations": [
                                    {
                                        "path": "requirements-dev.txt",
                                        "requested_operation": "modify",
                                        "action": "write_file",
                                        "absolute_path": "/repo/requirements-dev.txt",
                                        "status": "ready",
                                        "validation_reason": "ready",
                                        "expected_sha256": "abc123",
                                        "current_sha256": "abc123",
                                        "current_exists": True,
                                        "diff": "--- a/requirements-dev.txt\n+++ b/requirements-dev.txt\n@@ -1 +1,2 @@\n pytest\n+pytest-cov\n",
                                        "diff_bytes": 88,
                                        "content_sha256": "def456",
                                        "content": "pytest\npytest-cov\n",
                                    }
                                ],
                                "validation": ["pytest -q"],
                                "risks": ["Dependency updates can affect CI resolution."],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            class FakeApplier:
                def __init__(self, policy, *, config=None, workspace=None) -> None:
                    self.policy = policy

                def apply(self, preview):
                    from mrclean.apply import ApplyTransaction, AppliedOperation

                    return ApplyTransaction(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        status="applied",
                        summary="Update the dependency file narrowly.",
                        operations=(
                            AppliedOperation(
                                path="requirements-dev.txt",
                                action="write_file",
                                absolute_path="/repo/requirements-dev.txt",
                                status="applied",
                                validation_reason="applied",
                                expected_sha256="abc123",
                                before_sha256="abc123",
                                after_sha256="def456",
                                changed=True,
                            ),
                        ),
                        validation=("pytest -q",),
                        risks=("Dependency updates can affect CI resolution.",),
                    )

            buffer = StringIO()
            with patch("mrclean.cli.DraftApplier", FakeApplier):
                with redirect_stdout(buffer):
                    result = main(["apply", str(config_path), "--preview-file", str(preview_path), "--execute"])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("example/repo#32 [apply]", output)
            self.assertIn("write_file requirements-dev.txt [applied]", output)
            self.assertIn("after sha256: def456", output)

    def test_apply_command_returns_nonzero_for_blocked_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_example_config(require_signature=False), encoding="utf-8")
            preview_path = Path(tmpdir) / "preview.json"
            preview_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "mrclean.preview.v1",
                        "bundles": [
                            {
                                "repository": "example/repo",
                                "number": 32,
                                "branch": "fix-ci",
                                "status": "blocked",
                                "summary": "blocked",
                                "operations": [],
                                "validation": [],
                                "risks": ["hash mismatch"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            class FakeApplier:
                def __init__(self, policy, *, config=None, workspace=None) -> None:
                    self.policy = policy

                def apply(self, preview):
                    from mrclean.apply import ApplyTransaction

                    return ApplyTransaction(
                        repository="example/repo",
                        number=32,
                        branch="fix-ci",
                        status="blocked",
                        summary="blocked",
                        operations=(),
                        validation=(),
                        risks=("hash mismatch",),
                    )

            with patch("mrclean.cli.DraftApplier", FakeApplier):
                result = main(["apply", str(config_path), "--preview-file", str(preview_path), "--execute", "--json"])

            self.assertEqual(result, 1)

    def test_apply_command_rejects_unsigned_artifact_when_signatures_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_example_config(require_signature=True), encoding="utf-8")
            preview_path = Path(tmpdir) / "preview.json"
            preview_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "mrclean.preview.v1",
                        "bundles": [],
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stdout(StringIO()), patch("sys.stderr", stderr):
                result = main(["apply", str(config_path), "--preview-file", str(preview_path), "--execute"])

            self.assertEqual(result, 1)
            self.assertIn("preview artifact is unsigned", stderr.getvalue())

    def test_apply_command_accepts_signed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_example_config(require_signature=True), encoding="utf-8")
            preview_path = Path(tmpdir) / "preview.json"

            preview = PreviewBundle(
                repository="example/repo",
                number=32,
                branch="fix-ci",
                status="ready",
                summary="Update the dependency file narrowly.",
                operations=(
                    PreviewOperation(
                        path="requirements-dev.txt",
                        requested_operation="modify",
                        action="write_file",
                        absolute_path="/repo/requirements-dev.txt",
                        status="ready",
                        validation_reason="ready",
                        expected_sha256="abc123",
                        current_sha256="abc123",
                        current_exists=True,
                        diff="--- a/requirements-dev.txt\n+++ b/requirements-dev.txt\n@@ -1 +1,2 @@\n pytest\n+pytest-cov\n",
                        diff_bytes=88,
                        content_sha256="def456",
                        content="pytest\npytest-cov\n",
                    ),
                ),
                validation=("pytest -q",),
                risks=("Dependency updates can affect CI resolution.",),
            )
            with patch.dict(os.environ, {"MRCLEAN_ARTIFACT_SIGNING_KEY": "preview-secret"}, clear=False):
                dump_preview_bundles(
                    preview_path,
                    [preview],
                    key_env="MRCLEAN_ARTIFACT_SIGNING_KEY",
                )

                class FakeApplier:
                    def __init__(self, policy, *, config=None, workspace=None) -> None:
                        self.policy = policy
                        self.config = config

                    def apply(self, preview):
                        from mrclean.apply import ApplyTransaction

                        return ApplyTransaction(
                            repository=preview.repository,
                            number=preview.number,
                            branch=preview.branch,
                            status="applied",
                            summary=preview.summary,
                            operations=(),
                            validation=preview.validation,
                            risks=preview.risks,
                        )

                with patch("mrclean.cli.DraftApplier", FakeApplier):
                    result = main(["apply", str(config_path), "--preview-file", str(preview_path), "--execute", "--json"])

            self.assertEqual(result, 0)


def _minimal_scan_config() -> str:
    return """name = "mrclean"

[model]
provider = "openai"
name = "gpt-5.4-mini"

[policy]
dry_run = true
allow_local_apply = false
allow_push = false
allow_close_stale_prs = false
allow_force_push = false
require_signed_preview_artifacts = true
artifact_signing_key_env = "MRCLEAN_ARTIFACT_SIGNING_KEY"
max_patch_files = 5
protected_branches = ["main", "master"]

[[repositories]]
name = "example/repo"
base_branch = "main"
monitored_checks = ["build-linux"]
"""


class ScanIntegrationTests(unittest.TestCase):
    """Integration tests for the scan command exercising the full
    CLI → RepositoryScanner → GitHubCli stack with subprocess mocked
    at the lowest level (mrclean.github.subprocess.run)."""

    def _make_subprocess_run(
        self,
        responses: dict[tuple[str, ...], str],
        *,
        fail_keys: tuple[tuple[str, ...], ...] = (),
        auth_error: bool = False,
    ):
        """Return a mock for subprocess.run that serves canned gh responses."""

        def _mock_run(argv, *, check, capture_output, text):
            key = tuple(argv)
            if auth_error or key in fail_keys:
                err = subprocess.CalledProcessError(1, argv)
                err.stderr = "You are not logged into any GitHub hosts. Run gh auth login to authenticate."
                raise err
            if key in responses:
                result = MagicMock()
                result.stdout = responses[key]
                return result
            result = MagicMock()
            result.stdout = "[]"
            return result

        return _mock_run

    def test_scan_command_renders_pr_summary_through_full_github_stack(self) -> None:
        """Full integration path: CLI → RepositoryScanner → GitHubCli.

        Subprocess is mocked at the mrclean.github level so the real
        GitHubCli and RepositoryScanner code paths execute without
        a live GitHub connection.
        """
        list_key = (
            "gh",
            "pr",
            "list",
            "--repo",
            "example/repo",
            "--state",
            "open",
            "--json",
            "number,title,updatedAt,url",
        )
        view_key = (
            "gh",
            "pr",
            "view",
            "7",
            "--repo",
            "example/repo",
            "--json",
            "headRefName,headRefOid,mergeStateStatus,statusCheckRollup,title,updatedAt,url",
        )
        responses = {
            list_key: json.dumps(
                [
                    {
                        "number": 7,
                        "title": "Fix build failures",
                        "updatedAt": "2026-04-19T10:00:00Z",
                        "url": "https://github.com/example/repo/pull/7",
                    }
                ]
            ),
            view_key: json.dumps(
                {
                    "headRefName": "fix-build",
                    "headRefOid": "abc123",
                    "mergeStateStatus": "UNSTABLE",
                    "title": "Fix build failures",
                    "updatedAt": "2026-04-19T10:00:00Z",
                    "url": "https://github.com/example/repo/pull/7",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "build-linux",
                            "status": "COMPLETED",
                            "conclusion": "FAILURE",
                            "workflowName": "CI",
                        }
                    ],
                }
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_minimal_scan_config(), encoding="utf-8")

            mock_run = self._make_subprocess_run(responses)
            buffer = StringIO()
            with patch("mrclean.github.subprocess.run", side_effect=mock_run):
                with redirect_stdout(buffer):
                    result = main(["scan", str(config_path), "--repo", "example/repo"])

        self.assertEqual(result, 0)
        output = buffer.getvalue()
        self.assertIn("example/repo#7", output)
        self.assertIn("Fix build failures", output)
        self.assertIn("needs_attention", output)
        self.assertIn("build-linux", output)

    def test_scan_command_handles_unauthenticated_gh_cli(self) -> None:
        """Auth integration path: when gh reports an authentication error,
        the scan command should exit with code 1 and print a helpful message
        pointing the operator to 'gh auth login'.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_minimal_scan_config(), encoding="utf-8")

            mock_run = self._make_subprocess_run({}, auth_error=True)
            stderr_buffer = StringIO()
            with patch("mrclean.github.subprocess.run", side_effect=mock_run):
                with redirect_stdout(StringIO()), patch("sys.stderr", stderr_buffer):
                    result = main(["scan", str(config_path), "--repo", "example/repo"])

        self.assertEqual(result, 1)
        stderr = stderr_buffer.getvalue()
        self.assertIn("gh auth login", stderr)

    def test_scan_command_emits_json_through_full_github_stack(self) -> None:
        """Full integration path with --json output.

        Verifies that structured JSON output is produced correctly when
        the real GitHubCli and RepositoryScanner execute against mocked
        subprocess responses.
        """
        list_key = (
            "gh",
            "pr",
            "list",
            "--repo",
            "example/repo",
            "--state",
            "open",
            "--json",
            "number,title,updatedAt,url",
        )
        view_key = (
            "gh",
            "pr",
            "view",
            "12",
            "--repo",
            "example/repo",
            "--json",
            "headRefName,headRefOid,mergeStateStatus,statusCheckRollup,title,updatedAt,url",
        )
        responses = {
            list_key: json.dumps(
                [
                    {
                        "number": 12,
                        "title": "Stabilize CI",
                        "updatedAt": "2026-04-20T08:00:00Z",
                        "url": "https://github.com/example/repo/pull/12",
                    }
                ]
            ),
            view_key: json.dumps(
                {
                    "headRefName": "stabilize-ci",
                    "headRefOid": "def456",
                    "mergeStateStatus": "UNSTABLE",
                    "title": "Stabilize CI",
                    "updatedAt": "2026-04-20T08:00:00Z",
                    "url": "https://github.com/example/repo/pull/12",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "build-linux",
                            "status": "COMPLETED",
                            "conclusion": "FAILURE",
                            "workflowName": "CI",
                        }
                    ],
                }
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text(_minimal_scan_config(), encoding="utf-8")

            mock_run = self._make_subprocess_run(responses)
            buffer = StringIO()
            with patch("mrclean.github.subprocess.run", side_effect=mock_run):
                with redirect_stdout(buffer):
                    result = main(["scan", str(config_path), "--repo", "example/repo", "--json"])

        self.assertEqual(result, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(len(payload), 1)
        item = payload[0]
        self.assertEqual(item["repository"], "example/repo")
        self.assertEqual(item["number"], 12)
        self.assertEqual(item["title"], "Stabilize CI")
        self.assertEqual(item["category"], "needs_attention")
        self.assertIn("build-linux", item["failing_checks"])


if __name__ == "__main__":
    unittest.main()

