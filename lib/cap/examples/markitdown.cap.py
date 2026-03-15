#!/usr/bin/env cap
# ---
# name: markitdown
# description: Convert a file to markdown using Microsoft MarkItDown.
# dependencies: ['pypi:markitdown[pdf,youtube-transcription]']
# platform: linux/amd64
# network: ['*']
# access: ['$@']
# ---
import sys
from markitdown import MarkItDown

if len(sys.argv) < 2:
    print("Usage: markitdown <file>", file=sys.stderr)
    sys.exit(1)

result = MarkItDown().convert(sys.argv[1])
print(result.text_content)
