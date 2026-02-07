# AgentVault Architecture

AgentVault is a versioned filesystem environment with tool integration for AI agents. The system provides a Unix-like interface with sandboxed execution capabilities (a micro operating system for agents).

## Core Components

### Vault
The [vault](fs/vault.py) is a versioned SQLite-backed file system that tracks all file changes with metadata (author, timestamp, content hash). It supports reading, writing, deleting files, and maintains a full version history with commits and diffs.

### Overlay FS
The [overlay filesystem](fs/overlay.py) combines the vault (read-write) with read-only [folder providers](fs/providers.py). It mounts virtual directories:
- `/sbin` - Built-in commands via `BinProvider`
- `/tools` - Agent-callable tools via `ToolsProvider`
- `/models` - Available LLM models via `ModelProvider`
- `/proc` - Running agent processes via `ProcProvider`

### Tools
[Tools](system/tools.py) are Python functions decorated with `@tool` that agents can call. Examples: `read()`, `write()`, `list_directory()`, `grep()`, `sleep()`. Tools access the vault through the [SystemContext](system/context.py).

### Models
The [ModelProvider](fs/providers.py#L54-L112) exposes available LLM models as virtual files under `/models/<provider>/<model>`. Currently supports OpenAI models (via `OPENAI_API_KEY` env var) and an echo model for testing.

### Sandbox
The [sandbox](bin/sandbox.py) launches Docker containers with vault contents mounted as a volume. Changes made inside the container are automatically diffed and committed back to the vault. Supports custom images, command execution, and environment variables.

### Built-in Commands
[Built-in commands](bin/) are shell-like utilities implemented as async Python modules:
- File operations: `cat`, `ls`, `cp`, `mv`, `rm`, `edit`
- Search: `find`, `grep`, `fslog`
- System: `cd`, `clear`, `exit`, `sleep`, `watch`, `top`
- Execution: `ash` (shell), `sandbox`, `star`, `claude`

Commands are resolved via the system `PATH` ([/sbin, /bin]) and executed by the [execute](system/execute.py) module.

### Star
[Star](bin/star.py) executes Starlark scripts from the vault. Scripts have access to filesystem operations (`fs['read']`, `fs['write']`), command execution (`run_command`), and arguments. Useful for automation and scripting within the vault environment.

## Test-Driven Development

The [tests/](tests/) directory contains test cases and protocol definitions for how the implementation should behave.

When implementing features:
1. Start by writing or updating tests to cover the new functionality
2. Implement the feature to make tests pass
3. Never change tests without asking first (unless there's an inconsistency)

Use `uv run pytest` for all Python test execution.