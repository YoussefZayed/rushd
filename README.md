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
    ├── cli.py              # CLI commands (fire-based)
    ├── tui.py              # Interactive TUI (textual-based)
    ├── manager.py          # ClaudeInstanceManager - main orchestration
    ├── models.py           # Pydantic data models
    ├── store.py            # JSON persistence (~/.rushd/instances.json)
    ├── tmux.py             # TmuxController - tmux subprocess wrapper
    └── logs.py             # ClaudeLogReader - parse Claude Code logs
```

### How It Works

1. **Tmux Session**: All instances run in a single tmux session (`rushd-instances`), each in its own window.

2. **Instance Tracking**: Metadata is persisted to `~/.rushd/instances.json`, including:
   - Instance ID and name
   - Working directory
   - Tmux window target
   - Status (starting, running, idle, stopped, error)
   - Claude session ID (for log correlation)

3. **Message Flow**:
   ```
   User input → rushd CLI/TUI → manager.send_message() → tmux send-keys → Claude Code
   ```

4. **Log Reading**: Claude Code stores conversation logs at:
   ```
   ~/.claude/projects/-{encoded-path}/SESSION_ID.jsonl
   ```
   Where path `/home/admin/project` becomes `-home-admin-project`.

5. **Activity Display**: The log reader parses JSONL entries and extracts:
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

---

## Version History

- **v0.2.0** - Added conversation log integration, structured activity display, auto-approve mode, display mode toggle
- **v0.1.1** - Bug fixes for numeric message handling
- **v0.1.0** - Initial release with basic instance lifecycle and TUI

---

## License

Personal project. No license specified.

---

## Disclaimer

This tool is provided as-is for personal use. It interacts with Claude Code using `--dangerously-skip-permissions` by default, which bypasses safety prompts. Use responsibly and only in trusted environments.
