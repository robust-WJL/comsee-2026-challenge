#!/usr/bin/env python3
"""Build, query, and run public validation for ComSee solutions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from .comsee_core import (
        ConfigurationError,
        StrictJSONError,
        build_solution,
        loads_exact,
        query_binary,
        validate_binary,
    )
except ImportError:  # direct execution from an extracted kit
    from comsee_core import (  # type: ignore[no-redef]
        ConfigurationError,
        StrictJSONError,
        build_solution,
        loads_exact,
        query_binary,
        validate_binary,
    )


KIT_ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="compile one solution")
    build.add_argument("challenge")
    build.add_argument("--source-root", type=Path, default=Path.cwd())
    build.add_argument("--output", type=Path)

    query = subparsers.add_parser("query", help="send one JSON request to a binary")
    query.add_argument("challenge")
    query.add_argument("--binary", type=Path, required=True)
    request_group = query.add_mutually_exclusive_group(required=True)
    request_group.add_argument("--request", help="one JSON request")
    request_group.add_argument("--request-file", type=Path)

    validate = subparsers.add_parser("validate", help="run all public cases")
    validate.add_argument("challenge")
    validate.add_argument("--source-root", type=Path, default=Path.cwd())
    validate.add_argument("--binary", type=Path)
    validate.add_argument("--output", type=Path)
    return parser


def _output_path(challenge: str, supplied: Path | None) -> Path:
    return supplied or Path.cwd() / f"build/{challenge}/solution"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_solution(
                KIT_ROOT,
                args.source_root,
                args.challenge,
                _output_path(args.challenge, args.output),
            )
        elif args.command == "query":
            raw = (
                args.request
                if args.request is not None
                else args.request_file.read_bytes()
            )
            request = loads_exact(raw)
            result = query_binary(
                KIT_ROOT, args.challenge, args.binary, request
            )
        else:
            binary = args.binary
            if binary is None:
                binary = _output_path(args.challenge, args.output)
                result = build_solution(
                    KIT_ROOT,
                    args.source_root,
                    args.challenge,
                    binary,
                )
                if result["outcome"] != "pass":
                    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
                    return 1
            result = validate_binary(KIT_ROOT, args.challenge, binary)
    except (ConfigurationError, StrictJSONError, OSError) as exc:
        result = {"outcome": "infrastructure_failure", "detail": str(exc)}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
