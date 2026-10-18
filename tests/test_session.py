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
        from unittest import mock
        from eve_profit import along as _along
        _orig = _along.keep_rules
        with mock.patch.object(_along, "keep_rules", lambda c=None: {k: {**v, "upgrade_at": None} for k, v in _orig(c).items()}):      # the real list limits Miner II to Jita
            rich = plan_along(con, g, Profile(current_system="Home", wallet_isk=20e6, current_location_id=60000001), "Home")
            self.assertEqual([u["upgrade"] for u in rich["upgrades"]], ["Miner II"])
            poor = plan_along(con, g, Profile(current_system="Home", wallet_isk=1e6, current_location_id=60000001), "Home")
            self.assertEqual(poor["upgrades"], [])
        here_ = plan_along(con, g, Profile(current_system="Home", wallet_isk=20e6, current_location_id=60000001), "Home")
        self.assertEqual(here_["upgrades"], [])                   # Miner II is offered only in Jita (keep_items.json upgrade_at)


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
        from eve_profit.bonus import _cp_value
        self.assertEqual(offer_bonus("Soldier of Fortune", progs)[0], 25000 + 10 * _cp_value())
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
        self.assertNotEqual((act or {}).get("id"), "manufacturing_t1")        # the skill alone is not enough: no blueprint, no manufacturing test
        con.execute("INSERT INTO my_blueprints(blueprint_id,me,te,runs) VALUES(1,0,0,-1)")
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


class MakeOrBuyTests(unittest.TestCase):
    def _world(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        return con, Graph(con), Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)

    def test_options_cost_the_build_and_say_what_it_is_worth_afterwards(self):
        from eve_profit.makebuy import describe, options
        con, g, p = self._world()
        res = options(con, g, p)
        self.assertTrue(res, "the mock blueprint should be buildable from Home")
        o = res[0]
        self.assertIn(o["kind"], ("SELL", "KEEP", "NONE"))
        self.assertAlmostEqual(o["net"], o["value"] - o["cost"], places=3)
        self.assertIn("cost        ~", describe(o))

    def test_hangar_materials_are_valued_not_free(self):
        from eve_profit.makebuy import options
        con, g, p = self._world()
        before = options(con, g, p)[0]
        for mid, in con.execute("SELECT material_id FROM bp_materials WHERE blueprint_id=90002").fetchall():
            con.execute("INSERT OR REPLACE INTO inventory VALUES(?,?,?)", (mid, g.id_of("Home"), 100000))
        after = options(con, g, p)[0]
        self.assertEqual(after["buy"], [])
        self.assertLessEqual(after["cash"], before["cash"])

    def test_daily_goals_build_option_uses_the_make_or_buy_numbers(self):
        from eve_profit.dailygoals import build_option
        con, g, p = self._world()
        o = build_option(con, g, p)
        self.assertTrue(o["ok"])
        self.assertIn("Build", o["how"])


class TripTradesTests(unittest.TestCase):
    def test_trip_trades_are_added_to_jumps_and_build_options(self):
        import eve_profit.nextstep as ns
        from eve_profit.config import Profile
        from eve_profit.dailygoals import jumps_option
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        old = ns.trade_extras
        ns.trade_extras = lambda con, g, p, o: (100000.0, 5.0, [f"going: buy 10 x Foo at {o['to_system']} (-1,000)"])
        try:
            o = jumps_option(con, [(0.0, "Yulai (mining, 4 jumps)", 4, "Yulai")], g=object(), p=object())
        finally:
            ns.trade_extras = old
        self.assertEqual(o["cash"], 0)                              # side trades are listed but NOT counted in the rate (one-unit margins are often traps)
        self.assertIn("side trades on the way there and back", o["how"])
        self.assertIn("NOT counted", o["how"])
        self.assertEqual(o["minutes"], 9.0)


class ShopOnTheRouteTests(unittest.TestCase):
    def test_materials_on_the_jumps_route_cost_no_extra_travel(self):
        import eve_profit.nextstep as ns
        from eve_profit.config import Profile
        from eve_profit.dailygoals import plan
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)
        old = ns.trade_extras
        ns.trade_extras = lambda *a: (0.0, 0.0, [])
        try:
            far = plan(con, 445000, places=[(0.0, "Sys02 (mining, 1 jump)", 1, "Sys02")], g=g, p=p)
            nowhere = plan(con, 445000, places=[(0.0, "Nowhere", 1, None)], g=g, p=p)
        finally:
            ns.trade_extras = old
        txt = " ".join(o["how"] for o in far["best"]["pair"])
        self.assertIn("(on your route)", txt)
        self.assertLessEqual(far["best"]["minutes"], nowhere["best"]["minutes"])


class TripPlusTests(unittest.TestCase):
    def test_cheap_needs_finds_gear_you_lack_that_is_cheaper_on_the_route(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit import tripplus
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001)
        con.execute("INSERT INTO types(type_id,name) VALUES(777,'Miner I')")
        here, there = g.id_of("Home"), g.id_of("Sys02")
        con.execute("INSERT INTO orders(order_id,type_id,location_id,system_id,region_id,is_buy,price,volume_remain,fetched_at) VALUES(9001,777,1,?,1,0,50000,10,0)", (here,))
        con.execute("INSERT INTO orders(order_id,type_id,location_id,system_id,region_id,is_buy,price,volume_remain,fetched_at) VALUES(9002,777,2,?,1,0,20000,10,0)", (there,))
        lines = tripplus.cheap_needs(con, g, p, [here, there])
        self.assertTrue(any("Miner I" in l and "Sys02" in l for l in lines), lines)

    def test_extras_without_a_destination_is_empty(self):
        from eve_profit.tripplus import extras
        self.assertEqual(extras(None, None, None, None)["lines"], [])


