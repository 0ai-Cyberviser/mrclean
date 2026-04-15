from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .agent import CleanupSignal, MrCleanAgent
from .config import MrCleanConfig, sample_config
from .dispatch import DispatchCandidate, DispatchPlanner
from .drafts import DraftBundle, DraftGenerator
from .intents import EditIntent, IntentGenerator
from .materialize import IntentMaterializer, MaterializedIntent
from .monitor import RepositoryScanner, ScanResult
from .policies import PolicyEngine
from .previews import DraftPreviewer, PreviewBundle
from .proposals import Proposal, ProposalGenerator
from .runner import ActionExecution, LocalRunner, RunSession
from .watch import RepositoryWatcher, WatchEvent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mrclean", description="MrClean automation agent scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="write a sample MrClean config")
    init_parser.add_argument("path", nargs="?", default="mrclean.toml", help="path to write")
    init_parser.add_argument("--force", action="store_true", help="overwrite existing files")

    validate_parser = subparsers.add_parser("validate", help="validate a config file")
    validate_parser.add_argument("config", help="path to mrclean TOML config")

    plan_parser = subparsers.add_parser("plan", help="build a cleanup plan")
    plan_parser.add_argument("config", help="path to mrclean TOML config")
    plan_parser.add_argument("--repo", required=True, help="repository name from config")
    plan_parser.add_argument("--goal", required=True, help="cleanup goal")
    plan_parser.add_argument("--branch", default="main", help="working branch")
    plan_parser.add_argument("--check", action="append", default=[], help="failing check name")
    plan_parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="changed file associated with the signal",
    )
    plan_parser.add_argument("--notes", default="", help="extra operator notes")
    plan_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")

    scan_parser = subparsers.add_parser("scan", help="scan configured repositories for active PR issues")
    scan_parser.add_argument("config", help="path to mrclean TOML config")
    scan_parser.add_argument("--repo", action="append", default=[], help="limit scan to a configured repo")
    scan_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    scan_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the output instead of only pending or failing ones",
    )

    watch_parser = subparsers.add_parser("watch", help="poll configured repositories and emit queue changes")
    watch_parser.add_argument("config", help="path to mrclean TOML config")
    watch_parser.add_argument("--repo", action="append", default=[], help="limit watch to a configured repo")
    watch_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    watch_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )
    watch_parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="seconds to wait between polls",
    )
    watch_parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="number of polls to run; 0 means run until interrupted",
    )

    dispatch_parser = subparsers.add_parser(
        "dispatch",
        help="turn the current queue into guarded execution candidates",
    )
    dispatch_parser.add_argument("config", help="path to mrclean TOML config")
    dispatch_parser.add_argument("--repo", action="append", default=[], help="limit dispatch to a configured repo")
    dispatch_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    dispatch_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="execute safe local prep commands for ready or inspect-only candidates",
    )
    run_parser.add_argument("config", help="path to mrclean TOML config")
    run_parser.add_argument("--repo", action="append", default=[], help="limit run to a configured repo")
    run_parser.add_argument("--pr", type=int, help="target one PR number from the dispatch queue")
    run_parser.add_argument("--limit", type=int, default=1, help="number of candidates to run when --pr is omitted")
    run_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    run_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    propose_parser = subparsers.add_parser(
        "propose",
        help="generate a bounded edit proposal from a runnable candidate",
    )
    propose_parser.add_argument("config", help="path to mrclean TOML config")
    propose_parser.add_argument("--repo", action="append", default=[], help="limit propose to a configured repo")
    propose_parser.add_argument("--pr", type=int, help="target one PR number from the dispatch queue")
    propose_parser.add_argument("--limit", type=int, default=1, help="number of candidates to propose for when --pr is omitted")
    propose_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    propose_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    intent_parser = subparsers.add_parser(
        "intent",
        help="generate a validated machine-readable edit intent from a runnable candidate",
    )
    intent_parser.add_argument("config", help="path to mrclean TOML config")
    intent_parser.add_argument("--repo", action="append", default=[], help="limit intent generation to a configured repo")
    intent_parser.add_argument("--pr", type=int, help="target one PR number from the dispatch queue")
    intent_parser.add_argument("--limit", type=int, default=1, help="number of candidates to generate intents for when --pr is omitted")
    intent_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    intent_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    materialize_parser = subparsers.add_parser(
        "materialize",
        help="resolve a generated intent against the local checkout without applying it",
    )
    materialize_parser.add_argument("config", help="path to mrclean TOML config")
    materialize_parser.add_argument("--repo", action="append", default=[], help="limit materialization to a configured repo")
    materialize_parser.add_argument("--pr", type=int, help="target one PR number from the dispatch queue")
    materialize_parser.add_argument("--limit", type=int, default=1, help="number of candidates to materialize when --pr is omitted")
    materialize_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    materialize_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    draft_parser = subparsers.add_parser(
        "draft",
        help="convert a materialized intent into explicit file-write/delete operations without applying them",
    )
    draft_parser.add_argument("config", help="path to mrclean TOML config")
    draft_parser.add_argument("--repo", action="append", default=[], help="limit draft generation to a configured repo")
    draft_parser.add_argument("--pr", type=int, help="target one PR number from the dispatch queue")
    draft_parser.add_argument("--limit", type=int, default=1, help="number of candidates to draft when --pr is omitted")
    draft_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    draft_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    preview_parser = subparsers.add_parser(
        "preview",
        help="render unified diff previews from guarded draft bundles without applying them",
    )
    preview_parser.add_argument("config", help="path to mrclean TOML config")
    preview_parser.add_argument("--repo", action="append", default=[], help="limit preview generation to a configured repo")
    preview_parser.add_argument("--pr", type=int, help="target one PR number from the dispatch queue")
    preview_parser.add_argument("--limit", type=int, default=1, help="number of candidates to preview when --pr is omitted")
    preview_parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    preview_parser.add_argument(
        "--include-healthy",
        action="store_true",
        help="include healthy PRs in the queue instead of only pending or failing ones",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return _run_init(Path(args.path), args.force)
    if args.command == "validate":
        return _run_validate(Path(args.config))
    if args.command == "plan":
        return _run_plan(args)
    if args.command == "scan":
        return _run_scan(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "dispatch":
        return _run_dispatch(args)
    if args.command == "run":
        return _run_run(args)
    if args.command == "propose":
        return _run_propose(args)
    if args.command == "intent":
        return _run_intent(args)
    if args.command == "materialize":
        return _run_materialize(args)
    if args.command == "draft":
        return _run_draft(args)
    if args.command == "preview":
        return _run_preview(args)

    parser.error("unknown command")
    return 2


def _run_init(path: Path, force: bool) -> int:
    if path.exists() and not force:
        print(f"refusing to overwrite existing file: {path}", file=sys.stderr)
        return 1
    path.write_text(sample_config(), encoding="utf-8")
    print(f"wrote sample config to {path}")
    return 0


def _run_validate(path: Path) -> int:
    config = MrCleanConfig.from_toml(path)
    print(
        f"config valid: name={config.name}, repos={len(config.repositories)}, "
        f"dry_run={config.policy.dry_run}, model={config.model.name}"
    )
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    repository = config.get_repository(args.repo)
    agent = MrCleanAgent(config)
    plan = agent.draft_plan(
        CleanupSignal(
            repository=repository,
            goal=args.goal,
            branch=args.branch,
            failing_checks=tuple(args.check),
            changed_files=tuple(args.changed_file),
            notes=args.notes,
        )
    )

    if args.json:
        payload = {
            "repository": plan.repository,
            "goal": plan.goal,
            "model_summary": plan.model_summary,
            "actions": [
                {
                    "kind": action.kind,
                    "summary": action.summary,
                    "branch": action.branch,
                    "file_count": action.file_count,
                    "risky": action.risky,
                }
                for action in plan.actions
            ],
            "policy_notes": list(plan.policy_notes),
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Repository: {plan.repository}")
    print(f"Goal: {plan.goal}")
    print("Model summary:")
    print(plan.model_summary)
    print("Actions:")
    for action in plan.actions:
        print(f"- {action.kind}: {action.summary}")
    print("Policy notes:")
    for note in plan.policy_notes:
        print(f"- {note}")
    return 0


def _run_scan(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    scanner = RepositoryScanner(config)
    results = scanner.scan(
        repositories=tuple(args.repo),
        include_healthy=bool(args.include_healthy),
    )

    if args.json:
        payload = [_scan_item_payload(item) for item in results]
        print(json.dumps(payload, indent=2))
        return 0

    if not results:
        print("No matching PRs need attention.")
        return 0

    for item in results:
        _print_scan_item(item)
        print()
    return 0


def _run_watch(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    watcher = RepositoryWatcher(RepositoryScanner(config))
    iteration_limit = args.iterations
    try:
        while True:
            events = watcher.poll(
                repositories=tuple(args.repo),
                include_healthy=bool(args.include_healthy),
            )
            _emit_watch_iteration(watcher.iteration, events, json_mode=bool(args.json))

            if iteration_limit and watcher.iteration >= iteration_limit:
                return 0
            time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        print("watch interrupted", file=sys.stderr)
        return 130


def _run_dispatch(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    scanner = RepositoryScanner(config)
    results = scanner.scan(
        repositories=tuple(args.repo),
        include_healthy=bool(args.include_healthy),
    )
    planner = DispatchPlanner(PolicyEngine(config.policy))
    candidates = planner.build(results)

    if args.json:
        payload = [_dispatch_candidate_payload(candidate) for candidate in candidates]
        print(json.dumps(payload, indent=2))
        return 0

    if not candidates:
        print("No dispatch candidates.")
        return 0

    for candidate in candidates:
        _print_dispatch_candidate(candidate)
        print()
    return 0


def _run_run(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    scanner = RepositoryScanner(config)
    results = scanner.scan(
        repositories=tuple(args.repo),
        include_healthy=bool(args.include_healthy),
    )
    planner = DispatchPlanner(PolicyEngine(config.policy))
    candidates = planner.build(results)
    runner = LocalRunner()
    sessions = runner.run(candidates, pr_number=args.pr, limit=args.limit)

    if args.pr is not None and not sessions:
        print(f"PR #{args.pr} is not present in the dispatch queue.", file=sys.stderr)
        return 1

    if args.json:
        payload = [_run_session_payload(session) for session in sessions]
        print(json.dumps(payload, indent=2))
        return 0

    if not sessions:
        print("No runnable candidates.")
        return 0

    for session in sessions:
        _print_run_session(session)
        print()
    return 0


def _run_propose(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    scanner = RepositoryScanner(config)
    results = scanner.scan(
        repositories=tuple(args.repo),
        include_healthy=bool(args.include_healthy),
    )
    planner = DispatchPlanner(PolicyEngine(config.policy))
    candidates = planner.build(results)
    candidate_map = {(candidate.repository, candidate.number): candidate for candidate in candidates}

    runner = LocalRunner()
    sessions = runner.run(candidates, pr_number=args.pr, limit=args.limit)
    if args.pr is not None and not sessions:
        print(f"PR #{args.pr} is not present in the runnable queue.", file=sys.stderr)
        return 1
    if not sessions:
        print("No proposal candidates.")
        return 0

    generator = ProposalGenerator(config)
    proposals = []
    for session in sessions:
        candidate = candidate_map[(session.repository, session.number)]
        proposals.append(generator.generate(candidate, session))

    if args.json:
        payload = [_proposal_payload(item) for item in proposals]
        print(json.dumps(payload, indent=2))
        return 0

    for proposal in proposals:
        _print_proposal(proposal)
        print()
    return 0


def _run_intent(args: argparse.Namespace) -> int:
    config = MrCleanConfig.from_toml(Path(args.config))
    scanner = RepositoryScanner(config)
    results = scanner.scan(
        repositories=tuple(args.repo),
        include_healthy=bool(args.include_healthy),
    )
    planner = DispatchPlanner(PolicyEngine(config.policy))
    candidates = planner.build(results)
    candidate_map = {(candidate.repository, candidate.number): candidate for candidate in candidates}

    runner = LocalRunner()
    sessions = runner.run(candidates, pr_number=args.pr, limit=args.limit)
    if args.pr is not None and not sessions:
        print(f"PR #{args.pr} is not present in the runnable queue.", file=sys.stderr)
        return 1
    if not sessions:
        print("No intent candidates.")
        return 0

    generator = IntentGenerator(config)
    intents = []
    for session in sessions:
        candidate = candidate_map[(session.repository, session.number)]
        intents.append(generator.generate(candidate, session))

    if args.json:
        payload = [_intent_payload(item) for item in intents]
        print(json.dumps(payload, indent=2))
        return 0

    for intent in intents:
        _print_intent(intent)
        print()
    return 0


def _run_materialize(args: argparse.Namespace) -> int:
    materialized = _build_materialized_batch(args)
    if args.pr is not None and not materialized:
        print(f"PR #{args.pr} is not present in the runnable queue.", file=sys.stderr)
        return 1
    if not materialized:
        print("No materialization candidates.")
        return 0

    if args.json:
        payload = [_materialized_intent_payload(item) for item in materialized]
        print(json.dumps(payload, indent=2))
        return 0

    for item in materialized:
        _print_materialized_intent(item)
        print()
    return 0


def _run_draft(args: argparse.Namespace) -> int:
    drafts = _build_draft_batch(args)
    if args.pr is not None and not drafts:
        print(f"PR #{args.pr} is not present in the runnable queue.", file=sys.stderr)
        return 1
    if not drafts:
        print("No draft candidates.")
        return 0

    if args.json:
        payload = [_draft_bundle_payload(item) for item in drafts]
        print(json.dumps(payload, indent=2))
        return 0

    for item in drafts:
        _print_draft_bundle(item)
        print()
    return 0


def _run_preview(args: argparse.Namespace) -> int:
    drafts = _build_draft_batch(args)
    if args.pr is not None and not drafts:
        print(f"PR #{args.pr} is not present in the runnable queue.", file=sys.stderr)
        return 1
    if not drafts:
        print("No preview candidates.")
        return 0

    previewer = DraftPreviewer()
    previews = [previewer.preview(item) for item in drafts]

    if args.json:
        payload = [_preview_bundle_payload(item) for item in previews]
        print(json.dumps(payload, indent=2))
        return 0

    for item in previews:
        _print_preview_bundle(item)
        print()
    return 0


def _build_materialized_batch(args: argparse.Namespace) -> list[MaterializedIntent]:
    config = MrCleanConfig.from_toml(Path(args.config))
    scanner = RepositoryScanner(config)
    results = scanner.scan(
        repositories=tuple(args.repo),
        include_healthy=bool(args.include_healthy),
    )
    planner = DispatchPlanner(PolicyEngine(config.policy))
    candidates = planner.build(results)
    candidate_map = {(candidate.repository, candidate.number): candidate for candidate in candidates}

    runner = LocalRunner()
    sessions = runner.run(candidates, pr_number=args.pr, limit=args.limit)
    if not sessions:
        return []

    intent_generator = IntentGenerator(config)
    materializer = IntentMaterializer(config)
    materialized = []
    for session in sessions:
        candidate = candidate_map[(session.repository, session.number)]
        intent = intent_generator.generate(candidate, session)
        materialized.append(materializer.materialize(candidate, intent))
    return materialized


def _build_draft_batch(args: argparse.Namespace) -> list[DraftBundle]:
    materialized = _build_materialized_batch(args)
    if not materialized:
        return []

    config = MrCleanConfig.from_toml(Path(args.config))
    generator = DraftGenerator(config)
    return [generator.generate(item) for item in materialized]


def _scan_item_payload(item: ScanResult) -> dict[str, object]:
    return {
        "repository": item.repository,
        "number": item.number,
        "title": item.title,
        "url": item.url,
        "branch": item.branch,
        "updated_at": item.updated_at,
        "merge_state_status": item.merge_state_status,
        "category": item.category,
        "failing_checks": list(item.failing_checks),
        "pending_checks": list(item.pending_checks),
        "changed_files": list(item.changed_files),
        "workspace_path": item.workspace_path,
        "workspace_branch": item.workspace_branch,
        "workspace_notes": list(item.workspace_notes),
        "superseded_by": item.superseded_by,
        "plan": None
        if item.plan is None
        else {
            "goal": item.plan.goal,
            "actions": [
                {
                    "kind": action.kind,
                    "summary": action.summary,
                    "file_count": action.file_count,
                    "risky": action.risky,
                }
                for action in item.plan.actions
            ],
            "policy_notes": list(item.plan.policy_notes),
        },
    }


def _print_scan_item(item: ScanResult) -> None:
    print(f"{item.repository}#{item.number} [{item.category}]")
    print(f"Title: {item.title}")
    print(f"Branch: {item.branch}")
    print(f"Merge state: {item.merge_state_status or 'unknown'}")
    print(f"Updated at: {item.updated_at or 'unknown'}")
    if item.workspace_path:
        branch_text = item.workspace_branch or "unknown"
        print(f"Workspace: {item.workspace_path} (branch: {branch_text})")
    if item.failing_checks:
        print(f"Failing checks: {', '.join(item.failing_checks)}")
    if item.pending_checks:
        print(f"Pending checks: {', '.join(item.pending_checks)}")
    if item.changed_files:
        print(f"Changed files: {', '.join(item.changed_files)}")
    if item.workspace_notes:
        print(f"Workspace notes: {'; '.join(item.workspace_notes)}")
    if item.superseded_by is not None:
        print(f"Superseded by: PR #{item.superseded_by}")
    if item.plan is not None:
        print("Suggested actions:")
        for action in item.plan.actions:
            print(f"- {action.kind}: {action.summary}")
        print("Policy notes:")
        for note in item.plan.policy_notes:
            print(f"- {note}")
    print(f"URL: {item.url}")


def _emit_watch_iteration(iteration: int, events: tuple[WatchEvent, ...], json_mode: bool) -> None:
    if json_mode:
        payload = {
            "iteration": iteration,
            "events": [_watch_event_payload(event) for event in events],
        }
        print(json.dumps(payload, indent=2))
        return

    if not events:
        print(f"Iteration {iteration}: no queue changes.")
        return

    for event in events:
        print(f"Iteration {event.iteration}: {event.kind} {event.repository}#{event.number}")
        target = event.current if event.current is not None else event.previous
        if target is not None:
            _print_scan_item(target)
        if event.kind == "updated" and event.previous is not None and event.current is not None:
            print(f"Previous category: {event.previous.category}")
        if event.kind == "resolved":
            print("Resolved from queue.")
        print()


def _watch_event_payload(event: WatchEvent) -> dict[str, object]:
    return {
        "iteration": event.iteration,
        "kind": event.kind,
        "repository": event.repository,
        "number": event.number,
        "current": None if event.current is None else _scan_item_payload(event.current),
        "previous": None if event.previous is None else _scan_item_payload(event.previous),
    }


def _dispatch_candidate_payload(candidate: DispatchCandidate) -> dict[str, object]:
    return {
        "repository": candidate.repository,
        "number": candidate.number,
        "title": candidate.title,
        "url": candidate.url,
        "branch": candidate.branch,
        "category": candidate.category,
        "status": candidate.status,
        "priority": candidate.priority,
        "workspace_ready": candidate.workspace_ready,
        "workspace_reason": candidate.workspace_reason,
        "changed_files": list(candidate.changed_files),
        "actions": [
            {
                "kind": action.kind,
                "summary": action.summary,
                "allowed": action.allowed,
                "reason": action.reason,
                "command_hint": action.command_hint,
            }
            for action in candidate.actions
        ],
    }


def _print_dispatch_candidate(candidate: DispatchCandidate) -> None:
    print(f"{candidate.repository}#{candidate.number} [{candidate.status}]")
    print(f"Title: {candidate.title}")
    print(f"Branch: {candidate.branch}")
    print(f"Category: {candidate.category}")
    print(f"Priority: {candidate.priority}")
    print(f"Workspace ready: {'yes' if candidate.workspace_ready else 'no'}")
    print(f"Workspace reason: {candidate.workspace_reason}")
    if candidate.changed_files:
        print(f"Changed files: {', '.join(candidate.changed_files)}")
    if not candidate.actions:
        print("No actions queued.")
    else:
        print("Actions:")
        for action in candidate.actions:
            verdict = "allowed" if action.allowed else "blocked"
            print(f"- {action.kind} [{verdict}]: {action.summary}")
            print(f"  reason: {action.reason}")
            if action.command_hint:
                print(f"  hint: {action.command_hint}")
    print(f"URL: {candidate.url}")


def _run_session_payload(session: RunSession) -> dict[str, object]:
    return {
        "repository": session.repository,
        "number": session.number,
        "branch": session.branch,
        "candidate_status": session.candidate_status,
        "run_status": session.run_status,
        "executions": [_action_execution_payload(execution) for execution in session.executions],
    }


def _action_execution_payload(execution: ActionExecution) -> dict[str, object]:
    return {
        "kind": execution.kind,
        "summary": execution.summary,
        "command": execution.command,
        "status": execution.status,
        "reason": execution.reason,
        "returncode": execution.returncode,
        "stdout": execution.stdout,
        "stderr": execution.stderr,
    }


def _print_run_session(session: RunSession) -> None:
    print(f"{session.repository}#{session.number} [{session.run_status}]")
    print(f"Branch: {session.branch}")
    print(f"Candidate status: {session.candidate_status}")
    if not session.executions:
        print("No executions.")
        return
    print("Executions:")
    for execution in session.executions:
        print(f"- {execution.kind} [{execution.status}]: {execution.summary}")
        print(f"  reason: {execution.reason}")
        if execution.command:
            print(f"  command: {execution.command}")
        if execution.returncode is not None:
            print(f"  returncode: {execution.returncode}")
        if execution.stdout.strip():
            print("  stdout:")
            for line in execution.stdout.rstrip().splitlines():
                print(f"    {line}")
        if execution.stderr.strip():
            print("  stderr:")
            for line in execution.stderr.rstrip().splitlines():
                print(f"    {line}")


def _proposal_payload(proposal: Proposal) -> dict[str, object]:
    return {
        "repository": proposal.repository,
        "number": proposal.number,
        "branch": proposal.branch,
        "candidate_status": proposal.candidate_status,
        "run_status": proposal.run_status,
        "content": proposal.content,
        "model_provider": proposal.model_provider,
        "model_name": proposal.model_name,
        "raw": proposal.raw,
    }


def _print_proposal(proposal: Proposal) -> None:
    print(f"{proposal.repository}#{proposal.number} [proposal]")
    print(f"Branch: {proposal.branch}")
    print(f"Candidate status: {proposal.candidate_status}")
    print(f"Run status: {proposal.run_status}")
    print(f"Model: {proposal.model_provider}/{proposal.model_name}")
    print("Proposal:")
    for line in proposal.content.rstrip().splitlines():
        print(f"  {line}")


def _intent_payload(intent: EditIntent) -> dict[str, object]:
    return {
        "repository": intent.repository,
        "number": intent.number,
        "branch": intent.branch,
        "candidate_status": intent.candidate_status,
        "run_status": intent.run_status,
        "summary": intent.summary,
        "edits": [
            {
                "path": edit.path,
                "operation": edit.operation,
                "summary": edit.summary,
                "reason": edit.reason,
            }
            for edit in intent.edits
        ],
        "validation": list(intent.validation),
        "risks": list(intent.risks),
        "model_provider": intent.model_provider,
        "model_name": intent.model_name,
        "raw": intent.raw,
    }


def _print_intent(intent: EditIntent) -> None:
    print(f"{intent.repository}#{intent.number} [intent]")
    print(f"Branch: {intent.branch}")
    print(f"Candidate status: {intent.candidate_status}")
    print(f"Run status: {intent.run_status}")
    print(f"Model: {intent.model_provider}/{intent.model_name}")
    print(f"Summary: {intent.summary}")
    print("Edits:")
    for edit in intent.edits:
        print(f"- {edit.operation} {edit.path}: {edit.summary}")
        print(f"  reason: {edit.reason}")
    if intent.validation:
        print("Validation:")
        for item in intent.validation:
            print(f"- {item}")
    if intent.risks:
        print("Risks:")
        for item in intent.risks:
            print(f"- {item}")


def _materialized_intent_payload(item: MaterializedIntent) -> dict[str, object]:
    return {
        "repository": item.repository,
        "number": item.number,
        "branch": item.branch,
        "workspace_path": item.workspace_path,
        "workspace_branch": item.workspace_branch,
        "workspace_ready": item.workspace_ready,
        "workspace_reason": item.workspace_reason,
        "status": item.status,
        "summary": item.summary,
        "edits": [
            {
                "path": edit.path,
                "operation": edit.operation,
                "summary": edit.summary,
                "reason": edit.reason,
                "absolute_path": edit.absolute_path,
                "status": edit.status,
                "validation_reason": edit.validation_reason,
                "exists": edit.exists,
                "in_branch_scope": edit.in_branch_scope,
                "size_bytes": edit.size_bytes,
                "sha256": edit.sha256,
                "preview": edit.preview,
            }
            for edit in item.edits
        ],
        "validation": list(item.validation),
        "risks": list(item.risks),
    }


def _print_materialized_intent(item: MaterializedIntent) -> None:
    print(f"{item.repository}#{item.number} [materialized]")
    print(f"Branch: {item.branch}")
    print(f"Workspace: {item.workspace_path} (branch: {item.workspace_branch or 'unknown'})")
    print(f"Workspace ready: {'yes' if item.workspace_ready else 'no'}")
    print(f"Workspace reason: {item.workspace_reason}")
    print(f"Status: {item.status}")
    print(f"Summary: {item.summary}")
    print("Edits:")
    for edit in item.edits:
        print(f"- {edit.operation} {edit.path} [{edit.status}]")
        print(f"  validation: {edit.validation_reason}")
        print(f"  absolute path: {edit.absolute_path}")
        print(f"  in branch scope: {'yes' if edit.in_branch_scope else 'no'}")
        if edit.exists:
            print(f"  size: {edit.size_bytes} bytes")
            print(f"  sha256: {edit.sha256}")
            if edit.preview:
                print("  preview:")
                for line in edit.preview.rstrip().splitlines():
                    print(f"    {line}")
        else:
            print("  preview: <file does not exist>")
    if item.validation:
        print("Validation:")
        for check in item.validation:
            print(f"- {check}")
    if item.risks:
        print("Risks:")
        for risk in item.risks:
            print(f"- {risk}")


def _draft_bundle_payload(item: DraftBundle) -> dict[str, object]:
    return {
        "repository": item.repository,
        "number": item.number,
        "branch": item.branch,
        "status": item.status,
        "summary": item.summary,
        "operations": [
            {
                "path": operation.path,
                "requested_operation": operation.requested_operation,
                "action": operation.action,
                "summary": operation.summary,
                "reason": operation.reason,
                "absolute_path": operation.absolute_path,
                "status": operation.status,
                "validation_reason": operation.validation_reason,
                "expected_sha256": operation.expected_sha256,
                "content_sha256": operation.content_sha256,
                "content_bytes": operation.content_bytes,
                "content_preview": operation.content_preview,
                "content": operation.content,
            }
            for operation in item.operations
        ],
        "validation": list(item.validation),
        "risks": list(item.risks),
        "model_provider": item.model_provider,
        "model_name": item.model_name,
        "raw": item.raw,
    }


def _print_draft_bundle(item: DraftBundle) -> None:
    print(f"{item.repository}#{item.number} [draft]")
    print(f"Branch: {item.branch}")
    print(f"Status: {item.status}")
    print(f"Summary: {item.summary}")
    print(f"Model: {item.model_provider} {item.model_name}".rstrip())
    print("Operations:")
    for operation in item.operations:
        print(f"- {operation.action} {operation.path} [{operation.status}]")
        print(f"  requested operation: {operation.requested_operation}")
        print(f"  validation: {operation.validation_reason}")
        print(f"  absolute path: {operation.absolute_path}")
        if operation.expected_sha256:
            print(f"  expected sha256: {operation.expected_sha256}")
        if operation.content_sha256:
            print(f"  content sha256: {operation.content_sha256}")
        if operation.content_bytes is not None:
            print(f"  content bytes: {operation.content_bytes}")
        if operation.content_preview:
            print("  content preview:")
            for line in operation.content_preview.rstrip().splitlines():
                print(f"    {line}")
    if item.validation:
        print("Validation:")
        for check in item.validation:
            print(f"- {check}")
    if item.risks:
        print("Risks:")
        for risk in item.risks:
            print(f"- {risk}")


def _preview_bundle_payload(item: PreviewBundle) -> dict[str, object]:
    return {
        "repository": item.repository,
        "number": item.number,
        "branch": item.branch,
        "status": item.status,
        "summary": item.summary,
        "operations": [
            {
                "path": operation.path,
                "action": operation.action,
                "absolute_path": operation.absolute_path,
                "status": operation.status,
                "validation_reason": operation.validation_reason,
                "expected_sha256": operation.expected_sha256,
                "current_sha256": operation.current_sha256,
                "current_exists": operation.current_exists,
                "diff": operation.diff,
                "diff_bytes": operation.diff_bytes,
            }
            for operation in item.operations
        ],
        "validation": list(item.validation),
        "risks": list(item.risks),
    }


def _print_preview_bundle(item: PreviewBundle) -> None:
    print(f"{item.repository}#{item.number} [preview]")
    print(f"Branch: {item.branch}")
    print(f"Status: {item.status}")
    print(f"Summary: {item.summary}")
    print("Operations:")
    for operation in item.operations:
        print(f"- {operation.action} {operation.path} [{operation.status}]")
        print(f"  validation: {operation.validation_reason}")
        print(f"  absolute path: {operation.absolute_path}")
        if operation.expected_sha256:
            print(f"  expected sha256: {operation.expected_sha256}")
        if operation.current_sha256:
            print(f"  current sha256: {operation.current_sha256}")
        print(f"  current exists: {'yes' if operation.current_exists else 'no'}")
        print(f"  diff bytes: {operation.diff_bytes}")
        if operation.diff:
            print("  diff:")
            for line in operation.diff.rstrip().splitlines():
                print(f"    {line}")
    if item.validation:
        print("Validation:")
        for check in item.validation:
            print(f"- {check}")
    if item.risks:
        print("Risks:")
        for risk in item.risks:
            print(f"- {risk}")


if __name__ == "__main__":
    raise SystemExit(main())
