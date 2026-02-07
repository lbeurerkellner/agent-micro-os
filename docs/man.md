# man(1) - Display Manual Pages

## NAME
**man** - display manual pages for commands

## SYNOPSIS
```
man <command>
man
```

## DESCRIPTION
**man** displays the manual page (documentation) for the specified command. Manual pages are stored as Markdown files in the `docs/` directory of the project.

When invoked without arguments, **man** lists all available manual pages.

## ARGUMENTS

*command*
> Name of the command to display documentation for (e.g., `ash`, `grep`, `sandbox`)

## BEHAVIOR

### Display Manual Page
```bash
(/home) > man ash
# ash(1) - Agent Shell

## NAME
**ash** - Agent Shell for vault environment
...
```

### List Available Pages
```bash
(/home) > man
Available manual pages:
  ash
  cat
  grep
  ls
  man
  sandbox
```

### Command Not Found
```bash
(/home) > man nonexistent
man: No manual entry for nonexistent

Try 'man' without arguments to see available manual pages.
```

## EXAMPLES

### View Documentation for Sandbox
```bash
(/home) > man sandbox
```
Displays comprehensive documentation about Docker container execution.

### View Documentation for Grep
```bash
(/home) > man grep
```
Shows detailed grep command usage, options, and examples.

### List All Available Commands
```bash
(/home) > man
Available manual pages:
  ash
  cat
  grep
  ls
  man
  sandbox
```

### Quick Help
```bash
# Get usage information for any command
(/home) > man cat
(/home) > man sandbox
(/home) > man ash
```

## DOCUMENTATION STRUCTURE

Manual pages are organized in the `docs/` directory:

```
docs/
├── ash.md        # Agent Shell
├── cat.md        # Concatenate files
├── grep.md       # Search files
├── ls.md         # List directory
├── man.md        # This page
├── sandbox.md    # Docker containers
```

## MANUAL PAGE FORMAT

Each manual page follows the standard UNIX man page structure:

1. **NAME**: Command name and brief description
2. **SYNOPSIS**: Command syntax
3. **DESCRIPTION**: Detailed explanation
4. **OPTIONS**: Command-line flags and arguments
5. **EXAMPLES**: Practical usage examples
6. **SEE ALSO**: Related commands
7. **AUTHOR**: Documentation author
8. **BUGS**: How to report issues

## ADDING NEW MANUAL PAGES

To add documentation for a new command:

1. Create `docs/<command>.md`
2. Follow the standard man page structure
3. Use Markdown formatting
4. Include comprehensive examples

**Example:**
```markdown
# mycommand(1) - Brief Description

## NAME
**mycommand** - what it does

## SYNOPSIS
```
mycommand [OPTIONS] ARGS
```

## DESCRIPTION
Detailed explanation...
```

## MARKDOWN FORMATTING

Manual pages support GitHub-flavored Markdown:

### Headings
```markdown
# H1 - Command Name
## H2 - Sections
### H3 - Subsections
```

### Code Blocks
````markdown
```bash
command example
```
````

### Emphasis
```markdown
**bold**
*italic*
`code`
```

### Lists
```markdown
- Item 1
- Item 2

1. First
2. Second
```

### Tables
```markdown
| Column 1 | Column 2 |
|----------|----------|
| Value 1  | Value 2  |
```

## USE CASES

### Learning New Commands
```bash
# Learn about sandbox execution
(/home) > man sandbox
```

### Reference During Development
```bash
# Check grep options
(/home) > man grep
```

### Onboarding New Users
```bash
# Introduce new users to the shell
(/home) > man ash
```

### Troubleshooting
```bash
# Understand error messages
(/home) > man sandbox
```

## TECHNICAL DETAILS

### File Resolution
1. Check if argument provided
2. Look for `docs/<command>.md`
3. Display file if found, error otherwise

### Path Location
Manual pages are stored at:
```
<project-root>/docs/
```

Accessed via:
```python
docs_dir = Path(__file__).parent.parent / "docs"
doc_path = docs_dir / f"{command}.md"
```

### Display Method
- Reads entire file into memory
- Prints to stdout using `print(content)`
- No paging or scrolling (full output)

## EXIT STATUS
- **0**: Success (manual page displayed or list shown)
- **Non-zero**: Error (command not found or read error)

## DIFFERENCES FROM UNIX man

| Feature | ash man | UNIX man |
|---------|---------|----------|
| Format | Markdown | Troff/groff |
| Pager | No (full output) | Yes (less/more) |
| Search | No | / key in pager |
| Sections | No (all in section 1) | Yes (1-8) |
| Formatting | Markdown | Man page macros |
| Location | docs/ directory | /usr/share/man/ |
| Database | No (directory scan) | Yes (mandb) |

## LIMITATIONS

1. **No Paging**: Full output, no scrolling
2. **No Search**: Cannot search within page
3. **No Sections**: All commands in section 1
4. **No Formatting**: Plain text, no bold/underline in terminal
5. **No Man Path**: Fixed location in project
6. **No Compression**: Files stored as plain Markdown
7. **No Apropos**: No keyword search across all pages

## WORKAROUNDS

### Paging Long Pages
```bash
# Pipe to less (if available)
(/home) > man ash | less

# Or redirect to file
(/home) > man ash > /tmp/ash-docs.txt
(/home) > cat /tmp/ash-docs.txt
```

### Search Within Page
```bash
# Use grep to find specific content
(/home) > man ash | grep -A 5 "examples"
```

### Convert to HTML
```bash
# If markdown converter available
(/home) > man ash > ash.md
(/home) > markdown ash.md > ash.html
```

## FUTURE ENHANCEMENTS

Potential improvements:
- **Paging**: Integrate with pager (less/more)
- **Search**: In-page search functionality
- **Sections**: Organize commands by category
- **Formatting**: Terminal formatting (bold, underline)
- **Apropos**: Keyword search across all pages
- **HTML Export**: Generate HTML documentation

## DOCUMENTATION STANDARDS

When writing manual pages:

### Structure
- Follow standard man page sections
- Use consistent heading levels
- Include comprehensive examples

### Content
- Be concise but thorough
- Explain all options clearly
- Provide practical examples
- Include error messages and solutions

### Style
- Use active voice
- Write in present tense
- Be precise and unambiguous
- Include cross-references

## COMPARISON TABLE

| Command | Description | Key Features |
|---------|-------------|--------------|
| ash | Agent Shell | REPL, tab completion |
| sandbox | Docker integration | Isolation, versioning |
| ls | List files | Directory browsing |
| cat | Display files | File viewing |
| grep | Search files | Pattern matching |

## SEE ALSO
- **help**(1) - Built-in command help (if available)
- **info**(1) - Info documentation (if available)
- **ash**(1) - Agent Shell documentation

## EXTERNAL RESOURCES
- Markdown Guide: https://www.markdownguide.org/
- Man Page Writing: https://man7.org/linux/man-pages/

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues

## VERSION HISTORY
- 1.0: Initial implementation with Markdown support
