from system.context import SystemContext, cprint
from system.tools import build_ash_docstring

_USAGE = """\
help - Show available commands and their descriptions
"""


async def run(*args):
    ctx = SystemContext.current()
    cprint(build_ash_docstring(ctx.fs()))
