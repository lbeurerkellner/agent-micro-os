"""Test program execution (.PROMPT files) with mocked LLM runner."""

import io
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from system.context import SystemContext
from fs.providers import BinProvider, ToolsFolderProvider
from bin.ash import run_command


def _make_stream_events(text: str):
    """Build a list of mock RawResponsesStreamEvent objects that simulate
    a simple text-only LLM response (no tool calls)."""
    from agents import RawResponsesStreamEvent

    events = []

    # text delta — delivers content to the streaming handler
    events.append(RawResponsesStreamEvent(
        data=SimpleNamespace(type="response.output_text.delta", delta=text),
    ))

    # text done — finalises the message for tracing
    events.append(RawResponsesStreamEvent(
        data=SimpleNamespace(type="response.output_text.done", text=text),
    ))

    # response.completed — delivers usage stats
    events.append(RawResponsesStreamEvent(
        data=SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5)),
        ),
    ))

    return events


def _mock_run_streamed(events):
    """Return a mock that replaces Runner.run_streamed.

    The returned object has a stream_events() async iterator that yields
    the given events list.
    """
    async def _stream():
        for e in events:
            yield e

    mock_result = SimpleNamespace(stream_events=_stream)
    return mock_result


async def test_program_text_output(temp_db):
    """A .PROMPT program should produce text output from the LLM."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.mount("tools", ToolsFolderProvider(ctx))
        vault = ctx.fs()

        # set up model config — provider and model just need to pass has_provider/has_model
        vault.write("etc/model/default", b"echo echo")

        # write a simple program
        vault.write("greet", b".PROMPT\nGreet the user in a silly way\n")

        events = _make_stream_events("Hello there, silly human!")
        mock_runner = lambda *a, **kw: _mock_run_streamed(events)

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("agents.Runner.run_streamed", side_effect=mock_runner):
                await run_command("./greet")

        result = output.getvalue()
        assert "Hello there, silly human!" in result


async def test_program_with_redirect(temp_db):
    """Running a program with > should capture LLM output into a file."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.mount("tools", ToolsFolderProvider(ctx))
        vault = ctx.fs()

        vault.write("etc/model/default", b"echo echo")
        vault.write("greet", b".PROMPT\nGreet the user\n")

        events = _make_stream_events("Redirected greeting!")
        mock_runner = lambda *a, **kw: _mock_run_streamed(events)

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("agents.Runner.run_streamed", side_effect=mock_runner):
                await run_command("./greet > /out.txt")

        # stdout should be empty (redirected)
        assert output.getvalue().strip() == ""

        # file should contain the output
        content = ctx.fs().read("/out.txt").decode("utf-8")
        assert "Redirected greeting!" in content


async def test_program_writes_trace(temp_db):
    """Running a program should create a trajectory trace file."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.mount("tools", ToolsFolderProvider(ctx))
        vault = ctx.fs()

        vault.write("etc/model/default", b"echo echo")
        vault.write("agent", b".PROMPT\nDo something\n")

        events = _make_stream_events("I did something!")
        mock_runner = lambda *a, **kw: _mock_run_streamed(events)

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("agents.Runner.run_streamed", side_effect=mock_runner):
                await run_command("./agent")

        # check that a trace was written under /var/trajectories/
        all_files = ctx.fs().list(prefix="var/trajectories")
        trace_files = [f for f in all_files if not f.endswith(".out")]
        assert len(trace_files) >= 1

        # trace should contain the program name and response
        trace_content = ctx.fs().read(trace_files[0]).decode("utf-8")
        assert "agent" in trace_content
        assert ".COMPLETED" in trace_content


async def test_program_with_system_prompt(temp_db):
    """A .PROMPT program with .SYSTEM_PROMPT should pass it to the agent."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.mount("tools", ToolsFolderProvider(ctx))
        vault = ctx.fs()

        vault.write("etc/model/default", b"echo echo")
        vault.write("bot", b".SYSTEM_PROMPT\nYou are a pirate.\n.PROMPT\nSay ahoy\n")

        captured_agent = {}

        events = _make_stream_events("Ahoy matey!")
        def capturing_runner(*a, **kw):
            # The first positional arg to Runner.run_streamed is the agent
            if a:
                captured_agent["instructions"] = a[0].instructions
            return _mock_run_streamed(events)

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("agents.Runner.run_streamed", side_effect=capturing_runner):
                await run_command("./bot")

        assert "You are a pirate." in captured_agent.get("instructions", "")


async def test_program_chain_with_builtin(temp_db):
    """A program can be chained with && and builtins."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.mount("tools", ToolsFolderProvider(ctx))
        vault = ctx.fs()

        vault.write("etc/model/default", b"echo echo")
        vault.write("greet", b".PROMPT\nGreet\n")

        events = _make_stream_events("Hi!")
        mock_runner = lambda *a, **kw: _mock_run_streamed(events)

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("agents.Runner.run_streamed", side_effect=mock_runner):
                await run_command("echo before && ./greet")

        result = output.getvalue()
        assert "before" in result
        assert "Hi!" in result
