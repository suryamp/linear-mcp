import logging
import os
import sys
import threading

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from linear_mcp.client import LinearClient, LinearError

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("linear")
_linear: LinearClient | None = None
_linear_lock = threading.Lock()


def _client() -> LinearClient:
    global _linear
    with _linear_lock:
        if _linear is None:
            key = os.environ.get("LINEAR_API_KEY", "")
            if not key:
                raise LinearError("LINEAR_API_KEY is not set")
            if not key.startswith("lin_api_"):
                logger.warning(
                    "LINEAR_API_KEY doesn't start with 'lin_api_' — verify your key"
                )
            _linear = LinearClient(key)
    return _linear


def _validate_startup() -> None:
    key = os.environ.get("LINEAR_API_KEY", "")
    if not key:
        print(
            "ERROR: LINEAR_API_KEY is not set — every tool call will fail. "
            "Set it with: claude mcp add linear -e LINEAR_API_KEY=lin_api_... -- linear-mcp",
            file=sys.stderr,
            flush=True,
        )
        return
    if not key.startswith("lin_api_"):
        logger.warning("LINEAR_API_KEY doesn't start with 'lin_api_' — verify your key")
    try:
        viewer = _client().get_viewer()
        logger.info("Authenticated as %s", viewer.get("name"))
    except Exception as exc:
        print(f"ERROR: Linear API auth failed at startup: {exc}", file=sys.stderr, flush=True)


# ── Identity ──────────────────────────────────────────────────────────────────

@mcp.tool()
def get_viewer() -> dict:
    """Get the currently authenticated Linear user's id, name, and email."""
    return _client().get_viewer()


# ── Teams ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_teams() -> list:
    """List all teams in the Linear workspace with their IDs and keys."""
    return _client().list_teams()


@mcp.tool()
def list_members(team_id: str) -> list:
    """List all members of a team. Use this to look up user IDs before assigning issues.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    return _client().list_members(team_id)


# ── Workflow states ───────────────────────────────────────────────────────────

@mcp.tool()
def list_workflow_states(team_id: str) -> list:
    """List workflow states for a team sorted by position (Backlog → Todo → In Progress → Done).
    Call this before updating an issue's state to get the correct state ID.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    return _client().list_workflow_states(team_id)


# ── Issues ────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_my_issues(state: str | None = None, limit: int = 25) -> list:
    """Get issues assigned to you — the fastest way to see your current workload.

    Args:
        state: Optional filter by exact state name, e.g. 'In Progress'.
        limit: Max results (default 25).
    """
    return _client().get_my_issues(state=state, limit=limit)


@mcp.tool()
def list_issues(
    team_id: str | None = None,
    assignee_id: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    label_name: str | None = None,
    updated_after: str | None = None,
    limit: int = 25,
) -> list:
    """List issues sorted by last-updated. All filters are optional and composable.

    Args:
        team_id: Filter by team UUID.
        assignee_id: Filter by assignee UUID.
        state: Filter by exact state name, e.g. 'In Progress'.
        priority: Filter by priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        label_name: Filter by exact label name, e.g. 'bug'.
        updated_after: ISO timestamp — only return issues updated after this time,
                       e.g. '2026-06-01T00:00:00Z'.
        limit: Max results (default 25).
    """
    return _client().list_issues(
        team_id=team_id,
        assignee_id=assignee_id,
        state=state,
        priority=priority,
        label_name=label_name,
        updated_after=updated_after,
        limit=limit,
    )


@mcp.tool()
def get_issue(issue_id: str) -> dict:
    """Get full details for one issue including description, labels, parent, relations,
    and comments (up to 50).

    Args:
        issue_id: Issue UUID or short identifier like 'ENG-42'.
    """
    return _client().get_issue(issue_id)


@mcp.tool()
def search_issues(query: str, limit: int = 25) -> list:
    """Full-text search across issue titles and descriptions.

    Args:
        query: Search term.
        limit: Max results (default 25).
    """
    return _client().search_issues(query, limit)


