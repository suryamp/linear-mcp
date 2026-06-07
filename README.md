# linear-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server that connects Claude Code to your Linear workspace. Give Claude natural-language instructions and it handles the API calls.

```
Show me all In Progress issues for the engineering team
Create a high priority bug called "Login timeout on mobile"
Move ENG-42 to Done and add a comment explaining the fix
Assign all unassigned issues in the backlog to me
Add the "blocked" label to ENG-55 without removing its other labels
Create a sub-issue under ENG-10 for the auth redesign
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

# Use the full path to the installed script to avoid PATH issues:
claude mcp add linear \
  -e LINEAR_API_KEY=lin_api_your_key_here \
  -- "$(python -m site --user-base)/bin/linear-mcp"
```

### Option C — clone and run locally

```bash
git clone https://github.com/suryamp/linear-mcp
cd linear-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
claude mcp add linear \
  -e LINEAR_API_KEY=lin_api_your_key_here \
  -- /path/to/linear-mcp/.venv/bin/linear-mcp
```

## Getting your Linear API key

1. Go to [linear.app/settings/api](https://linear.app/settings/api)
2. Under **Personal API keys**, click **Create key**
3. Copy the key — it starts with `lin_api_`

## Available tools

| Tool | Description |
|---|---|
| `get_viewer` | Get your user profile |
| `list_teams` | List all teams with IDs and keys |
| `list_members` | List team members (for assigning issues) |
| `list_workflow_states` | List states like Todo / In Progress / Done |
| `list_issues` | List issues, filtered by team / assignee / state / priority / label / date |
| `get_issue` | Get full issue details including comments and parent |
| `search_issues` | Full-text search across all issues |
| `create_issue` | Create a new issue (supports sub-issues via `parent_id`, due dates) |
| `update_issue` | Update title, description, state, assignee, priority, due date |
| `unassign_issue` | Remove the assignee from an issue |
| `add_labels` | Add labels to an issue without removing existing ones |
| `remove_labels` | Remove specific labels, leaving others intact |
| `bulk_update_issues` | Apply the same state/assignee/priority to multiple issues at once |
| `create_issue_relation` | Link two issues (blocks, duplicate, related, etc.) |
| `delete_issue_relation` | Remove a relation between two issues |
| `archive_issue` | Archive an issue (reversible) |
| `delete_issue` | Permanently delete an issue (requires `confirm=True`) |
| `add_comment` | Add a comment to an issue |
| `list_projects` | List projects, optionally filtered by team |
| `list_labels` | List labels, optionally filtered by team |
| `list_cycles` | List cycles (sprints) for a team |
| `get_current_cycle` | Get the currently active sprint for a team |
| `add_issue_to_cycle` | Add an issue to a sprint |
| `remove_issue_from_cycle` | Remove an issue from its current sprint |
| `list_notifications` | List your recent Linear notifications |
| `mark_notification_read` | Mark a notification as read |

> **Label tip:** `update_issue(label_ids=...)` **replaces all labels**. Use `add_labels` / `remove_labels` to add or remove individual labels without clobbering the rest.

## Example prompts

```
What teams do I have in Linear?
Show me everything assigned to me that's In Progress
Create a medium priority issue called "Update onboarding docs" in the ENG team
Create a sub-issue under ENG-10 titled "Write migration script"
Move ENG-42 to Done and add a comment explaining the fix
Add a "needs-design" label to ENG-55 without removing its other labels
Who's on the mobile team?
What's the current sprint for the ENG team?
Add ENG-42 to the current sprint
```

## License

MIT
