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
from unittest.mock import patch

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

                def __init__(self, scanner) -> None:
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
                def run(self, candidates, pr_number=None, limit=1):
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
                def run(self, candidates, pr_number=None, limit=1):
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
                def run(self, candidates, pr_number=None, limit=1):
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
                def run(self, candidates, pr_number=None, limit=1):
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
                def run(self, candidates, pr_number=None, limit=1):
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
                def run(self, candidates, pr_number=None, limit=1):
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


if __name__ == "__main__":
    unittest.main()
