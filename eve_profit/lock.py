"""Single-instance lock: one lock file per (database, kind), holding the owner's PID.
A lock whose process has died (window killed, power loss) is detected and replaced, so a
crash never leaves you stuck."""
import contextlib
import os


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259         # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AlreadyRunning(RuntimeError):
    pass


@contextlib.contextmanager
def single_instance(path, what):
    """Hold `path` while the block runs. Raises AlreadyRunning if a live process owns it."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                owner = int(open(path).read().strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if owner and pid_alive(owner) and owner != os.getpid():
                raise AlreadyRunning(
                    f"Another eve_profit '{what}' is already running (PID {owner}). Close that window first "
                    f"(or: Stop-Process -Id {owner}). If you are sure nothing is running, delete {path}")
            try:
                os.remove(path)                       # stale lock from a dead process
            except OSError:
                pass
    else:
        raise AlreadyRunning(f"Could not take the lock {path}")
    try:
        yield
    finally:
        try:
            if int(open(path).read().strip() or 0) == os.getpid():
                os.remove(path)
        except (OSError, ValueError):
            pass
