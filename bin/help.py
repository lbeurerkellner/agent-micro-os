from system.context import SystemContext, cprint
from system.tools import generate_agents_md

_USAGE = """\
help - Show the agent environment documentation (AGENTS.md preview)
"""


async def run(*args):
    ctx = SystemContext.current()
    cprint(generate_agents_md(ctx.fs()))
