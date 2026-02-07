async def run(*args):
    """Change the current directory."""
    from system.context import SystemContext
    import os

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) != 1:
        print("Usage: cd <directory>")
        return

    new_dir = args[0]

    # Handle absolute vs relative paths
    if new_dir.startswith('/'):
        # Absolute path
        target_path = new_dir
    else:
        # Relative path - join with current directory
        if ctx.cwd == '/':
            target_path = '/' + new_dir
        else:
            target_path = ctx.cwd + '/' + new_dir

    # Normalize the path (remove redundant slashes, handle . and ..)
    target_path = os.path.normpath(target_path)

    # Ensure it starts with /
    if not target_path.startswith('/'):
        target_path = '/' + target_path

    # Remove leading slash for vault operations (vault stores paths without leading /)
    vault_path = target_path.lstrip('/')

    vault = ctx.fs()
    if not vault.exists(vault_path):
        print(f"Directory '{target_path}' does not exist.")
        return

    if not vault.is_dir(vault_path):
        print(f"'{target_path}' is not a directory.")
        return

    ctx.cwd = target_path