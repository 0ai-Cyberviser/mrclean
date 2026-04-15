from __future__ import annotations

from dataclasses import dataclass

from .monitor import RepositoryScanner, ScanResult


@dataclass(slots=True)
class WatchEvent:
    iteration: int
    kind: str
    repository: str
    number: int
    current: ScanResult | None = None
    previous: ScanResult | None = None


class RepositoryWatcher:
    def __init__(self, scanner: RepositoryScanner) -> None:
        self.scanner = scanner
        self._iteration = 0
        self._previous: dict[tuple[str, int], ScanResult] = {}

    @property
    def iteration(self) -> int:
        return self._iteration

    def poll(
        self,
        repositories: tuple[str, ...] | None = None,
        include_healthy: bool = False,
    ) -> tuple[WatchEvent, ...]:
        self._iteration += 1
        current_results = self.scanner.scan(repositories=repositories, include_healthy=include_healthy)
        current = {(item.repository, item.number): item for item in current_results}

        events: list[WatchEvent] = []
        for key in sorted(current, key=lambda item: (item[0], item[1])):
            item = current[key]
            previous = self._previous.get(key)
            if previous is None:
                events.append(
                    WatchEvent(
                        iteration=self._iteration,
                        kind="appeared",
                        repository=item.repository,
                        number=item.number,
                        current=item,
                    )
                )
                continue

            if _scan_signature(previous) != _scan_signature(item):
                events.append(
                    WatchEvent(
                        iteration=self._iteration,
                        kind="updated",
                        repository=item.repository,
                        number=item.number,
                        current=item,
                        previous=previous,
                    )
                )

        for key in sorted(self._previous, key=lambda item: (item[0], item[1])):
            if key in current:
                continue
            previous = self._previous[key]
            events.append(
                WatchEvent(
                    iteration=self._iteration,
                    kind="resolved",
                    repository=previous.repository,
                    number=previous.number,
                    previous=previous,
                )
            )

        self._previous = current
        return tuple(events)


def _scan_signature(item: ScanResult) -> tuple[object, ...]:
    return (
        item.title,
        item.url,
        item.branch,
        item.merge_state_status,
        item.category,
        item.failing_checks,
        item.pending_checks,
        item.changed_files,
        item.workspace_path,
        item.workspace_branch,
        item.workspace_notes,
        item.superseded_by,
        _plan_signature(item.plan),
    )


def _plan_signature(plan) -> tuple[object, ...] | None:
    if plan is None:
        return None
    return (
        plan.goal,
        tuple((action.kind, action.summary, action.branch, action.file_count, action.risky) for action in plan.actions),
        plan.policy_notes,
    )
