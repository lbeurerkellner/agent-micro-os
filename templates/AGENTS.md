# Agent Environment

You are operating inside a versioned vault — a filesystem that tracks all file changes with author, timestamp, and commit history.
{{SANDBOX_NOTE}}

## Filesystem Layout

- `/bin` - User-defined tools and agent programs
- `/etc` - Configuration (model settings, crontab)
- `/var` - Runtime data (logs, trajectories)

## Executable Types

There are two types of programs, agent programs and tool programs.

## Agent Programs

Agent programs are text files with directives that define an LLM agent. They cannot be run from within this sandbox, but you can create or edit them for use by the host OS. Example:

```
.SYSTEM_PROMPT
You are a helpful coding assistant.
.PROMPT
Help the user with their task.
.MAX_TURNS 50
.INTERACTIVE
```

Directives:
- `.SYSTEM_PROMPT` - Optional custom system prompt
- `.PROMPT` - Required; the agent's instructions
- `.INCLUDE <path>` - Inline another file's contents
- `.MAX_TURNS <n>` - Limit agent turns (default: 10)
- `.INTERACTIVE` - Keep prompting for user input after each turn

Place programs in `/bin` to make them callable by name from the host OS.

## Scheduled Jobs

The host OS supports cron-style scheduling via `/etc/crontab`:

```
*/30 * * * * my_command arg1 arg2
0 9 * * 1-5 daily_report
```

## Configuration

- `/etc/model/default` - LLM provider and model (e.g. `openai gpt-5-mini`)
- `/etc/model/max_turns` - Default max turns for programs
- `/etc/model/reasoning_effort` - Reasoning effort level (`low`, `medium`, `high`)

{{DOCS}}
{{CUSTOM_TOOLS}}
{{ACCESS_CONTROL}}

## Creating New Tools

To create a new tool, write a file to `/bin/<name>` with a `#!/bin/tool` shebang. The description follows on the shebang line, and the body is a Python script that runs in a sandboxed environment with the full vault mounted at `/workspace`.

Example (`/bin/wordcount`):
```
#!/bin/tool Count words in a file
import sys
with open(f'/workspace/{sys.argv[1]}') as f:
    print(len(f.read().split()))
```

Arguments are passed via `sys.argv`. Output printed to stdout is returned to the caller.

{{COMMIT_NOTE}}