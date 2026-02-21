"""grep — search file contents for pattern matches.

Supports regex, fixed-string, case-insensitive, whole-word, whole-line,
inverted, recursive, context lines, include/exclude globs, multiple
patterns, count, files-with/without-matches, only-matching, and quiet modes.

This command is strictly read-only; it never modifies the filesystem.
"""

import re
import fnmatch
from dataclasses import dataclass, field
from fs.utils import resolve_path


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass
class GrepOptions:
    """Parsed option flags for a grep invocation."""
    ignore_case: bool = False          # -i
    invert_match: bool = False         # -v
    line_number: bool = False          # -n
    count: bool = False                # -c
    files_with_matches: bool = False   # -l
    files_without_match: bool = False  # -L
    only_matching: bool = False        # -o
    fixed_strings: bool = False        # -F
    word_regexp: bool = False          # -w
    line_regexp: bool = False          # -x
    recursive: bool = False            # -r / -R
    max_count: int = 0                 # -m N  (0 = unlimited)
    after_context: int = 0             # -A N
    before_context: int = 0            # -B N
    quiet: bool = False                # -q
    show_filename: bool | None = None  # -H (True), -h (False), None=auto
    include_globs: list[str] = field(default_factory=list)   # --include=GLOB
    exclude_globs: list[str] = field(default_factory=list)   # --exclude=GLOB
    patterns: list[str] = field(default_factory=list)        # -e PAT (accumulates)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

_USAGE = """\
Usage: grep [OPTIONS] PATTERN [FILE ...]
       grep [OPTIONS] -e PATTERN [-e PATTERN ...] [FILE ...]

Search for PATTERN in each FILE (or recursively with -r).

Options:
  -i              ignore case distinctions in patterns and data
  -v              select non-matching lines
  -n              prefix each line of output with the line number
  -c              print only a count of matching lines per file
  -l              print only names of files with matches
  -L              print only names of files with no matches
  -o              show only the matched (non-empty) parts of a line
  -F              interpret PATTERN as a fixed string, not a regex
  -w              match only whole words
  -x              match only whole lines
  -r, -R          recursively search directories
  -m N            stop after N matches per file
  -A N            print N lines of trailing context
  -B N            print N lines of leading context
  -C N            print N lines of leading and trailing context
  -q              quiet; do not write anything to standard output
  -H              always print filename headers with output lines
  -h              suppress the prefixing of filenames on output
  -e PATTERN      use PATTERN for matching (may be repeated)
  --include=GLOB  search only files matching GLOB
  --exclude=GLOB  skip files matching GLOB"""


def _parse_args(args: tuple[str, ...]) -> tuple[GrepOptions, list[str]]:
    """Parse *args into (GrepOptions, positional_args).

    Raises ValueError with a message on bad input.
    """
    opts = GrepOptions()
    positional: list[str] = []
    it = iter(args)

    for tok in it:
        # Long options --include=GLOB / --exclude=GLOB
        if tok.startswith("--include="):
            opts.include_globs.append(tok[len("--include="):])
            continue
        if tok.startswith("--exclude="):
            opts.exclude_globs.append(tok[len("--exclude="):])
            continue

        # Short flags / flag+value
        if tok.startswith("-") and tok != "-" and not tok.startswith("--"):
            i = 1
            while i < len(tok):
                ch = tok[i]
                if ch == "i":
                    opts.ignore_case = True
                elif ch == "v":
                    opts.invert_match = True
                elif ch == "n":
                    opts.line_number = True
                elif ch == "c":
                    opts.count = True
                elif ch == "l":
                    opts.files_with_matches = True
                elif ch == "L":
                    opts.files_without_match = True
                elif ch == "o":
                    opts.only_matching = True
                elif ch == "F":
                    opts.fixed_strings = True
                elif ch == "w":
                    opts.word_regexp = True
                elif ch == "x":
                    opts.line_regexp = True
                elif ch in ("r", "R"):
                    opts.recursive = True
                elif ch == "q":
                    opts.quiet = True
                elif ch == "H":
                    opts.show_filename = True
                elif ch == "h":
                    opts.show_filename = False
                elif ch in ("m", "A", "B", "C", "e"):
                    # These consume the next value — either the remainder of
                    # the current token or the next token.
                    rest = tok[i + 1:]
                    val = rest if rest else next(it, None)
                    if val is None:
                        raise ValueError(f"Option -{ch} requires an argument")
                    if ch == "e":
                        opts.patterns.append(val)
                    elif ch == "m":
                        opts.max_count = int(val)
                    elif ch == "A":
                        opts.after_context = int(val)
                    elif ch == "B":
                        opts.before_context = int(val)
                    elif ch == "C":
                        opts.after_context = int(val)
                        opts.before_context = int(val)
                    break  # consumed rest of token
                else:
                    raise ValueError(f"Unknown option: -{ch}")
                i += 1
            continue

        # Everything else is positional
        positional.append(tok)

    return opts, positional


