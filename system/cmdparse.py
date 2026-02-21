"""Shell command parser for ash.

Tokenizes and parses command lines with support for:
- Quoted strings (single and double quotes with escapes)
- Command chaining: &&
- Output redirection: > and >>
- Background execution: &
"""

from dataclasses import dataclass, field


@dataclass
class Redirect:
    """Output redirection target."""
    target: str
    append: bool = False


@dataclass
class ShellCommand:
    """A single parsed command with its arguments and modifiers."""
    args: list[str] = field(default_factory=list)
    stdout: Redirect | None = None
    background: bool = False


# Operator token sentinels
_OP_AND = "&&"
_OP_GT = ">"
_OP_APPEND = ">>"
_OP_BG = "&"
_OPERATORS = {_OP_AND, _OP_GT, _OP_APPEND, _OP_BG}


def _tokenize(cmd: str) -> list[str]:
    """Tokenize a command string into words and operator tokens.

    Words follow bash-like quoting rules:
    - Single quotes: preserve everything literally (no escapes)
    - Double quotes: allow escapes (\\", \\\\, \\n, \\t, etc.)
    - Backslash outside quotes: escape next character

    Operators (&&, >>, >, &) are emitted as distinct tokens.
    Operators inside quotes are treated as regular text.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    escaped = False

    def flush():
        if current:
            tokens.append("".join(current))
            current.clear()

    i = 0
    while i < len(cmd):
        char = cmd[i]

        if escaped:
            if in_double_quote:
                escape_map = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "$": "$"}
                if char in escape_map:
                    current.append(escape_map[char])
                else:
                    current.append("\\")
                    current.append(char)
            else:
                current.append(char)
            escaped = False
            i += 1
            continue

        if char == "\\" and not in_single_quote:
            escaped = True
            i += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
            continue

        # Inside quotes — everything is literal
        if in_single_quote or in_double_quote:
            current.append(char)
            i += 1
            continue

        # Outside quotes — check for operators
        if char == ">" and i + 1 < len(cmd) and cmd[i + 1] == ">":
            flush()
            tokens.append(_OP_APPEND)
            i += 2
            continue

        if char == ">":
            flush()
            tokens.append(_OP_GT)
            i += 1
            continue

        if char == "&" and i + 1 < len(cmd) and cmd[i + 1] == "&":
            flush()
            tokens.append(_OP_AND)
            i += 2
            continue

        if char == "&":
            flush()
            tokens.append(_OP_BG)
            i += 1
            continue

        if char in (" ", "\t", "\n", "\r"):
            flush()
            i += 1
            continue

        current.append(char)
        i += 1

    flush()
    return tokens


def cmdparse(line: str) -> list[tuple[ShellCommand, str | None]]:
    """Parse a command line into a list of (ShellCommand, connector) pairs.

    The connector is '&&' between chained commands or None for the last command.

    Examples:
        "echo hello"
          -> [(ShellCommand(args=['echo','hello']), None)]

        "echo hello > out.txt && cat out.txt"
          -> [(ShellCommand(args=['echo','hello'], stdout=Redirect('out.txt')), '&&'),
              (ShellCommand(args=['cat','out.txt']), None)]

        "sleep 10 &"
          -> [(ShellCommand(args=['sleep','10'], background=True), None)]
    """
    tokens = _tokenize(line)
    if not tokens:
        return []

    result: list[tuple[ShellCommand, str | None]] = []
    cmd = ShellCommand()
    i = 0

    while i < len(tokens):
        tok = tokens[i]

        if tok == _OP_AND:
            # Finalize current command, link with &&
            if cmd.args:
                result.append((cmd, "&&"))
                cmd = ShellCommand()
            i += 1
            continue

        if tok == _OP_BG:
            cmd.background = True
            i += 1
            continue

        if tok in (_OP_GT, _OP_APPEND):
            # Next token is the redirect target
            if i + 1 < len(tokens) and tokens[i + 1] not in _OPERATORS:
                cmd.stdout = Redirect(target=tokens[i + 1], append=(tok == _OP_APPEND))
                i += 2
            else:
                # Syntax error — treat > as literal
                cmd.args.append(tok)
                i += 1
            continue

        cmd.args.append(tok)
        i += 1

    if cmd.args or cmd.stdout or cmd.background:
        result.append((cmd, None))

    return result
