import json
import os
import tempfile
import time
import unittest

from eve_profit import health


class T(unittest.TestCase):
    def test_report_and_line_from_logs(self):
        d = tempfile.mkdtemp()
        err, hourly = os.path.join(d, "errors.log"), os.path.join(d, "hourly.log")
        now = time.time()
        with open(err, "w", encoding="utf-8") as f:
            f.write(json.dumps({"t": now, "where": "nextstep", "msg": "TypeError: x", "at": "a.py:1 in f"}) + "\n")
            f.write(json.dumps({"t": now - 3 * 24 * 3600, "where": "old", "msg": "old", "at": "b.py:2 in g"}) + "\n")
        with open(hourly, "w", encoding="utf-8") as f:
            f.write("fine\nSell plan update skipped: 'int' object is not subscriptable\n")
        old_e, old_h = health.ERR_FILE, health.HOURLY
        health.ERR_FILE, health.HOURLY = err, hourly
        try:
            r = health.recent()
            self.assertEqual(list(r.values()), [1])                         # the 3-day-old error is not counted
            self.assertIn("skipped", health.report())
            self.assertIn("HEALTH: 2 problem", health.line())
        finally:
            health.ERR_FILE, health.HOURLY = old_e, old_h


if __name__ == "__main__":
    unittest.main()
