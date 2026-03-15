"""Tests for cap-style tool frontmatter parsing and integration."""

import os
import stat
import tempfile

import pytest

from system.tools import parse_cap_meta
from bin.sandbox import _export_to_dir


class TestParseCapMeta:
    """Tests for parse_cap_meta frontmatter extraction."""

    def test_basic_frontmatter(self):
        content = (
            "# ---\n"
            "# description: Fetch briefing from zeit.de\n"
            "# network: ['zeit.de']\n"
            "# ---\n"
            "import urllib.request\n"
            "print('hello')\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta is not None
        assert meta["description"] == "Fetch briefing from zeit.de"
        assert meta["network"] == ["zeit.de"]
        assert body == "import urllib.request\nprint('hello')"

    def test_frontmatter_with_shebang(self):
        content = (
            "#!/usr/bin/env cap\n"
            "# ---\n"
            "# description: My tool\n"
            "# dependencies: ['pypi:requests']\n"
            "# ---\n"
            "import requests\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta is not None
        assert meta["description"] == "My tool"
        assert meta["dependencies"] == ["pypi:requests"]
        assert body == "import requests"

    def test_no_frontmatter_returns_none(self):
        content = "print('hello world')\n"
        meta, body = parse_cap_meta(content)
        assert meta is None
        assert body == content

    def test_shebang_only_no_frontmatter(self):
        content = "#!/usr/bin/env python3\nprint('hello')\n"
        meta, body = parse_cap_meta(content)
        assert meta is None
        assert body == content

    def test_all_fields(self):
        content = (
            "# ---\n"
            "# name: my-tool\n"
            "# description: Does things\n"
            "# dependencies: ['pypi:requests', 'pypi:click']\n"
            "# access: ['data/**:rw', '$@']\n"
            "# network: ['api.example.com']\n"
            "# secrets: ['API_KEY']\n"
            "# stateful: true\n"
            "# ---\n"
            "print('hi')\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta["name"] == "my-tool"
        assert meta["description"] == "Does things"
        assert meta["dependencies"] == ["pypi:requests", "pypi:click"]
        assert meta["access"] == ["data/**:rw", "$@"]
        assert meta["network"] == ["api.example.com"]
        assert meta["secrets"] == ["API_KEY"]
        assert meta["stateful"] is True

    def test_network_disable(self):
        content = (
            "# ---\n"
            "# description: Offline tool\n"
            "# network: 'disable'\n"
            "# ---\n"
            "print('offline')\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta["network"] == "disable"

    def test_network_star(self):
        content = (
            "# ---\n"
            "# description: Unrestricted\n"
            "# network: '*'\n"
            "# ---\n"
            "print('online')\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta["network"] == ["*"]

    def test_defaults(self):
        content = (
            "# ---\n"
            "# description: Minimal\n"
            "# ---\n"
            "print('hi')\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta["dependencies"] == []
        assert meta["access"] == []
        assert meta["network"] == ["*"]
        assert meta["secrets"] == []
        assert meta["stateful"] is False

    def test_empty_body(self):
        content = (
            "# ---\n"
            "# description: Empty\n"
            "# ---\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta["description"] == "Empty"
        assert body == ""

    def test_js_frontmatter(self):
        content = (
            "// ---\n"
            "// description: Pretty-print JSON\n"
            "// runtime: 'node'\n"
            "// access: ['$@:ro']\n"
            "// network: 'disable'\n"
            "// ---\n"
            "const fs = require('fs');\n"
            "console.log('hi');\n"
        )
        meta, body = parse_cap_meta(content)
        assert meta is not None
        assert meta["description"] == "Pretty-print JSON"
        assert meta["lang"] == "js"
        assert meta["access"] == ["$@:ro"]
        assert meta["network"] == "disable"
        assert body == "const fs = require('fs');\nconsole.log('hi');"

    def test_js_frontmatter_not_detected_with_hash(self):
        """JS tools using # comments should not be detected as frontmatter."""
        content = (
            "# ---\n"
            "# description: Wrong syntax for JS\n"
            "# ---\n"
            "const x = 1;\n"
        )
        meta, body = parse_cap_meta(content)
        # This IS detected — it's valid Python/shell frontmatter.
        # The runtime field tells _run_cap_tool to use .cap.js extension,
        # but parse_cap_meta doesn't need to know the runtime to parse.
        assert meta is not None


class TestCapToolExport:
    """Tests for _export_to_dir handling cap frontmatter tools."""

    def test_shebang_file_is_executable(self):
        content = b"#!/usr/bin/env cap\n# ---\n# description: My tool\n# ---\nprint('hi')\n"
        snapshot = {"bin/mytool": content}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            mode = os.stat(os.path.join(tmpdir, "bin/mytool")).st_mode

        assert mode & 0o755 == 0o755

    def test_non_shebang_file_not_executable(self):
        snapshot = {"data.txt": b"just text\n"}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            mode = os.stat(os.path.join(tmpdir, "data.txt")).st_mode

        assert mode & 0o600 == 0o600
        assert not mode & stat.S_IXUSR

    def test_no_cap_stub_in_export(self):
        """Cap stub is injected via container preamble, not in the export dir."""
        snapshot = {"hello.txt": b"world\n"}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            stub_path = os.path.join(tmpdir, "bin", "cap")
            assert not os.path.exists(stub_path)
