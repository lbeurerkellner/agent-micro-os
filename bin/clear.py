import os

async def run():
    """Clear the console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')