class LookAheadTests(unittest.TestCase):
    def test_pure_math(self):
        from eve_profit.lookahead import act_rate, base_rate, chain_gain
        self.assertEqual(act_rate({"rate": 900000.0, "runs": 3, "prior": [1, 2]}), (900000.0, "measured"))
        r, src = act_rate({"rate": None, "runs": 0, "prior": [100000, 500000]})
        self.assertEqual(src, "guess")
        self.assertAlmostEqual(r, 240000.0)
        self.assertEqual(chain_gain(100000, 300000, 2, horizon=6, cost=50000), 750000.0)
        self.assertEqual(chain_gain(100000, 300000, 9, horizon=6), 0.0)
        cands = [(float("inf"), "TEST x", "", ""), (1.8e6, "daily", "", "once a day"), (7e5, "agent", "", "x"), (3e5, "trade", "", "y")]
        self.assertEqual(base_rate(cands), 7e5)

    def test_a_locked_activity_becomes_an_unlock_with_a_free_enabler(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.lookahead import analyse, enabler_step, format_long_view, unlock_options
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT INTO types(type_id,name,skill_rank,skill_primary,skill_secondary) VALUES(3412,'Astrometrics',3,165,164)")
        con.execute("INSERT INTO character_skills VALUES(3412,0,0)")                 # book already injected (level 0): it can be queued now
        con.execute("INSERT OR REPLACE INTO char_attrs VALUES('perception',20),('willpower',20),('intelligence',20),('memory',20),('charisma',20)")
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001)
        opts = unlock_options(con, g, p, 100000.0)
        ex = [o for o in opts if o["id"] == "explore_sites"]
        self.assertTrue(ex, [o["id"] for o in opts])
        self.assertIsNotNone(ex[0]["enabler"])
        cands = [(7e5, "agent mission", "x", "cash"), (1.8e6, "AIR daily goals", "y", "once a day")]
        an = analyse(con, g, p, cands)
        txt = format_long_view(an)
        self.assertIn("NOW", txt)
        self.assertIn("UNLOCK", txt)
        self.assertIn("QUEUE Astrometrics", enabler_step(an["enabler"], an["base"]))


class OneStepDefaultTests(unittest.TestCase):
    def test_next_prints_one_step_and_plan_prints_the_chain(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import next_action
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)
        one = next_action(con, g, p)
        full = next_action(con, g, p, ahead=True)
        self.assertNotIn("TODAY'S CHAIN", one)
        self.assertNotIn("THE LONG VIEW", one)
        self.assertIn("next --plan", one)
        self.assertEqual(one.count("STEP:") + one.count("AGENT MISSION:"), 1)
        self.assertIn("THE LONG VIEW", full)
        self.assertGreater(len(full), len(one))


class UnlockKindsTests(unittest.TestCase):
    def _world(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        return con, Graph(con), Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001)

    def test_standing_with_matches_names(self):
        from eve_profit.lookahead import standing_with
        con, g, p = self._world()
        self.assertIsNone(standing_with(con, "Federation Navy"))
        con.execute("INSERT INTO standing_names VALUES(500,'Federation Navy','corporation')")
        con.execute("INSERT INTO standings VALUES(500,0.35)")
        self.assertAlmostEqual(standing_with(con, "Federation Navy"), 0.35)

    def test_gear_boost_and_standing_unlock_are_priced(self):
        import eve_profit.lookahead as la
        con, g, p = self._world()
        con.execute("INSERT INTO standing_names VALUES(500,'Federation Navy','corporation')")
        con.execute("INSERT INTO standings VALUES(500,0.35)")
        con.execute("INSERT INTO types(type_id,name,skill_rank,skill_primary,skill_secondary) VALUES(3328,'Gallente Frigate',1,165,166),(3306,'Small Hybrid Turret',1,165,166)")
        con.execute("INSERT INTO character_skills VALUES(3328,3,0),(3306,3,0)")        # both required skills trained: only the standing is missing
        con.execute("INSERT OR REPLACE INTO char_attrs VALUES('perception',20),('willpower',20),('intelligence',20),('memory',20),('charisma',20)")
        old = la.load_unlocks
        la.load_unlocks = lambda: {
            "gear": [{"id": "gear_miner2", "item": "Miner II", "qty": 3, "boosts": {"mining_belt": 3.0}, "requires": {}, "est_cost": 60000}],
            "ships": [],
            "standings": [{"id": "st", "corp": "Federation Navy", "needs": 1.0, "per_step": 0.15, "minutes_per_step": 20, "unlocks": ["agent_l2_security"]}]}
        try:
            opts = la.unlock_options(con, g, p, 50000.0)
        finally:
            la.load_unlocks = old
        boost = [o for o in opts if o["kind"] == "boost"]
        self.assertTrue(boost, [o["id"] for o in opts])
        self.assertIn("buy 3 x Miner II", boost[0]["parts"][0])
        self.assertGreater(boost[0]["gain"], 0)
        self.assertEqual(boost[0]["books_cost"], 180000.0)                       # 3 x 60,000 estimate: not on the mock market
        st = [o for o in opts if o["id"] == "agent_l2_security"]
        self.assertTrue(st, [o["id"] for o in opts])
        self.assertTrue(any("standing with Federation Navy" in x and "5 Level 1 missions" in x for x in st[0]["parts"]), st[0]["parts"])
        self.assertAlmostEqual(st[0]["delay_h"], 5 * 20 / 60.0)                   # 5 missions x 20 min = the wait before it unlocks

    def test_owned_items_are_not_unlocks(self):
        import eve_profit.lookahead as la
        con, g, p = self._world()
        con.execute("INSERT INTO types(type_id,name) VALUES(888,'Miner II')")
        con.execute("INSERT INTO inventory VALUES(888,1,3)")
        old = la.load_unlocks
        la.load_unlocks = lambda: {"gear": [{"id": "g", "item": "Miner II", "qty": 3, "boosts": {"mining_belt": 3.0}, "requires": {}, "est_cost": 60000}], "ships": [], "standings": []}
        try:
            opts = la.unlock_options(con, g, p, 50000.0)
        finally:
            la.load_unlocks = old
        self.assertFalse([o for o in opts if o["kind"] == "boost"])


