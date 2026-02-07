from system.context import SystemContext
import textwrap
from contextlib import redirect_stdout, redirect_stderr

TOOLS: dict[str, callable] = {}

def tool(func):
    TOOLS[func.__name__] = func
    return func


def tool_description(func):
    return textwrap.dedent(func.__doc__ or "").strip()

def tool_signature(func):
    """
    Returns <toolname>(param1[: type], param2[: type]=default, ...)
    """
    from inspect import signature
    sig = signature(func)
    params = []
    for name, param in sig.parameters.items():
        param_str = name
        if param.annotation != param.empty:
            param_str += f": {param.annotation.__name__}"
        if param.default != param.empty:
            param_str += f"={param.default!r}"
        params.append(param_str)
    return f"{func.__name__}({', '.join(params)})"

@tool
def read(filepath: str) -> str:
    """Reads the contents of a file."""
    return SystemContext.current().fs().read(filepath).decode('utf-8')

@tool
def list_directory(path: str = ".") -> str:
    """Lists the contents of a specified directory path."""
    from bin.ls import _list_directory
    result = ""
    for entry in _list_directory(SystemContext.current().fs(), path):
        result += entry + "\n"
    return result.strip()

@tool
def write(filepath: str, content: str) -> str:
    """
    Writes content to a specified file.
    
    Non-existent directory path components are created as needed.
    """
    SystemContext.current().fs().write(filepath, content.encode('utf-8'))
    return f"Wrote to {filepath}"

@tool
def delete(filepath: str) -> str:
    """Deletes a specified file."""
    SystemContext.current().fs().delete(filepath)
    return f"Deleted {filepath}"

@tool
def grep(pattern: str, path: str = ".", recursive: bool = True, ignore_case: bool = False) -> str:
    """
    Searches file contents for lines matching a regex pattern.

    Returns matching lines prefixed with filepath and line number.
    Searches recursively by default. Read-only — never modifies files.
    """
    from bin.grep import _grep_files, _collect_files_recursive, _filter_files, GrepOptions
    ctx = SystemContext.current()
    vault = ctx.fs()
    abs_path, vault_path = None, path.strip("/")

    # Resolve path
    from fs.utils import resolve_path as _resolve
    abs_path, vault_path = _resolve(path, ctx.cwd)

    if recursive and vault.is_dir(vault_path):
        files = _collect_files_recursive(vault, abs_path)
    elif vault.exists(vault_path):
        files = [vault_path]
    else:
        return f"grep: {path}: No such file or directory"

    results = _grep_files(vault, pattern, files, ignore_case=ignore_case)
    if not results:
        return "No matches found."

    lines = []
    for filepath, lineno, text in results:
        lines.append(f"{filepath}:{lineno}:{text}")
    return "\n".join(lines)

@tool
def sleep(seconds: int) -> str:
    """Sleeps for the specified number of seconds."""
    import time
    time.sleep(seconds)
    return f"Slept for {seconds} seconds"

@tool
async def ash(command: str) -> str:
    """Executes an 'ash' shell command in the current context. See ls /sbin and ls /bin for available commands. See man <command> for details on specific commands."""
    from bin.ash import run_command

    # Capture stdout and stderr
    import io
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            result = await run_command(command)
        except Exception as e:
            return f"Error executing command: {e}\n{stderr.getvalue()}"
        
    output = stdout.getvalue()
    if result is not None:
        output += f"\nCommand result: {result}"
    error_output = stderr.getvalue()
    if error_output:
        output += f"\nError output: {error_output}"
    return output.strip()