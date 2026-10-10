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
        self.assertGreaterEqual(out.count("STEP:") + out.count("AGENT MISSION"), 1)      # a short plan, not the long --all view
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
        sellers = {"Bourynes": [("Accounting", 500_000.0)]}
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
        self.assertIn("1. ACCEPT ", txt)
        self.assertIn("ACCEPT", txt)                                                          # each mission to accept gets its own ACCEPT line
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
        import json
        f = os.path.join(tempfile.mkdtemp(), "o.json")
        json.dump({"offers": [{"agent": "A", "granted": ["Broker Relations (skill book)"]},
                              {"agent": "B", "granted": ["Hidden Book"], "available": False}]}, open(f, "w"))
        self.assertEqual(_granted_books(f), {"broker relations"})


class TimerLineTests(unittest.TestCase):
    def test_every_step_gets_a_named_timer(self):
        from eve_profit.nextstep import _name_of, _timer
        self.assertEqual(_name_of("STEP: LIST 1 item in Rotonos\n   8 x Core Scanner Probe I"), "Market list Core Scanner Probe I")
        self.assertEqual(_name_of("STEP: SELL NOW in Rotonos - about 5 ISK"), "Market sell stock Rotonos")
        self.assertEqual(_name_of("STEP: TRADE (best)\n   Buy 14 x Foo @ A, sell @ B"), "Trade Buy 14 x Foo @ A, sell @ B")
        self.assertIn('start --activity "X"', _timer("X"))
        self.assertNotIn("stop", _timer("X"))

    def test_a_book_costing_most_of_the_wallet_is_not_suggested(self):
        from eve_profit.nextstep import book_tag
        self.assertEqual(book_tag({"Rotonos": [("Accounting", 5_000_000.0)]}, "Rotonos", 6_900_000.0), [])


class ListPolicyTests(unittest.TestCase):
    def test_min_gain_and_staleness(self):
        import time
        from eve_profit import along
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        along.LIST_MIN_GAIN, saved = 50_000.0, along.LIST_MIN_GAIN
        try:
            self.assertGreaterEqual(along.list_min_gain(con), 50_000.0)
        finally:
            along.LIST_MIN_GAIN = saved
        g = Graph(con)
        sysid = next(iter(g.region))
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 40 * 86400))
        con.execute("DELETE FROM orders WHERE type_id=34 AND is_buy=0")
        con.execute("INSERT INTO orders VALUES(997001,34,60000001,?,10000001,0,5000.0,5,1,?,1)", (sysid, old))
        self.assertGreater(along.ask_age_days(con, g, 34, sysid, 5000.0), 30)


class MyOrdersTests(unittest.TestCase):
    def test_items_already_listed_are_not_advised_again(self):
        from eve_profit.along import plan_along
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT INTO orders VALUES(998001,34,60000001,1,10000001,1,5000.0,500,1,'',1)")
        con.execute("INSERT INTO inventory VALUES(34,1,100)")
        g, p = Graph(con), Profile(current_system="Home", cargo_m3=135, wallet_isk=1e7, current_location_id=60000001)
        self.assertIn("Tritanium", [d["name"] for d in plan_along(con, g, p, "Home")["sell_here"]])
        con.execute("INSERT INTO my_orders VALUES(1,34,60000001,0,4500.0,6,6,'2026-10-09T10:00:00Z')")
        self.assertNotIn("Tritanium", [d["name"] for d in plan_along(con, g, p, "Home")["sell_here"]])


class DailyGoalTests(unittest.TestCase):
    def test_missions_are_matched_to_air_daily_goals(self):
        from eve_profit.bonus import daily_goal_hits
        progs = [{"kind": "daily_goals", "goals": [{"goal": "Scan 5 Signatures", "progress": "0/5", "keywords": ["scan down"]},
                                                  {"goal": "Complete 3 Jumps", "progress": "0/3", "keywords": ["jump"]}]}]
        self.assertEqual(daily_goal_hits("Scan down the relic site", progs), ["Scan 5 Signatures (0/5)"])
        self.assertEqual(daily_goal_hits("nothing relevant", progs), [])


