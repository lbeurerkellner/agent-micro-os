# star(1) - Starlark Script Executor

## NAME
**star** - Execute Starlark scripts with vault filesystem access

## SYNOPSIS
```
star <script.star> [args...]
```

## DESCRIPTION
**star** executes Starlark scripts within the agent vault environment. Starlark is a deterministic, Python-like scripting language originally designed by Google for the Bazel build system. It provides a safe, sandboxed environment for scripting automation tasks within the vault.

Scripts executed by **star** have full access to the vault filesystem through a specialized `fs` API, can execute shell commands through `run_command()`, and can receive command-line arguments.

## STARLARK LANGUAGE

Starlark is a dialect of Python with the following characteristics:

### Syntax Features
- **Functions**: Define and call functions with `def`
- **Control Flow**: `if`, `elif`, `else`, `for`, `while` (inside functions only)
- **Data Types**: strings, integers, lists, dictionaries, tuples
- **Operators**: arithmetic (+, -, *, /), comparison (==, !=, <, >), logical (and, or, not)
- **List Comprehensions**: `[x * 2 for x in range(10)]`

### Restrictions
- **No Classes**: Starlark does not support class definitions
- **Immutable by Default**: Many data structures are frozen after creation
- **No Imports**: Cannot import external modules (use built-in functions)
- **Deterministic**: No system calls, threading, or non-deterministic operations
- **Top-level Control Flow**: Loops and conditionals must be inside functions

## BUILT-IN API

### Filesystem Operations

All filesystem operations are accessed through the `fs` dictionary using bracket notation:

#### fs['read'](path)
Read a file from the vault.

**Parameters:**
- `path` (string): Path to the file (relative or absolute)

**Returns:** File contents as a string

**Example:**
```python
content = fs['read']("/home/config.txt")
print("Config:", content)
```

**Errors:**
- Raises exception if file does not exist
- Returns `<binary data: N bytes>` for non-UTF-8 files

#### fs['write'](path, content)
Write a file to the vault.

**Parameters:**
- `path` (string): Path to the file (relative or absolute)
- `content` (string): Content to write

**Returns:** None

**Example:**
```python
fs['write']("/home/output.txt", "Hello, World!")
```

**Notes:**
- Creates parent directories automatically if needed
- Overwrites existing files
- All writes are attributed to the "starlark" author in the vault log

#### fs['list'](path="/")
List directory contents.

**Parameters:**
- `path` (string, optional): Directory path (default: root "/")

**Returns:** List of filenames (basenames only, not full paths)

**Example:**
```python
files = fs['list']("/home")
for filename in files:
    print("Found:", filename)
```

**Notes:**
- Returns immediate children only (not recursive)
- Returns basenames, not full paths
- Includes both files and subdirectories

#### fs['delete'](path)
Delete a file from the vault.

**Parameters:**
- `path` (string): Path to the file (relative or absolute)

**Returns:** None

**Example:**
```python
fs['delete']("/home/temp.txt")
print("File deleted")
```

**Errors:**
- Raises exception if file does not exist

#### fs['exists'](path)
Check if a file or directory exists.

**Parameters:**
- `path` (string): Path to check (relative or absolute)

**Returns:** `True` if exists, `False` otherwise

**Example:**
```python
if fs['exists']("/home/config.txt"):
    config = fs['read']("/home/config.txt")
else:
    print("Config file not found")
```

#### fs['is_dir'](path)
Check if a path is a directory.

**Parameters:**
- `path` (string): Path to check (relative or absolute)

**Returns:** `True` if directory, `False` otherwise

**Example:**
```python
if fs['is_dir']("/home/data"):
    files = fs['list']("/home/data")
    print("Directory contains:", len(files), "items")
```

### Shell Command Execution

#### run_command(command)
Execute an ash shell command and capture its output.

**Parameters:**
- `command` (string): Shell command to execute (e.g., "ls -la", "grep pattern file.txt")

**Returns:** Command output as a string

**Example:**
```python
output = run_command("ls /home")
print("Directory listing:", output)

# Execute multiple commands
result = run_command("echo hello && cat /home/file.txt")
```

**Notes:**
- Commands execute in the ash shell environment
- Has access to all vault commands (ls, cat, grep, etc.)
- Supports command chaining with `&&`
- Captures both stdout and stderr

### Output Functions

#### print(text)
Print text to the script output.

**Parameters:**
- `text` (any): Text to print (automatically converted to string)

**Returns:** None

**Example:**
```python
print("Processing files...")
print("Count:", 42)
print("Items:", ["a", "b", "c"])
```

### Command-Line Arguments

#### args
List of command-line arguments passed to the script.

**Type:** List of strings

**Example:**
```python
# Called as: star script.star input.txt output.txt

if len(args) < 2:
    print("Usage: script.star <input> <output>")
else:
    input_file = args[0]    # "input.txt"
    output_file = args[1]   # "output.txt"

    data = fs['read'](input_file)
    fs['write'](output_file, data)
```

## EXAMPLES

### Example 1: Hello World
```python
# hello.star
print("Hello from Starlark!")
```

Run with: `star hello.star`

### Example 2: File Processing
```python
# process.star - Convert text to uppercase
if len(args) < 2:
    print("Usage: process.star <input> <output>")
else:
    input_path = args[0]
    output_path = args[1]

    # Read input file
    content = fs['read'](input_path)

    # Process (convert to uppercase)
    result = content.upper()

    # Write output file
    fs['write'](output_path, result)
    print("Processed:", input_path, "->", output_path)
```

