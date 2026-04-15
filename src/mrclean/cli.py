from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .agent import CleanupSignal, MrCleanAgent
from .config import MrCleanConfig, sample_config


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

