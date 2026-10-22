"""One writer at a time for agent_offers.json: two scripts that read, change and write it at the same moment lost each other's offers
(2026-10-22: Avu Olunatsu and Gohtiras Uova vanished). Use:  with offers_lock(): load -> change -> write."""
import contextlib
import os
import time

LOCK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_offers.json.lock")


@contextlib.contextmanager
def offers_lock(timeout=600):
    t0 = time.time()
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - os.path.getmtime(LOCK) > 900:          # a crashed writer: its lock is stale
                os.remove(LOCK)
                continue
            if time.time() - t0 > timeout:
                raise TimeoutError("agent_offers.json is locked by another script")
            time.sleep(0.5)
    try:
        yield
    finally:
        os.close(fd)
        os.remove(LOCK)
