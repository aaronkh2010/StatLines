"""Rule-based approval: replaces manual review (rules live in rules.py)."""
from __future__ import annotations

from collections import Counter

from . import roster, rules
import json

from .common import BASE_PLAYERS_PATH, SPORTS, log, normalize


def known_players(pool: dict, sport: str, top_n: int, min_standouts: int) -> set[str]:
    weights = roster.load(sport)
    ranked = sorted(weights, key=lambda n: -weights[n])[:top_n]
    known = {normalize(n) for n in ranked}
    standouts = Counter(normalize(c["answer"]) for c in pool.values() if c["sport"] == sport)
    known |= {n for n, k in standouts.items() if k >= min_standouts}
    # Hand-curated icons (pipeline/data/base_players.json) always count, e.g. Jordan,
    # whose career mostly predates the stats used for the fame ranking.
    base = json.loads(BASE_PLAYERS_PATH.read_text()) if BASE_PLAYERS_PATH.exists() else {}
    known |= {normalize(n) for n in base.get(sport, [])}
    return known


def run(pool: dict) -> None:
    """Approve or reject every candidate that isn't scheduled and wasn't hand-reviewed."""
    for sport in SPORTS:
        known = known_players(pool, sport, rules.FLOOR_TOP_N[sport], rules.FLOOR_MIN_STANDOUTS)
        ok = no = 0
        for c in pool.values():
            if c["sport"] != sport or c["status"] == "scheduled" or c.get("manual"):
                continue
            name = normalize(c["answer"])
            if c["kind"] == "season" or c["type"] in rules.FLOOR_EXEMPT_TYPES:
                reason = None
            else:
                reason = None if name in known else "too obscure"
            if reason:
                c["status"], c["reject_reason"] = "rejected", reason
                no += 1
            else:
                c["status"] = "approved"
                c.pop("reject_reason", None)
                ok += 1
        log(f"{sport.upper()}: {ok} approved, {no} rejected (obscure players)")
