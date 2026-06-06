import httpx

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearError(Exception):
    pass


class LinearClient:
    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

    def _query(self, query: str, variables: dict | None = None) -> dict:
        response = httpx.post(
            LINEAR_API_URL,
            headers=self._headers,
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise LinearError(data["errors"][0]["message"])
        return data.get("data", {})

    # ── Identity ──────────────────────────────────────────────────────────────

    def get_viewer(self) -> dict:
        data = self._query("query { viewer { id name email } }")
        return data["viewer"]

    # ── Teams ─────────────────────────────────────────────────────────────────

    def list_teams(self) -> list[dict]:
        data = self._query("""
            query {
                teams {
                    nodes { id name key description }
                }
            }
        """)
        return data["teams"]["nodes"]

    def list_members(self, team_id: str) -> list[dict]:
        data = self._query("""
            query($teamId: String!) {
                team(id: $teamId) {
                    members {
                        nodes { id name email displayName }
                    }
                }
            }
        """, {"teamId": team_id})
        return data["team"]["members"]["nodes"]

    # ── Workflow states ───────────────────────────────────────────────────────

    def list_workflow_states(self, team_id: str) -> list[dict]:
        data = self._query("""
            query($teamId: String!) {
                workflowStates(filter: { team: { id: { eq: $teamId } } }) {
                    nodes { id name type color }
                }
            }
        """, {"teamId": team_id})
        return data["workflowStates"]["nodes"]

    # ── Issues ────────────────────────────────────────────────────────────────

    def list_issues(
        self,
        team_id: str | None = None,
        assignee_id: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        filters = []
        if team_id:
            filters.append(f'team: {{ id: {{ eq: "{team_id}" }} }}')
        if assignee_id:
            filters.append(f'assignee: {{ id: {{ eq: "{assignee_id}" }} }}')
        if state:
            filters.append(f'state: {{ name: {{ eq: "{state}" }} }}')

        filter_arg = f"filter: {{ {', '.join(filters)} }}, " if filters else ""

        data = self._query(f"""
            query {{
                issues({filter_arg}first: {limit}, orderBy: updatedAt) {{
                    nodes {{
                        id identifier title priority
                        state   {{ name }}
                        assignee {{ id name email }}
                        team     {{ id name key }}
                        createdAt updatedAt
                    }}
                }}
            }}
        """)
        return data["issues"]["nodes"]

    def get_issue(self, issue_id: str) -> dict:
        data = self._query("""
            query($id: String!) {
                issue(id: $id) {
                    id identifier title description priority
                    state    { name }
                    assignee { id name email }
                    team     { id name key }
                    project  { id name }
                    comments { nodes { id body createdAt user { name } } }
                    createdAt updatedAt
                }
            }
        """, {"id": issue_id})
        return data["issue"]

    def search_issues(self, query: str, limit: int = 25) -> list[dict]:
        data = self._query("""
            query($term: String!, $limit: Int!) {
                issueSearch(query: $term, first: $limit) {
                    nodes {
                        id identifier title priority
                        state    { name }
                        assignee { name }
                        team     { name key }
                    }
                }
            }
        """, {"term": query, "limit": limit})
        return data["issueSearch"]["nodes"]

    def create_issue(
        self,
        team_id: str,
        title: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        state_id: str | None = None,
        project_id: str | None = None,
    ) -> dict:
        input_data: dict = {"teamId": team_id, "title": title}
        if description is not None:
            input_data["description"] = description
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if priority is not None:
            input_data["priority"] = priority
        if state_id is not None:
            input_data["stateId"] = state_id
        if project_id is not None:
            input_data["projectId"] = project_id

        data = self._query("""
            mutation($input: IssueCreateInput!) {
                issueCreate(input: $input) {
                    success
                    issue {
                        id identifier title priority
                        state { name }
                        team  { name key }
                    }
                }
            }
        """, {"input": input_data})
        if not data["issueCreate"]["success"]:
            raise LinearError("issueCreate returned success=false")
        return data["issueCreate"]["issue"]

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
    ) -> dict:
        input_data: dict = {}
        if title is not None:
            input_data["title"] = title
        if description is not None:
            input_data["description"] = description
        if state_id is not None:
            input_data["stateId"] = state_id
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if priority is not None:
            input_data["priority"] = priority

        if not input_data:
            raise ValueError("update_issue called with no fields to update")

        data = self._query("""
            mutation($id: String!, $input: IssueUpdateInput!) {
                issueUpdate(id: $id, input: $input) {
                    success
                    issue {
                        id identifier title priority
                        state    { name }
                        assignee { name }
                    }
                }
            }
        """, {"id": issue_id, "input": input_data})
        if not data["issueUpdate"]["success"]:
            raise LinearError("issueUpdate returned success=false")
        return data["issueUpdate"]["issue"]

    def delete_issue(self, issue_id: str) -> bool:
        data = self._query("""
            mutation($id: String!) {
                issueDelete(id: $id) { success }
            }
        """, {"id": issue_id})
        return data["issueDelete"]["success"]

    # ── Comments ──────────────────────────────────────────────────────────────

    def add_comment(self, issue_id: str, body: str) -> dict:
        data = self._query("""
            mutation($input: CommentCreateInput!) {
                commentCreate(input: $input) {
                    success
                    comment { id body createdAt }
                }
            }
        """, {"input": {"issueId": issue_id, "body": body}})
        if not data["commentCreate"]["success"]:
            raise LinearError("commentCreate returned success=false")
        return data["commentCreate"]["comment"]

    # ── Projects ──────────────────────────────────────────────────────────────

    def list_projects(self, team_id: str | None = None) -> list[dict]:
        filter_arg = (
            f'filter: {{ teams: {{ id: {{ eq: "{team_id}" }} }} }}, '
            if team_id else ""
        )
        data = self._query(f"""
            query {{
                projects({filter_arg}first: 50) {{
                    nodes {{
                        id name description state
                        teams {{ nodes {{ name key }} }}
                    }}
                }}
            }}
        """)
        return data["projects"]["nodes"]
