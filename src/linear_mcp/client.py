import logging
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"
_MAX_RETRIES = 2


class LinearError(Exception):
    pass


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class LinearClient:
    def __init__(self, api_key: str):
        # Fix #2: persistent httpx.Client for connection pooling
        self._http = httpx.Client(
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0, read=30.0),
        )

    def close(self) -> None:
        self._http.close()

    def _query(self, query: str, variables: dict | None = None) -> dict:
        payload = {"query": query, "variables": variables or {}}
        logger.debug("GraphQL request vars=%s", variables)

        # Fix #14: retry on 429 with Retry-After
        for attempt in range(_MAX_RETRIES + 1):
            response = self._http.post(LINEAR_API_URL, json=payload)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                if attempt < _MAX_RETRIES:
                    logger.warning("Rate limited — retrying in %ss", retry_after)
                    time.sleep(retry_after)
                    continue
                raise LinearError(
                    f"Rate limited by Linear API. Try again in {retry_after}s."
                )

            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                msg = data["errors"][0]["message"]
                logger.error("GraphQL error: %s", msg)
                raise LinearError(msg)

            result = data.get("data", {})
            logger.debug("GraphQL response keys: %s", list(result.keys()))
            return result

        raise LinearError("Max retries exceeded")  # pragma: no cover

    # ── Identity ──────────────────────────────────────────────────────────────

    def get_viewer(self) -> dict:
        data = self._query("query { viewer { id name email } }")
        return data["viewer"]

    # ── Teams ─────────────────────────────────────────────────────────────────

    def list_teams(self) -> list[dict]:
        # Fix #4: add first: 100 to avoid unbounded result
        data = self._query("""
            query {
                teams(first: 100) {
                    nodes { id name key description }
                }
            }
        """)
        return data["teams"]["nodes"]

    def list_members(self, team_id: str) -> list[dict]:
        data = self._query("""
            query($teamId: String!) {
                team(id: $teamId) {
                    members {
                        nodes { id name email displayName }
                    }
                }
            }
        """, {"teamId": team_id})
        return data["team"]["members"]["nodes"]

    # ── Workflow states ───────────────────────────────────────────────────────

    def list_workflow_states(self, team_id: str) -> list[dict]:
        data = self._query("""
            query($teamId: String!) {
                workflowStates(filter: { team: { id: { eq: $teamId } } }) {
                    nodes { id name type color position }
                }
            }
        """, {"teamId": team_id})
        # Fix #10: sort by position so Claude sees natural flow (Backlog → Done)
        states = data["workflowStates"]["nodes"]
        return sorted(states, key=lambda s: s.get("position", 0))

    # ── Issues ────────────────────────────────────────────────────────────────

    def list_issues(
        self,
        team_id: str | None = None,
        assignee_id: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        # Fix #1: use GraphQL variables instead of f-string interpolation
        filter_obj: dict = {}
        if team_id:
            filter_obj["team"] = {"id": {"eq": team_id}}
        if assignee_id:
            filter_obj["assignee"] = {"id": {"eq": assignee_id}}
        if state:
            filter_obj["state"] = {"name": {"eq": state}}

        data = self._query("""
            query($filter: IssueFilter, $first: Int!) {
                issues(filter: $filter, first: $first, orderBy: updatedAt) {
                    nodes {
                        id identifier title priority
                        state    { name }
                        assignee { id name email }
                        team     { id name key }
                        labels   { nodes { id name color } }
                        createdAt updatedAt
                    }
                }
            }
        """, {"filter": filter_obj or None, "first": limit})
        return data["issues"]["nodes"]

    def get_my_issues(self, state: str | None = None, limit: int = 25) -> list[dict]:
        # Fix #6: single-call convenience — avoids 2-step get_viewer + list_issues
        viewer = self.get_viewer()
        return self.list_issues(assignee_id=viewer["id"], state=state, limit=limit)

    def get_issue(self, issue_id: str) -> dict:
        data = self._query("""
            query($id: String!) {
                issue(id: $id) {
                    id identifier title description priority
                    state    { name }
                    assignee { id name email }
                    team     { id name key }
                    project  { id name }
                    labels   { nodes { id name color } }
                    comments(first: 50) { nodes { id body createdAt user { name } } }
                    createdAt updatedAt
                }
            }
        """, {"id": issue_id})
        return data["issue"]

    def search_issues(self, query: str, limit: int = 25) -> list[dict]:
        data = self._query("""
            query($term: String!, $limit: Int!) {
                issueSearch(query: $term, first: $limit) {
                    nodes {
                        id identifier title priority
                        state    { name }
                        assignee { name }
                        team     { name key }
                    }
                }
            }
        """, {"term": query, "limit": limit})
        return data["issueSearch"]["nodes"]

    def create_issue(
        self,
        team_id: str,
        title: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        state_id: str | None = None,
        project_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        input_data: dict = {"teamId": team_id, "title": title}
        if description is not None:
            input_data["description"] = description
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if priority is not None:
            input_data["priority"] = priority
        if state_id is not None:
            input_data["stateId"] = state_id
        if project_id is not None:
            input_data["projectId"] = project_id
        if label_ids is not None:
            input_data["labelIds"] = label_ids

        data = self._query("""
            mutation($input: IssueCreateInput!) {
                issueCreate(input: $input) {
                    success
                    issue {
                        id identifier title priority
                        state  { name }
                        team   { name key }
                        labels { nodes { name } }
                    }
                }
            }
        """, {"input": input_data})
        if not data["issueCreate"]["success"]:
            raise LinearError("issueCreate returned success=false")
        return data["issueCreate"]["issue"]

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        input_data: dict = {}
        if title is not None:
            input_data["title"] = title
        if description is not None:
            input_data["description"] = description
        if state_id is not None:
            input_data["stateId"] = state_id
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if priority is not None:
            input_data["priority"] = priority
        if label_ids is not None:
            input_data["labelIds"] = label_ids

        if not input_data:
            raise ValueError("update_issue called with no fields to update")

        data = self._query("""
            mutation($id: String!, $input: IssueUpdateInput!) {
                issueUpdate(id: $id, input: $input) {
                    success
                    issue {
                        id identifier title priority
                        state    { name }
                        assignee { name }
                        labels   { nodes { name } }
                    }
                }
            }
        """, {"id": issue_id, "input": input_data})
        if not data["issueUpdate"]["success"]:
            raise LinearError("issueUpdate returned success=false")
        return data["issueUpdate"]["issue"]

    # Fix #7: archive_issue as a safer reversible alternative to delete
    def archive_issue(self, issue_id: str) -> bool:
        data = self._query("""
            mutation($id: String!) {
                issueArchive(id: $id) { success }
            }
        """, {"id": issue_id})
        return data["issueArchive"]["success"]

    def delete_issue(self, issue_id: str) -> bool:
        data = self._query("""
            mutation($id: String!) {
                issueDelete(id: $id) { success }
            }
        """, {"id": issue_id})
        return data["issueDelete"]["success"]

    # ── Comments ──────────────────────────────────────────────────────────────

    def add_comment(self, issue_id: str, body: str) -> dict:
        data = self._query("""
            mutation($input: CommentCreateInput!) {
                commentCreate(input: $input) {
                    success
                    comment { id body createdAt }
                }
            }
        """, {"input": {"issueId": issue_id, "body": body}})
        if not data["commentCreate"]["success"]:
            raise LinearError("commentCreate returned success=false")
        return data["commentCreate"]["comment"]

    # ── Projects ──────────────────────────────────────────────────────────────

    def list_projects(self, team_id: str | None = None, limit: int = 50) -> list[dict]:
        # Fix #1: use variables, not f-string interpolation
        filter_obj: dict = {}
        if team_id:
            filter_obj["teams"] = {"id": {"eq": team_id}}

        data = self._query("""
            query($filter: ProjectFilter, $first: Int!) {
                projects(filter: $filter, first: $first) {
                    nodes {
                        id name description state
                        teams { nodes { name key } }
                    }
                }
            }
        """, {"filter": filter_obj or None, "first": limit})
        return data["projects"]["nodes"]

    # ── Labels (#8) ───────────────────────────────────────────────────────────

    def list_labels(self, team_id: str | None = None) -> list[dict]:
        data = self._query("""
            query {
                issueLabels(first: 250) {
                    nodes { id name color team { id } }
                }
            }
        """)
        labels = data["issueLabels"]["nodes"]
        if team_id:
            labels = [
                lb for lb in labels
                if lb.get("team") and lb["team"]["id"] == team_id
            ]
        for lb in labels:
            lb.pop("team", None)
        return labels

    # ── Cycles (#9) ───────────────────────────────────────────────────────────

    def list_cycles(self, team_id: str) -> list[dict]:
        data = self._query("""
            query($teamId: String!) {
                team(id: $teamId) {
                    cycles(first: 20) {
                        nodes {
                            id number name startsAt endsAt completedAt
                            issues { totalCount }
                        }
                    }
                }
            }
        """, {"teamId": team_id})
        return data["team"]["cycles"]["nodes"]

    def get_current_cycle(self, team_id: str) -> dict | None:
        cycles = self.list_cycles(team_id)
        now = datetime.now(timezone.utc)
        for cycle in cycles:
            starts = cycle.get("startsAt")
            ends = cycle.get("endsAt")
            completed = cycle.get("completedAt")
            if starts and ends and not completed:
                try:
                    if _parse_iso(starts) <= now <= _parse_iso(ends):
                        return cycle
                except (ValueError, TypeError):
                    continue
        return None

    def add_issue_to_cycle(self, issue_id: str, cycle_id: str) -> dict:
        data = self._query("""
            mutation($input: CycleIssueCreateInput!) {
                cycleIssueCreate(input: $input) {
                    success
                    cycleIssue { id }
                }
            }
        """, {"input": {"issueId": issue_id, "cycleId": cycle_id}})
        if not data["cycleIssueCreate"]["success"]:
            raise LinearError("cycleIssueCreate returned success=false")
        return data["cycleIssueCreate"]["cycleIssue"]
