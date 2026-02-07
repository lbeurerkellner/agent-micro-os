import asyncio


async def run(*args):
    """Sleep for a specified number of seconds."""
    if len(args) != 1:
        print("Usage: sleep SECONDS")
        return

    try:
        seconds = int(args[0])
    except ValueError:
        print(f"sleep: invalid number: {args[0]}")
        return

    await asyncio.sleep(seconds)
