"""Test concurrent execution of multiple Starlark scripts."""
import asyncio
import tempfile
from pathlib import Path

import pytest

from fs import Vault
from system.context import SystemContext


@pytest.mark.asyncio
async def test_concurrent_star_scripts():
    """Test that multiple star scripts can run concurrently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create three scripts that write to different files
            script1 = """
fs['write']("/output1.txt", "Script 1 output")
print("Script 1 done")
"""
            script2 = """
fs['write']("/output2.txt", "Script 2 output")
print("Script 2 done")
"""
            script3 = """
fs['write']("/output3.txt", "Script 3 output")
print("Script 3 done")
"""

            vault.write("/home/script1.star", script1.encode(), author="test")
            vault.write("/home/script2.star", script2.encode(), author="test")
            vault.write("/home/script3.star", script3.encode(), author="test")

            # Execute all three scripts concurrently
            from bin.star import run

            await asyncio.gather(
                run("/home/script1.star"),
                run("/home/script2.star"),
                run("/home/script3.star"),
            )

            # Verify all scripts executed successfully
            assert vault.exists("/output1.txt")
            assert vault.exists("/output2.txt")
            assert vault.exists("/output3.txt")

            assert vault.read("/output1.txt") == b"Script 1 output"
            assert vault.read("/output2.txt") == b"Script 2 output"
            assert vault.read("/output3.txt") == b"Script 3 output"


@pytest.mark.asyncio
async def test_concurrent_star_with_fs_operations():
    """Test that multiple scripts with fs operations can run concurrently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create test files
            vault.write("/home/test1.txt", b"content1", author="test")
            vault.write("/home/test2.txt", b"content2", author="test")

            # Create two scripts that read and write
            script1 = """
content = fs['read']("/home/test1.txt")
fs['write']("/result1.txt", "Processed: " + content)
print("Script 1 complete")
"""
            script2 = """
content = fs['read']("/home/test2.txt")
fs['write']("/result2.txt", "Processed: " + content)
print("Script 2 complete")
"""

            vault.write("/home/script1.star", script1.encode(), author="test")
            vault.write("/home/script2.star", script2.encode(), author="test")

            # Execute both scripts concurrently
            from bin.star import run

            await asyncio.gather(
                run("/home/script1.star"),
                run("/home/script2.star"),
            )

            # Verify both scripts executed successfully
            assert vault.exists("/result1.txt")
            assert vault.exists("/result2.txt")

            assert vault.read("/result1.txt") == b"Processed: content1"
            assert vault.read("/result2.txt") == b"Processed: content2"


@pytest.mark.asyncio
async def test_star_multiple_operations():
    """Test that star can perform multiple operations without issues."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create test files
            vault.write("/home/a.txt", b"a", author="test")
            vault.write("/home/b.txt", b"b", author="test")
            vault.write("/home/c.txt", b"c", author="test")

            # Create a script that reads multiple files and combines them
            script = """
# Multiple fs operations should work fine
content_a = fs['read']("/home/a.txt")
content_b = fs['read']("/home/b.txt")
content_c = fs['read']("/home/c.txt")

combined = content_a + content_b + content_c
fs['write']("/combined.txt", combined)
"""

            vault.write("/home/test.star", script.encode(), author="test")

            from bin.star import run
            await run("/home/test.star")

            # Verify it executed successfully
            assert vault.exists("/combined.txt")
            content = vault.read("/combined.txt").decode()
            assert content == "abc"