# ---------------------------------------------------------------------------
# Pattern compilation
# ---------------------------------------------------------------------------

def _compile_pattern(opts: GrepOptions) -> re.Pattern:
    """Compile the search pattern(s) into a single ``re.Pattern``."""
    parts = list(opts.patterns)  # may be empty if pattern is positional
    if not parts:
        raise ValueError("No pattern supplied")

    processed: list[str] = []
    for p in parts:
        if opts.fixed_strings:
            p = re.escape(p)
        if opts.word_regexp:
            p = r"\b" + p + r"\b"
        if opts.line_regexp:
            p = r"^" + p + r"$"
        processed.append(p)

    combined = "|".join(f"(?:{p})" for p in processed) if len(processed) > 1 else processed[0]

    flags = 0
    if opts.ignore_case:
        flags |= re.IGNORECASE
    return re.compile(combined, flags)


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def _collect_files_recursive(vault, path: str) -> list[str]:
    """Return all file vault-paths under *path*, sorted."""
    if path == "/" or path == "":
        search_prefix = ""
    else:
        search_prefix = path.lstrip("/")

    files = vault.list(prefix=search_prefix)
    prefix = (search_prefix + "/") if search_prefix else ""

    result = []
    for fp in files:
        fp = fp.lstrip("/")
        if prefix and not fp.startswith(prefix):
            continue
        result.append(fp)
    return sorted(result)


def _matches_glob(filepath: str, globs: list[str]) -> bool:
    """Return True if *filepath* matches any of the given globs.

    Matching is performed against the basename only (like grep --include).
    """
    basename = filepath.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(basename, g) for g in globs)


def _filter_files(files: list[str], opts: GrepOptions) -> list[str]:
    """Apply --include and --exclude glob filters."""
    if opts.include_globs:
        files = [f for f in files if _matches_glob(f, opts.include_globs)]
    if opts.exclude_globs:
        files = [f for f in files if not _matches_glob(f, opts.exclude_globs)]
    return files


# ---------------------------------------------------------------------------
# Binary detection
# ---------------------------------------------------------------------------

_TEXT_CHARS = (
    set(range(32, 127))
    | {9, 10, 13}  # tab, newline, carriage-return
)


def _is_binary(data: bytes, sample_size: int = 4096) -> bool:
    """Heuristic: file is binary if the first *sample_size* bytes contain NUL."""
    sample = data[:sample_size]
    return b"\x00" in sample


# ---------------------------------------------------------------------------
# Core matching engine
# ---------------------------------------------------------------------------

