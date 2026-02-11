"""CLI interface for rushd."""

import sys
from pathlib import Path
from typing import Optional

import fire
from rich.console import Console
from rich.table import Table

from .config import ConfigManager
from .manager import ClaudeInstanceManager
from .models import InstanceStatus, NotificationStatus


console = Console()


class RushdCLI:
    """CLI for managing Claude Code instances."""

    def __init__(self, session: Optional[str] = None):
        """
        Initialize rushd CLI.

        Args:
            session: Tmux session name for instances (defaults to config value)
        """
        self._config = ConfigManager()
        config = self._config.load()
        self._session = session or config.defaults.session_name
        self._manager: Optional[ClaudeInstanceManager] = None

    @property
    def manager(self) -> ClaudeInstanceManager:
        """Lazy-load the manager."""
        if self._manager is None:
            self._manager = ClaudeInstanceManager(self._session)
        return self._manager

    def start(
        self,
        name: Optional[str] = None,
        dir: Optional[str] = None,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
        resume: Optional[str] = None,
        interactive: bool = False,
    ) -> None:
        """
        Start a new Claude Code instance.

        Args:
            name: User-friendly name for the instance (defaults to primary)
            dir: Working directory (defaults to primary working dir)
            model: Claude model to use
            prompt: Initial prompt to send
            resume: Session ID to resume
            interactive: If True, don't auto-approve prompts (manual control)
        """
        # If no name or dir specified, use primary config
        if name is None and dir is None:
            primary = self._config.get_primary()
            name = primary.name
            dir = str(primary.working_dir)
            model = model or primary.model
            if not interactive:
                interactive = not primary.auto_approve
            console.print(f"[dim]Using primary instance defaults[/dim]")

        working_dir = Path(dir).expanduser().resolve() if dir else None

        # Validate working directory exists
        if working_dir and not working_dir.exists():
            console.print(f"[red]Error:[/red] Working directory does not exist: {working_dir}")
            console.print("[dim]Create the directory or update ~/.rushd/config.json[/dim]")
            sys.exit(1)

        # auto_approve is True by default, but False if --interactive is passed
        auto_approve = not interactive

        try:
            instance = self.manager.start_instance(
                name=name,
                working_dir=working_dir,
                model=model,
                initial_prompt=prompt,
                resume=resume,
                auto_approve=auto_approve,
            )
            display_name = instance.name or instance.id
            console.print(f"[green]Started instance:[/green] {display_name}")
            console.print(f"  ID: {instance.id}")
            console.print(f"  Directory: {instance.working_dir}")
            console.print(f"  Window: {instance.tmux_window}")
            if auto_approve:
                console.print(f"  [dim]Auto-approve: enabled (--dangerously-skip-permissions)[/dim]")
            else:
                console.print(f"  [yellow]Auto-approve: disabled (interactive mode)[/yellow]")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    def list(self, all: bool = False, json: bool = False) -> None:
        """
        List all managed instances.

        Args:
            all: Include stopped instances
            json: Output as JSON
        """
        # Refresh statuses to detect activity state
        self.manager.refresh_statuses()
        instances = self.manager.list_instances(include_stopped=all)

        if json:
            import json as json_lib
            data = [
                {
                    "id": i.id,
                    "name": i.name,
                    "status": i.status,
                    "working_dir": str(i.working_dir),
                    "tmux_window": i.tmux_window,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                }
                for i in instances
            ]
            console.print(json_lib.dumps(data, indent=2))
            return

        if not instances:
            console.print("[dim]No instances. Use 'rushd start' to create one.[/dim]")
            return

        table = Table(title="Claude Code Instances")
        table.add_column("#", style="dim")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Directory")

        for i, inst in enumerate(instances, 1):
            # Enhanced status display with activity indicators
            status_display = {
                InstanceStatus.RUNNING: "[green]running[/green]",
                InstanceStatus.STARTING: "[yellow]starting...[/yellow]",
                InstanceStatus.THINKING: "[cyan]thinking*[/cyan]",
                InstanceStatus.TOOL_USE: "[magenta]tool~[/magenta]",
                InstanceStatus.IDLE: "[blue]idle[/blue]",
                InstanceStatus.STOPPED: "[red]stopped[/red]",
                InstanceStatus.ERROR: "[red]error![/red]",
            }.get(inst.status, f"[white]{inst.status}[/white]")

            table.add_row(
                str(i),
                inst.id[:8],
                inst.name or "-",
                status_display,
                str(inst.working_dir),
            )

        console.print(table)

    def stop(self, instance: Optional[str] = None, all: bool = False, force: bool = False) -> None:
        """
        Stop a Claude Code instance.

        Args:
            instance: Instance ID or name to stop
            all: Stop all instances
            force: Force kill without graceful shutdown
        """
        if all:
            count = self.manager.stop_all(force=force)
            console.print(f"[green]Stopped {count} instance(s)[/green]")
            return

        if not instance:
            console.print("[red]Error:[/red] Specify an instance or use --all")
            sys.exit(1)

        if self.manager.stop_instance(instance, force=force):
            console.print(f"[green]Stopped:[/green] {instance}")
        else:
            console.print(f"[red]Error:[/red] Instance not found: {instance}")
            sys.exit(1)

    def view(self, instance: Optional[str] = None, lines: int = 50, follow: bool = False, activity: bool = False) -> None:
        """
        View output from an instance.

        Args:
            instance: Instance ID or name (defaults to primary)
            lines: Number of lines to show
            follow: Follow output
            activity: Show structured activity from logs instead of raw terminal
        """
        # Default to primary instance
        if instance is None:
            primary = self._config.get_primary()
            instance = primary.name

        inst = self.manager.get_instance(instance)
        if not inst:
            console.print(f"[red]Error:[/red] Instance not found: {instance}")
            console.print("[dim]Start it with 'rushd start'[/dim]")
            sys.exit(1)

        if follow:
            import time
            last_output = ""
            try:
                while True:
                    if activity:
                        output = self.manager.get_activity_formatted(instance, last_n=lines)
                    else:
                        output = self.manager.capture_output(instance, lines=lines)
                    if output != last_output:
                        # Clear and reprint
                        console.clear()
                        console.print(output)
                        last_output = output
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        else:
            if activity:
                output = self.manager.get_activity_formatted(instance, last_n=lines)
            else:
                output = self.manager.capture_output(instance, lines=lines)
            console.print(output)

    def send(self, instance_or_message: Optional[str] = None, message="", file: Optional[str] = None) -> None:
        """
        Send a message to an instance.

        Args:
            instance_or_message: Instance ID/name, or message if no instance specified
            message: Message to send (when instance is specified)
            file: Read message from file
        """
        instance = instance_or_message

        # Smart detection: if first arg provided but no message, check if it's an instance or message
        if instance is not None and not message and not file:
            # Check if it's actually an instance
            inst = self.manager.get_instance(instance)
            if inst is None:
                # Not an instance - treat it as message to primary
                message = instance
                primary = self._config.get_primary()
                instance = primary.name

        # Default to primary instance if no instance specified
        if instance is None:
            primary = self._config.get_primary()
            instance = primary.name

        # Verify instance exists
        inst = self.manager.get_instance(instance)
        if not inst:
            console.print(f"[yellow]Instance '{instance}' not found.[/yellow]")
            console.print("[dim]Start it with 'rushd start'[/dim]")
            sys.exit(1)

        if file:
            with open(file, "r") as f:
                message = f.read()

        # Convert message to string (fire may pass int for numeric input)
        message = str(message)

        if not message:
            console.print("[red]Error:[/red] No message provided")
            sys.exit(1)

        if self.manager.send_message(instance, message):
            console.print("[green]Message sent[/green]")
        else:
            console.print(f"[red]Error:[/red] Failed to send to: {instance}")
            sys.exit(1)

    def attach(self, instance: Optional[str] = None) -> None:
        """
        Attach to an instance's tmux window.

        Args:
            instance: Instance ID or name (defaults to primary)
        """
        # Default to primary instance
        if instance is None:
            primary = self._config.get_primary()
            instance = primary.name

        inst = self.manager.get_instance(instance)
        if not inst:
            console.print(f"[red]Error:[/red] Instance not found: {instance}")
            console.print("[dim]Start it with 'rushd start'[/dim]")
            sys.exit(1)

        console.print(f"Attaching to {inst.name or inst.id}... (Ctrl+B D to detach)")
        self.manager.attach(instance)

    def log(self, instance: Optional[str] = None) -> None:
        """
        Show the conversation log path for an instance.

        Args:
            instance: Instance ID or name (defaults to primary)
        """
        from .logs import ClaudeLogReader

        # Default to primary instance
        if instance is None:
            primary = self._config.get_primary()
            instance = primary.name

        inst = self.manager.get_instance(instance)
        if not inst:
            console.print(f"[red]Error:[/red] Instance not found: {instance}")
            console.print("[dim]Start it with 'rushd start'[/dim]")
            sys.exit(1)

        log_reader = ClaudeLogReader(inst.working_dir)
        log_path = log_reader.find_latest_session()

        if log_path:
            console.print(f"[bold]Log file:[/bold] {log_path}")
        else:
            console.print(f"[yellow]No log file found for instance {instance}[/yellow]")
            console.print(f"[dim]Expected location: {log_reader.project_dir}[/dim]")

    def status(self, instance: Optional[str] = None) -> None:
        """
        Show detailed status of an instance.

        Args:
            instance: Instance ID or name (defaults to primary)
        """
        # Default to primary instance
        if instance is None:
            primary = self._config.get_primary()
            instance = primary.name

        inst = self.manager.get_instance(instance)
        if not inst:
            console.print(f"[red]Error:[/red] Instance not found: {instance}")
            console.print("[dim]Start it with 'rushd start'[/dim]")
            sys.exit(1)

        console.print(f"[bold]Instance: {inst.name or inst.id}[/bold]")
        console.print(f"  ID: {inst.id}")
        console.print(f"  Full ID: {inst.full_id}")
        console.print(f"  Status: {inst.status}")
        console.print(f"  Directory: {inst.working_dir}")
        console.print(f"  Tmux Window: {inst.tmux_window}")
        console.print(f"  Created: {inst.created_at}")
        if inst.model:
            console.print(f"  Model: {inst.model}")
        if inst.last_activity:
            console.print(f"  Last Activity: {inst.last_activity}")
        if inst.claude_session_id:
            console.print(f"  Claude Session: {inst.claude_session_id}")
        console.print(f"  Auto-Approve: {inst.auto_approve}")
        console.print(f"  Display Mode: {inst.display_mode}")

    def remove(self, instance: str) -> None:
        """
        Remove an instance from storage (must be stopped first).

        Args:
            instance: Instance ID or name to remove
        """
        inst = self.manager.get_instance(instance)
        if not inst:
            console.print(f"[red]Error:[/red] Instance not found: {instance}")
            sys.exit(1)

        if inst.status != InstanceStatus.STOPPED:
            # Check if tmux window still exists
            if self.manager.tmux.window_exists(inst.tmux_window):
                console.print(f"[red]Error:[/red] Instance is still running. Stop it first with 'rushd stop {instance}'")
                sys.exit(1)

        if self.manager.remove_instance(instance):
            console.print(f"[green]Removed:[/green] {instance}")
        else:
            console.print(f"[red]Error:[/red] Failed to remove: {instance}")
            sys.exit(1)

    def cleanup(self, force: bool = False) -> None:
        """
        Stop all instances and remove the tmux session.

        Args:
            force: Skip confirmation
        """
        if not force:
            instances = self.manager.list_instances()
            if instances:
                console.print(f"This will stop {len(instances)} instance(s) and remove the session.")
                confirm = console.input("Continue? [y/N] ")
                if confirm.lower() != "y":
                    console.print("Cancelled")
                    return

        self.manager.cleanup(force=True)
        console.print("[green]Cleanup complete[/green]")

    def config(self, show: bool = False, init: bool = False) -> None:
        """
        Manage rushd configuration.

        Args:
            show: Display current configuration
            init: Initialize config file with defaults
        """
        if init:
            if self._config.exists():
                console.print("[yellow]Config already exists at ~/.rushd/config.json[/yellow]")
                console.print("[dim]Use --show to view current config[/dim]")
                return
            from .config import RushdConfig
            config = RushdConfig()
            self._config.save(config)
            console.print("[green]Created config file at ~/.rushd/config.json[/green]")
            return

        # Default to showing config
        config = self._config.load()
        import json as json_lib
        console.print(json_lib.dumps(config.model_dump(mode="json"), indent=2, default=str))

    def discord(self) -> None:
        """Start the Discord bot bridge for the primary instance."""
        import os

        config = self._config.load()
        if not config.discord.enabled:
            console.print("[red]Error:[/red] Discord not enabled in config")
            console.print("[dim]Set discord.enabled = true in ~/.rushd/config.json[/dim]")
            return

        token = os.environ.get("RUSHD_DISCORD_TOKEN")
        if not token:
            console.print("[red]Error:[/red] RUSHD_DISCORD_TOKEN environment variable not set")
            return

        if not config.discord.guild_id:
            console.print("[red]Error:[/red] discord.guild_id not set in config")
            console.print("[dim]Right-click your server → Copy Server ID[/dim]")
            return

        if not config.discord.allowed_users:
            console.print("[yellow]Warning:[/yellow] No allowed_users configured")
            console.print("[dim]Add your Discord username to discord.allowed_users[/dim]")

        primary_name = config.primary.name
        if not self.manager.is_primary_running(primary_name):
            console.print("[yellow]Warning:[/yellow] Primary instance not running")
            console.print("[dim]Start it with 'rushd start'[/dim]")

        from .discord_bot import run_discord_bot
        console.print(f"[green]Starting Discord bot for '{primary_name}'...[/green]")
        console.print("[dim]Channels will be auto-created if needed[/dim]")
        run_discord_bot(self.manager, config.discord, self._config, primary_name, token)

    def responses(self, limit: int = 20, json: bool = False) -> None:
        """
        View Claude responses that were sent to Discord.

        Args:
            limit: Maximum number of responses to show (default: 20)
            json: Output as JSON
        """
        import json as json_lib

        responses_dir = Path.home() / ".rushd" / "responses"
        if not responses_dir.exists():
            console.print("[dim]No responses found. Run Discord bot to capture responses.[/dim]")
            return

        # Read response files, sorted by timestamp (newest first)
        files = sorted(responses_dir.glob("*.json"), reverse=True)[:limit]

        responses_list = []
        for f in files:
            try:
                data = json_lib.loads(f.read_text())
                responses_list.append(data)
            except Exception:
                pass

        if json:
            console.print(json_lib.dumps(responses_list, indent=2))
            return

        if not responses_list:
            console.print("[dim]No responses found[/dim]")
            return

        # Show oldest first for natural reading order
        for resp in reversed(responses_list):
            time_str = resp.get("timestamp", "")[:19]
            text = resp.get("text", "")
            console.print(f"[dim]{time_str}[/dim]")
            console.print(text)
            console.print()

    def verify_panes(self, fix: bool = False, json: bool = False) -> None:
        """
        Verify stored pane IDs match actual tmux panes.

        Cross-references instances.json pane IDs with actual tmux windows
        and reports/fixes mismatches.

        Args:
            fix: Automatically fix mismatched pane IDs
            json: Output as JSON
        """
        instances = self.manager.list_instances(include_stopped=False)
        tmux_windows = self.manager.tmux.list_windows()

        # Build lookup by window name
        window_by_name: dict[str, dict] = {}
        for w in tmux_windows:
            window_by_name[w["name"]] = w

        results = []
        fixes_applied = 0

        for inst in instances:
            window_name = inst.name or inst.id
            actual_window = window_by_name.get(window_name)

            result = {
                "instance_id": inst.id,
                "name": inst.name,
                "stored_pane_id": inst.tmux_pane_id,
                "actual_pane_id": actual_window["pane_id"] if actual_window else None,
                "window_exists": actual_window is not None,
                "match": False,
                "fixed": False,
            }

            if actual_window:
                result["match"] = inst.tmux_pane_id == actual_window["pane_id"]

                if not result["match"] and fix:
                    # Update the stored pane ID
                    self.manager.store.update(
                        inst.id,
                        tmux_pane_id=actual_window["pane_id"]
                    )
                    result["fixed"] = True
                    fixes_applied += 1

            results.append(result)

        if json:
            import json as json_lib
            console.print(json_lib.dumps(results, indent=2))
            return

        # Display results as table
        table = Table(title="Pane ID Verification")
        table.add_column("Instance", style="cyan")
        table.add_column("Stored Pane ID")
        table.add_column("Actual Pane ID")
        table.add_column("Status")

        for r in results:
            name = r["name"] or r["instance_id"]
            stored = r["stored_pane_id"] or "[dim]-[/dim]"
            actual = r["actual_pane_id"] or "[dim]-[/dim]"

            if not r["window_exists"]:
                status = "[red]window missing[/red]"
            elif r["match"]:
                status = "[green]OK[/green]"
            elif r["fixed"]:
                status = "[yellow]FIXED[/yellow]"
            else:
                status = "[red]MISMATCH[/red]"

            table.add_row(name, stored, actual, status)

        console.print(table)

        # Summary
        mismatches = sum(1 for r in results if not r["match"] and r["window_exists"])
        missing = sum(1 for r in results if not r["window_exists"])

        if mismatches > 0 or missing > 0:
            console.print()
            if mismatches > 0:
                if fix:
                    console.print(f"[green]Fixed {fixes_applied} mismatched pane ID(s)[/green]")
                else:
                    console.print(f"[yellow]{mismatches} mismatched pane ID(s) found[/yellow]")
                    console.print("[dim]Run with --fix to update stored values[/dim]")
            if missing > 0:
                console.print(f"[yellow]{missing} instance(s) have no tmux window[/yellow]")
                console.print("[dim]These instances may need to be removed[/dim]")
        else:
            console.print("[green]All pane IDs verified correctly[/green]")

    def notifications(
        self,
        worker: Optional[str] = None,
        limit: int = 20,
        undelivered: bool = False,
        json: bool = False,
    ) -> None:
        """
        List worker notifications.

        Args:
            worker: Filter by worker instance ID or name
            limit: Maximum number of notifications to show (default: 20)
            undelivered: Only show undelivered notifications
            json: Output as JSON
        """
        notifications_list = self.manager.list_notifications(
            worker_identifier=worker,
            undelivered_only=undelivered,
            limit=limit,
        )

        if json:
            import json as json_lib
            data = [
                {
                    "id": n.id,
                    "worker_id": n.worker_id,
                    "worker_name": n.worker_name,
                    "status": n.status,
                    "message": n.message,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                    "delivered": n.delivered,
                    "delivered_at": n.delivered_at.isoformat() if n.delivered_at else None,
                }
                for n in notifications_list
            ]
            console.print(json_lib.dumps(data, indent=2))
            return

        if not notifications_list:
            console.print("[dim]No notifications found[/dim]")
            return

        table = Table(title="Worker Notifications")
        table.add_column("Time", style="dim")
        table.add_column("Worker", style="cyan")
        table.add_column("Status")
        table.add_column("Message")
        table.add_column("Delivered", style="dim")

        for n in notifications_list:
            # Format time
            time_str = n.created_at.strftime("%Y-%m-%d %H:%M:%S") if n.created_at else "-"

            # Status with color
            status_display = {
                "success": "[green]success[/green]",
                "failure": "[red]failure[/red]",
                "info": "[blue]info[/blue]",
            }.get(n.status, n.status)

            # Delivered indicator
            delivered_str = "[green]Yes[/green]" if n.delivered else "[yellow]No[/yellow]"

            table.add_row(
                time_str,
                n.worker_name or n.worker_id,
                status_display,
                n.message or "-",
                delivered_str,
            )

        console.print(table)


def main():
    """Main entry point."""
    # If no arguments (or just --session), launch TUI
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] in ["-i", "--interactive"]):
        from .tui import run_tui

        result = run_tui()

        # Handle attach request
        if result == "attach":
            # Get the selected instance and attach
            manager = ClaudeInstanceManager()
            instances = manager.list_instances()
            if instances:
                manager.attach(instances[0].id)
    else:
        fire.Fire(RushdCLI)


if __name__ == "__main__":
    main()
