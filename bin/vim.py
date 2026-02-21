import subprocess
import tempfile
import os

def edit_with_vim(initial_text=""):
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as tf:
        tf.write(initial_text)
        tf.flush()
        temp_path = tf.name
    
    subprocess.call(['vim', temp_path])
    
    with open(temp_path, 'r') as f:
        result = f.read()
    
    os.unlink(temp_path)
    return result

async def run(*args):
    """Edit a file using vim."""
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        cprint("Usage: vim <file>")
        return

    if len(args) > 1:
        cprint("vim: only single file editing is supported")
        return

    vault = ctx.fs()
    filepath = args[0]

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if file exists and read content
    initial_content = ""
    if vault.exists(vault_path):
        # Check if it's a directory
        if vault.is_dir(vault_path):
            cprint(f"vim: {filepath}: Is a directory")
            return

        # Read existing file content
        try:
            content_bytes = vault.read(vault_path)
            try:
                initial_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                cprint(f"vim: {filepath}: Cannot edit binary file")
                return
        except Exception as e:
            cprint(f"vim: {filepath}: Error reading file: {e}")
            return

    # Edit with vim
    try:
        edited_content = edit_with_vim(initial_content)

        # Write back to vault
        vault.write(vault_path, edited_content.encode('utf-8'))
    except Exception as e:
        cprint(f"vim: {filepath}: Error: {e}")
