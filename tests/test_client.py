"""Unit tests for LinearClient — all httpx calls are mocked."""
from unittest.mock import MagicMock, patch

import pytest

from linear_mcp.client import LinearClient, LinearError


def make_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"data": data}
    resp.raise_for_status = MagicMock()
    if status >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "", request=MagicMock(), response=resp
        )
    return resp


def make_error_response(message: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"errors": [{"message": message}]}
    resp.raise_for_status = MagicMock()
    return resp


def make_rate_limit_response(retry_after: int = 5) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": str(retry_after)}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def client():
    with patch("linear_mcp.client.httpx.Client") as mock_cls:
        mock_http = MagicMock()
        mock_cls.return_value = mock_http
        c = LinearClient("lin_api_test")
        c._http = mock_http
        yield c, mock_http


class TestGetViewer:
    def test_returns_viewer(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@x.com"}}
        )
        result = c.get_viewer()
        assert result == {"id": "u1", "name": "Alice", "email": "a@x.com"}

    def test_graphql_error_raises(self, client):
        c, http = client
        http.post.return_value = make_error_response("Unauthorized")
        with pytest.raises(LinearError, match="Unauthorized"):
            c.get_viewer()


class TestListIssues:
    def test_no_filters_sends_null_filter(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues()
        payload = http.post.call_args[1]["json"]
        # filter variable must be None, not an f-string fragment
        assert payload["variables"]["filter"] is None

    def test_team_filter_uses_variable(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(team_id="team-abc")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] == {"team": {"id": {"eq": "team-abc"}}}

    def test_state_with_quotes_does_not_break_query(self, client):
        """Regression: f-string injection would have broken this."""
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        # A state name with a double-quote would break f-string interpolation
        c.list_issues(state='In "Progress"')
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"]["state"] == {"name": {"eq": 'In "Progress"'}}

    def test_limit_is_passed(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(limit=10)
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["first"] == 10


class TestListProjects:
    def test_no_filter_sends_null(self, client):
        c, http = client
        http.post.return_value = make_response({"projects": {"nodes": []}})
        c.list_projects()
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] is None

    def test_team_filter_uses_variable(self, client):
        c, http = client
        http.post.return_value = make_response({"projects": {"nodes": []}})
        c.list_projects(team_id="team-xyz")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] == {"teams": {"id": {"eq": "team-xyz"}}}


class TestWorkflowStates:
    def test_sorted_by_position(self, client):
        c, http = client
        states = [
            {"id": "s3", "name": "Done", "position": 3},
            {"id": "s1", "name": "Backlog", "position": 1},
            {"id": "s2", "name": "In Progress", "position": 2},
        ]
        http.post.return_value = make_response({"workflowStates": {"nodes": states}})
        result = c.list_workflow_states("team-1")
        assert [s["name"] for s in result] == ["Backlog", "In Progress", "Done"]


class TestRateLimiting:
    def test_retries_on_429_then_succeeds(self, client):
        c, http = client
        rate_limited = make_rate_limit_response(retry_after=0)
        success = make_response({"viewer": {"id": "u1", "name": "A", "email": "a@x.com"}})
        http.post.side_effect = [rate_limited, success]

        with patch("linear_mcp.client.time.sleep") as mock_sleep:
            result = c.get_viewer()

        mock_sleep.assert_called_once_with(0)
        assert result["id"] == "u1"

    def test_raises_after_max_retries(self, client):
        c, http = client
        http.post.return_value = make_rate_limit_response(retry_after=1)

        with patch("linear_mcp.client.time.sleep"):
            with pytest.raises(LinearError, match="Rate limited"):
                c.get_viewer()


class TestGetMyIssues:
    def test_calls_get_viewer_then_list_issues(self, client):
        c, http = client
        issue = {"id": "i1", "identifier": "ENG-1", "title": "Fix bug"}
        http.post.side_effect = [
            make_response({"viewer": {"id": "user-1", "name": "Alice", "email": "a@x.com"}}),
            make_response({"issues": {"nodes": [issue]}}),
        ]
        result = c.get_my_issues()
        assert result == [issue]
        # Second call should have assignee filter
        second_payload = http.post.call_args_list[1][1]["json"]
        assert second_payload["variables"]["filter"]["assignee"] == {"id": {"eq": "user-1"}}


