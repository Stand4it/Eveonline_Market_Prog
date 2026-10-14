import unittest



class ShipLinesTests(unittest.TestCase):
    def test_ship_and_fit_lines(self):
        from eve_profit import haul
        from eve_profit.db import connect
        from eve_profit.config import Profile
        con = connect(":memory:")
        con.execute("INSERT INTO types(type_id,name,volume,capacity) VALUES(1,'Expanded Cargohold I',5,0)")
        con.execute("INSERT INTO inventory VALUES(1,7,1)")

        class G:
            def id_of(self, n):
                return 7
        p = Profile(ship_name="Imicus", cargo_m3=400.0, current_system="Rotonos")
        out = "\n".join(haul.ship_lines(con, G(), p, {"other_m3": 12.0, "ore": False}))
        self.assertIn("SHIP: your Imicus", out)
        self.assertIn("FIT 1 x Expanded Cargohold I", out)

    def test_flex_gear_listed(self):
        from eve_profit import haul
        from eve_profit.db import connect
        from eve_profit.config import Profile
        con = connect(":memory:")
        con.execute("INSERT INTO types(type_id,name,volume,capacity) VALUES(2,'Civilian Miner',5,0)")
        con.execute("INSERT INTO inventory VALUES(2,7,1)")

        class G:
            def id_of(self, n):
                return 7
        out = "\n".join(haul.ship_lines(con, G(), Profile(ship_name="Imicus", cargo_m3=400.0, current_system="Rotonos"), {"other_m3": 1.0}))
        self.assertIn("KEEP FLEXIBLE: 1 x Civilian Miner", out)


class HopOnlyTests(unittest.TestCase):
    def test_only_the_hop_is_left(self):
        from eve_profit.haul import hop_only
        t = ("STEP: FLY to Tiberis - jump 1 of 18, hauling your stock to Jita\n"
             "           2 x Entropic Rose    1,152,550 there vs          0 here\n"
             "   1 trip(s), about 16 min, +1,503,032 ISK more\n"
             "   DO ONLY THIS: fly to Tiberis and stop there. Then run  python -m eve_profit next  (it plans again from there: 18 jumps left to Jita, no planned trip back).\n"
             "   AT Jita after selling: next best\n")
        o = hop_only(t)
        self.assertNotIn("Jita", o)
        self.assertIn("STEP: FLY to Tiberis", o)
        self.assertIn("2 x Entropic Rose", o)
        self.assertNotIn("there vs", o)


class DestinationTests(unittest.TestCase):
    def test_destination_of_a_fly_step(self):
        from eve_profit.autopilot import destination_of
        self.assertEqual(destination_of("STEP: FLY to Tiberis\n   DO ONLY THIS: x"), "Tiberis")
        self.assertEqual(destination_of(">> STEP: FLY to Tiberis - jump 1 of 18, hauling your stock to Jita"), "Tiberis")
        self.assertIsNone(destination_of("STEP: SELL Scordite"))


class AgentsNearTests(unittest.TestCase):
    def test_distance_is_recomputed_from_here(self):
        from eve_profit.haul import agents_near

        class R:
            def __init__(self, j):
                self.jumps = j

        class G:
            ids = {"Tiberis": 1, "Rotonos": 2, "Axiosere": 3}

            def id_of(self, n):
                return self.ids[n]

            def route(self, a, b, mx, yellow):
                return R(1 if {a, b} == {1, 2} else 2)

        class P:
            avoid_yellow = True
        out = agents_near(G(), P(), "Tiberis")
        self.assertTrue(any(l.startswith("1 jump away in Rotonos") for l in out))
        self.assertTrue(any("Axiosere" in l and "2 jumps away" in l for l in out))


class HopOnlyChainTests(unittest.TestCase):
    def test_chain_item_line_loses_price_and_destination(self):
        from eve_profit.haul import hop_only
        o = hop_only("STEP: FLY to Fortitude\n           2 x Entropic Rose Metallic - Limited ~  1,152,550 at Jita\n")
        self.assertNotIn("Jita", o)
        self.assertIn("2 x Entropic Rose Metallic - Limited", o)


