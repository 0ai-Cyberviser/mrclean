from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .agent import CleanupSignal, MrCleanAgent
from .config import MrCleanConfig, sample_config
from .monitor import RepositoryScanner


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
        payload = [
            {
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
            for item in results
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if not results:
        print("No matching PRs need attention.")
        return 0

    for item in results:
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
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
