#!/usr/bin/env python3
"""Dependency-free build, query, and public-validation core for ComSee.

This module executes student-built programs and therefore provides resource
bounds, not a security boundary. The supported release workflow runs it inside
the published local tool environment.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from typing import Any, Sequence


class ConfigurationError(ValueError):
    """The kit, manifest, challenge, or source layout is invalid."""


class StrictJSONError(ValueError):
    """A JSON document violates the exact public transport rules."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limited: bool = False


@dataclass(frozen=True)
class Case:
    name: str
    request: object
    expected: object


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> None:
    raise StrictJSONError(f"non-integer number: {value}")


def _reject_constant(value: str) -> None:
    raise StrictJSONError(f"invalid number: {value}")


def _validate_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise StrictJSONError("unpaired Unicode surrogate")


def loads_exact(data: bytes | str) -> Any:
    """Parse one strict UTF-8 JSON document with exact integers."""
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8", "strict")
        if data.startswith("\ufeff"):
            raise StrictJSONError("UTF-8 BOM is not permitted")
        value = json.loads(
            data,
            object_pairs_hook=_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
        pending: list[tuple[Any, int]] = [(value, 0)]
        while pending:
            current, depth = pending.pop()
            if depth > 256:
                raise StrictJSONError("JSON nesting exceeds 256")
            if isinstance(current, dict):
                for key in current:
                    _validate_string(key)
                pending.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, list):
                pending.extend((item, depth + 1) for item in current)
            elif isinstance(current, str):
                _validate_string(current)
        return value
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, ValueError) as exc:
        raise StrictJSONError(str(exc)) from exc


def semantic_equal(left: Any, right: Any) -> bool:
    pending = [(left, right)]
    while pending:
        first, second = pending.pop()
        if type(first) is not type(second):
            return False
        if isinstance(first, dict):
            if first.keys() != second.keys():
                return False
            pending.extend((first[key], second[key]) for key in first)
        elif isinstance(first, list):
            if len(first) != len(second):
                return False
            pending.extend(zip(first, second, strict=True))
        elif first != second:
            return False
    return True


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_bounded(
    argv: Sequence[str],
    *,
    input_bytes: bytes = b"",
    cwd: Path | None = None,
    wall_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
) -> ProcessResult:
    """Run one local process with bounded I/O and a wall deadline."""
    deadline = time.monotonic() + wall_seconds
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    assert process.stdin and process.stdout and process.stderr
    for stream in (process.stdin, process.stdout, process.stderr):
        os.set_blocking(stream.fileno(), False)

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    if input_bytes:
        selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    else:
        process.stdin.close()

    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    input_offset = 0
    timed_out = False
    output_limited = False
    killed = False
    drain_deadline: float | None = None

    def stop(*, timeout: bool) -> None:
        nonlocal killed, timed_out, drain_deadline
        if killed:
            return
        killed = True
        timed_out = timeout
        drain_deadline = time.monotonic() + 1.0
        _kill_group(process)
        try:
            selector.unregister(process.stdin)
        except (KeyError, ValueError):
            pass
        if not process.stdin.closed:
            process.stdin.close()

    try:
        while True:
            output_open = any(
                key.data in ("stdout", "stderr")
                for key in selector.get_map().values()
            )
            if process.poll() is not None and not output_open:
                break
            now = time.monotonic()
            if not killed and now >= deadline:
                stop(timeout=not output_limited)
            if killed and drain_deadline is not None and now >= drain_deadline:
                for key in list(selector.get_map().values()):
                    if key.data in ("stdout", "stderr"):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                break

            if selector.get_map():
                events = selector.select(0.05)
            else:
                time.sleep(0.01)
                events = []
            for key, _mask in events:
                if key.data == "stdin":
                    try:
                        written = os.write(
                            key.fd,
                            input_bytes[input_offset:input_offset + 65536],
                        )
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        written = 0
                        input_offset = len(input_bytes)
                    else:
                        input_offset += written
                    if input_offset == len(input_bytes) or process.poll() is not None:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue

                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                name = key.data
                room = limits[name] - len(chunks[name])
                if len(data) > room:
                    if room > 0:
                        chunks[name].extend(data[:room])
                    output_limited = True
                    stop(timeout=False)
                else:
                    chunks[name].extend(data)

        try:
            returncode = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            stop(timeout=not output_limited)
            returncode = process.wait(timeout=1)
    except BaseException:
        stop(timeout=False)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        raise
    finally:
        for key in list(selector.get_map().values()):
            selector.unregister(key.fileobj)
            key.fileobj.close()
        selector.close()

    return ProcessResult(
        returncode=returncode,
        stdout=bytes(chunks["stdout"]),
        stderr=bytes(chunks["stderr"]),
        timed_out=timed_out,
        output_limited=output_limited,
    )


