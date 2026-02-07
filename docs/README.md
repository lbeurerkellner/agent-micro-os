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

### Containerization
- **[sandbox](sandbox.md)** - Execute commands in Docker containers with vault access

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
| sandbox | Docker container integration |

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

## Additional Resources

### Internal
- [CLAUDE.md](../CLAUDE.md) - Development guidelines
- [README.md](../README.md) - Project overview
- [TODO.md](../TODO.md) - Project roadmap

### External
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
