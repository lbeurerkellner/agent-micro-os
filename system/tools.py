from system.context import SystemContext, cprint
import importlib
import textwrap
import io
import functools
from pathlib import Path


# static built-in tools
TOOLS = {}

# bin/ directory (project root / bin)
_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
# docs/ directory (project root / docs)
_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# Base docstring for ash (without commands list)
_ASH_BASE_DOC = """\
Executes a shell command. This is the only way to interact with the system. Use <command> -h for detailed usage of any command.

Available commands:
"""


@functools.cache
def _builtin_commands_summary() -> list[str]:
    """Scan bin/*.py and return one-liner descriptions (cached, runs once)."""
    lines = []
    for pyfile in sorted(_BIN_DIR.glob("*.py")):
        name = pyfile.stem
        if name in ("__init__", "ash"):
            continue
        try:
            mod = importlib.import_module(f"bin.{name}")
        except Exception:
            continue
        usage = getattr(mod, "_USAGE", None)
        if usage:
            lines.append(usage.strip().splitlines()[0])
        else:
            lines.append(name)
    return lines


def _vault_commands_summary(fs, access=None) -> list[str]:
    """List user-defined commands from vault bin/ directory."""
    builtin_names = {p.stem for p in _BIN_DIR.glob("*.py")} - {"__init__", "ash"}
    lines = []
    try:
        vault_bins = fs.list(prefix="bin")
    except Exception:
        return []
    # Filter by access globs when set
    if access:
        from bin.sandbox import _glob_match
        access_globs = [g for g, _ in access]
        vault_bins = [f for f in vault_bins if _glob_match(f, access_globs)]
    for filepath in sorted(vault_bins):
        if not filepath.startswith("bin/"):
            continue
        name = filepath[4:]  # strip "bin/"
        if not name or "/" in name or name in builtin_names:
            continue
        # Try to extract description from #!/bin/tool shebang
        try:
            content = fs.read(filepath).decode("utf-8")
            first_line = content.splitlines()[0] if content else ""
            if first_line.startswith("#!") and "tool" in first_line.split()[0]:
                # #!/bin/tool <description>
                desc = first_line.split(None, 1)[1] if " " in first_line else ""
                if desc:
                    lines.append(f"{name} - {desc}")
                else:
                    lines.append(name)
            else:
                lines.append(name)
        except Exception:
            lines.append(name)
    return lines


def build_ash_docstring(fs=None) -> str:
    """Build the full ash docstring with built-in and optionally vault commands."""
    lines = list(_builtin_commands_summary())
    if fs:
        lines.extend(_vault_commands_summary(fs))
    lines.sort(key=lambda l: l.split(" - ")[0] if " - " in l else l)
    return _ASH_BASE_DOC + "\n".join(lines)


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
    """Executes a shell command. This is the only way to interact with the system. Use <command> -h for detailed usage of any command."""
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


_AGENTS_TEMPLATE = (Path(__file__).resolve().parent.parent / "templates" / "AGENTS.md").read_text()


_SANDBOX_NOTE = (
    "\nThe working directory `/workspace` is a snapshot of the vault. The surrounding system at / is a standard Linux environment with access to typical tools (bash, python, etc.)."
    "When your session ends, any changes you made under `/workspace` are automatically diffed and committed back. Absolute paths listed below refer to the host environment; in your sandbox they are relative to `/workspace` (e.g. `/workspace/etc/crontab`, not `/etc/crontab`).\n\n"
    "You have full access to standard Linux tools (bash, python, etc.). Use them freely.\n"
    "Note that Agent Programs are not executable in your environment, but you can create or edit them for use by the host.\n"
    "Tool programs can be executed freely, but can also be edited and created for use by the host or this or future sandbox sessions.\n"
    "Any changes made to the system outside of /workspace (e.g. installing packages, modifying /etc) will persist for the duration of your session but will not be saved back to the vault or visible in future sessions."
)


def _docs_summary() -> str:
    """Build a Documentation section from docs/ files.

    Each doc file should have a one-sentence description as its first
    non-blank, non-heading line. That sentence is extracted and listed
    alongside the /docs/<path> mount path.
    """
    if not _DOCS_DIR.exists():
        return ""
    entries = []
    for doc_file in sorted(_DOCS_DIR.rglob("*")):
        if not doc_file.is_file():
            continue
        rel = doc_file.relative_to(_DOCS_DIR)
        mount_path = f"/docs/{rel}"
        desc = doc_file.stem  # fallback
        try:
            for line in doc_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Use only the first sentence
                dot = line.find(". ")
                desc = line[: dot + 1] if dot != -1 else line
                break
        except Exception:
            pass
        entries.append(f"- `{mount_path}` - {desc}")
    if not entries:
        return ""
    return "## Documentation\n\n" + "\n".join(entries) + "\n\n"


def generate_agents_md(fs, sandbox_note=False, access=None) -> str:
    """Generate the dynamic AGENTS.md content from template + custom tools."""
    vault_cmds = _vault_commands_summary(fs, access=access)
    if vault_cmds:
        custom_tools = "## Custom Tools\n\n" + "\n".join(f"- {line}" for line in vault_cmds) + "\n"
    else:
        custom_tools = ""
    
    # Build access policy markdown if access rules are provided
    access_control_note = ""

     # Append access policy section if access rules are set
    if access:
        rw_entries = [g for g, m in access if m == "rw"]
        ro_entries = [g for g, m in access if m == "ro"]
        access_control_note += "\n\n## File Access Policy\n\n"
        access_control_note += (
            "Your changes will be committed atomically when your session ends. "
            "If you write to, create, or delete any file outside the allowed read-write locations below, "
            "**your entire transaction will be rejected and ALL changes will be lost**.\n\n"
        )
        if rw_entries:
            access_control_note += "### Read-Write (you may read, execute, create, modify, and delete):\n"
            for g in rw_entries:
                access_control_note += f"- `{g}`\n"
            access_control_note += "\n"
        if ro_entries:
            access_control_note += "### Read-Only (you may read/execute but NOT modify):\n"
            for g in ro_entries:
                access_control_note += f"- `{g}`\n"
            access_control_note += "\n"

        access_control_note
    
    md = _AGENTS_TEMPLATE.replace("{{CUSTOM_TOOLS}}", custom_tools)
    
    md = md.replace("{{DOCS}}", _docs_summary())
    md = md.replace("{{SANDBOX_NOTE}}", _SANDBOX_NOTE if sandbox_note else "")
    md = md.replace("{{COMMIT_NOTE}}", """## Commit When You Are Done

When you have completed your modifications, write a concise commit message to `/workspace/COMMIT_MSG` describing the scope and reason for your changes. If there are follow-up changes, keep it updated.""" if sandbox_note else "")
    
    md = md.replace("{{ACCESS_CONTROL}}", access_control_note)
    
    return md.strip()


def make_ash_tool(fs=None):
    """Return a copy of the ash tool with a dynamic docstring that includes
    both built-in and vault user-defined commands."""
    @functools.wraps(ash)
    async def _ash(command: str) -> str:
        return await ash(command)
    _ash.__doc__ = build_ash_docstring(fs)
    return _ash
