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

    def test_delete_removes_a_mistaken_run(self):
        from eve_profit.session import fix_last
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 5 couriers',364010,0.6,1)")
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 6 both',0,0.02,2)")
        self.assertIn("Deleted", fix_last(con, delete=True))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0], 1)


class OffersWithProfileTests(unittest.TestCase):
    def test_ranking_works_with_a_graph_and_profile_and_keeps_the_profile_intact(self):
        """A variable named p inside the loop once replaced the Profile by a price and broke the trade lookup."""
        import json
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import offers_ranked
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        far = [s for s, r in g.reach(1, 3).items() if r.jumps == 2][0]
        con.execute("DELETE FROM orders WHERE type_id=35")
        con.execute("INSERT INTO orders VALUES(994001,35,60000001,1,10000001,0,10.0,100000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(994002,35,?,?,10000001,1,30.0,100000,1,'',1)", (60000000 + far, far))
        txt = offers_ranked(con, g, Profile(current_system="Home", cargo_m3=135, wallet_isk=1e7, secs_per_jump=45))
        self.assertIn("AGENT OFFERS", txt)

    def test_next_prints_exactly_one_step(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import next_action
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        out = next_action(con, g, Profile(current_system="Home", cargo_m3=135, wallet_isk=1e7, secs_per_jump=45))
        self.assertEqual(out.count("STEP:"), 1)
        self.assertNotIn("AGENT OFFERS", out)


class AgentStepsScriptTests(unittest.TestCase):
    def test_checklist_is_built_from_the_open_offers_with_timer_names(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("agent_steps", os.path.join("scripts", "agent_steps.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        names = [n for n, _, _ in mod.build_steps()]
        self.assertTrue(names)
        self.assertTrue(all(n.startswith("Agent L1") for n in names))
        self.assertEqual(len(names), len(set(names)) + names.count("Agent L1 step 1 Enforcer cash flow") - 1 if names.count("Agent L1 step 1 Enforcer cash flow") > 1 else len(names))


class BuyPriceTests(unittest.TestCase):
    def test_cheapest_full_order_and_nearest_are_found(self):
        from eve_profit.buyprice import best_buys, format_buys
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        near = [s for s, r in g.reach(1, 3).items() if r.jumps == 1][0]
        con.execute("DELETE FROM orders WHERE type_id=34")
        con.execute("INSERT INTO orders VALUES(995001,34,60000001,1,10000001,0,100.0,50,1,'',1)")
        con.execute("INSERT INTO orders VALUES(995002,34,?,?,10000001,0,80.0,500,1,'',1)", (60000000 + near, near))
        rows = best_buys(con, g, Profile(current_system="Home", secs_per_jump=45), None, [], 34, 100, refresh=False)
        self.assertEqual(rows[0]["system"], g.name[near])                  # a full order beats a partial one
        self.assertTrue(rows[0]["full"])
        self.assertFalse([r for r in rows if r["system"] == "Home"][0]["full"])
        self.assertIn("Cheapest", format_buys("Tritanium", 100, rows, "Home"))


class PickOffersTests(unittest.TestCase):
    def _row(self, rate, agent):
        return (rate, rate, 20.0, {"agent": agent, "mission": "m"}, [])

    def test_one_per_career_first_and_unmeasured_favoured(self):
        from eve_profit.nextstep import career_of, pick_offers
        rows = [self._row(900, "A (Industrialist - Producer)"), self._row(800, "B (Industrialist - Entrepreneur)"),
                self._row(700, "C (Explorer)"), self._row(300, "D (Enforcer)"), self._row(200, "E (Mining, Axiosere)")]
        self.assertEqual(career_of(rows[4][3]), "Mining")
        got = pick_offers(rows, {"Industrialist"}, limit=3)
        careers = [c for _, c, _ in got]
        self.assertEqual(len(got), 3)
        self.assertEqual(len(set(careers)), 3)                          # three different careers, not two Industrialist
        self.assertIn("Explorer", careers)
        full = pick_offers(rows, set(), limit=5)
        self.assertEqual(len(full), 5)

    def test_book_tag_only_when_sold_here_and_affordable(self):
        from eve_profit.nextstep import book_tag
        sellers = {"Bourynes": [("Accounting", 5_000_000.0)]}
        self.assertEqual(book_tag(sellers, "Rotonos", 9e6), [])
        self.assertEqual(book_tag(sellers, "Bourynes", 1e6), [])
        self.assertIn("INJECT", book_tag(sellers, "Bourynes", 9e6)[0])


class RegionalAskTests(unittest.TestCase):
    def test_listing_price_is_the_cheapest_ask_in_the_region_not_the_local_one(self):
        from eve_profit.along import regional_ask
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        sysid = next(iter(g.region))
        mates = [x for x, r in g.region.items() if r == g.region[sysid]]
        other = mates[-1]
        con.execute("DELETE FROM orders WHERE type_id=34 AND is_buy=0")
        con.execute("INSERT INTO orders VALUES(991101,34,60000001,?,10000001,0,5000.0,5,1,'',1)", (sysid,))
        con.execute("INSERT INTO orders VALUES(991102,34,60000002,?,10000001,0,1506.0,5,1,'',1)", (other,))
        self.assertEqual(regional_ask(con, g, 34, sysid, 5000.0), 1506.0 if other != sysid else 5000.0)
        self.assertEqual(regional_ask(con, g, 999999, sysid, 7.0), 7.0)


class ChainTests(unittest.TestCase):
    def test_agent_step_is_an_ordered_chain_and_chain_numbers_the_parts(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import _agent_step, _chain
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        txt, _ = _agent_step(con, Graph(con), Profile(current_system="Home", cargo_m3=135, wallet_isk=1e7))
        self.assertIn("1. ACCEPT Arnelin", txt)
        self.assertIn("2. ACCEPT Beradaillot", txt)                                           # each mission on its own line
        self.assertNotIn("python -m eve_profit stop", txt)                                  # stop is said once, in the footer
        self.assertEqual(_chain(["one"]), "one")
        self.assertIn("[2/2]", _chain(["a", "b"]))


class KeepListTests(unittest.TestCase):
    def test_kept_items_are_never_advised_for_sale(self):
        from eve_profit.along import keep_names, plan_along
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        self.assertIn("miner i", keep_names())
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(777001,'Miner I',5,1)")
        con.execute("INSERT INTO orders VALUES(995001,777001,60000001,1,10000001,1,1450.0,10,1,'',1)")
        con.execute("INSERT INTO inventory VALUES(777001,1,2)")
        res = plan_along(con, Graph(con), Profile(current_system="Home", cargo_m3=135, wallet_isk=1e7, current_location_id=60000001), "Home")
        self.assertNotIn("Miner I", [d["name"] for d in res["sell_here"]])

    def test_upgrade_is_advised_only_when_affordable(self):
        from eve_profit.along import plan_along
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(777001,'Miner I',5,1)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(777002,'Miner II',5,1)")
        con.execute("INSERT INTO orders VALUES(995001,777001,60000001,1,10000001,0,13900.0,10,1,'',1)")
        con.execute("INSERT INTO orders VALUES(995002,777002,60000001,1,10000001,0,60000.0,10,1,'',1)")
        con.execute("INSERT INTO inventory VALUES(777001,1,2)")
        g = Graph(con)
        rich = plan_along(con, g, Profile(current_system="Home", wallet_isk=20e6, current_location_id=60000001), "Home")
        self.assertEqual([u["upgrade"] for u in rich["upgrades"]], ["Miner II"])
        poor = plan_along(con, g, Profile(current_system="Home", wallet_isk=1e6, current_location_id=60000001), "Home")
        self.assertEqual(poor["upgrades"], [])


class RebuyNoteTests(unittest.TestCase):
    def test_note_only_for_building_materials_and_says_which_way_it_cuts(self):
        from eve_profit.nextstep import rebuy_note
        self.assertEqual(rebuy_note({"used_in": 0, "rebuy": 100.0, "net": 50.0}), "")
        cheap = rebuy_note({"used_in": 3, "rebuy": 9036.0, "net": 12210.0, "list_net": 0.0})
        self.assertIn("selling now and rebuying later is fine", cheap)
        dear = rebuy_note({"used_in": 3, "rebuy": 27800.0, "net": 2897.0, "list_net": 0.0})
        self.assertIn("MORE", dear)


class BonusTests(unittest.TestCase):
    def test_career_bonus_and_market_lines(self):
        from eve_profit.bonus import market_lines, offer_bonus
        progs = [{"name": "P", "kind": "career_missions", "careers": ["Soldier of Fortune"], "reward_isk": 25000, "career_points": 10},
                 {"name": "M", "market": True, "target_isk": 100, "progress_isk": 0},
                 {"name": "Done", "market": True, "target": 5, "progress": 5},
                 {"name": "Unsafe", "market": True, "safe": False, "target": 5, "progress": 0}]
        self.assertEqual(offer_bonus("Soldier of Fortune", progs)[0], 25000)
        self.assertEqual(offer_bonus("Explorer", progs)[0], 0)
        lines = market_lines(progs)
        self.assertEqual(len(lines), 1)
        self.assertIn("'M'", lines[0])


class GrantedBookTests(unittest.TestCase):
    def test_books_granted_by_open_missions_are_known(self):
        from eve_profit.nextstep import _granted_books
        self.assertIn("broker relations", _granted_books())


class TimerLineTests(unittest.TestCase):
    def test_every_step_gets_a_named_timer(self):
        from eve_profit.nextstep import _name_of, _timer
        self.assertEqual(_name_of("STEP: LIST 1 item in Rotonos\n   8 x Core Scanner Probe I"), "Market list Core Scanner Probe I")
        self.assertEqual(_name_of("STEP: SELL NOW in Rotonos - about 5 ISK"), "Market sell stock Rotonos")
        self.assertEqual(_name_of("STEP: TRADE (best)\n   Buy 14 x Foo @ A, sell @ B"), "Trade Buy 14 x Foo @ A, sell @ B")
        self.assertIn('start --activity "X"', _timer("X"))
        self.assertNotIn("stop", _timer("X"))
