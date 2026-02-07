"""Execute Starlark scripts from the vault."""
import sys
import asyncio
from io import StringIO


async def run(*args):
    """Execute a Starlark script file.

    Usage: star <script.star> [args...]

    The script will have access to:
    - fs['read'](path) - read file from vault
    - fs['write'](path, content) - write file to vault
    - fs['list'](path) - list directory contents
    - fs['delete'](path) - delete file
    - fs['exists'](path) - check if file exists
    - fs['is_dir'](path) - check if path is a directory
    - run_command(cmd) - execute ash shell command
    - print(...) - print output
    - args - list of command line arguments

    Note: Use bracket notation (fs['read']) instead of dot notation (fs.read)
    """
    from system.context import SystemContext
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        print("Usage: star <script.star> [args...]")
        return

    script_path = args[0]
    script_args = args[1:]

    # Resolve the script path
    _, vault_path = resolve_path(script_path, ctx.cwd)

    vault = ctx.fs()

    # Check if script exists
    if not vault.exists(vault_path):
        print(f"star: {script_path}: No such file or directory")
        return

    if vault.is_dir(vault_path):
        print(f"star: {script_path}: Is a directory")
        return

    # Read the script
    try:
        script_content = vault.read(vault_path).decode('utf-8')
    except UnicodeDecodeError:
        print(f"star: {script_path}: Not a valid text file")
        return
    except Exception as e:
        print(f"star: {script_path}: Error reading file: {e}")
        return

    # Get the running event loop
    loop = asyncio.get_running_loop()

    # Copy the current context to propagate it to the worker thread
    # This ensures SystemContext.current() works inside the thread
    import contextvars
    context = contextvars.copy_context()

    # Execute Starlark in a thread pool to avoid blocking the event loop
    # This allows multiple star scripts to run concurrently
    # Use context.run() to propagate context variables to the thread
    await loop.run_in_executor(
        None,  # Use default ThreadPoolExecutor
        context.run,
        _execute_starlark,
        script_content,
        vault_path,
        script_args,
        vault,
        ctx,
        loop  # Pass loop reference to the thread
    )


