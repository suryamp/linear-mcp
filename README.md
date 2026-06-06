# linear-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server that connects Claude Code to your Linear workspace. Give Claude natural-language instructions and it handles the API calls.

```
Show me all In Progress issues for the engineering team
Create a high priority bug called "Login timeout on mobile"
Move ENG-42 to Done and add a comment explaining the fix
Assign all unassigned issues in the backlog to me
```

## Requirements

- Python 3.10+
- A [Linear API key](https://linear.app/settings/api) (Personal API keys → Create key)
- [Claude Code](https://claude.ai/code)

## Installation

### Option A — uvx (no install needed)

```bash
claude mcp add linear \
  -e LINEAR_API_KEY=lin_api_your_key_here \
  -- uvx --from "git+https://github.com/suryamp/linear-mcp" linear-mcp
```

### Option B — pip install

```bash
pip install git+https://github.com/suryamp/linear-mcp
claude mcp add linear -e LINEAR_API_KEY=lin_api_your_key_here -- linear-mcp
```

### Option C — clone and run locally

```bash
git clone https://github.com/suryamp/linear-mcp
cd linear-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
claude mcp add linear \
  -e LINEAR_API_KEY=lin_api_your_key_here \
  -- /path/to/linear-mcp/.venv/bin/python -m linear_mcp.server
```

## Getting your Linear API key

1. Go to [linear.app/settings/api](https://linear.app/settings/api)
2. Under **Personal API keys**, click **Create key**
3. Copy the key — it starts with `lin_api_`

## Available tools

| Tool | Description |
|---|---|
| `get_viewer` | Get your user profile |
| `list_teams` | List all teams with IDs |
| `list_members` | List team members (for assigning issues) |
| `list_workflow_states` | List states like Todo / In Progress / Done |
| `list_issues` | List issues, filtered by team / assignee / state |
| `get_issue` | Get full issue details including comments |
| `search_issues` | Full-text search across all issues |
| `create_issue` | Create a new issue |
| `update_issue` | Update title, description, state, assignee, priority |
| `delete_issue` | Permanently delete an issue |
| `add_comment` | Add a comment to an issue |
| `list_projects` | List projects |

## Example prompts

```
What teams do I have in Linear?
Show me everything assigned to me that's In Progress
Create a medium priority issue called "Update onboarding docs" in the ENG team
Move all Done issues from last week to Cancelled
Add a comment to ENG-88 saying "Blocked on design review"
Who's on the mobile team?
```

## License

MIT
