import json
import os
import tempfile
import time
import unittest

from eve_profit import db, livepos


class PingPong(unittest.TestCase):
    def _con(self, log):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT OR REPLACE INTO meta VALUES('jump_log', ?)", (json.dumps(log),))
        return con

    def test_going_straight_back_is_a_reversal(self):
        now = time.time()
        con = self._con([[now - 600, "Manifest", "Yulai", 3]])
        self.assertEqual(livepos.reversal(con, "Manifest", "Yulai", now), 1)
        self.assertEqual(livepos.reversal(con, "Elsewhere", "Yulai", now), 0)

    def test_a_loop_already_under_way_is_level_two(self):
        now = time.time()
        con = self._con([[now - 900, "A", "B", 1], [now - 600, "B", "A", 1], [now - 300, "A", "B", 1]])
        self.assertEqual(livepos.reversal(con, "A", "B", now), 2)

    def test_old_moves_do_not_count(self):
        now = time.time()
        con = self._con([[now - 5 * 3600, "A", "B", 1]])
        self.assertEqual(livepos.reversal(con, "A", "B", now), 0)

    def test_jumps_today_counts_since_the_reset(self):
        now = time.time()
        con = self._con([[now - 60, "A", "B", 2], [now - 3 * 86400, "B", "C", 5]])
        self.assertEqual(livepos.jumps_today(con, now), 2)


if __name__ == "__main__":
    unittest.main()
