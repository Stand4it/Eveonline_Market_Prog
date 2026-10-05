"""Command line: python -m eve_profit <command>"""
import argparse
import os
import random
import time

from . import db
from .config import Profile, default_db_path
from .planner import format_plan, plan


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eve_profit")
    ap.add_argument("cmd", choices=["init", "mock", "sde", "scan", "plan", "watch", "profile", "login", "sync", "log"])
    ap.add_argument("--db", default=default_db_path())
    ap.add_argument("--profile", default="profile.json")
    ap.add_argument("--live", action="store_true", help="use real ESI market data")
    ap.add_argument("--regions", default="10000002", help="comma list of region ids")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--interval", type=int, default=300, help="watch seconds (ESI caches 5 min)")
    ap.add_argument("--client-id", default=os.environ.get("EVE_CLIENT_ID", ""))
    ap.add_argument("--activity", default="")
    ap.add_argument("--isk", type=float, default=0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)

    con = db.connect(a.db)
    p = Profile.load(a.profile)
    from .combat import seed_defaults
    seed_defaults(con)
    if a.cmd == "init":
        print("DB ready:", a.db)
    elif a.cmd == "profile":
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
    elif a.cmd == "sde":
        from .sde import download, import_sde
        path = download(os.path.dirname(a.db) or ".")
        print("Imported systems:", import_sde(con, path))
    else:
        regions = [int(x) for x in a.regions.split(",")]
        esi = None
        if a.live:
            from .esi import ESI
            esi = ESI()
        while True:
            if a.live:
                from .esi import refresh_orders
                print("Fetched orders:", refresh_orders(con, esi, regions, a.max_pages))
            elif a.cmd == "watch":
                from .mock import refresh_mock_orders
                refresh_mock_orders(con, random.Random())
            print(f"\n=== {time.strftime('%H:%M:%S')} from {p.current_system}, "
                  f"{p.cargo_m3:,.0f} m3, {p.max_jumps} jumps ===")
            print(format_plan(plan(con, p, a.top)))
            if a.cmd != "watch":
                break
            time.sleep(a.interval if a.live else 3)


if __name__ == "__main__":
    main()
