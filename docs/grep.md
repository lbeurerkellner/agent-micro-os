# grep(1) - Search File Contents

## NAME
**grep** - search file contents for pattern matches

## SYNOPSIS
```
grep [OPTIONS] PATTERN [FILE ...]
grep [OPTIONS] -e PATTERN [-e PATTERN ...] [FILE ...]
```

## DESCRIPTION
**grep** searches for PATTERN in each FILE (or recursively with `-r`). It supports regular expressions, fixed-string matching, case-insensitive search, whole-word matching, inverted matching, and various output formats.

This command is strictly read-only and never modifies the filesystem.

## OPTIONS

### Pattern Matching
**-i**
> Ignore case distinctions in patterns and data

**-F**
> Interpret PATTERN as a fixed string, not a regex

**-w**
> Match only whole words

**-x**
> Match only whole lines

**-e** *PATTERN*
> Use PATTERN for matching (may be repeated for multiple patterns)

### Output Control
**-v**
> Invert match - select non-matching lines

**-n**
> Prefix each line of output with the line number

**-c**
> Print only a count of matching lines per file

**-l**
> Print only names of files with matches

**-L**
> Print only names of files with no matches

**-o**
> Show only the matched (non-empty) parts of a line

**-q**
> Quiet mode - do not write anything to standard output

**-H**
> Always print filename headers with output lines

**-h**
> Suppress the prefixing of filenames on output

### Context Control
**-A** *N*
> Print N lines of trailing context after each match

**-B** *N*
> Print N lines of leading context before each match

**-C** *N*
> Print N lines of leading and trailing context

**-m** *N*
> Stop after N matches per file (0 = unlimited)

### Recursion and Filtering
**-r, -R**
> Recursively search directories

**--include=***GLOB*
> Search only files matching GLOB pattern

**--exclude=***GLOB*
> Skip files matching GLOB pattern

## PATTERN SYNTAX

### Regular Expressions (Default)
```bash
# Match literal string
grep "hello" file.txt

# Match at start of line
grep "^import" file.py

# Match at end of line
grep "world$" file.txt

# Match any character
grep "h.llo" file.txt

# Match character class
grep "[aeiou]" file.txt

# Match word boundary
grep "\bword\b" file.txt
```

### Fixed Strings (-F)
```bash
# Treat special chars literally
grep -F ".$*[]" file.txt
```

## EXAMPLES

### Basic Search
```bash
# Find lines containing "error"
(/home) > grep error logfile.txt
Error occurred at line 42
Fatal error: connection timeout
```

### Case-Insensitive Search
```bash
# Find "todo" in any case
(/home) > grep -i todo notes.txt
TODO: Fix bug
Todo: Add tests
todo: Review code
```

### Count Matches
```bash
# Count lines containing "import"
(/home) > grep -c import script.py
15
```

### Show Line Numbers
```bash
# Find pattern with line numbers
(/home) > grep -n "def " script.py
10:def main():
25:def helper_function():
42:def process_data():
```

### List Matching Files
```bash
# Find which Python files contain "class"
(/home) > grep -l "class" *.py
model.py
controller.py
view.py
```

### Recursive Search
```bash
# Search all files recursively
(/home) > grep -r "TODO" .
./notes.txt:TODO: Update docs
./src/main.py:# TODO: Refactor
./tests/test.py:TODO: Add more tests
```

### Context Lines
```bash
# Show 2 lines before and after match
(/home) > grep -C 2 "error" log.txt
line before 2
line before 1
ERROR: Connection failed
line after 1
line after 2
```

### Multiple Patterns
```bash
# Search for multiple patterns
(/home) > grep -e "error" -e "warning" log.txt
WARNING: Disk space low
ERROR: Connection timeout
```

### Whole Word Matching
```bash
# Match only whole word "log"
(/home) > grep -w "log" file.txt
log entry found       # Matches
logging is enabled    # Does NOT match
```

### Inverted Match
```bash
# Show lines NOT containing "#"
(/home) > grep -v "^#" config.txt
host=localhost
port=8080
```

### With File Patterns
```bash
# Search only Python files
(/home) > grep -r --include="*.py" "import sys" .

# Exclude test files
(/home) > grep -r --exclude="*test*" "TODO" .
```

