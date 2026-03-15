#!/usr/bin/env cap
# ---
# name: vim
# description: Edit files with vim in a sandboxed container.
# dependencies: []
# network: disable
# access: ['$@:rw']
# ---

import os
import sys

args = sys.argv[1:] or ["."]
os.execvp("vim", ["vim"] + args)
