from __future__ import annotations

from dataclasses import dataclass
import subprocess

from .dispatch import DispatchAction, DispatchCandidate

SAFE_EXECUTABLE_KINDS = {"inspect_signal", "review_pr_scope", "edit_patch"}


@dataclass(slots=True)
class ActionExecution:
    kind: str
    summary: str
    command: str
    status: str
    reason: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


@dataclass(slots=True)
class RunSession:
    repository: str
    number: int
    branch: str
    candidate_status: str
    run_status: str
    executions: tuple[ActionExecution, ...]


class LocalRunner:
    def __init__(self, command_runner: callable | None = None, output_limit: int = 4000) -> None:
        self._command_runner = command_runner or _run_command
        self.output_limit = output_limit

    def run(
        self,
        candidates: tuple[DispatchCandidate, ...],
        *,
        pr_number: int | None = None,
        limit: int = 1,
    ) -> tuple[RunSession, ...]:
        selected = _select_candidates(candidates, pr_number=pr_number, limit=limit)
        return tuple(self._run_candidate(candidate) for candidate in selected)

    def _run_candidate(self, candidate: DispatchCandidate) -> RunSession:
        executions: list[ActionExecution] = []
        executed_any = False

        for action in candidate.actions:
            execution = self._execute_action(action)
            executions.append(execution)
            if execution.status == "executed":
                executed_any = True

        run_status = _run_status(candidate.status, executed_any)
        return RunSession(
            repository=candidate.repository,
            number=candidate.number,
            branch=candidate.branch,
            candidate_status=candidate.status,
            run_status=run_status,
            executions=tuple(executions),
        )

    def _execute_action(self, action: DispatchAction) -> ActionExecution:
        if not action.allowed:
            return ActionExecution(
                kind=action.kind,
                summary=action.summary,
                command=action.command_hint,
                status="skipped",
                reason=action.reason,
            )
        if action.kind not in SAFE_EXECUTABLE_KINDS:
            return ActionExecution(
                kind=action.kind,
                summary=action.summary,
                command=action.command_hint,
                status="skipped",
                reason="action is not executable in local dry-run mode",
            )
        if not action.command_hint:
            return ActionExecution(
                kind=action.kind,
                summary=action.summary,
                command="",
                status="skipped",
                reason="no command hint available",
            )

        completed = self._command_runner(action.command_hint)
        stdout = _truncate(completed.stdout, self.output_limit)
        stderr = _truncate(completed.stderr, self.output_limit)
        status = "executed" if completed.returncode == 0 else "failed"
        reason = "command completed successfully" if completed.returncode == 0 else f"command exited with {completed.returncode}"
        return ActionExecution(
            kind=action.kind,
            summary=action.summary,
            command=action.command_hint,
            status=status,
            reason=reason,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )


def _select_candidates(
    candidates: tuple[DispatchCandidate, ...],
    *,
    pr_number: int | None,
    limit: int,
) -> tuple[DispatchCandidate, ...]:
    if pr_number is not None:
        return tuple(candidate for candidate in candidates if candidate.number == pr_number)

    runnable = tuple(candidate for candidate in candidates if candidate.status in {"ready", "inspect_only"})
    if limit <= 0:
        return runnable
    return runnable[:limit]


def _run_status(candidate_status: str, executed_any: bool) -> str:
    if not executed_any:
        return "blocked"
    if candidate_status == "inspect_only":
        return "inspected"
    return "prepared"


def _run_command(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 13] + "\n...[truncated]"
