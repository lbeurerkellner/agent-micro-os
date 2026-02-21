from system.context import SystemContext, cprint
import textwrap
from pathlib import Path
import importlib
import inspect
import io
import shlex

# static built-in tools
TOOLS = {}

# bin/ directory (project root / bin)
_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"

# Commands to skip when auto-discovering bin/ tools
# (interactive, internal, or already exposed differently)
_SKIP_COMMANDS = {"__init__", "ash", "edit", "vim"}


def _discover_bin_tools():
    """Scan bin/*.py for modules with _USAGE and register them as tools."""
    for pyfile in sorted(_BIN_DIR.glob("*.py")):
        name = pyfile.stem
        if name in _SKIP_COMMANDS:
            continue

        # Try to import and check for _USAGE
        module_name = f"bin.{name}"
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue

        usage = getattr(mod, "_USAGE", None)
        if not usage:
            continue

        run_fn = getattr(mod, "run", None)
        if not run_fn:
            continue

        # Extract description from first line: "name - Description"
        first_line = usage.strip().splitlines()[0]
        remainder = usage.strip()[len(first_line):].strip()
        if " - " in first_line:
            description = first_line.split(" - ", 1)[1]
        else:
            description = first_line

        # Create the tool wrapper
        _register_bin_tool(name, description.strip() + "\n\n" + remainder, run_fn)


def _register_bin_tool(name, description, run_fn):
    """Register a bin/ command as a tool with signature cmd(args: list[str]) -> str."""

    async def _tool_wrapper(args: list[str] = []) -> str:
        ctx = SystemContext.current()
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        # check whether run_fn has tool_use_mode parameter, if so, specify it to True
        signature = inspect.signature(run_fn)
        if "tool_use_mode" in signature.parameters:
            kwargs = {"tool_use_mode": True}
        else:
            kwargs = {}

        with ctx.child(stdout=stdout_buf, stderr=stderr_buf):
            try:
                result = await run_fn(*args, **kwargs)
            except Exception as e:
                return f"Error: {e}"
        output = stdout_buf.getvalue()
        err_output = stderr_buf.getvalue()
        if err_output:
            output += err_output
        if result is not None:
            output += str(result)
        return output.strip()

    _tool_wrapper.__name__ = name
    _tool_wrapper.__qualname__ = name
    _tool_wrapper.__doc__ = description
    TOOLS[name] = _tool_wrapper


