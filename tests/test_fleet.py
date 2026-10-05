import os, tempfile, unittest
from eve_profit import db
from eve_profit.combat import seed_defaults
from eve_profit.config import Profile
from eve_profit.fleet import describe_fleet, parked_ships, swap_opportunities, variant_profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock
from eve_profit.planner import FINDERS, plan


def setup():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    load_mock(con)
    seed_defaults(con)
    con.execute("UPDATE types SET capacity=50000 WHERE type_id=90001")       # pretend Mock Widget is a big hauler hull
    g = Graph(con)
    far = [s for s, r in g.reach(1, 2).items() if r.jumps == 2][0]
    con.execute("INSERT INTO my_ships VALUES(1001,90001,?,60000000)", (far,))
    return con, g, far


class T(unittest.TestCase):
    def test_parked_and_variant(self):
        con, g, far = setup()
        s = parked_ships(con)
        self.assertEqual((s[0]["name"], s[0]["capacity"]), ("Mock Widget", 50000))
        p2 = variant_profile(Profile(combat_dps=999, cargo_m3=100), s[0], g.name[far])
        self.assertEqual((p2.cargo_m3, p2.combat_dps, p2.current_system), (50000, 0.0, g.name[far]))   # no stats -> no combat

    def test_swap_charges_trip_and_prefixes(self):
        con, g, far = setup()
        p = Profile(max_jumps=2, cargo_m3=500, wallet_isk=1e9, min_profit_isk=1)
        r = swap_opportunities(con, g, p, FINDERS)
        self.assertTrue(r)
        o = r[0]
        self.assertIn("[swap to Mock Widget", o.description)
        self.assertGreaterEqual(o.jumps, 2)
        self.assertEqual(o.waypoints[:2], g.route(1, far).path[1:])
        self.assertFalse([w for w in o.waypoints if g.is_red(w)])

    def test_swap_combat_needs_stats(self):
        con, g, far = setup()
        p = Profile(max_jumps=3, cargo_m3=500, wallet_isk=1e9, min_profit_isk=1)
        every = dict(per_variant=10000)                      # don't let trades crowd combat out of the top 5
        self.assertFalse([o for o in swap_opportunities(con, g, p, FINDERS, **every) if o.kind.startswith("combat")])
        p.ships = {"Mock Widget": {"combat_dps": 700, "ship_ehp": 200000, "ship_tank_dps": 400}}
        self.assertTrue([o for o in swap_opportunities(con, g, p, FINDERS, **every) if o.kind.startswith("combat")])

    def test_planner_includes_swaps_and_can_disable(self):
        con, g, far = setup()
        p = Profile(max_jumps=2, cargo_m3=500, wallet_isk=1e9, min_profit_isk=1)
        self.assertTrue([o for o in plan(con, p, 100000, False) if "[swap to" in o.description])
        p.consider_ship_swaps = False
        self.assertFalse([o for o in plan(con, p, 100000, False) if "[swap to" in o.description])

    def test_describe_fleet(self):
        con, g, far = setup()
        txt = describe_fleet(con, g, Profile())
        self.assertIn("Mock Widget", txt)
        self.assertIn("2 jumps", txt)


if __name__ == "__main__":
    unittest.main()


class StockTests(unittest.TestCase):
    def test_stock_report_values_and_flags_unpriced(self):
        from eve_profit.stock import stock_report
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")           # Tritanium: has buyers nearby
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(77777,'Odd Skin',0.1)")
        con.execute("INSERT INTO inventory VALUES(77777,1,5)")           # no orders anywhere
        txt = stock_report(con, g, Profile(max_jumps=2))
        self.assertIn("Tritanium", txt)
        self.assertIn("Odd Skin x5", txt)
        self.assertIn("2 stacks", txt)
        self.assertIn("inside your ship's cargo", txt)


