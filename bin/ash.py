import asyncio
import importlib.util
import io
import os
import readline
import signal
from pathlib import Path


from system.context import SystemContext, cprint
from system.execute import execute
from system.cmdparse import cmdparse
from system.crond import start_crond
from fs.utils import resolve_path

import argparse

async def run_script(contents: str):
    """Run a script provided as a string."""
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue  # Skip empty lines and comments
        await run_command(line)

async def _exec_one(cmd_obj):
    """Execute a single ShellCommand. Returns True on success, False on error."""
    ctx = SystemContext.current()
    command = cmd_obj.args[0]
    args = cmd_obj.args[1:]

    # Search PATH for the command on the virtual filesystem
    vfs = ctx.fs()
    found_path = None

    # check search paths
    for path_dir in ctx.path:
        candidate = path_dir.strip('/') + '/' + command
        if vfs.exists(candidate) and not vfs.is_dir(candidate):
            found_path = "/" + candidate
            break

    # try to resolve as relative path
    if found_path is None:
        candidate = (ctx.cwd.strip('/') + '/' + command).lstrip('/')
        if vfs.exists(candidate) and not vfs.is_dir(candidate):
            found_path = candidate
        elif command.startswith('./'):
            candidate = (ctx.cwd.strip('/') + '/' + command[2:]).lstrip('/')
            if vfs.exists(candidate) and not vfs.is_dir(candidate):
                found_path = candidate

    if found_path is None:
        cprint(f"ash: command not found: {command}")
        return False

    # Built-in commands live under sbin/ (mounted from bin/)
    if found_path.startswith('/sbin/'):
        # strip away the sbin/ prefix to get the module name
        found_path = found_path[len('/sbin/'):]
        command = found_path
        # load and run the command module from bin/
        bin_dir = Path(__file__).parent
        module_path = bin_dir / f"{command}.py"

        try:
            spec = importlib.util.spec_from_file_location(command, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "run"):
                await module.run(*args)
            else:
                cprint(f"ash: {command} module has no run() function")
                return False
        except Exception as e:
            cprint(f"ash: error running {command}: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        await execute(ctx, found_path, *args)

    return True


async def run_command(user_input: str):
    """Execute command(s) and return True if should continue loop, False to exit.

    Supports:
    - && for chaining commands (stops on failure)
    - > and >> for output redirection to files
    - & for background execution
    """
    user_input = user_input.strip()
    if not user_input:
        return True

    pipeline = cmdparse(user_input)
    if not pipeline:
        return True

    ctx = SystemContext.current()

    for cmd_obj, connector in pipeline:
        if not cmd_obj.args:
            continue

        # Handle output redirection: capture stdout into a buffer
        if cmd_obj.stdout:
            stdout_buf = io.StringIO()
            with ctx.child(stdout=stdout_buf, interactive=False):
                if cmd_obj.background:
                    async def _bg_redirect(cmd, buf):
                        await _exec_one(cmd)
                        output = buf.getvalue()
                        _, vp = resolve_path(cmd.stdout.target, SystemContext.current().cwd)
                        mode = "a" if cmd.stdout.append else None
                        SystemContext.current().fs().write(vp, output.encode("utf-8"), mode=mode)
                    task = asyncio.create_task(_bg_redirect(cmd_obj, stdout_buf))
                    ctx.register_background_task(task)
                    continue

                ok = await _exec_one(cmd_obj)

            # Write captured output to redirect target
            output = stdout_buf.getvalue()
            _, vault_path = resolve_path(cmd_obj.stdout.target, ctx.cwd)
            mode = "a" if cmd_obj.stdout.append else None
            ctx.fs().write(vault_path, output.encode("utf-8"), mode=mode)
        elif cmd_obj.background:
            async def _bg(cmd):
                await _exec_one(cmd)
            task = asyncio.create_task(_bg(cmd_obj))
            ctx.register_background_task(task)
            continue
        else:
            ok = await _exec_one(cmd_obj)

        # For &&, stop chain if command failed
        if connector == "&&" and not ok:
            break

    return True


def get_available_commands(ctx):
    """Get list of available commands from PATH directories on the VFS."""
    if not ctx:
        return ["exit"]
    vfs = ctx.fs()
    commands = set()
    for path_dir in ctx.path:
        path_prefix = path_dir.strip('/')
        prefix = path_prefix + '/'
        for filepath in vfs.list(prefix=path_prefix):
            filepath = filepath.strip('/')
            if filepath.startswith(prefix):
                rel = filepath[len(prefix):]
                if '/' not in rel:
                    commands.add(rel)
    commands.add("exit")
    return sorted(commands)


def get_path_completions(text: str, cwd: str, vault):
    """Get file/directory path completions for the given text.

    :param text: The partial path to complete
    :param cwd: Current working directory
    :param vault: The vault instance
    :return: List of completion candidates
    """
    # Determine if path is absolute or relative
    if text.startswith('/'):
        # Absolute path
        base_dir = '/'
        search_path = text[1:]  # Remove leading /
    else:
        # Relative path
        base_dir = cwd
        search_path = text

    # Split the search path into directory and filename parts
    if '/' in search_path:
        # Completing nested path like "docs/tu" -> need to complete in docs/ directory
        dir_part, file_part = search_path.rsplit('/', 1)
        if base_dir == '/':
            current_dir = dir_part if dir_part else ''
        else:
            current_dir = base_dir.lstrip('/') + '/' + dir_part if dir_part else base_dir.lstrip('/')
    else:
        # Completing in current directory
        current_dir = base_dir.lstrip('/') if base_dir != '/' else ''
        file_part = search_path

    # Get files from vault filtered to current directory
    prefix = current_dir + '/' if current_dir else ''
    all_files = vault.list(prefix=current_dir)

    # Build set of entries in the target directory
    entries = set()

    for filepath in all_files:
        filepath = filepath.lstrip('/')

        # Check if file is in the target directory
        if current_dir and not filepath.startswith(prefix):
            continue
        elif not current_dir and '/' not in filepath:
            # Root level file
            entries.add(filepath)
            continue
        elif not current_dir:
            # Root level directory
            subdir = filepath.split('/')[0]
            entries.add(subdir + '/')
            continue

        # Get relative path from current directory
        rel_path = filepath[len(prefix):]

        if '/' in rel_path:
            # This is in a subdirectory
            subdir = rel_path.split('/')[0]
            entries.add(subdir + '/')
        else:
            # Direct file in current directory
            entries.add(rel_path)

    # Include explicit directories (created with mkdir) that have no files yet
    for dir_name in vault.list_dirs(prefix=current_dir):
        if dir_name + '/' not in entries:
            entries.add(dir_name + '/')

    # Filter entries that match the partial filename
    matches = [e for e in entries if e.startswith(file_part)]

    # Reconstruct full paths for matches
    if '/' in search_path:
        dir_part, _ = search_path.rsplit('/', 1)
        completions = [dir_part + '/' + m for m in matches]
    else:
        completions = matches

    # Add back the leading / for absolute paths
    if text.startswith('/'):
        completions = ['/' + c for c in completions]

    return completions


def create_completer(ctx, debug=False):
    """Create a readline completer function with access to context.

    :param ctx: The SystemContext instance to use for completions
    :param debug: If True, print debug information about completions
    """
    # Cache matches to avoid recomputing for each state
    completion_cache = {'text': None, 'matches': []}

    def completer(text, state):
        """Readline completer function."""
        try:
            # Compute matches only once per completion attempt (when state == 0)
            if state == 0:

                # Get the full input line
                begin_idx = readline.get_begidx()

                # Determine if we're completing a command or a path
                if begin_idx == 0:
                    # Completing command name
                    commands = get_available_commands(ctx)
                    matches = [cmd for cmd in commands if cmd.startswith(text)]
                else:
                    # Completing file/directory path
                    # ctx is captured from the closure - works across threads
                    vault = ctx.fs()
                    matches = get_path_completions(text, ctx.cwd, vault)

                completion_cache['text'] = text
                completion_cache['matches'] = sorted(matches)  # Sort for consistent ordering

                if debug:
                    cprint(f"\n[DEBUG] Completing: '{text}' (position: {begin_idx})", file=ctx.stderr)
                    cprint(f"[DEBUG] CWD: {ctx.cwd}", file=ctx.stderr)
                    cprint(f"[DEBUG] Matches ({len(matches)}): {matches[:10]}", file=ctx.stderr)  # Show first 10

            # Return the state-th match
            matches = completion_cache['matches']
            if state < len(matches):
                return matches[state]
            else:
                return None

        except Exception as e:
            # In debug mode, show the error
            if debug:
                cprint(f"\n[DEBUG] Completer error: {e}", file=ctx.stderr)
                import traceback
                traceback.print_exc()
            return None

    return completer


HISTORY_PATH = "/etc/history"


_history_offset = 0  # readline index after loading; new commands start after this


def load_history(ctx):
    """Load command history from vaultfs into readline."""
    global _history_offset
    content = ctx.read(HISTORY_PATH)
    if content:
        for line in content.splitlines():
            if line:
                readline.add_history(line)
    _history_offset = readline.get_current_history_length()


def save_history(ctx):
    """Append only the new commands from this session to the history file."""
    new_lines = []
    for i in range(_history_offset + 1, readline.get_current_history_length() + 1):
        item = readline.get_history_item(i)
        if item:
            new_lines.append(item)
    if new_lines:
        ctx.fs().write(HISTORY_PATH, ('\n'.join(new_lines) + '\n').encode('utf-8'), mode="a")


def setup_readline(ctx, debug=False):
    """Configure readline for tab completion.

    :param ctx: The SystemContext instance to use for completions
    :param debug: If True, enable debug output for completion
    """
    # Set up tab completion - detect readline implementation first
    if 'libedit' in (readline.__doc__ or ''):
        # libedit (macOS) syntax
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        # GNU readline syntax
        readline.parse_and_bind("tab: complete")

    readline.set_completer(create_completer(ctx, debug=debug))

    # Set completer delimiters (remove '/' so it doesn't break path completion)
    delims = readline.get_completer_delims()
    delims = delims.replace('/', '')
    readline.set_completer_delims(delims)

    if debug:
        cprint("[DEBUG] Readline configured:", file=ctx.stderr)
        cprint(f"[DEBUG]   Library: {'libedit' if 'libedit' in str(readline.__doc__) else 'GNU readline'}", file=ctx.stderr)
        cprint(f"[DEBUG]   Delimiters: {repr(delims)}", file=ctx.stderr)


async def loop(user: str, fsimage: str, command: str = None, debug: bool = False, cost_limit: float | None = None, crond: bool = True):
    """Agent shell - simple async REPL that loads commands from bin/ modules.

    :param user: Username for the session
    :param fsimage: Filesystem image to use
    :param command: Optional command to run in non-interactive mode
    :param debug: Enable debug output for tab completion
    :param cost_limit: Maximum USD cost allowed per 24h window (None = no limit)
    """
    with SystemContext(user=user, fsimage=fsimage, debug=debug, interactive=True, cost_limit=cost_limit) as ctx:
        # Mount built-in commands as /sbin
        from fs.providers import BinProvider, DocsProvider, ModelProvider

        # Mount standard folders
        SystemContext.current().mount("sbin", BinProvider())
        SystemContext.current().mount("models", ModelProvider())
        SystemContext.current().mount("docs", DocsProvider())

        # Start cron daemon as a background task
        if crond:
            cprint("[crond starting in background]", file=ctx.stderr)
            start_crond([user], fsimage)
        else:
            cprint("[crond not running in this process]", file=ctx.stderr)

        # Non-interactive mode: run single command and exit
        if command:
            await run_command(command)
            return

        # Interactive mode: REPL
        await run_script(ctx.read("/etc/profile", "echo ash v0.1 - Agent Shell"))
        if debug:
            cprint("[DEBUG MODE ENABLED]", file=ctx.stderr)
        cprint()

        # Set up tab completion (pass ctx directly since contextvars don't work in executor threads)
        setup_readline(ctx, debug=debug)

        # Load command history from vaultfs
        load_history(ctx)
        if debug:
            cprint(f"[DEBUG] History loaded: {readline.get_current_history_length()} entries", file=ctx.stderr)

        # Show initial file count in debug mode
        if debug:
            ctx = SystemContext.current()
            vault = ctx.fs()
            files = vault.list()
            cprint(f"[DEBUG] Vault has {len(files)} files", file=ctx.stderr)
            if files:
                cprint(f"[DEBUG] Sample files: {files[:5]}", file=ctx.stderr)
            cprint(file=ctx.stderr)

        ev_loop = asyncio.get_running_loop()

        # Ctrl-C at the prompt: just print a note and redisplay (don't exit).
        # We use a noop handler so SIGINT doesn't raise KeyboardInterrupt
        # during the input() wait; Ctrl-D (EOFError) is the only way to exit.
        def _sigint_noop():
            cprint("\n(use Ctrl-D to exit)")

        ev_loop.add_signal_handler(signal.SIGINT, _sigint_noop)

        try:
            while True:
                ctx = SystemContext.current()
                # Wrap ANSI codes with \001/\002 so readline calculates prompt width correctly
                text = f"({ctx.cwd}) > "
                prompt = f"\001\033[1;32m\002{text}\001\033[0m\002"

                try:
                    user_input = await ev_loop.run_in_executor(None, input, prompt)
                except EOFError:
                    cprint()
                    break

                # Restore default SIGINT during command execution so Ctrl-C
                # raises KeyboardInterrupt and interrupts subprocesses.
                ev_loop.remove_signal_handler(signal.SIGINT)
                try:
                    should_continue = await run_command(user_input)
                except KeyboardInterrupt:
                    cprint("^C")
                    should_continue = True
                finally:
                    ev_loop.add_signal_handler(signal.SIGINT, _sigint_noop)
                if not should_continue:
                    break
        finally:
            save_history(SystemContext.current())
            ev_loop.remove_signal_handler(signal.SIGINT)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent Shell (ash)")
    parser.add_argument("--user", required=True, help="Username for the session")
    parser.add_argument("--fsimage", required=True, help="Filesystem image to use")
    parser.add_argument("-c", "--command", help="Command to run in non-interactive mode")
    parser.add_argument("--debug", action="store_true", help="Enable debug output for tab completion")
    parser.add_argument("--limit", type=float, default=1.0, metavar="USD",
                        help="Maximum cost limit in USD per 24h; blocks program turns when exceeded (default: $1.00)")
    parser.add_argument("--crond", action="store_true", help="Start cron daemon (default: True)")
    args = parser.parse_args()

    try:
        asyncio.run(loop(user=args.user, fsimage=args.fsimage, command=args.command, debug=args.debug, cost_limit=args.limit, crond=args.crond))
    except KeyboardInterrupt:
        pass
    finally:
        os._exit(0)