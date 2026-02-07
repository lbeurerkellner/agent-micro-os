# AgentVault Command Documentation

This directory contains manual pages for all AgentVault commands. Each manual page is written in Markdown format and can be viewed using the `man` command.

## Usage

```bash
# View documentation for a specific command
man <command>

# List all available manual pages
man
```

## Available Commands

### Core Shell
- **[ash](ash.md)** - Agent Shell, the main interactive shell environment
- **[man](man.md)** - Display manual pages for commands

### Scripting & Automation
- **[star](star.md)** - Execute Starlark scripts with vault filesystem access

### Containerization
- **[sandbox](sandbox.md)** - Execute commands in Docker containers with vault access
- **[claude](claude.md)** - Run Claude Code AI assistant in a sandboxed environment

### File Operations
- **[ls](ls.md)** - List directory contents
- **[cat](cat.md)** - Concatenate and display files
- **[grep](grep.md)** - Search file contents for patterns

## Command Categories

### File Management
| Command | Description |
|---------|-------------|
| ls | List files and directories |
| cat | Display file contents |
| cp | Copy files |
| mv | Move/rename files |
| rm | Remove files |
| find | Search for files |

### Text Processing
| Command | Description |
|---------|-------------|
| grep | Search file contents |
| echo | Display text or write to files |
| edit | Interactive text editor |
| vim | Vi-like text editor |

### System & Monitoring
| Command | Description |
|---------|-------------|
| top | Real-time system monitor |
| watch | Execute command periodically |
| fslog | View filesystem change log |
| usage | Display storage usage |

### Advanced Features
| Command | Description |
|---------|-------------|
| star | Starlark script executor |
| sandbox | Docker container integration |
| claude | AI coding assistant |

## Documentation Format

Each manual page follows the standard UNIX man page structure:

1. **NAME** - Command name and brief description
2. **SYNOPSIS** - Command syntax
3. **DESCRIPTION** - Detailed explanation
4. **OPTIONS** - Command-line flags and arguments
5. **EXAMPLES** - Practical usage examples
6. **EXIT STATUS** - Return codes
7. **NOTES** - Additional information
8. **SEE ALSO** - Related commands
9. **AUTHOR** - Documentation author
10. **BUGS** - How to report issues

## Quick Start Examples

### Hello World with Star
```bash
# Create a Starlark script
echo 'print("Hello, World!")' > hello.star

# Execute it
star hello.star
```

### Sandbox Development
```bash
# Launch Python environment
sandbox --image python:3.11

# Inside container:
pip install requests
python script.py
# Exit container

# Changes are automatically committed to vault
```

### File Search
```bash
# Find all Python files
find . -name "*.py"

# Search for TODO comments
grep -r "TODO" .

# Count lines of code
cat *.py | wc -l
```

### Shell Navigation
```bash
# Start ash
ash --user alice --fsimage vault.db

# Navigate and explore
(/) > ls
(/) > cd home
(/home) > ls -t
(/home) > cat README.md
```

## Extending Documentation

To add documentation for a new command:

1. Create `docs/<command>.md`
2. Follow the standard man page template
3. Include comprehensive examples
4. Test with `man <command>`

**Template:**
```markdown
# command(1) - Brief Description

## NAME
**command** - what it does

## SYNOPSIS
\```
command [OPTIONS] ARGS
\```

## DESCRIPTION
Detailed explanation of the command...

## OPTIONS
List all command-line options...

## EXAMPLES
Practical usage examples...

## SEE ALSO
Related commands...

## AUTHOR
Written as part of the agentvault project.
```

## Documentation Standards

### Writing Style
- **Clarity**: Be clear and concise
- **Completeness**: Cover all features
- **Examples**: Include practical examples
- **Cross-references**: Link to related commands

### Formatting
- Use GitHub-flavored Markdown
- Include code blocks with syntax highlighting
- Use tables for comparison
- Add section headings for navigation

### Content
- Explain the "why" not just the "what"
- Include common use cases
- Document error messages
- Provide troubleshooting tips

## Star Command Highlights

The **[star](star.md)** command deserves special attention as it enables powerful scripting capabilities:

### Filesystem Access
```python
# Read files
content = fs['read']("/home/data.txt")

# Write files
fs['write']("/home/output.txt", "result")

# List directory
files = fs['list']("/home")

# Check existence
if fs['exists']("/home/config.json"):
    config = fs['read']("/home/config.json")
```

### Shell Integration
```python
# Execute shell commands
output = run_command("ls /home")
print(output)

# Chain commands
run_command("mkdir /home/backup && cp /home/*.txt /home/backup/")
```

### Practical Examples

**Backup Tool:**
```python
def backup_txt_files(source_dir, backup_dir):
    files = fs['list'](source_dir)
    for filename in files:
        if filename.endswith(".txt"):
            content = fs['read'](source_dir + "/" + filename)
            fs['write'](backup_dir + "/" + filename, content)
            print("Backed up:", filename)

backup_txt_files("/home/docs", "/home/backup")
```

**File Statistics:**
```python
def analyze_directory(path):
    files = fs['list'](path)
    total_size = 0
    for filename in files:
        if not fs['is_dir'](path + "/" + filename):
            content = fs['read'](path + "/" + filename)
            total_size += len(content)
    print("Total size:", total_size, "bytes")

analyze_directory("/home/data")
```

## Additional Resources

### Internal
- [CLAUDE.md](../CLAUDE.md) - Development guidelines
- [README.md](../README.md) - Project overview
- [TODO.md](../TODO.md) - Project roadmap

### External
- [Starlark Language Spec](https://github.com/bazelbuild/starlark)
- [Docker Documentation](https://docs.docker.com/)
- [Markdown Guide](https://www.markdownguide.org/)

## Contributing

To improve this documentation:

1. Edit the relevant `.md` file in `docs/`
2. Follow the established format
3. Test with `man <command>`
4. Submit changes for review

## Version

Documentation version: 1.0
Last updated: 2026-02-07

---

**Need help?** Run `man` to see all available commands, or `man <command>` for detailed documentation.
