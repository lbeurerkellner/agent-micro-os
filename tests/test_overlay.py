"""Tests for overlay FS with folder providers."""

import pytest

from fs.overlay import FolderProvider, OverlayFS
from fs.providers import BinProvider
from fs.vault import Vault


class DictProvider(FolderProvider):
    """A simple in-memory folder provider backed by a dict for testing."""

    def __init__(self, files: dict[str, bytes]):
        self._files = files

    def list(self) -> list[str]:
        return list(self._files.keys())

    def read(self, path: str) -> bytes:
        path = path.strip("/")
        if path not in self._files:
            raise FileNotFoundError(f"File '{path}' not found in provider")
        return self._files[path]

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        if path in self._files:
            return True
        prefix = path + "/"
        return any(f.startswith(prefix) for f in self._files)

    def is_dir(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        if path in self._files:
            return False
        prefix = path + "/"
        return any(f.startswith(prefix) for f in self._files)


@pytest.fixture
def vault(temp_db):
    return Vault(temp_db, "testuser")


@pytest.fixture
def provider():
    return DictProvider({
        "readme.txt": b"Hello from provider",
        "sub/nested.txt": b"Nested file content",
        "sub/deep/file.txt": b"Deep nested content",
    })


@pytest.fixture
def overlay(vault, provider):
    ofs = OverlayFS(vault)
    ofs.mount("mnt", provider)
    return ofs


# --- Basic provider reads ---


def test_read_from_provider(overlay):
    assert overlay.read("mnt/readme.txt") == b"Hello from provider"


def test_read_nested_from_provider(overlay):
    assert overlay.read("mnt/sub/nested.txt") == b"Nested file content"


def test_read_deep_nested_from_provider(overlay):
    assert overlay.read("mnt/sub/deep/file.txt") == b"Deep nested content"


def test_read_nonexistent_in_provider(overlay):
    with pytest.raises(FileNotFoundError):
        overlay.read("mnt/nonexistent.txt")


# --- Vault reads still work ---


def test_read_from_vault(overlay, vault):
    vault.write("hello.txt", b"Vault content")
    assert overlay.read("hello.txt") == b"Vault content"


def test_vault_and_provider_coexist_in_list(overlay, vault):
    vault.write("hello.txt", b"Vault content")
    files = overlay.list()
    assert "hello.txt" in files
    assert "mnt/readme.txt" in files
    assert "mnt/sub/nested.txt" in files
    assert "mnt/sub/deep/file.txt" in files


# --- exists() ---


def test_mount_point_exists(overlay):
    assert overlay.exists("mnt") is True


def test_file_in_mount_exists(overlay):
    assert overlay.exists("mnt/readme.txt") is True


def test_dir_in_mount_exists(overlay):
    assert overlay.exists("mnt/sub") is True


def test_nonexistent_in_mount(overlay):
    assert overlay.exists("mnt/nope.txt") is False


def test_vault_file_exists(overlay, vault):
    vault.write("hello.txt", b"hi")
    assert overlay.exists("hello.txt") is True


def test_nonexistent_anywhere(overlay):
    assert overlay.exists("nope/nope.txt") is False


# --- is_dir() ---


def test_mount_point_is_dir(overlay):
    assert overlay.is_dir("mnt") is True


def test_dir_in_mount_is_dir(overlay):
    assert overlay.is_dir("mnt/sub") is True


def test_file_in_mount_is_not_dir(overlay):
    assert overlay.is_dir("mnt/readme.txt") is False


def test_vault_dir_is_dir(overlay, vault):
    vault.write("docs/file.txt", b"content")
    assert overlay.is_dir("docs") is True


def test_vault_file_is_not_dir(overlay, vault):
    vault.write("file.txt", b"content")
    assert overlay.is_dir("file.txt") is False


# --- Read-only enforcement ---


def test_write_to_mount_raises(overlay):
    with pytest.raises(PermissionError):
        overlay.write("mnt/newfile.txt", b"data")


def test_delete_from_mount_raises(overlay):
    with pytest.raises(PermissionError):
        overlay.delete("mnt/readme.txt")


def test_write_to_vault_still_works(overlay):
    overlay.write("newfile.txt", b"data")
    assert overlay.read("newfile.txt") == b"data"


def test_delete_from_vault_still_works(overlay, vault):
    vault.write("todelete.txt", b"bye")
    overlay.delete("todelete.txt")
    assert overlay.exists("todelete.txt") is False


# --- Multiple mount points ---


def test_multiple_mounts(vault):
    p1 = DictProvider({"a.txt": b"Provider 1"})
    p2 = DictProvider({"b.txt": b"Provider 2"})
    ofs = OverlayFS(vault)
    ofs.mount("mount1", p1)
    ofs.mount("mount2", p2)

    assert ofs.read("mount1/a.txt") == b"Provider 1"
    assert ofs.read("mount2/b.txt") == b"Provider 2"
    assert ofs.exists("mount1") is True
    assert ofs.exists("mount2") is True

    files = ofs.list()
    assert "mount1/a.txt" in files
    assert "mount2/b.txt" in files


# --- list() returns provider files prefixed with mount point ---


def test_list_includes_all_provider_files(overlay):
    files = overlay.list()
    assert "mnt/readme.txt" in files
    assert "mnt/sub/nested.txt" in files
    assert "mnt/sub/deep/file.txt" in files


# --- Path normalization ---


def test_read_with_leading_slash(overlay):
    assert overlay.read("/mnt/readme.txt") == b"Hello from provider"


def test_exists_with_leading_slash(overlay):
    assert overlay.exists("/mnt") is True
    assert overlay.exists("/mnt/readme.txt") is True


# --- Passthrough methods ---


def test_log_passthrough(overlay, vault):
    vault.write("file.txt", b"v1")
    vault.write("file.txt", b"v2")
    log = overlay.log("file.txt")
    assert len(log) == 2


def test_begin_end_commit_passthrough(overlay, vault):
    overlay.begin_commit()
    overlay.write("committed.txt", b"data")
    overlay.end_commit("test commit")
    assert overlay.read("committed.txt") == b"data"


# --- Integration: ls._list_directory works with overlay ---


def test_list_directory_with_overlay(overlay, vault):
    from bin.ls import _list_directory

    vault.write("root_file.txt", b"hi")

    entries = _list_directory(overlay, "/")
    assert "root_file.txt" in entries
    assert "mnt/" in entries


def test_list_directory_inside_mount(overlay):
    from bin.ls import _list_directory

    entries = _list_directory(overlay, "/mnt")
    assert "readme.txt" in entries
    assert "sub/" in entries


def test_list_directory_nested_mount(overlay):
    from bin.ls import _list_directory

    entries = _list_directory(overlay, "/mnt/sub")
    assert "nested.txt" in entries
    assert "deep/" in entries


# --- Integration: cd should work with mounted dirs ---


def test_cd_into_mount_point(overlay, temp_db):
    from system.context import SystemContext

    with SystemContext(user="testuser", fsimage=temp_db):
        assert overlay.exists("mnt") is True
        assert overlay.is_dir("mnt") is True


# --- Root always works ---


def test_root_exists(overlay):
    assert overlay.exists("") is True
    assert overlay.is_dir("") is True


# --- BinProvider ---


@pytest.fixture
def bin_provider():
    return BinProvider()


def test_bin_provider_lists_commands(bin_provider):
    files = bin_provider.list()
    assert "ls" in files
    assert "cat" in files
    assert "cd" in files
    assert "rm" in files
    assert "edit" in files
    assert "ash" not in files
    assert "__init__" not in files
    assert not any(f.endswith(".py") for f in files)


def test_bin_provider_read_returns_builtin_marker(bin_provider):
    assert bin_provider.read("ls") == b"<built-in ls>"
    assert bin_provider.read("cat") == b"<built-in cat>"
    assert bin_provider.read("rm") == b"<built-in rm>"


def test_bin_provider_read_nonexistent(bin_provider):
    with pytest.raises(FileNotFoundError):
        bin_provider.read("nonexistent")


def test_bin_provider_exists(bin_provider):
    assert bin_provider.exists("ls") is True
    assert bin_provider.exists("cat") is True
    assert bin_provider.exists("nonexistent") is False


def test_bin_provider_is_dir(bin_provider):
    assert bin_provider.is_dir("ls") is False
    assert bin_provider.is_dir("") is True


def test_bin_provider_mounted_as_sbin(vault):
    ofs = OverlayFS(vault)
    ofs.mount("sbin", BinProvider())

    assert ofs.exists("sbin") is True
    assert ofs.is_dir("sbin") is True
    assert ofs.exists("sbin/ls") is True
    assert ofs.read("sbin/ls") == b"<built-in ls>"

    files = ofs.list()
    assert "sbin/ls" in files
    assert "sbin/cat" in files


def test_bin_provider_mounted_ls_integration(vault):
    from bin.ls import _list_directory

    ofs = OverlayFS(vault)
    ofs.mount("sbin", BinProvider())

    entries = _list_directory(ofs, "/sbin")
    assert "ls" in entries
    assert "cat" in entries
    assert "cd" in entries


# --- list_with_metadata() ---


def test_list_with_metadata_includes_mounts(overlay, vault):
    from fs.vault import FileMeta

    vault.write("vaultfile.txt", b"Vault content")

    metas = overlay.list_with_metadata()
    by_path = {m.filepath: m for m in metas}

    assert "mnt/readme.txt" in by_path
    m = by_path["mnt/readme.txt"]
    assert isinstance(m, FileMeta)
    assert m.timestamp is None
    assert m.author is None
    assert m.size is None


def test_list_with_metadata_vault_files_have_metadata(overlay, vault):
    from fs.vault import FileMeta

    vault.write("hello.txt", b"Hello!")

    metas = overlay.list_with_metadata()
    by_path = {m.filepath: m for m in metas}

    assert "hello.txt" in by_path
    m = by_path["hello.txt"]
    assert isinstance(m, FileMeta)
    assert m.timestamp is not None
    assert m.author is not None
    assert m.size == len(b"Hello!")
