import logging
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from linear_mcp.client import LinearClient

load_dotenv()

# Fix #12: structured logging; level controlled by LOG_LEVEL env var
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("linear")
_linear: LinearClient | None = None


def _client() -> LinearClient:
    global _linear
    if _linear is None:
        key = os.environ.get("LINEAR_API_KEY", "")
        if not key:
            raise RuntimeError("LINEAR_API_KEY is not set")
        # Fix #15: warn early if key looks wrong
        if not key.startswith("lin_api_"):
            logger.warning(
                "LINEAR_API_KEY doesn't start with 'lin_api_' — verify your key"
            )
        _linear = LinearClient(key)
    return _linear


# Fix #11: validate at startup, not at first tool call
def _validate_startup() -> None:
    key = os.environ.get("LINEAR_API_KEY", "")
    if not key:
        logger.error(
            "LINEAR_API_KEY is not set — every tool call will fail. "
            "Set it with: claude mcp add linear -e LINEAR_API_KEY=lin_api_... -- linear-mcp"
        )
        return
    if not key.startswith("lin_api_"):
        logger.warning("LINEAR_API_KEY doesn't start with 'lin_api_' — verify your key")
    try:
        viewer = _client().get_viewer()
        logger.info("Authenticated as %s (%s)", viewer.get("name"), viewer.get("email"))
    except Exception as exc:
        logger.error("Linear API auth failed at startup: %s", exc)


# ── Identity ──────────────────────────────────────────────────────────────────

# Fix #3: return dicts/lists directly; FastMCP serializes them — no more json.dumps
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
def get_my_issues(state: str = None, limit: int = 25) -> list:
    """Get issues assigned to you — the fastest way to see your current workload.

    Args:
        state: Optional filter by exact state name, e.g. 'In Progress'.
        limit: Max results (default 25).
    """
    return _client().get_my_issues(state=state, limit=limit)


@mcp.tool()
def list_issues(
    team_id: str = None,
    assignee_id: str = None,
    state: str = None,
    limit: int = 25,
) -> list:
    """List issues sorted by last-updated. All filters are optional.

    Args:
        team_id: Filter by team UUID.
        assignee_id: Filter by assignee UUID.
        state: Filter by exact state name, e.g. 'In Progress'.
        limit: Max results (default 25).
    """
    return _client().list_issues(
        team_id=team_id, assignee_id=assignee_id, state=state, limit=limit
    )


@mcp.tool()
def get_issue(issue_id: str) -> dict:
    """Get full details for one issue including description, labels, and comments (up to 50).

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
    description: str = None,
    assignee_id: str = None,
    priority: int = None,
    state_id: str = None,
    project_id: str = None,
    label_ids: list[str] = None,
) -> dict:
    """Create a new Linear issue.

    Args:
        team_id: Team UUID (use list_teams to find it).
        title: Issue title.
        description: Body text in markdown.
        assignee_id: Assignee UUID (use list_members to find it).
        priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        state_id: Workflow state UUID (use list_workflow_states to find it).
        project_id: Project UUID (use list_projects to find it).
        label_ids: List of label UUIDs to apply (use list_labels to find them).
    """
    return _client().create_issue(
        team_id=team_id, title=title, description=description,
        assignee_id=assignee_id, priority=priority,
        state_id=state_id, project_id=project_id, label_ids=label_ids,
    )


@mcp.tool()
def update_issue(
    issue_id: str,
    title: str = None,
    description: str = None,
    state_id: str = None,
    assignee_id: str = None,
    priority: int = None,
    label_ids: list[str] = None,
) -> dict:
    """Update fields on an existing issue. Only pass fields you want to change.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        title: New title.
        description: New body (markdown).
        state_id: New workflow state UUID (use list_workflow_states to find it).
        assignee_id: New assignee UUID (use list_members to find it).
        priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        label_ids: Replace all labels with these UUIDs (use list_labels to find them).
    """
    return _client().update_issue(
        issue_id=issue_id, title=title, description=description,
        state_id=state_id, assignee_id=assignee_id, priority=priority,
        label_ids=label_ids,
    )


# Fix #7: archive as primary, delete requires explicit confirm
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
def list_projects(team_id: str = None, limit: int = 50) -> list:
    """List projects, optionally filtered by team.

    Args:
        team_id: Filter by team UUID.
        limit: Max results (default 50).
    """
    return _client().list_projects(team_id, limit)


# ── Labels (#8) ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_labels(team_id: str = None) -> list:
    """List issue labels, optionally filtered by team.

    Args:
        team_id: Filter by team UUID (use list_teams to find it).
    """
    return _client().list_labels(team_id)


# ── Cycles (#9) ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_cycles(team_id: str) -> list:
    """List all cycles (sprints) for a team.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    return _client().list_cycles(team_id)


@mcp.tool()
def get_current_cycle(team_id: str) -> dict:
    """Get the currently active cycle (sprint) for a team.
    Returns an empty dict if no cycle is currently active.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    return _client().get_current_cycle(team_id) or {}


@mcp.tool()
def add_issue_to_cycle(issue_id: str, cycle_id: str) -> dict:
    """Add an issue to a cycle (sprint).

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        cycle_id: Cycle UUID (use list_cycles or get_current_cycle to find it).
    """
    return _client().add_issue_to_cycle(issue_id, cycle_id)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    _validate_startup()
    mcp.run()


if __name__ == "__main__":
    main()
