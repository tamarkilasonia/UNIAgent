"""Tests for the LangGraph agent.

Claude is replaced by FakeClaude, which replays scripted responses, so these
tests need no API key. Everything else is real: the graph, the MCP server
(connected in-process) and the SQLite database.
"""

import asyncio
import json
from types import SimpleNamespace

from anthropic.types.beta import BetaMessage
from mcp import Client

from agent.graph import create_agent
from agent.mcp_client import MCPClient
from mcp_server import server


class FakeClaude:
    """Stands in for AsyncAnthropic: returns scripted responses and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


def claude_says(*content, stop_reason="end_turn"):
    """Build a response object shaped exactly like a real Claude API response."""
    return BetaMessage.model_validate({
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": list(content),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    })


def text(value):
    return {"type": "text", "text": value}


def tool_use(name, arguments, call_id="call_1"):
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


def run_conversation(claude, user_id, *user_messages):
    """Send the messages to the agent one turn at a time and return the final state."""
    async def scenario():
        async with Client(server.mcp) as client:
            agent = await create_agent(MCPClient(client), claude=claude)
            config = {"configurable": {"thread_id": "test"}}
            for message in user_messages:
                turn = {"user_id": user_id, "messages": [{"role": "user", "content": message}]}
                state = await agent.ainvoke(turn, config)
            return state

    return asyncio.run(scenario())


def tool_result_sent_back(request):
    """The tool result the agent sent to Claude in this request, parsed from JSON."""
    result_block = request["messages"][-1]["content"][0]
    assert result_block["type"] == "tool_result"
    return json.loads(result_block["content"])


def test_the_model_never_sees_user_id():
    claude = FakeClaude(claude_says(text("Hello!")))
    run_conversation(claude, "S1002", "Hi")

    tools = claude.requests[0]["tools"]
    assert len(tools) == 5
    for tool in tools:
        assert "user_id" not in tool["input_schema"]["properties"]
        assert "user_id" not in tool["input_schema"]["required"]


def test_agent_calls_a_tool_and_answers_with_the_result():
    claude = FakeClaude(
        claude_says(tool_use("check_email_status", {}), stop_reason="tool_use"),
        claude_says(text("Your email is currently inactive.")),
    )
    state = run_conversation(claude, "S1002", "My university email is not working.")

    # The agent ran the tool for the logged-in student and passed the result to Claude.
    assert tool_result_sent_back(claude.requests[1])["email_status"] == "inactive"
    # Claude's final answer is the last message in the conversation.
    assert state["messages"][-1]["content"] == [text("Your email is currently inactive.")]


def test_agent_ignores_a_user_id_chosen_by_the_model():
    # Bob (S1002) is logged in. The model tries to read Carla's (S1003) ticket T-101.
    claude = FakeClaude(
        claude_says(
            tool_use("get_ticket_status", {"ticket_id": "T-101", "user_id": "S1003"}),
            stop_reason="tool_use",
        ),
        claude_says(text("I couldn't find that ticket on your account.")),
    )
    run_conversation(claude, "S1002", "What is the status of ticket T-101?")

    # The tools node replaced the user_id with Bob's, so the server refused.
    assert tool_result_sent_back(claude.requests[1]) == {
        "error": "Ticket T-101 was not found on your account."
    }


def test_agent_creates_a_ticket_after_the_student_says_yes():
    claude = FakeClaude(
        claude_says(text("Your email is inactive. Would you like me to create a ticket?")),
        claude_says(
            tool_use("create_ticket", {"issue": "email", "description": "Mailbox is inactive."}),
            stop_reason="tool_use",
        ),
        claude_says(text("Ticket T-102 has been created.")),
    )
    run_conversation(claude, "S1002", "My email is broken.", "Yes.")

    assert tool_result_sent_back(claude.requests[2])["ticket"]["ticket_id"] == "T-102"
    assert server.get_ticket_status("S1002", "T-102")["ticket"]["issue"] == "email"


def test_agent_remembers_earlier_turns():
    claude = FakeClaude(claude_says(text("Hi Bob!")), claude_says(text("You said hello.")))
    run_conversation(claude, "S1002", "Hello", "What did I just say?")

    second_request = claude.requests[1]["messages"]
    assert [message["role"] for message in second_request] == ["user", "assistant", "user"]
    assert second_request[0]["content"] == "Hello"


def test_agent_handles_a_refusal_politely():
    claude = FakeClaude(claude_says(stop_reason="refusal"))
    state = run_conversation(claude, "S1002", "Something the model declines")

    assert state["messages"][-1] == {
        "role": "assistant",
        "content": "Sorry, I can't help with that request.",
    }
