"""Tests for the du (disk usage) command."""

import io
import pytest
from system.context import SystemContext
from fs.vault import Vault
from bin.du import run, _format_size, _calculate_directory_sizes


@pytest.fixture
def populated_db(temp_db):
    """Create a vault database with sample files for testing."""
    vault = Vault(temp_db, "testuser")
    # Create files with different sizes
    vault.write("file1.txt", b"Hello")  # 5 bytes
    vault.write("file2.txt", b"World!")  # 6 bytes
    vault.write("dir1/file3.txt", b"A" * 100)  # 100 bytes
    vault.write("dir1/file4.txt", b"B" * 200)  # 200 bytes
    vault.write("dir1/subdir/file5.txt", b"C" * 50)  # 50 bytes
    vault.write("dir2/file6.txt", b"D" * 150)  # 150 bytes
    return temp_db


class TestFormatSize:
    """Test the _format_size helper function."""

    def test_bytes_format(self):
        """Test non-human-readable format (bytes)."""
        assert _format_size(0, False) == "0"
        assert _format_size(100, False) == "100"
        assert _format_size(1024, False) == "1024"
        assert _format_size(1048576, False) == "1048576"

    def test_human_readable_bytes(self):
        """Test human-readable format for small sizes."""
        assert _format_size(0, True) == "0"
        assert _format_size(100, True) == "100"
        assert _format_size(1023, True) == "1023"

    def test_human_readable_kilobytes(self):
        """Test human-readable format for KB sizes."""
        assert _format_size(1024, True) == "1.0K"
        assert _format_size(2048, True) == "2.0K"
        assert _format_size(1536, True) == "1.5K"

    def test_human_readable_megabytes(self):
        """Test human-readable format for MB sizes."""
        assert _format_size(1048576, True) == "1.0M"
        assert _format_size(2097152, True) == "2.0M"
        assert _format_size(1572864, True) == "1.5M"

    def test_human_readable_gigabytes(self):
        """Test human-readable format for GB sizes."""
        assert _format_size(1073741824, True) == "1.0G"
        assert _format_size(2147483648, True) == "2.0G"


class TestCalculateDirectorySizes:
    """Test the _calculate_directory_sizes helper function."""

    def test_root_directory(self, populated_db):
        """Test calculating sizes for root directory."""
        vault = Vault(populated_db, "testuser")
        current, total = _calculate_directory_sizes(vault, "")
        # Total: 5 + 6 + 100 + 200 + 50 + 150 = 511 bytes
        assert current["."] == 511
        assert current["dir1"] == 350  # 100 + 200 + 50
        assert current["dir1/subdir"] == 50
        assert current["dir2"] == 150
        # Since no updates yet, total should equal current
        assert total["."] == 511
        assert total["dir1"] == 350

    def test_subdirectory(self, populated_db):
        """Test calculating sizes for a subdirectory."""
        vault = Vault(populated_db, "testuser")
        current, total = _calculate_directory_sizes(vault, "dir1")
        # Should only include dir1 contents
        assert current["dir1"] == 350
        assert current["dir1/subdir"] == 50
        assert "dir2" not in current

    def test_empty_directory(self, temp_db):
        """Test calculating sizes for an empty vault."""
        vault = Vault(temp_db, "testuser")
        current, total = _calculate_directory_sizes(vault, "")
        assert current == {}
        assert total == {}

    def test_nonexistent_directory(self, populated_db):
        """Test calculating sizes for a non-existent directory."""
        vault = Vault(populated_db, "testuser")
        current, total = _calculate_directory_sizes(vault, "nonexistent")
        assert current == {}
        assert total == {}

    def test_with_versions(self, temp_db):
        """Test that total includes all versions."""
        vault = Vault(temp_db, "testuser")
        # Create a file
        vault.write("test.txt", b"Hello")  # 5 bytes

        # Update the file
        vault.write("test.txt", b"Hello World!")  # 12 bytes

        current, total = _calculate_directory_sizes(vault, "")
        # Current should be 12 bytes (latest version)
        assert current["."] == 12
        # Total should be 5 + 12 = 17 bytes (both versions)
        assert total["."] == 17