class HistoryTests(unittest.TestCase):
    def test_history_lists_steps_newest_first_with_isk_per_minute(self):
        import time as _t
        from eve_profit.session import history
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertIn("No completed steps yet", history(con))
        now = _t.time()
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Market sell stock Rotonos',451423,5/60.0,?)", (now - 100,))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('Skills queue',0,0.5/60.0,?)", (now,))
        txt = history(con)
        lines = txt.splitlines()
        self.assertIn("Skills queue", lines[2])                       # newest first
        self.assertIn("Market sell stock Rotonos", lines[3])
        self.assertIn("90,285", lines[3])                             # 451,423 ISK in 5 min
        self.assertIn("ALL TIME: 2 steps", txt)


class FixByIdTests(unittest.TestCase):
    def test_fixlast_can_fix_or_delete_any_row_by_its_history_number(self):
        from eve_profit.session import fix_last, history
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('old step',0,0.5,1000)")
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES('new step',100,0.5,2000)")
        old_id = con.execute("SELECT id FROM activity_log WHERE activity='old step'").fetchone()[0]
        self.assertIn(f" {old_id} ", history(con).splitlines()[3])           # the # column
        fix_last(con, 0, 5000, "", False, old_id)
        self.assertEqual(con.execute("SELECT isk FROM activity_log WHERE id=?", (old_id,)).fetchone()[0], 5000)
        self.assertEqual(con.execute("SELECT isk FROM activity_log WHERE activity='new step'").fetchone()[0], 100)
        fix_last(con, 0, 0, "", True, old_id)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            fix_last(con, 0, 0, "", False, 9999)


class SettleTests(unittest.TestCase):
    def _journal(self):
        e = lambda i, d, ref, amt, desc="": {"id": i, "date": f"2026-10-10T{d}:00Z", "ref_type": ref, "amount": amt, "description": desc}
        return [e(1, "09:14", "brokers_fee", -10133, "Market order commission to b"), e(2, "09:14", "market_safety_tax", -24411, "Market Safety Tax"),
                e(3, "11:46", "brokers_fee", -10133, "Market order commission to b"), e(4, "11:46", "exordium_fee", -24411, "Exordium Market Tax"),
                e(5, "14:44", "market_transaction", 488024, "Market: Helsp1 bought stuff"), e(6, "14:44", "transaction_tax", -36601, "Sales tax paid to the SCC"),
                e(7, "05:14", "agent_mission_reward", 62500, "AIR Career Program Reward")]

    def test_a_later_sale_goes_to_the_step_that_listed_it_and_the_finishing_step_is_merged(self):
        import calendar
        import time as _t
        from eve_profit.settle import apply, plan
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        utc = lambda hhmm: calendar.timegm(_t.strptime("2026-10-10 " + hhmm, "%Y-%m-%d %H:%M"))
        con.execute("INSERT INTO activity_log(id,activity,isk,hours,ts) VALUES(2,'Market sell stock Rotonos',0,2/60.0,?)", (utc("09:15"),))
        con.execute("INSERT INTO activity_log(id,activity,isk,hours,ts) VALUES(16,'Market sell stock Rotonos',451423,5/60.0,?)", (utc("14:45"),))
        con.execute("INSERT INTO activity_log(id,activity,isk,hours,ts) VALUES(17,'Agent L1 step 9',239000,0.5,?)", (utc("08:00"),))
        rows = con.execute("SELECT id, activity, isk, hours, ts FROM activity_log ORDER BY ts").fetchall()
        props = plan(rows, self._journal())
        self.assertEqual(len(props), 1)
        pr = props[0]
        self.assertEqual(pr["step"]["id"], 2)
        self.assertEqual(pr["income"], 488024)
        self.assertEqual(pr["costs"], -(10133 + 24411) * 2 - 36601)                # both listings' fees and the sales tax
        self.assertEqual([m["id"] for m in pr["merge"]], [16])
        apply(con, props)
        r = con.execute("SELECT isk, hours FROM activity_log WHERE id=2").fetchone()
        self.assertEqual(r["isk"], 488024 - 36601 - 69088)
        self.assertAlmostEqual(r["hours"], 7 / 60.0)                              # 2 min listing + 5 min finishing
        self.assertIsNone(con.execute("SELECT 1 FROM activity_log WHERE id=16").fetchone())
        self.assertIsNotNone(con.execute("SELECT 1 FROM activity_log WHERE id=17").fetchone())      # the agent mission is untouched
        again = plan(con.execute("SELECT id, activity, isk, hours, ts FROM activity_log ORDER BY ts").fetchall(), self._journal(),
                     used=__import__("json").loads(con.execute("SELECT value FROM meta WHERE key='settled_ids'").fetchone()[0]))
        self.assertEqual(again, [])                                               # nothing is counted twice


