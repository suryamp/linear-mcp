"""Unit tests for LinearClient — all httpx calls are mocked."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from linear_mcp.client import LinearClient, LinearError

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.is_success = status < 400
    resp.json.return_value = {"data": data}
    resp.raise_for_status = MagicMock()
    resp.text = ""
    return resp


def make_error_response(message: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.is_success = True
    resp.json.return_value = {"errors": [{"message": message}]}
    resp.raise_for_status = MagicMock()
    resp.text = ""
    return resp


def make_http_error_response(status: int, body: str = "error") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.is_success = False
    resp.text = body
    resp.raise_for_status = MagicMock()
    return resp


def make_rate_limit_response(retry_after: int = 5) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 429
    resp.is_success = False
    resp.headers = {"Retry-After": str(retry_after)}
    resp.raise_for_status = MagicMock()
    return resp


def _issue_stub(**overrides) -> dict:
    """Minimal issue dict for update/create responses."""
    base = {
        "id": "i1", "identifier": "ENG-1", "title": "T",
        "priority": 0, "dueDate": None,
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
    }
    base.update(overrides)
    return base


def _full_issue_stub(**overrides) -> dict:
    """Minimal full issue dict for get_issue responses."""
    base = {
        "id": "i1", "identifier": "ENG-1", "title": "X", "description": None,
        "priority": 0, "dueDate": None,
        "state": {"name": "Todo"}, "assignee": None,
        "team": {"id": "t1", "name": "Eng", "key": "ENG"},
        "project": None, "parent": None,
        "labels": {"nodes": []},
        "relations": {"nodes": []},
        "comments": {"nodes": []},
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


@pytest.fixture
def client():
    with patch("linear_mcp.client.httpx.Client") as mock_cls:
        mock_http = MagicMock()
        mock_cls.return_value = mock_http
        c = LinearClient("lin_api_test")
        c._http = mock_http
        yield c, mock_http


# ── Identity & caching ────────────────────────────────────────────────────────

class TestGetViewer:
    def test_returns_viewer(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@x.com"}}
        )
        result = c.get_viewer()
        assert result == {"id": "u1", "name": "Alice", "email": "a@x.com"}

    def test_caches_viewer_id(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@x.com"}}
        )
        assert c._viewer_id is None
        c.get_viewer()
        assert c._viewer_id == "u1"

    def test_graphql_error_raises(self, client):
        c, http = client
        http.post.return_value = make_error_response("Unauthorized")
        with pytest.raises(LinearError, match="Unauthorized"):
            c.get_viewer()


class TestGetMyIssues:
    def test_fetches_viewer_then_issues_on_first_call(self, client):
        c, http = client
        issue = {"id": "i1", "identifier": "ENG-1", "title": "Fix bug"}
        http.post.side_effect = [
            make_response({"viewer": {"id": "user-1", "name": "Alice", "email": "a@x.com"}}),
            make_response({"issues": {"nodes": [issue]}}),
        ]
        result = c.get_my_issues()
        assert result == [issue]
        second_payload = http.post.call_args_list[1][1]["json"]
        assert second_payload["variables"]["filter"]["assignee"] == {"id": {"eq": "user-1"}}

    def test_uses_cached_viewer_id_on_subsequent_calls(self, client):
        c, http = client
        issue = {"id": "i1", "identifier": "ENG-1", "title": "Fix bug"}
        http.post.side_effect = [
            make_response({"viewer": {"id": "user-1", "name": "Alice", "email": "a@x.com"}}),
            make_response({"issues": {"nodes": [issue]}}),
            make_response({"issues": {"nodes": [issue]}}),
        ]
        c.get_my_issues()
        c.get_my_issues()
        # Only 3 total calls: 1 viewer fetch + 2 issue fetches (not 4)
        assert http.post.call_count == 3


# ── Query error handling ──────────────────────────────────────────────────────

class TestQueryErrorHandling:
    def test_http_4xx_raises_linear_error(self, client):
        c, http = client
        http.post.return_value = make_http_error_response(401, "Unauthorized")
        with pytest.raises(LinearError, match="HTTP 401"):
            c.get_viewer()

    def test_http_500_raises_linear_error(self, client):
        c, http = client
        http.post.return_value = make_http_error_response(500, "Internal Server Error")
        with pytest.raises(LinearError, match="HTTP 500"):
            c.get_viewer()

    def test_network_error_raises_linear_error(self, client):
        c, http = client
        http.post.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(LinearError, match="Network error"):
            c.get_viewer()

    def test_graphql_error_with_no_data_raises(self, client):
        c, http = client
        http.post.return_value = make_error_response("Not found")
        with pytest.raises(LinearError, match="Not found"):
            c.get_viewer()

    def test_partial_response_with_data_and_errors_returns_data(self, client):
        """If data is present alongside errors, return data and only log the error."""
        c, http = client
        resp = MagicMock()
        resp.status_code = 200
        resp.is_success = True
        resp.json.return_value = {
            "data": {"viewer": {"id": "u1", "name": "Alice", "email": "a@x.com"}},
            "errors": [{"message": "some field failed"}],
        }
        resp.raise_for_status = MagicMock()
        http.post.return_value = resp
        result = c.get_viewer()
        assert result == {"id": "u1", "name": "Alice", "email": "a@x.com"}


class TestTimeoutRetry:
    def test_query_retries_on_timeout(self, client):
        """Read-only queries should retry once on timeout."""
        c, http = client
        success = make_response({"viewer": {"id": "u1", "name": "Alice", "email": "a@x.com"}})
        http.post.side_effect = [httpx.TimeoutException("timed out"), success]
        result = c.get_viewer()
        assert result["id"] == "u1"
        assert http.post.call_count == 2

    def test_query_raises_after_max_retries_on_timeout(self, client):
        c, http = client
        http.post.side_effect = httpx.TimeoutException("timed out")
        with pytest.raises(LinearError, match="timed out"):
            c.get_viewer()
        assert http.post.call_count == 3  # initial + 2 retries

    def test_mutation_does_not_retry_on_timeout(self, client):
        """Mutations must not retry on timeout — they may have already committed."""
        c, http = client
        http.post.side_effect = httpx.TimeoutException("timed out")
        with pytest.raises(LinearError, match="timed out"):
            c.create_issue("team-1", "Test")
        assert http.post.call_count == 1  # no retry


# ── Rate limiting ─────────────────────────────────────────────────────────────

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

    def test_http_date_retry_after_falls_back_to_5(self, client):
        """RFC 7231 allows Retry-After to be an HTTP-date string; int() crashes on it."""
        c, http = client
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.is_success = False
        rate_limited.headers = {"Retry-After": "Mon, 01 Jun 2026 00:00:00 GMT"}
        success = make_response({"viewer": {"id": "u1", "name": "A", "email": "a@x.com"}})
        http.post.side_effect = [rate_limited, success]

        with patch("linear_mcp.client.time.sleep") as mock_sleep:
            result = c.get_viewer()

        mock_sleep.assert_called_once_with(5)
        assert result["id"] == "u1"


# ── List issues ───────────────────────────────────────────────────────────────

class TestListIssues:
    def test_no_filters_sends_null_filter(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues()
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] is None

    def test_team_filter(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(team_id="team-abc")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] == {"team": {"id": {"eq": "team-abc"}}}

    def test_priority_filter(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(priority=2)
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] == {"priority": {"eq": 2}}

    def test_label_name_filter(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(label_name="bug")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] == {"labels": {"name": {"eq": "bug"}}}

    def test_updated_after_filter(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(updated_after="2026-06-01T00:00:00Z")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"] == {"updatedAt": {"gte": "2026-06-01T00:00:00Z"}}

    def test_filters_compose(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(team_id="t1", state="In Progress", priority=1)
        payload = http.post.call_args[1]["json"]
        f = payload["variables"]["filter"]
        assert f["team"] == {"id": {"eq": "t1"}}
        assert f["state"] == {"name": {"eq": "In Progress"}}
        assert f["priority"] == {"eq": 1}

    def test_state_with_quotes_is_safe(self, client):
        """Regression: f-string injection would have broken this."""
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(state='In "Progress"')
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["filter"]["state"] == {"name": {"eq": 'In "Progress"'}}

    def test_limit_is_passed(self, client):
        c, http = client
        http.post.return_value = make_response({"issues": {"nodes": []}})
        c.list_issues(limit=10)
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["first"] == 10


# ── Get issue ─────────────────────────────────────────────────────────────────

class TestGetIssue:
    def test_returns_issue(self, client):
        c, http = client
        issue = _full_issue_stub()
        http.post.return_value = make_response({"issue": issue})
        assert c.get_issue("ENG-1") == issue

    def test_not_found_raises_linear_error(self, client):
        c, http = client
        http.post.return_value = make_response({"issue": None})
        with pytest.raises(LinearError, match="not found"):
            c.get_issue("ENG-999")

    def test_query_includes_relations(self, client):
        c, http = client
        http.post.return_value = make_response({"issue": _full_issue_stub()})
        c.get_issue("ENG-1")
        query = http.post.call_args[1]["json"]["query"]
        assert "relations" in query


# ── Search issues ────────────────────────────────────────────────────────────

class TestSearchIssues:
    def _search_response(self) -> MagicMock:
        nodes = [{"id": "i1", "identifier": "ENG-1", "title": "Login bug"}]
        return make_response({"issues": {"nodes": nodes}})

    def test_returns_matching_issues(self, client):
        c, http = client
        http.post.return_value = self._search_response()
        result = c.search_issues("Login")
        assert result[0]["title"] == "Login bug"

    def test_uses_issues_query_not_deprecated_issueSearch(self, client):
        c, http = client
        http.post.return_value = self._search_response()
        c.search_issues("Login")
        query = http.post.call_args[1]["json"]["query"]
        assert "issueSearch" not in query
        assert "issues" in query

    def test_filter_uses_or_across_title_and_description(self, client):
        c, http = client
        http.post.return_value = self._search_response()
        c.search_issues("Login")
        variables = http.post.call_args[1]["json"]["variables"]
        conditions = variables["filter"]["or"]
        keys = {list(c.keys())[0] for c in conditions}
        assert "title" in keys
        assert "description" in keys


# ── Members ───────────────────────────────────────────────────────────────────

class TestListMembers:
    def test_returns_members(self, client):
        c, http = client
        members = [{"id": "u1", "name": "Alice", "email": "a@x.com"}]
        http.post.return_value = make_response({"team": {"members": {"nodes": members}}})
        assert c.list_members("team-1") == members

    def test_team_not_found_raises(self, client):
        c, http = client
        http.post.return_value = make_response({"team": None})
        with pytest.raises(LinearError, match="not found"):
            c.list_members("bad-team-id")

    def test_query_includes_first_500(self, client):
        c, http = client
        http.post.return_value = make_response({"team": {"members": {"nodes": []}}})
        c.list_members("team-1")
        query = http.post.call_args[1]["json"]["query"]
        assert "500" in query


# ── Workflow states ───────────────────────────────────────────────────────────

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


# ── Create issue ──────────────────────────────────────────────────────────────

class TestCreateIssue:
    def _make_create_response(self, **overrides) -> MagicMock:
        issue = {
            "id": "i1", "identifier": "ENG-1", "title": "X",
            "priority": 0, "dueDate": None,
            "state": {"name": "Todo"}, "team": {"name": "Eng", "key": "ENG"},
            "parent": None, "labels": {"nodes": []},
        }
        issue.update(overrides)
        return make_response({"issueCreate": {"success": True, "issue": issue}})

    def test_raises_on_success_false(self, client):
        c, http = client
        http.post.return_value = make_response({"issueCreate": {"success": False, "issue": None}})
        with pytest.raises(LinearError, match="success=false"):
            c.create_issue("team-1", "Test")

    def test_label_ids_in_input(self, client):
        c, http = client
        http.post.return_value = self._make_create_response()
        c.create_issue("team-1", "Test", label_ids=["l-a", "l-b"])
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["labelIds"] == ["l-a", "l-b"]

    def test_parent_id_in_input(self, client):
        c, http = client
        http.post.return_value = self._make_create_response(
            parent={"id": "i0", "identifier": "ENG-0", "title": "Parent"}
        )
        c.create_issue("team-1", "Sub-task", parent_id="i0")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["parentId"] == "i0"

    def test_due_date_in_input(self, client):
        c, http = client
        http.post.return_value = self._make_create_response(dueDate="2026-06-30")
        c.create_issue("team-1", "Test", due_date="2026-06-30")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["dueDate"] == "2026-06-30"

    def test_optional_fields_omitted_when_none(self, client):
        c, http = client
        http.post.return_value = self._make_create_response()
        c.create_issue("team-1", "Minimal")
        payload = http.post.call_args[1]["json"]
        for field in ("parentId", "labelIds", "description", "dueDate"):
            assert field not in payload["variables"]["input"]


# ── Update issue ──────────────────────────────────────────────────────────────

class TestUpdateIssue:
    def test_raises_with_no_fields(self, client):
        c, http = client
        with pytest.raises(ValueError, match="no fields"):
            c.update_issue("issue-1")

    def test_success_returns_issue(self, client):
        c, http = client
        updated = _issue_stub(title="Updated", priority=2, state={"name": "In Progress"})
        http.post.return_value = make_response({"issueUpdate": {"success": True, "issue": updated}})
        result = c.update_issue("i1", title="Updated")
        assert result["title"] == "Updated"

    def test_cycle_id_in_input(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.update_issue("i1", cycle_id="cycle-99")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["cycleId"] == "cycle-99"

    def test_due_date_in_input(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.update_issue("i1", due_date="2026-07-01")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["dueDate"] == "2026-07-01"

    def test_due_date_empty_string_sends_null(self, client):
        """due_date='' must send dueDate: null to clear the field, not skip it."""
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.update_issue("i1", due_date="")
        payload = http.post.call_args[1]["json"]
        assert "dueDate" in payload["variables"]["input"]
        assert payload["variables"]["input"]["dueDate"] is None

    def test_due_date_none_omits_field(self, client):
        """due_date=None (the default) must leave dueDate out of the payload entirely."""
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.update_issue("i1", title="X")
        payload = http.post.call_args[1]["json"]
        assert "dueDate" not in payload["variables"]["input"]

    def test_raises_on_success_false(self, client):
        c, http = client
        http.post.return_value = make_response({"issueUpdate": {"success": False, "issue": None}})
        with pytest.raises(LinearError, match="success=false"):
            c.update_issue("i1", title="X")


# ── _update_issue_fields (internal) ──────────────────────────────────────────

class TestUpdateIssueFields:
    def test_none_value_sent_as_null(self, client):
        """_update_issue_fields must include None in the payload (maps to JSON null)."""
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c._update_issue_fields("i1", {"assigneeId": None})
        payload = http.post.call_args[1]["json"]
        assert "assigneeId" in payload["variables"]["input"]
        assert payload["variables"]["input"]["assigneeId"] is None

    def test_raises_on_empty_input(self, client):
        c, http = client
        with pytest.raises(ValueError, match="empty input_data"):
            c._update_issue_fields("i1", {})


# ── Unassign ──────────────────────────────────────────────────────────────────

class TestUnassignIssue:
    def test_sends_assignee_id_null(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.unassign_issue("i1")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"] == {"assigneeId": None}


# ── Archive / delete ──────────────────────────────────────────────────────────

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


# ── Issue relations ───────────────────────────────────────────────────────────

class TestIssueRelations:
    def test_create_relation_success(self, client):
        c, http = client
        relation = {
            "id": "r1", "type": "blocks",
            "relatedIssue": {"id": "i2", "identifier": "ENG-2", "title": "Other"},
        }
        http.post.return_value = make_response(
            {"issueRelationCreate": {"success": True, "issueRelation": relation}}
        )
        result = c.create_issue_relation("i1", "i2", "blocks")
        assert result["type"] == "blocks"
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["type"] == "blocks"

    def test_create_relation_raises_on_success_false(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueRelationCreate": {"success": False, "issueRelation": None}}
        )
        with pytest.raises(LinearError, match="success=false"):
            c.create_issue_relation("i1", "i2", "related")

    def test_delete_relation_success(self, client):
        c, http = client
        http.post.return_value = make_response({"issueRelationDelete": {"success": True}})
        assert c.delete_issue_relation("r1") is True

    def test_relation_type_is_passed_through(self, client):
        c, http = client
        relation = {
            "id": "r1", "type": "duplicate",
            "relatedIssue": {"id": "i2", "identifier": "ENG-2", "title": "Dup"},
        }
        http.post.return_value = make_response(
            {"issueRelationCreate": {"success": True, "issueRelation": relation}}
        )
        c.create_issue_relation("i1", "i2", "duplicate")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"] == {
            "issueId": "i1",
            "relatedIssueId": "i2",
            "type": "duplicate",
        }


# ── Comments ──────────────────────────────────────────────────────────────────

class TestAddComment:
    def test_returns_comment_on_success(self, client):
        c, http = client
        comment = {"id": "c1", "body": "Hello", "createdAt": "2024-01-01T00:00:00Z"}
        http.post.return_value = make_response(
            {"commentCreate": {"success": True, "comment": comment}}
        )
        assert c.add_comment("issue-1", "Hello") == comment

    def test_raises_on_success_false(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"commentCreate": {"success": False, "comment": None}}
        )
        with pytest.raises(LinearError, match="success=false"):
            c.add_comment("issue-1", "Hello")

    def test_issue_id_and_body_in_input(self, client):
        c, http = client
        comment = {"id": "c1", "body": "Test", "createdAt": "2024-01-01T00:00:00Z"}
        http.post.return_value = make_response(
            {"commentCreate": {"success": True, "comment": comment}}
        )
        c.add_comment("ENG-42", "Test")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"] == {"issueId": "ENG-42", "body": "Test"}


# ── Projects ──────────────────────────────────────────────────────────────────

class TestListProjects:
    def test_no_filter_returns_all_projects(self, client):
        c, http = client
        projects = [
            {"id": "p1", "name": "Alpha", "teams": {"nodes": [{"id": "t1", "name": "eng", "key": "ENG"}]}},  # noqa: E501
        ]
        http.post.return_value = make_response({"projects": {"nodes": projects}})
        result = c.list_projects()
        assert result == projects

    def test_team_filter_filters_client_side(self, client):
        c, http = client
        projects = [
            {"id": "p1", "name": "Match", "teams": {"nodes": [{"id": "team-xyz", "name": "x", "key": "X"}]}},  # noqa: E501
            {"id": "p2", "name": "No match", "teams": {"nodes": [{"id": "other", "name": "y", "key": "Y"}]}},  # noqa: E501
        ]
        http.post.return_value = make_response({"projects": {"nodes": projects}})
        result = c.list_projects(team_id="team-xyz")
        assert len(result) == 1
        assert result[0]["id"] == "p1"


# ── Labels ────────────────────────────────────────────────────────────────────

class TestListLabels:
    def test_returns_all_labels_without_filter(self, client):
        c, http = client
        labels = [{"id": "l1", "name": "Bug", "color": "#f00"}]
        http.post.return_value = make_response({"issueLabels": {"nodes": labels}})
        result = c.list_labels()
        assert result == labels

    def test_team_filter_uses_graphql_not_python(self, client):
        """Team filtering must happen in GraphQL, not in Python, to avoid truncation."""
        c, http = client
        labels = [{"id": "l1", "name": "Bug", "color": "#f00"}]
        http.post.return_value = make_response({"issueLabels": {"nodes": labels}})
        c.list_labels(team_id="t1")
        query = http.post.call_args[1]["json"]["query"]
        assert "filter" in query
        # Filter object must use OR to also include workspace-level labels (team: null).
        variables = http.post.call_args[1]["json"]["variables"]
        flt = variables.get("filter", {})
        assert "or" in flt, "filter must use OR to include workspace labels"
        branches = flt["or"]
        team_ids = [b["team"]["id"]["eq"] for b in branches if "id" in b.get("team", {})]
        assert "t1" in team_ids
        null_branches = [b for b in branches if b.get("team", {}).get("null") is True]
        assert null_branches, "OR filter must include a null-team branch for workspace labels"

    def test_team_filtered_response_needs_no_python_postprocessing(self, client):
        """When using GraphQL filter, the returned labels need no client-side stripping."""
        c, http = client
        # Labels returned by GraphQL filter have no 'team' key (not requested)
        labels = [{"id": "l1", "name": "Bug", "color": "#f00"}]
        http.post.return_value = make_response({"issueLabels": {"nodes": labels}})
        result = c.list_labels(team_id="t1")
        assert result == [{"id": "l1", "name": "Bug", "color": "#f00"}]

    def test_no_team_filter_query_has_no_variables(self, client):
        c, http = client
        http.post.return_value = make_response({"issueLabels": {"nodes": []}})
        c.list_labels()
        variables = http.post.call_args[1]["json"]["variables"]
        assert variables == {}


# ── Cycles ────────────────────────────────────────────────────────────────────

class TestListCycles:
    def test_team_not_found_raises(self, client):
        c, http = client
        http.post.return_value = make_response({"team": None})
        with pytest.raises(LinearError, match="not found"):
            c.list_cycles("bad-team-id")

    def test_default_limit_is_20(self, client):
        c, http = client
        http.post.return_value = make_response({"team": {"cycles": {"nodes": []}}})
        c.list_cycles("team-1")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["first"] == 20

    def test_custom_limit_is_passed(self, client):
        c, http = client
        http.post.return_value = make_response({"team": {"cycles": {"nodes": []}}})
        c.list_cycles("team-1", limit=50)
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["first"] == 50


class TestGetCurrentCycle:
    def test_returns_active_cycle(self, client):
        c, http = client
        cycles = [{
            "id": "cycle-1", "number": 1, "name": "Sprint 1",
            "startsAt": "2020-01-01T00:00:00Z",
            "endsAt": "2099-12-31T00:00:00Z",
            "completedAt": None,
            "issues": {"totalCount": 5},
        }]
        http.post.return_value = make_response({"team": {"cycles": {"nodes": cycles}}})
        result = c.get_current_cycle("team-1")
        assert result["id"] == "cycle-1"

    def test_returns_none_when_completed(self, client):
        c, http = client
        cycles = [{
            "id": "cycle-1", "number": 1, "name": "Sprint 1",
            "startsAt": "2020-01-01T00:00:00Z",
            "endsAt": "2020-01-14T00:00:00Z",
            "completedAt": "2020-01-14T00:00:00Z",
            "issues": {"totalCount": 3},
        }]
        http.post.return_value = make_response({"team": {"cycles": {"nodes": cycles}}})
        assert c.get_current_cycle("team-1") is None

    def test_returns_none_when_no_cycles(self, client):
        c, http = client
        http.post.return_value = make_response({"team": {"cycles": {"nodes": []}}})
        assert c.get_current_cycle("team-1") is None

    def test_fetches_200_cycles_to_cover_mature_teams(self, client):
        """get_current_cycle must request 200 cycles, not the default 20, so teams
        with a long history don't miss their active sprint."""
        c, http = client
        http.post.return_value = make_response({"team": {"cycles": {"nodes": []}}})
        c.get_current_cycle("team-1")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["first"] == 200


