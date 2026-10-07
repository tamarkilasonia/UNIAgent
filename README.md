# UniAgent

UniAgent is an AI support agent for university IT problems. A student chats with it in the terminal. The agent decides which tools it needs, calls them through an **MCP server**, and answers in plain language. It can check the student's account, email and Wi-Fi, and it can create and look up support tickets.

It is a small, complete example of:

- an **AI agent** built with **LangGraph**
- **tool calling** with Claude
- tools served over **MCP (Model Context Protocol)**
- a **SQLite** database of mock students and tickets
- simple **authorization**: a student can only ever reach their own data

All data is mock data.

## Architecture

```text
User (CLI: app.py)
 ↓
LangGraph agent (agent/graph.py)       decides what to do, calls Claude
 ↓
MCP client (agent/mcp_client.py)       starts the server, sends tool calls
 ↓   MCP over stdin/stdout
MCP server (mcp_server/server.py)      exposes the tools, enforces authorization
 ↓
Tools
 ↓
SQLite (database/database.py)          mock students and tickets
```

This is what happens when a student types *"My university email is not working."*:

1. `app.py` sends the message to the LangGraph agent.
2. The **agent node** sends the conversation and the list of tools to Claude.
3. Claude replies that it wants to call `check_email_status`.
4. The **tools node** adds the logged-in student's ID and calls the tool on the MCP server.
5. The MCP server reads the student's row from SQLite and returns `{"email_status": "inactive", ...}`.
6. The result goes back to Claude, which writes the answer: *"Your email is currently inactive. Would you like me to create a support ticket?"*

## How the LangGraph agent works

The agent is a graph with two nodes that loop until Claude has an answer:

```text
START ──> agent ──(Claude asked for a tool)──> tools ──┐
            ↑                                          │
            └──────────────────────────────────────────┘
          agent ──(Claude answered)──> END
```

- **State** (`AgentState`) holds the logged-in `user_id` and the list of `messages`. The messages are in the Claude API's own format, so the state holds exactly what is sent to the API.
- **`agent` node**: calls Claude with the system prompt, the tools and the conversation so far. The reply is either text for the student or one or more `tool_use` requests.
- **`tools` node**: runs each requested tool on the MCP server and adds the results to the conversation as `tool_result` messages.
- **Conditional edge** (`route_after_agent`): if Claude's last message contains a tool call, go to `tools`; otherwise end the turn.
- **Memory**: the graph is compiled with a checkpointer (`InMemorySaver`). It stores each conversation by `thread_id`, so the agent remembers earlier messages (for example, when the student answers "Yes" to the ticket offer).

The model is `claude-opus-5-5` at `low` effort, which is enough for short support chats. You can change the model with `UNIAGENT_MODEL` in `.env`.

## What MCP does in this project

MCP (Model Context Protocol) is an open standard for connecting AI applications to tools and data. Here it separates **the agent** from **the tools**:

- The **MCP server** (`mcp_server/server.py`) defines the five tools with the official `mcp` Python SDK. Each tool is a normal Python function with a `@mcp.tool()` decorator. The SDK turns its type hints and docstring into a tool description and a JSON input schema.
- The **MCP client** (`agent/mcp_client.py`) starts the server as a subprocess and talks to it over stdin/stdout (the *stdio transport*).
- At startup the agent **discovers** the tools with `list_tools()`. It doesn't hard-code them, so a new tool on the server becomes available to the agent without changing the agent code.
- Any other MCP client could use the same server, for example a desktop AI app.

## Available tools

| Tool | What it does |
|---|---|
| `check_account_status(user_id)` | Is the account active or locked? Also returns the student's name and email. |
| `check_email_status(user_id)` | Is the university mailbox active or inactive? |
| `check_wifi_status(user_id)` | Does the student have campus Wi-Fi access? |
| `create_ticket(user_id, issue, description)` | Creates a support ticket. `issue` is one of `account`, `email`, `wifi`, `other`. |
| `get_ticket_status(user_id, ticket_id)` | Returns one ticket (e.g. `T-102`). Leave out `ticket_id` to list all of the student's tickets. |

