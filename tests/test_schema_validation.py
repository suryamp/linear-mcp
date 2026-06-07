"""Validate every GraphQL query/mutation in client.py against the saved Linear schema.

Run with: pytest tests/test_schema_validation.py -v

No LINEAR_API_KEY required — validation is purely static against the committed
tests/linear_schema.json snapshot. Re-fetch the snapshot with:

    python scripts/fetch_schema.py
"""
import json
import re
from pathlib import Path

import pytest
from graphql import build_client_schema, parse, validate

# ── Load schema once ──────────────────────────────────────────────────────────

SCHEMA_PATH = Path(__file__).parent / "linear_schema.json"
CLIENT_PATH = Path(__file__).parent.parent / "src" / "linear_mcp" / "client.py"


@pytest.fixture(scope="module")
def schema():
    introspection = json.loads(SCHEMA_PATH.read_text())
    return build_client_schema(introspection["data"])


# ── Extract queries from source ───────────────────────────────────────────────

def _extract_queries(source: str) -> list[tuple[str, str]]:
    """Return [(label, query_string), ...] for every triple-quoted GraphQL operation."""
    # Match triple-quoted strings that contain a query or mutation keyword.
    pattern = re.compile(
        r'self\._query\(\s*"""(\s*(?:query|mutation)\b.*?)"""',
        re.DOTALL,
    )
    results = []
    for i, m in enumerate(pattern.finditer(source)):
        query_text = m.group(1).strip()
        # Derive a label from the first line of the operation.
        first_line = query_text.splitlines()[0].strip()
        results.append((f"query_{i+1}: {first_line}", query_text))
    return results


_source = CLIENT_PATH.read_text()
_queries = _extract_queries(_source)


# ── Parametrised validation tests ─────────────────────────────────────────────

@pytest.mark.parametrize("label,query_text", _queries, ids=[q[0] for q in _queries])
def test_query_is_valid(schema, label, query_text):
    try:
        document = parse(query_text)
    except Exception as exc:
        pytest.fail(f"Parse error in {label!r}: {exc}")

    errors = validate(schema, document)
    if errors:
        messages = "\n".join(f"  • {e.message}" for e in errors)
        pytest.fail(f"Schema validation errors in {label!r}:\n{messages}")
