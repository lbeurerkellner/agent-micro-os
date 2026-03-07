# Writing Agent Programs

Overview of how to write agent programs (in /bin/) which are text files with directives that define an LLM agent (the primary way to create reusable, executable AI workflows, e.g. for cron jobs)

## Minimal Example

```
.PROMPT
Greet the user in a silly way
```

Save this as `bin/greet`, then run it:

```
(/) > greet
Ahoy-hoy, space pickle! 🥒✨
```

## Directives Reference

Directives are lines that start with a dot (`.`) and configure how the program runs. They must appear before `.PROMPT` (except `.INTERACTIVE`, which can appear anywhere).

| Directive | Required | Description |
|-----------|----------|-------------|
| `.PROMPT` | Yes | Everything after this line is the agent's instructions. |
| `.SYSTEM_PROMPT` | No | Custom system prompt (lines until the next directive). |
| `.INCLUDE <path>` | No | Inline another file's contents at that position. |
| `.MAX_TURNS <n>` | No | Maximum agent turns (default: 10). Ignored for claude engine. |
| `.INTERACTIVE` | No | The program runs in the foreground with the user paying attention and being able to follow up. If not specified the agent runs headless, with a single prompt to action turn (no user feedback). |
| `.ENGINE native\|claude` | No | Execution engine (default: `native`). |
| `.BUDGET <amount>` | No | Spending limit in USD for the run. |
| `.ACCESS <glob>` | No | File access rule (see [Access Control](#access-control)). |

## Execution Engines

### Native (default)

Uses the OpenAI Agents SDK. The agent interacts with the vault directly through the `ash` tool — all built-in commands (`ls`, `cat`, `edit`, `grep`, etc.) and user-defined tools are available.

```
.PROMPT
Summarize the contents of /data
```

### Claude

Uses the Claude Code CLI running inside a sandboxed Docker container. The vault is mounted at `/workspace` and changes are diffed and committed back atomically when the session ends.

```
.ENGINE claude --model sonnet
.BUDGET 0.50
.PROMPT
Refactor the code in src/ for readability.
```

Extra flags after `claude` are forwarded to the CLI (e.g. `--model sonnet`).

## Access Control

The `.ACCESS` directive restricts which files the agent can see and write to. This is enforced at the sandbox boundary (claude engine and tool scripts).

### Syntax

```
.ACCESS <glob>        # read-write access
.ACCESS <glob>:ro     # read-only access
```

A glob without a suffix grants **read-write** access. Appending `:ro` grants **read-only** access. Standard glob patterns are supported (`*`, `**`, `?`).

### How It Works

When `.ACCESS` is present:

1. **Export**: Only files matching an access glob (rw or ro) are copied into the sandbox. The agent literally cannot see files outside its access scope.
2. **Commit-back**: When the session ends, all changes are validated against the access rules. Every modified, added, or deleted file must match a read-write glob. If any change falls outside the allowed write locations, the **entire transaction is rejected** and all changes are discarded.

The all-or-nothing rejection is intentional — partially committing an agent's output could leave the vault in an inconsistent state.

When no `.ACCESS` directives are present, the agent has unrestricted access (the default behavior).

### Examples

**Only allow writes to a specific directory:**

```
.ACCESS src/**
.ACCESS lib/**:ro
.ENGINE claude
.PROMPT
Fix the bug described in the issue. You can read lib/ for context but only modify src/.
```

**Scope to files passed as arguments with `$@`:**

```
.ACCESS $@
.ACCESS tests/**
.ENGINE claude
.PROMPT
Fix the provided files and update their tests.
```

When invoked as `./fix src/app.py src/utils.py`, the agent gets read-write access to `src/app.py`, `src/utils.py`, and `tests/**`. The `$@` token expands to all positional arguments that resolve to existing vault paths (flags starting with `-` and non-existent paths are skipped).

**Read-only args with extra write targets:**

```
.ACCESS $@:ro
.ACCESS reports/**
.ENGINE claude
.PROMPT
Analyze the provided files and write a report to reports/.
```

### Commit Messages

When access control is active, the agent is instructed to write a commit message to `/workspace/COMMIT_MSG` before finishing. This message is used as the vault commit message and the file itself is not committed to the vault. If no commit message is provided, a default summary is used.

The `COMMIT_MSG` mechanism also works without `.ACCESS` — any sandbox session can write to it to provide a meaningful commit message.

## Including Files

Use `.INCLUDE` to inline the contents of another vault file:

```
.SYSTEM_PROMPT
You are a code reviewer.
.INCLUDE /agent/review-guidelines.md
.PROMPT
Review the latest changes.
```

The included file's contents replace the `.INCLUDE` line in whichever section it appears (system prompt or prompt).

## Interactive Programs

Add `.INTERACTIVE` to create a conversational agent that keeps prompting for input:

```
.PROMPT
You are a helpful assistant.
.INCLUDE /agent/BRAIN.md
.MAX_TURNS 100
.INTERACTIVE
```

The agent responds, then shows a `!` prompt for the next user message. Type `exit` or press Enter on an empty line to quit. Sessions are preserved and can be resumed with `--session <id>`.

## Sessions

Native engine programs support persistent sessions. Each run generates a session ID (shown at the end). Resume a session:

```
(/) > greet --session abc12345
```

The agent continues with its full conversation history from the previous run.

## Where to Put Programs

- **`/bin/<name>`** — callable by name from the shell (on the system PATH)
- **Anywhere else** — run with `./path/to/program` or an absolute path

## Complete Example

A scoped coding agent that can only modify `src/` and read `docs/` for context:

```
.ENGINE claude --model sonnet
.BUDGET 1.00
.ACCESS src/**
.ACCESS docs/**:ro
.SYSTEM_PROMPT
You are a senior developer. Follow the project's coding conventions.
.PROMPT
Implement the feature described below. Read docs/ for architectural context.
Only modify files under src/. Write your commit message to /workspace/COMMIT_MSG.
.INCLUDE /agent/current-task.md
```
