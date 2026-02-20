"""Streaming markdown-to-ANSI terminal renderer.

Supports a practical subset of markdown for streaming token-by-token output:
  - **bold**        → ANSI bold
  - `inline code`   → cyan
  - ``` code blocks  → dim
  - # headings       → bold + underline (at line start)
  - - list items     → bullet character (at line start)
"""

BOLD = "\033[1m"
NO_BOLD = "\033[22m"
DIM = "\033[2m"
NO_DIM = "\033[22m"
CYAN = "\033[36m"
UNDERLINE = "\033[4m"
RESET = "\033[0m"


class TerminalMarkdown:
    """Feed arbitrary text chunks via feed(); ANSI-rendered output is emitted
    through the callable passed to __init__."""

    def __init__(self, emit):
        self._emit = emit
        self._bold = False
        self._code = False        # inline code span
        self._code_block = False  # fenced code block
        self._heading = False
        self._stars = 0           # buffered consecutive '*' count
        self._at_sol = True       # at start of line
        self._sol_buf = ""        # start-of-line buffer
        self._cb_line = ""        # current line inside a code block

    # -- public API --

    def feed(self, text: str):
        """Process an incoming text chunk (any size)."""
        for ch in text:
            self._char(ch)

    def end(self):
        """Flush remaining state and reset."""
        self._drain_stars()
        if self._sol_buf:
            buf = self._sol_buf
            self._sol_buf = ""
            self._at_sol = False
            for c in buf:
                self._inline(c)
        if self._cb_line:
            self._emit(self._cb_line)
            self._cb_line = ""
        if self._bold or self._code or self._code_block or self._heading:
            self._emit(RESET)
        self._bold = False
        self._code = False
        self._code_block = False
        self._heading = False

    # -- internal --

    def _drain_stars(self):
        if self._stars:
            self._emit("*" * self._stars)
            self._stars = 0

    def _char(self, ch):
        # Inside a fenced code block: buffer line-by-line, look for closing fence
        if self._code_block:
            if ch == "\n":
                if self._cb_line.strip() == "```":
                    self._emit(NO_DIM)
                    self._code_block = False
                    self._at_sol = True
                    self._sol_buf = ""
                else:
                    self._emit(self._cb_line + "\n")
                self._cb_line = ""
            else:
                self._cb_line += ch
            return

        # At start of line: buffer to detect headings / lists / code fences
        if self._at_sol:
            self._sol_buf += ch

            if ch == "\n":
                stripped = self._sol_buf.rstrip("\n").strip()
                if stripped.startswith("```"):
                    self._code_block = True
                    self._sol_buf = ""
                    self._at_sol = False
                    self._cb_line = ""
                    self._emit(DIM)
                else:
                    buf = self._sol_buf
                    self._sol_buf = ""
                    self._at_sol = False
                    for c in buf:
                        self._inline(c)
                return

            stripped = self._sol_buf.lstrip()

            # Could still be heading (###...)
            if all(c == "#" for c in stripped):
                return

            # Could still be code fence (``, ```)
            if all(c == "`" for c in stripped) and len(stripped) <= 3:
                return

            # Could still be list item (-)
            if stripped == "-":
                return

            # Heading confirmed: "# ", "## ", etc.
            if len(stripped) >= 2 and stripped[-1] == " " and all(c == "#" for c in stripped[:-1]):
                self._sol_buf = ""
                self._at_sol = False
                self._heading = True
                self._emit(BOLD + UNDERLINE)
                return

            # List item confirmed: "- "
            if stripped == "- ":
                self._sol_buf = ""
                self._at_sol = False
                self._emit("  \u2022 ")
                return

            # Code fence with language tag: "```python"
            if stripped.startswith("```") and len(stripped) > 3 and not all(c == "`" for c in stripped):
                self._code_block = True
                self._sol_buf = ""
                self._at_sol = False
                self._cb_line = ""
                self._emit(DIM)
                return

            # Not a special line-start construct — flush buffer as inline text
            buf = self._sol_buf
            self._sol_buf = ""
            self._at_sol = False
            for c in buf:
                self._inline(c)
            return

        self._inline(ch)

    def _inline(self, ch):
        if ch == "\n":
            self._drain_stars()
            if self._heading:
                self._emit(RESET)
                self._heading = False
            self._emit("\n")
            self._at_sol = True
            self._sol_buf = ""
            return

        # Backtick: toggle inline code
        if ch == "`":
            self._drain_stars()
            if self._code:
                self._code = False
                self._emit(RESET)
                # Restore active styles
                if self._bold:
                    self._emit(BOLD)
                if self._heading:
                    self._emit(BOLD + UNDERLINE)
            else:
                self._code = True
                self._emit(CYAN)
            return

        # Inside inline code: emit literally
        if self._code:
            self._emit(ch)
            return

        # Star: buffer for bold detection
        if ch == "*":
            self._stars += 1
            if self._stars == 2:
                self._stars = 0
                self._bold = not self._bold
                self._emit(BOLD if self._bold else NO_BOLD)
            return

        self._drain_stars()
        self._emit(ch)