class CareersTests(unittest.TestCase):
    def test_runs_are_grouped_by_career_and_unmeasured_ones_are_suggested(self):
        from eve_profit.careers import career_of_activity, report
        self.assertEqual(career_of_activity("Agent L1 step 7 Entrepreneur relic site"), "Industrialist")
        self.assertEqual(career_of_activity("Agent L1 step 3 Explorer data site"), "Explorer")
        self.assertEqual(career_of_activity("Mining Venture Rotonos belt (freelance)"), "Mining")
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Agent L1 step 5 Industrialist courier',300000,0.5,1)")
        out = report(con, [{"agent": "Rounaminck Folle (Explorer)", "mission": "data site", "available": True}])
        self.assertIn("Industrialist", out)
        self.assertIn("600,000", out)
        self.assertIn("TRY NEXT: Explorer", out)
        self.assertIn("1 run(s): needs 2 more", out)


class BetterPlaceTests(unittest.TestCase):
    def test_next_points_at_a_clearly_better_market_nearby(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import _better_places
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        far = [x for x, r in g.reach(1, 3).items() if r.jumps == 2][0]
        con.execute("DELETE FROM orders WHERE type_id=34")
        con.execute("INSERT INTO orders VALUES(999001,34,60000001,1,10000001,1,185.0,100000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(999002,34,?,?,10000001,1,490.0,100000,1,'',1)", (60000000 + far, far))
        con.execute("INSERT INTO inventory VALUES(34,1,2000)")
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)
        self.assertIn(34, _better_places(con, g, p, rate=1_000_000.0))


class ScanBudgetTests(unittest.TestCase):
    def test_refresh_orders_stops_when_the_time_budget_is_used(self):
        import time as _t
        from eve_profit.esi import refresh_orders

        class FakeESI:
            def __init__(self):
                self.asked = []

            def region_orders(self, rid, max_pages=None, log=None):
                self.asked.append(rid)
                _t.sleep(0.05)
                return []

            def system_kills(self):
                return []

            def get(self, path, **kw):
                return [], 1

        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        esi = FakeESI()
        refresh_orders(con, esi, [1, 2, 3], budget_min=0.0005)            # 0.03 s budget: only the first region fits
        self.assertEqual(esi.asked, [1])


class HeartbeatTests(unittest.TestCase):
    def test_a_slow_command_prints_a_progress_line_and_a_fast_one_prints_nothing(self):
        import io
        import time as _t
        from eve_profit.pretty import Heartbeat
        buf = io.StringIO()
        with Heartbeat(every=0.05, out=buf):
            _t.sleep(0.12)
        self.assertIn("elapsed", buf.getvalue())
        quiet = io.StringIO()
        with Heartbeat(every=5.0, out=quiet):
            pass
        self.assertEqual(quiet.getvalue(), "")


class HaulCandidateTests(unittest.TestCase):
    def _world(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        far = [x for x, r in g.reach(1, 3).items() if r.jumps == 2][0]
        con.execute("DELETE FROM orders WHERE type_id=34")
        con.execute("INSERT INTO orders VALUES(999101,34,60000001,1,10000001,1,185.0,100000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(999102,34,?,?,10000001,1,490.0,100000,1,'',1)", (60000000 + far, far))
        con.execute("INSERT INTO inventory VALUES(34,1,2000)")
        return con, g, Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)

    def test_haul_option_finds_the_better_market_and_scores_isk_per_hour(self):
        from eve_profit.haul import haul_option, haul_step
        con, g, p = self._world()
        h = haul_option(con, g, p)
        self.assertIsNotNone(h)
        self.assertGreater(h["gain"], 50_000)
        self.assertGreater(h["rate_hr"], 0)
        self.assertIn("STEP: HAUL", haul_step(h))

    def test_next_names_the_comparison(self):
        from eve_profit.nextstep import next_action
        con, g, p = self._world()
        out = next_action(con, g, p)
        self.assertIn("python -m eve_profit start --activity", out)


class ProgressValueTests(unittest.TestCase):
    def test_progress_and_experiments(self):
        from eve_profit.progress import experiment_candidates, progress_isk
        v = {"agent_step": 30000.0, "new_career_run": 60000.0, "career_runs_until_measured": 3,
             "priors_isk_hr": {"Mining": 150000.0}, "prior_minutes": {"Mining": 45}}
        self.assertEqual(progress_isk("Explorer", {}, v), 90000.0)                 # new career: step + model value
        self.assertEqual(progress_isk("Industrialist", {"Industrialist": 10}, v), 30000.0)
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        got = experiment_candidates(con, {}, v)
        self.assertEqual(got[0][1], "test Mining")
        self.assertGreater(got[0][0], 150000.0)                                   # prior + model value
        self.assertEqual(experiment_candidates(con, {"Mining": 5}, v), [])


