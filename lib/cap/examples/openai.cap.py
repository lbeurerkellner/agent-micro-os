#!/bin/cap
# ---
# name: openai
# description: Run a prompt against the OpenAI chat API and print the response
# dependencies: ['pypi:openai']
# secrets: ['OPENAI_API_KEY']
# network: ['api.openai.com']
# ---
import os
import sys

from openai import OpenAI

prompt = " ".join(sys.argv[1:])
if not prompt:
    print("Usage: openai <prompt>", file=sys.stderr)
    sys.exit(1)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

stream = client.chat.completions.create(
    model="gpt-5-nano",
    messages=[{"role": "user", "content": prompt}],
    stream=True,
)

for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="", flush=True)

print()