class HopOnlyElsewhereTests(unittest.TestCase):
    def test_trades_at_other_systems_are_not_in_this_step(self):
        from eve_profit.haul import hop_only
        t = ("STEP: FLY to Fortitude\n   DO ONLY THIS: fly to Fortitude and stop there.\n"
             "   ON THE WAY (optional; confirm each buy with `check` first):\n"
             "      buy 2 x Ferros at Kemerk (-1,378,000), sell at Jita (+2,590,000) = +1,212,000 ISK\n"
             "   ALSO ON THE ROUTE:\n      need anyway: 3 x Miner I is ~12,000 each at Manifest on the route (here 25,000): buy there\n")
        o = hop_only(t, "Tiberis")
        self.assertNotIn("Kemerk", o)
        self.assertNotIn("Manifest", o)
        self.assertNotIn("ALSO ON THE ROUTE", o)
        o2 = hop_only(t, "Kemerk")
        self.assertIn("Kemerk", o2)


class ThreadsTests(unittest.TestCase):
    def test_best_per_thread(self):
        from eve_profit.nextstep import _threads
        t = _threads([(5e6, "haul stock to Jita", "x", ""), (1e6, "best trade A", "x", ""), (2e6, "AIR daily goals", "x", ""), (float("inf"), "update the model from the game", "x", "")])
        self.assertEqual(t["ISK: trading and hauling"][0], 5e6)
        self.assertIn("AIR career and agent missions", t)
        self.assertIn("teaching the model", t)


class StationLookupTests(unittest.TestCase):
    def test_station_name_from_table_and_id_kept_for_destination(self):
        from eve_profit import tradestep
        from eve_profit.db import connect
        con = connect(":memory:")
        con.execute("INSERT INTO stations(station_id,system_id,name) VALUES(60000001,5,'Manifest V - AIR Laboratories Trade Center')")
        con.execute("INSERT INTO orders VALUES(1,7291,60000001,5,10000001,0,55000.0,3,1,'',1)")

        class G:
            name = {5: "Manifest"}
        self.assertEqual(tradestep._station(con, 7291, 5, 0, G()), (60000001, "Manifest V - AIR Laboratories Trade Center"))
        tradestep.STATION["STEP: BUY at X"] = 42
        self.assertEqual(tradestep.station_of(">> STEP: BUY at X\n more"), 42)


class ExperimentWhereTests(unittest.TestCase):
    def test_place_bound_test_only_when_there(self):
        from eve_profit import catalog
        from eve_profit.db import connect
        con = connect(":memory:")
        acts = [a for a in catalog.status(con, 1e9) if a["id"] == "courier"]
        self.assertEqual(acts[0].get("where"), "Agrallarier")
        elsewhere = catalog.pick_experiment(con, 1e9, 1000.0, 99, 0, {"courier"}, here="Manifest")[0]
        self.assertTrue(elsewhere is None or elsewhere["id"] != "courier")


class SocialGoalTests(unittest.TestCase):
    def test_one_goal_at_a_time_and_done_marks_it(self):
        from eve_profit import social
        from eve_profit.db import connect
        con = connect(":memory:")
        rate, text = social.candidate(con, 245000.0)
        self.assertIn("Send a Message in Chat", text)
        self.assertGreater(rate, 1e6)
        social.mark_shown(con, text)
        self.assertIn("marked done", social.done(con))
        _, text2 = social.candidate(con, 245000.0)
        self.assertIn("Add a new Contact", text2)


class WantedScreensTests(unittest.TestCase):
    def test_wanted_screens_one_at_a_time(self):
        from eve_profit import screens
        from eve_profit.db import connect
        con = connect(":memory:")
        rate, text = screens.wanted_candidate(con)
        self.assertIn("STEP: SHOW ME A SCREEN", text)
        self.assertIn("python -m eve_profit done", text)
        screens.wanted_mark_shown(con, text)
        self.assertIn("Thank you", screens.wanted_done(con))
        _, text2 = screens.wanted_candidate(con)
        self.assertNotEqual(text, text2)