class TestArchiveIssue:
    def test_returns_true_on_success(self, client):
        c, http = client
        http.post.return_value = make_response({"issueArchive": {"success": True}})
        assert c.archive_issue("issue-1") is True


class TestDeleteIssue:
    def test_returns_true_on_success(self, client):
        c, http = client
        http.post.return_value = make_response({"issueDelete": {"success": True}})
        assert c.delete_issue("issue-1") is True


class TestCreateIssue:
    def test_raises_on_success_false(self, client):
        c, http = client
        http.post.return_value = make_response({"issueCreate": {"success": False, "issue": None}})
        with pytest.raises(LinearError, match="success=false"):
            c.create_issue("team-1", "Test")

    def test_label_ids_included_in_input(self, client):
        c, http = client
        http.post.return_value = make_response({
            "issueCreate": {
                "success": True,
                "issue": {"id": "i1", "identifier": "ENG-1", "title": "X",
                          "priority": 0, "state": {"name": "Todo"},
                          "team": {"name": "Eng", "key": "ENG"},
                          "labels": {"nodes": []}},
            }
        })
        c.create_issue("team-1", "Test", label_ids=["label-a", "label-b"])
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["labelIds"] == ["label-a", "label-b"]


class TestUpdateIssue:
    def test_raises_with_no_fields(self, client):
        c, http = client
        with pytest.raises(ValueError, match="no fields"):
            c.update_issue("issue-1")


class TestGetCurrentCycle:
    def test_returns_active_cycle(self, client):
        c, http = client
        cycles = [
            {
                "id": "cycle-1", "number": 1, "name": "Sprint 1",
                "startsAt": "2020-01-01T00:00:00Z",
                "endsAt": "2099-12-31T00:00:00Z",
                "completedAt": None,
                "issues": {"totalCount": 5},
            }
        ]
        http.post.return_value = make_response({"team": {"cycles": {"nodes": cycles}}})
        result = c.get_current_cycle("team-1")
        assert result["id"] == "cycle-1"

    def test_returns_none_when_completed(self, client):
        c, http = client
        cycles = [
            {
                "id": "cycle-1", "number": 1, "name": "Sprint 1",
                "startsAt": "2020-01-01T00:00:00Z",
                "endsAt": "2020-01-14T00:00:00Z",
                "completedAt": "2020-01-14T00:00:00Z",
                "issues": {"totalCount": 3},
            }
        ]
        http.post.return_value = make_response({"team": {"cycles": {"nodes": cycles}}})
        result = c.get_current_cycle("team-1")
        assert result is None

    def test_returns_none_when_no_cycles(self, client):
        c, http = client
        http.post.return_value = make_response({"team": {"cycles": {"nodes": []}}})
        result = c.get_current_cycle("team-1")
        assert result is None


class TestListLabels:
    def test_returns_all_labels_without_filter(self, client):
        c, http = client
        labels = [
            {"id": "l1", "name": "Bug", "color": "#red", "team": {"id": "t1"}},
            {"id": "l2", "name": "Feature", "color": "#blue", "team": {"id": "t2"}},
        ]
        http.post.return_value = make_response({"issueLabels": {"nodes": labels}})
        result = c.list_labels()
        assert len(result) == 2
        # team field should be stripped
        assert "team" not in result[0]

    def test_filters_by_team_id(self, client):
        c, http = client
        labels = [
            {"id": "l1", "name": "Bug", "color": "#red", "team": {"id": "t1"}},
            {"id": "l2", "name": "Feature", "color": "#blue", "team": {"id": "t2"}},
        ]
        http.post.return_value = make_response({"issueLabels": {"nodes": labels}})
        result = c.list_labels(team_id="t1")
        assert len(result) == 1
        assert result[0]["name"] == "Bug"