Each status comes with a short plain-language `details` field, so the agent can explain a problem from facts instead of guessing.

## Safety and authorization

The main rule is that **the AI model is not trusted to decide whose data it reads.**

1. **The model never sees `user_id`.** When the agent turns the MCP tools into Claude tools (`to_claude_tool` in `agent/graph.py`), it removes `user_id` from every input schema.
2. **The app fills in the identity.** The `tools` node adds the logged-in student's ID to every tool call. This overrides any `user_id` the model might try to pass.
3. **The server checks ownership.** Tickets are looked up by ticket number *and* owner (`WHERE id = ? AND user_id = ?`). Another student's ticket gets the same answer as a ticket that doesn't exist: *"Ticket T-100 was not found on your account."* So the tool doesn't even reveal which ticket IDs exist.
4. **The model doesn't invent facts.** The system prompt says to report only what tools returned, and to say so when something isn't available through the tools (grades, exam dates and so on).
5. **Inputs are validated.** The MCP SDK rejects invalid arguments (such as an unknown `issue` type) before the tool runs, and empty or very long ticket descriptions are refused.

Login is simulated: you type a student ID. A real university would use single sign-on, but the agent would work the same way, because the identity comes from the login, not from the chat.

## Project structure

```text
UNIAgent/
├── agent/
│   ├── graph.py          # LangGraph agent: state, nodes, edges, system prompt
│   └── mcp_client.py     # starts the MCP server and calls its tools
├── mcp_server/
│   └── server.py         # MCP server with the five tools + authorization
├── database/
│   └── database.py       # SQLite schema, mock data and queries
├── tests/
│   ├── test_database.py
│   ├── test_mcp_server.py
│   ├── test_mcp_client.py
│   └── test_agent.py
├── app.py                # command-line chat
├── requirements.txt
├── pytest.ini
├── .env.example
└── README.md
```

## Install and run

You need Python 3.10 or newer and an Anthropic API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then put your ANTHROPIC_API_KEY in .env
python app.py
```

Log in with one of the mock students:

| Student ID | Name | Situation |
|---|---|---|
| `S1001` | Alice Johnson | Everything works. Has a resolved Wi-Fi ticket `T-100`. |
| `S1002` | Bob Smith | Email is inactive. |
| `S1003` | Carla Gomez | Account locked, Wi-Fi blocked. Has an open ticket `T-101`. |

The database (`database/uniagent.db`) is created automatically on first run. To reset it to the original mock data, run:

```bash
python -m database.database
```

## Run the tests

```bash
pytest
```

The tests don't need an API key. In `tests/test_agent.py`, Claude is replaced by a fake that returns scripted responses. Everything else in those tests is real: the LangGraph graph, the MCP server and a temporary SQLite database. The tests check, among other things, that:

- the model never sees a `user_id` parameter
- a `user_id` invented by the model is overridden by the logged-in student's
- a student can't read another student's ticket
- the MCP server works as a real subprocess over stdio, as it does in the app

## Example conversations

The agent's wording varies from run to run. Lines starting with `[MCP tool]` show the tool calls as they happen. No `user_id` appears in them, because the model never provides one.

**Bob's email is down (logged in as `S1002`):**

```text
You: My university email is not working.
  [MCP tool] check_email_status()

Agent: Your university email is currently inactive, so you can't send or
receive messages. IT support can reactivate it. Would you like me to
create a support ticket?

You: Yes.
  [MCP tool] create_ticket(issue='email', description='University mailbox is inactive and cannot send or receive email.')

Agent: Ticket T-102 has been created. You can ask me for its status any time.
```

**Alice asks about someone else's ticket (logged in as `S1001`):**

```text
You: What is the status of ticket T-101?
  [MCP tool] get_ticket_status(ticket_id='T-101')

Agent: I couldn't find ticket T-101 on your account. I can only see your
own tickets. Would you like me to list them?

You: What are my exam grades?

Agent: I don't have access to grades. I can only help with your account,
email, Wi-Fi and support tickets. For anything else, please contact the
university IT help desk.
```
