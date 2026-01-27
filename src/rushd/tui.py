"""Interactive TUI for rushd using Textual."""

from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Static, RichLog

from .manager import ClaudeInstanceManager
from .models import InstanceStatus, DisplayMode


class InstanceTabs(Static):
    """Widget showing instance tabs at the top."""

    def __init__(self, manager: ClaudeInstanceManager, **kwargs):
        super().__init__(**kwargs)
        self.manager = manager
        self.selected_id: Optional[str] = None
        self.display_mode: DisplayMode = DisplayMode.ACTIVITY

    def compose(self) -> ComposeResult:
        yield Horizontal(id="tabs-container")

    def refresh_tabs(self, selected_id: Optional[str] = None, display_mode: DisplayMode = DisplayMode.ACTIVITY) -> None:
        """Refresh the tabs display."""
        self.selected_id = selected_id
        self.display_mode = display_mode
        instances = self.manager.list_instances()

        tabs_text = Text()
        tabs_text.append("Instances: ", style="bold")

        if not instances:
            tabs_text.append("[none]", style="dim")
        else:
            for i, inst in enumerate(instances, 1):
                name = inst.name or inst.id[:8]
                is_selected = inst.id == selected_id

                if is_selected:
                    tabs_text.append(f"[{i}] ", style="cyan")
                    tabs_text.append(f"{name}*", style="cyan bold")
                else:
                    tabs_text.append(f"[{i}] ", style="dim")
                    tabs_text.append(name, style="white")
                tabs_text.append("  ")

        tabs_text.append("[+] New", style="green")

        # Show current display mode
        mode_str = "activity" if display_mode == DisplayMode.ACTIVITY else "raw"
        tabs_text.append(f"  [{mode_str}]", style="magenta")

        self.update(tabs_text)


class OutputDisplay(RichLog):
    """Scrollable output display for instance output."""

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)


