import json
import anthropic
from linear_client import LinearClient
from tools import TOOLS

MODEL = "claude-sonnet-4-6"

SYSTEM = """You are a Linear project management assistant. You help users manage their \
Linear workspace through natural language.

You have tools to read and write issues, comments, projects, teams, and workflow states. \
When you need a UUID (team ID, state ID, assignee ID) that you don't have yet, fetch it \
first with the appropriate list tool before acting.

Priority scale: 0=No priority  1=Urgent  2=High  3=Medium  4=Low

After completing any write action, confirm what changed in one concise sentence."""


class LinearAgent:
    def __init__(self, linear: LinearClient, claude: anthropic.Anthropic):
        self.linear = linear
        self.claude = claude
        self.history: list[dict] = []

    # ── Tool dispatch ─────────────────────────────────────────────────────────

    def _run_tool(self, name: str, inputs: dict) -> str:
        try:
            match name:
                case "get_viewer":
                    result = self.linear.get_viewer()
                case "list_teams":
                    result = self.linear.list_teams()
                case "list_workflow_states":
                    result = self.linear.list_workflow_states(**inputs)
                case "list_issues":
                    result = self.linear.list_issues(**inputs)
                case "get_issue":
                    result = self.linear.get_issue(inputs["issue_id"])
                case "search_issues":
                    result = self.linear.search_issues(
                        inputs["query"], inputs.get("limit", 25)
                    )
                case "create_issue":
                    result = self.linear.create_issue(**inputs)
                case "update_issue":
                    issue_id = inputs["issue_id"]
                    rest = {k: v for k, v in inputs.items() if k != "issue_id"}
                    result = self.linear.update_issue(issue_id, **rest)
                case "delete_issue":
                    result = self.linear.delete_issue(inputs["issue_id"])
                case "add_comment":
                    result = self.linear.add_comment(inputs["issue_id"], inputs["body"])
                case "list_projects":
                    result = self.linear.list_projects(inputs.get("team_id"))
                case _:
                    return json.dumps({"error": f"unknown tool: {name}"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(result, default=str)

    # ── Agent loop ────────────────────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        while True:
            response = self.claude.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM,
                tools=TOOLS,
                messages=self.history,
            )

            self.history.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b.text for b in response.content if b.type == "text"]

            if response.stop_reason == "end_turn" or not tool_uses:
                return "\n".join(text_blocks)

            tool_results = []
            for tu in tool_uses:
                print(f"  [tool] {tu.name}  {json.dumps(tu.input, ensure_ascii=False)}")
                output = self._run_tool(tu.name, dict(tu.input))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": output,
                })

            self.history.append({"role": "user", "content": tool_results})
