#!/usr/bin/env python3
"""Explicit offline raw Ed25519 key enrollment for the independent reviewer.

Only a local IR/KH authenticated Root TTY can generate a node/lease key.
The private 32-byte seed never leaves its restricted directory. The public
32-byte pin is exported out-of-band and pinned on IR; no Node or Panel key
is replaced. This script never runs automatically or handles live routing.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import stat
import sys


class KeyEnrollmentHold(RuntimeError):pass


def generate(private:Path,public:Path,*,enforce_root=True):
    private,public=Path(private),Path(public)
    if enforce_root and (os.geteuid()!=0 or not sys.stdin.isatty()
        or os.uname().nodename.split(".")[0].lower() not in ("ir","kh")):
        raise KeyEnrollmentHold("IR_OR_KH_ROOT_TTY_ONLY")
    root=Path("/etc/u-opti/smite/approval-keys")
    if (enforce_root and (private.parent!=root or public.parent!=root)
            or private==public or private.exists() or private.is_symlink()
            or public.exists() or public.is_symlink()):
        raise KeyEnrollmentHold("PRE_EXISTING_OR_UNAPPROVED_KEY_TARGET")
    for parent in (private.parent,public.parent):
        info=parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700
                or (enforce_root and info.st_uid!=0)):
            raise KeyEnrollmentHold("KEY_PARENT_NOT_ROOT_PRIVATE")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,PublicFormat,PrivateFormat,NoEncryption,
    )
    key=Ed25519PrivateKey.generate()
    secret=key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption())
    pin=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    if len(secret)!=32 or len(pin)!=32:raise KeyEnrollmentHold("ED25519_KEY_INVALID")
    def write(path,data,mode):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
        try:
            os.fchmod(fd,mode)
            with os.fdopen(fd,"wb",closefd=False) as f:
                f.write(data);f.flush();os.fsync(f.fileno())
        finally:os.close(fd)
        dirfd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(dirfd)
        finally:os.close(dirfd)
    write(private,secret,0o400)
    write(public,pin,0o600)
    return hashlib.sha256(pin).hexdigest()


if __name__=="__main__":
    if len(sys.argv)!=4 or sys.argv[1]!="--generate":
        raise SystemExit("HOLD_EXPLICIT_KEY_GENERATION_ONLY")
    try:
        digest=generate(Path(sys.argv[2]),Path(sys.argv[3]))
        print("PUBLIC_PIN_SHA256="+digest)
        print("LIVE_CONFIG_CHANGES=NONE")
    except Exception:
        raise SystemExit("HOLD_KEY_ENROLLMENT_REQUIRES_REVIEW")
