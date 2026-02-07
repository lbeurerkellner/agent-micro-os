import os
import asyncio
from agentpy.agent import Agent, context, auto, tool
from fs import Vault

user = "bob"
vault = Vault("vaultdata.db", user=user)

@tool
def read(filepath: str) -> str:
    """Reads the contents of a file."""
    return vault.read(filepath).decode('utf-8')

@tool
def list_directory(path: str = ".") -> str:
    """Lists the contents of a specified directory path."""
    entries = ['.', '..']

    # Get all files and directories
    files = vault.list()

    # Normalize the path for comparison
    if path == '/' or path == '.':
        prefix = ''
        # For root directory, we need special handling
        check_root = True
    else:
        prefix = path.rstrip('/') + '/'
        check_root = False

    # Find direct children (files and dirs)
    seen = set()

    for filepath in files:
        # For root directory, skip files that start with /
        if check_root:
            # Skip files that have a leading slash followed by content
            if filepath.startswith('/'):
                filepath = filepath[1:]  # Remove leading slash
            
            # Check if this is a direct child of root
            if '/' in filepath:
                # This is in a subdirectory
                subdir = filepath.split('/')[0]
                if subdir and subdir not in seen:
                    entries.append(subdir)
                    seen.add(subdir)
            else:
                # Direct file in root
                if filepath and filepath not in seen:
                    entries.append(filepath)
                    seen.add(filepath)
        else:
            # Check if this file is in the current directory
            if not filepath.startswith(prefix):
                continue

            # Get the relative path from current directory
            rel_path = filepath[len(prefix):]

            # Only include direct children (no /)
            if '/' not in rel_path:
                if rel_path not in seen:
                    entries.append(rel_path)
                    seen.add(rel_path)
            else:
                # This is in a subdirectory, add the subdirectory name
                subdir = rel_path.split('/')[0]
                if subdir not in seen:
                    entries.append(subdir)
                    seen.add(subdir)

    if len(entries) == 2:
        return "Directory is empty."

    return entries

@tool
def write(filepath: str, content: str) -> str:
    """
    Writes content to a specified file.
    
    Non-existent directory path components are created as needed.
    """
    vault.write(filepath, content.encode('utf-8'))
    return f"Wrote to {filepath}"

@tool
def delete(filepath: str) -> str:
    """Deletes a specified file."""
    vault.delete(filepath)
    return f"Deleted {filepath}"

async def amain():
    agent = Agent(
        "You are a helpful assistant with access to file system tools. You can read files, write files, and list directories. When using tools, explain what you're doing step by step.",
        model="gpt-5-nano",
        tools=auto()
    )
    await agent.cli(persistent=False)

if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print("\nExiting...")