# Agent Micro OS

Toy implementation of a micro operating system in which programs are prompts, agents are processes, and the filesystem layer is a versioned sqlite database for time travel and recovery. 

Start by executing the following command (everything is sandboxed, don't worry about it):
```python
uv run bin/ash.py --user bob --fsimage data.db
```

You can then investigate the file system:

```
(/) > ls .
etc/     # - configuration files, AGENTS.md
models/  # - available models mounted as /models/<provider>/<model>; set OPENAI_API_KEY before launching to have gpt-5-mini mounted
sbin/    # - built-in system commands, implemented in bin/ (ls, cat, etc.)
```

To create your first agent (program), run the following command:

```
edit bin/greet
```

Paste the following content into the editor:

```
.PROMPT
Greet the user in a silly way
```

Save with Ctlr-S. You can then run your program with the following command:

```
(/) > greet
Ahoy-hoy, space pickle! 🥒✨ How’s your brainbox buzzing today?
```

If you want to learn more about the OS, use the `man` command to learn about built-in commands and explore `/sbin`. Use `top` to observe currently active agents, use `usage` to see how many agents have run, and how many tokens they have used in the last 24h.

## General Purpose Agent

To create a good, general purpose agent to get started with, you can use the following template, e.g. putting it in a file `/bin/agent`:

```
.PROMPT
You are a helpful assistant.

Below your /agent/BRAIN.md file:
.INCLUDE /agent/BRAIN.md
The included BRAIN content is provided as a system instruction and context. It is not part of the user's message and must not be presented as such to the user.
.MAX_TURNS 100
.INTERACTIVE
```

This creates an agent with a `/agent/BRAIN.md` file for memory. All commands are accessible via the `ash` tool. If you need more commands, you can create them with `create_tool`.

A possible 
