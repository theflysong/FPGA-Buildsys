"""Print shell completion candidates without configuring a project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from completion_candidates import candidates
from util import ConfigError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="read a JSON word array from stdin and return a JSON candidate array")
    parser.add_argument("words", nargs=argparse.REMAINDER,
                        help="command arguments including the unfinished final word")


def run(arguments: argparse.Namespace) -> int:
    root = (arguments.project or Path.cwd()).expanduser().resolve()
    words = arguments.words
    if arguments.json:
        try:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            words = json.load(stream)
        except (ValueError, UnicodeError) as exc:
            raise ConfigError(f"invalid completion JSON: {exc}") from exc
        if not isinstance(words, list) or not all(isinstance(word, str) for word in words):
            raise ConfigError("completion JSON must be an array of strings")
    elif words[:1] == ["--"]:
        words = words[1:]
    result = candidates(root, words)
    if arguments.json:
        print(json.dumps(result))
    else:
        for item in result:
            print(item)
    return 0
