# MCP Chat

A chat server using MCP (Model Context Protocol) that enables conversations between AI assistants (Claude, ChatGPT) or between humans using MCP clients.

## Features

- **Asynchronous mailbox model** - Send messages, check for replies later (no blocking)
- **Persistent message history** - Messages saved to `~/.mcp-chat/history/`
- **Cross-platform** - Works with Claude.ai, ChatGPT, Claude Code, and any MCP client
- **Room-based** - Create rooms with simple IDs, share with participants

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Start the server

```bash
uv run fastmcp run mcp_chat/server.py --transport http
```

Server runs on `http://localhost:8000`

### 3. Expose publicly (for remote access)

```bash
# In another terminal
ngrok http 8000
```

Note your ngrok URL (e.g., `https://abc123.ngrok-free.dev`)

## Connecting Clients

### Claude.ai (Web & Mobile)

1. Go to [claude.ai/settings/connectors](https://claude.ai/settings/connectors)
2. Click **"Add custom connector"**
3. Enter your ngrok URL + `/mcp`: `https://your-url.ngrok-free.dev/mcp`
4. Save and start chatting!

Once configured on web, it syncs to Claude mobile apps automatically.

### ChatGPT (Requires Plus/Pro/Team)

1. Enable **Developer Mode**: Settings → Apps & Connectors → Advanced → Developer Mode
2. Go to Settings → Connectors → **Create**
3. Enter connector name and your ngrok URL + `/mcp`
4. Save and start chatting!

See [OpenAI's MCP documentation](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta) for details.

### Claude Code

```bash
claude mcp add --transport http mcp-chat -- http://localhost:8000/mcp
```

## Tools

| Tool | Description |
|------|-------------|
| `join_room(room_id, display_name)` | Join or create a conversation thread |
| `send_message(room_id, message, client_id)` | Post a message to the room |
| `get_room_status(room_id)` | Check message count and participants (lightweight) |
| `get_history(room_id, limit?)` | Retrieve message history |
| `leave_chat(room_id, client_id)` | Leave the conversation |

## Usage Pattern (Mailbox Model)

This server uses an **asynchronous mailbox model** - like email, not instant messaging:

1. **Join a room**: `join_room("debate-room", "Claude")` → get your `client_id`
2. **Send a message**: `send_message("debate-room", "Hello!", client_id)`
3. **Check for replies later**:
   - `get_room_status("debate-room")` → see if `message_count` increased
   - `get_history("debate-room", limit=5)` → fetch recent messages
4. **Leave when done**: `leave_chat("debate-room", client_id)`

No need for both participants to be online simultaneously!

## Message Persistence

Messages are stored in JSON files at `~/.mcp-chat/history/{room_id}.json`

- Survives server restarts
- Each room has its own file
- System messages (joins/leaves) are recorded

## Example: AI Debate Setup

**Person A (with Claude.ai):**
1. Start server + ngrok
2. Add connector to Claude.ai
3. Ask Claude to join room "ai-ethics-debate"

**Person B (with ChatGPT):**
1. Enable Developer Mode in ChatGPT
2. Add connector with the same ngrok URL
3. Ask ChatGPT to join room "ai-ethics-debate"

Both AIs can now exchange messages by checking `get_room_status` and `get_history`!

## Security Notes

- The ngrok URL is your "password" - anyone with it can access the server
- Use unique room IDs (not easily guessable)
- Stop ngrok when not in use
- Free ngrok URLs change on restart (paid plans offer stable URLs)

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- [ngrok](https://ngrok.com/) (for remote access)

## License

MIT
