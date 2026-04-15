from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .agent import AgentPlan, CleanupSignal, MrCleanAgent
from .config import MrCleanConfig, RepositoryConfig
from .github import GitHubCli, PullRequestSnapshot


@dataclass(slots=True)
class ScanResult:
    repository: str
    number: int
    title: str
    url: str
    branch: str
    updated_at: str
    merge_state_status: str
    category: str
    failing_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]
    superseded_by: int | None = None
    plan: AgentPlan | None = None


class RepositoryScanner:
    def __init__(self, config: MrCleanConfig, github: GitHubCli | None = None) -> None:
        self.config = config
        self.github = github or GitHubCli()
        self.agent = MrCleanAgent(config)

    def scan(
        self,
        repositories: tuple[str, ...] | None = None,
        include_healthy: bool = False,
    ) -> tuple[ScanResult, ...]:
        selected = (
            tuple(self.config.get_repository(name) for name in repositories)
            if repositories
            else self.config.repositories
        )
        results: list[ScanResult] = []
        for repository in selected:
            snapshots = self.github.list_open_pull_requests(repository.name)
            repository_results: list[ScanResult] = []
            for snapshot in snapshots:
                result = self._scan_pull_request(repository, snapshot, include_healthy)
                if result is not None:
                    repository_results.append(result)
            self._mark_superseded_candidates(repository, repository_results)
            results.extend(repository_results)
        return tuple(results)

    def _scan_pull_request(
        self,
        repository: RepositoryConfig,
        snapshot: PullRequestSnapshot,
        include_healthy: bool,
    ) -> ScanResult | None:
        failing = snapshot.failing_checks(repository.monitored_checks)
        pending = snapshot.pending_checks(repository.monitored_checks)

        category = "healthy"
        plan: AgentPlan | None = None
        if failing:
            category = "needs_attention"
            plan = self.agent.draft_plan(
                CleanupSignal(
                    repository=repository,
                    goal=f"stabilize failing CI for PR #{snapshot.number}",
                    branch=snapshot.head_ref_name or repository.base_branch,
                    failing_checks=failing,
                    notes=f"PR #{snapshot.number}: {snapshot.title}",
                )
            )
        elif pending:
            category = "pending"
        elif not include_healthy:
            return None

        return ScanResult(
            repository=repository.name,
            number=snapshot.number,
            title=snapshot.title,
            url=snapshot.url,
            branch=snapshot.head_ref_name or repository.base_branch,
            updated_at=snapshot.updated_at,
            merge_state_status=snapshot.merge_state_status,
            category=category,
            failing_checks=failing,
            pending_checks=pending,
            plan=plan,
        )

    def _mark_superseded_candidates(
        self,
        repository: RepositoryConfig,
        results: list[ScanResult],
    ) -> None:
        groups: dict[tuple[str, ...], list[ScanResult]] = {}
        for result in results:
            if result.category != "needs_attention" or not result.failing_checks:
                continue
            groups.setdefault(_normalize_checks(result.failing_checks), []).append(result)

        for siblings in groups.values():
            if len(siblings) < 2:
                continue

            newest = max(siblings, key=_result_sort_key)
            for stale in siblings:
                if stale.number == newest.number:
                    continue
                stale.category = "superseded_candidate"
                stale.superseded_by = newest.number
                stale.plan = self.agent.draft_plan(
                    CleanupSignal(
                        repository=repository,
                        goal=f"review stale PR #{stale.number} and confirm it is superseded",
                        branch=stale.branch,
                        notes=(
                            f"PR #{stale.number} appears older than PR #{newest.number} and is failing "
                            f"the same monitored checks: {', '.join(stale.failing_checks)}"
                        ),
                    )
                )


def _normalize_checks(checks: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(checks, key=str.lower))


def _result_sort_key(result: ScanResult) -> tuple[datetime, int]:
    return (_parse_timestamp(result.updated_at), result.number)


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
