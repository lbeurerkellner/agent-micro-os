# Agent Micro OS

Toy implementation of a micro operating system in which programs are prompts, agents are processes, and the filesystem layer is versioned into a database for time travel and recovery.

Start by executing the following command.
```python
uv run bin/ash.py --user bob --fsimage data.db
```

You can then investigate the file system:

```
(/) > ls .
etc/     # - configuration files, AGENTS.md
models/  # - available models mounted as /models/<provider>/<model>; set OPENAI_API_KEY to get gpt-5-mini mounted
sbin/    # - built-in system command, implemented in bin/ (ls, cat, etc.)
tools/   # - tools available to agents, implemented in system/tools.py
```

To create your first agent (program), run the following command:

```
edit bin/greet
```

Paste the following content into the editor:

```
.PROMPT
Greet the user in a silly way
.TOOLS
/tools/list_directory
/tools/read
```

You can then run your program with the following command:

```
(/) > greet
Ahoy-hoy, space pickle! 🥒✨ How’s your brainbox buzzing today?
```

If you want to learn more about the OS, use the 'man' command to learn about built-in commands and explore `/sbin`. Use 'top' to observe currently active agents, use 'usage' to see how many agents have run, and how many tokens they have used in the last 24h.