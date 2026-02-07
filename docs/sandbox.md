# sandbox(1) - Docker Container Execution

## NAME
**sandbox** - Execute commands in Docker containers with vault filesystem access

## SYNOPSIS
```
sandbox [--image IMAGE] [--prefix PATH] [--cmd CMD] [--mount PATH] [--uid UID] [path]
```

## DESCRIPTION
**sandbox** creates an isolated Docker container environment with bidirectional synchronization to the agent vault. It exports the current vault snapshot to a Docker volume, launches a container, and upon exit, automatically commits any changes back to the vault.

This enables running untrusted code, system tools, or complex software stacks in isolation while maintaining persistent storage in the vault.

## OPTIONS

**--image** *IMAGE*
> Docker image to use. Default: `ubuntu:24.04`

**--prefix** *PATH*
> Only mount files under this vault path. Filters which files are exported to the container.

**--cmd** *CMD*
> Run a specific command instead of interactive bash shell.

**--mount** *PATH*
> Container mount point for the vault volume. Default: `/workspace`

**--uid** *UID*
> User ID for file ownership in the container. Default: `0` (root)

*path*
> Shorthand for `--prefix`. Only mount files under this vault path.

## OPERATION

### Export Phase
1. Filters vault files based on `--prefix` (if specified)
2. Creates a temporary Docker volume
3. Exports filtered files to a tar archive
4. Populates the volume with the tar contents
5. Sets file ownership to specified UID/GID

### Container Phase
1. Launches container with volume mounted
2. Sets working directory to mount point
3. Runs interactive bash (or specified command)
4. User can make any changes inside the container

### Import Phase
1. Reads current volume contents
2. Diffs against original snapshot
3. Reports added, modified, and deleted files
4. Commits changes back to vault (unless readonly)
5. Removes temporary volume

## EXAMPLES

### Launch Ubuntu Container
```bash
sandbox
```
Opens an interactive bash shell in Ubuntu 24.04 with full vault access at `/workspace`.

### Use Different Image
```bash
sandbox --image python:3.11
```
Launch a Python container for running Python scripts.

### Run Specific Command
```bash
sandbox --cmd "python script.py"
```
Execute a Python script and exit.

### Mount Subset of Vault
```bash
sandbox --prefix /home/projects/web
```
Only mount files under `/home/projects/web` to the container.

### Custom Mount Point
```bash
sandbox --mount /app
```
Mount vault at `/app` instead of default `/workspace`.

### Run as Non-Root User
```bash
sandbox --uid 1000
```
Set file ownership to UID 1000 (typical for first user on Linux systems).

### Complex Example
```bash
sandbox --image node:20 --prefix /home/app --cmd "npm install && npm test" --uid 1000
```
- Use Node.js 20 image
- Mount only `/home/app` directory
- Run npm install and tests
- Files owned by UID 1000

## USE CASES

### Software Development
```bash
# Test code in clean environment
sandbox --image rust:latest --prefix /home/project --cmd "cargo test"

# Run linters
sandbox --image node:20 --cmd "npm run lint"
```

### System Administration
```bash
# Install packages in isolation
sandbox --cmd "apt-get update && apt-get install -y postgresql"

# Test shell scripts
sandbox --prefix /home/scripts --cmd "bash test-runner.sh"
```

### Data Processing
```bash
# Process large datasets with Python
sandbox --image python:3.11 --cmd "python analyze_data.py"

# Run R statistical analysis
sandbox --image r-base --cmd "Rscript analysis.R"
```

### Security Testing
```bash
# Run untrusted code safely
sandbox --image ubuntu:24.04 --cmd "bash suspicious-script.sh"

# Analyze malware in isolation
sandbox --image remnux/remnux --prefix /samples
```

## ENVIRONMENT VARIABLES

Environment variables can be passed programmatically via the Python API:

```python
from bin.sandbox import run

await run("--cmd", "env", env={"FOO": "bar", "DEBUG": "true"})
```

This translates to: `docker run -e FOO=bar -e DEBUG=true ...`

## CHANGE TRACKING

