#!/usr/bin/env python3
"""Build and validate source-only ComSee submission ZIP archives.

This module deliberately treats source bytes as opaque data.  It validates the ZIP
container and its paths, but it never extracts files or executes submitted code.
It uses only the Python standard library so the same file can be copied into the
public student kit and imported by organizer tooling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
from typing import Iterable
import zipfile
import zlib


KNOWN_IDS = tuple(f"C{number:02d}" for number in range(1, 18))
MAX_ARCHIVE_BYTES = 1 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024
MAX_FILES = 128
MAX_ENTRIES = 256
MAX_FILE_BYTES = 256 * 1024
MAX_COMPONENT_BYTES = 255

_ALLOWED_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_ALLOWED_FLAG_BITS = 0x0006 | 0x0008 | 0x0800  # DEFLATE options, data descriptor, UTF-8 names
_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_LOCAL_SIGNATURE = 0x04034B50
_EOCD = struct.Struct("<4s4H2LH")
_EOCD_SIGNATURE = b"PK\x05\x06"
_FORBIDDEN_PORTABLE_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class _InvalidArchive(Exception):
    def __init__(self, code: str, message: str, entry: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.entry = entry


class PackagingError(ValueError):
    """Raised when a source tree cannot be safely packaged."""


def _normalise_allowed_ids(allowed_ids: Iterable[str] | None) -> tuple[str, ...]:
    values = KNOWN_IDS if allowed_ids is None else tuple(allowed_ids)
    if not values:
        raise ValueError("allowed_ids must contain at least one challenge ID")
    if len(values) != len(set(values)):
        raise ValueError("allowed_ids contains a duplicate challenge ID")
    unknown = sorted(set(values) - set(KNOWN_IDS))
    if unknown:
        raise ValueError(f"unknown challenge ID: {', '.join(unknown)}")
    return tuple(sorted(values))


def _empty_result(archive_bytes: int, digest: str | None) -> dict[str, object]:
    return {
        "valid": False,
        "sha256": digest,
        "archive_bytes": archive_bytes,
        "attempted_ids": [],
        "entries": [],
        "entry_count": 0,
        "file_count": 0,
        "expanded_bytes": 0,
        "error": None,
    }


def _failure(result: dict[str, object], error: _InvalidArchive) -> dict[str, object]:
    detail: dict[str, str] = {"code": error.code, "message": error.message}
    if error.entry is not None:
        detail["entry"] = error.entry
    result["error"] = detail
    return result


def _read_archive(source: os.PathLike[str] | str | bytes | bytearray | memoryview) -> tuple[bytes, int, str | None]:
    if isinstance(source, (bytes, bytearray, memoryview)):
        size = source.nbytes if isinstance(source, memoryview) else len(source)
        if size > MAX_ARCHIVE_BYTES:
            return b"", size, None
        data = source if isinstance(source, bytes) else bytes(source)
        return data, size, hashlib.sha256(data).hexdigest()

    path = Path(source)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _InvalidArchive("READ_ERROR", f"cannot read archive: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise _InvalidArchive("READ_ERROR", "archive path must be a regular file")
    size = metadata.st_size
    if size > MAX_ARCHIVE_BYTES:
        return b"", size, None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _InvalidArchive("READ_ERROR", f"cannot read archive: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise _InvalidArchive("READ_ERROR", "archive path must remain a regular file")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_ARCHIVE_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_ARCHIVE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        data = b"".join(chunks)
    except OSError as exc:
        raise _InvalidArchive("READ_ERROR", f"cannot read archive: {exc}") from exc
    finally:
        os.close(descriptor)
    if len(data) > MAX_ARCHIVE_BYTES:
        return data, len(data), None
    return data, len(data), hashlib.sha256(data).hexdigest()


def _validate_component(component: str, full_name: str) -> None:
    if component in {"", ".", ".."}:
        raise _InvalidArchive("INVALID_PATH", "path contains an empty or dot component", full_name)
    if component[-1] in {".", " "}:
        raise _InvalidArchive("INVALID_PATH", "path component ends in a dot or space", full_name)
    if len(component.encode("ascii")) > MAX_COMPONENT_BYTES:
        raise _InvalidArchive("INVALID_PATH", f"path component exceeds {MAX_COMPONENT_BYTES} bytes", full_name)
    if any(ord(character) < 32 or ord(character) == 127 or character in _FORBIDDEN_PORTABLE_CHARS for character in component):
        raise _InvalidArchive("INVALID_PATH", "path component contains a non-portable character", full_name)
    stem = component.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise _InvalidArchive("INVALID_PATH", "path uses a Windows reserved name", full_name)


def _validate_name(info: zipfile.ZipInfo, allowed: frozenset[str]) -> tuple[str | None, bool]:
    original = info.orig_filename
    name = info.filename
    if "\x00" in original or "\x00" in name:
        raise _InvalidArchive("INVALID_PATH", "path contains NUL", original)
    try:
        original.encode("ascii")
        name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _InvalidArchive("INVALID_PATH", "path is not ASCII", name) from exc
    if original != name:
        raise _InvalidArchive("INVALID_PATH", "path was altered while parsing", original)
    if not name or "\\" in name or name.startswith("/"):
        raise _InvalidArchive("INVALID_PATH", "path must be relative and use forward slashes", name)
    if len(name) >= 2 and name[0].isalpha() and name[1] == ":":
        raise _InvalidArchive("INVALID_PATH", "drive-prefixed path is forbidden", name)

    is_directory = info.is_dir()
    path_without_slash = name[:-1] if is_directory else name
    parts = path_without_slash.split("/")
    for component in parts:
        _validate_component(component, name)

    if is_directory:
        permitted = {"solutions", "common"}
        permitted.update(f"solutions/{challenge_id}" for challenge_id in allowed)
        if path_without_slash not in permitted:
            raise _InvalidArchive("UNEXPECTED_PATH", "directory is outside permitted source parents", name)
        return None, True

    challenge_id: str | None = None
    if len(parts) == 2 and parts[0] == "common" and parts[1].endswith(".h"):
        pass
    elif (
        len(parts) == 3
        and parts[0] == "solutions"
        and parts[1] in allowed
        and (parts[2].endswith(".c") or parts[2].endswith(".h"))
    ):
        challenge_id = parts[1]
    else:
        raise _InvalidArchive("UNEXPECTED_PATH", "only flat C/H challenge sources and common headers are allowed", name)
    return challenge_id, False


def _validate_attributes(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if info.flag_bits & ~_ALLOWED_FLAG_BITS:
        if info.flag_bits & 0x0001:
            raise _InvalidArchive("ENCRYPTED", "encrypted entries are forbidden", name)
        raise _InvalidArchive("UNSUPPORTED_FLAGS", "entry uses unsupported ZIP flags", name)
    if info.compress_type not in _ALLOWED_METHODS:
        raise _InvalidArchive("UNSUPPORTED_COMPRESSION", "entry is not STORED or DEFLATED", name)
    if info.compress_type != zipfile.ZIP_DEFLATED and info.flag_bits & 0x0006:
        raise _InvalidArchive("UNSUPPORTED_FLAGS", "compression option flags require DEFLATED data", name)

    unix_mode = (info.external_attr >> 16) & 0xFFFF if info.create_system == 3 else 0
    if unix_mode:
        kind = stat.S_IFMT(unix_mode)
        expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
        if kind not in (0, expected):
            raise _InvalidArchive("SPECIAL_FILE", "links and special files are forbidden", name)
        if not info.is_dir() and unix_mode & 0o111:
            raise _InvalidArchive("EXECUTABLE", "executable entries are forbidden", name)
    if info.is_dir() and info.file_size != 0:
        raise _InvalidArchive("INVALID_DIRECTORY", "directory entries must be empty", name)


def _validate_local_header(data: bytes, info: zipfile.ZipInfo) -> tuple[int, int]:
    offset = info.header_offset
    if offset < 0 or offset + _LOCAL_HEADER.size > len(data):
        raise _InvalidArchive("MALFORMED_ZIP", "local header is outside the archive", info.filename)
    fields = _LOCAL_HEADER.unpack_from(data, offset)
    signature, _version, flags, method, _time, _date, crc, compressed, expanded, name_len, extra_len = fields
    if signature != _LOCAL_SIGNATURE:
        raise _InvalidArchive("MALFORMED_ZIP", "invalid local header signature", info.filename)
    name_start = offset + _LOCAL_HEADER.size
    data_start = name_start + name_len + extra_len
    data_end = data_start + info.compress_size
    if data_start > len(data) or data_end > len(data):
        raise _InvalidArchive("MALFORMED_ZIP", "truncated local header", info.filename)
    raw_name = data[name_start : name_start + name_len]
    if b"\x00" in raw_name:
        raise _InvalidArchive("INVALID_PATH", "raw path contains NUL", info.filename)
    try:
        decoded_name = raw_name.decode("utf-8" if flags & 0x0800 else "ascii")
    except UnicodeDecodeError as exc:
        raise _InvalidArchive("INVALID_PATH", "raw path is not ASCII", info.filename) from exc
    if decoded_name != info.filename:
        raise _InvalidArchive("MALFORMED_ZIP", "local and central paths differ", info.filename)
    if flags != info.flag_bits:
        raise _InvalidArchive("MALFORMED_ZIP", "local and central flags differ", info.filename)
    if flags & ~_ALLOWED_FLAG_BITS:
        if flags & 0x0001:
            raise _InvalidArchive("ENCRYPTED", "encrypted entries are forbidden", info.filename)
        raise _InvalidArchive("UNSUPPORTED_FLAGS", "local header uses unsupported ZIP flags", info.filename)
    if method != info.compress_type:
        raise _InvalidArchive("MALFORMED_ZIP", "local and central compression methods differ", info.filename)
    if not flags & 0x0008 and (crc, compressed, expanded) != (
        info.CRC,
        info.compress_size,
        info.file_size,
    ):
        raise _InvalidArchive("MALFORMED_ZIP", "local and central sizes or CRC differ", info.filename)
    return data_start, data_end


def _measure_member(data: bytes, start: int, end: int, info: zipfile.ZipInfo) -> tuple[int, int]:
    """Independently decompress one exact raw member region with a hard output cap."""

    actual = 0
    checksum = 0

    def account(output: bytes) -> None:
        nonlocal actual, checksum
        if not output:
            return
        actual += len(output)
        if info.is_dir() and actual:
            raise _InvalidArchive("INVALID_DIRECTORY", "directory entry contains data", info.filename)
        if actual > MAX_FILE_BYTES:
            raise _InvalidArchive("FILE_TOO_LARGE", f"file exceeds {MAX_FILE_BYTES} bytes", info.filename)
        checksum = zlib.crc32(output, checksum)

    compressed = memoryview(data)[start:end]
    if info.compress_type == zipfile.ZIP_STORED:
        for offset in range(0, len(compressed), 64 * 1024):
            account(bytes(compressed[offset : offset + 64 * 1024]))
    else:
        decompressor = zlib.decompressobj(-15)
        for offset in range(0, len(compressed), 64 * 1024):
            pending = compressed[offset : offset + 64 * 1024]
            while pending:
                room = MAX_FILE_BYTES + 1 - actual
                output = decompressor.decompress(pending, room)
                account(output)
                if decompressor.unused_data:
                    raise _InvalidArchive("MALFORMED_ZIP", "compressed member has trailing data", info.filename)
                tail = decompressor.unconsumed_tail
                if tail and len(tail) == len(pending) and not output:
                    raise _InvalidArchive("MALFORMED_ZIP", "DEFLATE stream made no progress", info.filename)
                pending = tail
        if not decompressor.eof:
            raise _InvalidArchive("MALFORMED_ZIP", "truncated DEFLATE stream", info.filename)
        account(decompressor.flush(MAX_FILE_BYTES + 1 - actual))

    checksum &= 0xFFFFFFFF
    if actual != info.file_size:
        raise _InvalidArchive("SIZE_MISMATCH", "declared and actual expanded sizes differ", info.filename)
    if checksum != info.CRC:
        raise _InvalidArchive("CRC_MISMATCH", "member CRC does not match its contents", info.filename)
    return actual, checksum


def _validate_end_record(data: bytes, expected_entries: int) -> None:
    earliest = max(0, len(data) - (_EOCD.size + 65535))
    offset = data.rfind(_EOCD_SIGNATURE, earliest)
    while offset >= earliest:
        if offset + _EOCD.size <= len(data):
            fields = _EOCD.unpack_from(data, offset)
            _signature, disk, central_disk, disk_entries, entries, central_size, central_offset, comment_size = fields
            if offset + _EOCD.size + comment_size == len(data):
                if disk != 0 or central_disk != 0 or disk_entries != entries:
                    raise _InvalidArchive("MALFORMED_ZIP", "multi-disk ZIP archives are forbidden")
                if entries != expected_entries:
                    raise _InvalidArchive("MALFORMED_ZIP", "central-directory entry count is inconsistent")
                if central_offset + central_size != offset:
                    raise _InvalidArchive("MALFORMED_ZIP", "central-directory bounds are inconsistent")
                return
        offset = data.rfind(_EOCD_SIGNATURE, earliest, offset)
    raise _InvalidArchive("MALFORMED_ZIP", "missing or trailing data after ZIP end record")


def check_zip(
    source: os.PathLike[str] | str | bytes | bytearray | memoryview,
    allowed_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    """Validate an archive and return structured metadata without extracting it.

    Invalid or malformed archives produce ``valid: false`` and a coded ``error``;
    ordinary input failures do not escape as exceptions.  Invalid ``allowed_ids``
    is a caller configuration error and raises :class:`ValueError`.
    """

    allowed = frozenset(_normalise_allowed_ids(allowed_ids))
    try:
        data, archive_size, digest = _read_archive(source)
    except _InvalidArchive as exc:
        return _failure(_empty_result(0, None), exc)
    result = _empty_result(archive_size, digest)
    if archive_size > MAX_ARCHIVE_BYTES:
        return _failure(
            result,
            _InvalidArchive("ARCHIVE_TOO_LARGE", f"archive exceeds {MAX_ARCHIVE_BYTES} bytes"),
        )
    if not data:
        return _failure(result, _InvalidArchive("MALFORMED_ZIP", "archive is empty"))

    attempted: set[str] = set()
    solution_ids: set[str] = set()
    names: set[str] = set()
    folded_names: set[str] = set()
    total_expanded = 0
    file_count = 0
    entries: list[dict[str, object]] = []

    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            infos = archive.infolist()
            if not infos:
                raise _InvalidArchive("EMPTY_ARCHIVE", "archive contains no entries")
            _validate_end_record(data, len(infos))
            if len(infos) > MAX_ENTRIES:
                raise _InvalidArchive("TOO_MANY_ENTRIES", f"archive exceeds {MAX_ENTRIES} entries")
            if min(info.header_offset for info in infos) != 0:
                raise _InvalidArchive("MALFORMED_ZIP", "data before the first local header is forbidden")

            regions: list[tuple[int, int, str]] = []

            for info in infos:
                _validate_attributes(info)
                folded = info.filename.casefold()
                if info.filename in names:
                    raise _InvalidArchive("DUPLICATE_PATH", "duplicate archive path", info.filename)
                if folded in folded_names:
                    raise _InvalidArchive("CASE_ALIAS", "case-ambiguous archive path", info.filename)
                challenge_id, is_directory = _validate_name(info, allowed)
                data_start, data_end = _validate_local_header(data, info)
                if data_end > archive.start_dir:
                    raise _InvalidArchive("MALFORMED_ZIP", "member overlaps the central directory", info.filename)
                regions.append((info.header_offset, data_end, info.filename))
                names.add(info.filename)
                folded_names.add(folded)

                entry = {
                    "path": info.filename,
                    "directory": is_directory,
                    "compressed_bytes": info.compress_size,
                    "declared_bytes": info.file_size,
                    "actual_bytes": 0 if is_directory else None,
                }
                entries.append(entry)
                result["entry_count"] = len(entries)
                result["entries"] = entries
                if is_directory:
                    _measure_member(data, data_start, data_end, info)
                    continue

                file_count += 1
                result["file_count"] = file_count
                if file_count > MAX_FILES:
                    raise _InvalidArchive("TOO_MANY_FILES", f"archive exceeds {MAX_FILES} files", info.filename)
                if info.file_size > MAX_FILE_BYTES:
                    raise _InvalidArchive("FILE_TOO_LARGE", f"file exceeds {MAX_FILE_BYTES} bytes", info.filename)
                if total_expanded + info.file_size > MAX_EXPANDED_BYTES:
                    raise _InvalidArchive("EXPANDED_TOO_LARGE", f"archive exceeds {MAX_EXPANDED_BYTES} expanded bytes", info.filename)
                if challenge_id is not None:
                    attempted.add(challenge_id)
                    result["attempted_ids"] = sorted(attempted)
                    if info.filename == f"solutions/{challenge_id}/solution.c":
                        solution_ids.add(challenge_id)

                actual, _checksum = _measure_member(data, data_start, data_end, info)
                entry["actual_bytes"] = actual
                if total_expanded + actual > MAX_EXPANDED_BYTES:
                    raise _InvalidArchive("EXPANDED_TOO_LARGE", f"archive exceeds {MAX_EXPANDED_BYTES} expanded bytes", info.filename)
                total_expanded += actual
                result["expanded_bytes"] = total_expanded

            ordered_regions = sorted(regions)
            for (_start, end, name), (next_start, _next_end, _next_name) in zip(ordered_regions, ordered_regions[1:]):
                if end > next_start:
                    raise _InvalidArchive("MALFORMED_ZIP", "member regions overlap", name)

            if not attempted:
                raise _InvalidArchive("NO_CHALLENGES", "archive contains no challenge solutions")
            missing = sorted(attempted - solution_ids)
            if missing:
                raise _InvalidArchive(
                    "MISSING_SOLUTION",
                    f"missing solution.c for: {', '.join(missing)}",
                )
    except _InvalidArchive as exc:
        return _failure(result, exc)
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError, ValueError, NotImplementedError) as exc:
        return _failure(result, _InvalidArchive("MALFORMED_ZIP", f"invalid ZIP data: {exc}"))
    except MemoryError:
        raise
    except Exception as exc:  # malformed inputs must fail closed rather than crash callers
        return _failure(result, _InvalidArchive("MALFORMED_ZIP", f"invalid ZIP data: {exc}"))

    result["valid"] = True
    result["error"] = None
    return result


def _assert_no_symlink_components(path: Path) -> None:
    # The caller chooses the source root.  Reject that root and every component we
    # descend into; ancestry outside the root may include normal OS aliases such as
    # macOS /var -> /private/var and is not part of the packaged tree.
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise PackagingError(f"cannot inspect {path}: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise PackagingError(f"symlink path component is forbidden: {path}")


def _recheck_source_components(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PackagingError(f"source escaped the selected root: {path}") from exc
    current = root
    _assert_no_symlink_components(current)
    for component in relative.parts[:-1]:
        current /= component
        _assert_no_symlink_components(current)


def _scan_source_tree(root: Path, allowed: frozenset[str]) -> list[tuple[str, Path]]:
    _assert_no_symlink_components(root)
    if not root.is_dir():
        raise PackagingError(f"source root is not a directory: {root}")

    files: list[tuple[str, Path]] = []
    attempted: set[str] = set()
    solutions = root / "solutions"
    if not solutions.exists():
        raise PackagingError("solutions directory is missing")
    _assert_no_symlink_components(solutions)
    if not solutions.is_dir():
        raise PackagingError("solutions is not a directory")

    try:
        challenge_entries = list(os.scandir(solutions))
    except OSError as exc:
        raise PackagingError(f"cannot scan solutions: {exc}") from exc
    for challenge_entry in challenge_entries:
        if challenge_entry.is_symlink():
            raise PackagingError(f"symlink is forbidden: {challenge_entry.path}")
        if not challenge_entry.is_dir(follow_symlinks=False) or challenge_entry.name not in allowed:
            raise PackagingError(f"unexpected entry in solutions: {challenge_entry.name}")
        challenge_id = challenge_entry.name
        attempted.add(challenge_id)
        challenge_dir = Path(challenge_entry.path)
        seen_solution = False
        try:
            source_entries = list(os.scandir(challenge_dir))
        except OSError as exc:
            raise PackagingError(f"cannot scan {challenge_dir}: {exc}") from exc
        for source_entry in source_entries:
            if source_entry.is_symlink():
                raise PackagingError(f"symlink is forbidden: {source_entry.path}")
            if not source_entry.is_file(follow_symlinks=False):
                raise PackagingError(f"nested directory or special file is forbidden: {source_entry.path}")
            if not (source_entry.name.endswith(".c") or source_entry.name.endswith(".h")):
                raise PackagingError(f"unexpected file in {challenge_id}: {source_entry.name}")
            try:
                source_entry.name.encode("ascii")
                _validate_component(source_entry.name, f"solutions/{challenge_id}/{source_entry.name}")
            except (UnicodeEncodeError, _InvalidArchive) as exc:
                raise PackagingError(f"invalid source filename: {source_entry.name}") from exc
            seen_solution |= source_entry.name == "solution.c"
            files.append((f"solutions/{challenge_id}/{source_entry.name}", Path(source_entry.path)))
        if not seen_solution:
            raise PackagingError(f"{challenge_id} is missing solution.c")

    common = root / "common"
    if common.exists():
        _assert_no_symlink_components(common)
        if not common.is_dir():
            raise PackagingError("common is not a directory")
        try:
            common_entries = list(os.scandir(common))
        except OSError as exc:
            raise PackagingError(f"cannot scan common: {exc}") from exc
        for source_entry in common_entries:
            if source_entry.is_symlink():
                raise PackagingError(f"symlink is forbidden: {source_entry.path}")
            if not source_entry.is_file(follow_symlinks=False) or not source_entry.name.endswith(".h"):
                raise PackagingError(f"unexpected entry in common: {source_entry.name}")
            try:
                source_entry.name.encode("ascii")
                _validate_component(source_entry.name, f"common/{source_entry.name}")
            except (UnicodeEncodeError, _InvalidArchive) as exc:
                raise PackagingError(f"invalid common filename: {source_entry.name}") from exc
            files.append((f"common/{source_entry.name}", Path(source_entry.path)))

    if not attempted:
        raise PackagingError("at least one challenge solution is required")
    if len(files) > MAX_FILES:
        raise PackagingError(f"source tree exceeds {MAX_FILES} files")
    return sorted(files)


def _read_source_file(root: Path, path: Path) -> bytes:
    _recheck_source_components(root, path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PackagingError(f"cannot safely open source file {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PackagingError(f"source is not a regular file: {path}")
        if metadata.st_mode & 0o111:
            raise PackagingError(f"executable source file is forbidden: {path}")
        if metadata.st_size > MAX_FILE_BYTES:
            raise PackagingError(f"source exceeds {MAX_FILE_BYTES} bytes: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise PackagingError(f"source exceeds {MAX_FILE_BYTES} bytes: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def package_zip(
    root: os.PathLike[str] | str,
    destination: os.PathLike[str] | str,
    allowed_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    """Create a deterministic, source-only archive and validate it atomically."""

    allowed = frozenset(_normalise_allowed_ids(allowed_ids))
    root_path = Path(root)
    _assert_no_symlink_components(root_path)
    try:
        root_path = root_path.resolve(strict=True)
    except OSError as exc:
        raise PackagingError(f"cannot resolve source root: {exc}") from exc
    destination_path = Path(destination).absolute()
    files = _scan_source_tree(root_path, allowed)
    try:
        resolved_parent = destination_path.parent.resolve(strict=True)
    except OSError as exc:
        raise PackagingError(f"cannot resolve destination parent: {exc}") from exc
    destination_path = resolved_parent / destination_path.name
    if destination_path.suffix.lower() != ".zip":
        raise PackagingError("destination must have a .zip extension")
    source_paths = {path.resolve(strict=True) for _name, path in files}
    if destination_path in source_paths:
        raise PackagingError("destination would overwrite a source file")
    for protected in (root_path / "solutions", root_path / "common"):
        if destination_path.is_relative_to(protected):
            raise PackagingError("destination cannot be inside a packaged source directory")
    parent = destination_path.parent
    if not parent.is_dir():
        raise PackagingError(f"destination parent is not a directory: {parent}")

    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination_path.name}.", suffix=".tmp", dir=parent)
        os.close(descriptor)
        with zipfile.ZipFile(
            temporary_name,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for archive_name, source_path in files:
                contents = _read_source_file(root_path, source_path)
                info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, contents, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        result = check_zip(temporary_name, allowed)
        if not result["valid"]:
            error = result["error"]
            raise PackagingError(f"created archive failed validation: {error}")
        os.replace(temporary_name, destination_path)
        temporary_name = None
        return result
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackagingError(f"cannot create archive: {exc}") from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="validate an existing submission ZIP")
    check.add_argument("archive", help="ZIP archive to validate")
    check.add_argument("--allow-id", action="append", dest="allowed_ids", choices=KNOWN_IDS)
    package = subparsers.add_parser("package", help="package sources below the current directory")
    package.add_argument("output", help="destination ZIP (may be outside the source directory)")
    package.add_argument("--allow-id", action="append", dest="allowed_ids", choices=KNOWN_IDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        try:
            result = check_zip(args.archive, args.allowed_ids)
        except ValueError as exc:
            print(json.dumps({"valid": False, "error": {"code": "CONFIG_ERROR", "message": str(exc)}}))
            return 1
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["valid"] else 1
    try:
        result = package_zip(Path.cwd(), args.output, args.allowed_ids)
    except (PackagingError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": {"code": "PACKAGE_ERROR", "message": str(exc)}}), file=sys.stdout)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
