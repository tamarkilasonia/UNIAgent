"""SQLite storage for UniAgent: mock students and their IT support tickets.

This module is plain data access. The rules about who may see what live in
the MCP server (mcp_server/server.py), which is the only way the agent can
reach this data.

Reset the database to the original mock data with:

    python -m database.database
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "uniagent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    user_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    email          TEXT NOT NULL,
    account_status TEXT NOT NULL,  -- 'active' or 'locked'
    email_status   TEXT NOT NULL,  -- 'active' or 'inactive'
    wifi_status    TEXT NOT NULL   -- 'active' or 'blocked'
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL REFERENCES students(user_id),
    issue       TEXT NOT NULL,     -- 'account', 'email', 'wifi' or 'other'
    description TEXT NOT NULL,
    status      TEXT NOT NULL,     -- 'open', 'in_progress' or 'resolved'
    created_at  TEXT NOT NULL
);
"""

# Mock data only - these are not real people.
MOCK_STUDENTS = [
    # (user_id, name, email, account_status, email_status, wifi_status)
    ("S1001", "Alice Johnson", "alice.johnson@uni.example.edu", "active", "active", "active"),
    ("S1002", "Bob Smith", "bob.smith@uni.example.edu", "active", "inactive", "active"),
    ("S1003", "Carla Gomez", "carla.gomez@uni.example.edu", "locked", "active", "blocked"),
]

MOCK_TICKETS = [
    # (id, user_id, issue, description, status, created_at)
    (100, "S1001", "wifi", "Wi-Fi keeps disconnecting in the library.", "resolved", "2026-09-14 10:30"),
    (101, "S1003", "account", "Locked out after changing my password.", "in_progress", "2026-10-01 09:15"),
]


def get_db_path() -> Path:
    """Where the database file lives. Tests point UNIAGENT_DB_PATH at a temporary file."""
    return Path(os.getenv("UNIAGENT_DB_PATH", DEFAULT_DB_PATH))


@contextmanager
def connect():
    """Open the database, commit if everything went well, and always close it."""
    connection = sqlite3.connect(get_db_path())
    connection.row_factory = sqlite3.Row  # lets us read columns by name
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(reset: bool = False) -> None:
    """Create the tables and add the mock data if the database is empty."""
    path = get_db_path()
    if reset and path.exists():
        path.unlink()

    with connect() as conn:
        conn.executescript(SCHEMA)
        student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        if student_count == 0:
            conn.executemany("INSERT INTO students VALUES (?, ?, ?, ?, ?, ?)", MOCK_STUDENTS)
            conn.executemany("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)", MOCK_TICKETS)


def get_student(user_id: str) -> dict | None:
    """Return one student as a dict, or None if the ID doesn't exist."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM students WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_ticket(user_id: str, issue: str, description: str) -> dict:
    """Store a new open ticket and return it."""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO tickets (user_id, issue, description, status, created_at) "
            "VALUES (?, ?, ?, 'open', ?)",
            (user_id, issue, description, created_at),
        )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _ticket_to_dict(row)


def get_ticket(user_id: str, ticket_number: int) -> dict | None:
    """Return a ticket only if it belongs to this student, otherwise None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE id = ? AND user_id = ?", (ticket_number, user_id)
        ).fetchone()
    return _ticket_to_dict(row) if row else None


def list_tickets(user_id: str) -> list[dict]:
    """Return all of this student's tickets, newest first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tickets WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
    return [_ticket_to_dict(row) for row in rows]


def _ticket_to_dict(row: sqlite3.Row) -> dict:
    """Shape a ticket row for the outside world, e.g. id 102 -> "T-102"."""
    return {
        "ticket_id": f"T-{row['id']}",
        "issue": row["issue"],
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Database reset with mock data: {get_db_path()}")
