"""Tests for the streaming terminal markdown renderer."""
import pytest
from system.terminal_markdown import TerminalMarkdown

BOLD = "\033[1m"
NO_BOLD = "\033[22m"
DIM = "\033[2m"
NO_DIM = "\033[22m"
CYAN = "\033[36m"
UNDERLINE = "\033[4m"
RESET = "\033[0m"


def render(text, chunk_size=None):
    """Helper: feed text through renderer and return ANSI output."""
    out = []
    md = TerminalMarkdown(lambda t: out.append(t))
    if chunk_size is None:
        md.feed(text)
    else:
        for i in range(0, len(text), chunk_size):
            md.feed(text[i:i + chunk_size])
    md.end()
    return "".join(out)


class TestPlainText:
    def test_plain_text_passthrough(self):
        assert render("hello world") == "hello world"

    def test_multiline_plain(self):
        assert render("line one\nline two\n") == "line one\nline two\n"


class TestBold:
    def test_bold_word(self):
        result = render("**bold**")
        assert result == f"{BOLD}bold{NO_BOLD}"

    def test_bold_in_sentence(self):
        result = render("hello **world** foo")
        assert result == f"hello {BOLD}world{NO_BOLD} foo"

    def test_single_star_literal(self):
        result = render("a * b")
        assert result == "a * b"

    def test_bold_streaming_char_by_char(self):
        result = render("**hi**", chunk_size=1)
        assert result == f"{BOLD}hi{NO_BOLD}"


class TestInlineCode:
    def test_inline_code(self):
        result = render("use `foo()` here")
        assert result == f"use {CYAN}foo(){RESET} here"

    def test_inline_code_streaming(self):
        result = render("run `cmd`", chunk_size=1)
        assert result == f"run {CYAN}cmd{RESET}"

    def test_bold_inside_code_ignored(self):
        """Stars inside inline code should be literal."""
        result = render("`**not bold**`")
        assert result == f"{CYAN}**not bold**{RESET}"


class TestCodeBlock:
    def test_code_block(self):
        text = "before\n```\ncode here\n```\nafter\n"
        result = render(text)
        assert DIM in result
        assert "code here\n" in result
        assert NO_DIM in result
        # "before" and "after" should not be dimmed
        before_dim = result.index(DIM)
        assert result.index("before") < before_dim

    def test_code_block_with_language(self):
        text = "```python\nprint('hi')\n```\n"
        result = render(text)
        assert DIM in result
        assert "print('hi')\n" in result
        assert NO_DIM in result

    def test_code_block_no_markdown_inside(self):
        """Bold markers inside code blocks should be literal."""
        text = "```\n**not bold**\n```\n"
        result = render(text)
        assert BOLD not in result
        assert "**not bold**" in result

    def test_code_block_streaming(self):
        text = "```\nfoo\n```\n"
        result = render(text, chunk_size=1)
        assert DIM in result
        assert "foo\n" in result


class TestHeadings:
    def test_h1(self):
        result = render("# Title\n")
        assert result == f"{BOLD}{UNDERLINE}Title{RESET}\n"

    def test_h2(self):
        result = render("## Subtitle\n")
        assert result == f"{BOLD}{UNDERLINE}Subtitle{RESET}\n"

    def test_heading_streaming(self):
        result = render("# Hello\n", chunk_size=1)
        assert result == f"{BOLD}{UNDERLINE}Hello{RESET}\n"

    def test_heading_not_in_middle_of_line(self):
        """# only triggers heading at start of line."""
        result = render("foo # bar\n")
        assert UNDERLINE not in result
        assert "foo # bar" in result


class TestListItems:
    def test_dash_list(self):
        result = render("- item one\n- item two\n")
        assert "  • item one" in result
        assert "  • item two" in result

    def test_dash_list_streaming(self):
        result = render("- hello\n", chunk_size=1)
        assert "  • hello" in result


class TestStreamingConsistency:
    """Verify that output is identical regardless of chunk boundaries."""

    @pytest.mark.parametrize("text", [
        "**bold** and `code`",
        "# Heading\nBody text\n",
        "- item\n- another\n",
        "```\nblock\n```\n",
        "mix **bold** and `code` and\n# heading\n",
    ])
    def test_chunk_sizes_match(self, text):
        full = render(text)
        for size in [1, 2, 3, 5]:
            assert render(text, chunk_size=size) == full, f"Mismatch at chunk_size={size}"
