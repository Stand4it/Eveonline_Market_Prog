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


class LootTests(unittest.TestCase):
    def test_loot_value_uses_best_market_net_of_travel_time_and_adds_hours(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.loot import gains, value_loot
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        con.execute("DELETE FROM orders WHERE type_id=34")
        near = [s for s, r in g.reach(1, 2).items() if r.jumps == 1][0]
        con.execute("INSERT INTO orders VALUES(990001,34,60000001,1,10000001,1,1.0,10000000,1,'',1)")        # bid here 1.0
        con.execute("INSERT INTO orders VALUES(990002,34,?,?,10000001,1,5.0,10000000,1,'',1)", (60000000 + near, near))   # 5.0 one jump away
        p = Profile(current_system="Home", secs_per_jump=45)
        rows = gains({"34:1": 10}, {"34:1": 1010})
        self.assertEqual(rows, [(34, 1, 1000)])
        big = value_loot(con, g, p, [(34, 1, 100000)])
        self.assertEqual(big["where"], g.name[near])                       # worth the side trip
        self.assertGreater(big["value"], 100000 * 1.0)
        self.assertGreater(big["travel_hours"], 0)
        small = value_loot(con, g, p, [(34, 1, 10)])
        self.assertIsNone(small["where"])                                  # not worth leaving for
        self.assertEqual(small["travel_hours"], 0)


class PauseTests(unittest.TestCase):
    def test_pause_and_resume_remove_the_time_away(self):
        from eve_profit.session import pause, resume
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        t0 = 1_800_000_000
        iso = lambda t: __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime(t))
        start(con, "Agent L1 step 1 test", 7, now=t0)
        self.assertIn("PAUSED", pause(con, now=t0 + 600))
        self.assertIn("already paused", pause(con, now=t0 + 700))
        self.assertIn("RESUMED", resume(con, now=t0 + 3000))               # 40 min away
        entries = [{"date": iso(t0 + 100), "ref_type": "agent_mission_reward", "amount": 1_000_000}]
        msg = stop(con, FakeESI(entries), now=t0 + 4200)                    # 70 min wall clock - 40 away = 30
        self.assertIn("in 30 min", msg)
        with self.assertRaises(ValueError):
            pause(con)


class AgentOffersTests(unittest.TestCase):
    def test_note_says_not_measured_yet_then_ranks_measured_agent_runs(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import agent_note
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        p = Profile()
        self.assertIn("not measured yet", agent_note(con, g, p))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 1 x',1000000,1.0,1)")
        txt = agent_note(con, g, p)
        self.assertIn("AGENT MISSIONS (measured)", txt)
        self.assertIn("1,000,000 ISK/hr", txt)


class FixLastAndDocsTests(unittest.TestCase):
    def test_fixlast_adds_minutes_and_docs_cover_every_command(self):
        from eve_profit import docs
        from eve_profit.session import fix_last
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('x',600000,0.5,1)")
        msg = fix_last(con, add_min=30, add_isk=0)
        self.assertIn("in 60 min", msg)
        self.assertIn("600,000 ISK/hr", msg)
        self.assertEqual([c for c in docs.code_commands() if c not in docs.COMMAND_HELP], [])


class CommandReferenceTests(unittest.TestCase):
    def test_reference_lists_every_command_with_options_and_docx_opens(self):
        import zipfile
        from eve_profit import docs
        lines = docs.reference_lines(docs.code_commands())
        text = "\n".join(lines)
        for c in docs.code_commands():
            self.assertIn(c.upper() + "  -  ", text)
        self.assertIn("--add-min", text)
        path = os.path.join(tempfile.mkdtemp(), "c.docx")
        docs.write_docx(path, lines)
        self.assertIn("word/document.xml", zipfile.ZipFile(path).namelist())


class AgentsViewTests(unittest.TestCase):
    def test_report_lists_known_agents_runs_and_levels(self):
        from eve_profit.agents_view import report
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 1 x',1000000,1.0,1)")
        txt = report(con, Graph(con), Profile(current_system="Home"))
        self.assertIn("CAREER AGENTS", txt)
        self.assertIn("Agent L1 step 1 x", txt)
        self.assertIn("MISSION AGENTS NEAR YOU BY LEVEL", txt)


class TradeExtrasTests(unittest.TestCase):
    def test_a_trip_job_gets_trades_on_the_way_added_to_its_value(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import trade_extras
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        far = [s for s, r in g.reach(1, 3).items() if r.jumps == 2][0]
        con.execute("DELETE FROM orders WHERE type_id=35")
        con.execute("INSERT INTO orders VALUES(993001,35,60000001,1,10000001,0,10.0,100000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(993002,35,?,?,10000001,1,30.0,100000,1,'',1)", (60000000 + far, far))
        p = Profile(current_system="Home", cargo_m3=135, wallet_isk=1e7, secs_per_jump=45)
        isk, mins, lines = trade_extras(con, g, p, {"to_system": g.name[far], "m3": 40})
        self.assertGreater(isk, 0)
        self.assertTrue(any("buy" in l for l in lines))
        self.assertEqual(trade_extras(con, g, p, {}), (0.0, 0.0, []))


class FixLastActivityTests(unittest.TestCase):
    def test_fix_a_named_older_run(self):
        from eve_profit.session import fix_last
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 2 Soldier maulus',0,0.5,1)")
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 5 couriers',364010,0.6,2)")
        msg = fix_last(con, add_isk=180000, activity="step 2 Soldier")
        self.assertIn("180,000 ISK in 30 min", msg)
        self.assertEqual(con.execute("SELECT isk FROM activity_log WHERE activity LIKE '%couriers'").fetchone()[0], 364010)
        with self.assertRaises(ValueError):
            fix_last(con, activity="nothing like this")
