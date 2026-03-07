# Agent Micro OS

A virtual operating system for agents. Programs are prompts, agents are processes, and the filesystem is a versioned database for time travel and recovery. Supports OpenAI Agents SDK and Claude Code as execution engines, sandboxed tool execution via Docker, and a live process dashboard.

## Getting Started

To get started, launch a new shell session inside the virtual OS (everything is sandboxed; each user ID has its own machine state).
```
uv run bin/ash.py --user bob --fsimage data.db
```

Useful CLI flags:

| Flag | Description |
|------|-------------|
| `--limit USD` | Maximum spend in USD per 24 h window (default: $1.00). Blocks program turns when exceeded. |
| `--crond` | Start the cron daemon in the background (runs scheduled jobs from `/etc/crontab`). |

Explore the filesystem:

```
(/) > ls .
etc/     # configuration files
bin/     # user-defined tools and agent programs
var/     # runtime data (logs, trajectories)
sbin/    # built-in system commands (ls, cat, grep, etc.)
```

Set `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` before launching to enable the respective agent types. You can also rely on Claude Code's built-in OAuth Sign In for authentication (just run `claude` and go through the standard flow).

## Creating an Agent Program

Create a simple agent:

```
(/) > edit bin/greet
```

Paste the following content into the editor and save with Ctrl-S:

```
.PROMPT
Greet the user in a silly way
```

Then run it:

```
(/) > greet
Ahoy-hoy, space pickle! 🥒✨ How's your brainbox buzzing today?
```

### Program Directives

Agent programs are text files with directives that define LLM agent behavior:

| Directive | Description |
|-----------|-------------|
| `.PROMPT` | Required. The agent's instructions. |
| `.INCLUDE <path>` | Inline another file's contents. |
| `.MAX_TURNS <n>` | Limit agent turns (default: 10). |
| `.INTERACTIVE` | Keep prompting for user input after each response. |
| `.ENGINE native\|claude` | Execution engine — `native` (OpenAI agent SDK) or `claude` (Claude Code CLI). |
| `.BUDGET <amount>` | Spending limit in USD for the program run. |

### Execution Engines

Programs run on the `native` engine (OpenAI agent SDK) by default. To use Claude instead:

```
.ENGINE claude --model sonnet
.BUDGET 0.50
.PROMPT
You are a helpful coding assistant.
.INTERACTIVE
```

Claude programs execute inside a sandboxed Docker container with the vault mounted at `/workspace`. Changes are automatically committed back.

## Custom Tools

Create tools as scripts in `/bin` with a `#!/bin/tool` shebang. The description follows on the shebang line, and the body is a Python script that runs in a sandboxed Docker container with the vault mounted at `/workspace`.

```
#!/bin/tool Count words in a file
import sys
with open(f'/workspace/{sys.argv[1]}') as f:
    print(len(f.read().split()))
```

Save as `/bin/wordcount`, then use it from any agent via `ash wordcount myfile.txt`. Custom tools are automatically discovered and documented in agent system prompts.

## Monitoring

- **`top`** — Live interactive dashboard showing all active and recent agent sessions (both native and Claude). Navigate with arrow keys, press Enter to follow up on a session. Displays token usage, cost tracking, and per-model breakdowns.
- **`usage`** — Token and cost summary for the last 24 hours.
- **`help <command>`** — Built-in help for any command.

## General Purpose Agent

A template for a capable interactive agent with persistent memory:

```
.PROMPT
You are a helpful assistant.

Below your /agent/BRAIN.md file:
.INCLUDE /agent/BRAIN.md
The included BRAIN content is provided as a system instruction and context. It is not part of the user's message and must not be presented as such to the user.
.MAX_TURNS 100
.INTERACTIVE
```

This creates an agent with a `/agent/BRAIN.md` file for memory. All commands are accessible via `ash`.

## Scheduled Jobs

Cron-style scheduling via `/etc/crontab`:

```
*/30 * * * * my_command arg1 arg2
0 9 * * 1-5 daily_report
```

Start the cron daemon automatically by passing `--crond` to `ash`.

## Web UI

A read-only FastAPI web interface for browsing the vault from a browser:

```
uv run bin/web.py --fsimage data.db --passwd passwd.txt
```

The `passwd.txt` file contains one `user:bcrypt_hash` entry per line. The UI exposes:

- **`/browse/`** — navigate the vault filesystem
- **`/notes/`** — view Markdown files as rendered pages

## Deployment

A `docker-compose.yml` and `Makefile` are included for server deployment.

```bash
# Deploy to a remote host (requires DEPLOY_HOST and DEPLOY_PATH in .env)
make deploy
```

The compose stack runs the web UI on port 8000 and is pre-configured for Traefik reverse-proxy with automatic TLS (`vault.<PRIMARY_DOMAIN>` via Let's Encrypt). Mount your `vault.db` and `passwd.txt` before starting:

```bash
docker compose up -d
```