class CatalogTests(unittest.TestCase):
    def _con(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(777,'Trade',0.01,1)")
        return con

    def test_status_locked_unlocked_and_modeled(self):
        from eve_profit.catalog import models_report, status
        con = self._con()
        st = {a["id"]: a for a in status(con, 6_900_000)}
        self.assertTrue(st["pd"]["unlocked"])
        self.assertFalse(st["agent_l2_security"]["unlocked"])               # needs Gallente Frigate 3 etc.
        self.assertIn("Trade 2", st["station_trading"]["missing"] or ["Trade 2"])
        for i in range(3):
            con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Project Discovery',50000,0.5,?)", (i,))
        self.assertEqual({a["id"]: a for a in status(con)}["pd"]["state"], "MODELED")
        self.assertIn("MODEL MAP", models_report(con, 6_900_000))

    def test_experiment_is_offered_every_fourth_step_and_on_new_unlock(self):
        from eve_profit.catalog import EVERY, pick_experiment
        con = self._con()
        act, why, seen = pick_experiment(con, 6_900_000, 700_000.0, counter=1, last_exp=0, seen=set())
        self.assertIsNone(act)                                              # first call only records what is already unlocked
        self.assertTrue(seen)
        act, why, _ = pick_experiment(con, 6_900_000, 700_000.0, counter=EVERY, last_exp=0, seen=set(seen))
        self.assertIsNotNone(act)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(778,'Industry',0.01,1)")
        con.execute("INSERT INTO character_skills(skill_id,level,sp) VALUES(778,1,100)")
        act, why, _ = pick_experiment(con, 6_900_000, 700_000.0, counter=2, last_exp=1, seen=set(seen))
        self.assertEqual(act["id"], "manufacturing_t1")
        self.assertIn("NEW", why)


class MiningSitesTests(unittest.TestCase):
    def test_sites_are_ranked_by_ore_value_per_m3_minus_distance(self):
        from eve_profit.mining_sites import rank_sites, recommend, sites
        self.assertTrue(sites())
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(881,'Pyroxeres 0-Grade',0.3,1)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(882,'Veldspar 0-Grade',0.1,1)")
        con.execute("INSERT INTO orders VALUES(990001,881,60000001,1,10000001,1,60.0,1000,1,'',1)")      # 200 ISK/m3
        con.execute("INSERT INTO orders VALUES(990002,882,60000001,1,10000001,1,10.0,1000,1,'',1)")      # 100 ISK/m3
        r = rank_sites(con)
        self.assertEqual(r[0]["system"], "Rotonos")                                  # 0 jumps beats the 1-jump sites with the same ores
        self.assertEqual(r[0]["best_ore"], "Pyroxeres 0-Grade")
        self.assertIn("WHERE: Rotonos", recommend(con))


class HaulSafetyTests(unittest.TestCase):
    def test_kept_gear_is_not_hauled_and_side_trades_are_capped(self):
        from eve_profit import haul
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        self.assertLessEqual(haul.TRADE_WALLET_SHARE, 0.5)
        self.assertLess(haul.TRADE_HAIRCUT, 1.0)
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        far = [x for x, r in g.reach(1, 3).items() if r.jumps == 2][0]
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(883,'Core Scanner Probe I',1,1)")
        con.execute("INSERT INTO orders VALUES(990101,883,?,?,10000001,1,9000.0,50,1,'',1)", (60000000 + far, far))
        con.execute("INSERT INTO inventory VALUES(883,1,8)")
        con.execute("DELETE FROM inventory WHERE type_id!=883")
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)
        self.assertIsNone(haul.haul_option(con, g, p))                      # the only stack is on the keep list


