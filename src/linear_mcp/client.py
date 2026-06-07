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
        self._http = httpx.Client(
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0, read=30.0),
        )
        self._viewer_id: str | None = None  # cached after first get_viewer()

    def close(self) -> None:
        self._http.close()

    def _query(self, query: str, variables: dict | None = None) -> dict:
        payload = {"query": query, "variables": variables or {}}
        # Mutations are not retried on timeout — they may already have committed server-side.
        is_mutation = query.lstrip().startswith("mutation")
        logger.debug(
            "GraphQL %s keys=%s",
            "mutation" if is_mutation else "query",
            list((variables or {}).keys()),
        )

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._http.post(LINEAR_API_URL, json=payload)
            except httpx.TimeoutException as exc:
                # Retry read-only queries on timeout; never retry mutations (idempotency risk).
                if not is_mutation and attempt < _MAX_RETRIES:
                    logger.warning("Query timed out — retrying (%d/%d)", attempt + 1, _MAX_RETRIES)
                    continue
                raise LinearError(f"Request timed out: {exc}") from exc
            except httpx.RequestError as exc:
                raise LinearError(f"Network error: {exc}") from exc

            if response.status_code == 429:
                try:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                except ValueError:
                    retry_after = 5
                if attempt < _MAX_RETRIES:
                    logger.warning("Rate limited — retrying in %ss", retry_after)
                    time.sleep(retry_after)
                    continue
                raise LinearError(
                    f"Rate limited by Linear API. Try again in {retry_after}s."
                )

            if not response.is_success:
                raise LinearError(
                    f"HTTP {response.status_code} from Linear API: {response.text[:200]}"
                )

            body = response.json()

            if "errors" in body:
                msg = body["errors"][0]["message"]
                logger.error("GraphQL error: %s", msg)
                if not body.get("data"):
                    raise LinearError(msg)
                logger.warning("GraphQL partial error (data still returned): %s", msg)

            result = body.get("data", {})
            logger.debug("GraphQL response keys: %s", list(result.keys()))
            return result

        raise LinearError("Max retries exceeded")  # pragma: no cover

    # ── Identity ──────────────────────────────────────────────────────────────

    def get_viewer(self) -> dict:
        data = self._query("query { viewer { id name email } }")
        viewer = data["viewer"]
        self._viewer_id = viewer["id"]
        return viewer

    # ── Teams ─────────────────────────────────────────────────────────────────

    def list_teams(self) -> list[dict]:
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
                    members(first: 500) {
                        nodes { id name email displayName }
                    }
                }
            }
        """, {"teamId": team_id})
        team = data.get("team")
        if not team:
            raise LinearError(f"Team {team_id!r} not found")
        return team["members"]["nodes"]

    # ── Workflow states ───────────────────────────────────────────────────────

    def list_workflow_states(self, team_id: str) -> list[dict]:
        data = self._query("""
            query($teamId: ID!) {
                workflowStates(
                    filter: { team: { id: { eq: $teamId } } }
                    first: 250
                ) {
                    nodes { id name type color position }
                }
            }
        """, {"teamId": team_id})
        states = data["workflowStates"]["nodes"]
        return sorted(states, key=lambda s: s.get("position", 0))

    # ── Issues ────────────────────────────────────────────────────────────────

    def list_issues(
        self,
        team_id: str | None = None,
        assignee_id: str | None = None,
        state: str | None = None,
        priority: int | None = None,
        label_name: str | None = None,
        updated_after: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        filter_obj: dict = {}
        if team_id:
            filter_obj["team"] = {"id": {"eq": team_id}}
        if assignee_id:
            filter_obj["assignee"] = {"id": {"eq": assignee_id}}
        if state:
            filter_obj["state"] = {"name": {"eq": state}}
        if priority is not None:
            filter_obj["priority"] = {"eq": priority}
        if label_name:
            filter_obj["labels"] = {"name": {"eq": label_name}}
        if updated_after:
            filter_obj["updatedAt"] = {"gte": updated_after}

        data = self._query("""
            query($filter: IssueFilter, $first: Int!) {
                issues(filter: $filter, first: $first, orderBy: updatedAt) {
                    nodes {
                        id identifier title priority dueDate
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
        # Use cached viewer ID — avoids a round-trip on every call after the first.
        if not self._viewer_id:
            self.get_viewer()
        return self.list_issues(assignee_id=self._viewer_id, state=state, limit=limit)

    def get_issue(self, issue_id: str) -> dict:
        data = self._query("""
            query($id: String!) {
                issue(id: $id) {
                    id identifier title description priority dueDate
                    state    { name }
                    assignee { id name email }
                    team     { id name key }
                    project  { id name }
                    parent   { id identifier title }
                    labels   { nodes { id name color } }
                    relations { nodes { id type relatedIssue { id identifier title } } }
                    comments(first: 50) { nodes { id body createdAt user { name } } }
                    createdAt updatedAt
                }
            }
        """, {"id": issue_id})
        issue = data.get("issue")
        if issue is None:
            raise LinearError(f"Issue {issue_id!r} not found")
        return issue

    def search_issues(self, query: str, limit: int = 25) -> list[dict]:
        data = self._query("""
            query($filter: IssueFilter, $limit: Int!) {
                issues(filter: $filter, first: $limit, orderBy: updatedAt) {
                    nodes {
                        id identifier title priority description dueDate
                        state    { name }
                        assignee { name }
                        team     { name key }
                        project  { name }
                        createdAt updatedAt
                    }
                }
            }
        """, {
            "filter": {"or": [
                {"title": {"containsIgnoreCase": query}},
                {"description": {"containsIgnoreCase": query}},
            ]},
            "limit": limit,
        })
        return data["issues"]["nodes"]

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
        parent_id: str | None = None,
        due_date: str | None = None,
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
        if parent_id is not None:
            input_data["parentId"] = parent_id
        if due_date is not None:
            input_data["dueDate"] = due_date

        data = self._query("""
            mutation($input: IssueCreateInput!) {
                issueCreate(input: $input) {
                    success
                    issue {
                        id identifier title priority dueDate
                        state  { name }
                        team   { name key }
                        parent { id identifier title }
                        labels { nodes { name } }
                    }
                }
            }
        """, {"input": input_data})
        if not data["issueCreate"]["success"]:
            raise LinearError("issueCreate returned success=false")
        return data["issueCreate"]["issue"]

    def _update_issue_fields(self, issue_id: str, input_data: dict) -> dict:
        """Send exactly the fields in input_data to issueUpdate.
        Unlike update_issue(), this passes None values as JSON null (e.g. to unassign)."""
        if not input_data:
            raise ValueError("_update_issue_fields called with empty input_data")
        data = self._query("""
            mutation($id: String!, $input: IssueUpdateInput!) {
                issueUpdate(id: $id, input: $input) {
                    success
                    issue {
                        id identifier title priority dueDate
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

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
        cycle_id: str | None = None,
        due_date: str | None = None,
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
        if cycle_id is not None:
            input_data["cycleId"] = cycle_id
        if due_date is not None:
            input_data["dueDate"] = due_date if due_date else None

        if not input_data:
            raise ValueError("update_issue called with no fields to update")

        return self._update_issue_fields(issue_id, input_data)

    def transition_issue(self, issue_id: str, state_name: str, team_id: str | None = None) -> dict:
        if team_id is None:
            data = self._query(
                "query($id: String!) { issue(id: $id) { team { id } } }",
                {"id": issue_id},
            )
            team_id = data["issue"]["team"]["id"]
        states = self.list_workflow_states(team_id)
        match = next((s for s in states if s["name"].lower() == state_name.lower()), None)
        if match is None:
            available = [s["name"] for s in states]
            raise ValueError(f"No workflow state {state_name!r}. Available: {available}")
        return self._update_issue_fields(issue_id, {"stateId": match["id"]})

    def unassign_issue(self, issue_id: str) -> dict:
        """Remove the assignee from an issue (set to unassigned)."""
        return self._update_issue_fields(issue_id, {"assigneeId": None})

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

    # ── Issue relations ───────────────────────────────────────────────────────

    def create_issue_relation(
        self, issue_id: str, related_issue_id: str, relation_type: str
    ) -> dict:
        """type: 'blocks', 'blocked_by', 'duplicate', 'duplicated_by', 'related'"""
        data = self._query("""
            mutation($input: IssueRelationCreateInput!) {
                issueRelationCreate(input: $input) {
                    success
                    issueRelation { id type relatedIssue { id identifier title } }
                }
            }
        """, {"input": {
            "issueId": issue_id,
            "relatedIssueId": related_issue_id,
            "type": relation_type,
        }})
        if not data["issueRelationCreate"]["success"]:
            raise LinearError("issueRelationCreate returned success=false")
        return data["issueRelationCreate"]["issueRelation"]

    def delete_issue_relation(self, relation_id: str) -> bool:
        data = self._query("""
            mutation($id: String!) {
                issueRelationDelete(id: $id) { success }
            }
        """, {"id": relation_id})
        return data["issueRelationDelete"]["success"]

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
        data = self._query("""
            query($first: Int!) {
                projects(first: $first) {
                    nodes {
                        id name description state
                        teams { nodes { id name key } }
                    }
                }
            }
        """, {"first": limit})
        projects = data["projects"]["nodes"]
        if team_id:
            projects = [
                p for p in projects
                if any(t["id"] == team_id for t in p.get("teams", {}).get("nodes", []))
            ]
        return projects

    # ── Labels ────────────────────────────────────────────────────────────────

    def list_labels(self, team_id: str | None = None) -> list[dict]:
        # OR filter includes both team-scoped labels and workspace-level labels (team: null).
        filter_obj = (
            {"or": [
                {"team": {"id": {"eq": team_id}}},
                {"team": {"null": True}},
            ]}
            if team_id
            else None
        )
        variables: dict = {"filter": filter_obj} if filter_obj is not None else {}
        data = self._query("""
            query($filter: IssueLabelFilter) {
                issueLabels(first: 250, filter: $filter) {
                    nodes { id name color }
                }
            }
        """, variables)
        return data["issueLabels"]["nodes"]

    # ── Cycles ────────────────────────────────────────────────────────────────

    def list_cycles(self, team_id: str, limit: int = 20) -> list[dict]:
        data = self._query("""
            query($teamId: String!, $first: Int!) {
                team(id: $teamId) {
                    cycles(first: $first) {
                        nodes {
                            id number name startsAt endsAt completedAt
                        }
                    }
                }
            }
        """, {"teamId": team_id, "first": limit})
        team = data.get("team")
        if not team:
            raise LinearError(f"Team {team_id!r} not found")
        return team["cycles"]["nodes"]

    def get_current_cycle(self, team_id: str) -> dict | None:
        cycles = self.list_cycles(team_id, limit=200)
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
        return self._update_issue_fields(issue_id, {"cycleId": cycle_id})

    def remove_issue_from_cycle(self, issue_id: str) -> dict:
        """Remove an issue from its current cycle (sets cycleId to null)."""
        return self._update_issue_fields(issue_id, {"cycleId": None})

    def _get_issue_label_ids(self, issue_id: str) -> list[str]:
        data = self._query("""
            query($id: String!) {
                issue(id: $id) {
                    labels { nodes { id } }
                }
            }
        """, {"id": issue_id})
        issue = data.get("issue")
        if issue is None:
            raise LinearError(f"Issue {issue_id!r} not found")
        return [lb["id"] for lb in issue["labels"]["nodes"]]

    def add_labels(self, issue_id: str, label_ids: list[str]) -> dict:
        """Append labels to an issue without removing existing ones.
        Uses read-modify-write — concurrent label updates will be lost."""
        existing = self._get_issue_label_ids(issue_id)
        merged = list(dict.fromkeys(existing + label_ids))  # dedup, preserve order
        return self.update_issue(issue_id, label_ids=merged)

    def remove_labels(self, issue_id: str, label_ids: list[str]) -> dict:
        """Remove specific labels from an issue, leaving others intact.
        Uses read-modify-write — a concurrent label update between the read and write will be lost.
        Silently no-ops for label IDs not present on the issue."""
        existing = self._get_issue_label_ids(issue_id)
        to_remove = set(label_ids)
        remaining = [lid for lid in existing if lid not in to_remove]
        return self.update_issue(issue_id, label_ids=remaining)

    def bulk_update_issues(
        self,
        issue_ids: list[str],
        state_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        due_date: str | None = None,
    ) -> list[dict]:
        """Apply the same update to multiple issues. Returns updated issues in order."""
        if not any(x is not None for x in (state_id, assignee_id, priority, due_date)):
            raise ValueError("bulk_update_issues: at least one field to update is required")
        return [
            self.update_issue(
                iid,
                state_id=state_id,
                assignee_id=assignee_id,
                priority=priority,
                due_date=due_date,
            )
            for iid in issue_ids
        ]

    # ── Notifications ─────────────────────────────────────────────────────────

    def list_notifications(self, limit: int = 25) -> list[dict]:
        data = self._query("""
            query($first: Int!) {
                notifications(first: $first) {
                    nodes {
                        id type readAt createdAt updatedAt
                        ... on IssueNotification {
                            issue { id identifier title }
                            actor { name }
                        }
                    }
                }
            }
        """, {"first": limit})
        return data["notifications"]["nodes"]

    def mark_notification_read(self, notification_id: str) -> dict:
        read_at = datetime.now(timezone.utc).isoformat()
        data = self._query("""
            mutation($id: String!, $input: NotificationUpdateInput!) {
                notificationUpdate(id: $id, input: $input) {
                    success
                    notification { id readAt }
                }
            }
        """, {"id": notification_id, "input": {"readAt": read_at}})
        if not data["notificationUpdate"]["success"]:
            raise LinearError("notificationUpdate returned success=false")
        return data["notificationUpdate"]["notification"]
