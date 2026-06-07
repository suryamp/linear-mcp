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
`update_issue()` skips `None` parameters (treating them as "don't change this field"). To explicitly null a field (e.g., unassign, clear due date, remove from cycle), use `_update_issue_fields(issue_id, {"fieldName": None})` directly — it sends the value as JSON `null`.

## Adding a new tool

1. Add a `@mcp.tool()` function in `server.py` that validates inputs and delegates to a client method.
2. Add the corresponding method to `LinearClient` in `client.py` using `self._query(query_string, variables_dict)`.
3. Use `$filter: SomeFilter` variables (not hardcoded literals) when the query supports filtering.
4. Add unit tests in `tests/test_client.py` — mock `http.post` via the `client` fixture.

## Code style

- Ruff: line-length 100, selects E/F/W/I. No auto-formatter (ruff lint only).
- Section dividers: `# ── Section name ──────────────────────────────────────────────────────────────────`
- Type unions use `X | Y` syntax (Python 3.10+), not `Optional[X]` or `Union[X, Y]`.
- Priority encoding: 0=None 1=Urgent 2=High 3=Medium 4=Low (Linear API convention).
