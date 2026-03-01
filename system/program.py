import asyncio
import json
import signal
import sys
import uuid
from dataclasses import dataclass
from fs.providers import ModelProvider
from system.context import SystemContext, cprint
from system.tools import make_ash_tool, generate_agents_md
from termcolor import colored

from agents import Runner, Agent, RawResponsesStreamEvent, RunItemStreamEvent, function_tool, ModelSettings
from system.terminal_markdown import TerminalMarkdown

@dataclass
class Program:
    # paths to tools available
    tools: list[callable]

    # tool paths (always ["/tools/ash"])
    tool_paths: list[str]

    # whether this is an interactive program that keeps prompting after a turn completes
    is_interactive: bool

    # input prompt
    prompt: str

    # system prompt, if not default
    system_prompt: str | None = None

    # maximum number of turns for the agent to run, default is 10
    max_turns: int = 10

def parse(contents: str):
    """
    A program looks like this

    ```
    [.SYSTEM_PROMPT
    <optional system prompt, if not present the default system prompt will be used>]
    .PROMPT
    <system prompt>
    ```
    [...] is optional.
    """
    lines = contents.splitlines()
    system_prompt = None
    prompt_lines = []
    section = None
    is_interactive = False

    max_turns = safe_int(SystemContext.current().read("/etc/model/max_turns", "10"), default=10)

    assert ".PROMPT" in lines, "Program must contain a .PROMPT section"

    for line in lines:
        if line == ".SYSTEM_PROMPT":
            section = "system_prompt"
            continue
        elif line == ".PROMPT":
            section = "prompt"
            continue
        elif line == ".TOOLS":
            # .TOOLS section is no longer used; silently skip
            section = "tools"
            continue
        elif line == ".INTERACTIVE":
            is_interactive = True
            continue
        elif line.startswith(".INCLUDE"):
            include_path = line[len(".INCLUDE"):].strip()
            try:
                include_contents = SystemContext.current().fs().read(include_path).decode()
                line = include_contents.strip()
            except Exception as e:
                raise ValueError(f"Failed to include file '{include_path}' in program: {str(e)}")
        elif line.startswith(".MAX_TURNS"):
            max_turns = safe_int(line[len(".MAX_TURNS"):].strip(), default=10)
            continue

        if section == "system_prompt":
            system_prompt = (system_prompt or "") + line + "\n"
        elif section == "prompt":
            prompt_lines.append(line)
        # .TOOLS lines are silently ignored

    # All programs get the ash tool as the sole native tool,
    # with a dynamic docstring that includes vault user-defined commands
    tools = [make_ash_tool(SystemContext.current().fs())]
    tool_paths = ["/tools/ash"]

    prompt = "\n".join(prompt_lines).strip()
    return Program(tools=tools, tool_paths=tool_paths, system_prompt=system_prompt, prompt=prompt, max_turns=max_turns or 10, is_interactive=is_interactive)

def safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except ValueError:
        return default

async def run(program: Program, filepath: str, *args):
    models = ModelProvider()
    
    context = SystemContext.current()

    # get model configuration
    model_configuration = context.read("/etc/model/default", "openai gpt-5-mini")
    reasoning_effort = context.read("/etc/model/reasoning_effort", "low")
    
    # get system prompt, if not provided use default
    system_prompt = program.system_prompt or context.read("/AGENTS.md", "You are a helpful assistant.")
    system_prompt += "\n\n" + generate_agents_md(context.fs())
    
    # parse model configuration
    try:
        provider, model = model_configuration.split()
    except ValueError:
        provider, model = "openai", "gpt-5-mini"

    # if model is 'auto', use the first available model from the provider
    if model == "auto":
        for m in models.list():
            if m.startswith(provider + "/"):
                model = m[len(provider) + 1:]
                break
    if model == "auto":
        raise ValueError(f"No available models found for provider '{provider}' in /models/, but 'auto' was specified. Please make sure there is at least one model available for this provider in /models/ or specify a model explicitly in /etc/model/default")

    # ensure model and provider are available
    assert models.has_provider(provider), f"{provider} provider is not available. Please make sure /etc/model/default points to a model that is currently available (/models/<provider>/<model>)"
    assert models.has_model(provider, model), f"{model} model from {provider} provider is not available. Currently available models are {models.list()}. You may need to update your /etc/model/default to point to an available model."

    # construct the agent
    agent = Agent(name=filepath, instructions=system_prompt, tools=[function_tool(t) for t in program.tools], model=model, model_settings=ModelSettings(reasoning={"effort": reasoning_effort}))

    # actually run the agent
    await run_streamed_spinner(context, agent, program, filepath, f"{provider} {model}", *args)


