import json
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from linear_mcp.client import LinearClient

load_dotenv()

mcp = FastMCP("linear")
_linear: LinearClient | None = None


def _client() -> LinearClient:
    global _linear
    if _linear is None:
        key = os.environ.get("LINEAR_API_KEY", "")
        if not key:
            raise RuntimeError("LINEAR_API_KEY environment variable is not set")
        _linear = LinearClient(key)
    return _linear


@mcp.tool()
def get_viewer() -> str:
    """Get the currently authenticated Linear user's id, name, and email."""
    return json.dumps(_client().get_viewer())


@mcp.tool()
def list_teams() -> str:
    """List all teams in the Linear workspace with their IDs and keys."""
    return json.dumps(_client().list_teams())


@mcp.tool()
def list_members(team_id: str) -> str:
    """List all members of a team. Use this to look up user IDs before assigning issues.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    return json.dumps(_client().list_members(team_id))


@mcp.tool()
def list_workflow_states(team_id: str) -> str:
    """List workflow states for a team (Todo, In Progress, Done, etc).
    Call this before updating an issue's state to get the correct state ID.

    Args:
        team_id: Team UUID (use list_teams to find it).
    """
    return json.dumps(_client().list_workflow_states(team_id))


@mcp.tool()
def list_issues(
    team_id: str = None,
    assignee_id: str = None,
    state: str = None,
    limit: int = 25,
) -> str:
    """List issues sorted by last-updated. All filters are optional.

    Args:
        team_id: Filter by team UUID.
        assignee_id: Filter by assignee UUID.
        state: Filter by exact state name, e.g. 'In Progress'.
        limit: Max results (default 25).
    """
    return json.dumps(_client().list_issues(
        team_id=team_id, assignee_id=assignee_id, state=state, limit=limit
    ))


@mcp.tool()
def get_issue(issue_id: str) -> str:
    """Get full details for one issue including description and comments.

    Args:
        issue_id: Issue UUID or short identifier like 'ENG-42'.
    """
    return json.dumps(_client().get_issue(issue_id), default=str)


@mcp.tool()
def search_issues(query: str, limit: int = 25) -> str:
    """Full-text search across issue titles and descriptions.

    Args:
        query: Search term.
        limit: Max results (default 25).
    """
    return json.dumps(_client().search_issues(query, limit))


@mcp.tool()
def create_issue(
    team_id: str,
    title: str,
    description: str = None,
    assignee_id: str = None,
    priority: int = None,
    state_id: str = None,
    project_id: str = None,
) -> str:
    """Create a new Linear issue.

    Args:
        team_id: Team UUID (use list_teams to find it).
        title: Issue title.
        description: Body text in markdown.
        assignee_id: Assignee UUID (use list_members to find it).
        priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
        state_id: Workflow state UUID (use list_workflow_states to find it).
        project_id: Project UUID.
    """
    return json.dumps(_client().create_issue(
        team_id=team_id, title=title, description=description,
        assignee_id=assignee_id, priority=priority,
        state_id=state_id, project_id=project_id,
    ))


@mcp.tool()
def update_issue(
    issue_id: str,
    title: str = None,
    description: str = None,
    state_id: str = None,
    assignee_id: str = None,
    priority: int = None,
) -> str:
    """Update fields on an existing issue. Only pass fields you want to change.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        title: New title.
        description: New body (markdown).
        state_id: New workflow state UUID (use list_workflow_states to find it).
        assignee_id: New assignee UUID (use list_members to find it).
        priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.
    """
    return json.dumps(_client().update_issue(
        issue_id=issue_id, title=title, description=description,
        state_id=state_id, assignee_id=assignee_id, priority=priority,
    ))


@mcp.tool()
def delete_issue(issue_id: str) -> str:
    """Permanently delete an issue. Cannot be undone.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
    """
    return json.dumps({"success": _client().delete_issue(issue_id)})


@mcp.tool()
def add_comment(issue_id: str, body: str) -> str:
    """Add a markdown comment to an issue.

    Args:
        issue_id: Issue UUID or identifier like 'ENG-42'.
        body: Comment text (markdown supported).
    """
    return json.dumps(_client().add_comment(issue_id, body), default=str)


@mcp.tool()
def list_projects(team_id: str = None) -> str:
    """List projects, optionally filtered by team.

    Args:
        team_id: Filter by team UUID.
    """
    return json.dumps(_client().list_projects(team_id))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