# ── Cycle membership ──────────────────────────────────────────────────────────

class TestAddIssueToCycle:
    def test_sets_cycle_id_via_issue_update(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": {"id": "i1", "identifier": "ENG-1",
             "title": "T", "priority": 0, "dueDate": None,
             "state": {"name": "Backlog"}, "assignee": None, "labels": {"nodes": []}}}}
        )
        c.add_issue_to_cycle("i1", "cycle-99")
        payload = http.post.call_args[1]["json"]
        assert "issueUpdate" in payload["query"]
        assert payload["variables"]["input"] == {"cycleId": "cycle-99"}

    def test_sends_cycle_id_not_null(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": {"id": "i1", "identifier": "ENG-1",
             "title": "T", "priority": 0, "dueDate": None,
             "state": {"name": "Backlog"}, "assignee": None, "labels": {"nodes": []}}}}
        )
        c.add_issue_to_cycle("i1", "cycle-abc")
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["cycleId"] == "cycle-abc"


class TestRemoveIssueFromCycle:
    def test_sends_cycle_id_null(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.remove_issue_from_cycle("i1")
        payload = http.post.call_args[1]["json"]
        assert "issueUpdate" in payload["query"]
        assert payload["variables"]["input"] == {"cycleId": None}


# ── _get_issue_label_ids (internal) ──────────────────────────────────────────

class TestGetIssueLabelIds:
    def test_returns_label_ids(self, client):
        c, http = client
        http.post.return_value = make_response({
            "issue": {"labels": {"nodes": [{"id": "l1"}, {"id": "l2"}]}}
        })
        assert c._get_issue_label_ids("i1") == ["l1", "l2"]

    def test_returns_empty_list_when_no_labels(self, client):
        c, http = client
        http.post.return_value = make_response({
            "issue": {"labels": {"nodes": []}}
        })
        assert c._get_issue_label_ids("i1") == []

    def test_not_found_raises(self, client):
        c, http = client
        http.post.return_value = make_response({"issue": None})
        with pytest.raises(LinearError, match="not found"):
            c._get_issue_label_ids("bad-id")

    def test_uses_narrow_query_without_comments_or_description(self, client):
        """Must not fetch the full issue (with 50 comments) just to read label IDs."""
        c, http = client
        http.post.return_value = make_response({
            "issue": {"labels": {"nodes": []}}
        })
        c._get_issue_label_ids("i1")
        query = http.post.call_args[1]["json"]["query"]
        assert "labels" in query
        assert "comments" not in query
        assert "description" not in query


# ── Label helpers ─────────────────────────────────────────────────────────────

class TestAddRemoveLabels:
    def _labels_resp(self, label_ids: list[str]) -> MagicMock:
        """Narrow response matching what _get_issue_label_ids expects."""
        return make_response({
            "issue": {"labels": {"nodes": [{"id": lid} for lid in label_ids]}}
        })

    def _update_resp(self) -> MagicMock:
        return make_response({"issueUpdate": {"success": True, "issue": _issue_stub()}})

    def test_add_labels_merges_with_existing(self, client):
        c, http = client
        http.post.side_effect = [self._labels_resp(["l1"]), self._update_resp()]
        c.add_labels("i1", ["l2"])
        update_payload = http.post.call_args_list[1][1]["json"]
        assert set(update_payload["variables"]["input"]["labelIds"]) == {"l1", "l2"}

    def test_add_labels_deduplicates(self, client):
        c, http = client
        http.post.side_effect = [self._labels_resp(["l1"]), self._update_resp()]
        c.add_labels("i1", ["l1"])
        update_payload = http.post.call_args_list[1][1]["json"]
        assert update_payload["variables"]["input"]["labelIds"] == ["l1"]

    def test_remove_labels_keeps_others(self, client):
        c, http = client
        http.post.side_effect = [self._labels_resp(["l1", "l2", "l3"]), self._update_resp()]
        c.remove_labels("i1", ["l2"])
        update_payload = http.post.call_args_list[1][1]["json"]
        remaining = update_payload["variables"]["input"]["labelIds"]
        assert set(remaining) == {"l1", "l3"}

    def test_remove_nonexistent_label_is_no_op(self, client):
        """Removing a label ID not on the issue silently leaves everything else intact."""
        c, http = client
        http.post.side_effect = [self._labels_resp(["l1", "l2"]), self._update_resp()]
        c.remove_labels("i1", ["l-nonexistent"])
        update_payload = http.post.call_args_list[1][1]["json"]
        assert set(update_payload["variables"]["input"]["labelIds"]) == {"l1", "l2"}


# ── Bulk update ───────────────────────────────────────────────────────────────

class TestBulkUpdateIssues:
    def test_updates_each_issue(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub(state={"name": "Done"})}}
        )
        results = c.bulk_update_issues(["i1", "i2", "i3"], state_id="state-done")
        assert len(results) == 3
        assert http.post.call_count == 3

    def test_raises_with_no_fields(self, client):
        c, http = client
        with pytest.raises(ValueError, match="at least one field"):
            c.bulk_update_issues(["i1"])

    def test_correct_state_id_sent_for_each(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.bulk_update_issues(["i1", "i2"], state_id="state-xyz")
        for call in http.post.call_args_list:
            assert call[1]["json"]["variables"]["input"]["stateId"] == "state-xyz"

    def test_due_date_passed_to_each_issue(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.bulk_update_issues(["i1", "i2"], due_date="2026-09-01")
        for call in http.post.call_args_list:
            assert call[1]["json"]["variables"]["input"]["dueDate"] == "2026-09-01"

    def test_multiple_fields_sent_together(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.bulk_update_issues(["i1"], state_id="s1", priority=2)
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["input"]["stateId"] == "s1"
        assert payload["variables"]["input"]["priority"] == 2

    def test_unrelated_fields_not_included(self, client):
        """Fields not passed must not appear in each issue's update payload."""
        c, http = client
        http.post.return_value = make_response(
            {"issueUpdate": {"success": True, "issue": _issue_stub()}}
        )
        c.bulk_update_issues(["i1"], priority=1)
        payload = http.post.call_args[1]["json"]["variables"]["input"]
        assert "stateId" not in payload
        assert "assigneeId" not in payload
        assert "dueDate" not in payload


# ── Notifications ─────────────────────────────────────────────────────────────

class TestListNotifications:
    def test_returns_nodes(self, client):
        c, http = client
        notifications = [
            {"id": "n1", "type": "issueAssigned", "readAt": None, "createdAt": "2024-01-01T00:00:00Z"},  # noqa: E501
        ]
        http.post.return_value = make_response({"notifications": {"nodes": notifications}})
        result = c.list_notifications()
        assert result == notifications

    def test_limit_is_passed(self, client):
        c, http = client
        http.post.return_value = make_response({"notifications": {"nodes": []}})
        c.list_notifications(limit=10)
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["first"] == 10


class TestMarkNotificationRead:
    def test_success(self, client):
        c, http = client
        notification = {"id": "n1", "readAt": "2026-06-06T00:00:00Z"}
        http.post.return_value = make_response(
            {"notificationUpdate": {"success": True, "notification": notification}}
        )
        result = c.mark_notification_read("n1")
        assert result["id"] == "n1"
        payload = http.post.call_args[1]["json"]
        assert payload["variables"]["id"] == "n1"
        assert "readAt" in payload["variables"]["input"]

    def test_raises_on_success_false(self, client):
        c, http = client
        http.post.return_value = make_response(
            {"notificationUpdate": {"success": False, "notification": None}}
        )
        with pytest.raises(LinearError, match="success=false"):
            c.mark_notification_read("n1")


# ── transition_issue ──────────────────────────────────────────────────────────

def _states_resp(*names: str) -> MagicMock:
    nodes = [{"id": f"s{i}", "name": n, "type": "started", "color": "#000", "position": i}
             for i, n in enumerate(names)]
    return make_response({"workflowStates": {"nodes": nodes}})


class TestTransitionIssue:
    def test_resolves_state_name_to_id_and_updates(self, client):
        c, http = client
        http.post.side_effect = [
            _states_resp("Todo", "In Progress", "Done"),
            make_response({"issueUpdate": {"success": True, "issue": _issue_stub(state={"name": "In Progress"})}}),  # noqa: E501
        ]
        result = c.transition_issue("i1", "In Progress", team_id="team-1")
        assert result["state"]["name"] == "In Progress"
        update_payload = http.post.call_args_list[1][1]["json"]
        assert update_payload["variables"]["input"] == {"stateId": "s1"}

    def test_state_name_matching_is_case_insensitive(self, client):
        c, http = client
        http.post.side_effect = [
            _states_resp("In Progress"),
            make_response({"issueUpdate": {"success": True, "issue": _issue_stub()}}),
        ]
        c.transition_issue("i1", "in progress", team_id="team-1")
        update_payload = http.post.call_args_list[1][1]["json"]
        assert update_payload["variables"]["input"]["stateId"] == "s0"

    def test_raises_with_available_states_when_name_not_found(self, client):
        c, http = client
        http.post.return_value = _states_resp("Todo", "Done")
        with pytest.raises(ValueError, match="Todo"):
            c.transition_issue("i1", "Nonexistent", team_id="team-1")

    def test_fetches_team_id_from_issue_when_omitted(self, client):
        c, http = client
        http.post.side_effect = [
            make_response({"issue": {"team": {"id": "team-99"}}}),
            _states_resp("Done"),
            make_response({"issueUpdate": {"success": True, "issue": _issue_stub()}}),
        ]
        c.transition_issue("i1", "Done")
        team_query_payload = http.post.call_args_list[0][1]["json"]
        assert "team" in team_query_payload["query"]
        states_payload = http.post.call_args_list[1][1]["json"]
        assert states_payload["variables"]["teamId"] == "team-99"
