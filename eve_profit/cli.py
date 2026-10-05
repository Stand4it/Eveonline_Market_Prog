"""Command line: python -m eve_profit <command>"""
import argparse
import os
import random
import time

from . import db
from .config import Profile, default_db_path
from .planner import format_plan, plan


def resolve_client_id(explicit=""):
    """Priority: --client-id, then client_id.txt, then env EVE_CLIENT_ID. Placeholders/typos are
    rejected: a real CCP client id is 32 hex characters."""
    import re
    cands = [explicit]
    if os.path.exists("client_id.txt"):
        cands.append(open("client_id.txt").read().strip())
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
    ap.add_argument("cmd", choices=["init", "mock", "sde", "scan", "plan", "watch", "profile", "login", "sync", "log", "go", "universe", "esimap", "fleet", "skills", "diag", "explain", "check", "stock", "along", "fit", "zkill", "next", "keep", "bpbuy"])
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
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)
    a.client_id = resolve_client_id(a.client_id)

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


def _run(a):
    con = db.connect(a.db)
    p = Profile.load(a.profile)
    if a.away:
        p.away_mode = True
    from .combat import seed_defaults
    seed_defaults(con)
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
            r = sso.login(a.client_id)
            print("Logged in as", r["character_name"], r["character_id"])
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
    elif a.cmd == "fleet":
        from .fleet import describe_fleet
        from .graph import Graph
        print(describe_fleet(con, Graph(con), p))
    elif a.cmd in ("universe", "esimap"):
        have = con.execute("SELECT COUNT(*) FROM systems").fetchone()[0]
        if a.cmd == "universe" and have > 500:
            print(f"Universe already loaded ({have} systems).")
        else:
            ok = False
            if a.cmd == "universe":                       # 1) official SDE download
                from .sde_jsonl import download as dl_jsonl, import_jsonl
                try:
                    zip_path = a.sde_file or (dl_jsonl(os.path.dirname(a.db) or ".", a.sde_url)
                                              if a.sde_url else dl_jsonl(os.path.dirname(a.db) or "."))
                    counts = import_jsonl(con, zip_path)
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
                print("Fetched orders:", refresh_orders(con, esi, regions, a.max_pages))
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
                    if a.client_id and os.path.exists("tokens.json"):
                        from . import sso
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


if __name__ == "__main__":
    main()
