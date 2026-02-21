import asyncio

from system.context import cprint


async def run(*args):
    """Sleep for a specified number of seconds."""
    if len(args) != 1:
        cprint("Usage: sleep SECONDS")
        return

    try:
        seconds = int(args[0])
    except ValueError:
        cprint(f"sleep: invalid number: {args[0]}")
        return

    await asyncio.sleep(seconds)
