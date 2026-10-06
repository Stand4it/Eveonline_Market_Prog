"""Command line: python -m eve_profit <command>"""
import argparse
import os
import sys
import random
import time

from . import db
from .config import Profile, default_db_path
from .planner import format_plan, plan


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_client_id(explicit=""):
    """Priority: --client-id, then client_id.txt, then env EVE_CLIENT_ID. Placeholders/typos are
    rejected: a real CCP client id is 32 hex characters."""
    import re
    cands = [explicit]
    for path in ("client_id.txt", os.path.join(_ROOT, "client_id.txt"), os.path.join(_ROOT, "scripts", "client_id.txt")):
        if os.path.exists(path):
            cands.append(open(path).read().strip())
            break
    cands.append(os.environ.get("EVE_CLIENT_ID", ""))
    for c in cands:
        if c and re.fullmatch(r"[0-9a-fA-F]{32}", c.strip()):
            return c.strip()
    bad = [c for c in cands if c]
    if bad:
        raise SystemExit(f"Client ID '{bad[0]}' is not valid (expected 32 letters/digits). Put the real one in "
                         f"client_id.txt and clear any old setting:  Remove-Item Env:EVE_CLIENT_ID")
    return ""


def regions_near(con, p):
    """Region ids of every system within 2x your jump radius (so cross-border trades are seen)."""
    from .graph import Graph
    g = Graph(con)
    reach = g.reach(g.id_of(p.current_system), p.max_jumps * 2, p.avoid_yellow)
    return sorted({g.region[s] for s in reach})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eve_profit")
    ap.add_argument("cmd", choices=["init", "mock", "sde", "scan", "plan", "watch", "profile", "login", "sync", "log", "go", "universe", "esimap", "fleet", "skills", "diag", "explain", "check", "stock", "along", "fit", "zkill", "next", "keep", "bpbuy", "update", "bestprice", "sellplan", "day", "now", "chars", "combatfit", "journey", "compare", "start", "stop", "trainplan", "activities"])
    ap.add_argument("--db", default=default_db_path())
    ap.add_argument("--profile", default="profile.json")
    ap.add_argument("--live", action="store_true", help="use real ESI market data")
    ap.add_argument("--regions", default="", help="comma list of region ids (default: auto from your system)")
    ap.add_argument("--system", default="", help="profile: set current system name")
    ap.add_argument("--cargo", type=float, default=0, help="profile: set cargo m3")
    ap.add_argument("--depth", type=int, default=0, help="esimap: jumps around your system (default 3x radius)")
    ap.add_argument("--sde-file", default="", help="sde: import this local sqlite/.bz2 instead of downloading")
    ap.add_argument("--sde-url", default="", help="sde: download from this URL")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--interval", type=int, default=300, help="watch seconds (ESI caches 5 min)")
    ap.add_argument("--client-id", default="", help="else env EVE_CLIENT_ID, else client_id.txt")
    ap.add_argument("--pick", type=int, default=1, help="go: which ranked opportunity")
    ap.add_argument("--send", action="store_true", help="go: really set in-game waypoints")
    ap.add_argument("--activity", default="")
    ap.add_argument("--isk", type=float, default=0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--away", action="store_true", help="unattended mode: long safe autopilot hauls only")
    ap.add_argument("--to", default="", help="along: destination system name")
    ap.add_argument("--force", action="store_true", help="universe: reload even if already loaded")
    ap.add_argument("--world", type=int, default=0, help="sellplan: also check the N biggest stacks in every region")
    ap.add_argument("--cash", type=float, default=0, help="day: extra ISK you expect to have (e.g. from selling stock)")
    ap.add_argument("--no-stock", action="store_true", help="day: leave out selling/listing the stock in your hangar")
    ap.add_argument("--item", default="", help="bestprice: item name or type id")
    ap.add_argument("--qty", type=int, default=0, help="bestprice: quantity (default: what you hold here, else 1)")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--ship", default="", help="combatfit: hull name (default: the ship you are in)")
    ap.add_argument("--dps", type=float, default=0, help="combatfit: damage per second from Pyfa")
    ap.add_argument("--ehp", type=float, default=0, help="combatfit: effective HP from Pyfa")
    ap.add_argument("--tank", type=float, default=0, help="combatfit: sustained repair per second from Pyfa")
    ap.add_argument("--value", type=float, default=0, help="combatfit: ship + fit value in ISK (what you lose if it dies)")
    ap.add_argument("--char", default="", help="separate character: own login, profile and database (e.g. --char fresh)")
    ap.add_argument("--detour", type=int, default=2, help="journey: how many jumps off the route to look for goods and buyers")
    ap.add_argument("--max-age", type=int, default=15, help="--live: skip regions downloaded less than this many minutes ago")
    ap.add_argument("--quick", action="store_true", help="journey --live: refresh only the items you own along the route (seconds, not minutes)")
    ap.add_argument("--paused", type=float, default=0, help="stop: minutes you were away from the activity (not counted)")
    ap.add_argument("--fast", action="store_true", help="now: skip the market re-scan (sync + next only)")
    ap.add_argument("--sync", action="store_true", help="refresh your character data (assets, wallet, location) first")
    a = ap.parse_args(argv)
    a.client_id = resolve_client_id(a.client_id)
    if a.char:
        from .active import match
        a.char = match(a.char)
    elif a.cmd not in ("init", "mock", "sde", "universe", "esimap", "login", "chars", "update") and a.client_id:
        from .active import pick
        a.char = pick(a.client_id, os.path.dirname(a.db) or ".")
    if a.char:
        _use_character(a, ap)
        if not os.path.exists(a.profile) and a.cmd not in ("login", "sync", "chars", "init", "profile"):
            print("[first time for this character: syncing it now]")
            a.sync = True

    kind = {"watch": "watch", "login": "login", "sync": "setup", "universe": "setup", "esimap": "setup",
            "sde": "setup", "mock": "setup"}.get(a.cmd)
    if not kind:
        return _run(a)
    from .lock import AlreadyRunning, single_instance
    try:
        with single_instance(f"{a.db}.{kind}.lock", kind):
            return _run(a)
    except AlreadyRunning as e:
        raise SystemExit(str(e))


CHAR_TABLES = ["inventory", "my_blueprints", "character_skills", "skill_queue", "char_attrs", "standings",
               "lp_balance", "transactions", "fitted", "my_ships", "opportunities", "activity_log"]


def _use_character(a, ap):
    """--char NAME: own tokens_NAME.json, profile_NAME.json and eve_profit_NAME.db. The first time, the shared
    game data (map, items, prices) is copied from the main database so no re-download is needed."""
    import re
    import sqlite3
    name = re.sub(r"[^A-Za-z0-9_-]", "", a.char)
    if not name:
        raise SystemExit("--char needs a simple name, e.g. --char fresh")
    os.environ["EVE_PROFIT_TOKENS"] = f"tokens_{name}.json"
    if a.profile == ap.get_default("profile"):
        a.profile = f"profile_{name}.json"
    main_db = a.db
    if a.db == ap.get_default("db"):
        a.db = os.path.join(os.path.dirname(main_db), f"eve_profit_{name}.db")
        if not os.path.exists(a.db) and os.path.exists(main_db):
            os.makedirs(os.path.dirname(a.db) or ".", exist_ok=True)
            src, dst = sqlite3.connect(main_db), sqlite3.connect(a.db)
            src.backup(dst)
            for t in CHAR_TABLES:
                try:
                    dst.execute(f"DELETE FROM {t}")
                except sqlite3.OperationalError:
                    pass
            dst.commit()
            src.close()
            dst.close()
            print(f"[{name}] new character database created from the shared game data: {a.db}")
    if not os.path.exists(a.profile) and os.path.exists(ap.get_default("profile")):
        print(f"[{name}] no {a.profile} yet: run login, then sync (it fills in ship, cargo, wallet, location)")


def _run(a):
    con = db.connect(a.db)
    p = Profile.load(a.profile)
    if a.away:
        p.away_mode = True
    from .combat import seed_defaults
    seed_defaults(con)
    NEEDS_SYSTEM = ("stock", "next", "along", "day", "sellplan", "bestprice", "check", "explain", "keep", "bpbuy", "fleet", "go", "zkill")
    if a.cmd in NEEDS_SYSTEM and not a.sync and con.execute("SELECT COUNT(*) FROM systems WHERE name=? COLLATE NOCASE",
                                                            (p.current_system,)).fetchone()[0] == 0:
        raise SystemExit(f"This character's profile has no known location ('{p.current_system}'). "
                         f"Run:  python -m eve_profit sync   (log in first with:  python -m eve_profit login)")
    if a.sync and a.cmd not in ("login", "sync", "init", "mock", "sde", "universe", "esimap"):
        from . import sso
        from .character import sync_character
        from .esi import ESI
        esi = ESI()
        esi.token, cid = sso.get_token(a.client_id)
        print(sync_character(con, esi, cid, p))
        p.save(a.profile)
    if a.cmd == "init":
        print("DB ready:", a.db)
    elif a.cmd == "profile":
        if a.system:
            p.current_system = a.system
        if a.cargo:
            p.cargo_m3 = a.cargo
        p.save(a.profile)
        print("Wrote", a.profile, "- edit ship/cargo/system, then run scan")
    elif a.cmd in ("login", "sync"):
        from . import sso
        if not a.client_id:
            raise SystemExit("Set EVE_CLIENT_ID or pass --client-id (see README: EVE login)")
        if a.cmd == "login":
            if a.char:
                r = sso.login(a.client_id)
                print("Logged in as", r["character_name"], r["character_id"])
            else:                                         # any character: it is filed automatically
                from .active import register, remember
                r = sso.login(a.client_id, path="tokens_pending.json")
                label, name = register()
                remember(os.path.dirname(a.db) or ".", label)
                print(f"Logged in as {name}. From now on the tool finds this character by itself (no --char needed).")
        else:
            from .character import sync_character
            from .esi import ESI
            esi = ESI()
            esi.token, cid = sso.get_token(a.client_id)
            print(sync_character(con, esi, cid, p))
            p.save(a.profile)
            print("Profile updated:", a.profile)
    elif a.cmd == "go":
        from .autopilot import route_alerts, send_route
        from .graph import Graph
        opps = plan(con, p, max(a.top, a.pick))
        if len(opps) < a.pick:
            raise SystemExit("No such opportunity; run scan first")
        o = opps[a.pick - 1]
        g = Graph(con)
        print(format_plan([o]))
        esi = None
        if a.send:
            from . import sso
            from .esi import ESI
            esi = ESI()
            esi.token, _ = sso.get_token(a.client_id)
        print("Waypoints:", " > ".join(send_route(esi, g, o.waypoints, a.send, stops=o.detail.get("stops"))))
        print("SENT to game client - press autopilot / fly it yourself." if a.send
              else "Dry run. Add --send to set waypoints in your game client.")
        for n, k in route_alerts(g, o.waypoints):
            print(f"ALERT {k}: {n}")
    elif a.cmd in ("start", "stop"):
        from . import sso
        from .esi import ESI
        from .session import start, stop
        if a.cmd == "start":
            if not a.activity:
                raise SystemExit('usage: start --activity "Level 1 security mission"')
            _, cid = sso.get_token(a.client_id)
            print(start(con, a.activity, cid))
        else:
            esi = ESI()
            esi.token, _ = sso.get_token(a.client_id)
            try:
                print(stop(con, esi, a.isk, ship=p.ship_name, paused_min=a.paused))
            except ValueError as e:
                raise SystemExit(str(e))
    elif a.cmd == "log":
        if not (a.activity and a.hours > 0):
            raise SystemExit('usage: log --activity "<name>" --isk <earned> --hours <spent>')
        con.execute("INSERT INTO activity_log(activity,isk,hours,ts) VALUES(?,?,?,?)",
                    (a.activity, a.isk, a.hours, time.time()))
        con.commit()
        print("Logged. Planner will use your real average after 3 runs.")
    elif a.cmd == "mock":
        from .mock import load_mock
        load_mock(con)
        print("Mock universe + market loaded into", a.db)
    elif a.cmd == "day":
        from .graph import Graph
        from .schedule import build_day, format_day
        print(format_day(build_day(con, Graph(con), p, a.hours or 8.0, a.cash, include_stock=not a.no_stock)))
    elif a.cmd == "sellplan":
        from .esi import ESI
        from .graph import Graph
        from .sellplan import format_sellplan, sell_plan
        g = Graph(con)
        world = {}
        if a.world:
            from .bestprice import best_prices
            esi = ESI()
            held = con.execute("SELECT i.type_id,i.quantity FROM inventory i WHERE i.system_id=? ORDER BY i.quantity DESC",
                               (g.id_of(p.current_system),)).fetchall()
            first = sell_plan(con, g, p, a.to or None)["rows"][:a.world]       # the biggest stacks only
            ids = {r["name"]: r for r in first}
            for r in held:
                nm = con.execute("SELECT name FROM types WHERE type_id=?", (r["type_id"],)).fetchone()[0]
                if nm in ids:
                    print(f"Checking every market for {nm}...", flush=True)
                    world[r["type_id"]] = best_prices(con, g, p, esi, r["type_id"], r["quantity"])[0]
        print(format_sellplan(sell_plan(con, g, p, a.to or None, world)))
    elif a.cmd == "bestprice":
        from .bestprice import best_prices, format_best, resolve_type
        from .esi import ESI
        from .graph import Graph
        if not a.item:
            raise SystemExit('usage: bestprice --item "Zydrine" [--qty 25393]')
        g = Graph(con)
        tid, nm, _ = resolve_type(con, a.item)
        held = con.execute("SELECT quantity FROM inventory WHERE type_id=? AND system_id=?", (tid, g.id_of(p.current_system))).fetchone()
        qty = a.qty or (held[0] if held else 1)
        print(f"Asking ESI for buy orders of {nm} in every region (about a minute)...", flush=True)
        rows, _ = best_prices(con, g, p, ESI(), tid, qty, log=lambda m: print(m, flush=True))
        print(format_best(nm, qty, rows, p.current_system))
        from .bestprice import add_asks
        asks = add_asks(ESI(), rows, tid, p.current_system)
        sysid = {g.name[k]: k for k in asks}
        here_ask = asks.get(g.id_of(p.current_system))
        net = lambda price: qty * price * (1 - p.sales_tax - p.broker_fee)
        print("\nIf you LIST instead (lowest sell order now, you still wait for a buyer; after tax and broker fee):")
        seen = set()
        for d in rows[:8]:
            sid = next((k for k, v in g.name.items() if v == d["system"]), None)
            if sid in asks and d["system"] not in seen:
                seen.add(d["system"])
                tag = "  <- here" if d["system"] == p.current_system else ""
                print(f"   {d['system']:<14} lowest ask {asks[sid]:>16,.0f}   you would get about {net(asks[sid]):>16,.0f}{tag}")
        if here_ask:
            print(f"   (here {p.current_system}: listing ~{net(here_ask):,.0f} vs selling instantly here {rows and next((d['net'] for d in rows if d['system'] == p.current_system), 0):,.0f})")
    elif a.cmd == "update":
        from .update import check_update, remember
        status, build = check_update(con)
        if status == "new":
            print(f"NEW GAME DATA (build {build}): a patch has changed items/blueprints/skills.\n"
                  f"   Reload and re-check:  python -m eve_profit universe --force\n"
                  f"   then:  python -m eve_profit scan --live   python -m eve_profit bpbuy   python -m eve_profit skills")
        elif status == "first":
            remember(con, build)
            print(f"Recorded the current game data build ({build}). Run `update` again after each patch.")
        else:
            print(f"Game data is up to date (build {build}).")
    elif a.cmd == "bpbuy":
        from .bpbuy import bp_buy_candidates, format_bpbuy
        from .graph import Graph
        if a.to:
            p.current_system = a.to           # evaluate the stock parked in that system, priced there
        print(format_bpbuy(*bp_buy_candidates(con, Graph(con), p)))
    elif a.cmd == "keep":
        from .graph import Graph
        from .keep import format_keep, keep_vs_sell
        if a.to:
            p.current_system = a.to
        print(format_keep(*keep_vs_sell(con, Graph(con), p)))
    elif a.cmd == "journey":
        from .graph import Graph
        from .journey import format_journey, journey_regions, plan_journey
        if not a.to:
            raise SystemExit('usage: journey --to Jita [--detour 2] [--live]')
        g = Graph(con)
        if a.live:
            from .esi import ESI, refresh_item, refresh_orders, region_age_min
            regs = journey_regions(g, p, a.to, a.detour)
            if a.quick:
                tids = [r[0] for r in con.execute("SELECT DISTINCT type_id FROM inventory")]
                print(f"Quick refresh: {len(tids)} items you own x {len(regs)} regions...", flush=True)
                esi, n = ESI(), 0
                for tid in tids:
                    try:
                        n += refresh_item(con, esi, regs, tid)
                    except Exception as e:
                        print(f"   item {tid} skipped: {type(e).__name__}")
                print("Fetched orders:", n)
            else:
                stale = [r for r in regs if (region_age_min(con, r) is None or region_age_min(con, r) >= a.max_age)]
                print(f"Refreshing the markets along the route: {len(stale)} of {len(regs)} regions are stale "
                      f"(older than {a.max_age} min); the rest are reused. Big hubs take a while; Ctrl+C keeps what is done.", flush=True)
                print("Fetched orders:", refresh_orders(con, ESI(), regs, a.max_pages, a.max_age))
        try:
            print(format_journey(plan_journey(con, g, p, a.to, a.detour)))
        except (ValueError, KeyError) as e:
            raise SystemExit(f"Cannot plan that trip: {e} (check the system name; 'no safe route' means every way is red or too long)")
    elif a.cmd == "compare":
        from .compare import compare, format_compare
        from .esi import ESI
        from .graph import Graph
        if not a.to:
            raise SystemExit("usage: compare --to Jita [--detour 2]   (needs a synced character and fresh prices)")
        try:
            print(format_compare(compare(con, Graph(con), p, ESI(), a.to, a.detour)))
        except (ValueError, KeyError) as e:
            raise SystemExit(f"Cannot compare: {e}")
    elif a.cmd == "combatfit":
        if not (a.dps and a.ehp):
            raise SystemExit('usage: combatfit [--ship "Vexor"] --dps 450 --ehp 60000 [--tank 200] [--value 30000000]\n'
                             "   Read the numbers off Pyfa (DPS, effective HP, sustained tank) for the fit you fly.")
        ship = a.ship or p.ship_name
        st = {"combat_dps": a.dps, "ship_ehp": a.ehp, "ship_tank_dps": a.tank, "ship_value_isk": a.value}
        p.ships[ship] = {**p.ships.get(ship, {}), **st}
        if ship == p.ship_name:
            p.combat_dps, p.ship_ehp, p.ship_tank_dps = a.dps, a.ehp, a.tank
            if a.value:
                p.fit_value_isk = a.value
        p.save(a.profile)
        print(f"Saved combat numbers for {ship}: {a.dps:,.0f} DPS, {a.ehp:,.0f} EHP, {a.tank:,.0f} tank/s. "
              f"Combat is now ranked against everything else by ISK/hr (only where the win margin is high).")
    elif a.cmd == "now":
        _now(a)
    elif a.cmd == "chars":
        from .chars import compare
        print(compare(a.db if not a.char else default_db_path(), "profile.json"))
    elif a.cmd == "next":
        from .graph import Graph
        from .nextstep import next_action
        print(next_action(con, Graph(con), p))
    elif a.cmd == "zkill":
        from .esi import ESI
        from .zkill import ZKill, refresh_gank_map
        print("Fetching recent hauler losses from zKillboard (about 1 request per second)...")
        print(refresh_gank_map(con, ZKill(), ESI(), regions_near(con, p)))
        from .graph import Graph
        g = Graph(con)
        top = sorted(g.gank.items(), key=lambda kv: -kv[1])[:10]
        for s, n in top:
            print(f"   {g.name[s]:<14} {n} hauler losses in 7 days  (sec {g.sec[s]:.1f})")
    elif a.cmd == "fit":
        from .fit import describe_fit
        print(describe_fit(con, p))
    elif a.cmd == "along":
        from .along import format_along, plan_along
        from .graph import Graph
        if not a.to:
            raise SystemExit('usage: along --to "<destination system>"')
        g = Graph(con)
        res = plan_along(con, g, p, a.to)
        if any(d.get("advice") == "LIST" for d in res["sell_here"]):
            try:
                from .along import attach_history
                from .esi import ESI
                attach_history(ESI(), res, g.region[g.id_of(p.current_system)])
            except Exception as e:
                print("(could not fetch market history:", e, ")")
        print(format_along(res))
    elif a.cmd == "stock":
        from .graph import Graph
        from .stock import stock_report
        print(stock_report(con, Graph(con), p, max(a.top, 25)))
    elif a.cmd == "check":
        from .esi import ESI, refresh_item
        from .explain import explain_trade
        from .graph import Graph
        opps = plan(con, p, max(a.top, a.pick), save=False)
        if len(opps) < a.pick or opps[a.pick - 1].kind != "trade":
            raise SystemExit("check works on a ranked trade; run scan, then check --pick N")
        o = opps[a.pick - 1]
        g = Graph(con)
        regions = sorted({g.region[o.detail["from_sys"]], g.region[o.detail["to_sys"]]})
        print(f"Asking ESI for fresh orders of this item in regions {regions}...", flush=True)
        print(f"Fresh orders stored: {refresh_item(con, ESI(), regions, o.detail['type_id'])}")
        fresh = [x for x in plan(con, p, 10000, save=False) if x.kind == "trade"
                 and x.detail.get("type_id") == o.detail["type_id"]
                 and x.detail.get("from_sys") == o.detail["from_sys"] and x.detail.get("to_sys") == o.detail["to_sys"]]
        if not fresh:
            print("\nAFTER REFRESH THIS TRADE NO LONGER MAKES MONEY. Do not buy.")
        else:
            print(format_plan([fresh[0]]))
            print()
            print(explain_trade(con, g, p, fresh[0]))
    elif a.cmd == "explain":
        from .explain import explain_trade
        from .graph import Graph
        opps = plan(con, p, max(a.top, a.pick), save=False)
        if len(opps) < a.pick:
            raise SystemExit("No such opportunity; run scan first")
        print(format_plan([opps[a.pick - 1]]))
        print()
        print(explain_trade(con, Graph(con), p, opps[a.pick - 1]))
    elif a.cmd == "diag":
        from .diag import diagnose
        print(diagnose(con, p))
    elif a.cmd == "skills":
        from .advisor import advise, format_advice
        from .advisor import candidate_skill_ids, fill_skill_info
        from .esi import ESI
        got = fill_skill_info(con, ESI(), candidate_skill_ids(con, p))
        if got:
            print(f"Fetched training ranks for {got} skills from ESI.")
        print("Testing each skill by re-running the planner (this can take a minute or two)...")
        print(format_advice(advise(con, p, plan, a.hours or 72)))   # --hours N = training hours to plan
        from .trainplan import format_trainplan, plan_training
        print("\n" + format_trainplan(plan_training(con, a.hours or 72)))
    elif a.cmd == "activities":
        from .session import summary
        print(summary(con))
    elif a.cmd == "trainplan":
        from .advisor import fill_skill_info
        from .esi import ESI
        from .trainplan import GOALS, format_trainplan, plan_training
        try:
            fill_skill_info(con, ESI(), [r[0] for n, _, _ in GOALS for r in [con.execute(
                "SELECT type_id FROM types WHERE name=? COLLATE NOCASE", (n,)).fetchone() or (None,)] if r])
        except Exception:
            pass
        print(format_trainplan(plan_training(con, a.hours or 24)))
    elif a.cmd == "fleet":
        from .fleet import describe_fleet
        from .graph import Graph
        print(describe_fleet(con, Graph(con), p))
    elif a.cmd in ("universe", "esimap"):
        have = con.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
        if a.cmd == "universe" and have > 500 and not a.force:
            print(f"Universe already loaded ({have} systems).")
        else:
            ok = False
            if a.cmd == "universe":                       # 1) official SDE download
                from .sde_jsonl import download as dl_jsonl, import_jsonl
                try:
                    zip_path = a.sde_file or (dl_jsonl(os.path.dirname(a.db) or ".", a.sde_url)
                                              if a.sde_url else dl_jsonl(os.path.dirname(a.db) or "."))
                    counts = import_jsonl(con, zip_path)
                    try:
                        from .update import check_update, remember
                        remember(con, check_update(con)[1])
                    except Exception:
                        pass
                    print("Imported SDE:", counts)
                    ok = counts.get("systems", 0) > 500 and counts.get("gates", 0) > 500
                    if not ok:
                        print("SDE layout not as expected; falling back to the ESI map builder.")
                except Exception as e:
                    print("SDE download/import failed:", e)
            if not ok:                                    # 2) build the neighbourhood from ESI
                from .esi import ESI
                from .esimap import build_map
                depth = a.depth or max(3, p.max_jumps * 3)
                print(f"Building the map around {p.current_system} ({depth} jumps) from ESI...")
                s, g = build_map(con, ESI(), p.current_system, depth)
                print(f"Map ready: {s} systems, {g} gates. (No blueprint/agent data without the SDE.)")
    elif a.cmd == "sde":
        from .sde import download, import_sde
        from .sde import extract
        try:
            if a.sde_file:
                if not os.path.exists(a.sde_file):
                    raise SystemExit(f"File not found: {a.sde_file}")
                path = extract(a.sde_file, os.path.join(os.path.dirname(a.db) or ".", "sde.sqlite"))
            else:
                path = download(os.path.dirname(a.db) or ".", a.sde_url or None)
        except RuntimeError as e:
            raise SystemExit(str(e))
        print("Imported systems:", import_sde(con, path))
    else:
        esi = None
        if a.live:
            from .esi import ESI
            esi = ESI()
        if con.execute("SELECT COUNT(*) FROM systems WHERE name=? COLLATE NOCASE",
                       (p.current_system,)).fetchone()[0] == 0:
            raise SystemExit(f"System '{p.current_system}' not found in this database. Set yours with:  "
                             f"python -m eve_profit profile --system \"<system name>\"   "
                             f"(for live data run  python -m eve_profit sde  first)")
        while True:
            regions = ([int(x) for x in a.regions.split(",")] if a.regions
                       else regions_near(con, p))
            if a.live:
                print(f"Contacting ESI for market orders in regions {regions} "
                      f"(first page can take up to ~30 s; Ctrl+C to stop)...", flush=True)
                from .esi import refresh_orders
                print("Fetched orders:", refresh_orders(con, esi, regions, a.max_pages, a.max_age))
                from .contracts import refresh_contracts
                from .graph import Graph
                g0 = Graph(con)
                near = g0.reach(g0.id_of(p.current_system), p.max_jumps * 2, p.avoid_yellow)
                print("Contracts stored / contents fetched:",
                      refresh_contracts(con, esi, regions, set(near)))
                from .lp import refresh_offers
                ids = ",".join(str(int(s)) for s in near) or "0"
                corps = [r[0] for r in con.execute(
                    f"SELECT corporation_id FROM lp_balance UNION SELECT corporation_id FROM agents "
                    f"WHERE system_id IN ({ids}) UNION SELECT corporation_id FROM stations "
                    f"WHERE system_id IN ({ids}) AND corporation_id IS NOT NULL")]
                print("LP stores refreshed:", refresh_offers(con, esi, corps))
                try:
                    from .zkill import ZKill, refresh_gank_map
                    print("zKillboard:", refresh_gank_map(con, ZKill(), esi, regions))
                except Exception as e:           # optional signal: never break a scan
                    print("zKillboard skipped:", e)
                if p.use_structures:
                    from . import sso
                    if a.client_id and os.path.exists(sso.token_path()):
                        from .structures import refresh_structures
                        esi.token, _ = sso.get_token(a.client_id)      # refreshes if expired
                        print("Structures:", refresh_structures(con, esi, set(near), p.structure_ids))
                    else:
                        print("Structure markets skipped (run login first)")
            elif a.cmd == "watch":
                from .mock import refresh_mock_orders
                refresh_mock_orders(con, random.Random())
            print(f"\n=== {time.strftime('%H:%M:%S')} from {p.current_system}, "
                  f"{p.cargo_m3:,.0f} m3, {p.max_jumps} jumps ===")
            top = plan(con, p, a.top)
            print(format_plan(top))
            from .skills import blocked_blueprints
            for name, why in blocked_blueprints(con, p):
                print(f"  blocked build: {name} - needs {why}")
            if top:
                from .autopilot import route_alerts
                from .graph import Graph
                for n, k in route_alerts(Graph(con), top[0].waypoints):
                    print(f"\a!! {k} system {n} on best route: dock up / wait / pick another")
            if a.cmd != "watch":
                break
            time.sleep(a.interval if a.live else 3)


def _now(a):
    """One command: sync -> live market scan -> best next step -> worldwide price check for the big stacks."""
    import contextlib
    import copy
    import io
    t0 = time.time()

    class Progress(io.StringIO):
        """Keeps the stage output for later but shows the slow download progress lines as they happen."""
        SHOW = ("  region ", "Fetched", "Contracts", "LP stores", "zKillboard", "Structures", "Contacting")
        _line = ""

        def write(self, text):
            super().write(text)
            self._line += text
            while "\n" in self._line:
                line, self._line = self._line.split("\n", 1)
                if line.startswith(self.SHOW):
                    sys.__stdout__.write("   " + line.strip() + "\n")
                    sys.__stdout__.flush()
            return len(text)

    def stage(label, cmd, **kw):
        b = copy.copy(a)
        b.cmd, b.sync = cmd, False
        for k, v in kw.items():
            setattr(b, k, v)
        print(f"[{label}] ...", flush=True)
        buf = Progress()
        try:
            with contextlib.redirect_stdout(buf):
                _run(b)
        except KeyboardInterrupt:
            print("   stopped with Ctrl+C: carrying on with the data already stored")
        except SystemExit as e:
            print(f"   skipped: {e}")
        except Exception as e:                  # one failed stage must not stop the rest
            print(f"   failed: {type(e).__name__}: {e}")
        return buf.getvalue().strip()

    stage("1/4 your character: assets, wallet, location", "sync")
    if not a.fast:
        stage("2/4 market prices (live)", "scan", live=True, top=5)
    step = stage("3/4 working out your next step", "next")
    checks = []
    try:
        from .along import plan_along
        from .bestprice import best_prices, format_best
        from .esi import ESI
        from .graph import Graph
        con = db.connect(a.db)
        p = Profile.load(a.profile)
        g = Graph(con)
        sells = [d for d in plan_along(con, g, p, p.current_system)["sell_here"]
                 if d["advice"] != "LIST" and d["net"] >= 5_000_000 and d.get("tid")]
        if sells:
            print(f"[4/4 best price in all of New Eden for your {min(len(sells), 2)} biggest sell stack(s)] ...", flush=True)
            esi = ESI()
            for d in sells[:2]:
                rows, _ = best_prices(con, g, p, esi, d["tid"], d["sold"], log=lambda m: None)
                checks.append(f"   {d['name']}: " + format_best(d["name"], d["sold"], rows, p.current_system).splitlines()[-1])
        else:
            print("[4/4 worldwide price check] nothing big enough to check")
    except SystemExit as e:
        print(f"   skipped: {e}")
    except Exception as e:
        print(f"   price check failed: {type(e).__name__}: {e}")
    print(f"\n{'=' * 70}\n{step}")
    if checks:
        print("\nWORLDWIDE PRICE CHECK:")
        print("\n".join(checks))
    print(f"\n(done in {time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
