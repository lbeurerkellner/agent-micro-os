# 🧢 `cap` - Capability-Based CLIs

`cap` lets AI agents request access to sensitive resources by writing small, self-contained programs. The program source code acts as the capability token. Its contents and declared permissions (file access, network targets, secrets) are hashed together, and secrets are only released from the system keychain when the hash matches a previously approved version.

When an agent writes a cap program, it's composing a permission request in executable form. The human reviews the code, sees exactly what it does and what it can access, and approves or rejects it. Any change to the code or its capabilities invalidates the approval and requires re-authorization.

Cap programs run as isolated containers and define their own sandboxing properties as part of their configuration. This gives you least-privilege agent tooling without requiring upstream providers to support fine-grained access controls.

`cap` supports Python, Node.js, and shell programs, with dependencies via PyPI and npm. Capabilities are specified as frontmatter in the source file.

## Quick Start

```bash
uv tool install --editable .
```

To test, see `examples/shell.cap.py`:

```
#!/usr/bin/env cap
# ---
# name: shell
# description: Interactive bash shell for testing network restrictions.
# dependencies: []
# network: "*"
# access: ['$@']
# ---
import os
os.execvp("bash", ["bash"])
```

This configuration gives full network access to a containerized `bash` process, and grants access to just the passed file path.

For instance, in the following, the shell CLI can only access and edit the `README.md` file:

```bash
> cap examples/shell.cap.py README.md

root@b5d85df70865:/workspace > echo 'testing' >> README.md

root@b5d85df70865:/workspace > curl google.com
(... google.com response ...)

root@b5d85df70865:/workspace > exit
exit


File Changes:
  ~ README.md

Network connections:
  google.com  GET  (2 req)
```

As you can see, cap programs run in an audited and policed environment. In this example, the shell has the capability to read and write only `README.md` and to make arbitrary HTTP requests. Upon completion, the changes to `README.md` are tracked and written back to the host file system, while all network connections are also reported.

## Examples

The `examples/` directory contains ready-to-use cap programs:

| Program | Description | Capabilities |
|---------|-------------|-------------|
| [`shell.cap.py`](examples/shell.cap.py) | Interactive bash shell | Full network, file access via args |
| [`vim.cap.py`](examples/vim.cap.py) | Sandboxed vim editor | No network, read/write access via args |
| [`openai.cap.py`](examples/openai.cap.py) | Chat with the OpenAI API | `OPENAI_API_KEY` secret, network limited to `api.openai.com` |
| [`claude.cap.sh`](examples/claude.cap.sh) | Run Claude Code in a container | Stateful container, file access via args |
| [`markitdown.cap.py`](examples/markitdown.cap.py) | Convert files to markdown via MarkItDown | Full network, file access via args, PyPI dependency |
| [`date.cap.py`](examples/date.cap.py) | Print current date/time with optional timezone | No network, no file access |

These examples illustrate how capabilities scale from fully locked down (`date` — no network, no files, no secrets) to progressively more permissive, with each program declaring exactly what it needs.