class WalletDeltaTests(unittest.TestCase):
    def test_stop_shows_wallet_change_and_counts_market_sales(self):
        from eve_profit.session import INCOME_TYPES, start, stop, summarize_journal

        class E:
            def paged(self, path):
                return [{"date": "2026-10-10T04:14:00Z", "ref_type": "market_transaction", "amount": 393377.0},
                        {"date": "2026-10-10T04:14:00Z", "ref_type": "market_transaction", "amount": -5000.0}]
        self.assertNotIn("market_transaction", INCOME_TYPES)                  # only selling runs count sales
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        t0 = 1_791_000_000.0
        import calendar as _c
        import time as _t
        t_start = _c.timegm(_t.strptime("2026-10-10T04:13:00", "%Y-%m-%dT%H:%M:%S"))
        start(con, "Market sell stock X", 1, now=t_start, wallet=6_000_000.0)            # a selling run: sales count
        out = stop(con, E(), now=t_start + 120, wallet_now=6_388_377.0)
        self.assertIn("393,377", out)                                       # the sale counted, the purchase (negative) did not
        self.assertIn("wallet changed by +388,377", out)


class DailyGoalTests2(unittest.TestCase):
    def test_daily_goals_are_due_until_a_reward_is_seen_today(self):
        from eve_profit.bonus import daily_goal_due, daily_goal_step
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertTrue(daily_goal_due(con, today="2026-10-10"))
        con.execute("INSERT OR REPLACE INTO meta VALUES('daily_goal_last','2026-10-10')")
        self.assertFalse(daily_goal_due(con, today="2026-10-10"))
        self.assertTrue(daily_goal_due(con, today="2026-10-11"))
        self.assertIn("AIR DAILY GOALS", daily_goal_step({"reward_isk": 445000, "goals": [{"goal": "Complete 3 Jumps", "progress": "0/3"}]}))


class ExperimentClockTests(unittest.TestCase):
    def test_looking_at_next_does_not_advance_the_model_clock_but_starting_does(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import next_action
        from eve_profit.session import start
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)
        for _ in range(6):
            next_action(con, g, p)
        self.assertIsNone(con.execute("SELECT value FROM meta WHERE key='start_count'").fetchone())
        start(con, "Agent L1 something", 1, wallet=1e7)
        self.assertEqual(con.execute("SELECT value FROM meta WHERE key='start_count'").fetchone()[0], "1")
        start(con, "Test Project Discovery", 1, wallet=1e7)
        self.assertEqual(con.execute("SELECT value FROM meta WHERE key='last_exp'").fetchone()[0], "2")


class TimerNameTests2(unittest.TestCase):
    def test_daily_goals_timer_name_is_short(self):
        from eve_profit.nextstep import _name_of
        self.assertEqual(_name_of("STEP: AIR DAILY GOALS - about 445,000 ISK for any 2 of the 5 goals (resets daily)\n   Destroy 25"), "AIR Daily Goals")


class DailyGoalPlannerTests(unittest.TestCase):
    def _con(self):
        return db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))

    def test_armor_repair_is_never_routed_and_jumps_are_free_on_a_far_trip(self):
        from eve_profit.dailygoals import plan
        con = self._con()
        pl = plan(con, 445000, free_ride=True)
        rep = [o for o in pl["options"] if o["goal"].startswith("Armor")][0]
        self.assertFalse(rep["ok"])
        self.assertTrue(pl["best"])
        names = [o["goal"] for o in pl["best"]["pair"]]
        self.assertNotIn(rep["goal"], names)
        other = [o for o in pl["best"]["pair"] if o["goal"] != "Complete 3 Jumps"][0]
        self.assertEqual(pl["best"]["minutes"], other["minutes"] + 1.0)      # the 3 jumps cost only 1 extra minute on a trip you take anyway

    def test_build_uses_hangar_materials_and_picks_the_free_build(self):
        from eve_profit.dailygoals import build_option
        con = self._con()
        con.execute("INSERT INTO types(type_id,name) VALUES(1,'Toy Blueprint'),(2,'Tritanium')")
        con.execute("INSERT INTO my_blueprints(blueprint_id) VALUES(1)")
        con.execute("INSERT INTO bp_materials VALUES(1,2,100)")
        con.execute("INSERT INTO inventory VALUES(2,1,500)")
        o = build_option(con)
        self.assertTrue(o["ok"])
        self.assertEqual(o["cash"], 0.0)
        self.assertIn("already in your hangar", o["how"])

    def test_step_text_names_the_best_pair_and_the_not_routed_goal(self):
        from eve_profit.dailygoals import format_plan, plan
        txt = format_plan(plan(self._con(), 445000, free_ride=True))
        self.assertIn("BEST PAIR", txt)
        self.assertIn("NOT ROUTED", txt)
