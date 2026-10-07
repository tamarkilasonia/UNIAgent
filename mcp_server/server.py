"""UniAgent MCP server.

MCP (Model Context Protocol) is a standard way to offer tools to AI
applications. This server offers five university IT support tools. Any MCP
client can discover them and call them by name; UniAgent's LangGraph agent
is one such client.

The server is also the security boundary. Every tool only returns data for
the `user_id` it is given, and tickets are always looked up together with
their owner, so one student can never read another student's ticket.

Run it on its own with:

    python -m mcp_server.server

It then speaks MCP over stdin/stdout (the "stdio" transport).
"""

from typing import Literal

from mcp.server.mcpserver import MCPServer

from database import database as db

mcp = MCPServer("uniagent", log_level="WARNING")

MAX_DESCRIPTION_LENGTH = 1000

# Plain-language explanations returned with each status, so the agent can
# explain a problem from facts we give it instead of guessing.
ACCOUNT_DETAILS = {
    "active": "The account is active and working normally.",
    "locked": "The account is locked, usually after too many failed login attempts. "
    "IT support can unlock it.",
}
EMAIL_DETAILS = {
    "active": "The mailbox is active and can send and receive email.",
    "inactive": "The mailbox is inactive, so email cannot be sent or received. "
    "IT support can reactivate it.",
}
WIFI_DETAILS = {
    "active": "Campus Wi-Fi access is enabled for this account. If Wi-Fi still fails, "
    "the problem is probably the device or the location.",
    "blocked": "Campus Wi-Fi access is blocked for this account. IT support can restore it.",
}


def unknown_student(user_id: str) -> dict:
    return {"error": f"No student found with ID {user_id}."}


@mcp.tool()
def check_account_status(user_id: str) -> dict:
    """Check the student's university account: whether it is active or locked."""
    student = db.get_student(user_id)
    if student is None:
        return unknown_student(user_id)

    status = student["account_status"]
    return {
        "name": student["name"],
        "email": student["email"],
        "account_status": status,
        "details": ACCOUNT_DETAILS[status],
    }


@mcp.tool()
def check_email_status(user_id: str) -> dict:
    """Check whether the student's university email is working."""
    student = db.get_student(user_id)
    if student is None:
        return unknown_student(user_id)

    status = student["email_status"]
    return {"email": student["email"], "email_status": status, "details": EMAIL_DETAILS[status]}


@mcp.tool()
def check_wifi_status(user_id: str) -> dict:
    """Check whether the student has access to the campus Wi-Fi."""
    student = db.get_student(user_id)
    if student is None:
        return unknown_student(user_id)

    status = student["wifi_status"]
    return {"wifi_status": status, "details": WIFI_DETAILS[status]}


@mcp.tool()
def create_ticket(
    user_id: str,
    issue: Literal["account", "email", "wifi", "other"],
    description: str,
) -> dict:
    """Create an IT support ticket for the student.

    `issue` is the area of the problem. `description` is one or two sentences
    describing what is wrong.
    """
    if db.get_student(user_id) is None:
        return unknown_student(user_id)

    description = description.strip()
    if not description:
        return {"error": "The ticket description cannot be empty."}
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return {"error": f"The description is too long (max {MAX_DESCRIPTION_LENGTH} characters)."}

    ticket = db.create_ticket(user_id, issue, description)
    return {"message": "Ticket created.", "ticket": ticket}


@mcp.tool()
def get_ticket_status(user_id: str, ticket_id: str | None = None) -> dict:
    """Look up the student's support tickets.

    Pass a ticket ID such as "T-102" to get one ticket, or leave it out to
    list all of the student's tickets.
    """
    if db.get_student(user_id) is None:
        return unknown_student(user_id)

    if not ticket_id:
        return {"tickets": db.list_tickets(user_id)}

    ticket_number = parse_ticket_number(ticket_id)
    if ticket_number is None:
        return {"error": f"'{ticket_id}' is not a valid ticket ID. Ticket IDs look like T-102."}

    # AUTHORIZATION: the lookup matches on ticket number AND owner. Another
    # student's ticket gets the same answer as a ticket that doesn't exist,
    # so this tool doesn't even reveal which ticket IDs are in use.
    ticket = db.get_ticket(user_id, ticket_number)
    if ticket is None:
        return {"error": f"Ticket T-{ticket_number} was not found on your account."}
    return {"ticket": ticket}


def parse_ticket_number(ticket_id: str) -> int | None:
    """Turn "T-102", "t-102" or "102" into 102. Returns None for anything else."""
    text = ticket_id.strip().upper().removeprefix("T-")
    return int(text) if text.isdigit() else None


if __name__ == "__main__":
    db.init_db()
    mcp.run()  # stdio transport: MCP messages over stdin/stdout
