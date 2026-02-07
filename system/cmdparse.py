"""Bash-like command tokenizer for ash shell.

Handles quoted strings and escape sequences similar to bash.
"""


def cmdparse(cmd: str) -> list[str]:
    """Tokenize a command string, handling quotes and escapes like bash.

    Rules:
    - Single quotes: preserve everything literally (no escapes)
    - Double quotes: allow escapes (\", \\, \n, \t, etc.)
    - Backslash outside quotes: escape next character
    - Whitespace outside quotes: token separator

    Examples:
        'echo hello world' -> ['echo', 'hello', 'world']
        'echo "hello world"' -> ['echo', 'hello world']
        "echo 'hello world'" -> ['echo', 'hello world']
        'echo "say \\"hi\\""' -> ['echo', 'say "hi"']
        'echo hello\\ world' -> ['echo', 'hello world']
    """
    tokens = []
    current_token = []
    in_single_quote = False
    in_double_quote = False
    escaped = False

    i = 0
    while i < len(cmd):
        char = cmd[i]

        if escaped:
            # Process escape sequence
            if in_double_quote:
                # In double quotes, handle common escapes
                if char == 'n':
                    current_token.append('\n')
                elif char == 't':
                    current_token.append('\t')
                elif char == 'r':
                    current_token.append('\r')
                elif char == '\\':
                    current_token.append('\\')
                elif char == '"':
                    current_token.append('"')
                elif char == '$':
                    current_token.append('$')
                else:
                    # Unknown escape, keep backslash and char
                    current_token.append('\\')
                    current_token.append(char)
            else:
                # Outside quotes or in single quotes, escape next char literally
                current_token.append(char)
            escaped = False
            i += 1
            continue

        if char == '\\':
            if in_single_quote:
                # Backslash is literal in single quotes
                current_token.append(char)
            else:
                # Start escape sequence
                escaped = True
            i += 1
            continue

        if char == "'" and not in_double_quote:
            # Toggle single quote mode
            in_single_quote = not in_single_quote
            i += 1
            continue

        if char == '"' and not in_single_quote:
            # Toggle double quote mode
            in_double_quote = not in_double_quote
            i += 1
            continue

        if char in (' ', '\t', '\n', '\r') and not in_single_quote and not in_double_quote:
            # Whitespace outside quotes - token separator
            if current_token:
                tokens.append(''.join(current_token))
                current_token = []
            i += 1
            continue

        # Regular character
        current_token.append(char)
        i += 1

    # Add final token if any
    if current_token:
        tokens.append(''.join(current_token))

    return tokens
