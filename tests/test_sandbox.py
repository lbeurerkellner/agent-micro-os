"""Tests for sandbox export/import utilities."""

import os
import stat
import tempfile

from fs.vault import Vault
from bin.sandbox import _build_snapshot, _export_to_dir


class TestExportToDir:
    """Tests for _build_snapshot + _export_to_dir file permissions."""

    def test_shebang_files_are_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("bin/captool", b"#!/usr/bin/env cap\n# ---\n# description: my tool\n# ---\nprint('hello')\n")
        vault.write("bin/ashtool", b"#!/bin/ash\necho hello\n")
        vault.write("bin/no_shebang", b"# ---\n# description: no shebang\n# ---\nprint('hi')\n")

        snapshot = {"bin/captool": vault.read("bin/captool"),
                    "bin/ashtool": vault.read("bin/ashtool"),
                    "bin/no_shebang": vault.read("bin/no_shebang")}

        with tempfile.TemporaryDirectory() as tmpdir:
            _export_to_dir(snapshot, tmpdir)
            cap_mode = os.stat(os.path.join(tmpdir, "bin/captool")).st_mode
            ash_mode = os.stat(os.path.join(tmpdir, "bin/ashtool")).st_mode
            no_shebang_mode = os.stat(os.path.join(tmpdir, "bin/no_shebang")).st_mode

        assert cap_mode & 0o755 == 0o755
        assert ash_mode & 0o755 == 0o755
        assert not no_shebang_mode & stat.S_IXUSR

    def test_cap_tool_with_shebang_is_executable(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("bin/mytool", b"#!/usr/bin/env cap\n# ---\n# description: tool\n# ---\nimport sys\n")

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