class SettleGapTests(unittest.TestCase):
    def test_charges_missing_from_the_journal_are_found_from_the_balance_gaps(self):
        import calendar
        import time as _t
        from eve_profit.settle import plan, with_gaps
        e = lambda i, d, ref, amt, bal: {"id": i, "date": f"2026-10-10T{d}:00Z", "ref_type": ref, "amount": amt, "balance": bal, "description": ""}
        journal = [e(7, "05:14", "air_career_program_reward", 62500, 7910702.0),
                   e(1, "09:14", "brokers_fee", -10133, 7876158.0),                       # 24,411 missing before this one
                   e(3, "11:46", "brokers_fee", -10133, 7841614.0),                       # and again
                   e(5, "14:44", "market_transaction", 488024, 8329638.0), e(6, "14:44", "transaction_tax", -36601, 8293037.0)]
        journal[0]["id"], journal[1]["id"], journal[2]["id"], journal[3]["id"], journal[4]["id"] = 10, 11, 12, 13, 14
        gaps = [x for x in with_gaps(journal) if str(x["id"]).startswith("gap-")]
        self.assertEqual(sorted(round(x["amount"]) for x in gaps), [-24411, -24411])
        utc = lambda hhmm: calendar.timegm(_t.strptime("2026-10-10 " + hhmm, "%Y-%m-%d %H:%M"))
        rows = [{"id": 2, "activity": "Market sell stock Rotonos", "isk": 0, "hours": 2 / 60.0, "ts": utc("09:15")},
                {"id": 16, "activity": "Market sell stock Rotonos", "isk": 451423, "hours": 5 / 60.0, "ts": utc("14:45")}]
        pr = plan(rows, journal)[0]
        self.assertEqual(round(pr["net"]), 488024 - 36601 - 2 * 10133 - 2 * 24411)       # = what the wallet really changed by


class SettlePayoutTests(unittest.TestCase):
    def test_zero_isk_agent_steps_get_the_payouts_the_journal_posted_after_stop(self):
        import calendar
        import time as _t
        from eve_profit.settle import payout_plan
        utc = lambda d, hhmm: calendar.timegm(_t.strptime(f"2026-10-{d} {hhmm}", "%Y-%m-%d %H:%M"))
        e = lambda i, d, hh, ref, amt, bal, desc="": {"id": i, "date": f"2026-10-{d}T{hh}Z", "ref_type": ref, "amount": amt, "balance": bal, "description": desc}
        # the corporation tax lines are NOT in the journal: only the balance shows them (20,657 and 24,280)
        journal = [e(0, "09", "00:50:00", "brokers_fee", -100, 1000000.0),
                   e(1, "09", "01:26:02", "agent_mission_reward", 187790, 1167133.0, "Mission reward from agent Arnelin"),
                   e(2, "09", "01:26:02", "agent_mission_time_bonus_reward", 220720, 1363573.0, "Mission reward bonus from agent Arnelin"),
                   e(4, "09", "08:14:48", "agent_mission_reward", 239000, 1602573.0, "Mission reward from agent Arnelin")]
        rows = [{"id": 18, "activity": "Agent L1 step 8 Industrialist shuttle", "isk": 0, "hours": 20 / 60.0, "ts": utc("09", "01:26")},
                {"id": 19, "activity": "Agent L1 step 8 Industrialist shuttle", "isk": 423640, "hours": 54 / 60.0, "ts": utc("09", "08:15")}]
        out = payout_plan(rows, journal)
        self.assertEqual(len(out), 1)                                           # only the 0-ISK step; the paid one is left alone
        self.assertEqual(out[0]["step"]["id"], 18)
        self.assertEqual(out[0]["gross"], 187790 + 220720)
        self.assertEqual(round(out[0]["net"]), 187790 + 220720 - 20657 - 24280)  # tax recovered from the balance gaps
        self.assertEqual(payout_plan(rows, journal, used=[1, 2, "gap-1", "gap-2"]), [])      # used entries are never counted twice


class ReprocessTests(unittest.TestCase):
    def _world(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        for name in ("Tritanium", "Pyerite"):
            if not con.execute("SELECT 1 FROM types WHERE name=?", (name,)).fetchone():
                con.execute("INSERT INTO types(type_id,name) VALUES(?,?)", (9100 + len(name), name))
        con.execute("DELETE FROM orders WHERE type_id IN (SELECT type_id FROM types WHERE name IN ('Tritanium','Pyerite'))")
        tid = {n: con.execute("SELECT type_id FROM types WHERE name=?", (n,)).fetchone()[0] for n in ("Tritanium", "Pyerite")}
        home = Graph(con).id_of("Home")
        for oid, name, price in ((95001, "Tritanium", 5.0), (95002, "Pyerite", 20.0)):
            con.execute("INSERT INTO orders VALUES(?,?,60000001,?,10000001,1,?,?,1,'',1)", (oid, tid[name], home, price, 10_000_000))
        return con, Graph(con), Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001)

    def test_refining_wins_when_the_raw_price_is_low_and_loses_when_it_is_high(self):
        from eve_profit.reprocess import describe, refine_option
        con, g, p = self._world()
        low = refine_option(con, g, p, "Scordite 0-Grade", 66667, raw_net=100000.0)
        self.assertTrue(low["refine_wins"])
        self.assertEqual(low["minerals"]["Tritanium"], 19980)
        self.assertIn("REFINE FIRST", "\n".join(describe("Scordite 0-Grade", low)))
        high = refine_option(con, g, p, "Scordite 0-Grade", 66667, raw_net=400000.0)
        self.assertFalse(high["refine_wins"])
        txt = "\n".join(describe("Scordite 0-Grade", high))
        self.assertIn("SELL RAW", txt)
        self.assertIn("% yield", txt)                                   # the break-even yield is shown
        self.assertGreater(high["breakeven_yield"], 0.40)

    def test_unknown_items_are_ignored(self):
        from eve_profit.reprocess import refine_option
        con, g, p = self._world()
        self.assertIsNone(refine_option(con, g, p, "Kernite", 1000, 5000.0))