After container exits, sandbox reports changes:

```
Exported 42 files
Launching ubuntu:24.04...
<container session>
15 added, 3 modified, 2 removed
Committed.
Volume vault-abc123def456 removed
```

### Change Types
- **Added**: New files created in container
- **Modified**: Existing files changed
- **Removed**: Files deleted in container

## READONLY MODE

Programmatic readonly mode (Python API only):
```python
await run(readonly=True)
```

Changes are discarded instead of committed back to vault. Useful for:
- Testing destructive operations
- Temporary workspaces
- Read-only analysis

## TECHNICAL DETAILS

### Volume Lifecycle
1. Created: `docker volume create vault-<random-id>`
2. Populated: Files extracted from tar into volume
3. Mounted: Volume attached to container at mount point
4. Diffed: Final state compared to initial snapshot
5. Cleaned: Volume removed after commit

### File Permissions
- Directories: `0755` (rwxr-xr-x)
- Files: `0600` (rw-------)
- Owner: UID/GID from `--uid` option

### Tar Format
- Format: POSIX tar (uncompressed)
- Directory creation: All parent directories created automatically
- Symlinks: Not currently supported

## EXIT STATUS
- **0**: Success
- **1**: Error (Docker not available, volume creation failed, etc.)
- *Container exit code*: In command mode, returns container's exit status

## NOTES

1. **Docker Required**: Must have Docker daemon running
2. **Image Availability**: Images are pulled automatically if not present
3. **Network Access**: Containers have network access by default
4. **Isolation**: Each sandbox creates a new container (not reused)
5. **Cleanup**: Volumes are always removed after use
6. **Binary Files**: All file types supported (text and binary)

## SECURITY CONSIDERATIONS

### Container Isolation
- Containers run with default Docker isolation
- No access to host filesystem outside volume
- Network access enabled (can reach internet)
- Process isolation via namespaces

### Untrusted Code
When running untrusted code:
1. Use `--readonly` to prevent vault modification
2. Consider network isolation with Docker options
3. Use minimal base images
4. Set resource limits (memory, CPU)

### Privilege Escalation
- Containers run as root by default
- Files created have specified UID ownership
- Consider using `--uid` with non-zero UID for better isolation

## DOCKER INTEGRATION

### Images
Any Docker image from Docker Hub or local builds:
```bash
sandbox --image alpine:latest
sandbox --image myregistry.com/custom:v1
sandbox --image my-local-image:dev
```

### Volumes
Temporary volumes are managed automatically:
- Created: Before container launch
- Mounted: Read-write mode
- Cleaned: After changes are committed

### Future Enhancements
Potential future features (not yet implemented):
- Network isolation flags
- Resource limits (--memory, --cpus)
- Volume persistence (--keep-volume)
- Multiple volume mounts
- Custom entrypoint

## COMPARISON WITH ALTERNATIVES

| Feature | sandbox | docker run | chroot |
|---------|---------|------------|--------|
| Vault Integration | Native | Manual | N/A |
| Change Tracking | Automatic | Manual | N/A |
| Isolation Level | Container | Container | Process |
| Portability | Any Docker image | Any Docker image | Host-dependent |
| Overhead | Low | Low | Minimal |

## EXAMPLES WITH WORKFLOWS

### Python Development
```bash
# Create virtual environment and install deps
sandbox --image python:3.11 --prefix /home/project --cmd "
  python -m venv .venv &&
  source .venv/bin/activate &&
  pip install -r requirements.txt &&
  pytest tests/
"
```

### Node.js Build
```bash
# Build a Node.js application
sandbox --image node:20 --prefix /home/webapp --cmd "
  npm ci &&
  npm run build &&
  npm run test
" --uid 1000
```

### Database Migrations
```bash
# Run database migrations in isolation
sandbox --image postgres:15 --prefix /home/migrations --cmd "
  psql -f schema.sql &&
  psql -f migrations/*.sql
"
```

## SEE ALSO
- **docker**(1) - Docker container runtime
- **ash**(1) - Agent shell
- **claude**(1) - Claude Code in sandbox

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
