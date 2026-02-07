"""Display manual pages for commands."""
import os
from pathlib import Path


async def run(*args):
    """Display the manual page for a command.

    Usage: man <command>

    Shows the documentation for the specified command from the docs/ directory.
    """
    if len(args) == 0:
        print("Usage: man <command>")
        print()
        print("Available manual pages:")

        # List all available man pages
        docs_dir = Path(__file__).parent.parent / "docs"
        if docs_dir.exists():
            man_pages = sorted([f.stem for f in docs_dir.glob("*.md")])
            if man_pages:
                for page in man_pages:
                    print(f"  {page}")
            else:
                print("  (no manual pages available)")
        else:
            print("  (docs directory not found)")
        return

    command = args[0]

    # Find the documentation file
    docs_dir = Path(__file__).parent.parent / "docs"
    doc_path = docs_dir / f"{command}.md"

    if not doc_path.exists():
        print(f"man: No manual entry for {command}")
        print()
        print("Try 'man' without arguments to see available manual pages.")
        return

    # Read and display the documentation
    try:
        content = doc_path.read_text()
        print(content)
    except Exception as e:
        print(f"man: Error reading manual page for {command}: {e}")
