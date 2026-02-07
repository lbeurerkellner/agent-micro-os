# ls(1) - List Directory Contents

## NAME
**ls** - list directory contents

## SYNOPSIS
```
ls [-t] [DIRECTORY]
```

## DESCRIPTION
**ls** lists files and directories in the specified directory (or current working directory if none specified). It displays entries in alphabetical order by default, or by timestamp when using the `-t` option.

Directories are indicated with a trailing slash (`/`).

## OPTIONS

**-t**
> Display timestamps. Shows modification time for files, blank for directories. Files are sorted by most recent first, directories appear last.

*DIRECTORY*
> Directory to list. If omitted, lists current working directory. Can be relative or absolute path.

## OUTPUT FORMAT

### Default Mode
```
file1.txt
file2.log
subdirectory/
```

Entries are printed one per line in alphabetical order.

### With Timestamps (-t)
```
2026-02-07 14:30:22  recent.txt
2026-02-07 10:15:03  older.txt
                     subdirectory/
```

Format: `YYYY-MM-DD HH:MM:SS  filename`
- Files: Timestamp from last modification
- Directories: Empty timestamp field (19 spaces)
- Order: Most recent files first, then directories

## DIRECTORY INDICATORS

Directories are shown with a trailing slash:
- `data/` - Directory
- `file.txt` - Regular file

## PATH RESOLUTION

Paths can be:
- **Absolute**: `/home/projects/`
- **Relative to CWD**: `projects/`
- **Parent directory**: `../`
- **Current directory**: `./` or `.`

## EXAMPLES

### List Current Directory
```bash
(/) > ls
home/
sbin/
etc/
models/

(/) > cd home
(/home) > ls
documents/
notes.txt
script.py
```

### List Specific Directory
```bash
(/home) > ls /
home/
sbin/
etc/
models/

(/home) > ls documents
report.pdf
data.csv
```

### List with Timestamps
```bash
(/home) > ls -t
2026-02-07 14:30:22  script.py
2026-02-07 10:15:03  notes.txt
                     documents/
```

Shows that `script.py` was modified most recently.

### Recursive Listing (Use with Other Commands)
```bash
# Use find for recursive listing
(/home) > find . -type f
./notes.txt
./script.py
./documents/report.pdf
./documents/data.csv
```

## BEHAVIOR

### Empty Directories
Empty directories produce no output:
```bash
(/home/empty) > ls
(/home/empty) >
```

### Non-Existent Directory
Error handling for invalid paths:
```bash
(/home) > ls /nonexistent
(No output - directory treated as empty)
```

### Files vs Directories
Only direct children are shown (non-recursive):
```bash
(/home) > ls
projects/        # Contains many files, but only directory shown
README.md        # File in /home
```

## TECHNICAL DETAILS

### Listing Algorithm
1. Retrieve all files from vault
2. Filter by target directory prefix
3. Extract immediate children (files and subdirectories)
4. Deduplicate entries
5. Sort alphabetically (or by timestamp with `-t`)

### Performance
- **Fast**: Single vault query regardless of directory size
- **Memory**: Minimal - only direct children loaded
- **Scalability**: Efficient even for large vaults

## DIFFERENCES FROM UNIX ls

| Feature | ash ls | UNIX ls |
|---------|--------|---------|
| Timestamps | -t only | Multiple formats (-l, -lt, etc.) |
| Long format | Not available | -l |
| Hidden files | All shown | Need -a |
| Colors | Not supported | --color |
| Sorting | Alpha or time | Multiple options |
| Columns | Single column | Auto-width columns |
| File size | Not shown | -l shows size |
| Permissions | Not shown | -l shows mode |

## LIMITATIONS

1. **No Long Format**: No `-l` option for detailed file information
2. **No File Size**: File sizes not displayed
3. **No Permissions**: Ownership and modes not shown
4. **No Colors**: No color-coded output
5. **No Column Layout**: Always single-column output
6. **No Sorting Options**: Only alphabetical or time sorting

## USE CASES

### Basic Navigation
```bash
# Explore directory structure
(/) > ls
(/) > cd home
(/home) > ls
(/home) > cd projects
```

### File Discovery
```bash
# Find recently modified files
(/home) > ls -t
2026-02-07 14:30:22  latest.log
2026-02-07 10:15:03  previous.log
```

### Scripting
```bash
# Check if directory has files (use in scripts)
files=$(ls /home/data)
if [ -z "$files" ]; then
    echo "Directory is empty"
fi
```

### Verification
```bash
# Verify file creation
(/home) > echo "test" > newfile.txt
(/home) > ls
newfile.txt
```

## RELATED OPERATIONS

### Count Files
```bash
# Count files in directory
(/home) > ls | wc -l
```

### Filter Output
```bash
# Find .txt files
(/home) > ls | grep "\.txt$"
notes.txt
data.txt
```

### Find Command (Recursive)
```bash
# Recursively find all Python files
(/home) > find . -name "*.py"
./script.py
./utils/helpers.py
./tests/test_main.py
```

## EXIT STATUS
- **0**: Success (always - errors not currently reported via exit status)

## NOTES

1. **Virtual Filesystem**: Operates on vault, not host filesystem
2. **No Inode Information**: Vault uses filepath-based addressing
3. **Timestamp Source**: From vault modification log
4. **Directory Detection**: Based on presence of children with `/` prefix

## SEE ALSO
- **find**(1) - Search for files recursively
- **cat**(1) - Display file contents
- **cd**(1) - Change directory
- **pwd**(1) - Print working directory (via shell prompt)

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
