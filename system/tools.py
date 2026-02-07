from system.context import SystemContext
import textwrap
from contextlib import redirect_stdout, redirect_stderr

# static built-in tools
TOOLS = {}

class ToolProvider:
    """Provides access to both built-in tools and custom .tool files from /bin/"""

    def __init__(self, ctx: SystemContext):
        self.ctx = ctx

    def _load_custom_tools(self):
        """Load .tool files from /bin/ directory (real-time, not cached)"""
        custom_tools = {}
        try:
            from fs.vault import Vault

            # Access vault directly to avoid circular dependencies with overlay providers
            vault = Vault(self.ctx.fsimage, self.ctx.user)

            # List all files in vault and filter for .tool files in bin/
            try:
                all_files = vault.list()
                bin_tools = [f for f in all_files if f.startswith("bin/") and f.endswith(".tool")]

                for filepath in bin_tools:
                    # Extract tool name from bin/name.tool
                    tool_name = filepath[4:-5]  # Remove "bin/" prefix and ".tool" suffix
                    try:
                        custom_tools[tool_name] = self._create_tool_wrapper(tool_name)
                    except Exception as e:
                        print(f"Warning: Failed to load tool {tool_name}: {e}")
            except Exception:
                # Vault doesn't exist or can't be listed, return empty dict
                return {}
        except Exception as e:
            print(f"Warning: Failed to load custom tools: {e}")

        return custom_tools

    def _parse_tool_file(self, content):
        """Parse a .tool file structure"""
        lines = content.splitlines()
        description = []
        arguments = []
        implementation = []
        section = None

        for line in lines:
            stripped = line.strip()
            if stripped == ".DESCRIPTION":
                section = "description"
                continue
            elif stripped.startswith(".ARGUMENT"):
                # Parse .ARGUMENT name type
                parts = stripped.split()
                if len(parts) >= 3:
                    arg_name = parts[1]
                    arg_type = parts[2]
                    arguments.append({'name': arg_name, 'type': arg_type})
                continue
            elif stripped == ".IMPL":
                section = "implementation"
                continue

            if section == "description":
                description.append(line)
            elif section == "implementation":
                implementation.append(line)

        return {
            'description': '\n'.join(description).strip(),
            'arguments': arguments,
            'implementation': '\n'.join(implementation).strip()
        }

    def _create_tool_wrapper(self, tool_name):
        """Create a callable wrapper for a custom .tool file"""
        fs = self.ctx.fs()

        # Read and parse the .tool file
        content = fs.read(f"bin/{tool_name}.tool").decode('utf-8')
        parsed = self._parse_tool_file(content)

        # Build function signature string
        params = []
        for arg in parsed['arguments']:
            params.append(f"{arg['name']}: {arg['type']}")

        params_str = ', '.join(params)
        param_names = [arg['name'] for arg in parsed['arguments']]

        # Create the wrapper function dynamically using exec
        func_code = f'''async def {tool_name}({params_str}) -> str:
    """{parsed['description']}"""
    return await _execute_tool({repr(tool_name)}, {repr(parsed)}, {repr(param_names)}, locals())
'''

        namespace = {'_execute_tool': self._execute_custom_tool}
        exec(func_code, namespace)
        func = namespace[tool_name]

        return func

    async def _execute_custom_tool(self, tool_name, parsed, param_names, local_vars):
        """Execute a custom tool by running its implementation in a sandbox"""
        import uuid
        from bin.sandbox import run as sandbox_run

        fs = self.ctx.fs()

        # Build the full script with argument extraction
        script_lines = ["import sys", ""]

        # Add argument extractions: arg_name = sys.argv[1], etc.
        for i, param_name in enumerate(param_names, start=1):
            script_lines.append(f"{param_name} = sys.argv[{i}]")

        script_lines.append("")
        script_lines.append(parsed['implementation'])

        script = '\n'.join(script_lines)

        # Write to a temporary file
        temp_id = str(uuid.uuid4())
        temp_file = f"tmp/tool_{temp_id}.py"
        fs.write(temp_file, script.encode('utf-8'))

        try:
            # Build the command with arguments
            arg_values = [str(local_vars[name]) for name in param_names]
            # Properly escape arguments for shell (shlex.quote wraps in
            # single-quotes, which preserves JSON double-quotes intact)
            import shlex
            escaped_args = ' '.join(shlex.quote(str(val)) for val in arg_values)
            cmd = f"python /workspace/{temp_file} {escaped_args}".strip()

            # execute via sandbox with --cmd
            return await sandbox_run("--image", "python:3.12", "--cmd", cmd, readonly=True, quiet=True, capture=True)
        finally:
            # Clean up temp file
            try:
                fs.delete(temp_file)
            except Exception:
                pass

    def __contains__(self, key):
        """Check if a tool exists (built-in or custom)"""
        if key in TOOLS:
            return True
        custom_tools = self._load_custom_tools()
        return key in custom_tools

    def __getitem__(self, key):
        """Get a tool by name"""
        if key in TOOLS:
            return TOOLS[key]
        custom_tools = self._load_custom_tools()
        if key in custom_tools:
            return custom_tools[key]
        raise KeyError(f"Tool '{key}' not found")

    def get(self, key, default=None):
        """Get a tool with optional default"""
        try:
            return self[key]
        except KeyError:
            return default
        
    def keys(self):
        """Return all available tool names"""
        custom_tools = self._load_custom_tools()
        return list(TOOLS.keys()) + list(custom_tools.keys())

def tool(func):
    """Decorator to register a built-in tool"""
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
    from bin.grep import _grep_files, _collect_files_recursive
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

@tool
def create_tool(name: str, description: str, arguments: str, implementation: str) -> str:
    """
    Creates a new tool file in /bin/<name>.tool with a structured format.

    The tool file will be created at /bin/<name>.tool in the vault and contains:

    .DESCRIPTION
    <description text>

    .ARGUMENT <name> <type>
    .ARGUMENT <name> <type>
    ...

    .IMPL
    <python implementation>

    Parameters:
    - name: The tool name (creates /bin/<name>.tool)
    - description: Text describing what the tool does (for .DESCRIPTION section)
    - arguments: Newline-separated list of "<name> <type>" pairs for .ARGUMENT lines
                 (e.g., "filepath str\\ncount int"). Leave empty if no arguments.
    - implementation: Python script for the .IMPL section

    The Python implementation will be executed in a sandboxed environment where
    /workspace is the current working directory, containing a copy of the / (root)
    of the current environment. The tool can read/write files relative to /workspace.

    Example:
    create_tool(
        name="wordcount",
        description="Counts words in a file",
        arguments="filepath str",
        implementation="with open(f'/workspace{filepath}') as f:\\n    print(len(f.read().split()))"
    )
    """
    ctx = SystemContext.current()
    fs = ctx.fs()

    # Construct the filepath
    filepath = f"bin/{name}.tool"

    # Check if file already exists
    if fs.exists(filepath):
        return f"Error: Tool /bin/{name}.tool already exists"

    # Build the tool file content
    content = f".DESCRIPTION\n{description}\n\n"

    # Add arguments if provided
    if arguments.strip():
        for arg_line in arguments.strip().split("\n"):
            arg_line = arg_line.strip()
            if arg_line:
                content += f".ARGUMENT {arg_line}\n"
        content += "\n"

    content += f".IMPL\n{implementation}\n"

    # Write the file
    fs.write(filepath, content.encode('utf-8'))

    return f"Created tool at /bin/{name}.tool"