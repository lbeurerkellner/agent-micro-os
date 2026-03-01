"""Test program execution (.PROMPT files) with mocked LLM runner."""

import io
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from system.context import SystemContext
from fs.providers import BinProvider
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


async def test_program_with_system_prompt_ignored(temp_db):
    """A .SYSTEM_PROMPT section should be silently ignored (deprecated)."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())

        vault = ctx.fs()

        vault.write("etc/model/default", b"echo echo")
        vault.write("bot", b".SYSTEM_PROMPT\nYou are a pirate.\n.PROMPT\nSay ahoy\n")

        captured_agent = {}

        events = _make_stream_events("Ahoy matey!")
        def capturing_runner(*a, **kw):
            if a:
                captured_agent["instructions"] = a[0].instructions
            return _mock_run_streamed(events)

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("agents.Runner.run_streamed", side_effect=capturing_runner):
                await run_command("./bot")

        # .SYSTEM_PROMPT content is still passed through for backwards compat
        # but the directive itself is deprecated
        assert "Ahoy matey!" in output.getvalue()


async def test_program_engine_native_default(temp_db):
    """Programs default to engine=native."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("prog", b".PROMPT\nDo something\n")

        from system.program import parse
        contents = vault.read("prog").decode()
        program = parse(contents)
        assert program.engine == "native"
        assert program.budget is None


async def test_program_engine_claude(temp_db):
    """Programs with .ENGINE claude should set engine='claude'."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("prog", b".ENGINE claude\n.PROMPT\nDo something\n")

        from system.program import parse
        contents = vault.read("prog").decode()
        program = parse(contents)
        assert program.engine == "claude"


async def test_program_budget_parsed(temp_db):
    """Programs with .BUDGET should parse the dollar value."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("prog", b".BUDGET 1.50\n.PROMPT\nDo something\n")

        from system.program import parse
        contents = vault.read("prog").decode()
        program = parse(contents)
        assert program.budget == 1.50
        assert program.engine == "native"


async def test_program_engine_claude_with_flags(temp_db):
    """Extra flags after 'claude' in .ENGINE should be parsed."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("prog", b".ENGINE claude --model sonnet\n.PROMPT\nDo something\n")

        from system.program import parse
        contents = vault.read("prog").decode()
        program = parse(contents)
        assert program.engine == "claude"
        assert program.engine_flags == ["--model", "sonnet"]


async def test_program_invalid_engine_raises(temp_db):
    """An unknown .ENGINE value should raise ValueError."""
    import pytest
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("prog", b".ENGINE unknown\n.PROMPT\nDo something\n")

        from system.program import parse
        contents = vault.read("prog").decode()
        with pytest.raises(ValueError, match="Unknown engine"):
            parse(contents)


async def test_program_invalid_budget_raises(temp_db):
    """An invalid .BUDGET value should raise ValueError."""
    import pytest
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("prog", b".BUDGET notanumber\n.PROMPT\nDo something\n")

        from system.program import parse
        contents = vault.read("prog").decode()
        with pytest.raises(ValueError, match="Invalid .BUDGET"):
            parse(contents)


async def test_program_claude_engine_calls_claude(temp_db):
    """A .ENGINE claude program should call the claude CLI, not the native runner."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()
        vault.write("etc/model/default", b"echo echo")
        vault.write("bot", b".ENGINE claude\n.BUDGET 2.00\n.PROMPT\nDo something\n")

        captured_args = {}

        async def mock_claude_run(*args, **kwargs):
            captured_args["args"] = args
            captured_args["kwargs"] = kwargs

        output = io.StringIO()
        with ctx.child(stdout=output, interactive=False):
            with patch("system.program.run_claude", side_effect=mock_claude_run) as mock:
                await run_command("./bot")

        mock.assert_called_once()
        call_args = mock.call_args
        # program should have engine=claude and budget=2.0
        program_arg = call_args[0][1]  # second positional arg is program
        assert program_arg.engine == "claude"
        assert program_arg.budget == 2.00


async def test_program_chain_with_builtin(temp_db):
    """A program can be chained with && and builtins."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())

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
