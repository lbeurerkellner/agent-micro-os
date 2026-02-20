import asyncio
import importlib.util
import os
import readline
import signal
from pathlib import Path

import termcolor

from system.context import SystemContext
from system.execute import execute
from system.cmdparse import cmdparse

import argparse

async def run_script(contents: str):
    """Run a script provided as a string."""
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue  # Skip empty lines and comments
        await run_command(line)

async def run_command(user_input: str):
    """Execute command(s) and return True if should continue loop, False to exit.

    Supports && for chaining commands - stops execution if any command fails.
    Commands are resolved by searching the system PATH on the virtual filesystem.
    Built-in commands (under /sbin) are imported and run as Python modules.
    """
    # Strip whitespace
    user_input = user_input.strip()

    # Skip empty input
    if not user_input:
        return True

    # Split on && for command chaining
    commands = [cmd.strip() for cmd in user_input.split('&&')]

    ctx = SystemContext.current()

    # Execute each command in sequence
    for cmd in commands:
        if not cmd:
            continue

        # Parse command (first word) and arguments using bash-like tokenizer
        parts = cmdparse(cmd)
        if not parts:
            continue
        command = parts[0]
        args = parts[1:]

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
            print(f"ash: command not found: {command}")
            break  # Stop chain on error

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
                    print(f"ash: {command} module has no run() function")
                    break  # Stop chain on error
            except Exception as e:
                print(f"ash: error running {command}: {e}")
                import traceback
                traceback.print_exc()
                break  # Stop chain on error
        else:
            await execute(ctx, found_path, *args)
            break  # Stop chain on error

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
                    print(f"\n[DEBUG] Completing: '{text}' (position: {begin_idx})")
                    print(f"[DEBUG] CWD: {ctx.cwd}")
                    print(f"[DEBUG] Matches ({len(matches)}): {matches[:10]}")  # Show first 10

            # Return the state-th match
            matches = completion_cache['matches']
            if state < len(matches):
                return matches[state]
            else:
                return None

        except Exception as e:
            # In debug mode, show the error
            if debug:
                print(f"\n[DEBUG] Completer error: {e}")
                import traceback
                traceback.print_exc()
            return None

    return completer


HISTORY_PATH = "/etc/history"


def load_history(ctx):
    """Load command history from vaultfs into readline."""
    content = ctx.read(HISTORY_PATH)
    if content:
        for line in content.splitlines():
            if line:
                readline.add_history(line)


def save_history(ctx):
    """Save readline history to vaultfs."""
    lines = []
    for i in range(1, readline.get_current_history_length() + 1):
        item = readline.get_history_item(i)
        if item:
            lines.append(item)
    if lines:
        ctx.fs().write(HISTORY_PATH, '\n'.join(lines).encode('utf-8'))


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
        print("[DEBUG] Readline configured:")
        print(f"[DEBUG]   Library: {'libedit' if 'libedit' in str(readline.__doc__) else 'GNU readline'}")
        print(f"[DEBUG]   Delimiters: {repr(delims)}")


async def loop(user: str, fsimage: str, command: str = None, debug: bool = False, cost_limit: float | None = None):
    """Agent shell - simple async REPL that loads commands from bin/ modules.

    :param user: Username for the session
    :param fsimage: Filesystem image to use
    :param command: Optional command to run in non-interactive mode
    :param debug: Enable debug output for tab completion
    :param cost_limit: Maximum USD cost allowed per 24h window (None = no limit)
    """
    with SystemContext(user=user, fsimage=fsimage, debug=debug, interactive=True, cost_limit=cost_limit) as ctx:
        # Mount built-in commands as /sbin
        from fs.providers import BinProvider, ModelProvider, ProcProvider, ToolsFolderProvider

        # Mount standard folders
        SystemContext.current().mount("sbin", BinProvider())
        SystemContext.current().mount("models", ModelProvider())
        SystemContext.current().mount("tools", ToolsFolderProvider(ctx))
        SystemContext.current().mount("proc", ProcProvider(ctx._agents))

        # Non-interactive mode: run single command and exit
        if command:
            await run_command(command)
            return

        # Interactive mode: REPL
        await run_script(ctx.read("/etc/profile", "echo ash v0.1 - Agent Shell"))
        if debug:
            print("[DEBUG MODE ENABLED]")
        print()

        # Set up tab completion (pass ctx directly since contextvars don't work in executor threads)
        setup_readline(ctx, debug=debug)

        # Load command history from vaultfs
        load_history(ctx)
        if debug:
            print(f"[DEBUG] History loaded: {readline.get_current_history_length()} entries")

        # Show initial file count in debug mode
        if debug:
            ctx = SystemContext.current()
            vault = ctx.fs()
            files = vault.list()
            print(f"[DEBUG] Vault has {len(files)} files")
            if files:
                print(f"[DEBUG] Sample files: {files[:5]}")
            print()

        ev_loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        ev_loop.add_signal_handler(signal.SIGINT, stop.set)

        try:
            while True:
                ctx = SystemContext.current()
                # Wrap ANSI codes with \001/\002 so readline calculates prompt width correctly
                text = f"({ctx.cwd}) > "
                prompt = f"\001\033[1;32m\002{text}\001\033[0m\002"

                input_task = asyncio.ensure_future(
                    ev_loop.run_in_executor(None, input, prompt)
                )
                stop_task = asyncio.ensure_future(stop.wait())

                done, pending = await asyncio.wait(
                    {input_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()

                if stop.is_set():
                    print()
                    break

                try:
                    user_input = input_task.result()
                except EOFError:
                    print()
                    break

                should_continue = await run_command(user_input)
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
    args = parser.parse_args()

    try:
        asyncio.run(loop(user=args.user, fsimage=args.fsimage, command=args.command, debug=args.debug, cost_limit=args.limit))
    except KeyboardInterrupt:
        pass
    finally:
        os._exit(0)