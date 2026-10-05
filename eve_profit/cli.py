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
    ap.add_argument("cmd", choices=["init", "mock", "sde", "scan", "plan", "watch", "profile", "login", "sync", "log", "go", "universe", "esimap"])
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
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)
    a.client_id = resolve_client_id(a.client_id)

    con = db.connect(a.db)
    p = Profile.load(a.profile)
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
        print("Waypoints:", " > ".join(send_route(esi, g, o.waypoints, a.send)))
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
