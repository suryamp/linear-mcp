#!/usr/bin/env python
"""Refresh tests/linear_schema.json from the live Linear API.

Usage:
    LINEAR_API_KEY=lin_api_... python scripts/fetch_schema.py
    # or with .env:
    uv run python scripts/fetch_schema.py
"""
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("LINEAR_API_KEY", "")
if not API_KEY:
    sys.exit("LINEAR_API_KEY not set")

INTROSPECTION = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    types { ...FullType }
    directives {
      name description locations
      args { ...InputValue }
    }
  }
}
fragment FullType on __Type {
  kind name description
  fields(includeDeprecated: true) {
    name description
    args { ...InputValue }
    type { ...TypeRef }
    isDeprecated deprecationReason
  }
  inputFields { ...InputValue }
  interfaces { ...TypeRef }
  enumValues(includeDeprecated: true) { name description isDeprecated deprecationReason }
  possibleTypes { ...TypeRef }
}
fragment InputValue on __InputValue {
  name description
  type { ...TypeRef }
  defaultValue
}
fragment TypeRef on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } }
}
"""

r = httpx.post(
    "https://api.linear.app/graphql",
    headers={"Authorization": API_KEY, "Content-Type": "application/json"},
    json={"query": INTROSPECTION},
    timeout=30,
)
r.raise_for_status()
data = r.json()

if "errors" in data:
    sys.exit(f"GraphQL errors: {data['errors']}")

out = Path(__file__).parent.parent / "tests" / "linear_schema.json"
out.write_text(json.dumps(data, indent=2))
n = len(data["data"]["__schema"]["types"])
print(f"Saved {n} types → {out}")