### Only Matching Parts
```bash
# Show only matched text
(/home) > grep -o "http[s]*://[^[:space:]]*" file.txt
https://example.com
http://test.org
```

## OUTPUT FORMATS

### Default (Matched Lines)
```
line containing pattern
another line with pattern
```

### With Filenames (Multiple Files)
```
file1.txt:matched line
file2.txt:matched line
```

### With Line Numbers (-n)
```
15:matched line
42:another match
```

### Count Only (-c)
```
file1.txt:5
file2.txt:12
```

### Files Only (-l)
```
file1.txt
file2.txt
```

### With Context (-C 1)
```
10-context before
11:matched line
12-context after
```

## ADVANCED USE CASES

### Find Function Definitions
```bash
# Find all function definitions in Python
(/home) > grep -n "^def " *.py
```

### Search Logs for Errors
```bash
# Find errors with context
(/home) > grep -A 3 -B 1 "ERROR" application.log
```

### Find Configuration Values
```bash
# Extract port number from config
(/home) > grep -o "port=[0-9]*" config.ini
port=8080
```

### Count Occurrences
```bash
# Count TODO comments per file
(/home) > grep -c "TODO" *.py
main.py:5
utils.py:12
test.py:3
```

### Find Empty Lines
```bash
# Match empty lines (inverted)
(/home) > grep -v "^$" file.txt
```

### Search Multiple Directories
```bash
# Search in specific subdirectories
(/home) > grep -r "pattern" src/ tests/ docs/
```

## EXIT STATUS
- **0**: Match found
- **1**: No match found
- **2**: Error occurred

## TECHNICAL DETAILS

### Regular Expression Engine
- Uses Python `re` module
- Supports full Python regex syntax
- Compiled patterns for efficiency

### Performance
- **Single file**: Linear scan
- **Recursive**: All vault files examined
- **Memory**: Efficient - processes line-by-line

### File Encoding
- Assumes UTF-8 encoding
- Binary files may produce unexpected results
- Use `--include`/`--exclude` to filter file types

## DIFFERENCES FROM UNIX grep

| Feature | ash grep | GNU grep |
|---------|----------|----------|
| Regex support | Yes | Yes |
| Case insensitive | -i | -i |
| Context lines | -A -B -C | -A -B -C |
| Recursive | -r | -r |
| File patterns | --include/exclude | --include/exclude |
| Performance | Python regex | C implementation |
| Binary files | No special handling | --binary-files |
| Color output | No | --color |

## REGEX QUICK REFERENCE

| Pattern | Meaning |
|---------|---------|
| `.` | Any character |
| `^` | Start of line |
| `$` | End of line |
| `*` | 0 or more repetitions |
| `+` | 1 or more repetitions |
| `?` | 0 or 1 repetition |
| `[abc]` | Character class |
| `[^abc]` | Negated class |
| `\d` | Digit |
| `\w` | Word character |
| `\s` | Whitespace |
| `(...)` | Group |
| `\|` | Alternation |

## COMMON PATTERNS

### Python
```bash
# Find imports
grep "^import\|^from" *.py

# Find class definitions
grep "^class " *.py

# Find function definitions
grep "^def " *.py
```

### Configuration Files
```bash
# Find uncommented lines
grep -v "^\s*#" config.ini

# Find specific setting
grep "^host=" config.ini
```

### Log Files
```bash
# Find errors and warnings
grep -E "ERROR|WARNING" app.log

# Find by date
grep "2026-02-07" access.log
```

## LIMITATIONS

1. **No Binary File Detection**: Binary files processed as text
2. **No Color Output**: No `--color` option
3. **No Perl Regex**: Only Python regex supported
4. **No Null-Separated Output**: No `-Z` option
5. **No Max Match Depth**: Unlimited recursion depth

## SCRIPTING WITH GREP

### Conditional Execution
```bash
# Check if pattern exists
if grep -q "error" log.txt; then
    echo "Errors found!"
fi
```

### Extract and Process
```bash
# Extract IP addresses
grep -o "[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}" access.log
```

### Combine with Other Tools
```bash
# Count unique matches
grep -o "pattern" file.txt | sort | uniq -c
```

## SEE ALSO
- **find**(1) - Search for files by name
- **cat**(1) - Display file contents
- **sed**(1) - Stream editor (if available)
- **awk**(1) - Pattern scanning (if available)

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
