"""Interactive terminal review of mined candidates."""
from __future__ import annotations

import textwrap

from .common import KINDS, SPORTS, load_pool, save_pool

BALL = {"nba": "🏀", "mlb": "⚾", "nfl": "🏈"}
BOLD, DIM, GREEN, RED, YELLOW, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def show(c: dict, idx: int, total: int) -> None:
    print("\n" + "─" * 64)
    print(f"{DIM}[{idx}/{total}] {c['id']}  score={c['score']}{RESET}")
    print(f"{BOLD}{BALL[c['sport']]} {c['sport'].upper()} · {c['type']}{RESET}")
    print(f"{DIM}{c['context']}{RESET}\n")
    labels = [s["label"] for s in c["stats"]]
    values = [s["value"] for s in c["stats"]]
    widths = [max(len(l), len(v)) + 2 for l, v in zip(labels, values)]
    print("".join(l.center(w) for l, w in zip(labels, widths)))
    print(YELLOW + "".join(v.center(w) for v, w in zip(values, widths)) + RESET + "\n")
    for i, h in enumerate(c["hints"], 1):
        print(textwrap.fill(f"Hint {i}: {h}", 64, subsequent_indent="        "))
    print(f"\n{GREEN}Answer: {c['answer']}{RESET}   aliases: {', '.join(c['aliases']) or '—'}")
    print(f"{DIM}Reveal: {c['reveal']}{RESET}")


def edit(c: dict) -> None:
    print(f"{DIM}Press Enter to keep a value.{RESET}")
    for i, h in enumerate(c["hints"]):
        new = input(f"Hint {i + 1} [{h}]\n> ").strip()
        if new:
            c["hints"][i] = new
    new = input(f"Aliases, comma-separated [{', '.join(c['aliases'])}]\n> ").strip()
    if new:
        c["aliases"] = [a.strip() for a in new.split(",") if a.strip()]
    new = input(f"Context [{c['context']}]\n> ").strip()
    if new:
        c["context"] = new
    new = input(f"Reveal [{c['reveal']}]\n> ").strip()
    if new:
        c["reveal"] = new


def run(sport: str | None, kind: str | None, min_score: float) -> None:
    pool = load_pool()
    queue = [c for c in pool.values()
             if c["status"] == "pending"
             and (sport is None or c["sport"] == sport)
             and (kind is None or c["kind"] == kind)
             and c["score"] >= min_score]
    # Most notable first, so the best material gets approved early.
    queue.sort(key=lambda c: -c["score"])
    if not queue:
        print("Nothing pending to review. Run `python3 -m pipeline mine <sport>` first.")
        return

    approved = rejected = 0
    print(f"{len(queue)} pending candidates. Keys: [a]pprove  [r]eject  [e]dit then decide  [s]kip  [q]uit")
    for i, c in enumerate(queue, 1):
        show(c, i, len(queue))
        while True:
            choice = input(f"{BOLD}a/r/e/s/q > {RESET}").strip().lower()
            if choice == "e":
                edit(c)
                show(c, i, len(queue))
                continue
            break
        if choice == "a":
            c["status"], c["manual"] = "approved", True
            approved += 1
            print(f"{GREEN}✓ approved{RESET}")
        elif choice == "r":
            c["status"], c["manual"] = "rejected", True
            rejected += 1
            print(f"{RED}✗ rejected{RESET}")
        elif choice == "q":
            break
        else:
            print(f"{DIM}skipped{RESET}")
        save_pool(pool)  # save after every decision so quitting never loses work
    save_pool(pool)
    print(f"\nDone: {approved} approved, {rejected} rejected.")


def status() -> None:
    pool = load_pool()
    print(f"{'':6}{'kind':10}{'pending':>9}{'approved':>10}{'rejected':>10}{'scheduled':>11}")
    runway = {}
    for s in SPORTS:
        days_left = []
        for k in KINDS:
            counts = {st: 0 for st in ("pending", "approved", "rejected", "scheduled")}
            for c in pool.values():
                if c["sport"] == s and c["kind"] == k:
                    counts[c["status"]] += 1
            print(f"{s.upper():6}{k:10}{counts['pending']:>9}{counts['approved']:>10}"
                  f"{counts['rejected']:>10}{counts['scheduled']:>11}")
            per_day = 2 if k in ("game", "season") else 1
            days_left.append(counts["approved"] // per_day)
        runway[s] = min(days_left)
    print("\nRunway (days schedulable from approved stock): "
          + ", ".join(f"{s.upper()} {d}" for s, d in runway.items())
          + f"  →  {min(runway.values())} full days")
