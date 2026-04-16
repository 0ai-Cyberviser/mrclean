from __future__ import annotations

import json
import unittest

from mrclean.github import GitHubCli


class GitHubCliTests(unittest.TestCase):
    def test_list_open_pull_requests_parses_checks(self) -> None:
        responses = {
            (
                "gh",
                "pr",
                "list",
                "--repo",
                "example/repo",
                "--state",
                "open",
                "--json",
                "number,title,updatedAt,url",
            ): json.dumps(
                [
                    {
                        "number": 7,
                        "title": "Fix CI",
                        "updatedAt": "2026-04-15T18:00:00Z",
                        "url": "https://github.com/example/repo/pull/7",
                    }
                ]
            ),
            (
                "gh",
                "pr",
                "view",
                "7",
                "--repo",
                "example/repo",
                "--json",
                "headRefName,headRefOid,mergeStateStatus,statusCheckRollup,title,updatedAt,url",
            ): json.dumps(
                {
                    "headRefName": "fix-ci",
                    "headRefOid": "abc123",
                    "mergeStateStatus": "UNSTABLE",
                    "title": "Fix CI",
                    "updatedAt": "2026-04-15T18:00:00Z",
                    "url": "https://github.com/example/repo/pull/7",
                    "statusCheckRollup": [
                        {
                            "__typename": "CheckRun",
                            "name": "build-linux",
                            "status": "COMPLETED",
                            "conclusion": "FAILURE",
                            "workflowName": "Python Package CI",
                        },
                        {
                            "__typename": "CheckRun",
                            "name": "lint",
                            "status": "IN_PROGRESS",
                            "conclusion": "",
                            "workflowName": "Lint",
                        },
                        {
                            "__typename": "CheckRun",
                            "name": "run-fuzzers",
                            "status": "COMPLETED",
                            "conclusion": "FAILURE",
                            "workflowName": "OSS-Fuzz",
                        },
                    ],
                }
            ),
        }

        def runner(argv: list[str]) -> str:
            return responses[tuple(argv)]

        snapshot = GitHubCli(runner=runner).list_open_pull_requests("example/repo")[0]
        self.assertEqual(snapshot.head_ref_name, "fix-ci")
        self.assertEqual(snapshot.failing_checks(("build-linux",)), ("build-linux",))
        self.assertEqual(snapshot.failing_checks(("oss-fuzz",)), ("run-fuzzers",))
        self.assertEqual(snapshot.pending_checks(("lint",)), ("lint",))

    def test_list_open_pull_requests_applies_author_filter(self) -> None:
        expected = (
            "gh",
            "pr",
            "list",
            "--repo",
            "example/repo",
            "--state",
            "open",
            "--author",
            "0ai-Cyberviser",
            "--json",
            "number,title,updatedAt,url",
        )
        responses = {
            expected: "[]",
        }

        def runner(argv: list[str]) -> str:
            return responses[tuple(argv)]

        snapshots = GitHubCli(runner=runner).list_open_pull_requests(
            "example/repo",
            authors=("0ai-Cyberviser",),
        )
        self.assertEqual(snapshots, ())

    def test_list_open_pull_requests_merges_multiple_authors(self) -> None:
        responses = {
            (
                "gh",
                "pr",
                "list",
                "--repo",
                "example/repo",
                "--state",
                "open",
                "--author",
                "0ai-Cyberviser",
                "--json",
                "number,title,updatedAt,url",
            ): json.dumps(
                [
                    {
                        "number": 7,
                        "title": "Fix CI",
                        "updatedAt": "2026-04-15T18:00:00Z",
                        "url": "https://github.com/example/repo/pull/7",
                    }
                ]
            ),
            (
                "gh",
                "pr",
                "list",
                "--repo",
                "example/repo",
                "--state",
                "open",
                "--author",
                "app/copilot-swe-agent",
                "--json",
                "number,title,updatedAt,url",
            ): json.dumps(
                [
                    {
                        "number": 7,
                        "title": "Fix CI",
                        "updatedAt": "2026-04-15T18:00:00Z",
                        "url": "https://github.com/example/repo/pull/7",
                    },
                    {
                        "number": 8,
                        "title": "Fix fuzzing",
                        "updatedAt": "2026-04-15T19:00:00Z",
                        "url": "https://github.com/example/repo/pull/8",
                    },
                ]
            ),
            (
                "gh",
                "pr",
                "view",
                "8",
                "--repo",
                "example/repo",
                "--json",
                "headRefName,headRefOid,mergeStateStatus,statusCheckRollup,title,updatedAt,url",
            ): json.dumps(
                {
                    "headRefName": "fix-fuzzing",
                    "headRefOid": "def456",
                    "mergeStateStatus": "UNSTABLE",
                    "title": "Fix fuzzing",
                    "updatedAt": "2026-04-15T19:00:00Z",
                    "url": "https://github.com/example/repo/pull/8",
                    "statusCheckRollup": [],
                }
            ),
            (
                "gh",
                "pr",
                "view",
                "7",
                "--repo",
                "example/repo",
                "--json",
                "headRefName,headRefOid,mergeStateStatus,statusCheckRollup,title,updatedAt,url",
            ): json.dumps(
                {
                    "headRefName": "fix-ci",
                    "headRefOid": "abc123",
                    "mergeStateStatus": "UNSTABLE",
                    "title": "Fix CI",
                    "updatedAt": "2026-04-15T18:00:00Z",
                    "url": "https://github.com/example/repo/pull/7",
                    "statusCheckRollup": [],
                }
            ),
        }

        def runner(argv: list[str]) -> str:
            return responses[tuple(argv)]

        snapshots = GitHubCli(runner=runner).list_open_pull_requests(
            "example/repo",
            authors=("0ai-Cyberviser", "app/copilot-swe-agent"),
        )
        self.assertEqual(tuple(snapshot.number for snapshot in snapshots), (8, 7))
        self.assertEqual(len(snapshots), 2)


if __name__ == "__main__":
    unittest.main()
