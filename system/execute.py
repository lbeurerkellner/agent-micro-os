from fs.utils import resolve_path
from fs.overlay import OverlayFS

from system.context import cprint
from system.program import parse, run

async def execute(ctx, filepath, *args):
    vault: OverlayFS = ctx.fs()

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if file exists
    if not vault.exists(vault_path):
        cprint(f"{filepath}: No such file or directory", file=ctx.stderr)
        return

    # Check if it's a directory
    if vault.is_dir(vault_path):
        cprint(f"{filepath} is a directory", file=ctx.stderr)
        return

    try:
        # get contents
        contents = vault.read(vault_path).decode('utf-8')
    except Exception as e:
        cprint(f"Error executing {filepath}: {str(e)}", file=ctx.stderr)
        return

    # Check for shebang (#!)
    if contents.startswith('#!'):
        # Extract the shebang line
        first_line, _, rest = contents.partition('\n')
        shebang = first_line[2:].strip()  # Remove #! and whitespace

        # Check if it's an ash script
        if shebang in ['/sbin/ash', '/bin/ash', 'ash']:
            # Execute as ash script (line-by-line)
            from bin.ash import run_script
            try:
                # get content, replacing all $@ with the arguments
                await run_script(rest)
            except Exception as e:
                cprint(f"Error running ash script {filepath}: {str(e)}", file=ctx.stderr)
            return

        # Check if it's a tool script (#!/bin/tool <description>)
        interpreter = shebang.split()[0] if shebang else ""
        if interpreter in ['/bin/tool', '/sbin/tool', 'tool']:
            await _run_tool_script(ctx, filepath, rest, *args)
            return

        cprint(f"{filepath}: unsupported interpreter: {shebang}", file=ctx.stderr)
        return

    # check for .PROMPT directive (may appear after other directives like .ENGINE, .BUDGET)
    if "\n.PROMPT\n" not in contents and not contents.startswith(".PROMPT\n"):
        cprint(f"{filepath} is not executable", file=ctx.stderr)
        return

    # parse the prompt program
    try:
        program = parse(contents)
    except Exception as e:
        cprint(f"Error parsing {filepath}: {str(e)}", file=ctx.stderr)
        return

    # run the program
    try:
        await run(program, filepath, *args)
    except Exception as e:
        cprint(f"Error running {filepath}: {str(e)}", file=ctx.stderr)
        return


async def _run_tool_script(ctx, filepath, script_body, *args):
    """Run a #!/bin/tool script in a sandboxed Python environment."""
    import uuid
    import shlex

    fs = ctx.fs()
    temp_id = str(uuid.uuid4())
    temp_file = f"tmp/tool_{temp_id}.py"
    fs.write(temp_file, script_body.strip().encode("utf-8"))

    try:
        from bin.sandbox import run as sandbox_run
        cmd = f"python /workspace/{temp_file}"
        if args:
            cmd += " " + " ".join(shlex.quote(a) for a in args)
        result = await sandbox_run(
            "--image", "python:3.12", "--cmd", cmd,
            readonly=False, quiet=True, capture=True,
        )
        if result:
            cprint(result)
    except Exception as e:
        cprint(f"Error running tool {filepath}: {str(e)}", file=ctx.stderr)
    finally:
        try:
            fs.delete(temp_file)
        except Exception:
            pass