class DoneOrderTests(unittest.TestCase):
    def test_done_marks_shown_social_goal_before_advancing_screens(self):
        from eve_profit import social
        from eve_profit.dailygoals import chain_done
        from eve_profit.db import connect
        con = connect(":memory:")
        _, text = social.candidate(con, 245000.0)
        social.mark_shown(con, text)
        self.assertIn("marked done", chain_done(con))
        self.assertIn("Add a new Contact", social.candidate(con, 1.0)[1])
        self.assertIn("marked done", social.mark_goal_done(con, "mail"))


class FreelanceMiningTests(unittest.TestCase):
    def test_bonus_only_when_accepted(self):
        from eve_profit.mining import freelance_bonus
        from eve_profit.db import connect
        from eve_profit.mining import accept_job
        con = connect(":memory:")
        self.assertEqual(freelance_bonus("Veldspar", con), (0.0, 0))     # not accepted yet
        accept_job("Veldspar", con)
        self.assertEqual(freelance_bonus("Veldspar", con), (5.0, 1000000))
        self.assertEqual(freelance_bonus("Scordite", con), (0.0, 0))


class MiningChainTests(unittest.TestCase):
    def test_accept_steps_come_first(self):
        from eve_profit.db import connect
        from eve_profit.miningchain import is_mining_step, prestep
        con = connect(":memory:")
        self.assertTrue(is_mining_step("STEP: TEST Freelance belt mining (Venture) (x)"))
        t = prestep(con, None, None, "STEP: TEST Freelance belt mining (Venture) (x)\n  how")
        self.assertIn("STEP: ACCEPT FREELANCE JOB 1 of 3", t)
        self.assertEqual(prestep(con, None, None, "STEP: SELL NOW"), "STEP: SELL NOW")


class AdaptiveScreensTests(unittest.TestCase):
    def test_interval_adapts(self):
        from eve_profit import screens
        from eve_profit.db import connect
        con = connect(":memory:")
        def ask():
            left = [i for i in screens.wanted_unseen(con) if i["id"] == "freelance_list"]
            self.assertTrue(left)
            screens.wanted_mark_shown(con, "STEP: SHOW ME A SCREEN - x\n   DO ONLY THIS: open  " + left[0]["where"])
        ask()
        self.assertIn("12 h", screens.wanted_done(con))                  # first time: base interval
        self.assertFalse([i for i in screens.wanted_unseen(con) if i["id"] == "freelance_list"])   # not due right away
        con.execute("UPDATE meta SET value=replace(value, '\"ts\"', '\"ts\"') WHERE key='wanted_state'")
        import json, time
        st = json.loads(con.execute("SELECT value FROM meta WHERE key='wanted_state'").fetchone()[0])
        st["freelance_list"]["ts"] = time.time() - 13 * 3600
        con.execute("INSERT OR REPLACE INTO meta VALUES('wanted_state',?)", (json.dumps(st),))
        ask()
        self.assertIn("6 h", screens.wanted_done(con, True))             # it changed: twice as often, floor 6 h


class DynamicDetailScreensTests(unittest.TestCase):
    def test_unverified_job_asks_for_its_detail_page(self):
        from eve_profit import screens
        ids = [i["id"] for i in screens._dynamic()]
        self.assertIn("jobdetail_plagioclase", ids)


class ListingsTests(unittest.TestCase):
    def test_new_and_gone(self):
        from eve_profit import listings
        from eve_profit.db import connect
        con = connect(":memory:")
        listings.ensure(con)
        a = {"key": "a|mine", "title": "A"}
        b = {"key": "b|mine", "title": "B"}
        listings.apply(con, {"list": "freelance", "ts": "t1", "complete": True, "items": [a, b]})
        self.assertFalse(listings.is_gone(con, "freelance", "b|mine"))
        s = listings.apply(con, {"list": "freelance", "ts": "t2", "complete": True, "items": [a]})
        self.assertIn("1 gone", s)
        self.assertTrue(listings.is_gone(con, "freelance", "b|mine"))
        listings.apply(con, {"list": "freelance", "ts": "t3", "complete": False, "items": []})     # partial: nothing newly gone
        self.assertFalse(listings.is_gone(con, "freelance", "a|mine"))


