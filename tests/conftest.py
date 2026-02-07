"""Shared fixtures for all tests."""

import os
import tempfile

import pytest


@pytest.fixture
def temp_db():
    """Fixture that provides a temporary database file path.

    Usage:
        def test_example(temp_db):
            vault = Vault(temp_db, "username")
            # use vault...
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)
