# Writing Cap Tools

Cap tools are sandboxed scripts that run in isolated Docker containers with explicit capability grants. They are the primary way to extend the system with custom commands.

## Minimal Example

```
#!/usr/bin/env cap
# ---
# description: Greet the world
# network: 'disable'
# ---
print("Hello, world!")
```

Save as `bin/hello`, then run it:

```
(/) > hello
Hello, world!
```

The `#!/usr/bin/env cap` shebang is **required** — it tells the system to execute the file as a cap tool.

## Frontmatter Reference

After the shebang, a `# ---` block declares the tool's capabilities. The body below the block is the script that runs inside the container.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `description` | Yes | `""` | One-line summary shown in help and agent prompts. |
| `runtime` | No | `'python'` | Script runtime: `'python'`, `'node'`, or `'shell'`. Determines comment syntax (`#` vs `//`) and file extension. |
| `dependencies` | No | `[]` | Packages to install, e.g. `['pypi:requests', 'npm:lodash']`. |
| `access` | No | `[]` | File globs copied into the container's `/workspace`. |
| `network` | No | `'*'` | Network policy (see below). |
| `secrets` | No | `[]` | Env vars injected from the system keychain. |
| `stateful` | No | `false` | Persist `/root` volume across runs. |
| `name` | No | filename | Override the tool name. |

## File Access

The `access` field controls which vault files are available inside the container at `/workspace`. **Only declared files are exported** — the tool cannot see the rest of the vault.

### Path syntax

- Paths must be **vault-absolute** (start with `/`): `'/var/data'`, `'/etc/config.yaml'`
- `'$@'` expands to file paths passed as CLI arguments (resolved relative to the caller's working directory)
- Suffix `:ro` for read-only (changes discarded), `:rw` for read-write (default)
- A directory path like `'/var/data'` implicitly includes all files beneath it

### `$@` — file arguments

When a tool declares `'$@'` (or `'$@:rw'`), CLI arguments that resolve to existing vault files are copied into the workspace. Non-file arguments (flags, strings) pass through unchanged.

```
#!/usr/bin/env cap
# ---
# description: Format JSON files
# dependencies: ['pypi:black']
# access: ['$@:rw']
# network: 'disable'
# ---
import sys, json
for path in sys.argv[1:]:
    with open(path) as f:
        data = json.load(f)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
```

### Fixed paths

For tools that always operate on a known location, use a vault-absolute path:

```
#!/usr/bin/env cap
# ---
# description: Store an experience note
# access: ['/var/experiences:rw']
# network: 'disable'
# ---
import sys, os
from datetime import datetime
# ... writes to /workspace/var/experiences/
```

### Combining `$@` with fixed paths

A tool can declare both. The workspace will contain the union of all matched files:

```
#!/usr/bin/env cap
# ---
# description: Analyze file and log result
# access: ['/var/log:rw', '$@:ro']
# network: 'disable'
# ---
```

Changes to `:rw` files are committed back to the vault when the tool finishes.

## Network Policy

| Value | Behavior |
|-------|----------|
| `'*'` | Unrestricted outbound access (default). |
| `'disable'` | No network at all. |
| `['host1.com', '*.api.com']` | HTTPS-intercepting proxy allowlist. Unmatched hosts get 403. |

```
#!/usr/bin/env cap
# ---
# description: Fetch headlines from zeit.de
# network: ['zeit.de']
# ---
import urllib.request
html = urllib.request.urlopen("https://zeit.de").read()
print(html[:500])
```

## Secrets

Secrets are stored in the system keychain and injected as environment variables at runtime. They are never baked into the Docker image.

```
#!/usr/bin/env cap
# ---
# description: Query OpenAI
# dependencies: ['pypi:openai']
# secrets: ['OPENAI_API_KEY']
# network: ['api.openai.com']
# ---
import os, openai
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
print(client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Say hello"}],
).choices[0].message.content)
```

On first run, you are prompted to provide the secret. If the tool's code changes, re-authorization is required.

## Dependencies

Prefix packages with `pypi:` or `npm:`. Dependencies are installed into a cached Docker layer so rebuilds only happen when the dependency list changes.

```
#!/usr/bin/env cap
# ---
# description: Convert documents to markdown
# dependencies: ['pypi:markitdown[pdf,youtube-transcription]']
# access: ['$@']
# network: ['*']
# ---
from markitdown import MarkItDown
import sys
md = MarkItDown()
print(md.convert(sys.argv[1]).text_content)
```

## Stateful Tools

Set `stateful: true` to persist the container's `/root` directory across runs. Useful for tools that cache data or maintain state.

```
#!/usr/bin/env cap
# ---
# description: Interactive shell
# access: ['$@']
# stateful: true
# ---
import os
os.system("bash")
```

## Runtimes

Cap tools default to Python but can also use Node.js or shell. Set the `runtime` field to control which file extension (`.cap.py`, `.cap.js`, `.cap.sh`) is used when invoking cap. Each runtime uses its own comment syntax for frontmatter.

### Node.js

```
#!/usr/bin/env cap
// ---
// description: Pretty-print JSON
// runtime: 'node'
// access: ['$@:ro']
// network: 'disable'
// ---
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
console.log(JSON.stringify(data, null, 2));
```

Node.js tools use `//` comment syntax for frontmatter. Arguments arrive in `process.argv` (index 2+ for user args). Use `npm:` prefix for dependencies.

### Shell

```
#!/usr/bin/env cap
# ---
# description: Count lines in files
# runtime: 'shell'
# access: ['$@:ro']
# network: 'disable'
# ---
for f in "$@"; do
    echo "$(wc -l < "$f") $f"
done
```

Shell tools use `#` comment syntax (same as Python) and run with `/bin/sh`. Arguments arrive as `$1`, `$2`, etc.

## Where to Put Tools

- **`/bin/<name>`** — callable by name from the shell (on the system PATH)
- Tools are automatically discovered and listed in agent system prompts
- Arguments are passed via `sys.argv` (Python), `process.argv` (Node.js), or `$@` (shell)
- Inside sandbox containers, a `cap` stub is available that prints an error — cap tools cannot be nested
