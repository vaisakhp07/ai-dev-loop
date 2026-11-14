"""Regression tests for GitHub CodeRabbit check-run and review-thread gating."""
import unittest
from unittest.mock import patch

import agent


class ReviewSnapshotTests(unittest.TestCase):
    SHA = "sha-current"
    EXPECTED_CLEAR = (
        "clear",
        "CodeRabbit check passed for current HEAD; no unresolved CodeRabbit threads",
    )

    def check(self, *, name="CodeRabbit", app="coderabbitai", sha=None,
              status="completed", conclusion="success", id=1,
              started_at="2026-11-14T00:00:00Z"):
        return {
            "name": name, "app": {"slug": app},
            "head_sha": sha if sha is not None else self.SHA,
            "status": status, "conclusion": conclusion,
            "id": id, "started_at": started_at,
        }

    def snapshot(self, checks, threads=None):
        with patch.object(agent, "gh_json", return_value={"check_runs": checks}) as api:
            with patch.object(agent, "pr_threads", return_value=threads or []) as pr:
                result = agent.review_snapshot("owner", "repo", 4, self.SHA)
                if result[0] == "clear" or result[0] == "issues":
                    pr.assert_called_once_with("owner", "repo", 4)
                return result, api.call_args.args

    def thread(self, *, resolved=False, outdated=False, comments=None):
        if comments is None:
            comments = [{"author": {"login": "coderabbitai"}, "body": "original finding"}]
        return {"isResolved": resolved, "isOutdated": outdated,
                "comments": {"nodes": comments}}

    def test_current_commit_success_and_get_method(self):
        result, args = self.snapshot([self.check()])
        self.assertEqual(result, self.EXPECTED_CLEAR)
        self.assertIn("--method", args)
        self.assertIn("GET", args)
        self.assertIn("per_page=100", args)

    def test_ignores_other_apps_names_and_shas(self):
        checks = [
            self.check(name="Other"),
            self.check(app="otherbot"),
            self.check(sha="old-sha"),
        ]
        result, _ = self.snapshot(checks)
        self.assertEqual(result[0], "pending")
        self.assertIn("No CodeRabbit check", result[1])

    def test_selects_latest_matching_check(self):
        checks = [
            self.check(id=2, started_at="2026-11-14T01:00:00Z", conclusion="success"),
            self.check(id=1, started_at="2026-11-14T00:00:00Z", conclusion="failure"),
            self.check(id=3, sha="old-sha", started_at="2026-11-14T02:00:00Z", conclusion="failure"),
        ]
        result, _ = self.snapshot(checks)
        self.assertEqual(result, self.EXPECTED_CLEAR)

    def test_no_check_is_pending(self):
        self.assertEqual(self.snapshot([])[0][0], "pending")

    def test_incomplete_check_is_pending(self):
        for status in ("queued", "in_progress"):
            with self.subTest(status=status):
                self.assertEqual(self.snapshot([self.check(status=status, conclusion=None)])[0][0], "pending")

    def test_failed_completed_checks_are_blocked(self):
        for conclusion in ("failure", "timed_out", "cancelled"):
            with self.subTest(conclusion=conclusion):
                result, _ = self.snapshot([self.check(conclusion=conclusion)])
                self.assertEqual(result, ("blocked", f"CodeRabbit: {conclusion}"))

    def test_other_non_success_conclusions_are_pending(self):
        for conclusion in ("neutral", "skipped", "blocked", None):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(self.snapshot([self.check(conclusion=conclusion)])[0][0], "pending")

    def test_unresolved_outdated_threads_are_included(self):
        result, _ = self.snapshot([self.check()], [self.thread(outdated=True)])
        self.assertEqual(result[0], "issues")
        self.assertIn("original finding", result[1])

    def test_resolved_threads_are_excluded(self):
        result, _ = self.snapshot([self.check()], [self.thread(resolved=True)])
        self.assertEqual(result, self.EXPECTED_CLEAR)

    def test_non_coderabbit_threads_are_not_blockers(self):
        comment = {"author": {"login": "human"}, "body": "human note"}
        result, _ = self.snapshot([self.check()], [self.thread(comments=[comment])])
        self.assertEqual(result, self.EXPECTED_CLEAR)

    def test_original_finding_survives_many_replies(self):
        comments = [{"author": {"login": "coderabbitai"}, "body": "original finding"}]
        comments.extend(
            {"author": {"login": "human"}, "body": f"reply {i}"}
            for i in range(5)
        )
        result, _ = self.snapshot([self.check()], [self.thread(comments=comments)])
        self.assertEqual(result[0], "issues")
        self.assertIn("original finding", result[1])
        self.assertIn("reply 4", result[1])


if __name__ == "__main__":
    unittest.main()
