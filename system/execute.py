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

        # Check if it's a Starlark script
        if shebang in ['/sbin/star', '/bin/star', 'star']:
            # Execute as Starlark script
            from bin.star import run as star_run
            try:
                await star_run("/" + vault_path, *args)
            except Exception as e:
                print(f"Error running Starlark script {filepath}: {str(e)}")
            return
        else:
            print(f"{filepath}: unsupported interpreter: {shebang}")
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