Run with: `star process.star /home/input.txt /home/output.txt`

### Example 3: Backup Tool
```python
# backup.star - Backup all .txt files
def backup_txt_files(source_dir, backup_dir):
    """Backup all .txt files from source to backup directory."""
    files = fs['list'](source_dir)
    count = 0

    for filename in files:
        if filename.endswith(".txt"):
            source_path = source_dir + "/" + filename
            backup_path = backup_dir + "/" + filename

            content = fs['read'](source_path)
            fs['write'](backup_path, content)
            print("Backed up:", filename)
            count = count + 1

    print("Total files backed up:", count)

# Run the backup
if len(args) >= 2:
    backup_txt_files(args[0], args[1])
else:
    backup_txt_files("/home/data", "/home/backup")
```

Run with: `star backup.star /home/docs /home/backup/docs`

### Example 4: File Statistics
```python
# stats.star - Analyze file sizes in a directory
def analyze_directory(path):
    """Print statistics about files in a directory."""
    files = fs['list'](path)

    total_size = 0
    file_count = 0

    print("Analyzing:", path)
    print()

    for filename in files:
        filepath = path + "/" + filename

        # Skip directories
        if fs['is_dir'](filepath):
            continue

        # Get file size
        content = fs['read'](filepath)
        size = len(content)

        print("  %s: %d bytes" % (filename, size))

        total_size = total_size + size
        file_count = file_count + 1

    print()
    print("Summary:")
    print("  Files:", file_count)
    print("  Total size:", total_size, "bytes")

    if file_count > 0:
        avg = total_size // file_count
        print("  Average size:", avg, "bytes")

# Run analysis
target = args[0] if len(args) > 0 else "/home"
analyze_directory(target)
```

Run with: `star stats.star /home/data`

### Example 5: Using Shell Commands
```python
# find_pattern.star - Search for a pattern in files
def search_files(directory, pattern):
    """Search for a pattern using grep."""
    cmd = "grep -r '" + pattern + "' " + directory
    result = run_command(cmd)
    print(result)

if len(args) >= 2:
    search_files(args[0], args[1])
else:
    print("Usage: find_pattern.star <directory> <pattern>")
```

Run with: `star find_pattern.star /home "TODO"`

### Example 6: FizzBuzz
```python
# fizzbuzz.star - Classic FizzBuzz implementation
def fizzbuzz(n):
    """Print FizzBuzz from 1 to n."""
    for i in range(1, n + 1):
        output = ""

        if i % 3 == 0:
            output = output + "Fizz"
        if i % 5 == 0:
            output = output + "Buzz"

        if output:
            print(output)
        else:
            print(i)

# Get count from args or default to 15
count = int(args[0]) if len(args) > 0 else 15
fizzbuzz(count)
```

Run with: `star fizzbuzz.star 20`

### Example 7: Configuration File Generator
```python
# genconfig.star - Generate a configuration file
def generate_config(output_path, settings):
    """Generate a configuration file from settings dict."""
    lines = []

    for key in settings:
        value = settings[key]
        line = key + "=" + str(value)
        lines.append(line)

    content = "\n".join(lines)
    fs['write'](output_path, content)
    print("Configuration written to:", output_path)

# Define settings
config = {
    "host": "localhost",
    "port": "8080",
    "debug": "true",
    "max_connections": "100"
}

# Generate config file
output = args[0] if len(args) > 0 else "/home/config.ini"
generate_config(output, config)
```

Run with: `star genconfig.star /home/server.conf`

## EXIT STATUS
- **0**: Success
- **Non-zero**: Error occurred during script execution

## ERROR HANDLING

### Syntax Errors
If the script contains syntax errors, **star** will report them:
```
star: script.star: Syntax error: unexpected token
```

### Runtime Errors
Runtime errors (e.g., file not found, invalid operations) are reported:
```
star: script.star: Runtime error: File not found: /nonexistent.txt
```

### Name Errors
Undefined variable or function references:
```
star: script.star: Name error: undefined: unknown_variable
```

## NOTES

1. **Path Resolution**: Paths can be relative (to current working directory) or absolute
2. **String Concatenation**: Use `+` operator: `path = dir + "/" + filename`
3. **Top-Level Control Flow**: Wrap loops/conditionals in functions (see wrapped_script in implementation)
4. **Performance**: Starlark is interpreted; for heavy processing, consider using shell commands
5. **Sandboxing**: Starlark provides safety - scripts cannot access host system directly

## USE CASES

**star** is ideal for:
- **Automation**: Batch file processing, backups, cleanup tasks
- **Data Processing**: Text transformation, log analysis, report generation
- **Configuration Management**: Generating config files, updating settings
- **System Administration**: File organization, permission management
- **Custom Tools**: Building reusable command-line tools in Starlark
- **Testing**: Scripting test scenarios for vault operations

## COMPARISON WITH OTHER TOOLS

| Feature | star | ash scripts | Python |
|---------|------|-------------|--------|
| Vault Access | Native | Native | Requires API |
| Safety | Sandboxed | Full access | Full access |
| Syntax | Python-like | Shell | Python |
| Performance | Medium | Fast | Fast |
| Use Case | Vault automation | System tasks | General programming |

## SEE ALSO
- **ash**(1) - Agent Shell
- **sandbox**(1) - Docker container execution
- **cat**(1), **ls**(1), **grep**(1) - Basic file operations

## STARLARK RESOURCES
- Starlark Language Specification: https://github.com/bazelbuild/starlark
- Bazel Starlark Guide: https://bazel.build/rules/language

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
