"""Advisory lock shared by CLI and menu bar workers (macOS / Linux)."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


def lock_path(database):
    return Path(str(Path(database).resolve()) + ".worker.lock")


@contextmanager
def worker_lock(database):
    path = lock_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "A worker is already running for this database. Stop it before starting another."
            ) from error
        file.seek(0)
        file.truncate()
        file.write(str(os.getpid()))
        file.flush()
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def worker_status(database):
    path = lock_path(database)
    if not path.exists():
        return {"running": False, "pid": None}
    with path.open("r") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            text = file.read().strip()
            return {"running": True, "pid": int(text) if text.isdigit() else None}
        else:
            fcntl.flock(file, fcntl.LOCK_UN)
            return {"running": False, "pid": None}