@mcp.tool()
def create_issue(
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
    """Create a new Linear issue. Optionally nest it under a parent issue (sub-issue).

    Args:
        team_id: Team UUID (use list_teams to find it).
        title: Issue title.
        description: Body text in markdown.
        assignee_id: Assignee UUID (use list_members to find it).
        priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        state_id: Workflow state UUID (use list_workflow_states to find it).
        project_id: Project UUID (use list_projects to find it).
        label_ids: List of label UUIDs to apply (use list_labels to find them).
        parent_id: Parent issue UUID or identifier to create this as a sub-issue.
        due_date: Due date in YYYY-MM-DD format, e.g. '2026-06-30'.
    """
    return _client().create_issue(
        team_id=team_id, title=title, description=description,
        assignee_id=assignee_id, priority=priority,
        state_id=state_id, project_id=project_id,
        label_ids=label_ids, parent_id=parent_id, due_date=due_date,
    )


@mcp.tool()
def update_issue(
    issue_id: str,
    title: str | None = None,
    description: str | None = None,
    state_id: str | None = None,
    assignee_id: str | None = None,
    priority: int | None = None,
    label_ids: list[str] | None = None,
    due_date: str | None = None,
) -> dict:
    """Update fields on an existing issue. Only pass fields you want to change.
    To remove the assignee entirely, use unassign_issue instead.
    WARNING: label_ids REPLACES all existing labels. Use add_labels / remove_labels
    to append or remove individual labels without clobbering the rest.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        title: New title.
        description: New body (markdown).
        state_id: New workflow state UUID (use list_workflow_states to find it).
        assignee_id: New assignee UUID (use list_members to find it).
        priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        label_ids: Replace ALL labels with these UUIDs. Use add_labels or remove_labels
                   to add/remove individual labels without losing others.
        due_date: Due date in YYYY-MM-DD format, e.g. '2026-06-30'. Pass empty string to clear.
    """
    return _client().update_issue(
        issue_id=issue_id, title=title, description=description,
        state_id=state_id, assignee_id=assignee_id, priority=priority,
        label_ids=label_ids, due_date=due_date,
    )


@mcp.tool()
def transition_issue(issue_id: str, state_name: str, team_id: str | None = None) -> dict:
    """Move an issue to a named workflow state without needing the state UUID.
    If team_id is omitted it is fetched from the issue automatically (one extra API call).

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        state_name: Workflow state name, e.g. 'In Progress'. Case-insensitive.
        team_id: Team UUID (use list_teams to find it). Optional — fetched from issue if omitted.
    """
    return _client().transition_issue(issue_id, state_name, team_id)


@mcp.tool()
def unassign_issue(issue_id: str) -> dict:
    """Remove the assignee from an issue, leaving it unassigned.
    Use update_issue to change the assignee to someone else.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
    """
    return _client().unassign_issue(issue_id)


@mcp.tool()
def add_labels(issue_id: str, label_ids: list[str]) -> dict:
    """Add one or more labels to an issue without removing existing labels.
    Note: uses read-then-write — if another process updates labels between the read
    and write, those changes will be overwritten.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        label_ids: Label UUIDs to add (use list_labels to find them).
    """
    return _client().add_labels(issue_id, label_ids)


@mcp.tool()
def remove_labels(issue_id: str, label_ids: list[str]) -> dict:
    """Remove one or more labels from an issue, leaving other labels intact.
    Label IDs not present on the issue are silently ignored.
    Note: uses read-then-write — see add_labels for the concurrency caveat.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        label_ids: Label UUIDs to remove.
    """
    return _client().remove_labels(issue_id, label_ids)


@mcp.tool()
def bulk_update_issues(
    issue_ids: list[str],
    state_id: str | None = None,
    assignee_id: str | None = None,
    priority: int | None = None,
    due_date: str | None = None,
) -> list:
    """Apply the same state/assignee/priority/due-date update to multiple issues at once.
    At least one update field is required. Issues are updated sequentially.

    Args:
        issue_ids: List of issue UUIDs or identifiers like ['ENG-42', 'ENG-43'].
        state_id: New workflow state UUID for all issues (use list_workflow_states).
        assignee_id: New assignee UUID for all issues (use list_members).
        priority: New priority for all issues: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        due_date: Due date in YYYY-MM-DD format for all issues.
    """
    return _client().bulk_update_issues(
        issue_ids=issue_ids,
        state_id=state_id,
        assignee_id=assignee_id,
        priority=priority,
        due_date=due_date,
    )


@mcp.tool()
def archive_issue(issue_id: str) -> dict:
    """Archive an issue (reversible). Prefer this over delete_issue for most cases.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
    """
    return {"success": _client().archive_issue(issue_id)}


@mcp.tool()
def delete_issue(issue_id: str, confirm: bool = False) -> dict:
    """Permanently delete an issue. Cannot be undone. Use archive_issue instead when possible.
    You MUST pass confirm=True — this prevents accidental deletion.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        confirm: Must be True to proceed. False returns a warning without deleting.
    """
    if not confirm:
        return {
            "warning": "This action is permanent and cannot be undone.",
            "action": (
                "Pass confirm=True to delete, or use archive_issue for a reversible alternative."
            ),
        }
    return {"success": _client().delete_issue(issue_id)}


# ── Issue relations ───────────────────────────────────────────────────────────

@mcp.tool()
def create_issue_relation(
    issue_id: str,
    related_issue_id: str,
    relation_type: str,
) -> dict:
    """Create a relation between two issues (e.g. blocks, duplicate, related).
    The relation ID returned can be used with delete_issue_relation to remove it.

    Args:
        issue_id: The source issue UUID or identifier like 'ENG-42'.
        related_issue_id: The target issue UUID or identifier like 'ENG-43'.
        relation_type: One of 'blocks', 'blocked_by', 'duplicate', 'duplicated_by', 'related'.
    """
    return _client().create_issue_relation(issue_id, related_issue_id, relation_type)


@mcp.tool()
def delete_issue_relation(relation_id: str) -> dict:
    """Remove a relation between two issues.

    Args:
        relation_id: Relation UUID (visible in get_issue under 'relations').
    """
    return {"success": _client().delete_issue_relation(relation_id)}


# ── Comments ──────────────────────────────────────────────────────────────────

@mcp.tool()
def add_comment(issue_id: str, body: str) -> dict:
    """Add a markdown comment to an issue.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        body: Comment text (markdown supported).
    """
    return _client().add_comment(issue_id, body)


# ── Projects ──────────────────────────────────────────────────────────────────

@mcp.tool()
def list_projects(team_id: str | None = None, limit: int = 50) -> list:
    """List projects, optionally filtered by team.

    Args:
        team_id: Filter by team UUID.
        limit: Max results (default 50).
    """
    return _client().list_projects(team_id, limit)


# ── Labels ────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_labels(team_id: str | None = None) -> list:
    """List issue labels, optionally filtered by team.

    Args:
        team_id: Filter by team UUID (use list_teams to find it).
    """
    return _client().list_labels(team_id)


# ── Cycles ────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_cycles(team_id: str, limit: int = 20) -> list:
    """List cycles (sprints) for a team, including issue counts and date ranges.

    Args:
        team_id: Team UUID (use list_teams to find it).
        limit: Max cycles to return (default 20, increase for teams with long history).
    """
    return _client().list_cycles(team_id, limit=limit)


@mcp.tool()
def get_current_cycle(team_id: str) -> dict:
    """Get the currently active cycle (sprint) for a team.
    Returns {"active": false} if no cycle is currently running.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    cycle = _client().get_current_cycle(team_id)
    if cycle is not None:
        return cycle
    return {"active": False, "message": "No active cycle for this team"}


@mcp.tool()
def add_issue_to_cycle(issue_id: str, cycle_id: str) -> dict:
    """Add an issue to a cycle (sprint).

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        cycle_id: Cycle UUID (use list_cycles or get_current_cycle to find it).
    """
    return _client().add_issue_to_cycle(issue_id, cycle_id)


@mcp.tool()
def remove_issue_from_cycle(issue_id: str) -> dict:
    """Remove an issue from its current cycle (sprint), leaving it unscheduled.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
    """
    return _client().remove_issue_from_cycle(issue_id)


# ── Notifications ─────────────────────────────────────────────────────────────

@mcp.tool()
def list_notifications(limit: int = 25) -> list:
    """List your unread and recent Linear notifications.

    Args:
        limit: Max results (default 25).
    """
    return _client().list_notifications(limit=limit)


@mcp.tool()
def mark_notification_read(notification_id: str) -> dict:
    """Mark a notification as read.

    Args:
        notification_id: Notification UUID (from list_notifications).
    """
    return _client().mark_notification_read(notification_id)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    _validate_startup()
    mcp.run()


if __name__ == "__main__":
    main()
