# rushd

**A CLI tool for managing multiple Claude Code instances via tmux.**

> **Warning**: This is a personal project under active development. The API, commands, and behavior may change wildly between versions without notice. Use at your own risk.

---

## Overview

`rushd` lets you spawn, monitor, and control multiple [Claude Code](https://claude.ai/claude-code) instances from a single terminal. Each instance runs in its own tmux window, and rushd provides both a CLI and an interactive TUI for managing them.

**Key Features:**
- Start multiple Claude Code instances with different working directories
- Send messages to instances without attaching to their terminals
- View structured activity logs (thinking, tool use, responses) or raw terminal output
- Interactive TUI for real-time monitoring and control
- **Discord as a first-class interface** — slash commands, interactive buttons, multi-instance support
- Auto-approve mode bypasses all permission prompts by default

---

## Installation

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
cd ~/rushd
uv tool install -e .
```

Or install directly:

```bash
uv tool install git+https://github.com/YOUR_USERNAME/rushd.git
```

**Dependencies:**
- `tmux` (must be installed and available in PATH)
- `claude` CLI (Claude Code must be installed)

---

## Quick Start

```bash
# Launch interactive TUI
rushd

# Or use CLI commands directly
rushd start -n my-project -d ~/projects/myapp
rushd list
rushd send my-project "explain the codebase structure"
rushd view my-project --activity
rushd stop my-project
```

---

## Commands

### Instance Lifecycle

#### `rushd start`
Start a new Claude Code instance.

```bash
rushd start [OPTIONS]

Options:
  -n, --name NAME       User-friendly name for the instance
  -d, --dir PATH        Working directory (defaults to current)
  -m, --model MODEL     Claude model to use
  -p, --prompt TEXT     Initial prompt to send on startup
  --resume ID           Resume a previous Claude Code session
  --interactive         Disable auto-approve (manual permission control)
```

**Examples:**
```bash
# Start with a name and directory
rushd start -n frontend -d ~/projects/webapp/frontend

# Start with an initial prompt
rushd start -n api-work -d ~/api -p "review the authentication middleware"

# Start in interactive mode (prompts require manual approval)
rushd start -n careful-work --interactive
```

By default, instances start with `--dangerously-skip-permissions` which auto-approves all trust and permission prompts. Use `--interactive` to disable this.

---

#### `rushd list`
List all managed instances.

```bash
rushd list [OPTIONS]

Options:
  --all    Include stopped instances
  --json   Output as JSON
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━ Claude Code Instances ━━━━━━━━━━━━━━━━━━━━━┓
┃ #  │ ID       │ Name     │ Status  │ Directory               ┃
┡━━━━┿━━━━━━━━━━┿━━━━━━━━━━┿━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1  │ a7f3b2c1 │ frontend │ running │ /home/admin/webapp      │
│ 2  │ b8e4c3d2 │ backend  │ running │ /home/admin/api         │
└────┴──────────┴──────────┴─────────┴─────────────────────────┘
```

---

#### `rushd stop`
Stop a Claude Code instance.

```bash
rushd stop INSTANCE [OPTIONS]

Arguments:
  INSTANCE    Instance name or ID to stop

Options:
  --all       Stop all running instances
  --force     Force kill without graceful shutdown (skip Ctrl+C)
```

**Examples:**
```bash
rushd stop frontend
rushd stop a7f3b2c1
rushd stop --all
rushd stop backend --force
```

---

#### `rushd cleanup`
Stop all instances and remove the tmux session entirely.

```bash
rushd cleanup [OPTIONS]

Options:
  --force    Skip confirmation prompt
```

---

### Interaction

#### `rushd send`
Send a message to an instance.

```bash
rushd send INSTANCE MESSAGE [OPTIONS]

Arguments:
  INSTANCE    Instance name or ID
  MESSAGE     Message text to send

Options:
  --file PATH    Read message from a file instead
```

**Examples:**
```bash
rushd send frontend "add dark mode support to the theme"
rushd send backend --file ~/prompts/review-checklist.txt
rushd send api-work "1"  # Send a numbered selection (e.g., for prompts)
```

---

#### `rushd view`
View output from an instance.

```bash
rushd view INSTANCE [OPTIONS]

Arguments:
  INSTANCE    Instance name or ID

Options:
  --lines N       Number of lines to show (default: 50)
  -f, --follow    Continuously follow output (like tail -f)
  --activity      Show structured activity from logs (default: raw terminal)
```

**Examples:**
```bash
# View raw terminal output
rushd view frontend

# View structured activity (thinking, tools, responses)
rushd view frontend --activity

# Follow output in real-time
rushd view frontend -f --activity
```

**Structured Activity View:**
```
👤 explain the authentication flow
🤔 Let me explore the authentication implementation...
🔧 Glob: src/**/auth*.py
   ✓ Found 4 files
🔧 Read: src/auth/middleware.py
   ✓ 145 lines
💬 The authentication flow works as follows...
```

---

#### `rushd attach`
Attach directly to an instance's tmux window.

```bash
rushd attach INSTANCE
```

This hands control to tmux. Use `Ctrl+B D` to detach and return to your shell.

---

### Information

#### `rushd status`
Show detailed status of an instance.

```bash
rushd status INSTANCE
```

**Output:**
```
Instance: frontend
  ID: a7f3b2c1
  Full ID: a7f3b2c1-d4e5-6f7g-8h9i-j0k1l2m3n4o5
  Status: running
  Directory: /home/admin/webapp
  Tmux Window: rushd-instances:1
  Created: 2026-01-27 10:30:00
  Last Activity: 2026-01-27 11:45:30
  Claude Session: abc123-def4-5678-9012-ghijklmnopqr
  Auto-Approve: True
  Display Mode: activity
```

---

#### `rushd log`
Show the path to an instance's Claude Code conversation log.

```bash
rushd log INSTANCE
```

**Output:**
```
Log file: /home/admin/.claude/projects/-home-admin-webapp/abc123-def4-5678-9012-ghijklmnopqr.jsonl
```

Useful for debugging or manually inspecting the raw conversation logs.

---

## Interactive TUI

Running `rushd` with no arguments launches the interactive terminal UI.

```bash
rushd
# or explicitly:
rushd -i
```

### TUI Layout

```
┌─ rushd ──────────────────────────────────────────────────────────┐
│ Instances: [1] frontend* [2] backend [3] api-work    [+] New     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ 👤 explain the codebase structure                                │
│ 🤔 Let me explore the project to understand its structure...     │
│ 🔧 Glob: **/*.py                                                 │
│    ✓ Found 45 files                                              │
│ 🔧 Read: src/main.py                                             │
│    ✓ 234 lines                                                   │
│ 💬 This is a FastAPI application with the following structure... │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ > Type message, or: /switch N, /new, /stop, /list, /quit         │
└──────────────────────────────────────────────────────────────────┘
```

### TUI Commands

| Command | Description |
|---------|-------------|
| `/new [-n name] [-d dir]` | Create a new instance |
| `/switch N` or `/N` | Switch to instance by number (e.g., `/1`, `/2`) |
| `/switch name` | Switch to instance by name |
| `/stop [name]` | Stop instance (current if none specified) |
| `/list` or `/ls` | List all instances |
| `/attach` or `/a` | Attach to current instance's tmux (Ctrl+B D to return) |
| `/activity` | Switch to structured activity view (default) |
| `/raw` | Switch to raw terminal output view |
| `/help` or `/h` | Show help |
| `/quit` or `/q` | Exit rushd |

### TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+N` | Create new instance |
| `Ctrl+C` | Quit |
| `Escape` | Clear input |
| `Enter` | Send message to selected instance |

### Display Modes

**Activity Mode** (default): Shows parsed conversation logs with icons:
- 👤 User messages
- 🤔 Claude's thinking
- 🔧 Tool usage (Read, Write, Bash, etc.)
- ✓/✗ Tool results (success/error)
- 💬 Claude's text responses

**Raw Mode**: Shows actual terminal output from the tmux pane, including all formatting and escape sequences.

---

## Architecture

### Package Structure

```
rushd/
├── pyproject.toml          # Package configuration
├── README.md               # This file
└── src/rushd/
    ├── __init__.py
    ├── cli.py              # CLI commands (fire-based, thin wrapper)
    ├── commands.py          # Shared command handlers (used by CLI + Discord)
    ├── tui.py              # Interactive TUI (textual-based)
    ├── manager.py          # ClaudeInstanceManager - main orchestration
    ├── models.py           # Pydantic data models
    ├── store.py            # JSON persistence (~/.rushd/instances.json)
    ├── config.py           # Configuration management (~/.rushd/config.json)
    ├── tmux.py             # TmuxController - tmux subprocess wrapper
    ├── logs.py             # ClaudeLogReader - parse Claude Code logs
    ├── notifications.py    # Worker-to-primary notification storage
    ├── discord_bot.py      # Backward-compat shim (imports from discord/)
    └── discord/            # Discord bot package
        ├── __init__.py
        ├── bot.py          # RushdBot - commands.Bot with slash commands
        ├── routing.py      # Channel-to-instance routing
        ├── embeds.py       # Rich embed builders
        ├── views.py        # Interactive components (buttons, modals)
        ├── utils.py        # Shared utilities (truncate, split, hash)
        ├── watcher.py      # Filesystem watcher for log changes
        └── cogs/
            ├── instances.py  # /start, /stop, /list, /status, /remove
            ├── messaging.py  # /send, /clear, /approve
            └── approvals.py  # Persistent view registration
```

### How It Works

1. **Tmux Session**: All instances run in a single tmux session (`rushd-instances`), each in its own window.

2. **Instance Tracking**: Metadata is persisted to `~/.rushd/instances.json`, including:
   - Instance ID and name
   - Working directory
   - Tmux window target
   - Status (starting, running, idle, stopped, error)
   - Claude session ID (for log correlation)

3. **Shared Command Layer**: The `CommandHandler` class in `commands.py` encapsulates all business logic. Both the CLI and Discord bot call the same handlers, returning structured `CommandResult` objects. The CLI formats results for the terminal (via Rich), while Discord formats them as embeds.

4. **Message Flow**:
   ```
   CLI:     User input → CLI → CommandHandler → manager → tmux send-keys → Claude
   Discord: Discord msg → Bot → CommandHandler → manager → tmux send-keys → Claude
   ```

5. **Log Reading**: Claude Code stores conversation logs at:
   ```
   ~/.claude/projects/-{encoded-path}/SESSION_ID.jsonl
   ```
   Where path `/home/admin/project` becomes `-home-admin-project`.

6. **Activity Display**: The log reader parses JSONL entries and extracts:
   - User messages
   - Assistant thinking blocks
   - Tool use (name, inputs)
   - Tool results (stdout, stderr, errors)
   - Text responses

### Data Storage

**Instance metadata**: `~/.rushd/instances.json`
```json
{
  "version": "1.0",
  "session_name": "rushd-instances",
  "instances": {
    "a7f3b2c1": {
      "id": "a7f3b2c1",
      "full_id": "a7f3b2c1-d4e5-...",
      "name": "frontend",
      "status": "running",
      "working_dir": "/home/admin/webapp",
      "tmux_window": "rushd-instances:1",
      "created_at": "2026-01-27T10:30:00",
      "claude_session_id": "abc123-...",
      "auto_approve": true,
      "display_mode": "activity"
    }
  }
}
```

---

## Configuration

### Auto-Approve Mode

By default, rushd starts Claude Code with `--dangerously-skip-permissions`, which:
- Automatically trusts the working directory
- Auto-approves all tool permission prompts
- Enables fully autonomous operation

To disable this and manually handle prompts:
```bash
rushd start -n careful --interactive
```

### Tmux Session Name

The default tmux session is `rushd-instances`. To use a different session:
```bash
rushd --session my-session start -n test
rushd --session my-session list
```

### Primary Instance

rushd supports a "primary" instance that serves as the default target for commands when no instance is specified.

**Setup:**
```bash
# Initialize config with defaults
rushd config --init

# Or copy the example
cp config.example.json ~/.rushd/config.json
```

**Configuration (~/.rushd/config.json):**
```json
{
  "version": "1.0",
  "primary": {
    "name": "primary",
    "working_dir": "/home/admin/control-center",
    "model": null,
    "auto_approve": true
  },
  "defaults": {
    "session_name": "rushd-instances"
  }
}
```

**Usage:**
```bash
# Start primary instance (uses config defaults)
rushd start

# Send to primary (no instance argument needed)
rushd send "hello world"

# View primary output
rushd view

# Explicitly start with different settings
rushd start -n other -d ~/other-project
```

**Config Fields:**
| Field | Description |
|-------|-------------|
| `primary.name` | Name for the primary instance (default: "primary") |
| `primary.working_dir` | Default working directory for primary |
| `primary.model` | Default Claude model (null = use Claude default) |
| `primary.auto_approve` | Whether to skip permission prompts (default: true) |
| `defaults.session_name` | Tmux session name for all instances |

**View/Edit Config:**
```bash
rushd config           # Display current config
rushd config --show    # Same as above
rushd config --init    # Create config with defaults
```

---

## Troubleshooting

### "Instance not found"
The instance may have stopped or its tmux window was killed externally.
```bash
rushd list --all   # Check if it's marked as stopped
rushd cleanup      # Clean up stale entries
```

### "No log file found"
Claude Code hasn't created a session log yet. This happens if:
- The instance just started and hasn't processed any messages
- The working directory path encoding doesn't match

Check the expected path:
```bash
rushd log <instance>
# Shows: Expected location: ~/.claude/projects/-path-to-dir/
```

### Tmux session issues
```bash
# Check if the session exists
tmux has-session -t rushd-instances

# Manually attach to debug
tmux attach -t rushd-instances

# Kill and start fresh
rushd cleanup --force
```

### UV cache issues after updates
If code changes aren't reflected after editing:
```bash
uv cache clean rushd
uv tool install -e . --force
```

---

## Dependencies

- **[fire](https://github.com/google/python-fire)** - CLI generation
- **[pydantic](https://docs.pydantic.dev/)** - Data validation and serialization
- **[rich](https://rich.readthedocs.io/)** - Terminal formatting and tables
- **[textual](https://textual.textualize.io/)** - TUI framework
- **[discord.py](https://discordpy.readthedocs.io/)** - Discord bot framework (slash commands, views)
- **[watchdog](https://python-watchdog.readthedocs.io/)** - Filesystem monitoring for log changes

---

## Discord Integration

Discord is a first-class interface for rushd. You can manage all your Claude Code instances entirely from Discord using slash commands, interactive buttons, and per-instance channels — no terminal needed.

### Setup

1. **Create a Discord Bot** at [Discord Developer Portal](https://discord.com/developers/applications):
   - Create a new application
   - Go to Bot tab → Enable "Message Content Intent"
   - Copy the bot token

2. **Invite the bot** to your server:
   - OAuth2 → URL Generator
   - Scopes: `bot`, `applications.commands`
   - Permissions: `Manage Channels`, `Send Messages`, `Read Message History`, `View Channels`, `Add Reactions`, `Use Slash Commands`
   - Use the generated URL to add bot to your server

3. **Configure rushd** (`~/.rushd/config.json`):
   ```json
   {
     "discord": {
       "enabled": true,
       "guild_id": 123456789012345678,
       "allowed_users": ["your-discord-username"],
       "poll_interval": 2.0
     }
   }
   ```

4. **Set the token** (add to `~/.bashrc` or environment):
   ```bash
   export RUSHD_DISCORD_TOKEN="your-bot-token"
   ```

5. **Start the bot**:
   ```bash
   rushd discord
   ```

Slash commands are synced to your server on startup and available immediately.

### Discord Channels

The bot automatically creates a category and channels for each instance:

| Channel | Purpose |
|---------|---------|
| `#<instance>-activity` | Full activity stream (thinking, tools, results) |
| `#<instance>-responses` | Claude's text responses only |
| `#<instance>-status` | Status change notifications (with embeds) |
| `#<instance>-commands` | Send messages to Claude here |
| `#<instance>-live-view` | Auto-updating message with recent activity |

For the primary instance, channels are named `#primary-activity`, `#primary-commands`, etc. When you start additional instances via `/start`, they each get their own category and channel set automatically.

### Slash Commands

Type `/` in any channel to see all available commands:

| Command | Parameters | Description |
|---------|-----------|-------------|
| `/start` | `name?`, `directory?`, `model?`, `prompt?` | Start a new Claude Code instance |
| `/stop` | `instance` | Stop a running instance |
| `/list` | `all?` | List all instances (rich embed) |
| `/status` | `instance?` | Detailed status of an instance |
| `/send` | `instance`, `message` | Send a message to an instance |
| `/clear` | `instance?` | Destroy and recreate an instance |
| `/remove` | `instance` | Remove a stopped instance from storage |
| `/cleanup` | | Stop all instances and clean up |
| `/approve` | `instance?` | Approve a pending plan |

All `instance` parameters support **autocomplete** — start typing and it shows running instances with their current status.

When `instance` is optional and not provided, it defaults to the instance mapped to the current channel (or primary).

### Plain Text Messaging

You can also type plain text in `#<instance>-commands` or `#<instance>-responses` channels to send messages directly to Claude. This works the same as before — no slash command needed.

Attachments (screenshots, images) are automatically downloaded and forwarded to Claude for analysis.

### Interactive Plan Approval

When Claude finishes planning and calls `ExitPlanMode`, Discord shows an interactive message with three buttons:

- **Approve** (green) — approves the plan and starts implementation
- **Reject** (red) — rejects the plan
- **Modify...** (blue) — opens a text modal where you type feedback for Claude to revise the plan

Plain text approval still works as a fallback — type `yes`, `approve`, `lgtm`, etc.

### Interactive Question Answering

When Claude asks a question via `AskUserQuestion`, Discord shows clickable buttons for each option. Click a button to send your answer, or type your response as plain text.

### Multi-Instance Support

Each instance gets its own Discord category with isolated channels:

```
primary/
  #primary-activity
  #primary-responses
  #primary-status
  #primary-commands
  #primary-live-view

worker-1/
  #worker-1-activity
  #worker-1-responses
  #worker-1-status
  #worker-1-commands
  #worker-1-live-view
```

Messages typed in `#worker-1-commands` are routed to the `worker-1` instance. Each instance has its own independent monitoring loop.

To create a new instance with its own channels:
```
/start name:worker-1 directory:/home/admin/my-project
```

### Activity Monitoring

The bot monitors each running instance and dispatches activity to the appropriate channels:

- **Thinking** → `#<instance>-activity` (code block)
- **Tool use** → `#<instance>-activity` (tool name + input)
- **Tool results** → `#<instance>-activity` (code block)
- **Text responses** → both `#<instance>-activity` and `#<instance>-responses`
- **Status changes** → `#<instance>-status` (rich embeds with color coding)

Status embeds use color coding:
- 🟢 Running | 🔵 Thinking | 🟣 Tool Use | ⚪ Idle | 🔴 Stopped | 🟡 Starting

### Running as a Service

For persistent operation, create a systemd service:

```ini
# /etc/systemd/system/rushd-discord.service
[Unit]
Description=rushd Discord Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username
Environment="RUSHD_DISCORD_TOKEN=your-token"
Environment="PATH=/home/your-username/.local/bin:/usr/bin:/bin"
ExecStart=/home/your-username/.local/bin/rushd discord
Restart=always
RestartSec=10
StandardOutput=append:/var/log/rushd-discord.log
StandardError=append:/var/log/rushd-discord.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rushd-discord
sudo systemctl start rushd-discord
```

---

## Version History

- **v0.5.0** - Discord-first interface: slash commands, interactive plan approval buttons, multi-instance channel routing, rich embeds, shared command handler layer, filesystem watcher
- **v0.4.0** - Added Discord bot integration with multi-channel support, /clear command
- **v0.3.0** - Added primary instance support, user configuration (~/.rushd/config.json), commands default to primary instance
- **v0.2.0** - Added conversation log integration, structured activity display, auto-approve mode, display mode toggle
- **v0.1.1** - Bug fixes for numeric message handling
- **v0.1.0** - Initial release with basic instance lifecycle and TUI

---

## License

Personal project. No license specified.

---

## Disclaimer

This tool is provided as-is for personal use. It interacts with Claude Code using `--dangerously-skip-permissions` by default, which bypasses safety prompts. Use responsibly and only in trusted environments.
