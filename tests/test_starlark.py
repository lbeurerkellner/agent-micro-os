"""Test Starlark script execution."""
import asyncio
import tempfile
from pathlib import Path

import pytest

from fs import Vault
from system.context import SystemContext


@pytest.mark.asyncio
async def test_starlark_basic_execution():
    """Test basic Starlark script execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Write a simple script
            script = """
print("Hello from Starlark!")
"""
            vault.write("/home/test.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/test.star")


@pytest.mark.asyncio
async def test_starlark_fs_read():
    """Test Starlark can read files from vault."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create a file to read
            vault.write("/home/data.txt", b"Hello World!", author="test")

            # Write a script that reads it
            script = """
content = fs['read']("/home/data.txt")
print("Content:", content)
"""
            vault.write("/home/reader.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/reader.star")


@pytest.mark.asyncio
async def test_starlark_fs_write():
    """Test Starlark can write files to vault."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Write a script that creates a file
            script = """
fs['write']("/home/output.txt", "Created by Starlark!")
print("File written")
"""
            vault.write("/home/writer.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/writer.star")

            # Verify the file was created
            content = vault.read("/home/output.txt")
            assert content == b"Created by Starlark!"


@pytest.mark.asyncio
async def test_starlark_fs_list():
    """Test Starlark can list directory contents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create some files
            vault.write("/home/file1.txt", b"test1", author="test")
            vault.write("/home/file2.txt", b"test2", author="test")

            # Write a script that lists them
            script = """
files = fs['list']("/home")
for f in files:
    print("Found:", f)
"""
            vault.write("/home/lister.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/lister.star")


@pytest.mark.asyncio
async def test_starlark_fs_delete():
    """Test Starlark can delete files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create a file
            vault.write("/home/todelete.txt", b"delete me", author="test")

            # Write a script that deletes it
            script = """
fs['delete']("/home/todelete.txt")
print("File deleted")
"""
            vault.write("/home/deleter.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/deleter.star")

            # Verify the file was deleted
            assert not vault.exists("/home/todelete.txt")


@pytest.mark.asyncio
async def test_starlark_function_definition():
    """Test Starlark supports function definitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Write a script with function definition
            script = """
def greet(name):
    return "Hello, " + name + "!"

message = greet("World")
print(message)
"""
            vault.write("/home/functions.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/functions.star")


@pytest.mark.asyncio
async def test_starlark_control_flow():
    """Test Starlark supports control flow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Write a script with control flow
            script = """
def fizzbuzz(n):
    for i in range(1, n + 1):
        s = ""
        if i % 3 == 0:
            s = s + "Fizz"
        if i % 5 == 0:
            s = s + "Buzz"
        if s:
            print(s)
        else:
            print(i)

fizzbuzz(15)
"""
            vault.write("/home/fizzbuzz.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/fizzbuzz.star")


@pytest.mark.asyncio
async def test_starlark_tool_implementation():
    """Test implementing a full tool in Starlark (like a bin/ command)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        vault = Vault(db_path, user="testuser")

        with SystemContext(user="testuser", fsimage=db_path):
            # Create some test files
            vault.write("/home/data/file1.txt", b"content1", author="test")
            vault.write("/home/data/file2.txt", b"content2", author="test")
            vault.write("/home/data/file3.log", b"log content", author="test")

            # Write a tool that backs up all .txt files
            script = """
def backup_txt_files(source_dir, backup_dir):
    \"\"\"Backup all .txt files from source to backup directory.\"\"\"
    files = fs['list'](source_dir)
    count = 0

    for filename in files:
        if filename.endswith(".txt"):
            source_path = source_dir + "/" + filename
            backup_path = backup_dir + "/" + filename

            content = fs['read'](source_path)
            fs['write'](backup_path, content)
            print("Backed up:", filename)
            count = count + 1

    print("Total files backed up:", count)

# Run the backup
backup_txt_files("/home/data", "/home/backup")
"""
            vault.write("/home/bin/backup.star", script.encode(), author="test")

            # Execute it
            from bin.star import run
            await run("/home/bin/backup.star")

            # Verify the backup files exist
            assert vault.exists("/home/backup/file1.txt")
            assert vault.exists("/home/backup/file2.txt")
            assert not vault.exists("/home/backup/file3.log")  # .log file should not be backed up

            # Verify content
            assert vault.read("/home/backup/file1.txt") == b"content1"
            assert vault.read("/home/backup/file2.txt") == b"content2"