def load_manifest(kit_root: Path) -> dict[str, object]:
    path = kit_root / "student/public_manifest.json"
    try:
        manifest = loads_exact(path.read_bytes())
    except (OSError, StrictJSONError) as exc:
        raise ConfigurationError(f"cannot load public manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ConfigurationError("unsupported public manifest")
    challenges = manifest.get("challenges")
    if not isinstance(challenges, list) or not challenges:
        raise ConfigurationError("public manifest has no challenges")
    ids = [item.get("id") for item in challenges if isinstance(item, dict)]
    if len(ids) != len(challenges) or len(ids) != len(set(ids)):
        raise ConfigurationError("public manifest challenge IDs are invalid")
    return manifest


def challenge_config(manifest: dict[str, object], challenge_id: str) -> dict[str, object]:
    for challenge in manifest["challenges"]:
        if challenge.get("id") == challenge_id:
            return challenge
    raise ConfigurationError(f"challenge is not present in this kit: {challenge_id}")


def load_cases(path: Path) -> list[Case]:
    try:
        raw = loads_exact(path.read_bytes())
    except (OSError, StrictJSONError) as exc:
        raise ConfigurationError(f"cannot load public cases: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ConfigurationError("public case set must be a nonempty array")
    cases: list[Case] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {"name", "request", "expected"}:
            raise ConfigurationError(f"public case {index} has invalid fields")
        name = item["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ConfigurationError(f"public case {index} has an invalid name")
        names.add(name)
        cases.append(Case(name, item["request"], item["expected"]))
    return cases


def _limits(manifest: dict[str, object]) -> dict[str, int]:
    raw = manifest.get("limits")
    required = {
        "compile_wall_seconds", "case_wall_seconds", "stdout_bytes", "stderr_bytes",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise ConfigurationError("public manifest limits are invalid")
    if any(type(raw[key]) is not int or raw[key] <= 0 for key in required):
        raise ConfigurationError("public manifest limits must be positive integers")
    return raw


def prepare_output_destination(
    kit_root: Path,
    source_root: Path,
    destination: Path,
) -> Path:
    """Resolve and create a safe output parent without touching source files.

    Outputs inside either the kit or the source workspace are restricted to that
    root's ``build/`` directory. An output elsewhere is allowed, but its nearest
    existing parent is resolved before applying the policy so a directory alias
    cannot hide an overwrite of an input tree.
    """
    try:
        kit_root = kit_root.resolve(strict=True)
        source_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve kit or source root: {exc}") from exc

    lexical = destination.absolute()
    if lexical.is_symlink():
        raise ConfigurationError("binary output must not be a symlink")
    existing = lexical.parent
    missing: list[str] = []
    while not existing.exists():
        missing.append(existing.name)
        parent = existing.parent
        if parent == existing:
            raise ConfigurationError("binary output has no existing ancestor")
        existing = parent
    if existing.is_symlink():
        raise ConfigurationError("binary output parent must not be a symlink")
    try:
        resolved_parent = existing.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve output directory: {exc}") from exc
    for name in reversed(missing):
        resolved_parent /= name
    candidate = resolved_parent / lexical.name

    for root in {kit_root, source_root}:
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if not relative.parts or relative.parts[0] != "build":
            raise ConfigurationError(
                "outputs inside the kit or source workspace are allowed only "
                "under build/; run this command from the repository root"
            )

    resolved_parent.mkdir(parents=True, exist_ok=True)
    if resolved_parent.is_symlink():
        raise ConfigurationError("binary output parent must not be a symlink")
    return resolved_parent.resolve(strict=True) / lexical.name


def build_solution(
    kit_root: Path,
    source_root: Path,
    challenge_id: str,
    destination: Path,
) -> dict[str, object]:
    if kit_root.is_symlink() or source_root.is_symlink():
        raise ConfigurationError("kit and source roots must not be symlinks")
    manifest = load_manifest(kit_root)
    config = challenge_config(manifest, challenge_id)
    limits = _limits(manifest)
    target = manifest.get("target")
    if not isinstance(target, dict) or target.get("c_standard") != "c17":
        raise ConfigurationError("public manifest target is invalid")
    compiler = target.get("compiler")
    optimization = config.get("optimization")
    if not isinstance(compiler, str) or not compiler or optimization not in ("-O1", "-O2"):
        raise ConfigurationError("public build recipe is invalid")

    try:
        kit_root = kit_root.resolve(strict=True)
        source_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve kit or source root: {exc}") from exc
    challenge_dir = source_root / f"solutions/{challenge_id}"
    if (source_root / "solutions").is_symlink() or challenge_dir.is_symlink():
        raise ConfigurationError("solution directory symlinks are forbidden")
    solution = challenge_dir / "solution.c"
    if not solution.is_file() or solution.is_symlink():
        raise ConfigurationError(f"missing regular solutions/{challenge_id}/solution.c")
    sources = sorted(
        path for path in challenge_dir.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix == ".c"
    )
    if not sources:
        raise ConfigurationError(f"no C sources for {challenge_id}")
    for entry in challenge_dir.iterdir():
        if entry.is_symlink() or not entry.is_file() or entry.suffix not in (".c", ".h"):
            raise ConfigurationError(f"unexpected source entry: {entry.name}")
    common = source_root / "common"
    if common.exists():
        if common.is_symlink() or not common.is_dir():
            raise ConfigurationError("common must be a regular directory")
        for entry in common.iterdir():
            if entry.is_symlink() or not entry.is_file() or entry.suffix != ".h":
                raise ConfigurationError(f"unexpected common entry: {entry.name}")

    shared_sources = [
        kit_root / "shared/src/cli.c",
        kit_root / "shared/src/comsee_json.c",
        kit_root / "shared/src/comsee_dom.c",
    ]
    required_files = [kit_root / "shared/include/comsee.h",
                      kit_root / "shared/include/comsee_json.h", *shared_sources]
    if any((kit_root / part).is_symlink()
           for part in ("shared", "shared/include", "shared/src")):
        raise ConfigurationError("shared build directory symlinks are forbidden")
    if any(not path.is_file() or path.is_symlink() for path in required_files):
        raise ConfigurationError("shared build files are missing or unsafe")

    destination = prepare_output_destination(
        kit_root, source_root, destination
    )
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / "solution"
        command = [
            compiler, "-std=c17", optimization, "-Wall", "-Wextra", "-Werror",
            "-I", str(kit_root / "shared/include"),
            "-I", str(challenge_dir),
        ]
        if common.is_dir():
            command.extend(["-I", str(common)])
        command.extend(map(str, [*shared_sources, *sources]))
        command.extend(["-o", str(staged)])
        try:
            result = run_bounded(
                command,
                wall_seconds=limits["compile_wall_seconds"],
                stdout_limit=1 << 20,
                stderr_limit=1 << 20,
            )
        except OSError as exc:
            return {
                "outcome": "infrastructure_failure",
                "detail": f"cannot start compiler {compiler}: {exc}",
            }
        if result.timed_out:
            return {"outcome": "compilation_failure", "detail": "compiler timeout"}
        if result.output_limited:
            return {"outcome": "compilation_failure", "detail": "compiler output limit"}
        if result.returncode != 0:
            return {
                "outcome": "compilation_failure",
                "detail": result.stderr.decode("utf-8", "replace"),
            }
        os.chmod(staged, 0o755)
        os.replace(staged, destination)
    return {"outcome": "pass", "binary": str(destination)}


def query_binary(
    kit_root: Path,
    challenge_id: str,
    binary: Path,
    request: object,
) -> dict[str, object]:
    manifest = load_manifest(kit_root)
    challenge_config(manifest, challenge_id)
    limits = _limits(manifest)
    return _query_process(
        binary,
        request,
        wall_seconds=limits["case_wall_seconds"],
        stdout_limit=limits["stdout_bytes"],
        stderr_limit=limits["stderr_bytes"],
    )


def _query_process(
    binary: Path,
    request: object,
    *,
    wall_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
) -> dict[str, object]:
    input_bytes = json.dumps(request, separators=(",", ":")).encode() + b"\n"
    try:
        result = run_bounded(
            [str(binary)],
            input_bytes=input_bytes,
            wall_seconds=wall_seconds,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
        )
    except OSError as exc:
        return {"outcome": "infrastructure_failure", "detail": str(exc)}
    detail = {
        "request": request,
        "stderr": result.stderr.decode("utf-8", "replace"),
    }
    if result.timed_out:
        return {"outcome": "timeout", **detail}
    if result.output_limited:
        return {"outcome": "resource_output_limit", **detail}
    if result.returncode != 0:
        return {"outcome": "runtime_failure", "returncode": result.returncode, **detail}
    try:
        value = loads_exact(result.stdout)
    except StrictJSONError as exc:
        return {"outcome": "invalid_output", "detail": str(exc), **detail}
    return {"outcome": "pass", "result": value, **detail}


def evaluate_cases(
    binary: Path,
    cases: Sequence[Case],
    *,
    wall_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
) -> dict[str, object]:
    """Evaluate cases with the same fresh-process core used by public/private tools."""
    if not cases:
        raise ConfigurationError("case set must not be empty")
    report: dict[str, object] = {
        "outcome": "pass",
        "passed": 0,
        "total": len(cases),
        "cases": [],
    }
    for case in cases:
        result = _query_process(
            binary,
            case.request,
            wall_seconds=wall_seconds,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
        )
        if result["outcome"] != "pass":
            report["outcome"] = result["outcome"]
            report["detail"] = case.name
            report["cases"].append({"name": case.name, **result})
            return report
        if not semantic_equal(result["result"], case.expected):
            report["outcome"] = "wrong_answer"
            report["detail"] = case.name
            report["cases"].append({
                "name": case.name,
                "outcome": "wrong_answer",
                "request": case.request,
                "expected": case.expected,
                "actual": result["result"],
            })
            return report
        report["passed"] += 1
        report["cases"].append({"name": case.name, "outcome": "pass"})
    return report


def validate_binary(
    kit_root: Path,
    challenge_id: str,
    binary: Path,
) -> dict[str, object]:
    manifest = load_manifest(kit_root)
    challenge_config(manifest, challenge_id)
    limits = _limits(manifest)
    cases = load_cases(kit_root / f"challenges/{challenge_id}/public/cases.json")
    report = evaluate_cases(
        binary,
        cases,
        wall_seconds=limits["case_wall_seconds"],
        stdout_limit=limits["stdout_bytes"],
        stderr_limit=limits["stderr_bytes"],
    )
    report["challenge"] = challenge_id
    return report
