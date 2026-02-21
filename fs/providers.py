"""Built-in folder providers for the overlay filesystem."""

from pathlib import Path
import os

import termcolor

from fs.overlay import FolderProvider
from system.tools import tool_description, tool_signature, ToolProvider

# bin/ directory relative to this file's parent (project root)
_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"


class BinProvider(FolderProvider):
    """Read-only provider that exposes bin/ commands as files under a mount point.

    File names are the command names (no .py extension).
    Reading a file returns b"<built-in FILENAME>".
    """

    def __init__(self):
        self._commands = self._discover_commands()

    def _discover_commands(self) -> list[str]:
        commands = []
        for f in _BIN_DIR.glob("*.py"):
            if f.name in ("__init__.py", "ash.py"):
                continue
            commands.append(f.stem)
        return sorted(commands)

    def list(self, prefix: str = "") -> list[str]:
        if prefix:
            return [c for c in self._commands if c.startswith(prefix)]
        return list(self._commands)

    def read(self, path: str) -> bytes:
        path = path.strip("/")
        if path not in self._commands:
            raise FileNotFoundError(f"'{path}' is not a built-in command")
        return f"<built-in {path}>".encode()

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        return path in self._commands

    def is_dir(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        return False

class ModelProvider(FolderProvider):
    """Read-only provider that exposes /models/ as a folder with available model providers.

    If OPENAI_API_KEY is set it exposes /models/openai/<MODEL_NAME> for each model in OPENAI_MODELS (comma-separated list; default value is gpt-5-mini).
    """
    
    def __init__(self):
        self._providers = self._discover_providers()

    def _discover_providers(self) -> dict[str, list[str]]:
        providers = {}
        
        # openai support
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            models = os.getenv("OPENAI_MODELS", "gpt-5-mini").split(",")
            providers["openai"] = [m.strip() for m in models if m.strip()]
        
        # echo model
        providers["echo"] = ["echo"]

        return providers

    def list(self, prefix: str = "") -> list[str]:
        paths = []
        for provider, models in self._providers.items():
            for model in models:
                p = f"{provider}/{model}"
                if not prefix or p.startswith(prefix):
                    paths.append(p)
        return sorted(paths)

    def read(self, path: str) -> bytes:
        path = path.strip("/")
        parts = path.split("/")
        if len(parts) != 2:
            raise FileNotFoundError(f"'{path}' is not a valid model provider path")
        provider, model = parts
        if provider not in self._providers or model not in self._providers[provider]:
            raise FileNotFoundError(f"Model '{model}' not found for provider '{provider}'")
        return f"<model provider {provider} model {model}>".encode()

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        parts = path.split("/")
        if len(parts) == 2:
            provider, model = parts
            return provider in self._providers and model in self._providers[provider]
        elif len(parts) == 1:
            provider = parts[0]
            return provider in self._providers
        else:
            return False

    def is_dir(self, path: str) -> bool:
        path = path.strip("/")
        return not path or any(path == p.split("/")[0] for p in self.list())
    
    def has_provider(self, provider: str) -> bool:
        return provider in self._providers
    
    def has_model(self, provider: str, model: str) -> bool:
        return provider in self._providers and model in self._providers[provider]
    
class ToolsFolderProvider(FolderProvider):
    """Read-only provider that exposes /tools/ as a folder with available tools.

    Tools are registered via ToolProvider, which includes both built-in tools and custom .tool files from /bin/.
    """

    def __init__(self, ctx):
        self.ctx = ctx

    def list(self, prefix: str = "") -> list[str]:
        tool_provider = ToolProvider(self.ctx)
        if prefix:
            return sorted(k for k in tool_provider.keys() if k.startswith(prefix))
        return sorted(tool_provider.keys())

    def read(self, path: str) -> bytes:
        path = path.strip("/")
        tool_provider = ToolProvider(self.ctx)
        if path not in tool_provider:
            raise FileNotFoundError(f"'{path}' is not a registered tool")
        return f"{termcolor.colored(tool_signature(tool_provider[path]), 'cyan', attrs=['bold'])}\n\n{tool_description(tool_provider[path])}".encode()

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        tool_provider = ToolProvider(self.ctx)
        return path in tool_provider

    def is_dir(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        return False