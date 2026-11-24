"""StatLines content pipeline.

  python3 -m pipeline mine nba --seasons 2000-2025   # pull candidates into the pool
  python3 -m pipeline review --sport nba              # approve / reject / edit
  python3 -m pipeline approve --sport nfl             # bulk-approve pending (skip manual review)
  python3 -m pipeline select                          # approve/reject everything by rules.py
  python3 -m pipeline daily                           # what the scheduled job runs each day
  python3 -m pipeline status                          # pool counts + days of runway
  python3 -m pipeline schedule --days 14              # publish puzzles/<date>.json
  python3 -m pipeline players --refresh               # rebuild full-league autocomplete lists
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from . import review, schedule
from .common import KINDS, SPORTS, add_candidates, load_pool, log, save_pool


def parse_seasons(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def next_unpublished_day() -> date:
    idx = schedule.PUZZLE_DIR / "index.json"
    if idx.exists():
        import json
        dates = json.loads(idx.read_text()).get("dates", [])
        if dates:
            return max(date.fromisoformat(dates[-1]) + timedelta(days=1), date.today())
    return date.today()


def main() -> None:
    p = argparse.ArgumentParser(prog="python3 -m pipeline", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mine", help="fetch stats and add candidates to the pool")
    m.add_argument("sport", choices=SPORTS)
    m.add_argument("--seasons", default=None,
                   help="e.g. 2005-2025 or 2016,2021. NBA uses the season's END year (2016 = 2015-16).")

    r = sub.add_parser("review", help="interactively approve/reject pending candidates")
    r.add_argument("--sport", choices=SPORTS)
    r.add_argument("--kind", choices=KINDS)
    r.add_argument("--min-score", type=float, default=0)

    a = sub.add_parser("approve", help="bulk-approve pending candidates without reviewing them")
    a.add_argument("--sport", choices=SPORTS)
    a.add_argument("--kind", choices=KINDS)
    a.add_argument("--min-score", type=float, default=0)

    sub.add_parser("select", help="approve/reject all unreviewed candidates using rules.py")

    d = sub.add_parser("daily", help="refresh current seasons, apply rules, publish today")
    d.add_argument("--no-mine", action="store_true", help="skip refreshing current-season stats")
    d.add_argument("--ahead", type=int, default=0,
                   help="days past today to publish (default 0: each day's file reveals the previous day's answers)")

    sub.add_parser("status", help="pool counts and runway")

    s = sub.add_parser("schedule", help="assign approved candidates to dates and publish them")
    s.add_argument("--start", type=date.fromisoformat, default=None,
                   help="first date to fill (default: day after the last published day)")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--cooldown", type=int, default=14, help="minimum days before a player can repeat in a sport")
    s.add_argument("--force", action="store_true", help="re-pick dates that are already published")

    pl = sub.add_parser("players", help="rebuild players.json (autocomplete list)")
    pl.add_argument("--refresh", nargs="*", choices=SPORTS, metavar="SPORT",
                    help="re-download full-league rosters first (no SPORT = all three)")

    args = p.parse_args()

    if args.cmd == "mine":
        from importlib import import_module
        miner = import_module(f".{args.sport}", __package__)
        seasons = parse_seasons(args.seasons) if args.seasons else miner.DEFAULT_SEASONS
        candidates = miner.mine(seasons)
        pool = load_pool()
        added = add_candidates(pool, candidates)
        save_pool(pool)
        schedule.write_players(pool)
        log(f"{args.sport.upper()}: {len(candidates)} candidates found, {added} new added to the pool.")
    elif args.cmd == "review":
        review.run(args.sport, args.kind, args.min_score)
    elif args.cmd == "approve":
        pool = load_pool()
        n = 0
        for c in pool.values():
            if (c["status"] == "pending" and (not args.sport or c["sport"] == args.sport)
                    and (not args.kind or c["kind"] == args.kind) and c["score"] >= args.min_score):
                c["status"] = "approved"
                n += 1
        save_pool(pool)
        log(f"Approved {n} pending candidates.")
    elif args.cmd == "select":
        from . import select
        pool = load_pool()
        select.run(pool)
        save_pool(pool)
    elif args.cmd == "daily":
        from . import select
        from .common import eastern_today
        from importlib import import_module
        if not args.no_mine:
            pool = load_pool()
            for sport in SPORTS:
                miner = import_module(f".{sport}", __package__)
                try:
                    add_candidates(pool, miner.mine(miner.current_seasons()))
                except Exception as e:  # noqa: BLE001 — a flaky source shouldn't block publishing
                    log(f"{sport.upper()}: refresh failed ({e}); publishing from the existing pool")
            save_pool(pool)
        pool = load_pool()
        select.run(pool)
        save_pool(pool)
        today = eastern_today()
        schedule.run(today, args.ahead + 1, 14, False)
    elif args.cmd == "status":
        review.status()
    elif args.cmd == "schedule":
        schedule.run(args.start or next_unpublished_day(), args.days, args.cooldown, args.force)
    elif args.cmd == "players":
        if args.refresh is not None:
            from . import roster
            for sp in args.refresh or SPORTS:
                roster.refresh(sp)
        schedule.write_players()


if __name__ == "__main__":
    main()
