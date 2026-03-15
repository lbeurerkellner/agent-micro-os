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
