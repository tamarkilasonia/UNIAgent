"""UniAgent command-line chat.

    python app.py
"""

import asyncio
import os

import anthropic
from dotenv import load_dotenv

from agent.graph import create_agent
from agent.mcp_client import connect_to_server
from database import database as db

DEMO_STUDENTS = [
    ("S1001", "everything works"),
    ("S1002", "email is inactive"),
    ("S1003", "account is locked, Wi-Fi blocked"),
]


def log_in() -> dict | None:
    """Simulated login: look up the student ID that was typed in.

    A real university would use single sign-on (SSO) here. What matters for
    the agent is that the student's identity comes from the login, not from
    the chat.
    """
    user_id = input("Student ID: ").strip().upper()
    return db.get_student(user_id)


def print_reply(message: dict) -> None:
    """Print what the agent said and which MCP tools it called."""
    if message["role"] != "assistant":
        return  # tool results; the agent explains them in its next message

    if isinstance(message["content"], str):
        print(f"\nAgent: {message['content']}")
        return

    for block in message["content"]:
        if block["type"] == "text" and block["text"].strip():
            print(f"\nAgent: {block['text'].strip()}")
        elif block["type"] == "tool_use":
            arguments = ", ".join(f"{name}={value!r}" for name, value in block["input"].items())
            print(f"  [MCP tool] {block['name']}({arguments})")


async def chat(student: dict) -> None:
    """Run the conversation loop for one logged-in student."""
    async with connect_to_server() as mcp_client:
        agent = await create_agent(mcp_client)
        # The checkpointer stores this conversation's history under this thread_id.
        config = {"configurable": {"thread_id": student["user_id"]}}

        while True:
            try:
                text = input("\nYou: ").strip()
            except EOFError:
                break
            if text.lower() in {"quit", "exit"}:
                break
            if not text:
                continue

            turn = {"user_id": student["user_id"], "messages": [{"role": "user", "content": text}]}
            try:
                # stream_mode="updates" yields each node's output as soon as it finishes,
                # so tool calls are printed while the agent is still working.
                async for step in agent.astream(turn, config, stream_mode="updates"):
                    for node_output in step.values():
                        for message in node_output["messages"]:
                            print_reply(message)
            except anthropic.APIError as error:
                print(f"\nAgent: Sorry, the AI service returned an error: {error.message}")


def main() -> None:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        return

    db.init_db()
    print("UniAgent - University IT Support\n")
    print("Demo students:")
    for user_id, description in DEMO_STUDENTS:
        print(f"  {user_id}  ({description})")
    print()

    student = log_in()
    if student is None:
        print("Unknown student ID.")
        return

    print(f"\nHi {student['name']}! Ask me about your account, email, Wi-Fi or tickets.")
    print("Type 'quit' to exit.")
    asyncio.run(chat(student))
    print("\nGoodbye!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # Ctrl+C
        print("\nGoodbye!")