class ToolProvider:
    """Provides access to both built-in tools and custom .tool files from /bin/"""

    def __init__(self, ctx: SystemContext):
        self.ctx = ctx
        self.custom_tools_cache = None  # Cache for custom tools to avoid repeated vault access

    def _load_custom_tools(self):
        """Load .tool files from /bin/ directory (real-time, not cached)"""
        if self.custom_tools_cache is not None:
            return self.custom_tools_cache

        custom_tools = {}
        try:
            from fs.vault import Vault

            # Access vault directly to avoid circular dependencies with overlay providers
            vault = Vault(self.ctx.fsimage, self.ctx.user)

            # List all files in vault and filter for .tool files in bin/
            try:
                all_files = vault.list(prefix="bin")
                bin_tools = [f for f in all_files if f.startswith("bin/")]

                for filepath in bin_tools:
                    # Extract tool name from bin/name
                    tool_name = filepath[4:]
                    try:
                        if tool := self._create_tool_wrapper(tool_name):
                            custom_tools[tool_name] = tool
                    except Exception as e:
                        cprint(f"Warning: Failed to load tool {tool_name}: {e}", file=self.ctx.stderr)
            except Exception:
                # Vault doesn't exist or can't be listed, return empty dict
                return {}
        except Exception as e:
            cprint(f"Warning: Failed to load custom tools: {e}", file=self.ctx.stderr)

        # cache the loaded tools
        self.custom_tools_cache = custom_tools

        return custom_tools

    def _parse_tool_file(self, content):
        """Parse a .tool file structure"""
        lines = content.splitlines()
        description = []
        implementation = []
        section = None

        for line in lines:
            stripped = line.strip()
            if stripped == ".DESCRIPTION":
                section = "description"
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
            'implementation': '\n'.join(implementation).strip()
        }

    def _create_tool_wrapper(self, tool_name):
        """Create a callable wrapper for a custom .tool file"""
        fs = self.ctx.fs()

        # Read and parse the .tool file
        content = fs.read(f"bin/{tool_name}").decode('utf-8')
        if ".DESCRIPTION" not in content:
            return None
        parsed = self._parse_tool_file(content)

        # Create the wrapper function dynamically using exec
        func_code = f'''async def {tool_name}(args: list[str] = []) -> str:
    """{parsed['description']}\n\nImplementation in /bin/{tool_name}"""
    return await _execute_tool({repr(tool_name)}, {repr(parsed)}, args)
'''

        namespace = {'_execute_tool': self._execute_custom_tool}
        exec(func_code, namespace)
        func = namespace[tool_name]

        return func

    async def _execute_custom_tool(self, tool_name, parsed, args, quiet=True, capture=True):
        """Execute a custom tool by running its implementation in a sandbox"""
        import uuid
        from bin.sandbox import run as sandbox_run

        fs = self.ctx.fs()

        # Write implementation to a temporary file
        temp_id = str(uuid.uuid4())
        temp_file = f"tmp/tool_{temp_id}.py"
        fs.write(temp_file, parsed['implementation'].encode('utf-8'))

        try:
            # Build the command, passing args as-is
            cmd = f"python /workspace/{temp_file}"
            if args:
                cmd += " " + " ".join(shlex.quote(a) for a in args)

            # execute via sandbox with --cmd
            return await sandbox_run("--image", "python:3.12", "--cmd", cmd, readonly=False, quiet=quiet, capture=capture)
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

    def list(self):
        """List all available tools (built-in and custom)"""
        custom_tools = self._load_custom_tools()
        return list(TOOLS.keys()) + list(custom_tools.keys())

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
async def ash(command: str) -> str:
    """Executes an 'ash' shell command in the current context. See ls /sbin and ls /bin for available commands. Note that this is only a very restricted shell environment. You always should prefer using dedicated tools, and otherwise check /sbin and /bin before running a command with this."""
    from bin.ash import run_command

    ctx = SystemContext.current()
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    with ctx.child(interactive=False, stdout=stdout_buf, stderr=stderr_buf):
        try:
            result = await run_command(command)
        except Exception as e:
            return f"Error executing command: {e}\n{stderr_buf.getvalue()}"

    output = stdout_buf.getvalue()
    if result is not None:
        output += f"\nCommand result: {result}"
    error_output = stderr_buf.getvalue()
    if error_output:
        output += f"\nError output: {error_output}"
    return output.strip()

@tool
def create_tool(name: str, description: str, implementation: str) -> str:
    """
    Creates a new tool executable in the form of a CLI executable in /bin/<name>.

    The tool executable will be created at /bin/<name> in the vault and contains:

    .DESCRIPTION
    <description text>

    .IMPL
    <python implementation>

    Parameters:
    - name: The tool name (creates /bin/<name>)
    - description: Text describing what the tool does so others know how to use it exactly (for .DESCRIPTION section)
    - implementation: Python script for the .IMPL section

    The tool receives a single `args: str` argument. The implementation can parse arguments from sys.argv as needed.

    The Python implementation will be executed in a sandboxed environment where
    /workspace is the current working directory, containing a copy of the / (root)
    of the current environment. The tool can read/write files relative to /workspace.

    Once created, the tool will be exposed as /bin/<executable> but also show up as a system-mounted tool in the virtual filesystem at /tool/<name>.

    You should use the 'ash' tool to test the created tool directly via 'ash <toolname> <args>' after creation. It may be helpful to debug the tool with some simple inputs, before you finalize.

    Example:
    create_tool(
        name="wordcount",
        description="Counts words in a file",
        implementation="import sys\\nwith open(f'/workspace/{sys.argv[1]}') as f:\\n    print(len(f.read().split()))"
    )
    """
    ctx = SystemContext.current()
    fs = ctx.fs()

    # Construct the filepath
    filepath = f"bin/{name}"

    # Check if file already exists
    if fs.exists(filepath):
        return f"Error: Tool /bin/{name} already exists"

    # Build the tool file content
    content = f".DESCRIPTION\n{description}\n\n.IMPL\n{implementation}\n"

    # Write the file
    fs.write(filepath, content.encode('utf-8'))

    return f"Created tool at /bin/{name}"


# Auto-discover bin/ commands at import time
_discover_bin_tools()