class TestDuCommand:
    """Test the du command execution."""

    @pytest.mark.asyncio
    async def test_du_default(self, populated_db):
        """Test du with no flags (show all directories)."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run()

            result = output.getvalue()
            lines = result.strip().split('\n')

            # Should show all directories with current and total sizes
            # Format: CURRENT\tTOTAL\tPATH
            assert any("511\t511\t." in line for line in lines)
            assert any("350\t350\t./dir1" in line for line in lines)
            assert any("50\t50\t./dir1/subdir" in line for line in lines)
            assert any("150\t150\t./dir2" in line for line in lines)

    @pytest.mark.asyncio
    async def test_du_summarize(self, populated_db):
        """Test du with -s flag (summarize only)."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-s")

            result = output.getvalue()
            lines = result.strip().split('\n')

            # Should show only the total
            assert len(lines) == 1
            assert "511\t511\t." in lines[0]

    @pytest.mark.asyncio
    async def test_du_human_readable(self, populated_db):
        """Test du with -h flag (human-readable)."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-h")

            result = output.getvalue()

            # Should show sizes in bytes (less than 1K)
            assert "511\t511\t." in result
            assert "350\t350\t./dir1" in result

    @pytest.mark.asyncio
    async def test_du_human_readable_large(self, temp_db):
        """Test du with -h flag for larger files."""
        vault = Vault(temp_db, "testuser")
        # Create files with larger sizes
        vault.write("big1.dat", b"X" * 2048)  # 2KB
        vault.write("big2.dat", b"Y" * 1536)  # 1.5KB

        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-h")

            result = output.getvalue()

            # Should show sizes in KB (3.5KB total)
            assert "3.5K\t3.5K\t." in result

    @pytest.mark.asyncio
    async def test_du_both_flags(self, populated_db):
        """Test du with both -s and -h flags."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-s", "-h")

            result = output.getvalue()
            lines = result.strip().split('\n')

            # Should show only total in human-readable format
            assert len(lines) == 1
            assert "511\t511\t." in lines[0]

    @pytest.mark.asyncio
    async def test_du_specific_directory(self, populated_db):
        """Test du with a specific directory argument."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("dir1")

            result = output.getvalue()

            # Should show dir1 and its subdirectories
            assert "350\t350\tdir1" in result
            assert "50\t50\tdir1/subdir" in result
            # Should not show dir2
            assert "dir2" not in result

    @pytest.mark.asyncio
    async def test_du_specific_directory_summarize(self, populated_db):
        """Test du with -s flag and specific directory."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-s", "dir1")

            result = output.getvalue()
            lines = result.strip().split('\n')

            # Should show only dir1 total
            assert len(lines) == 1
            assert "350\t350\tdir1" in lines[0]

    @pytest.mark.asyncio
    async def test_du_from_subdirectory(self, populated_db):
        """Test du when current directory is not root."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            ctx.cwd = "/dir1"

            output = io.StringIO()
            with ctx.child(stdout=output):
                await run()

            result = output.getvalue()

            # Should show current directory (dir1) and its contents
            assert "350\t350\t." in result
            assert "50\t50\t./subdir" in result

    @pytest.mark.asyncio
    async def test_du_empty_vault(self, temp_db):
        """Test du on an empty vault."""
        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run()

            result = output.getvalue().strip()

            # Should show 0 for current directory
            assert "0\t0\t." in result

    @pytest.mark.asyncio
    async def test_du_invalid_flag(self, populated_db):
        """Test du with an invalid flag."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-x")

            result = output.getvalue()

            # Should show error message
            assert "unknown option: -x" in result
            assert "Usage:" in result

    @pytest.mark.asyncio
    async def test_du_multiple_paths(self, populated_db):
        """Test du with multiple path arguments."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("dir1", "dir2")

            result = output.getvalue()

            # Should show both directories
            assert "350\t350\tdir1" in result
            assert "150\t150\tdir2" in result

    @pytest.mark.asyncio
    async def test_du_with_versions(self, temp_db):
        """Test du shows different current and total sizes when files have multiple versions."""
        vault = Vault(temp_db, "testuser")
        # Create initial files
        vault.write("test.txt", b"Hello")  # 5 bytes
        vault.write("data.txt", b"World")  # 5 bytes

        # Update test.txt to be larger
        vault.write("test.txt", b"Hello World!!!")  # 14 bytes

        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run()

            result = output.getvalue()

            # Current size: 14 + 5 = 19 bytes
            # Total size: 5 + 5 + 14 = 24 bytes (includes old version of test.txt)
            assert "19\t24\t." in result

    @pytest.mark.asyncio
    async def test_du_with_versions_human_readable(self, temp_db):
        """Test du with -h shows different current and total sizes."""
        vault = Vault(temp_db, "testuser")
        # Create a file with multiple versions
        vault.write("big.dat", b"X" * 1024)  # 1KB
        vault.write("big.dat", b"Y" * 2048)  # 2KB

        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-s", "-h")

            result = output.getvalue()

            # Current: 2KB, Total: 3KB (1KB + 2KB)
            assert "2.0K\t3.0K\t." in result

    @pytest.mark.asyncio
    async def test_du_glob_star(self, populated_db):
        """Test du with * glob pattern."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("*")

            result = output.getvalue()

            # Should show individual entries for each top-level item
            assert "dir1" in result
            assert "dir2" in result
            assert "file1.txt" in result
            assert "file2.txt" in result

    @pytest.mark.asyncio
    async def test_du_glob_pattern(self, populated_db):
        """Test du with specific glob pattern."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("dir*")

            result = output.getvalue()

            # Should show only directories matching dir*
            assert "dir1" in result
            assert "dir2" in result
            # Should not show files
            assert "file1.txt" not in result
            assert "file2.txt" not in result

    @pytest.mark.asyncio
    async def test_du_glob_with_flags(self, populated_db):
        """Test du with glob and -h flag."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("-h", "dir*")

            result = output.getvalue()

            # Should show sizes in human-readable format
            assert "350\t350\tdir1" in result
            assert "150\t150\tdir2" in result

    @pytest.mark.asyncio
    async def test_du_glob_no_match(self, populated_db):
        """Test du with glob pattern that matches nothing."""
        with SystemContext(user="testuser", fsimage=populated_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("nomatch*")

            result = output.getvalue()

            # Should show error message
            assert "No such file or directory" in result

    @pytest.mark.asyncio
    async def test_du_glob_question_mark(self, temp_db):
        """Test du with ? glob pattern."""
        vault = Vault(temp_db, "testuser")
        vault.write("a1.txt", b"test")
        vault.write("a2.txt", b"test")
        vault.write("b1.txt", b"test")

        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("a?.txt")

            result = output.getvalue()

            # Should match a1.txt and a2.txt but not b1.txt
            assert "a1.txt" in result
            assert "a2.txt" in result
            assert "b1.txt" not in result

    @pytest.mark.asyncio
    async def test_du_individual_files(self, temp_db):
        """Test du on individual files (not directories)."""
        vault = Vault(temp_db, "testuser")
        vault.write("file1.txt", b"Hello")  # 5 bytes
        vault.write("file1.txt", b"Hello World!")  # 12 bytes (update)
        vault.write("file2.txt", b"Test")  # 4 bytes

        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("file1.txt", "file2.txt")

            result = output.getvalue()

            # file1.txt: current=12, total=5+12=17
            assert "12\t17\tfile1.txt" in result
            # file2.txt: current=4, total=4
            assert "4\t4\tfile2.txt" in result

    @pytest.mark.asyncio
    async def test_du_glob_on_files(self, temp_db):
        """Test du with glob matching individual files."""
        vault = Vault(temp_db, "testuser")
        vault.write("bin/agent", b"x" * 100)
        vault.write("bin/agent", b"x" * 120)  # Update
        vault.write("bin/greet", b"y" * 50)
        vault.write("bin/python", b"z" * 30)

        with SystemContext(user="testuser", fsimage=temp_db) as ctx:
            ctx.cwd = "/bin"

            output = io.StringIO()
            with ctx.child(stdout=output):
                await run("*")

            result = output.getvalue()

            # Should show individual file sizes
            # agent: current=120, total=100+120=220
            assert "120\t220\tagent" in result
            # greet: current=50, total=50
            assert "50\t50\tgreet" in result
            # python: current=30, total=30
            assert "30\t30\tpython" in result
