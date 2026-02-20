# AgentVault Internals

You are an AI agent running inside AgentVault — a micro operating system for agents. This document explains how the system you inhabit works.

## Filesystem Layout

```
/sbin/      Read-only built-in commands (ls, cat, grep, find, cp, mv, rm, write, edit, top, watch, sandbox, ...)
/tools/     Read-only callable tools (read, write, list_directory, grep, sleep, ash, create_tool, ...)
/models/    Read-only available LLM models (e.g. openai/gpt-4o-mini, echo/echo)
/proc/      Read-only running agent processes (one file per agent, named by UUID)
/bin/       Writable — agent programs and custom tools live here
/etc/       Writable — system configuration
/var/       Writable — runtime data (trajectories, logs)
/tmp/       Writable — temporary files
```

Everything under `/sbin`, `/tools`, `/models`, `/proc` is a virtual read-only mount. Everything else is stored in a versioned SQLite-backed vault (full history, diffs, time-travel).

## Tools

Tools are the primary way you interact with the system. They are Python functions you can call. Available tools are listed in `/tools/`. Built-in tools:

- `read(filepath)` — read a file
- `write(filepath, content)` — write a file
- `list_directory(path)` — list directory contents
- `grep(pattern, path, ...)` — search files
- `sleep(seconds)` — wait
- `ash(command)` — run any shell command from `/sbin`
- `create_tool(name, description, implementation)` — define a new tool

The `ash` tool lets you chain shell commands: `ash("ls / && cat /etc/AGENTS.md")`.

## Agent Programs

Programs (agent definitions) are plain text files, typically stored in `/bin/`. Format:

```
.SYSTEM_PROMPT
Optional custom system prompt.

.PROMPT
The task or instructions for the agent. Required.

.TOOLS
/tools/read
/tools/write
/tools/*        <- wildcard: all available tools

.MAX_TURNS
10
```

Running a program (`greet hello`) spawns a new agent. The agent gets the program content as its prompt, executes tool calls in a loop, and terminates when done or after max turns.

## Configuration

- `/etc/model/default` — model to use, e.g. `openai gpt-4o-mini`
- `/etc/model/reasoning_effort` — `low` or `high`
- `/etc/model/max_turns` — default iteration limit
- `/etc/AGENTS.md` — default system prompt injected into every agent

## Processes

Each running agent is registered in `/proc/<UUID>` while alive. Use `top` to watch live agents. Append `&` to a command to run it in the background; output goes to `/var/trajectories/<UUID>.out`.

## Execution Traces

Every agent run produces a trajectory at `/var/trajectories/<UUID>` containing the full model, prompt, tool calls, outputs, and token usage. Inspect with `cat /var/trajectories/<UUID>`.

## Custom Tools

Any file in `/bin/` that contains a `.DESCRIPTION` section is treated as a custom tool and immediately appears in `/tools/`. Files without `.DESCRIPTION` (e.g. plain agent programs with only `.PROMPT`) are not exposed as tools.

**Tool file format:**

```
.DESCRIPTION
What this tool does and how to call it.

.IMPL
# Python code — runs in a Docker sandbox (python:3.12 image)
# /workspace contains a full snapshot of the vault at the time of the call
# Arguments are passed via sys.argv
import sys
filepath = sys.argv[1]
with open(f"/workspace/{filepath}") as f:
    print(f.read())
```

### How the sandbox executes tools

When a custom tool is called, the following happens:

1. **Snapshot export** — the entire vault is exported as a tar archive into a fresh Docker volume. This is the state of the file system at call time.
2. **Container launch** — a `python:3.12` container starts with the volume mounted at `/workspace`. The tool's `.IMPL` code is written to `/workspace/tmp/tool_<id>.py` and executed with `python`.
3. **Execution** — the tool runs with full read/write access to `/workspace`. It can read any file from the vault and create, modify, or delete files.
4. **Diff and commit** — after the container exits, the volume is re-read and compared against the original snapshot (added, modified, removed files are detected). Only the changed files are written back to the vault in a single atomic commit.
5. **Captured output** — stdout/stderr from the container is returned as the tool's result string.

The key implication: **tools can have file system side effects**. If a tool writes a file to `/workspace/bin/result.txt`, that file appears in the vault after the call. If it deletes a file, it's gone from the vault. Unchanged files are never re-written.

**Creating a tool with `create_tool`:**

```
create_tool(
    name="wordcount",
    description="Counts words in a file. Usage: wordcount <filepath>",
    implementation="import sys\nwith open(f'/workspace/{sys.argv[1]}') as f:\n    print(len(f.read().split()))"
)
```

This writes the file to `/bin/wordcount` and the tool becomes available at `/tools/wordcount`. If `/bin/wordcount` already exists, creation fails — use `write` or `edit` to update it instead.

**Updating an existing tool:** Edit `/bin/<name>` directly with `write` or `edit`. Changes take effect immediately on the next call.

**Which tools are editable:**
- Custom tools in `/bin/` (`.DESCRIPTION` + `.IMPL`) — fully editable, stored in the vault
- Built-in tools in `/tools/` (e.g. `read`, `write`, `ash`, `grep`) — read-only, implemented in system Python code, cannot be changed

To see the signature and description of any tool: `cat /tools/<name>`.

## Key Facts

- All file paths use `/`-prefixed absolute paths or relative paths from cwd.
- `cd` changes your working directory; relative paths resolve from it.
- The vault is versioned: every write is tracked with author, timestamp, and hash.
- Programs and tools are composable: agents can spawn agents, create tools, and modify the system.
