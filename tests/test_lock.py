import os, subprocess, sys, tempfile, unittest
from eve_profit.lock import AlreadyRunning, pid_alive, single_instance


class T(unittest.TestCase):
    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "x.db.watch.lock")

    def test_second_holder_is_refused_and_lock_released(self):
        with single_instance(self.p, "watch"):
            self.assertTrue(os.path.exists(self.p))
            # a different live process owns it -> use this very PID's parent as a stand-in owner
            open(self.p, "w").write(str(os.getppid()))
            with self.assertRaises(AlreadyRunning) as cm:
                with single_instance(self.p, "watch"):
                    pass
            self.assertIn("already running", str(cm.exception))
            open(self.p, "w").write(str(os.getpid()))
        self.assertFalse(os.path.exists(self.p))

    def test_stale_lock_from_dead_process_is_replaced(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        open(self.p, "w").write(str(child.pid))               # that PID is gone now
        self.assertFalse(pid_alive(child.pid))
        with single_instance(self.p, "watch"):
            self.assertEqual(open(self.p).read(), str(os.getpid()))

    def test_garbage_lock_file_is_replaced(self):
        open(self.p, "w").write("not a pid")
        with single_instance(self.p, "watch"):
            pass

    def test_lock_released_on_exception(self):
        with self.assertRaises(ValueError):
            with single_instance(self.p, "watch"):
                raise ValueError("boom")
        self.assertFalse(os.path.exists(self.p))

    def test_cli_refuses_second_watch(self):
        from eve_profit.cli import main
        d = tempfile.mkdtemp()
        db = os.path.join(d, "t.db")
        open(db + ".watch.lock", "w").write(str(os.getppid()))
        with self.assertRaises(SystemExit) as cm:
            main(["watch", "--db", db, "--profile", os.path.join(d, "p.json")])
        self.assertIn("already running", str(cm.exception))
        self.assertTrue(os.path.exists(db + ".watch.lock"))    # not stolen from the live owner


if __name__ == "__main__":
    unittest.main()
