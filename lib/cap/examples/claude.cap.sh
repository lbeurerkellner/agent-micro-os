#!/usr/bin/env cap
# ---
# name: claude
# description: Run Claude Code (claude) in a sandboxed container
# dependencies: ['npm:@anthropic-ai/claude-code']
# access: ['$@:rw']
# stateful: true
# ---

claude "$@"
