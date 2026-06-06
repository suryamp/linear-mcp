TOOLS = [
    {
        "name": "get_viewer",
        "description": "Get the currently authenticated user's id, name, and email.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_teams",
        "description": "List all teams in the Linear workspace with their IDs and keys.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_workflow_states",
        "description": "List all workflow states for a team (e.g. Todo, In Progress, Done). Call this before updating an issue's state so you have the correct state ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Team UUID"},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "list_issues",
        "description": "List issues, optionally filtered by team, assignee, or state name. Results are sorted by last-updated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id":     {"type": "string", "description": "Filter by team UUID"},
                "assignee_id": {"type": "string", "description": "Filter by assignee UUID"},
                "state":       {"type": "string", "description": "Filter by exact state name, e.g. 'In Progress'"},
                "limit":       {"type": "integer", "description": "Max results (default 25)", "default": 25},
            },
            "required": [],
        },
    },
    {
        "name": "get_issue",
        "description": "Get full details for a single issue including description and comments. Accepts a UUID or a short identifier like 'ENG-42'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Issue UUID or identifier (e.g. 'ENG-42')"},
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "search_issues",
        "description": "Full-text search across issue titles and descriptions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "description": "Max results (default 25)", "default": 25},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_issue",
        "description": "Create a new issue. Requires team_id and title. Priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id":     {"type": "string", "description": "Team UUID"},
                "title":       {"type": "string", "description": "Issue title"},
                "description": {"type": "string", "description": "Issue body (markdown)"},
                "assignee_id": {"type": "string", "description": "Assignee UUID"},
                "priority":    {"type": "integer", "enum": [0, 1, 2, 3, 4], "description": "0=None 1=Urgent 2=High 3=Medium 4=Low"},
                "state_id":    {"type": "string", "description": "Workflow state UUID"},
                "project_id":  {"type": "string", "description": "Project UUID"},
            },
            "required": ["team_id", "title"],
        },
    },
    {
        "name": "update_issue",
        "description": "Update one or more fields of an existing issue. Only pass the fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id":    {"type": "string", "description": "Issue UUID or identifier"},
                "title":       {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description (markdown)"},
                "state_id":    {"type": "string", "description": "New workflow state UUID"},
                "assignee_id": {"type": "string", "description": "New assignee UUID"},
                "priority":    {"type": "integer", "enum": [0, 1, 2, 3, 4], "description": "0=None 1=Urgent 2=High 3=Medium 4=Low"},
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "delete_issue",
        "description": "Permanently delete an issue. Cannot be undone — confirm with the user before calling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Issue UUID or identifier"},
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "add_comment",
        "description": "Add a markdown comment to an issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Issue UUID or identifier"},
                "body":     {"type": "string", "description": "Comment text (markdown)"},
            },
            "required": ["issue_id", "body"],
        },
    },
    {
        "name": "list_projects",
        "description": "List projects, optionally filtered by team.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Filter by team UUID"},
            },
            "required": [],
        },
    },
]
