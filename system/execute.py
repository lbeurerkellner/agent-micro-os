from fs.utils import resolve_path
from fs.overlay import OverlayFS

from system.program import parse, run

async def execute(ctx, filepath, *args):
    vault: OverlayFS = ctx.fs()

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if file exists
    if not vault.exists(vault_path):
        print(f"{filepath}: No such file or directory")
        return

    # Check if it's a directory
    if vault.is_dir(vault_path):
        print(f"{filepath} is a directory")
        return

    try:
        # get contents
        contents = vault.read(vault_path).decode('utf-8')
    except Exception as e:
        print(f"Error executing {filepath}: {str(e)}")
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
                print(f"Error running ash script {filepath}: {str(e)}")
            return
        else:
            print(f"{filepath}: unsupported interpreter: {shebang}")
            return

    # check for .DESCRIPTION/.IMPL (custom tool file)
    if ".DESCRIPTION" in contents and ".IMPL" in contents:
        from system.tools import ToolProvider
        from system.context import SystemContext

        provider = ToolProvider(SystemContext.current())
        parsed = provider._parse_tool_file(contents)

        args_str = " ".join(args) if args else ""
        try:
            result = await provider._execute_custom_tool(
                vault_path.split("/")[-1], parsed, args_str, quiet=True, capture=False
            )
            if result:
                print(result)
        except Exception as e:
            print(f"Error running tool {filepath}: {str(e)}")
        return

    # check for .PROMPT directive
    if not contents.startswith(".PROMPT\n"):
        print(f"{filepath} is not executable")
        return

    # parse the prompt program
    try:
        program = parse(contents)
    except Exception as e:
        print(f"Error parsing {filepath}: {str(e)}")
        return

    # run the program
    try:
        await run(program, filepath, *args)
    except Exception as e:
        print(f"Error running {filepath}: {str(e)}")
        return