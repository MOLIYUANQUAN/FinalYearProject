"""云上确认部署：草稿先标成可审查，再合并。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("CURSOR_REPO_URL", "https://github.com/MOLIYUANQUAN/FinalYearProject")
os.environ.setdefault("CURSOR_REPO_REF", "develop")

from src import ship  # noqa: E402


def _response(status: int, payload: dict | list | None = None, text: str = "") -> MagicMock:
    res = MagicMock()
    res.status_code = status
    res.ok = status < 400
    res.text = text or ("" if payload is None else str(payload))
    res.json.return_value = {} if payload is None else payload
    return res


class MergeDraftTests(unittest.TestCase):
    def test_existing_draft_is_marked_ready_before_merge(self) -> None:
        draft = {
            "number": 3,
            "draft": True,
            "node_id": "PR_node",
        }
        calls: list[tuple[str, str]] = []

        def post(url, **kwargs):
            calls.append(("POST", url))
            if url.endswith("/pulls"):
                return _response(422, {"message": "A pull request already exists"}, text="already exists")
            raise AssertionError(url)

        def get(url, **kwargs):
            calls.append(("GET", url))
            return _response(200, [draft])

        def do_patch(url, **kwargs):
            calls.append(("PATCH", url))
            self.assertEqual(kwargs["json"], {"draft": False})
            return _response(200, {**draft, "draft": False})

        def put(url, **kwargs):
            calls.append(("PUT", url))
            self.assertTrue(url.endswith("/pulls/3/merge"))
            return _response(200, {"merged": True})

        with patch.object(ship.requests, "post", side_effect=post), patch.object(
            ship.requests, "get", side_effect=get
        ), patch.object(ship.requests, "patch", side_effect=do_patch), patch.object(
            ship.requests, "put", side_effect=put
        ):
            result = ship._merge_github("cursor/friday-friction-b5f73526-25cf")

        self.assertTrue(result["ok"])
        self.assertEqual(result["pr"], 3)
        kinds = [kind for kind, _ in calls]
        self.assertLess(kinds.index("PATCH"), kinds.index("PUT"))

    def test_ready_pr_is_merged_without_patch(self) -> None:
        created = {"number": 9, "draft": False, "node_id": "PR_ready"}

        with patch.object(ship.requests, "post", return_value=_response(201, created)), patch.object(
            ship.requests, "patch", side_effect=AssertionError("should not undraft")
        ), patch.object(ship.requests, "put", return_value=_response(200, {"merged": True})) as put:
            result = ship._merge_github("feature/chat-dialog-ui")

        self.assertTrue(result["ok"])
        put.assert_called_once()

    def test_graphql_fallback_when_patch_rejects_draft(self) -> None:
        draft = {"number": 3, "draft": True, "node_id": "PR_node"}
        calls: list[str] = []

        def post(url, **kwargs):
            calls.append(url)
            if url.endswith("/pulls"):
                return _response(201, draft)
            if url.endswith("/graphql"):
                self.assertEqual(kwargs["json"]["variables"]["id"], "PR_node")
                return _response(200, {"data": {"markPullRequestReadyForReview": {"pullRequest": {"isDraft": False}}}})
            raise AssertionError(url)

        with patch.object(ship.requests, "post", side_effect=post), patch.object(
            ship.requests, "patch", return_value=_response(422, text='{"message":"draft is invalid"}')
        ), patch.object(ship.requests, "put", return_value=_response(200, {"merged": True})):
            result = ship._merge_github("cursor/some-branch")

        self.assertTrue(result["ok"])
        self.assertTrue(any(url.endswith("/graphql") for url in calls))

    def test_cloud_deploy_miss_tells_user_github_is_deploying(self) -> None:
        pending = {"branch": "cursor/friday-friction-b5f73526-25cf", "friction_id": ""}
        with patch.object(ship, "load_or_recover_pending", return_value=pending), patch.object(
            ship, "_merge_local", return_value={"ok": False, "error": "no_git"}
        ), patch.object(
            ship, "_merge_github", return_value={"ok": True, "method": "github_api", "pr": 3}
        ), patch.object(
            ship,
            "_deploy",
            return_value={"ok": False, "error": "deploy_failed", "message": "flyctl not found. In PowerShell:"},
        ), patch.object(ship, "clear_pending"), patch.object(ship.friction, "resolve"):
            result = ship.ship(user_confirmed=True)

        self.assertTrue(result["ok"])
        self.assertIn("GitHub 正在自动部署", result["say"])
        self.assertNotIn("flyctl", result["say"])


if __name__ == "__main__":
    unittest.main()