class ListingOriginTests(unittest.TestCase):
    def test_moved_list_is_not_marked_gone(self):
        from eve_profit import listings
        from eve_profit.db import connect
        con = connect(":memory:")
        listings.ensure(con)
        a, b = {"key": "a|mine", "title": "A"}, {"key": "b|mine", "title": "B"}
        listings.apply(con, {"list": "freelance", "ts": "t1", "complete": True, "origin": "Manifest", "items": [a, b]})
        listings.apply(con, {"list": "freelance", "ts": "t2", "complete": True, "origin": "Rotonos", "items": [a]})
        self.assertFalse(listings.is_gone(con, "freelance", "b|mine"))     # b is just out of range from the new place
        listings.apply(con, {"list": "freelance", "ts": "t3", "complete": True, "origin": "Rotonos", "items": [a]})
        self.assertTrue(listings.is_gone(con, "freelance", "b|mine"))      # same place twice: now it really is gone


class MarkSeenTests(unittest.TestCase):
    def test_mark_seen_by_part_of_id(self):
        from eve_profit import screens
        from eve_profit.db import connect
        con = connect(":memory:")
        self.assertIn("Thank you", screens.mark_seen(con, "anymining"))
        self.assertNotIn("freelance_detail_anymining", [i["id"] for i in screens.wanted_unseen(con)])


class GrabIntervalTests(unittest.TestCase):
    def test_interval_follows_change_rate(self):
        from eve_profit.grabs import next_interval
        self.assertEqual(next_interval(1.0, 0.5, 0.25, 24), 0.5)       # a lot changed: pull twice as often
        self.assertEqual(next_interval(1.0, 0.0, 0.25, 24), 1.5)       # nothing changed: pull less often
        self.assertEqual(next_interval(0.25, 0.9, 0.25, 24), 0.25)     # never faster than the floor
        self.assertEqual(next_interval(20.0, 0.0, 0.25, 24), 24)       # nor slower than the ceiling


class FreelanceParseTests(unittest.TestCase):
    def test_per_unit_and_mining_jobs(self):
        import json
        from eve_profit import freelance
        from eve_profit.db import connect
        con = connect(":memory:")
        con.execute("CREATE TABLE IF NOT EXISTS freelance_raw(job_id TEXT PRIMARY KEY, fetched REAL, listing TEXT, detail TEXT)")
        j = {"id": "x", "name": "Get started mining Veldspar (Read Description)", "state": "Active", "progress": {"current": 1, "desired": 250000000}, "reward": {"initial": 1250000000, "remaining": 1}}
        con.execute("INSERT INTO freelance_raw VALUES('x',0,?,NULL)", (json.dumps(j),))
        self.assertAlmostEqual(freelance.per_unit(j), 5.0)
        m = freelance.mining_jobs(con)
        self.assertEqual(m[0]["ore"], "Veldspar")
        self.assertAlmostEqual(m[0]["isk_per_unit"], 5.0)


class FreelanceParseDetailTests(unittest.TestCase):
    def test_parse_mine_and_deliver(self):
        from eve_profit.freelance import alive, parse
        lst = {"id": "a", "name": "Get started mining Veldspar", "state": "Active", "progress": {"current": 1, "desired": 10}, "reward": {"initial": 50, "remaining": 40}}
        det = {"details": {"expires": "2099-01-01T00:00:00Z", "creator": {"corporation": {"name": "Corp Borp"}}},
               "configuration": {"method": "MineOre", "parameters": {"ore": {"matcher": {"values": [{"value_type": "ore_group", "values": ["462"]}]}}}},
               "contribution": {"reward_per_contribution": 5, "contribution_per_participant_limit": 1000000},
               "access_and_visibility": {"broadcast_locations": [{"id": 30100032, "name": "Manifest"}], "restrictions": {"maximum_age": 14}}}
        j = parse(lst, det)
        self.assertEqual((j["method"], j["per_unit"], j["cap_pp"], j["max_age_days"]), ("MineOre", 5, 1000000, 14))
        self.assertEqual(j["items"], [("ore_group", 462)])
        self.assertTrue(alive(lst))
        self.assertFalse(alive({**lst, "reward": {"initial": 50, "remaining": 0}}))