def _grep_files(
    vault,
    pattern_str: str,
    files: list[str],
    *,
    ignore_case: bool = False,
    fixed_strings: bool = False,
    word_regexp: bool = False,
    line_regexp: bool = False,
    invert_match: bool = False,
    max_count: int = 0,
) -> list[tuple[str, int, str]]:
    """Search *files* for *pattern_str* and return matches.

    This is the primary helper used by ``system/tools.py``.

    Returns a list of ``(filepath, line_number, line_text)`` tuples.
    Line numbers are 1-based.
    """
    opts = GrepOptions(
        ignore_case=ignore_case,
        fixed_strings=fixed_strings,
        word_regexp=word_regexp,
        line_regexp=line_regexp,
        invert_match=invert_match,
        max_count=max_count,
    )
    opts.patterns = [pattern_str]
    regex = _compile_pattern(opts)

    results: list[tuple[str, int, str]] = []
    for fp in files:
        try:
            data = vault.read(fp)
        except (FileNotFoundError, PermissionError):
            continue
        if _is_binary(data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

        hit_count = 0
        for lineno, line in enumerate(text.splitlines(), 1):
            matched = bool(regex.search(line))
            if invert_match:
                matched = not matched
            if matched:
                results.append((fp, lineno, line))
                hit_count += 1
                if max_count and hit_count >= max_count:
                    break
    return results


# ---------------------------------------------------------------------------
# Full grep engine (used by ``run``)
# ---------------------------------------------------------------------------

@dataclass
class _MatchLine:
    """A single output line produced by the grep engine."""
    filepath: str
    lineno: int          # 1-based
    text: str
    is_match: bool       # True for match, False for context
    match_spans: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class _FileResult:
    """All results for one file."""
    filepath: str
    match_count: int = 0
    lines: list[_MatchLine] = field(default_factory=list)
    is_binary: bool = False


def _search_file(
    vault,
    filepath: str,
    regex: re.Pattern,
    opts: GrepOptions,
) -> _FileResult:
    """Search a single file and return structured results."""
    result = _FileResult(filepath=filepath)

    try:
        data = vault.read(filepath)
    except (FileNotFoundError, PermissionError):
        return result

    if _is_binary(data):
        # Still check for a match so we can print the "Binary file matches" notice
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return result
        result.is_binary = True
        for line in text.splitlines():
            matched = bool(regex.search(line))
            if opts.invert_match:
                matched = not matched
            if matched:
                result.match_count += 1
                break  # one is enough for the notice
        return result

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        result.is_binary = True
        return result

    all_lines = text.splitlines()
    total = len(all_lines)
    if total == 0:
        return result

    # Determine which lines are matches
    match_indices: list[int] = []  # 0-based indices of matching lines
    match_spans_by_idx: dict[int, list[tuple[int, int]]] = {}

    for idx, line in enumerate(all_lines):
        spans = list(regex.finditer(line))
        matched = bool(spans)
        if opts.invert_match:
            matched = not matched
            spans = []
        if matched:
            match_indices.append(idx)
            match_spans_by_idx[idx] = [(m.start(), m.end()) for m in spans]
            if opts.max_count and len(match_indices) >= opts.max_count:
                break

    result.match_count = len(match_indices)
    if result.match_count == 0:
        return result

    # Determine which lines to include (matches + context)
    has_context = opts.before_context > 0 or opts.after_context > 0
    include_set: set[int] = set()

    for midx in match_indices:
        include_set.add(midx)
        if opts.before_context:
            for b in range(max(0, midx - opts.before_context), midx):
                include_set.add(b)
        if opts.after_context:
            for a in range(midx + 1, min(total, midx + opts.after_context + 1)):
                include_set.add(a)

    # Build ordered output lines, inserting group separators
    prev_idx = -2
    for idx in sorted(include_set):
        # Insert a separator marker when there is a gap
        if has_context and prev_idx >= 0 and idx > prev_idx + 1:
            result.lines.append(_MatchLine(
                filepath=filepath, lineno=0, text="--",
                is_match=False,
            ))
        is_match = idx in match_spans_by_idx or (opts.invert_match and idx in set(match_indices))
        result.lines.append(_MatchLine(
            filepath=filepath,
            lineno=idx + 1,
            text=all_lines[idx],
            is_match=(idx in set(match_indices)),
            match_spans=match_spans_by_idx.get(idx, []),
        ))
        prev_idx = idx

    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_results(
    file_results: list[_FileResult],
    opts: GrepOptions,
    display_paths: dict[str, str],
) -> list[str]:
    """Format *file_results* into printable lines.

    *display_paths* maps vault-path → display-path (as the user typed it).
    """
    if opts.quiet:
        return []

    # Decide whether to show filenames
    multi = len(file_results) > 1
    if opts.show_filename is True:
        show_fn = True
    elif opts.show_filename is False:
        show_fn = False
    else:
        # Recursive mode always shows filenames (like real grep)
        show_fn = multi or opts.recursive

    output: list[str] = []

    for fr in file_results:
        dp = display_paths.get(fr.filepath, fr.filepath)

        # -l  list files with matches
        if opts.files_with_matches:
            if fr.match_count > 0:
                output.append(dp)
            continue

        # -L  list files without matches
        if opts.files_without_match:
            if fr.match_count == 0:
                output.append(dp)
            continue

        # -c  count
        if opts.count:
            if show_fn:
                output.append(f"{dp}:{fr.match_count}")
            else:
                output.append(str(fr.match_count))
            continue

        # Binary file notice
        if fr.is_binary:
            if fr.match_count > 0:
                output.append(f"Binary file {dp} matches")
            continue

        # Normal / context / only-matching output
        for ml in fr.lines:
            # Group separator
            if ml.lineno == 0 and ml.text == "--":
                output.append("--")
                continue

            prefix = ""
            if show_fn:
                sep = ":" if ml.is_match else "-"
                prefix = f"{dp}{sep}"

            if opts.line_number:
                sep = ":" if ml.is_match else "-"
                prefix += f"{ml.lineno}{sep}"

            if opts.only_matching and ml.is_match:
                # Print each match span on its own line
                for start, end in ml.match_spans:
                    output.append(prefix + ml.text[start:end])
            else:
                output.append(prefix + ml.text)

    return output


# ---------------------------------------------------------------------------
# Async command entry point
# ---------------------------------------------------------------------------

async def run(*args):
    """Search file contents for lines matching a pattern."""
    from system.context import SystemContext, cprint

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if not args:
        cprint(_USAGE)
        return

    try:
        opts, positional = _parse_args(args)
    except ValueError as exc:
        cprint(f"grep: {exc}")
        return

    # If no -e patterns were given, the first positional arg is the pattern
    if not opts.patterns:
        if not positional:
            cprint(_USAGE)
            return
        opts.patterns.append(positional.pop(0))

    try:
        regex = _compile_pattern(opts)
    except re.error as exc:
        cprint(f"grep: invalid pattern: {exc}")
        return

    vault = ctx.fs()

    # Collect files to search
    file_args = positional if positional else None
    vault_files: list[str] = []          # vault paths
    display_paths: dict[str, str] = {}   # vault_path → user-facing path

    if file_args:
        for farg in file_args:
            abs_path, vault_path = resolve_path(farg, ctx.cwd)
            if not vault.exists(vault_path) and not vault.is_dir(vault_path):
                cprint(f"grep: {farg}: No such file or directory")
                continue
            if vault.is_dir(vault_path):
                if not opts.recursive:
                    cprint(f"grep: {farg}: Is a directory")
                    continue
                children = _collect_files_recursive(vault, abs_path)
                children = _filter_files(children, opts)
                for child in children:
                    vault_files.append(child)
                    # Build display path relative to the argument
                    vp_prefix = (vault_path + "/") if vault_path else ""
                    rel = child[len(vp_prefix):] if vp_prefix and child.startswith(vp_prefix) else child
                    dp = (farg.rstrip("/") + "/" + rel) if farg.rstrip("/") else rel
                    display_paths[child] = dp
            else:
                vault_files.append(vault_path)
                display_paths[vault_path] = farg
    elif opts.recursive:
        # No file args + -r → search from cwd
        vault_files = _collect_files_recursive(vault, ctx.cwd)
        vault_files = _filter_files(vault_files, opts)
        cwd_clean = ctx.cwd.lstrip("/")
        cwd_prefix = (cwd_clean + "/") if cwd_clean else ""
        for vf in vault_files:
            rel = vf[len(cwd_prefix):] if cwd_prefix and vf.startswith(cwd_prefix) else vf
            display_paths[vf] = "./" + rel
    else:
        cprint(_USAGE)
        return

    # Search each file
    results: list[_FileResult] = []
    for vf in vault_files:
        fr = _search_file(vault, vf, regex, opts)
        results.append(fr)

    # Format & print
    lines = _format_results(results, opts, display_paths)
    for line in lines:
        cprint(line)
