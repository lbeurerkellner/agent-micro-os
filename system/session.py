"""VaultJSONSession: stores agent conversation history as JSONL files in the vault.

Sessions are stored at /var/sessions/<session_id>.jsonl and are fully versioned
through the vault, making them inspectable with `cat`, diffable with `fslog`, etc.

Each line in the file is a single JSON-encoded TResponseInputItem (JSONL format).

add_items uses vault append mode so it never needs to read before writing.
pop_item and clear_session rewrite the file from scratch since they mutate history.

"""

import asyncio
import json
from typing import TYPE_CHECKING

from agents.memory import SessionABC, SessionSettings
from agents.memory.session_settings import resolve_session_limit

if TYPE_CHECKING:
    from system.context import SystemContext


class VaultJSONSession(SessionABC):
    """Session that persists conversation history as a JSONL file in the vault.

    Each session is stored at /var/sessions/<session_id>.jsonl — one JSON object
    per line. add_items appends directly without reading first.
    """

    def __init__(
        self,
        session_id: str,
        ctx: "SystemContext",
        session_settings: SessionSettings | None = None,
    ):
        self.session_id = session_id
        self.session_settings = session_settings or SessionSettings()
        self._ctx = ctx
        self._path = f"/var/sessions/{session_id}.jsonl"
        self._lock = asyncio.Lock()

    def _read_all(self) -> list:
        try:
            data = self._ctx.fs().read(self._path).decode("utf-8")
            return [json.loads(line) for line in data.splitlines() if line.strip()]
        except FileNotFoundError:
            return []

    def _overwrite(self, items: list) -> None:
        content = "".join(json.dumps(item) + "\n" for item in items)
        self._ctx.fs().write(self._path, content.encode("utf-8"))

    async def get_items(self, limit: int | None = None):
        async with self._lock:
            items = self._read_all()
            effective_limit = resolve_session_limit(limit, self.session_settings)
            if effective_limit is not None:
                items = items[-effective_limit:]
            return items

    async def add_items(self, items: list) -> None:
        async with self._lock:
            chunk = "".join(json.dumps(item) + "\n" for item in items)
            try:
                existing = self._ctx.fs().read(self._path)
            except FileNotFoundError:
                existing = b""
            self._ctx.fs().write(self._path, existing + chunk.encode("utf-8"), mode="a")

    async def pop_item(self):
        async with self._lock:
            items = self._read_all()
            if not items:
                return None
            item = items.pop()
            self._overwrite(items)
            return item

    async def clear_session(self) -> None:
        async with self._lock:
            self._overwrite([])
