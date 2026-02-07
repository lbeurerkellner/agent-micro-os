# cat(1) - Concatenate and Display Files

## NAME
**cat** - concatenate files and print on the standard output

## SYNOPSIS
```
cat <file> [file2 ...]
```

## DESCRIPTION
**cat** reads one or more files from the vault and displays their contents to standard output. For text files, content is displayed as-is. For binary files, a placeholder message is shown indicating the file size.

Multiple files are concatenated in the order specified.

## ARGUMENTS

*file*
> File path to display (required). Can be relative or absolute.

*file2 ...*
> Additional files to display (optional). Contents are concatenated in order.

## BEHAVIOR

### Text Files
UTF-8 encoded files are displayed with their full content:
```bash
(/home) > cat notes.txt
This is a text file.
Line 2.
Line 3.
```

### Binary Files
Non-UTF-8 files show size information instead of raw bytes:
```bash
(/home) > cat image.png
<binary data: 45823 bytes>
```

### Multiple Files
Files are concatenated sequentially:
```bash
(/home) > cat file1.txt file2.txt
Contents of file1.txt
Contents of file2.txt
```

### Error Handling

**File Not Found:**
```bash
(/home) > cat nonexistent.txt
cat: nonexistent.txt: No such file or directory
```

**Directory Instead of File:**
```bash
(/home) > cat documents/
cat: documents/: Is a directory
```

**Permission Errors:**
```bash
(/home) > cat restricted.txt
cat: restricted.txt: Permission denied
```

## EXAMPLES

### Display Single File
```bash
(/home) > cat README.md
# Project Title
This is the README file.
```

### Concatenate Multiple Files
```bash
(/home) > cat header.txt body.txt footer.txt
This is the header.
This is the main content.
This is the footer.
```

### Display Configuration File
```bash
(/etc) > cat profile
echo ash v0.1 - Agent Shell
cd /home
```

### Verify File Content After Write
```bash
(/home) > echo "Hello World" > test.txt
(/home) > cat test.txt
Hello World
```

### Check JSON Configuration
```bash
(/home) > cat config.json
{
  "host": "localhost",
  "port": 8080,
  "debug": true
}
```

## USE CASES

### File Inspection
```bash
# Quickly view file contents
(/home) > cat notes.txt
```

### Log Analysis
```bash
# View log files
(/var/log) > cat application.log
```

### Configuration Review
```bash
# Check configuration
(/etc) > cat config.ini
```

### Concatenation
```bash
# Combine multiple files
(/home) > cat part1.txt part2.txt part3.txt > combined.txt
```

### Piping to Other Commands
```bash
# Count lines in file
(/home) > cat file.txt | wc -l

# Search within file
(/home) > cat file.txt | grep "pattern"
```

## TECHNICAL DETAILS

### Encoding
- **UTF-8**: Displayed as text
- **Other encodings**: Treated as binary
- **Invalid UTF-8**: Shows as binary with size

### Output
- **Newlines**: Preserved from original file
- **Final newline**: Single newline added after content
- **No line buffering**: Entire file read and displayed at once

### Memory
- Files are read entirely into memory
- Large files may consume significant RAM
- No streaming or pagination

## DIFFERENCES FROM UNIX cat

| Feature | ash cat | UNIX cat |
|---------|---------|----------|
| Display text | Yes | Yes |
| Binary detection | Automatic | Raw output |
| Multiple files | Yes | Yes |
| Line numbers | No | -n option |
| Show tabs | No | -T option |
| Show newlines | No | -E option |
| Squeeze blank lines | No | -s option |
| Stdin support | No | Yes (cat -) |

## LIMITATIONS

1. **No Standard Input**: Cannot read from stdin (no `cat -`)
2. **No Line Numbers**: No `-n` option
3. **No Special Character Display**: No `-v`, `-T`, `-E` options
4. **No Output Redirection Inside Cat**: Must use shell redirection
5. **No Pagination**: Large files dump entire content (use `less` equivalent if available)

## ALTERNATIVES

### For Large Files
```bash
# Use head/tail for large files (if available)
(/home) > head -n 20 large.log
(/home) > tail -n 50 large.log
```

### For Binary Files
```bash
# Binary files show size only
(/home) > cat binary.dat
<binary data: 1024 bytes>

# Use specialized tools if needed
```

### For Formatted Output
```bash
# Use grep with context
(/home) > grep -A 5 -B 5 "pattern" file.txt
```

## COMBINING WITH OTHER COMMANDS

### Count Lines
```bash
(/home) > cat file.txt | wc -l
42
```

### Search Content
```bash
(/home) > cat *.log | grep ERROR
```

### Extract Data
```bash
(/home) > cat data.csv | cut -d',' -f2
```

### Compare Files
```bash
(/home) > cat file1.txt > /tmp/1.txt
(/home) > cat file2.txt > /tmp/2.txt
(/home) > diff /tmp/1.txt /tmp/2.txt
```

## ERROR MESSAGES

**No such file or directory**
> File does not exist in vault

**Is a directory**
> Specified path is a directory, not a file

**Permission denied**
> Insufficient permissions to read file (rare in vault)

## EXIT STATUS
- **0**: Success (all files read successfully)
- **Non-zero**: Error (file not found, is directory, etc.)

## NOTES

1. **Vault Access**: Reads from virtual filesystem, not host OS
2. **Binary Detection**: Uses UTF-8 decode attempt
3. **Concatenation Order**: Preserves argument order
4. **Error Continuation**: Errors on one file don't stop processing others

## SEE ALSO
- **echo**(1) - Display text or write to files
- **less**(1) - Paginated file viewer (if available)
- **grep**(1) - Search file contents
- **head**(1), **tail**(1) - Display file portions (if available)

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
