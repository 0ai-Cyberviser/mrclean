from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .agent import CleanupSignal, MrCleanAgent
from .config import MrCleanConfig, sample_config
from .dispatch import DispatchCandidate, DispatchPlanner
from .monitor import RepositoryScanner, ScanResult
from .policies import PolicyEngine
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


if __name__ == "__main__":
    raise SystemExit(main())