def _execute_starlark(script_content, vault_path, script_args, vault, ctx, event_loop):
    """Execute Starlark script in a worker thread.

    This runs in a worker thread, allowing the main event loop to remain free
    for other concurrent operations. Multiple star scripts can run in parallel,
    each in their own thread, sharing the same event loop for async operations.

    Args:
        script_content: The Starlark script source code
        vault_path: Path to the script file (for error messages)
        script_args: Command-line arguments passed to the script
        vault: The vault/filesystem instance
        ctx: The SystemContext
        event_loop: The main asyncio event loop for scheduling async operations
    """
    from starlark_go import Starlark
    from starlark_go.errors import SyntaxError as StarlarkSyntaxError, EvalError, ResolveError

    # Create standard library for Starlark (pass event_loop for async operations)
    fs_read, fs_write, fs_list, fs_delete, fs_exists, fs_is_dir, run_command = \
        create_fs_functions(vault, ctx, event_loop)

    # Capture print output
    output_buffer = StringIO()

    def star_print(text):
        """Print function for Starlark scripts."""
        output_buffer.write(text + '\n')

    # Create Starlark interpreter with custom print function
    star = Starlark(print=star_print)

    # Set up the environment
    try:
        # Register individual fs functions
        star.set(
            fs_read=fs_read,
            fs_write=fs_write,
            fs_list=fs_list,
            fs_delete=fs_delete,
            fs_exists=fs_exists,
            fs_is_dir=fs_is_dir,
        )

        # Register run_command
        star.set(run_command=run_command)

        # Add command line arguments
        star.set(args=list(script_args))

    except Exception as e:
        print(f"star: {vault_path}: Error setting up environment: {e}")
        return

    # Prepare the script with fs module wrapper using dictionary notation
    # Since Starlark doesn't support dot notation on dicts, we create a helper
    # Also wrap in main() function since control flow must be inside a function
    wrapped_script = """
# Create fs module using dict (use fs['read'](...) notation)
fs = {
    'read': fs_read,
    'write': fs_write,
    'list': fs_list,
    'delete': fs_delete,
    'exists': fs_exists,
    'is_dir': fs_is_dir,
}

# Wrap user script in main() function to allow top-level control flow
def _starlark_main():
""" + "\n".join("    " + line for line in script_content.splitlines()) + """

# Execute main function
_starlark_main()
"""

    # Execute the script (blocks THIS THREAD, not the event loop)
    try:
        # Execute the Starlark code
        star.exec(wrapped_script, filename=vault_path)

        # Print captured output
        output = output_buffer.getvalue()
        if output:
            print(output, end='')

    except StarlarkSyntaxError as e:
        print(f"star: {vault_path}: Syntax error: {e}")
        return
    except EvalError as e:
        print(f"star: {vault_path}: Runtime error: {e}")
        return
    except ResolveError as e:
        print(f"star: {vault_path}: Name error: {e}")
        return
    except Exception as e:
        print(f"star: {vault_path}: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return


def create_fs_functions(vault, ctx, event_loop):
    """Create filesystem functions for Starlark.

    Args:
        vault: The OverlayFS instance
        ctx: The SystemContext
        event_loop: The main asyncio event loop to schedule async operations on

    Returns:
        Tuple of (fs_read, fs_write, fs_list, fs_delete, fs_exists, fs_is_dir, run_command)
    """
    from fs.utils import resolve_path

    def fs_read(path):
        """Read a file from the vault.

        Args:
            path: Path to the file (relative or absolute)

        Returns:
            File contents as a string
        """
        _, vault_path = resolve_path(path, ctx.cwd)
        try:
            content = vault.read(vault_path)
            return content.decode('utf-8')
        except UnicodeDecodeError:
            # Return bytes representation for binary files
            return f"<binary data: {len(content)} bytes>"
        except FileNotFoundError:
            raise Exception(f"File not found: {path}")

    def fs_write(path, content):
        """Write a file to the vault.

        Args:
            path: Path to the file (relative or absolute)
            content: Content to write (string)
        """
        _, vault_path = resolve_path(path, ctx.cwd)
        if isinstance(content, str):
            content = content.encode('utf-8')
        vault.write(vault_path, content, author="starlark")

    def fs_list(path="/"):
        """List directory contents.

        Args:
            path: Directory path (default: root)

        Returns:
            List of filenames (not full paths, just basenames)
        """
        _, vault_path = resolve_path(path, ctx.cwd)

        # Ensure path ends with / for directory listing
        if not vault_path.endswith('/'):
            vault_path += '/'

        # Get all files in the vault
        all_files = vault.list()

        # Filter files that are in this directory
        prefix = vault_path
        result = []

        for filepath in all_files:
            if filepath.startswith(prefix):
                # Get the relative path
                relative = filepath[len(prefix):]
                # Only include immediate children (no nested paths)
                if '/' not in relative or relative.endswith('/'):
                    # Extract just the filename
                    filename = relative.rstrip('/')
                    if filename and filename not in result:
                        result.append(filename)

        return result

    def fs_delete(path):
        """Delete a file from the vault.

        Args:
            path: Path to the file (relative or absolute)
        """
        _, vault_path = resolve_path(path, ctx.cwd)
        try:
            vault.delete(vault_path)
        except FileNotFoundError:
            raise Exception(f"File not found: {path}")

    def fs_exists(path):
        """Check if a file or directory exists.

        Args:
            path: Path to check (relative or absolute)

        Returns:
            True if exists, False otherwise
        """
        _, vault_path = resolve_path(path, ctx.cwd)
        return vault.exists(vault_path)

    def fs_is_dir(path):
        """Check if a path is a directory.

        Args:
            path: Path to check (relative or absolute)

        Returns:
            True if directory, False otherwise
        """
        _, vault_path = resolve_path(path, ctx.cwd)
        return vault.is_dir(vault_path)

    def run_command(command):
        """Run an ash shell command from Starlark.

        This is called from Starlark (sync context in a worker thread).
        It schedules the async command on the main event loop and waits
        for completion, allowing multiple scripts to have their commands
        interleaved on the event loop.

        Args:
            command: Command string to execute (e.g., "ls -la", "cat file.txt")

        Returns:
            Command output as a string
        """
        from bin.ash import run_command as ash_run_command

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            # Schedule the async command on the main event loop from this thread
            # This allows concurrent execution of multiple scripts' commands
            future = asyncio.run_coroutine_threadsafe(
                ash_run_command(command),
                event_loop  # Use the passed event loop, don't create a new one
            )

            # Block THIS THREAD (not the event loop) until the command completes
            # The event loop remains free to process other async operations
            future.result()

            # Get the output
            output = sys.stdout.getvalue()
            return output
        finally:
            # Restore stdout
            sys.stdout = old_stdout

    return fs_read, fs_write, fs_list, fs_delete, fs_exists, fs_is_dir, run_command
