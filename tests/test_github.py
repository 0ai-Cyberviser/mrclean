from __future__ import annotations

import json
import unittest

from mrclean.github import GitHubCli


class GitHubCliTests(unittest.TestCase):
    def test_list_open_pull_requests_parses_checks(self) -> None:
        responses = {
            (
                "gh",
                "search",
                "prs",
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


if __name__ == "__main__":
    unittest.main()
