import asyncio
import io

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout

from system.context import SystemContext, cprint


async def capture_command_output(command_str: str) -> str:
    """Run a shell command and capture its stdout."""
    from bin.ash import run_command

    buf = io.StringIO()
    ctx = SystemContext.current()
    with ctx.child(stdout=buf):
        await run_command(command_str)
    return buf.getvalue()


async def run(*args):
    """Repeatedly run a command at a fixed interval.

    Usage: watch -n SECONDS COMMAND [ARGS...]
    """
    if len(args) < 3 or args[0] != '-n':
        cprint("Usage: watch -n SECONDS COMMAND [ARGS...]")
        return

    try:
        interval = int(args[1])
    except ValueError:
        cprint(f"watch: invalid interval: {args[1]}")
        return

    command_str = ' '.join(args[2:])

    state = {"text": "Loading..."}

    kb = KeyBindings()

    @kb.add("q")
    def quit_watch(event):
        event.app.exit()

    @kb.add("c-c")
    def ctrl_c(event):
        event.app.exit()

    def get_text():
        return state["text"]

    header_text = f"  Every {interval}s: {command_str}    (q to quit)"
    header = FormattedTextControl(text=header_text)
    body = FormattedTextControl(text=get_text)

    root = HSplit([
        Window(content=header, height=1),
        Window(content=FormattedTextControl(text=""), height=1),
        Window(content=body, dont_extend_height=True),
        Window(),  # spacer absorbs remaining space
    ])

    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        full_screen=True,
    )

    async def refresh_loop():
        try:
            while True:
                output = await capture_command_output(command_str)
                state["text"] = output.rstrip("\n")
                app.invalidate()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def run_app():
        refresh_task = asyncio.create_task(refresh_loop())
        try:
            await app.run_async()
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass

    await run_app()
