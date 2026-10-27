"""Deterministic JSON, atomic writes, and process-scoped file locks."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile


class DataError(Exception):
    """A bounded, nonsecret diagnostic suitable for CLI display."""


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path):
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError()
        return parsed

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          parse_float=finite_float,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, OSError):
        raise DataError("json_unreadable_or_nonfinite") from None


def atomic_json(path, value):
    path = Path(path)
    raw = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def exclusive(path):
    """OS lock releases on process death; no stale lock-file recovery required."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DataError("another_process_holds_lock") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