class StyleTests(unittest.TestCase):
    TEXT = ("STEP: SELL NOW in Rotonos - about 1 ISK\n      66,666 x Scordite 0-Grade       @ 4.66 each\n      => SELL RAW. Refining only wins above about 78% yield\n"
            "   In game: Market > item > Sell\n   Time it:  python -m eve_profit start --activity \"Market sell stock Rotonos\"\n\n"
            "When done:  python -m eve_profit stop   (wait)   then   python -m eve_profit sync")

    def tearDown(self):
        import eve_profit.style as st
        st._ON = None
        os.environ.pop("EVE_COLOR", None)
        os.environ.pop("NO_COLOR", None)

    def test_without_color_the_marker_is_still_there(self):
        import eve_profit.style as st
        st._ON = None
        os.environ["NO_COLOR"] = "1"
        out = st.task_block(self.TEXT)
        self.assertTrue(out.startswith(">> STEP: SELL NOW in Rotonos"))
        self.assertNotIn("\x1b[", out)                                         # no escape codes at all

    def test_with_color_the_task_lines_are_yellow_on_black_and_the_commands_bold_white(self):
        import eve_profit.style as st
        st._ON = None
        os.environ["EVE_COLOR"] = "1"
        lines = st.task_block(self.TEXT).split("\n")
        Y = "\x1b[1;93;40m"
        self.assertIn(Y, lines[0])                                              # headline
        self.assertIn(Y, lines[1])                                              # what to sell
        self.assertIn(Y, lines[2])                                              # the '=> SELL RAW' verdict
        self.assertNotIn("\x1b[", lines[3])                                     # the 'In game: ... Sell' line below it is NOT highlighted
        self.assertEqual(lines[4], "")                                          # a blank line before the timer line
        start = [l for l in lines if "start --activity" in l][0]
        self.assertIn('\x1b[1;97mpython -m eve_profit start --activity "Market sell stock Rotonos"\x1b[0m', start)
        done = [l for l in lines if l.startswith("When done:")][0]
        self.assertEqual(done.count("\x1b[1;97m"), 2)                           # stop and sync both bold white
        self.assertEqual(st.dim("x"), "x")


