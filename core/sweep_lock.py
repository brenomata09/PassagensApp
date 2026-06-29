"""
Sweep lock: impede que dois sweeps rodem ao mesmo tempo.
Usa criacao atomica de arquivo para evitar corrida entre processos.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

from core.config import settings

LOCK_PATH: Path = settings.root / "data" / "sweep.lock"
LOCK_TIMEOUT_SECONDS: int = 60 * 30


def _is_stale(lock_path: Path) -> bool:
    try:
        return (time.time() - lock_path.stat().st_mtime) > LOCK_TIMEOUT_SECONDS
    except FileNotFoundError:
        return False


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lock_owner_is_running(lock_path: Path) -> bool:
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    return _pid_is_running(pid)


@contextmanager
def acquire_sweep_lock():
    lock_path = LOCK_PATH
    lock_path.parent.mkdir(exist_ok=True)

    if lock_path.exists():
        if not _is_stale(lock_path) and _lock_owner_is_running(lock_path):
            raise RuntimeError(f"Sweep ja em execucao (lock: {lock_path}).")
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError(f"Sweep ja em execucao (lock: {lock_path}).")

    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
