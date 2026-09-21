#!/usr/bin/env python3
"""Build/check the pinned ComSee toolchain and run the local student tool."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any
import uuid

try:
    from .comsee_core import (
        ConfigurationError,
        prepare_output_destination,
        run_bounded,
    )
except ImportError:  # direct execution from an extracted kit
    from comsee_core import (  # type: ignore[no-redef]
        ConfigurationError,
        prepare_output_destination,
        run_bounded,
    )


KIT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = KIT_ROOT / "infra/toolchain-lock.json"
CONTAINERFILE = KIT_ROOT / "infra/Containerfile.toolchain"


class DockerToolError(RuntimeError):
    pass


def load_lock() -> dict[str, Any]:
    try:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DockerToolError(f"cannot load toolchain lock: {exc}") from exc
    expected_packages = {"gcc-14", "libc6-dev", "binutils", "python3"}
    if (lock.get("schema_version") != 1 or
            lock.get("platform") != "linux/amd64" or
            set(lock.get("packages", {})) != expected_packages):
        raise DockerToolError("toolchain lock has an unsupported shape")
    if not str(lock.get("base_image", "")).startswith(
        "debian:13-slim@sha256:"
    ):
        raise DockerToolError("toolchain base image is not digest-pinned")
    return lock


def build_command(lock: dict[str, Any]) -> list[str]:
    packages = lock["packages"]
    return [
        "docker", "build", "--platform", lock["platform"], "--pull=false",
        "--tag", lock["image_tag"], "--file", str(CONTAINERFILE),
        "--build-arg", f"DEBIAN_SNAPSHOT={lock['debian_snapshot']}",
        "--build-arg", f"GCC14_PACKAGE_VERSION={packages['gcc-14']}",
        "--build-arg", f"LIBC_DEV_PACKAGE_VERSION={packages['libc6-dev']}",
        "--build-arg", f"BINUTILS_PACKAGE_VERSION={packages['binutils']}",
        "--build-arg", f"PYTHON3_PACKAGE_VERSION={packages['python3']}",
        str(KIT_ROOT / "infra"),
    ]


def _run(
    command: list[str],
    *,
    timeout: int,
    stdout_limit: int = 16 << 20,
    stderr_limit: int = 16 << 20,
    cleanup_container: str | None = None,
):
    try:
        result = run_bounded(
            command,
            wall_seconds=timeout,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
        )
    except OSError as exc:
        raise DockerToolError(f"cannot run {command[0]}: {exc}") from exc
    if (result.timed_out or result.output_limited) and cleanup_container:
        try:
            run_bounded(
                ["docker", "rm", "--force", cleanup_container],
                wall_seconds=30,
                stdout_limit=1 << 20,
                stderr_limit=1 << 20,
            )
        except OSError:
            pass
    if result.timed_out:
        raise DockerToolError(f"command timed out after {timeout}s: {command[0]}")
    if result.output_limited:
        raise DockerToolError(f"command output exceeded its limit: {command[0]}")
    return result


def _checked(command: list[str], *, timeout: int, cleanup_container: str | None = None):
    result = _run(command, timeout=timeout, cleanup_container=cleanup_container)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace")[-8000:]
        raise DockerToolError(
            f"command exited {result.returncode}: {' '.join(command[:4])}\n{stderr}"
        )
    return result


def build_image(lock: dict[str, Any]) -> dict[str, object]:
    _checked(build_command(lock), timeout=1200)
    return smoke_image(lock)


def smoke_image(lock: dict[str, Any]) -> dict[str, object]:
    image_ids = _checked([
        "docker", "image", "ls", "--no-trunc", "--quiet", lock["image_tag"],
    ], timeout=60).stdout.decode("ascii", "strict").splitlines()
    if len(image_ids) != 1 or not image_ids[0].startswith("sha256:"):
        raise DockerToolError("toolchain tag does not identify exactly one local image")
    image_ref = image_ids[0]
    inspect = json.loads(_checked([
        "docker", "image", "inspect", image_ref,
    ], timeout=60).stdout)[0]
    if (inspect.get("Os"), inspect.get("Architecture")) != ("linux", "amd64"):
        raise DockerToolError("toolchain image is not linux/amd64")
    labels = (inspect.get("Config") or {}).get("Labels") or {}
    expected_labels = {
        "org.comsee.debian.snapshot": lock["debian_snapshot"],
        "org.comsee.toolchain.gcc14": lock["packages"]["gcc-14"],
        "org.comsee.toolchain.libc6-dev": lock["packages"]["libc6-dev"],
        "org.comsee.toolchain.binutils": lock["packages"]["binutils"],
        "org.comsee.toolchain.python3": lock["packages"]["python3"],
        "org.opencontainers.image.base.digest": lock["base_image"].split("@", 1)[1],
    }
    if any(labels.get(key) != value for key, value in expected_labels.items()):
        raise DockerToolError("toolchain image labels differ from the lock")

    lock["_image_ref"] = image_ref
    name = _container_name()
    versions = _checked(container_command(lock, [
        "sh", "-c",
        "dpkg-query -W -f='${Package}=${Version}\\n' gcc-14 libc6-dev binutils python3; "
        "gcc-14 --version | head -1; python3 --version; uname -sm",
    ], name=name), timeout=60, cleanup_container=name).stdout.decode(
        "utf-8", "replace"
    ).splitlines()
    installed: dict[str, str] = {}
    for line in versions[:4]:
        if "=" not in line:
            raise DockerToolError("toolchain package-version smoke check failed")
        package, version = line.split("=", 1)
        installed[package] = version
    if (len(versions) != 7 or installed != lock["packages"] or
            not versions[4].startswith("gcc-14 ") or
            not versions[5].startswith("Python 3.13") or
            versions[6] != "Linux x86_64"):
        raise DockerToolError("toolchain version/platform smoke check failed")
    return {
        "outcome": "pass",
        "image": lock["image_tag"],
        "image_id": inspect.get("Id"),
        "platform": "linux/amd64",
        "versions": versions,
    }


def container_command(
    lock: dict[str, Any],
    command: list[str],
    *,
    mounts: list[tuple[Path, str, bool]] | None = None,
    workdir: str | None = None,
    name: str | None = None,
) -> list[str]:
    if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        raise DockerToolError(
            "the current Docker helper supports Linux and macOS hosts; Windows is unverified"
        )
    argv = [
        "docker", "run", "--rm", "--platform", lock["platform"],
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "64",
        "--memory", "1g", "--memory-swap", "1g",
        "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=64m",
        "--user", f"{os.getuid()}:{os.getgid()}",
    ]
    if name:
        argv.extend(["--name", name])
    for source, destination, readonly in mounts or []:
        source = source.resolve(strict=True)
        if "," in str(source):
            raise DockerToolError("mounted paths must not contain commas")
        mode = ",readonly" if readonly else ""
        argv.extend([
            "--mount", f"type=bind,src={source},dst={destination}{mode}",
        ])
    if workdir:
        argv.extend(["--workdir", workdir])
    argv.append(str(lock.get("_image_ref", lock["image_tag"])))
    argv.extend(command)
    return argv


def _container_name() -> str:
    return f"comsee-student-{os.getpid()}-{uuid.uuid4().hex[:12]}"


def run_tool(lock: dict[str, Any], args: argparse.Namespace) -> int:
    if args.source_root.is_symlink():
        raise DockerToolError("source root must not be a symlink")
    source_root = args.source_root.resolve(strict=True)
    requested_output = args.output.absolute() if args.output else (
        Path.cwd() / f"build/{args.challenge}/solution"
    )
    output = prepare_output_destination(KIT_ROOT, source_root, requested_output)
    output_parent = output.parent.resolve(strict=True)
    mounts = [
        (KIT_ROOT, "/kit", True),
        (source_root, "/workspace", True),
        (output_parent, "/output", False),
    ]
    tool_args = [args.action, args.challenge]
    if args.action in ("build", "validate"):
        tool_args.extend([
            "--source-root", "/workspace",
            "--output", f"/output/{output.name}",
        ])
    name = _container_name()
    command = container_command(
        lock,
        ["python3", "/kit/student/comsee_tool.py", *tool_args],
        mounts=mounts,
        workdir="/workspace",
        name=name,
    )
    result = _run(command, timeout=120, cleanup_container=name)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


def run_query(lock: dict[str, Any], args: argparse.Namespace) -> int:
    binary = args.binary.resolve(strict=True)
    mounts = [(KIT_ROOT, "/kit", True), (binary.parent, "/binary", True)]
    tool_args = [
        "query", args.challenge,
        "--binary", f"/binary/{binary.name}",
        "--request", args.request,
    ]
    name = _container_name()
    result = _run(container_command(
        lock,
        ["python3", "/kit/student/comsee_tool.py", *tool_args],
        mounts=mounts,
        name=name,
    ), timeout=30, cleanup_container=name)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


_TUTORIAL_FAILURES = {
    64: "--input must be an even-length hexadecimal string",
    65: "--input contains a character that is not a hexadecimal digit",
}


def run_tutorial(lock: dict[str, Any], args: argparse.Namespace) -> int:
    requested = args.output.absolute() if args.output else (
        Path.cwd() / "build/tutorial-xor"
    )
    output = prepare_output_destination(KIT_ROOT, KIT_ROOT, requested)
    name = _container_name()
    command = container_command(
        lock,
        [
            "gcc-14", "-std=c17", "-O1", "-Wall", "-Wextra", "-Werror",
            "/kit/tutorial/X01-xor/main.c",
            "/kit/tutorial/X01-xor/reference.c",
            "-o", f"/output/{output.name}",
        ],
        mounts=[(KIT_ROOT, "/kit", True), (output.parent, "/output", False)],
        name=name,
    )
    result = _run(command, timeout=120, cleanup_container=name)
    if result.returncode == 0:
        os.chmod(output, 0o755)
        run_name = _container_name()
        executed = _run(container_command(
            lock,
            [f"/output/{output.name}", args.input],
            mounts=[(output.parent, "/output", True)],
            name=run_name,
        ), timeout=30, cleanup_container=run_name)
        if executed.returncode != 0:
            sys.stdout.buffer.write(executed.stdout)
            sys.stderr.buffer.write(executed.stderr)
            # main.c exits 64 on an odd-length argument and 65 on a bad hex
            # digit, printing nothing. Report the reason instead of failing
            # silently.
            print(json.dumps({
                "outcome": "invalid_input" if executed.returncode in (64, 65)
                           else "runtime_failure",
                "binary": str(output),
                "input": args.input,
                "returncode": executed.returncode,
                "detail": _TUTORIAL_FAILURES.get(
                    executed.returncode, "the tutorial binary exited non-zero"
                ),
            }, sort_keys=True, separators=(",", ":")))
            return executed.returncode
        print(json.dumps({
            "outcome": "pass",
            "binary": str(output),
            "input": args.input,
            "output": executed.stdout.decode("ascii", "strict").strip(),
        }, sort_keys=True, separators=(",", ":")))
    else:
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
    return result.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("build-image", help="build the pinned toolchain image")
    subparsers.add_parser("check-image", help="verify image labels and versions")
    tutorial = subparsers.add_parser("tutorial", help="build the unscored tutorial")
    tutorial.add_argument("--output", type=Path)
    tutorial.add_argument("--input", default="deadbeef")
    for action in ("build", "validate"):
        command = subparsers.add_parser(action)
        command.add_argument("challenge")
        command.add_argument("--source-root", type=Path, default=Path.cwd())
        command.add_argument("--output", type=Path)
    query = subparsers.add_parser("query")
    query.add_argument("challenge")
    query.add_argument("--binary", type=Path, required=True)
    query.add_argument("--request", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not shutil.which("docker"):
            raise DockerToolError("docker command is not installed")
        lock = load_lock()
        if args.action == "build-image":
            result = build_image(lock)
        elif args.action == "check-image":
            result = smoke_image(lock)
        elif args.action in ("build", "validate"):
            smoke_image(lock)
            return run_tool(lock, args)
        elif args.action == "tutorial":
            smoke_image(lock)
            return run_tutorial(lock, args)
        else:
            smoke_image(lock)
            return run_query(lock, args)
    except (DockerToolError, OSError, ValueError) as exc:
        result = {"outcome": "infrastructure_failure", "detail": str(exc)}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
