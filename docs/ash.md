# ash(1) - Agent Shell

## NAME
**ash** - Agent Shell, an interactive command-line interface for the agent vault

## SYNOPSIS
```
ash --user <username> --fsimage <path> [--command <cmd>] [--debug]
```

## DESCRIPTION
**ash** (Agent Shell) is a UNIX-like shell environment that provides an interactive command-line interface to the agent vault filesystem. It supports tab completion, command history, and a familiar UNIX command syntax.

The shell operates on a virtual filesystem stored in a SQLite database, providing versioning, multi-user access, and atomic commits. All commands are executed within a SystemContext that maintains the current working directory, user identity, and filesystem state.

## OPTIONS

**--user** *username*
> Specify the username for the session. Required.

**--fsimage** *path*
> Path to the filesystem image (SQLite database). Required.

**-c, --command** *cmd*
> Execute a single command in non-interactive mode and exit.

**--debug**
> Enable debug output for tab completion and shell operations.

## INTERACTIVE FEATURES

### Tab Completion
**ash** provides intelligent tab completion for:
- **Command names**: Press TAB to complete command names from PATH
- **File paths**: Press TAB to complete file and directory paths
- **Relative paths**: Supports both relative (./file) and absolute (/home/file) paths

### Command History
- Command history is persistent across sessions
- Stored in `/etc/history` in the vault
- Use UP/DOWN arrow keys to navigate history
- History is loaded on startup and saved on exit

### Command Chaining
Commands can be chained using `&&`:
```bash
mkdir /home/backup && cp /home/data.txt /home/backup/
```
Execution stops if any command in the chain fails.

## COMMAND RESOLUTION

Commands are resolved by searching the PATH in the following order:

1. **Built-in commands** (under `/sbin/`): Implemented as Python modules in `bin/`
2. **Executable programs**: LLM prompt programs and ash scripts in PATH directories
3. **Relative paths**: Commands starting with `./` are resolved relative to CWD

### PATH Environment
The default PATH includes:
- `/sbin/` - Built-in commands
- `/bin/` - User commands
- `/usr/bin/` - Additional utilities

## BUILT-IN COMMANDS

### File Operations
- **cat** - Display file contents
- **ls** - List directory contents
- **cp** - Copy files
- **mv** - Move/rename files
- **rm** - Remove files
- **find** - Search for files

### Directory Operations
- **cd** - Change directory
- **pwd** - Print working directory (via shell prompt)

### File Editing
- **edit** - Interactive text editor
- **vim** - Vi-like text editor
- **echo** - Write text to files

### Text Processing
- **grep** - Search file contents

### System Commands
- **clear** - Clear the screen
- **exit** - Exit the shell
- **sleep** - Pause execution

### Monitoring
- **top** - Real-time system monitor
- **watch** - Execute command periodically
- **fslog** - View filesystem change log
- **usage** - Display storage usage

### Advanced Features
- **sandbox** - Launch Docker containers with vault access

## VIRTUAL FILESYSTEM

The ash shell operates on a virtual filesystem with the following characteristics:

### Mount Points
- `/sbin/` - Built-in commands (BinProvider)
- `/models/` - Available AI models (ModelProvider)
- `/tools/` - Available tools (ToolsProvider)
- `/proc/` - Process information (ProcProvider)

### File Versioning
All file modifications are versioned:
- Each write operation creates a new version
- Changes are tracked with timestamps and authors
- Use `fslog` to view change history

### Multi-User Support
- Each user has their own view of the filesystem
- Changes are attributed to the current user
- User identity is set via `--user` flag

## ENVIRONMENT

### SystemContext
Each ash session runs within a SystemContext that maintains:
- **user**: Current username
- **cwd**: Current working directory (starts at `/`)
- **fsimage**: Path to the SQLite database
- **path**: List of directories to search for commands
- **fs()**: Access to the vault filesystem

### Configuration
On startup, ash executes `/etc/profile` if it exists, allowing custom initialization.

## EXAMPLES

### Start an Interactive Session
```bash
ash --user alice --fsimage vault.db
```

### Execute a Single Command
```bash
ash --user alice --fsimage vault.db --command "ls /home"
```

### Debug Mode
```bash
ash --user alice --fsimage vault.db --debug
```

### Example Session
```
(/) > cd /home
(/home) > ls
documents/
projects/
notes.txt

(/home) > cat notes.txt
This is a note file.

(/home) > echo "New note" > newfile.txt
(/home) > ls
documents/
projects/
notes.txt
newfile.txt

(/home) > find . -name "*.txt"
./notes.txt
./newfile.txt

(/home) > fslog
2026-02-07 10:30:15 alice: write /home/newfile.txt

(/home) > exit
```

## KEYBOARD SHORTCUTS

- **Ctrl+C**: Interrupt current command (signal handling)
- **Ctrl+D**: Exit shell (EOF)
- **UP/DOWN**: Navigate command history
- **TAB**: Auto-completion
- **Ctrl+A**: Move to beginning of line (readline)
- **Ctrl+E**: Move to end of line (readline)
- **Ctrl+U**: Clear line (readline)

## FILES

- `/etc/profile` - Startup script executed on ash launch
- `/etc/history` - Persistent command history
- `vault.db` - SQLite database containing the filesystem

## SCRIPTING

### Inline Scripts
Execute multiple commands using `&&`:
```bash
cd /home && mkdir backup && cp *.txt backup/
```

### Script Files
Create executable ash scripts:
```bash
# backup.ash
cd /home/data
cp *.txt /home/backup/
echo "Backup complete"
```

Execute with:
```bash
ash --user alice --fsimage vault.db --command "$(cat backup.ash)"
```

## EXIT STATUS
- **0**: Success
- **Non-zero**: Error occurred

## ENVIRONMENT VARIABLES
Currently, ash does not support environment variables. Configuration is done through:
- Command-line flags
- SystemContext settings
- `/etc/profile` startup script

## NOTES

1. **Path Handling**: All paths are normalized and stored with leading slashes
2. **Atomicity**: File operations are atomic and versioned
3. **Concurrency**: Multiple ash sessions can access the same vault simultaneously
4. **Storage**: The vault is stored in a SQLite database with full ACID guarantees

## COMPARISON WITH BASH

| Feature | ash | bash |
|---------|-----|------|
| Filesystem | Virtual (SQLite) | Host OS |
| Versioning | Built-in | Not available |
| Tab Completion | Yes | Yes |
| Scripting | LLM prompts + commands | Bash scripts |
| Pipes | Limited | Full support |
| Environment Vars | No | Yes |
| Job Control | No | Yes |

## SEE ALSO
- **sandbox**(1) - Docker container execution
- **fslog**(1) - Filesystem change log
- **vim**(1), **edit**(1) - Text editors

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
