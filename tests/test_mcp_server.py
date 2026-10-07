"""Tests for the MCP tools, including the authorization rules."""

import asyncio

from mcp import Client

from mcp_server import server


# --- The tools themselves (called as plain Python functions) ---

def test_check_account_status():
    result = server.check_account_status("S1003")
    assert result["account_status"] == "locked"
    assert "unlock" in result["details"]


def test_check_email_status():
    assert server.check_email_status("S1002")["email_status"] == "inactive"
    assert server.check_email_status("S1001")["email_status"] == "active"


def test_check_wifi_status():
    assert server.check_wifi_status("S1003")["wifi_status"] == "blocked"


def test_unknown_student_gets_an_error():
    assert "error" in server.check_email_status("S9999")


def test_create_ticket_and_read_it_back():
    created = server.create_ticket("S1002", "email", "My mailbox is inactive.")
    ticket_id = created["ticket"]["ticket_id"]

    result = server.get_ticket_status("S1002", ticket_id)
    assert result["ticket"]["status"] == "open"
    assert result["ticket"]["description"] == "My mailbox is inactive."


def test_create_ticket_needs_a_description():
    assert "error" in server.create_ticket("S1002", "email", "   ")


def test_ticket_ids_are_parsed_flexibly():
    assert server.parse_ticket_number("T-102") == 102
    assert server.parse_ticket_number(" t-102 ") == 102
    assert server.parse_ticket_number("102") == 102
    assert server.parse_ticket_number("hello") is None


# --- Authorization ---

def test_student_cannot_see_another_students_ticket():
    # T-100 belongs to S1001. For S1002 it looks exactly like a ticket that doesn't exist.
    assert server.get_ticket_status("S1002", "T-100") == {
        "error": "Ticket T-100 was not found on your account."
    }
    assert server.get_ticket_status("S1002", "T-999") == {
        "error": "Ticket T-999 was not found on your account."
    }


def test_listing_tickets_only_shows_own_tickets():
    tickets = server.get_ticket_status("S1003")["tickets"]
    assert [t["ticket_id"] for t in tickets] == ["T-101"]


# --- Over MCP ---

def test_server_offers_five_tools_over_mcp():
    async def scenario():
        async with Client(server.mcp) as client:  # in-process MCP connection
            return (await client.list_tools()).tools

    names = {tool.name for tool in asyncio.run(scenario())}
    assert names == {
        "check_account_status",
        "check_email_status",
        "check_wifi_status",
        "create_ticket",
        "get_ticket_status",
    }


def test_mcp_rejects_an_invalid_issue_type():
    async def scenario():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                "create_ticket", {"user_id": "S1002", "issue": "pizza", "description": "Hungry."}
            )

    assert asyncio.run(scenario()).is_error
