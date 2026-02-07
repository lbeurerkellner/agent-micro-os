# claude(1) - Claude Code Integration

## NAME
**claude** - Run Claude Code AI assistant in a sandboxed container environment

## SYNOPSIS
```
claude [claude-code-options...]
```

## DESCRIPTION
**claude** launches Claude Code (Anthropic's AI coding assistant) inside a Docker container with full access to the agent vault filesystem. This enables AI-assisted development while maintaining isolation and integration with the vault's versioning system.

The command automatically:
1. Builds or reuses a Claude Code Docker image
2. Mounts the vault at `/workspace` in the container
3. Configures Claude Code with authentication
4. Launches the interactive Claude Code session
5. Commits any changes back to the vault on exit

## PREREQUISITES

### OAuth Token
The `CLAUDE_CODE_OAUTH_TOKEN` environment variable must be set:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="your-token-here"
```

To obtain a token:
1. Visit https://claude.ai
2. Sign in to your account
3. Navigate to Settings → Developer
4. Generate an OAuth token

### Docker
Docker must be installed and the Docker daemon must be running.

## OPERATION

### Image Management
The command uses a Docker image tagged with a hash of the Dockerfile content:
- **Image tag format**: `claude-sandbox:<hash>`
- **Cache behavior**: Image is rebuilt only when Dockerfile changes
- **Build location**: `sandboxes/Dockerfile.claude`

### Configuration
Claude Code configuration is stored in the vault at:
- **Path**: `/agent/claude/claude.json`
- **Auto-creation**: Minimal config created if not present
- **Persistence**: Configuration persists across sessions

**Default configuration**:
```json
{
    "numStartups": 1,
    "hasCompletedOnboarding": true
}
```

### Container Setup
- **Mount point**: `/workspace` (entire vault)
- **Working directory**: `/workspace`
- **User ID**: 1000 (non-root)
- **Environment variables**:
  - `CLAUDE_CONFIG_DIR=/workspace/agent/claude`
  - `CLAUDE_CODE_OAUTH_TOKEN=<your-token>`

## OPTIONS

All arguments are passed directly to the `claude` command inside the container:

```bash
# Open interactive chat
claude

# Run in specific directory
claude --cwd /workspace/project

# Execute with specific prompt
claude "explain this code"

# Use specific model
claude --model sonnet
```

Refer to Claude Code documentation for available options.

## EXAMPLES

### Basic Usage
```bash
claude
```
Launches interactive Claude Code session.

### Work on Specific Project
```bash
claude --cwd /workspace/home/project
```
Opens Claude Code with working directory set to project.

### Quick Query
```bash
claude "write a Python function to parse JSON"
```
Get a response without entering interactive mode.

### Code Review
```bash
claude "review the code in /workspace/home/app.py"
```
Ask Claude to review specific files.

## USE CASES

### Code Generation
```bash
claude "create a REST API with FastAPI for user management"
```

### Debugging
```bash
claude "why is this Python script throwing a KeyError?"
```

### Refactoring
```bash
claude "refactor /workspace/home/legacy.py to use modern Python features"
```

### Documentation
```bash
claude "add docstrings to all functions in /workspace/home/utils.py"
```

### Testing
```bash
claude "write pytest tests for the Calculator class"
```

### Code Explanation
```bash
claude "explain how the authentication system works"
```

## VAULT INTEGRATION

### File Access
Claude Code can read and write files in the vault:
- **Read**: Access any file in `/workspace`
- **Write**: Create, modify, or delete files
- **Commit**: Changes automatically committed on exit

### Persistence
All Claude Code interactions are preserved:
- **Chat history**: Stored in `/agent/claude/`
- **Generated code**: Written to vault
- **Configuration**: Persists across sessions

### Versioning
File changes made by Claude are tracked:
- **Author**: Changes attributed to current user
- **Timestamp**: Each modification is timestamped
- **History**: Use `fslog` to view changes made by Claude

## CONFIGURATION FILES

### Claude Config (`/agent/claude/claude.json`)
```json
{
    "numStartups": 1,
    "hasCompletedOnboarding": true,
    "firstStartTime": "2026-02-07T09:49:54.448Z"
}
```

### Custom Settings
You can customize Claude Code by modifying the config file:
```bash
edit /agent/claude/claude.json
```

## TECHNICAL DETAILS

### Dockerfile
Located at `sandboxes/Dockerfile.claude`, the image includes:
- Base OS (Ubuntu/Debian)
- Claude Code binary
- Required dependencies
- Configuration tools

### Hash-Based Caching
The image tag includes a SHA-256 hash of the Dockerfile:
- **Format**: `claude-sandbox:abc123def456`
- **Rebuild trigger**: Any change to Dockerfile content
- **Cache hit**: Existing image reused if hash matches

### Sandbox Integration
Claude runs through the `sandbox` command:
```python
await sandbox.run(
    "--image", image_name,
    "--cmd", "claude " + " ".join(args),
    "--mount", "/workspace",
    "--uid", "1000",
    env=env,
    readonly=False
)
```

## ENVIRONMENT

### Required Environment Variables
- `CLAUDE_CODE_OAUTH_TOKEN`: OAuth token for authentication

### Container Environment
- `CLAUDE_CONFIG_DIR`: Path to Claude config directory
- `CLAUDE_CODE_OAUTH_TOKEN`: Passed from host environment

## SECURITY

### Authentication
- OAuth token required for Claude API access
- Token passed securely via environment variable
- Token not stored in vault

### Isolation
- Runs in Docker container
- Isolated from host system
- Network access for Claude API calls

### Permissions
- Runs as UID 1000 (non-root)
- Full read/write access to vault
- No access to host filesystem

## LIMITATIONS

1. **Network Required**: Must have internet access for Claude API
2. **Token Expiry**: OAuth tokens expire and need renewal
3. **Resource Usage**: Claude Code requires memory and CPU
4. **Image Size**: Docker image can be large (500MB+)

## TROUBLESHOOTING

### Token Not Set
```
Error: CLAUDE_CODE_OAUTH_TOKEN environment variable is not set.
```
**Solution**: Export the token before running:
```bash
export CLAUDE_CODE_OAUTH_TOKEN="your-token"
```

### Docker Not Running
```
Error: Cannot connect to Docker daemon
```
**Solution**: Start Docker:
```bash
sudo systemctl start docker  # Linux
# or
open -a Docker  # macOS
```

### Image Build Fails
**Solution**: Check Dockerfile and Docker logs:
```bash
docker build -f sandboxes/Dockerfile.claude .
```

### Permission Errors
**Solution**: Verify UID 1000 has access, or modify `--uid` parameter in source code.

## EXIT STATUS
- **0**: Success
- **1**: Error (missing token, Docker unavailable, etc.)
- *Claude exit code*: Returns Claude Code's exit status

## FILES
- `sandboxes/Dockerfile.claude` - Docker image definition
- `/agent/claude/claude.json` - Claude configuration (in vault)
- `/agent/claude/` - Claude workspace directory (in vault)

## SEE ALSO
- **sandbox**(1) - Docker container execution
- **ash**(1) - Agent shell

## EXTERNAL RESOURCES
- Claude Code Documentation: https://docs.anthropic.com/claude-code
- Claude AI: https://claude.ai
- Anthropic: https://anthropic.com

## AUTHOR
Written as part of the agentvault project.

## BUGS
Report bugs at: https://github.com/yourusername/agentvault/issues
