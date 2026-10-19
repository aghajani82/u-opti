#!/usr/bin/env python3
"""Fd-relative private file operations for the NONDEPLOYABLE Smite recovery lab.

No CLI, Docker, sockets, elevation or production filesystem paths. All
parents are walked as opened dirfds with O_DIRECTORY|O_NOFOLLOW. A private
0700 disposable root is a precondition; this is not a complete host security
boundary or a replacement for independent process / mount isolation.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import uuid

DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class UnsafePath(ValueError):
    pass


def parts(relative):
    if (not isinstance(relative, str) or not relative or
            relative.startswith("/") or "\x00" in relative):
        raise UnsafePath("UNSAFE_RELATIVE_PATH")
    items = relative.split("/")
    if any(x in ("", ".", "..") for x in items):
        raise UnsafePath("UNSAFE_RELATIVE_PATH")
    return items


def _folder_ok(fd, *, root=False):
    st = os.fstat(fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or
            stat.S_IMODE(st.st_mode) & (0o077 if root else 0o022)):
        raise UnsafePath("UNTRUSTED_DIRECTORY")


def _file_ok(st, limit):
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or st.st_nlink != 1 or st.st_size > limit or st.st_size < 0):
        raise UnsafePath("UNTRUSTED_FILE")


def _fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_nlink, st.st_uid, st.st_mode,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)


@contextmanager
def parent(root, relative, *, create=False):
    names = parts(relative)
    root = Path(root)
    try:
        current = os.open(root, DIR)
    except OSError as exc:
        raise UnsafePath("UNTRUSTED_ROOT") from exc
    try:
        _folder_ok(current, root=True)
        absent = False
        for name in names[:-1]:
            if absent:
                break
            try:
                new = os.open(name, DIR, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    absent = True
                    break
                try:
                    os.mkdir(name, 0o700, dir_fd=current)
                except FileExistsError:
                    pass  # Races are handled by the no-follow directory open.
                os.fsync(current)
                new = os.open(name, DIR, dir_fd=current)
            except OSError as exc:
                raise UnsafePath("SYMLINK_OR_UNSAFE_PARENT") from exc
            try:
                _folder_ok(new)
            except BaseException:
                os.close(new)
                raise
            os.close(current)
            current = new
        yield (None if absent else current), names[-1]
    except OSError as exc:
        raise UnsafePath("UNSAFE_DIRECTORY_ACCESS") from exc
    finally:
        os.close(current)


def _read_fd(fd, limit):
    before = os.fstat(fd)
    _file_ok(before, limit)
    output = bytearray()
    while len(output) <= limit:
        buf = os.read(fd, min(1024 * 1024, limit + 1 - len(output)))
        if not buf:
            break
        output.extend(buf)
    after = os.fstat(fd)
    if len(output) > limit or len(output) != before.st_size or _fingerprint(before) != _fingerprint(after):
        raise UnsafePath("FILE_CHANGED_DURING_READ")
    return bytes(output), stat.S_IMODE(after.st_mode)


def read(root, relative, limit):
    """Return (bytes|None, mode|None), rejecting symlinks and hardlinks."""
    with parent(root, relative) as (directory, name):
        if directory is None:
            return None, None
        try:
            fd = os.open(name, READ, dir_fd=directory)
        except FileNotFoundError:
            return None, None
        except OSError as exc:
            raise UnsafePath("SYMLINK_OR_UNSAFE_FILE") from exc
        try:
            return _read_fd(fd, limit)
        finally:
            os.close(fd)


def _stat_target(directory, name):
    try:
        st = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    _file_ok(st, 48 * 1024 * 1024)
    return _fingerprint(st)


def replace(root, relative, data, mode):
    """Replace only a trusted file; all operations are dirfd relative."""
    if not isinstance(data, bytes) or not (0 <= len(data) <= 48 * 1024 * 1024):
        raise UnsafePath("UNSAFE_WRITE_BYTES")
    if mode not in (0o600, 0o755):
        raise UnsafePath("UNSAFE_WRITE_MODE")
    with parent(root, relative, create=True) as (directory, name):
        before = _stat_target(directory, name)
        tmp = ".uopti-txn-" + uuid.uuid4().hex
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            try:
                os.fchmod(fd, mode)
                at = 0
                while at < len(data):
                    at += os.write(fd, data[at:])
                os.fsync(fd)
            finally:
                os.close(fd)
            if _stat_target(directory, name) != before:
                raise UnsafePath("CONCURRENT_FILE_REPLACEMENT")
            os.replace(tmp, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(tmp, dir_fd=directory)
            except FileNotFoundError:
                pass


def remove(root, relative):
    with parent(root, relative) as (directory, name):
        if directory is None:
            return
        previous = _stat_target(directory, name)
        if previous is None:
            return
        if _stat_target(directory, name) != previous:
            raise UnsafePath("CONCURRENT_FILE_REPLACEMENT")
        os.unlink(name, dir_fd=directory)
        os.fsync(directory)


def move(root, src, dst):
    with parent(root, src) as (src_dir, src_name):
        with parent(root, dst) as (dst_dir, dst_name):
            if src_dir is None or dst_dir is None:
                raise UnsafePath("MISSING_MOVE_PARENT")
            before = _stat_target(src_dir, src_name)
            if before is None or _stat_target(dst_dir, dst_name) is not None:
                raise UnsafePath("AUDIT_SOURCE_OR_DESTINATION_CONFLICT")
            os.rename(src_name, dst_name, src_dir_fd=src_dir, dst_dir_fd=dst_dir)
            os.fsync(src_dir)
            os.fsync(dst_dir)


@contextmanager
def lock(root):
    with parent(root, ".shared-engine.lock") as (directory, name):
        if directory is None:
            raise UnsafePath("MISSING_LOCK_DIRECTORY")
        try:
            fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW |
                         os.O_CLOEXEC, 0o600, dir_fd=directory)
        except OSError as exc:
            raise UnsafePath("UNSAFE_LOCK_FILE") from exc
        try:
            st = os.fstat(fd)
            _file_ok(st, 4096)
            if stat.S_IMODE(st.st_mode) & 0o077:
                raise UnsafePath("LOCK_UNTRUSTED")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UnsafePath("SHARED_ENGINE_TRANSACTION_LOCKED") from exc
            yield
        finally:
            os.close(fd)
