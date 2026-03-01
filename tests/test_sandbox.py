"""Tests for sandbox export/import utilities."""

import io
import tarfile

from fs.vault import Vault
from bin.sandbox import _export_to_tar, _TOOL_SHEBANG_SETUP


class TestExportToTar:
    """Tests for _export_to_tar."""

    def test_tool_shebang_files_are_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("bin/mytool", b"#!/bin/tool my description\nprint('hello')\n")
        vault.write("bin/regular", b"#!/bin/ash\necho hello\n")

        buf, snapshot = _export_to_tar(vault, "")

        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r") as tar:
            tool_member = tar.getmember("bin/mytool")
            regular_member = tar.getmember("bin/regular")

        assert tool_member.mode == 0o755
        assert regular_member.mode == 0o600

    def test_sbin_tool_shebang_is_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("bin/mytool", b"#!/sbin/tool\nimport sys\n")

        buf, snapshot = _export_to_tar(vault, "")

        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r") as tar:
            member = tar.getmember("bin/mytool")

        assert member.mode == 0o755

    def test_non_tool_file_not_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("data.txt", b"just some text\n")

        buf, snapshot = _export_to_tar(vault, "")

        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r") as tar:
            member = tar.getmember("data.txt")

        assert member.mode == 0o600


class TestToolShebangSetup:
    """Tests for the /bin/tool injection command."""

    def test_setup_creates_bin_tool(self):
        # The setup command should create /bin/tool and make it executable
        assert "/bin/tool" in _TOOL_SHEBANG_SETUP
        assert "chmod +x" in _TOOL_SHEBANG_SETUP
        assert "python3" in _TOOL_SHEBANG_SETUP