class RushdApp(App):
    """Interactive TUI for managing Claude Code instances."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #instance-tabs {
        height: 3;
        padding: 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    #output {
        height: 1fr;
        border: solid $primary;
        padding: 1;
    }

    #input-container {
        height: 3;
        padding: 0 1;
    }

    #message-input {
        width: 100%;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+n", "new_instance", "New"),
        Binding("escape", "clear_input", "Clear"),
    ]

    def __init__(self, session_name: str = "rushd-instances"):
        super().__init__()
        self.manager = ClaudeInstanceManager(session_name)
        self.selected_instance: Optional[str] = None
        self._output_widget: Optional[OutputDisplay] = None
        self._tabs_widget: Optional[InstanceTabs] = None
        self._status_widget: Optional[Static] = None
        self._last_output: str = ""
        self._display_mode: DisplayMode = DisplayMode.ACTIVITY

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield InstanceTabs(self.manager, id="instance-tabs")
        yield OutputDisplay(id="output")
        yield Horizontal(
            Input(placeholder="Type message, or: /switch N, /new, /stop, /list, /attach, /quit", id="message-input"),
            id="input-container"
        )
        yield Static("Ready. Type /new to create an instance.", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the app on mount."""
        self._output_widget = self.query_one("#output", OutputDisplay)
        self._tabs_widget = self.query_one("#instance-tabs", InstanceTabs)
        self._status_widget = self.query_one("#status-bar", Static)

        # Refresh tabs
        self._refresh_tabs()

        # Auto-select first instance if any
        instances = self.manager.list_instances()
        if instances:
            self.selected_instance = instances[0].id
            self._refresh_tabs()

        # Start output polling
        self.set_interval(0.5, self._poll_output)

        # Focus the input
        self.query_one("#message-input", Input).focus()

    def _refresh_tabs(self) -> None:
        """Refresh the instance tabs."""
        if self._tabs_widget:
            self._tabs_widget.refresh_tabs(self.selected_instance, self._display_mode)

    def _poll_output(self) -> None:
        """Poll and update output from selected instance."""
        if not self.selected_instance or not self._output_widget:
            return

        # Get output based on display mode
        if self._display_mode == DisplayMode.ACTIVITY:
            output = self.manager.get_activity_formatted(self.selected_instance, last_n=50)
        else:
            output = self.manager.capture_output(self.selected_instance, lines=200)

        # Only update if changed
        if output != self._last_output:
            self._last_output = output
            self._output_widget.clear()
            self._output_widget.write(output)
            self._output_widget.scroll_end()

    def _set_status(self, message: str) -> None:
        """Update the status bar."""
        if self._status_widget:
            self._status_widget.update(message)

    @on(Input.Submitted, "#message-input")
    def handle_input(self, event: Input.Submitted) -> None:
        """Handle user input."""
        text = event.value.strip()
        if not text:
            return

        # Clear input
        event.input.value = ""

        # Handle commands
        if text.startswith("/"):
            self._handle_command(text)
        else:
            self._send_message(text)

    def _handle_command(self, cmd: str) -> None:
        """Process slash commands."""
        parts = cmd[1:].split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Handle numeric shortcuts for switch
        if command.isdigit():
            self._switch_to_index(int(command))
            return

        if command == "quit" or command == "q":
            self.exit()
        elif command == "new":
            self._create_instance(args)
        elif command == "stop":
            self._stop_instance(args)
        elif command == "list" or command == "ls":
            self._list_instances()
        elif command == "switch" or command == "s":
            self._switch_instance(args)
        elif command == "attach" or command == "a":
            self._attach_instance()
        elif command == "raw":
            self._set_display_mode(DisplayMode.RAW)
        elif command == "activity":
            self._set_display_mode(DisplayMode.ACTIVITY)
        elif command == "help" or command == "h":
            self._show_help()
        else:
            self._set_status(f"Unknown command: /{command}. Type /help for commands.")

    def _switch_to_index(self, index: int) -> None:
        """Switch to instance by 1-based index."""
        instances = self.manager.list_instances()
        if 1 <= index <= len(instances):
            self.selected_instance = instances[index - 1].id
            self._refresh_tabs()
            self._last_output = ""  # Force refresh
            inst = instances[index - 1]
            name = inst.name or inst.id[:8]
            self._set_status(f"Switched to [{index}] {name}")
        else:
            self._set_status(f"No instance at index {index}")

    def _switch_instance(self, identifier: str) -> None:
        """Switch to an instance by name, ID, or index."""
        if not identifier:
            self._set_status("Usage: /switch <name|id|index>")
            return

        # Try as index first
        if identifier.isdigit():
            self._switch_to_index(int(identifier))
            return

        # Try by name or ID
        instance = self.manager.get_instance(identifier)
        if instance:
            self.selected_instance = instance.id
            self._refresh_tabs()
            self._last_output = ""
            name = instance.name or instance.id[:8]
            self._set_status(f"Switched to {name}")
        else:
            self._set_status(f"Instance not found: {identifier}")

    def _create_instance(self, args: str) -> None:
        """Create a new instance."""
        name = None
        working_dir = None

        # Parse simple args: -n name -d dir
        parts = args.split()
        i = 0
        while i < len(parts):
            if parts[i] == "-n" and i + 1 < len(parts):
                name = parts[i + 1]
                i += 2
            elif parts[i] == "-d" and i + 1 < len(parts):
                working_dir = Path(parts[i + 1]).expanduser()
                i += 2
            else:
                # Treat as name if no flag
                if not name:
                    name = parts[i]
                i += 1

        try:
            instance = self.manager.start_instance(name=name, working_dir=working_dir)
            self.selected_instance = instance.id
            self._refresh_tabs()
            self._last_output = ""
            display_name = instance.name or instance.id[:8]
            self._set_status(f"Created instance: {display_name}")
        except Exception as e:
            self._set_status(f"Error creating instance: {e}")

    def _stop_instance(self, identifier: str) -> None:
        """Stop an instance."""
        if not identifier:
            # Stop current instance
            if self.selected_instance:
                identifier = self.selected_instance
            else:
                self._set_status("No instance selected. Usage: /stop <name|id>")
                return

        if self.manager.stop_instance(identifier):
            self._set_status(f"Stopped instance: {identifier}")
            # Select next available instance
            instances = self.manager.list_instances()
            if instances:
                self.selected_instance = instances[0].id
            else:
                self.selected_instance = None
                self._last_output = ""
                if self._output_widget:
                    self._output_widget.clear()
            self._refresh_tabs()
        else:
            self._set_status(f"Failed to stop instance: {identifier}")

    def _list_instances(self) -> None:
        """Show list of instances in output."""
        instances = self.manager.list_instances(include_stopped=True)
        if not instances:
            self._set_status("No instances. Type /new to create one.")
            return

        if self._output_widget:
            self._output_widget.clear()
            self._output_widget.write("[bold]Instances:[/bold]\n")
            for i, inst in enumerate(instances, 1):
                name = inst.name or inst.id[:8]
                status_icon = {
                    InstanceStatus.RUNNING: "[green]running[/green]",
                    InstanceStatus.STARTING: "[yellow]starting[/yellow]",
                    InstanceStatus.IDLE: "[blue]idle[/blue]",
                    InstanceStatus.STOPPED: "[red]stopped[/red]",
                    InstanceStatus.ERROR: "[red]error[/red]",
                }.get(inst.status, inst.status)
                selected = "*" if inst.id == self.selected_instance else " "
                self._output_widget.write(
                    f"  {selected}[{i}] {name} - {status_icon} - {inst.working_dir}\n"
                )

    def _attach_instance(self) -> None:
        """Attach to the selected instance's tmux window."""
        if not self.selected_instance:
            self._set_status("No instance selected")
            return

        # Suspend the TUI and attach to tmux
        self._set_status("Attaching... Use Ctrl+B D to detach from tmux")

        # We need to exit the TUI first
        self.exit(result="attach")

    def _send_message(self, message: str) -> None:
        """Send a message to the selected instance."""
        if not self.selected_instance:
            self._set_status("No instance selected. Use /new to create one.")
            return

        if self.manager.send_message(self.selected_instance, message):
            self._set_status("Message sent")
        else:
            self._set_status("Failed to send message")

    def _set_display_mode(self, mode: DisplayMode) -> None:
        """Set the display mode and refresh output."""
        self._display_mode = mode
        self._last_output = ""  # Force refresh
        self._refresh_tabs()
        mode_name = "activity" if mode == DisplayMode.ACTIVITY else "raw terminal"
        self._set_status(f"Switched to {mode_name} view")

    def _show_help(self) -> None:
        """Show help in output."""
        if self._output_widget:
            self._output_widget.clear()
            self._output_widget.write("""[bold]rushd Commands:[/bold]

[cyan]/new[/cyan] [-n name] [-d dir]  Create new Claude Code instance
[cyan]/switch[/cyan] <N|name|id>      Switch to instance (or just /N)
[cyan]/stop[/cyan] [name|id]          Stop instance (current if none specified)
[cyan]/list[/cyan]                    List all instances
[cyan]/attach[/cyan]                  Attach to tmux window (Ctrl+B D to detach)
[cyan]/raw[/cyan]                     Show raw terminal output
[cyan]/activity[/cyan]                Show structured activity (default)
[cyan]/quit[/cyan]                    Exit rushd

[bold]Shortcuts:[/bold]
  /1, /2, /3...  Quick switch to instance by number
  Ctrl+N         Create new instance
  Ctrl+C         Quit

[bold]Display Modes:[/bold]
  [magenta]activity[/magenta] - Shows parsed log entries (thinking, tools, responses)
  [magenta]raw[/magenta]      - Shows actual terminal output from tmux

[bold]Sending Messages:[/bold]
  Just type and press Enter to send to the selected instance.
""")

    def action_new_instance(self) -> None:
        """Create a new instance (keyboard shortcut)."""
        self._create_instance("")

    def action_clear_input(self) -> None:
        """Clear the input field."""
        self.query_one("#message-input", Input).value = ""

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()


def run_tui(session_name: str = "rushd-instances") -> Optional[str]:
    """Run the TUI and return the result (e.g., 'attach' if user wants to attach)."""
    app = RushdApp(session_name)
    return app.run()
