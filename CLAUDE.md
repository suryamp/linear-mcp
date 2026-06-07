# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Linear MCP server — a FastMCP Python package that exposes 23+ tools for managing Linear issues, projects, cycles, and labels via GraphQL. Tools are declared in `server.py` and delegate to `LinearClient` in `client.py`.

## Commands

```bash
# Install (with dev deps)
pip install -e ".[dev]"
# or with uv:
uv run --extra dev python -m pytest tests/ -v

# Test
pytest tests/ -v
pytest tests/test_client.py::ClassName::test_name -v   # single test

# Lint
ruff check src tests

# Run the server
linear-mcp
```

Tests mock all HTTP calls — no `LINEAR_API_KEY` needed to run them.

## Environment

`LINEAR_API_KEY=lin_api_...` must be set (in `.env` or the environment). The server reads it at startup via `python-dotenv` and calls `get_viewer()` to validate auth. The key format check (`lin_api_` prefix) warns but doesn't block.

## Critical invariants

**1. Mutations are never retried on timeout.**  
Queries retry up to `_MAX_RETRIES = 2` times. Mutations don't — they may already have committed server-side. Detection is `query.lstrip().startswith("mutation")`. Do not add retry logic to mutations.

**2. `update_issue(label_ids=...)` replaces all labels.**  
Passing `label_ids` to `update_issue` clobbers every existing label on the issue. Use `add_labels()` / `remove_labels()` to append or remove individual labels without losing the rest.

**3. stdout is the MCP JSON-RPC channel.**  
The server runs on stdio transport. Any plain text written to stdout corrupts the protocol framing. All diagnostic output must go to `sys.stderr`. Use `logger.*` calls or `print(..., file=sys.stderr)` — never bare `print()` in `server.py`.

**4. GraphQL queries must use parameterized variables.**  
Always pass user-supplied values through the `variables` dict argument to `_query()`. Never interpolate them into the query string with f-strings — this was the original injection bug.

**5. Use `_update_issue_fields` when setting a field to null.**  
`update_issue()` skips `None` parameters (treating them as "don't change this field"). To explicitly null a field (e.g., unassign, clear due date, remove from cycle, un-nest from parent), use `_update_issue_fields(issue_id, {"fieldName": None})` directly — it sends the value as JSON `null`. For example, to remove a parent: `_update_issue_fields(issue_id, {"parentId": None})`. Passing `parent_id=None` to `update_issue` does nothing.

## Adding a new tool

1. Add a `@mcp.tool()` function in `server.py` that validates inputs and delegates to a client method.
2. Add the corresponding method to `LinearClient` in `client.py` using `self._query(query_string, variables_dict)`.
3. Use `$filter: SomeFilter` variables (not hardcoded literals) when the query supports filtering.
4. Add unit tests in `tests/test_client.py` — mock `http.post` via the `client` fixture.

**Tool docstrings are agent instructions, not API docs.**  
Write them as LLM tool-selection guidance: lead with *when* to use the tool, include cross-tool hints so the model can chain calls, and surface non-obvious behaviour. Example: `"Use this to look up user IDs before assigning issues"` is correct. `"Returns a list of team members"` is not.

**Destructive tools require a `confirm` guard.**  
Any tool that permanently deletes or irreversibly modifies data must accept `confirm: bool = False` and return a warning dict (not raise) when `confirm` is `False`. See `delete_issue` in `server.py` for the pattern. This prevents agent misfires.

## Known limitations

These are intentional gaps, not bugs. Fix them correctly — don't work around them by raising hardcoded limits.

**Pagination not implemented.**  
`list_issues`, `search_issues`, and `list_notifications` cap results with `first: N`. There is no cursor support yet. An agent silently sees a truncated slice with no indication that more results exist. The correct fix is to add `cursor: str | None = None` parameters and return `pageInfo { hasNextPage endCursor }` alongside nodes. Tracked in BUILD-9.

**No `list_sub_issues` tool.**  
`get_issue` returns a `parent` field but there is no tool to enumerate children. Linear's API exposes this via the `children` connection on `Issue`. Tracked in BUILD-10.

**`list_projects` filters by team client-side.**  
Python post-processes the full project list to filter by `team_id`. This is a Linear API limitation — the `projects` query does not expose a server-side team filter. Do not add a `$filter` variable; it won't work.

**`bulk_update_issues` is sequential.**  
Issues are updated one mutation at a time. This is intentional — parallel mutations on the same resource risk race conditions. Do not add concurrency here.

## CI workflows

`.github/workflows/ci.yml` — runs lint + tests across Python 3.10–3.14 on every push/PR.

`.github/workflows/refresh-schema.yml` — runs daily at 06:00 UTC. Introspects the live Linear GraphQL API, diffs `tests/linear_schema.json`, runs `tests/test_schema_validation.py` against the new schema, and opens a PR if anything changed. The PR body includes the validation output so you can see immediately whether `client.py` needs updates. Requires `LINEAR_API_KEY` set as a repository secret.

## Code style

- Ruff: line-length 100, selects E/F/W/I. No auto-formatter (ruff lint only).
- Section dividers: `# ── Section name ──────────────────────────────────────────────────────────────────`
- Type unions use `X | Y` syntax (Python 3.10+), not `Optional[X]` or `Union[X, Y]`.
- Priority encoding: 0=None 1=Urgent 2=High 3=Medium 4=Low (Linear API convention).
