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
    ap.add_argument("cmd", choices=["init", "mock", "sde", "scan", "plan", "watch", "profile"])
    ap.add_argument("--db", default=default_db_path())
    ap.add_argument("--profile", default="profile.json")
    ap.add_argument("--live", action="store_true", help="use real ESI market data")
    ap.add_argument("--regions", default="10000002", help="comma list of region ids")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--interval", type=int, default=300, help="watch seconds (ESI caches 5 min)")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)

    con = db.connect(a.db)
    p = Profile.load(a.profile)
    if a.cmd == "init":
        print("DB ready:", a.db)
    elif a.cmd == "profile":
        p.save(a.profile)
        print("Wrote", a.profile, "- edit ship/cargo/system, then run scan")
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
