"""Atomic local JSON storage for paper report history.

This module is intentionally isolated: it has no network, exchange, bot, or
paper-account integration. Callers must supply an explicit history-file path.
Writes are append-only, use a same-directory temporary file plus os.replace,
and preserve the previous valid primary file as a .bak file.
"""
import os
from contextlib import contextmanager
from pathlib import Path
import tempfile

from paper_report_history import (
    deserialize_report_history,
    serialize_report_history,
    validate_report_history,
)


def _history_path(path):
    result = Path(path)
    if not result.name:
        raise ValueError("history path must name a file")
    try:
        resolved = result.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("history path cannot be resolved safely") from exc
    if result.name.casefold() == "paper_state.json" or resolved.name.casefold() == "paper_state.json":
        raise ValueError("refusing to use the paper trading state file")
    if result.is_symlink():
        raise ValueError("history path must not be a symbolic link")
    return result


def _read_bytes(path):
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read history file: {path}") from exc


def _decode_history(payload, source):
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source} is not valid UTF-8") from exc
    try:
        return deserialize_report_history(text)
    except ValueError as exc:
        raise ValueError(f"{source} contains invalid report history: {exc}") from exc


def _atomic_write(path, payload):
    """Write bytes atomically using a temporary file in the target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not available on every supported filesystem.
            pass
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@contextmanager
def _exclusive_history_lock(target):
    """Serialize readers/writers across processes using a sidecar OS lock."""
    lock_path = target.with_name(target.name + ".lock")
    if lock_path.is_symlink():
        raise ValueError("history lock must not be a symbolic link")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(lock_path), flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def load_report_history(path):
    """Load and validate the primary history file; never auto-recover."""
    target = _history_path(path)
    with _exclusive_history_lock(target):
        if not target.exists():
            raise FileNotFoundError(target)
        return _decode_history(_read_bytes(target), str(target))


def save_report_history(path, history):
    """Append to an existing history and atomically save it.

    Existing entries must remain an identical prefix. A malformed primary is
    never overwritten. Its valid contents are backed up before replacement.
    """
    target = _history_path(path)
    validate_report_history(history)

    previous = []
    previous_bytes = None
    if target.exists():
        previous_bytes = _read_bytes(target)
        previous = _decode_history(previous_bytes, str(target))
        if len(history) < len(previous) or history[:len(previous)] != previous:
            raise ValueError("history update must preserve all existing entries")

    payload = (serialize_report_history(history) + "\n").encode("utf-8")
    if previous_bytes is not None:
        backup = target.with_name(target.name + ".bak")
        _atomic_write(backup, previous_bytes)
    _atomic_write(target, payload)
    return len(history)


def recover_report_history(path):
    """Explicitly restore a valid .bak file when the primary is missing/bad.

    The backup is validated first and is left untouched. This operation never
    silently runs during load or save.
    """
    target = _history_path(path)
    with _exclusive_history_lock(target):
        backup = target.with_name(target.name + ".bak")
        if target.exists():
            primary_bytes = _read_bytes(target)
            try:
                _decode_history(primary_bytes, str(target))
            except ValueError:
                pass
            else:
                raise ValueError("primary history is valid; refusing rollback")
        if not backup.exists():
            raise FileNotFoundError(backup)
        backup_bytes = _read_bytes(backup)
        history = _decode_history(backup_bytes, str(backup))
        _atomic_write(target, backup_bytes)
        return history
