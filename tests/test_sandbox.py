"""Tests for sandbox export/import utilities."""

import os
import stat
import tempfile

from fs.vault import Vault
from bin.sandbox import _build_snapshot, _export_to_dir, _TOOL_SHEBANG_SETUP


class TestExportToDir:
    """Tests for _build_snapshot + _export_to_dir file permissions."""

    def test_tool_shebang_files_are_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("bin/mytool", b"#!/bin/tool my description\nprint('hello')\n")
        vault.write("bin/regular", b"#!/bin/ash\necho hello\n")

        snapshot = {"bin/mytool": vault.read("bin/mytool"),
                    "bin/regular": vault.read("bin/regular")}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            tool_mode = os.stat(os.path.join(tmpdir, "bin/mytool")).st_mode
            regular_mode = os.stat(os.path.join(tmpdir, "bin/regular")).st_mode

        assert tool_mode & 0o755 == 0o755
        assert regular_mode & 0o600 == 0o600
        assert not regular_mode & stat.S_IXUSR

    def test_sbin_tool_shebang_is_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("bin/mytool", b"#!/sbin/tool\nimport sys\n")

        snapshot = {"bin/mytool": vault.read("bin/mytool")}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            mode = os.stat(os.path.join(tmpdir, "bin/mytool")).st_mode

        assert mode & 0o755 == 0o755

    def test_non_tool_file_not_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("data.txt", b"just some text\n")

        snapshot = {"data.txt": vault.read("data.txt")}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            mode = os.stat(os.path.join(tmpdir, "data.txt")).st_mode

        assert mode & 0o600 == 0o600
        assert not mode & stat.S_IXUSR


class TestToolShebangSetup:
    """Tests for the /bin/tool injection command."""

    def test_setup_creates_bin_tool(self):
        # The setup command should create /bin/tool and make it executable
        assert "/bin/tool" in _TOOL_SHEBANG_SETUP
        assert "chmod +x" in _TOOL_SHEBANG_SETUP
        assert "python3" in _TOOL_SHEBANG_SETUP
