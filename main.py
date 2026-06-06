import os
import sys
from dotenv import load_dotenv
import anthropic
from linear_client import LinearClient
from agent import LinearAgent

load_dotenv()


def main() -> None:
    linear_key = os.environ.get("LINEAR_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not linear_key:
        sys.exit("Error: LINEAR_API_KEY not set in .env")
    if not anthropic_key:
        sys.exit("Error: ANTHROPIC_API_KEY not set in .env")

    linear = LinearClient(linear_key)
    claude = anthropic.Anthropic(api_key=anthropic_key)
    agent = LinearAgent(linear, claude)

    # Verify credentials on startup
    try:
        viewer = linear.get_viewer()
        print(f"Connected as {viewer['name']} ({viewer['email']})")
    except Exception as exc:
        sys.exit(f"Linear connection failed: {exc}")

    print("Linear Agent ready. Type your request, or 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            break

        reply = agent.chat(user_input)
        if reply:
            print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    main()
