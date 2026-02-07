"""SystemContext with contextvar-based stacking for async support."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fs.overlay import FolderProvider, OverlayFS
from fs.vault import Vault


@dataclass
class AgentProcess:
    """An active agent process tracked in /proc."""

    pid: str          # UUID
    program: str      # filepath of the program being run
    trajectory: str   # path to trajectory file


# Global context var storing a stack of SystemContexts
_context_stack: ContextVar[list['SystemContext']] = ContextVar('_context_stack', default=[])


class SystemContext:
    """A context manager that provides stacking context access via contextvars.

    This allows nested coroutines in asyncio to access the current context.

    Usage:
        with SystemContext() as ctx:
            # ctx is accessible here
            assert SystemContext.current() is ctx

            # Works in nested async contexts too
            async def nested():
                assert SystemContext.current() is ctx
    """
    
    user: str # current user, constant
    fsimage: str # path to fsimage DB, constant
    cwd: str # current working directory, mutable
    path: list[str] # system PATH for command resolution

    def __init__(self, user: str, fsimage: str, debug: bool = False):
        self.user = user
        self.fsimage = fsimage
        self.debug = debug

        self.path = ['/sbin', '/bin']

        self.cwd = '/'
        self._mounts: dict[str, FolderProvider] = {}
        self._agents: dict[str, AgentProcess] = {}
        # set of asyncio background tasks for tracking purposes (to enable clean up)
        self._background_tasks = set()

    def mount(self, path: str, provider: FolderProvider):
        """Mount a read-only folder provider at the given path.

        :param path: Mount point (e.g. "sys", "mnt/data")
        :param provider: The folder provider to mount
        """
        self._mounts[path.strip("/")] = provider

    def read(self, filepath: str, default: Optional[str] = None) -> Optional[str]:
        """Read a file from the context's filesystem, returning default if not found."""
        try:
            return self.fs().read(filepath).decode('utf-8')
        except FileNotFoundError:
            return default

    def register_background_task(self, task):
        """Registers background tasks to keep track of."""
        self._background_tasks.add(task)

    def register_agent(self, pid: str, program: str, trajectory: str):
        """Register an active agent process."""
        self._agents[pid] = AgentProcess(pid=pid, program=program, trajectory=trajectory)

    def unregister_agent(self, pid: str):
        """Remove an agent process (completed, cancelled, or failed)."""
        self._agents.pop(pid, None)

    def fs(self) -> OverlayFS:
        """Get an OverlayFS instance wrapping the vault with any registered mounts."""
        return OverlayFS(Vault(self.fsimage, self.user), self._mounts)

    def __enter__(self):
        """Enter the context manager, pushing this context onto the stack."""
        stack = _context_stack.get()
        new_stack = stack.copy()
        new_stack.append(self)
        _context_stack.set(new_stack)
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """Exit the context manager, popping this context from the stack."""
        stack = _context_stack.get()
        new_stack = stack.copy()
        new_stack.pop()
        _context_stack.set(new_stack)
        return False

    @classmethod
    def current(cls) -> Optional['SystemContext']:
        """Get the current SystemContext from the contextvar stack.

        Returns:
            The current SystemContext, or None if no context is active.
        """
        stack = _context_stack.get()
        return stack[-1] if stack else None