class LoadTests(unittest.TestCase):
    def test_load_prefers_dense_value_and_respects_cargo(self):
        from eve_profit.stock import best_loads, format_loads
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        # Tritanium 0.01 m3 (cheap per m3) vs a 5 m3 item with a much better price per m3 is the Widget (16000/5)
        con.execute("INSERT INTO inventory VALUES(34,1,2000000)")        # 20,000 m3 of Tritanium
        con.execute("INSERT INTO inventory VALUES(36,1,100000)")         # Mexallon 1,000 m3, pricier per m3
        p = Profile(max_jumps=2, cargo_m3=5000, wallet_isk=1e9)
        loads = best_loads(con, g, p)
        self.assertTrue(loads)
        d = loads[0]
        self.assertLessEqual(d["used"], 5000 + 1e-6)
        dens = [v / u for _, u, v in d["items"]]                          # both items are 0.01 m3, so ISK/unit = ISK/m3 order
        self.assertEqual(dens, sorted(dens, reverse=True))                # densest value is loaded first
        self.assertIn("Best hold-loads", format_loads(loads))
        self.assertFalse([w for w in d["waypoints"] if g.is_red(w)])


class AlongTests(unittest.TestCase):
    def test_sells_where_best_along_route_and_travels_light(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        con.execute("DELETE FROM orders WHERE type_id IN (34,36)")
        path = g.route(1, far).path
        mid = path[1]
        now = 1.0
        # Tritanium: better price at the destination; Mexallon: best right here at the start
        con.execute("INSERT INTO orders VALUES(8001,34,60000099,?,10000001,1,9.0,10000000,1,'',?)", (far, now))
        con.execute("INSERT INTO orders VALUES(8002,34,60000098,1,10000001,1,5.0,10000000,1,'',?)", (now,))
        con.execute("INSERT INTO orders VALUES(8003,36,60000097,1,10000001,1,100.0,10000000,1,'',?)", (now,))
        con.execute("INSERT INTO orders VALUES(8004,36,60000096,?,10000001,1,60.0,10000000,1,'',?)", (far, now))
        con.execute("INSERT INTO inventory VALUES(34,1,100000)")
        con.execute("INSERT INTO inventory VALUES(36,1,5000)")
        res = plan_along(con, g, Profile(cargo_m3=5000), g.name[far])
        self.assertEqual([d["name"] for d in res["sell_here"]], ["Mexallon"])           # best at the start: sold there
        self.assertEqual([d["name"] for d in res["carry"]], ["Tritanium"])              # better at the destination: carried
        self.assertEqual(res["carry"][0]["at"], len(path) - 1)
        txt = format_along(res)
        self.assertIn("IN Home, buy orders", txt)
        self.assertIn("CARRY", txt)

    def test_carry_respects_hold(self):
        from eve_profit.along import plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        con.execute("DELETE FROM orders WHERE type_id=34")
        con.execute("INSERT INTO orders VALUES(8101,34,60000099,?,10000001,1,9.0,10000000,1,'',1)", (far,))
        con.execute("INSERT INTO inventory VALUES(34,1,1000000)")                        # 10,000 m3 of Tritanium
        res = plan_along(con, g, Profile(cargo_m3=2000), g.name[far])
        self.assertLessEqual(res["used_m3"], 2000 + 1e-6)
        self.assertEqual(res["carry"][0]["sold"], 200000)

    def test_empty_hangar_gives_instructions(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        txt = format_along(plan_along(con, g, Profile(cargo_m3=5000), g.name[far]))
        self.assertIn("No items found in your Home hangar", txt)
        self.assertIn("sync", txt)


class AlongDockTests(unittest.TestCase):
    def test_sell_here_uses_only_the_docked_station_and_shows_listing_value(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id=34")
        # two Home stations: the one you dock at pays 5, the other pays 50 (you cannot sell there from your dock)
        con.execute("INSERT INTO orders VALUES(9001,34,60000001,1,10000001,1,5.0,10000000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(9002,34,60000555,1,10000001,1,50.0,10000000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(9003,34,60000001,1,10000001,0,8.0,10000000,1,'',1)")
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")
        p = Profile(cargo_m3=5000, current_location_id=60000001)
        res = plan_along(con, g, p, g.name[far])
        d = res["sell_here"][0]
        self.assertAlmostEqual(d["net"], 1000 * 5.0 * (1 - p.sales_tax), places=4)        # not the 50 ISK order
        self.assertEqual(d["listing"], 8000.0)
        self.assertEqual(d["advice"], "LIST")                                             # 8,000 listed beats 4,900 instant by >15%
        txt = format_along(res)
        self.assertIn("listed, after fees", txt)
        self.assertIn("the station you are docked at", txt)
        p.current_location_id = 0
        self.assertIn("dock unknown", format_along(plan_along(con, g, p, g.name[far])))


class BasisTests(unittest.TestCase):
    def _world(self):
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,36)")
        return con, g, far

    def test_cost_basis_averages_buys_and_subtracts_sales(self):
        from eve_profit.basis import cost_basis, stack_basis
        con, g, far = self._world()
        con.executemany("INSERT INTO transactions VALUES(?,?,?,?,?,?,?)", [
            (1, "d", 34, 1, 10.0, 100, 1), (2, "d", 34, 1, 20.0, 100, 1), (3, "d", 34, 1, 50.0, 50, 0)])
        b = cost_basis(con)
        self.assertEqual(b[34], (15.0, 150))                                    # avg of buys; 50 already sold
        self.assertEqual(stack_basis(b, 34, 120), (1800.0, 120))
        self.assertEqual(stack_basis(b, 34, 200), (2250.0, 150))                # only 150 units have a known price
        self.assertEqual(stack_basis(b, 99, 5), (0.0, 0))                       # never bought: no basis

    def test_loss_everywhere_on_route_is_held_with_better_buyer_hint(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = self._world()
        con.execute("INSERT INTO transactions VALUES(1,'d',34,1,100.0,1000,1)")  # paid 100 each
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")
        con.execute("INSERT INTO orders VALUES(9301,34,60000001,1,10000001,1,60.0,10000000,1,'',1)")   # here: 60 (loss)
        # a far buyer (not on the route) pays 150
        route = set(g.route(1, far).path)
        off = next(s for s in g.reach(1, 8) if s not in route and not g.is_red(s) and g.reach(1, 8)[s].jumps >= 1)
        con.execute("INSERT INTO orders VALUES(9302,34,60000002,?,10000001,1,150.0,10000000,1,'',1)", (off,))
        res = plan_along(con, g, Profile(cargo_m3=5000, current_location_id=60000001), g.name[far])
        self.assertFalse(res["sell_here"])
        self.assertEqual(len(res["losses"]), 1)
        self.assertEqual(res["losses"][0]["alt_name"], g.name[off])
        txt = format_along(res)
        self.assertIn("DO NOT SELL AT A LOSS", txt)
        self.assertIn("better buyer", txt)

    def test_profit_column_and_no_record_items(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = self._world()
        con.execute("INSERT INTO transactions VALUES(1,'d',34,1,2.0,1000,1)")    # paid 2 each; sells at 5 -> profit
        con.execute("INSERT INTO inventory VALUES(34,1,1000)")
        con.execute("INSERT INTO inventory VALUES(36,1,500)")                    # no record: mined/looted
        con.execute("INSERT INTO orders VALUES(9401,34,60000001,1,10000001,1,5.0,10000000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(9402,36,60000001,1,10000001,1,3.0,10000000,1,'',1)")
        p = Profile(cargo_m3=5000, current_location_id=60000001)
        res = plan_along(con, g, p, g.name[far])
        by = {d["name"]: d for d in res["sell_here"]}
        self.assertGreater(by["Tritanium"]["net"], by["Tritanium"]["cost"])
        self.assertEqual(by["Mexallon"]["covered"], 0)
        txt = format_along(res)
        self.assertIn("(no record)", txt)
        self.assertIn("you paid", txt)


class AdviceTests(unittest.TestCase):
    def test_list_vs_sell_now_and_history(self):
        from eve_profit.along import attach_history, format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,36)")
        # Tritanium: bid 5 vs ask 5.2 -> sell now.  Mexallon: bid 10 vs ask 100 -> list.
        for oid, tid, buy, price in [(9501, 34, 1, 5.0), (9502, 34, 0, 5.2), (9503, 36, 1, 10.0), (9504, 36, 0, 100.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,?,?,10000000,1,'',1)", (oid, tid, buy, price))
        con.execute("INSERT INTO inventory VALUES(34,1,1000)"); con.execute("INSERT INTO inventory VALUES(36,1,100)")
        p = Profile(cargo_m3=5000, current_location_id=60000001, broker_fee=0.03)
        res = plan_along(con, g, p, g.name[far])
        adv = {d["name"]: d["advice"] for d in res["sell_here"]}
        self.assertEqual(adv, {"Tritanium": "SELL NOW", "Mexallon": "LIST"})

        class E:
            def get(self, path, **kw):
                assert path == "/markets/10000001/history/" and kw == {"type_id": 36}
                return [{"volume": 10}] * 40, 1
        attach_history(E(), res, 10000001)
        mx = next(d for d in res["sell_here"] if d["name"] == "Mexallon")
        self.assertEqual(mx["vol_day"], 10)
        self.assertEqual(mx["days_to_sell"], 10)
        txt = format_along(res)
        self.assertIn("PLAN: sell 1 stacks now", txt)
        self.assertIn("~10/day on the market", txt)


class SlotTests(unittest.TestCase):
    def test_order_slots_formula_and_unknown(self):
        from eve_profit.skills import order_slots
        con, g, far = setup()
        self.assertIsNone(order_slots(con))                                   # skills not synced
        con.executemany("INSERT INTO character_skills(skill_id,level) VALUES(?,?)",
                        [(3443, 5), (3444, 2), (16596, 1)])
        self.assertEqual(order_slots(con), 5 + 4 * 5 + 8 * 2 + 16 * 1)

    def test_only_best_gain_per_slot_are_listed(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,35,36)")
        con.execute("INSERT INTO character_skills(skill_id,level) VALUES(3443,0)")      # => 5 slots
        for k, tid in enumerate((34, 35, 36)):
            pass
        # three items, all worth listing; give them very different gains, with only 1 slot forced via monkeypatch
        for oid, tid, buy, price in [(9601, 34, 1, 1.0), (9602, 34, 0, 10.0), (9603, 35, 1, 1.0), (9604, 35, 0, 100.0),
                                     (9605, 36, 1, 1.0), (9606, 36, 0, 1000.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,?,?,10000000,1,'',1)", (oid, tid, buy, price))
        for tid in (34, 35, 36):
            con.execute("INSERT INTO inventory VALUES(?,1,100)", (tid,))
        from unittest import mock
        with mock.patch("eve_profit.along.order_slots", return_value=2):
            res = plan_along(con, g, Profile(cargo_m3=5000, current_location_id=60000001), g.name[far])
        adv = {d["name"]: d["advice"] for d in res["sell_here"]}
        self.assertEqual(adv["Mexallon"], "LIST")                              # biggest gain
        self.assertEqual(adv["Pyerite"], "LIST")
        self.assertEqual(adv["Tritanium"], "SELL NOW")                         # smallest gain lost the last slot
        txt = format_along(res)
        self.assertIn("Market order slots from your skills: 2", txt)
        self.assertIn("(no free slot)", txt)


class WatchTests(unittest.TestCase):
    def test_route_watch_flags_kills_and_gank_systems(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("INSERT INTO inventory VALUES(34,1,10)")
        path = g.route(1, far).path
        mid = path[1]
        con.execute("DELETE FROM system_kills")
        con.execute("INSERT INTO system_kills VALUES(?,7,1,0)", (mid,))                    # 7 ships killed last hour
        con.execute("INSERT INTO gank_events VALUES(1,?,652,1e7,'t',10000001)", (mid,))
        con.execute("INSERT INTO gank_events VALUES(2,?,652,1e7,'t',10000001)", (mid,))
        res = plan_along(con, Graph(con), Profile(cargo_m3=5000), Graph(con).name[far])
        w = {x["name"]: x for x in res["watch"]}
        self.assertEqual(w[Graph(con).name[mid]]["level"], "DANGER")
        txt = format_along(res)
        self.assertIn("ROUTE WATCH", txt)
        self.assertIn("DANGER", txt)
        self.assertIn("ships killed last hour: 7", txt)
        self.assertIn("hauler losses 7d: 2", txt)

    def test_clean_route_says_so(self):
        from eve_profit.along import format_along, plan_along
        con, g, far = setup()
        con.execute("DELETE FROM system_kills"); con.execute("DELETE FROM inventory")
        con.execute("INSERT INTO inventory VALUES(34,1,10)")
        for s in list(g.reach(1, 3)):
            if g.is_yellow(s):
                con.execute("UPDATE systems SET security=0.9 WHERE system_id=?", (s,))
        g2 = Graph(con)
        far2 = [s for s, r in g2.reach(1, 2).items() if r.jumps == 2][0]
        txt = format_along(plan_along(con, g2, Profile(cargo_m3=5000), g2.name[far2]))
        self.assertIn("no recent kills or hauler losses", txt)


class NextStepTests(unittest.TestCase):
    def _world(self):
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,35,36)")
        return con, g

    def test_sell_now_comes_first_and_is_short(self):
        from eve_profit.nextstep import next_action
        con, g = self._world()
        for oid, tid, buy, price in [(9701, 34, 1, 5000.0), (9702, 34, 0, 5100.0),            # liquid: sell now
                                     (9703, 36, 1, 100.0), (9704, 36, 0, 100000.0)]:        # huge gap: list
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,?,?,10000000,1,'',1)", (oid, tid, buy, price))
        con.execute("INSERT INTO inventory VALUES(34,1,100)"); con.execute("INSERT INTO inventory VALUES(36,1,50)")
        txt = next_action(con, g, Profile(cargo_m3=5000, current_location_id=60000001))
        self.assertTrue(txt.startswith("STEP: SELL NOW"))
        self.assertIn("Tritanium", txt)
        self.assertNotIn("Mexallon", txt)                                   # one thing at a time
        self.assertLess(len(txt.splitlines()), 14)
        self.assertIn("python -m eve_profit next", txt)

    def test_then_list_one_item_then_trade(self):
        from eve_profit.nextstep import next_action
        con, g = self._world()
        for oid, tid, buy, price in [(9803, 36, 1, 100.0), (9804, 36, 0, 100000.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,?,?,10000000,1,'',1)", (oid, tid, buy, price))
        con.execute("INSERT INTO inventory VALUES(36,1,50)")
        txt = next_action(con, g, Profile(cargo_m3=5000, current_location_id=60000001))
        self.assertTrue(txt.startswith("STEP: LIST 1 item"))
        self.assertIn("100,000.00", txt)
        con.execute("DELETE FROM inventory")
        p = Profile(max_jumps=3, cargo_m3=5000, wallet_isk=1e9, min_profit_isk=1, current_location_id=60000001)
        con.execute("DELETE FROM orders WHERE order_id>=9800")
        txt = next_action(con, g, p)
        self.assertTrue(txt.startswith("STEP: TRADE"))
        self.assertIn("check --pick 1", txt)


class KeepTests(unittest.TestCase):
    def _world(self, widget_bid):
        from eve_profit.keep import keep_vs_sell
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM orders WHERE type_id IN (34,35,36,90001)")
        # materials (blueprint 90002 needs 34x1000, 35x500, 36x50 per run at ME0): bids 1/2/10 ISK here, no asks
        for oid, tid, price in [(9901, 34, 1.0), (9902, 35, 2.0), (9903, 36, 10.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,1,?,100000000,1,'',1)", (oid, tid, price))
        con.execute("INSERT INTO orders VALUES(9904,90001,60000001,1,10000001,1,?,1000,1,'',1)", (widget_bid,))
        for tid, q in ((34, 100000), (35, 50000), (36, 5000)):
            con.execute("INSERT INTO inventory VALUES(?,1,?)", (tid, q))
        con.execute("UPDATE my_blueprints SET me=0,te=0"); con.execute("DELETE FROM skill_reqs")
        con.execute("UPDATE prices SET adjusted_price=0")
        p = Profile(max_jumps=1, cargo_m3=1e6, wallet_isk=1e9, max_runs=10, job_fee_rate=0.0)
        return keep_vs_sell(con, g, p)

    def test_build_wins_when_product_pays_more_than_materials(self):
        from eve_profit.keep import format_keep
        res, slots = self._world(widget_bid=10000.0)       # 10 runs: product 10 x 10,000; materials sell for ~1000+1000+500
        d = res[0]
        self.assertGreater(d["gain"], 0)
        self.assertEqual(d["runs"], 10)
        self.assertIn("BUILD beats selling", format_keep(res, slots))
        self.assertIn("Tritanium", format_keep(res, slots))

    def test_sell_wins_when_product_is_worth_less(self):
        from eve_profit.keep import format_keep
        res, slots = self._world(widget_bid=100.0)         # product 10 x 100 = 1,000 < 25,000 of materials
        self.assertLess(res[0]["gain"], 0)
        self.assertIn("SELL the materials", format_keep(res, slots))

    def test_no_owned_materials_means_nothing_to_compare(self):
        from eve_profit.keep import format_keep, keep_vs_sell
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        res, slots = keep_vs_sell(con, g, Profile(max_jumps=1))
        self.assertEqual(res, [])
        self.assertIn("SELL the materials", format_keep(res, slots))


class BpBuyTests(unittest.TestCase):
    def _world(self, widget_bid, bpo_ask, skills=None):
        from eve_profit.bpbuy import bp_buy_candidates
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM my_blueprints")
        con.execute("DELETE FROM orders WHERE type_id IN (34,35,36,90001,90002)")
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(90002,'Mock Widget Blueprint',0.01)")
        for oid, tid, price in [(9911, 34, 1.0), (9912, 35, 2.0), (9913, 36, 10.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,1,?,100000000,1,'',1)", (oid, tid, price))
        con.execute("INSERT INTO orders VALUES(9914,90001,60000001,1,10000001,1,?,1000,1,'',1)", (widget_bid,))
        if bpo_ask:
            con.execute("INSERT INTO orders VALUES(9915,90002,60000001,1,10000001,0,?,5,1,'',1)", (bpo_ask,))
        for tid, q in ((34, 100000), (35, 50000), (36, 5000)):
            con.execute("INSERT INTO inventory VALUES(?,1,?)", (tid, q))
        con.execute("DELETE FROM skill_reqs"); con.execute("UPDATE prices SET adjusted_price=0")
        if skills:
            con.execute("INSERT INTO skill_reqs VALUES(90002,3380,3)")
            con.execute("INSERT INTO character_skills(skill_id,level) VALUES(3380,1)")
        return bp_buy_candidates(con, g, Profile(max_jumps=1, cargo_m3=1e6, wallet_isk=1e9, max_runs=10, job_fee_rate=0.0)), con

    def test_cheap_blueprint_is_worth_buying(self):
        from eve_profit.bpbuy import format_bpbuy
        (res, scanned), con = self._world(widget_bid=10000.0, bpo_ask=5000.0)
        self.assertEqual(res[0]["blueprint"], "Mock Widget Blueprint")
        self.assertGreater(res[0]["net"], 0)
        self.assertIn("BUY the blueprint and build", format_bpbuy(res, scanned))

    def test_expensive_blueprint_is_not(self):
        from eve_profit.bpbuy import format_bpbuy
        (res, scanned), con = self._world(widget_bid=10000.0, bpo_ask=10_000_000.0)
        self.assertLess(res[0]["net"], 0)
        self.assertIn("NO - not worth buying", format_bpbuy(res, scanned))

    def test_unpriced_blueprint_is_flagged_and_missing_skills_shown(self):
        from eve_profit.bpbuy import format_bpbuy
        (res, scanned), con = self._world(widget_bid=10000.0, bpo_ask=None, skills=True)
        txt = format_bpbuy(res, scanned)
        self.assertIn("CANNOT PRICE", txt)
        (res, scanned), con = self._world(widget_bid=10000.0, bpo_ask=5000.0, skills=True)
        self.assertIn("YOU LACK SKILLS", format_bpbuy(res, scanned))
        self.assertIn("Industry 3 (have 1)", format_bpbuy(res, scanned))

    def test_no_stock_nothing_to_check(self):
        from eve_profit.bpbuy import bp_buy_candidates, format_bpbuy
        con, g, far = setup()
        con.execute("DELETE FROM inventory")
        res, scanned = bp_buy_candidates(con, g, Profile(max_jumps=1))
        self.assertEqual(res, [])
        self.assertIn("none beats simply selling", format_bpbuy(res, scanned))


class BpBuyScaleTests(unittest.TestCase):
    def test_big_stock_makes_a_blueprint_worthwhile_that_one_batch_would_not(self):
        from eve_profit.bpbuy import bp_buy_candidates
        con, g, far = setup()
        con.execute("DELETE FROM inventory"); con.execute("DELETE FROM my_blueprints")
        con.execute("DELETE FROM orders WHERE type_id IN (34,35,36,90001,90002)")
        con.execute("INSERT INTO types(type_id,name,volume) VALUES(90002,'Mock Widget Blueprint',0.01)")
        con.execute("DELETE FROM skill_reqs"); con.execute("UPDATE prices SET adjusted_price=0")
        for oid, tid, price in [(9921, 34, 1.0), (9922, 35, 2.0), (9923, 36, 10.0)]:
            con.execute("INSERT INTO orders VALUES(?,?,60000001,1,10000001,1,?,1000000000,1,'',1)", (oid, tid, price))
        # per run: product bid 3,000 vs materials 1000x1 + 500x2 + 50x10 = 2,500 sell value -> +500 minus 7%... use bid 3,000
        con.execute("INSERT INTO orders VALUES(9924,90001,60000001,1,10000001,1,3000.0,100000,1,'',1)")
        con.execute("INSERT INTO orders VALUES(9925,90002,60000001,1,10000001,0,100000.0,5,1,'',1)")   # blueprint 100,000
        for tid, q in ((34, 10_000_000), (35, 5_000_000), (36, 500_000)):
            con.execute("INSERT INTO inventory VALUES(?,1,?)", (tid, q))
        p = Profile(max_jumps=1, cargo_m3=1e9, wallet_isk=1e12, job_fee_rate=0.0)
        res, scanned = bp_buy_candidates(con, g, p)
        d = res[0]
        self.assertGreaterEqual(d["runs"], 100)                                  # chose a big batch, not 10
        self.assertGreater(d["net"], 0)                                          # pays back the 100,000 blueprint
        # at 10 runs alone it would NOT have paid back the blueprint:
        self.assertLess(10 * 500, 100000)