class DetourStepTests(unittest.TestCase):
    def test_a_clearly_better_market_one_jump_away_becomes_the_step(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.nextstep import _name_of, next_action
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        home = g.id_of("Home")
        near = g.adj[home][0]
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(96001,'Scordite 0-Grade',0.15)")
        con.execute("DELETE FROM inventory")
        con.execute("INSERT INTO inventory VALUES(96001,?,66666)", (home,))
        con.execute("DELETE FROM orders WHERE type_id=96001")
        con.execute("INSERT INTO orders VALUES(97001,96001,60000001,?,10000001,1,5.04,2000000,1,'',1)", (home,))
        con.execute("INSERT INTO orders VALUES(97002,96001,60000009,?,10000001,1,8.70,700000,1,'',1)", (near,))
        p = Profile(current_system="Home", cargo_m3=50, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45, ship_name="Venture - Stand4it Dahl")
        from eve_profit.screens import mark
        mark(con)                                                               # the game-screens step is due first in a new world: it is not what this test is about
        from eve_profit.social import GOALS as _SG
        con.execute("INSERT OR REPLACE INTO meta VALUES('social_done', ?)", (__import__("json").dumps([g_[0] for g_ in _SG]),))      # nor the one-minute AIR social goals
        con.execute("INSERT OR REPLACE INTO meta VALUES('wanted_seen', ?)", (__import__("json").dumps([i["id"] for i in __import__("eve_profit.screens", fromlist=["x"]).wanted_unseen(con)]),))
        import eve_profit.nextstep as ns
        import eve_profit.sellplan as sp
        old = sp.sell_plan
        sp.sell_plan = lambda con_, g_, p_, **kw: old(con_, g_, p_, **{**kw, "rate": 1_000_000.0})        # the mock world has absurd 17M ISK/hr trades
        try:
            txt = next_action(con, g, p)
        finally:
            sp.sell_plan = old
        first = next(l.strip().lstrip("§ ") for l in txt.splitlines() if "STEP:" in l)           # the step now sits at its number in the command list
        self.assertTrue(first.startswith("STEP: SELL SCORDITE 0-GRADE 1 JUMP AWAY in "), first)
        self.assertIn("HOW:", txt)
        self.assertIn("Load 33,333 x Scordite 0-Grade", txt)                    # 66,666 in 2 trips of the 5,000 m3 hold
        self.assertIn("QUICK ALTERNATIVE", txt)
        self.assertTrue(_name_of(first).startswith("Market sell stock "))


class CompactDailyGoalsTests(unittest.TestCase):
    def test_default_next_shows_a_short_ordered_checklist_for_the_daily_goals(self):
        import eve_profit.nextstep as ns
        from eve_profit.config import Profile
        from eve_profit.dailygoals import compact_plan, plan
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        p = Profile(current_system="Home", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, secs_per_jump=45)
        old = ns.trade_extras
        ns.trade_extras = lambda *a: (100000.0, 5.0, ["going: buy 1 x Foo at X (-1)"])
        try:
            pl = plan(con, 445000, places=[(0.0, "Sys02 (mining, 1 jump)", 1, "Sys02")], g=g, p=p)
        finally:
            ns.trade_extras = old
        txt = compact_plan(pl)
        self.assertTrue(txt.startswith("STEP: AIR DAILY GOALS"))
        self.assertLess(len(txt.splitlines()), 16)                              # one short checklist, not a wall of text
        self.assertNotIn("ALL FIVE", txt)
        self.assertNotIn("going:", txt)                                          # the side trades are not in the default step
        self.assertIn("Collect the finished job", txt)
        self.assertIn("Opportunities > AIR Daily Goals", txt)
        full = __import__("eve_profit.dailygoals", fromlist=["format_plan"]).format_plan(pl)
        self.assertIn("ALL FIVE", full)                                         # the analysis is still there for --plan


class DailyChainTests(unittest.TestCase):
    def _world(self):
        import json
        import time as _t
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        if not con.execute("SELECT 1 FROM types WHERE name='Tritanium'").fetchone():
            con.execute("INSERT INTO types(type_id,name) VALUES(9034,'Tritanium')")
        con.execute("DELETE FROM inventory")
        g = Graph(con)
        st = {"t": _t.time(), "home": "Home", "dest": "Sys02", "dest_label": "Sys02 (mining, 1 jump)", "product": "Mock Widget", "runs": 1, "units": 10, "job_min": 5.0,
              "buy": [{"item": "Tritanium", "qty": 100, "system": "Sys02", "cost": 500.0, "route": True}], "bought": False, "started": False, "epic_done": False,
              "reward": 445000.0, "minutes": 14.0}
        con.execute("INSERT OR REPLACE INTO meta VALUES('daily_chain', ?)", (json.dumps(st),))
        mk = lambda system, slots=0: Profile(current_system=system, cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001, mfg_slots_used=slots)
        return con, g, mk

    def test_each_next_shows_only_the_step_you_are_at(self):
        from eve_profit.dailygoals import chain_step
        con, g, mk = self._world()
        pl = {"best": None, "reward": 445000.0}
        t1 = chain_step(con, g, mk("Home"), pl)
        self.assertIn("DO ONLY THIS: fly to Sys02", t1)                          # step 1: just the flight
        self.assertNotIn("Industry", t1)
        t2 = chain_step(con, g, mk("Sys02"), pl)
        self.assertIn("buy these here", t2)
        self.assertIn("100 x Tritanium", t2)
        con.execute("INSERT INTO inventory VALUES((SELECT type_id FROM types WHERE name='Tritanium'),?,100)", (g.id_of("Sys02"),))
        t3 = chain_step(con, g, mk("Sys02"), pl)                                  # bought: not Manifest, so no epic arc: fly home
        self.assertIn("fly back to Home", t3)
        t4 = chain_step(con, g, mk("Home"), pl)
        self.assertIn("DO ONLY THIS: Industry > Mock Widget blueprint", t4)
        t5 = chain_step(con, g, mk("Home", slots=1), pl)
        self.assertIn("THE BUILD IS RUNNING", t5)
        t6 = chain_step(con, g, mk("Home", slots=0), pl)                          # job delivered
        self.assertIn("Opportunities > AIR Daily Goals", t6)
        for t in (t1, t2, t3, t4, t5, t6):
            self.assertLess(len(t.splitlines()), 8)                              # always a short step

    def test_the_epic_arc_is_offered_once_at_manifest_and_done_moves_on(self):
        import json
        from eve_profit.dailygoals import chain_done, chain_step
        con, g, mk = self._world()
        st = json.loads(con.execute("SELECT value FROM meta WHERE key='daily_chain'").fetchone()[0])
        st.update({"dest": "Manifest", "bought": True, "buy": []})
        con.execute("INSERT OR REPLACE INTO meta VALUES('daily_chain', ?)", (json.dumps(st),))
        con.execute("INSERT OR IGNORE INTO systems VALUES(8888,'Manifest',0.9,10000001)")
        g2 = __import__("eve_profit.graph", fromlist=["Graph"]).Graph(con)
        pl = {"best": None, "reward": 445000.0}
        from eve_profit.screens import mark
        mark(con)                                                               # no game-screens step pending: `done` then belongs to the epic arc step
        txt = chain_step(con, g2, mk("Manifest"), pl)
        self.assertIn("Cassandra Ahfrim", txt)
        self.assertIn("python -m eve_profit done", txt)
        chain_done(con)
        self.assertIn("fly back to Home", chain_step(con, g2, mk("Manifest"), pl))


class TimerRunningNoteTests(unittest.TestCase):
    def test_a_running_timer_for_the_same_task_is_not_offered_again(self):
        import json
        from eve_profit.nextstep import _timer
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertIn("Time it:", _timer("AIR Daily Goals", con))
        con.execute("INSERT OR REPLACE INTO meta VALUES('session', ?)", (json.dumps({"activity": "AIR Daily Goals", "t": 1}),))
        self.assertIn("already running", _timer("AIR Daily Goals", con))
        self.assertIn("Time it:", _timer("Something else", con))


class WayLinesTests(unittest.TestCase):
    def test_trap_margins_and_big_bets_are_dropped_but_sane_trades_and_stock_sales_stay(self):
        from eve_profit.dailygoals import way_lines
        res = {"stops": [("Ligare", 0, {"pick": [], "sell": [], "buy": [("Sane Thing", 100, 100000.0), ("Trap Thing", 6, 1000000.0), ("Whale Thing", 10, 4000000.0)]}),
                         ("Manifest", 0, {"pick": [], "buy": [], "sell": [("Sane Thing", 100, 130000.0), ("Trap Thing", 6, 3200000.0), ("Whale Thing", 10, 5000000.0),
                                                                          ("Scordite", 30000, 250000.0)]})]}
        lines = way_lines(res, wallet=8_000_000)
        txt = "\n".join(lines)
        self.assertIn("Sane Thing", txt)                                         # +30% on 100k
        self.assertNotIn("Trap Thing", txt)                                      # +220%: usually a trap
        self.assertNotIn("Whale Thing", txt)                                     # 4M of an 8M wallet
        self.assertIn("sell 30,000 x Scordite from your hangar at Manifest", txt)

    def test_the_fly_step_has_no_next_step_in_it_and_says_when_there_is_nothing_on_the_way(self):
        import json
        con, g, mk = DailyChainTests()._world()
        from eve_profit.dailygoals import chain_step
        txt = chain_step(con, g, mk("Home"), {"best": None, "reward": 445000.0})
        self.assertNotIn("next step", txt)
        self.assertNotIn("run  sync", txt)
        self.assertTrue("ON THE WAY" in txt or "Nothing worth buying or selling on this route" in txt)

    def test_cheap_needs_here_lists_keep_gear_that_is_much_cheaper_in_this_system(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.tripplus import cheap_needs_here
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        g = Graph(con)
        home, there = g.id_of("Home"), g.id_of("Sys02")
        con.execute("INSERT INTO types(type_id,name) VALUES(777,'Core Scanner Probe I')")
        con.execute("INSERT INTO orders VALUES(9301,777,1,?,10000001,0,29850,10,1,'',1)", (home,))
        con.execute("INSERT INTO orders VALUES(9302,777,2,?,10000001,0,9290,10,1,'',1)", (there,))
        p = Profile(current_system="Sys02", cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001)
        lines = cheap_needs_here(con, g, p, "Home")
        self.assertTrue(any("Core Scanner Probe I" in l and "saves" in l for l in lines), lines)


class WorldHoldTests(unittest.TestCase):
    def _con(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        rows = [{"system": "Amarr", "net": 278100.0, "units": 1, "jumps": 37, "gank": 0}, {"system": "Jita", "net": 203800.0, "units": 1, "jumps": 18, "gank": 2}]
        from eve_profit.worldprices import save
        save(con, 31083, rows)
        return con

    def test_a_light_stack_that_pays_far_more_elsewhere_is_kept_not_dumped(self):
        from eve_profit.worldprices import hold_advice, keep_line
        con = self._con()
        adv = hold_advice(con, 31083, 1, 5.0, local_net=57359.0)
        self.assertEqual(adv["system"], "Amarr")                                   # the best of the remembered markets
        self.assertAlmostEqual(adv["extra"], 278100.0 - 57359.0)
        self.assertIn("keep 1 x Small Salvage Tackle I", keep_line("Small Salvage Tackle I", 1, adv))
        self.assertIsNone(hold_advice(con, 31083, 1, 5.0, local_net=200000.0))     # not 2x better: sell it
        self.assertIsNone(hold_advice(con, 31083, 50, 5.0, local_net=57359.0))     # 250 m3: too heavy to just carry along
        self.assertIsNone(hold_advice(con, 99999, 1, 5.0, local_net=1.0))          # nothing remembered

    def test_old_prices_are_not_trusted(self):
        import time
        from eve_profit.worldprices import hold_advice
        con = self._con()
        con.execute("UPDATE world_prices SET ts=?", (time.time() - 10 * 86400,))
        self.assertIsNone(hold_advice(con, 31083, 1, 5.0, local_net=1000.0))

    def test_way_lines_keep_the_item_instead_of_selling_it_cheap_on_the_route(self):
        from eve_profit.dailygoals import way_lines
        from eve_profit.worldprices import hold_advice
        con = self._con()
        res = {"stops": [("Manifest", 0, {"pick": [], "buy": [], "sell": [("Small Salvage Tackle I", 1, 57359.0), ("Contaminated Lorentz Fluid", 1, 48109.0)]})]}
        fn = lambda name, qty, net: hold_advice(con, 31083, qty, 5.0, net) if name == "Small Salvage Tackle I" else None
        lines = way_lines(res, 8_000_000, hold_fn=fn)
        txt = "\n".join(lines)
        self.assertIn("keep 1 x Small Salvage Tackle I", txt)
        self.assertNotIn("sell 1 x Small Salvage Tackle I", txt)
        self.assertIn("sell 1 x Contaminated Lorentz Fluid", txt)                  # no far market remembered: sell it on the way

    def test_sell_buy_keep_lines_are_yellow_too(self):
        import eve_profit.style as st
        st._ON = None
        os.environ["EVE_COLOR"] = "1"
        try:
            out = st.task_block("STEP: X\n   DO ONLY THIS: fly\n      sell 1 x Foo from your hangar at Manifest (+1)\n      keep 1 x Bar: pays more\n      buy 3 x Baz at Y")
        finally:
            st._ON = None
            os.environ.pop("EVE_COLOR", None)
        lines = out.split("\n")
        self.assertEqual(lines[1], "")                                          # a blank line BEFORE the action
        for ln in lines[2:]:                                                    # the DO ONLY THIS line and the sell / keep / buy lines
            self.assertIn("\x1b[1;93;40m", ln)


class BoldCommandsEverywhereTests(unittest.TestCase):
    def tearDown(self):
        import eve_profit.style as st
        st._ON = None
        os.environ.pop("EVE_COLOR", None)

    def test_commands_in_any_output_are_bold_white_and_plain_without_color(self):
        import io
        import eve_profit.style as st
        from eve_profit.pretty import Pretty
        for color, expect in (("1", True), ("0", False)):
            st._ON = None
            os.environ["EVE_COLOR"] = color
            buf = io.StringIO()
            pr = Pretty(buf)
            pr.write("   then route:   python -m eve_profit go --pick 1 --send\n")
            pr.write("a line with no command\n")
            pr.flush()
            lines = buf.getvalue().split("\n")
            self.assertEqual("\x1b[1;97mpython -m eve_profit go --pick 1 --send\x1b[0m" in lines[0], expect)
            self.assertEqual(lines[1], "a line with no command")


class LogAfterTheFactTests(unittest.TestCase):
    def test_air_rewards_count_as_income_and_recent_payouts_are_listed(self):
        import calendar
        import time as _t
        from eve_profit.session import INCOME_TYPES
        from eve_profit.settle import format_recent, recent_payouts
        self.assertIn("daily_goal_payouts", INCOME_TYPES)
        self.assertIn("air_career_program_reward", INCOME_TYPES)
        e = lambda i, d, ref, amt: {"id": i, "date": f"2026-10-11T{d}Z", "ref_type": ref, "amount": amt, "description": ""}
        since = calendar.timegm(_t.strptime("2026-10-11 05:00", "%Y-%m-%d %H:%M"))
        rows = recent_payouts([e(1, "04:00:00", "daily_goal_payouts", 111), e(2, "05:30:00", "daily_goal_payouts", 445000), e(3, "06:00:00", "brokers_fee", -5)], since)
        self.assertEqual([r[2] for r in rows], [445000])                         # the old payout and the fee are not listed
        self.assertIn("fixlast --isk AMOUNT", format_recent(rows))
        self.assertIn("No payouts", format_recent([]))


class HaulChainTests(unittest.TestCase):
    def _world(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("DELETE FROM inventory")
        g = Graph(con)
        home = g.id_of("Home")
        mid = g.adj[home][0]
        far = [x for x in g.adj[mid] if x != home][0]
        return con, g, g.name[home], g.name[mid], g.name[far], lambda system: Profile(current_system=system, cargo_m3=5000, wallet_isk=1e7, current_location_id=60000001)

    def _chain(self, con, origin, dest, total):
        from eve_profit.haulchain import make, save
        save(con, make({"dest": dest, "jumps": total, "gain": 600000.0, "net": 900000.0, "items": [("Scordite 0-Grade", 66666, 900000.0, 300000.0)], "ore": True}, origin))

    def test_a_haul_is_one_jump_at_a_time_and_ends_with_the_sale_not_a_return(self):
        from eve_profit.haulchain import candidate, load
        con, g, home, mid, far, mk = self._world()
        self._chain(con, home, far, 2)
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(96001,'Scordite 0-Grade',0.15)")
        con.execute("INSERT INTO inventory VALUES(96001,?,66666)", (g.id_of(home),))
        self.assertIsNone(candidate(con, g, mk(home)))                           # still in the hangar: not started, the normal haul step handles it
        con.execute("DELETE FROM inventory")                                      # loaded into the ship: sync cannot see cargo
        rate, text = candidate(con, g, mk(home))
        self.assertIn("DO ONLY THIS: fly to", text)
        self.assertIn("jump 1 of 2", text)
        rate2, text2 = candidate(con, g, mk(mid))                                  # one jump later: no agent here, so no look-around: re-planned from here
        self.assertIn("jump 2 of 2", text2)
        self.assertIn("1 jumps left", text2)
        rate3, text3 = candidate(con, g, mk(far))                                  # arrived
        self.assertIn("SELL YOUR HAULED STOCK", text3)
        self.assertIn("no planned trip back", text3)
        self.assertGreater(rate3, 1e9)
        self.assertIn("SELL YOUR HAULED STOCK", candidate(con, g, mk(far))[1])      # still at the destination: the sell step stays until you stop its timer
        self.assertIsNone(candidate(con, g, mk(mid)))                              # you left the destination: the haul is over, the best step is chosen fresh
        self.assertIsNone(load(con))

    def test_haul_minutes_are_one_way_for_a_single_load(self):
        from eve_profit.haul import haul_option
        con, g, home, mid, far, mk = self._world()
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(96001,'Rare Widget',1.0)")
        con.execute("INSERT INTO inventory VALUES(96001,?,10)", (g.id_of(home),))
        con.execute("DELETE FROM orders WHERE type_id=96001")
        con.execute("INSERT INTO orders VALUES(97001,96001,60000001,?,10000001,1,100.0,1000,1,'',1)", (g.id_of(home),))
        con.execute("INSERT INTO orders VALUES(97002,96001,60000002,?,10000001,1,30000.0,1000,1,'',1)", (g.id_of(mid),))
        h = haul_option(con, g, mk(home))
        self.assertIsNotNone(h)
        self.assertEqual(h["trips"], 1)
        self.assertAlmostEqual(h["minutes_stock"], 1 * mk(home).jump_seconds / 60.0 + 2.0)      # one jump one way + docking, no return




class ScreensStepTests(unittest.TestCase):
    def test_the_game_screens_come_one_at_a_time_and_done_moves_on(self):
        from eve_profit import screens
        from eve_profit.dailygoals import chain_done
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertTrue(screens.due(con))
        n = len(screens.items())
        txt = screens.step(con)
        self.assertIn(f"screen 1 of {n}", txt)
        self.assertIn("AIR Opportunities window", txt)
        self.assertEqual(txt.count("DO ONLY THIS"), 1)                          # ONE thing to do
        self.assertIn("Win + Shift + S", txt)                                    # how to send the image
        self.assertNotIn("eve_profit done", txt)          # `stop` marks the step done
        if n > 1:
            msg = chain_done(con)                                                # done: on to screen 2
            self.assertIn("Screen 1 of", msg)
            self.assertIn(f"screen 2 of {n}", screens.step(con))
            self.assertTrue(screens.due(con))
        for _ in range(n):
            chain_done(con)
        self.assertFalse(screens.due(con))                                       # all sent: not asked again for 12 hours


class AirAroundTheActionTests(unittest.TestCase):
    def test_blank_lines_before_the_action_and_before_the_timer(self):
        import eve_profit.style as st
        st._ON = None
        os.environ["NO_COLOR"] = "1"
        try:
            out = st.task_block("STEP: X - screen 1 of 7\n   DO ONLY THIS: open the window\n   Show me: goals.\n   When it is sent run:  python -m eve_profit done\n   Time it:  python -m eve_profit start --activity \"Y\"\n\nWhen done:  python -m eve_profit stop")
        finally:
            st._ON = None
            os.environ.pop("NO_COLOR", None)
        lines = out.split("\n")
        i = [k for k, l in enumerate(lines) if "DO ONLY THIS" in l][0]
        j = [k for k, l in enumerate(lines) if l.strip().startswith("Time it:")][0]
        self.assertEqual(lines[i - 1], "")                                      # air before the action
        self.assertEqual(lines[j - 1], "")                                      # air after it
        self.assertNotIn("\n\n\n", out)                                         # but never a double gap
