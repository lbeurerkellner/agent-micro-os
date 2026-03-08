"""Tests for tool dependency parsing and persistent image caching."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from system.execute import _parse_tool_deps
from bin.sandbox import _tool_image_tag


class TestParseToolDeps:
    """Tests for parsing # pip: and # npm: declarations from tool scripts."""

    def test_no_deps(self):
        script = "import sys\nprint('hello')\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == []
        assert npm == []

    def test_single_pip_dep(self):
        script = "# pip: requests\nimport requests\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests"]
        assert npm == []

    def test_multiple_pip_deps_on_one_line(self):
        script = "# pip: requests numpy pandas\nimport requests\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests", "numpy", "pandas"]

    def test_multiple_pip_lines(self):
        script = "# pip: requests\n# pip: numpy\nimport requests\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests", "numpy"]

    def test_npm_dep(self):
        script = "# npm: typescript\nimport subprocess\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == []
        assert npm == ["typescript"]

    def test_mixed_pip_and_npm(self):
        script = "# pip: requests\n# npm: typescript prettier\nimport requests\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests"]
        assert npm == ["typescript", "prettier"]

    def test_stops_at_non_comment_line(self):
        # A pip: comment after real code should NOT be picked up
        script = "import sys\n# pip: requests\nprint('hello')\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == []

    def test_blank_lines_in_header_continue_scanning(self):
        # Blank lines between comments are allowed in the header
        script = "# pip: requests\n\n# pip: numpy\nimport requests\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests", "numpy"]

    def test_version_specifiers_preserved(self):
        script = "# pip: requests>=2.28.0 numpy==1.24.0\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests>=2.28.0", "numpy==1.24.0"]

    def test_ignores_other_comments(self):
        script = "# This is a regular comment\n# pip: requests\nimport requests\n"
        pip, npm = _parse_tool_deps(script)
        assert pip == ["requests"]

    def test_empty_script(self):
        pip, npm = _parse_tool_deps("")
        assert pip == []
        assert npm == []


class TestToolImageTag:
    """Tests for deterministic image tag generation."""

    def test_no_deps_returns_base_image(self):
        # When called with empty deps the caller should use base image directly,
        # but the tag function itself still generates a tag — verify it's stable.
        tag1 = _tool_image_tag([], [], "python:3.12")
        tag2 = _tool_image_tag([], [], "python:3.12")
        assert tag1 == tag2

    def test_same_deps_same_tag(self):
        tag1 = _tool_image_tag(["requests", "numpy"], [], "python:3.12")
        tag2 = _tool_image_tag(["requests", "numpy"], [], "python:3.12")
        assert tag1 == tag2

    def test_order_insensitive(self):
        tag1 = _tool_image_tag(["numpy", "requests"], [], "python:3.12")
        tag2 = _tool_image_tag(["requests", "numpy"], [], "python:3.12")
        assert tag1 == tag2

    def test_different_deps_different_tag(self):
        tag1 = _tool_image_tag(["requests"], [], "python:3.12")
        tag2 = _tool_image_tag(["numpy"], [], "python:3.12")
        assert tag1 != tag2

    def test_different_base_image_different_tag(self):
        tag1 = _tool_image_tag(["requests"], [], "python:3.12")
        tag2 = _tool_image_tag(["requests"], [], "python:3.11")
        assert tag1 != tag2

    def test_tag_format(self):
        tag = _tool_image_tag(["requests"], [], "python:3.12")
        assert tag.startswith("agentvault-tool-")
        # Should only contain safe characters for a Docker tag
        suffix = tag[len("agentvault-tool-"):]
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_npm_deps_affect_tag(self):
        tag1 = _tool_image_tag(["requests"], [], "python:3.12")
        tag2 = _tool_image_tag(["requests"], ["typescript"], "python:3.12")
        assert tag1 != tag2


class TestEnsureToolImage:
    """Tests for _ensure_tool_image image build/cache logic."""

    @pytest.mark.asyncio
    async def test_no_deps_returns_base_image(self):
        from bin.sandbox import _ensure_tool_image

        result = await _ensure_tool_image([], [], base_image="python:3.12", quiet=True)
        assert result == "python:3.12"

    @pytest.mark.asyncio
    async def test_existing_image_not_rebuilt(self):
        from bin.sandbox import _ensure_tool_image

        mock_client = MagicMock()
        mock_client.images.get.return_value = MagicMock()  # image found

        with patch("docker.from_env", return_value=mock_client):
            result = await _ensure_tool_image(["requests"], [], quiet=True)

        # Should not attempt to build
        mock_client.images.get.assert_called_once()
        assert result.startswith("agentvault-tool-")

    @pytest.mark.asyncio
    async def test_missing_image_triggers_build(self):
        import docker
        from bin.sandbox import _ensure_tool_image

        mock_client = MagicMock()
        mock_client.images.get.side_effect = docker.errors.ImageNotFound("not found")

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("docker.from_env", return_value=mock_client):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
                result = await _ensure_tool_image(["requests"], [], quiet=True)

        assert result.startswith("agentvault-tool-")
        # docker build should have been called
        call_args = mock_exec.call_args[0]
        assert "docker" in call_args
        assert "build" in call_args

    @pytest.mark.asyncio
    async def test_dockerfile_contains_pip_install(self):
        """The generated Dockerfile must install the requested pip packages."""
        import docker
        from bin.sandbox import _ensure_tool_image

        captured_dockerfile = {}

        mock_client = MagicMock()
        mock_client.images.get.side_effect = docker.errors.ImageNotFound("not found")

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        original_open = open

        def fake_open(path, *a, **kw):
            if "Dockerfile" in str(path) and "w" in (a[0] if a else kw.get("mode", "r")):
                import io

                class CapturingFile:
                    def __init__(self):
                        self.content = ""

                    def write(self, data):
                        self.content += data

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        captured_dockerfile["content"] = self.content

                return CapturingFile()
            return original_open(path, *a, **kw)

        with patch("docker.from_env", return_value=mock_client):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                with patch("builtins.open", side_effect=fake_open):
                    await _ensure_tool_image(["requests", "numpy"], [], quiet=True)

        dockerfile = captured_dockerfile.get("content", "")
        assert "pip install" in dockerfile
        assert "requests" in dockerfile
        assert "numpy" in dockerfile

    @pytest.mark.asyncio
    async def test_dockerfile_contains_npm_install(self):
        """The generated Dockerfile must install npm packages when requested."""
        import docker
        from bin.sandbox import _ensure_tool_image

        captured_dockerfile = {}

        mock_client = MagicMock()
        mock_client.images.get.side_effect = docker.errors.ImageNotFound("not found")

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        original_open = open

        def fake_open(path, *a, **kw):
            if "Dockerfile" in str(path) and "w" in (a[0] if a else kw.get("mode", "r")):
                class CapturingFile:
                    def __init__(self):
                        self.content = ""

                    def write(self, data):
                        self.content += data

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        captured_dockerfile["content"] = self.content

                return CapturingFile()
            return original_open(path, *a, **kw)

        with patch("docker.from_env", return_value=mock_client):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                with patch("builtins.open", side_effect=fake_open):
                    await _ensure_tool_image([], ["typescript"], quiet=True)

        dockerfile = captured_dockerfile.get("content", "")
        assert "npm" in dockerfile
        assert "typescript" in dockerfile
