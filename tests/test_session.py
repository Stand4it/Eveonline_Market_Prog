import os, tempfile, unittest
from eve_profit import db
from eve_profit.session import start, stop, summarize_journal


class FakeESI:
    def __init__(self, entries):
        self.entries = entries

    def paged(self, path, **kw):
        return self.entries


class SessionTests(unittest.TestCase):
    def test_only_payouts_inside_the_window_count_and_the_log_gets_a_row(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        t0 = 1_800_000_000
        iso = lambda t: __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime(t))
        entries = [
            {"date": iso(t0 - 600), "ref_type": "bounty_prizes", "amount": 999_000},      # before start: ignored
            {"date": iso(t0 + 600), "ref_type": "bounty_prizes", "amount": 1_000_000},
            {"date": iso(t0 + 1200), "ref_type": "agent_mission_reward", "amount": 2_000_000},
            {"date": iso(t0 + 1300), "ref_type": "market_transaction", "amount": 5_000_000},   # trading: not counted
            {"date": iso(t0 + 1400), "ref_type": "bounty_prizes", "amount": -50},
        ]
        isk, by = summarize_journal(entries, t0, t0 + 3600)
        self.assertEqual(isk, 3_000_000)
        start(con, "Level 1 security mission", 42, now=t0)
        msg = stop(con, FakeESI(entries), extra_isk=500_000, now=t0 + 3600)
        self.assertIn("3,500,000 ISK in 60 min", msg)
        row = con.execute("SELECT activity,isk,hours FROM activity_log").fetchone()
        self.assertEqual((row[0], row[1], round(row[2], 2)), ("Level 1 security mission", 3_500_000, 1.0))
        with self.assertRaises(ValueError):
            stop(con, FakeESI([]))


if __name__ == "__main__":
    unittest.main()


class SummaryTests(unittest.TestCase):
    def test_levels_and_ships_are_kept_apart(self):
        from eve_profit.session import summary
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts,ship) VALUES('Level 1 security mission',1000000,1.0,1,'Velator')")
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts,ship) VALUES('Level 2 security mission',3000000,1.0,2,'Velator')")
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts,ship) VALUES('Level 2 security mission',6000000,1.0,3,'Incursus')")
        txt = summary(con)
        self.assertIn("Level 1 security mission", txt)
        self.assertEqual(txt.count("Level 2 security mission"), 2)       # one line per ship
        self.assertIn("Nothing timed yet", summary(db.connect(os.path.join(tempfile.mkdtemp(), "e.db"))))