async def run_streamed_spinner(context: SystemContext, agent: Agent, program: Program, filepath: str, model_configuration: str, *args):
    # parse --session <id> flag
    from system.session import VaultJSONSession
    session_id = None
    
    # prepare arguments
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1
    args = tuple(filtered_args)

    # prepare session
    is_new_session = False
    if session_id is None:
        session_id = str(uuid.uuid4())[:8]
        is_new_session = True
    session = VaultJSONSession(session_id, context)
    
    # spinner setup
    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    spinner_task = None

    async def spin(msg=""):
        """Show a spinner on stderr until cancelled."""
        i = 0
        try:
            while True:
                context.stderr.write(f"\r{spinner_chars[i % len(spinner_chars)]} {msg}")
                context.stderr.flush()
                i += 1
                await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            context.stderr.write("\r\033[K")
            context.stderr.flush()

    async def stop_spinner():
        nonlocal spinner_task
        if spinner_task and not spinner_task.done():
            spinner_task.cancel()
            try:
                await spinner_task
            except asyncio.CancelledError:
                pass
        spinner_task = None

    def start_spinner(msg=""):
        nonlocal spinner_task
        if context.interactive:
            spinner_task = asyncio.create_task(spin(msg))

    # output setup
    def print_output(text="", end="\n", flush=False, file=None):
        if file is None:
            file = context.stdout
        # suppress stderr chrome (spinner, tool calls, session) when not interactive
        if not context.interactive and file is context.stderr:
            return
        cprint(text, end=end, flush=flush, file=file)

    # trace file setup
    call_id = str(uuid.uuid4())
    trace_path = f"/var/trajectories/{call_id}"

    try:
        # register in /proc
        context.register_agent(call_id, filepath, trace_path)

        def trace_write(content: str):
            context.fs().write(trace_path, content.encode(), mode="a")

        async def agent_task():
            trace_content = ""
            total_input = 0
            total_output = 0
            try:
                # construct full prompt input
                args_input = "" if len(args) == 0 else "\n\nThe user has now entered the following:\n" + " ".join(args)
                prompt = "Working Directory: " + context.cwd + "\n\n"
                
                # depending on whether this is a new session, we re-include the original program prompt or not
                if is_new_session:
                    prompt += program.prompt + args_input
                else:
                    prompt += args_input

                # write trace header immediately
                trace_content = filepath + "\n"
                trace_content += ".MODEL " + model_configuration + "\n"
                trace_content += ".SESSION " + session_id + "\n"
                trace_content += ".SYSTEM_PROMPT\n" + (agent.instructions or "") + "\n"
                trace_content += ".PROMPT\n" + prompt + "\n"
                if program.tool_paths:
                    trace_content += ".TOOLS\n" + "\n".join(program.tool_paths) + "\n"
                trace_content += ".RESPONSE\n"
                trace_write(trace_content)

                while True:
                    # Check cost limit before each turn
                    if context.cost_limit is not None:
                        from bin.usage import collect_usage
                        from datetime import timedelta
                        stats = collect_usage(context.fs(), timedelta(hours=24))
                        used = stats["cost"]
                        if used >= context.cost_limit:
                            await stop_spinner()
                            print_output(
                                f"Cost limit of ${context.cost_limit:.4f}/24h exceeded "
                                f"(${used:.4f} used). Blocking execution.",
                                file=context.stderr,
                            )
                            break

                    result = Runner.run_streamed(agent, prompt, max_turns=program.max_turns, session=session)

                    start_spinner()
                    streaming_text = False
                    tool_names = {}  # item_id -> tool name
                    md = TerminalMarkdown(lambda t: print_output(t, end="", flush=True))

                    async for event in result.stream_events():
                        # Handle tool output from RunItemStreamEvent
                        if isinstance(event, RunItemStreamEvent):
                            if event.name == "tool_output":
                                await stop_spinner()
                                raw_item = event.item.raw_item
                                full_output = raw_item.get("output", "") if isinstance(raw_item, dict) else str(event.item.output)
                                full_output = str(full_output)
                                # trace: full output
                                call_id_ref = raw_item.get("call_id", "") if isinstance(raw_item, dict) else ""
                                trace_content += json.dumps({"type": "tool_output", "call_id": call_id_ref, "output": full_output}) + "\n"
                                trace_write(trace_content)
                                # display: truncated
                                display = (full_output if len(full_output) <= 200 else full_output[:200]).replace("\n", "⏎ ") + "..."
                                print_output(colored(f"  -> {display}", 'dark_grey'), file=context.stderr)
                                start_spinner()
                            continue

                        if not isinstance(event, RawResponsesStreamEvent):
                            continue

                        raw = event.data
                        event_type = getattr(raw, "type", None)

                        if event_type == "response.output_text.delta":
                            if not streaming_text:
                                streaming_text = True
                                await stop_spinner()
                                print_output()  # newline before text response
                            md.feed(raw.delta)

                        elif event_type == "response.output_item.added":
                            # track tool name from the function call item
                            item = getattr(raw, "item", None)
                            if item and getattr(item, "type", None) == "function_call":
                                tool_names[item.id] = item.name

                        elif event_type == "response.function_call_arguments.done":
                            await stop_spinner()
                            name = raw.name or tool_names.get(raw.item_id, "?")
                            args_display = raw.arguments if len(raw.arguments) <= 200 else raw.arguments[:200] + "..."
                            print_output(colored(f"[{name}", 'dark_grey', attrs=['bold']) + colored(f"({args_display})]", 'dark_grey'), file=context.stderr)
                            # trace: tool call
                            trace_content += json.dumps({"type": "tool_call", "name": name, "arguments": raw.arguments}) + "\n"
                            trace_write(trace_content)
                            start_spinner()

                        elif event_type == "response.output_text.done":
                            # trace: full message text
                            trace_content += json.dumps({"type": "message", "text": raw.text}) + "\n"
                            trace_write(trace_content)

                        elif event_type == "response.output_item.done":
                            item = getattr(raw, "item", None)
                            if item and getattr(item, "type", None) == "reasoning":
                                summary = getattr(item, "summary", [])
                                trace_content += json.dumps({"type": "reasoning", "summary": summary}) + "\n"
                                trace_write(trace_content)

                        elif event_type == "response.completed":
                            usage = getattr(raw.response, "usage", None)
                            if usage:
                                total_input += usage.input_tokens
                                total_output += usage.output_tokens
                                trace_content += json.dumps({"type": "usage", "input_tokens": total_input, "output_tokens": total_output}) + "\n"
                                trace_write(trace_content)

                        elif event_type == "response.created" and streaming_text:
                            # new response cycle after text — agent is doing another turn
                            md.end()
                            streaming_text = False
                            print_output()  # newline after previous text
                            start_spinner()

                    await stop_spinner()
                    md.end()
                    print_output()  # newline after turn

                    # if not interactive, don't prompt for more input and just exit after one run
                    if not program.is_interactive or not context.interactive:
                        break

                    # prompt for next user input
                    print_output("\n! ", end="", flush=True)
                    loop = asyncio.get_running_loop()
                    try:
                        line = await loop.run_in_executor(None, sys.stdin.readline)
                    except asyncio.CancelledError:
                        break
                    line = line.rstrip("\n")
                    if not line:
                        break

                    prompt = line
                    if prompt.strip() == "exit":
                        break
                    trace_content += json.dumps({"type": "user_input", "text": prompt}) + "\n"
                    trace_write(trace_content)

                print_output(colored(f"\nsession: {session_id}", "dark_grey"), file=context.stderr)
            except Exception as e:
                await stop_spinner()
                trace_content += ".ERROR\n" + str(e) + "\n"
                trace_write(trace_content)
                print_output(f"Error running program {filepath}: {str(e)}")
            finally:
                # log final usage and completion marker
                trace_content += ".USAGE\n"
                trace_content += json.dumps({"input_tokens": total_input, "output_tokens": total_output}) + "\n"
                trace_content += ".COMPLETED\n"
                trace_write(trace_content)
                # unregister from /proc
                context.unregister_agent(call_id)
        
        # create separate task for agent execution
        task = asyncio.create_task(agent_task())

        # install SIGINT handler to cancel the running task on ctrl-c
        loop = asyncio.get_running_loop()
        cancelled_by_user = False

        def on_sigint():
            nonlocal cancelled_by_user
            cancelled_by_user = True
            task.cancel()

        loop.add_signal_handler(signal.SIGINT, on_sigint)
        try:
            await task
        except asyncio.CancelledError:
            await stop_spinner()
            if cancelled_by_user:
                print_output("\nInterrupted.", file=context.stderr)
                print_output(colored(f"session: {session_id}", "dark_grey"), file=context.stderr)
            context.unregister_agent(call_id)
        finally:
            loop.remove_signal_handler(signal.SIGINT)
    except Exception as e:
        # make sure to unregister from /proc in case of any setup errors
        context.unregister_agent(call_id)
        # re-raise the exception to be handled by the caller
        raise e
