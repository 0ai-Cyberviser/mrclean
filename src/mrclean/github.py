from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess


SUCCESSFUL_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}


@dataclass(slots=True)
class CheckStatus:
    name: str
    status: str
    conclusion: str
    workflow_name: str = ""

    def is_failing(self) -> bool:
        return self.status == "COMPLETED" and self.conclusion not in SUCCESSFUL_CONCLUSIONS

    def is_pending(self) -> bool:
        return self.status != "COMPLETED"


@dataclass(slots=True)
class PullRequestSnapshot:
    repository: str
    number: int
    title: str
    url: str
    updated_at: str
    head_ref_name: str = ""
    head_ref_oid: str = ""
    merge_state_status: str = ""
    checks: tuple[CheckStatus, ...] = ()

    def failing_checks(self, monitored_checks: tuple[str, ...] = ()) -> tuple[str, ...]:
        return tuple(
            check.name for check in self.checks if check.is_failing() and _matches_monitored(check, monitored_checks)
        )

    def pending_checks(self, monitored_checks: tuple[str, ...] = ()) -> tuple[str, ...]:
        return tuple(
            check.name for check in self.checks if check.is_pending() and _matches_monitored(check, monitored_checks)
        )


class GitHubCli:
    def __init__(self, runner: callable | None = None) -> None:
        self._runner = runner or _run_gh_json

    def list_open_pull_requests(
        self,
        repository: str,
        *,
        authors: tuple[str, ...] = (),
    ) -> tuple[PullRequestSnapshot, ...]:
        selected_authors = tuple(author for author in authors if author)
        if not selected_authors:
            rows = self._search_pull_requests(repository)
        else:
            deduped: dict[int, dict[str, object]] = {}
            for author in selected_authors:
                for row in self._search_pull_requests(repository, author=author):
                    deduped[int(row["number"])] = row
            rows = tuple(
                sorted(
                    deduped.values(),
                    key=lambda item: (
                        str(item.get("updatedAt", "")),
                        int(item.get("number", 0)),
                    ),
                    reverse=True,
                )
            )

        snapshots: list[PullRequestSnapshot] = []
        for row in rows:
            snapshots.append(self.get_pull_request(repository, int(row["number"])))
        return tuple(snapshots)

    def _search_pull_requests(
        self,
        repository: str,
        *,
        author: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        argv = [
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
        ]
        if author:
            argv.extend(["--author", author])
        argv.extend(["--json", "number,title,updatedAt,url"])
        raw_prs = self._runner(argv)
        rows = json.loads(raw_prs)
        return tuple(rows)

    def get_pull_request(self, repository: str, number: int) -> PullRequestSnapshot:
        raw = self._runner(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                repository,
                "--json",
                "headRefName,headRefOid,mergeStateStatus,statusCheckRollup,title,updatedAt,url",
            ]
        )
        data = json.loads(raw)
        checks = tuple(
            CheckStatus(
                name=str(item.get("name", "")),
                status=str(item.get("status", "")),
                conclusion=str(item.get("conclusion", "")),
                workflow_name=str(item.get("workflowName", "")),
            )
            for item in data.get("statusCheckRollup", [])
            if item.get("__typename") == "CheckRun"
        )
        return PullRequestSnapshot(
            repository=repository,
            number=number,
            title=str(data.get("title", "")),
            url=str(data.get("url", "")),
            updated_at=str(data.get("updatedAt", "")),
            head_ref_name=str(data.get("headRefName", "")),
            head_ref_oid=str(data.get("headRefOid", "")),
            merge_state_status=str(data.get("mergeStateStatus", "")),
            checks=checks,
        )


def _run_gh_json(argv: list[str]) -> str:
    completed = subprocess.run(argv, check=True, capture_output=True, text=True)
    return completed.stdout


def _matches_monitored(check: CheckStatus, monitored_checks: tuple[str, ...]) -> bool:
    if not monitored_checks:
        return True
    candidates = tuple(value.lower() for value in (check.name, check.workflow_name) if value)
    patterns = tuple(pattern.lower() for pattern in monitored_checks)
    return any(pattern in candidate for candidate in candidates for pattern in patterns)