class JobPlanTests(unittest.TestCase):
    def test_deliver_job_beats_buying_cost(self):
        import json
        from eve_profit import jobplan
        from eve_profit.config import Profile
        from eve_profit.db import connect
        con = connect(":memory:")
        con.execute("CREATE TABLE IF NOT EXISTS freelance_raw(job_id TEXT PRIMARY KEY, fetched REAL, listing TEXT, detail TEXT)")
        con.execute("INSERT INTO types(type_id,name,volume,group_id,capacity) VALUES(1230,'Scordite',0.15,460,0)")
        con.execute("INSERT INTO orders VALUES(1,1230,60000001,1,10000001,0,5.0,100000,1,'',1)")
        lst = {"id": "j", "name": "any scordite", "state": "Active", "progress": {"current": 0, "desired": 1000000}, "reward": {"initial": 9000000, "remaining": 9000000}}
        det = {"details": {"expires": "2099-01-01T00:00", "creator": {"corporation": {"name": "C"}}}, "configuration": {"method": "DeliverItem", "parameters": {"corporation_item_delivery": {"corporation_item_delivery": {"item_type": {"values": [{"value_type": "item_type", "values": ["1230"]}]}}}}},
               "contribution": {"reward_per_contribution": 9}, "access_and_visibility": {"broadcast_locations": [{"id": 1, "name": "A"}]}}
        con.execute("INSERT INTO freelance_raw VALUES('j',0,?,?)", (json.dumps(lst), json.dumps(det)))

        class R:
            def __init__(self, j):
                self.jumps = j

        class G:
            name = {1: "A"}

            def id_of(self, n):
                return 1

            def reach(self, a, j, y):
                return {1: R(0)}
        p = Profile(cargo_m3=15.0, wallet_isk=1e6, current_system="A")
        rows = jobplan.options(con, G(), p)
        self.assertEqual(rows[0]["kind"], "deliver")
        self.assertEqual(rows[0]["units"], 100)
        self.assertAlmostEqual(rows[0]["net"], 100 * (9 - 5))


class JobChainTests(unittest.TestCase):
    def test_accept_then_fly_then_deliver_state(self):
        from eve_profit import jobchain
        from eve_profit.db import connect
        con = connect(":memory:")
        jobchain._save(con, {"id": "j", "name": "any scordite", "item": "Scordite", "units": 10, "stage": "accept"})
        jobchain.mark_shown(con, "STEP: ACCEPT FREELANCE JOB - any scordite (about 1 minute)\n x")
        self.assertIn("accepted", jobchain.done(con))
        self.assertEqual(jobchain._load(con)["stage"], "fly")
        jobchain.mark_shown(con, "STEP: DELIVER 10 x Scordite for the freelance job (about 3 minutes)")
        self.assertIn("delivered", jobchain.done(con))
        self.assertIsNone(jobchain._load(con))


class AgentChainTests(unittest.TestCase):
    def test_accept_first_then_done_advances(self):
        from eve_profit import agentchain
        from eve_profit.db import connect
        con = connect(":memory:")

        class P:
            current_system = "Manifest"
            avoid_yellow = True
        o = {"agent": "Cassandra Ahfrim (Security)", "mission": "chapter 1: report to Holorelay: Heika Torigo at Kita-Aino V", "isk": 42000, "bonus": 54000, "to_system": "Kita-Aino", "where": "Kita-Aino V"}
        t = agentchain.stage_text(con, None, P(), o)
        self.assertIn("STEP: ACCEPT Cassandra Ahfrim's MISSION", t)
        agentchain.mark_shown(con, t)
        self.assertIn("accepted", agentchain.done(con))
        self.assertEqual(agentchain._load(con)["stage"], "go")


class HopOnlyAgentLineTests(unittest.TestCase):
    def test_agent_lines_for_other_systems_are_dropped_from_the_one_step(self):
        from eve_profit.haul import hop_only
        txt = ("STEP: FLY to Meves - jump 1 of 2, hauling your stock to Lirsautton\n   6 x Thing\n"
               "      AGENT at Lirsautton: Wemire (rd, level 1): look at the offer when you stop there\n"
               "      AGENTS at Lirsautton: 4 level-1 - open their windows\n"
               "      AGENT at Dodixie: Someone (security, level 1): look at the offer\n")
        out = hop_only(txt, "Dodixie")
        self.assertNotIn("Lirsautton", out.split("\n", 1)[1])
        self.assertIn("AGENT at Dodixie", out)
