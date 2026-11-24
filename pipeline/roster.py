"""Full-league name lists for autocomplete, each with a rough 'fame' weight.

The weight only orders suggestions (famous names first). It is built from career
volume stats, so stars outrank one-season players.

Output: pipeline/data/roster_<sport>.json  ->  {"Player Name": weight, ...}
"""
from __future__ import annotations

import ast
import csv
import io
import json
from collections import defaultdict

from .common import DATA_DIR, fetch, fetch_json, log
from . import nfl as nfl_miner

NBA_API_DATA = "https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/stats/library/data.py"


def roster_path(sport: str):
    return DATA_DIR / f"roster_{sport}.json"


def _save(sport: str, weights: dict[str, float]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = {n.strip(): round(w, 1) for n, w in weights.items() if n and n.strip()}
    roster_path(sport).write_text(json.dumps(clean, ensure_ascii=False, indent=0, sort_keys=True))
    log(f"{sport.upper()} roster: {len(clean)} names")


def nba() -> None:
    weights: dict[str, float] = defaultdict(float)
    # Every NBA player ever, from the open-source nba_api project. The file is
    # parsed as data line by line and never executed.
    text = fetch(NBA_API_DATA, ext="py", max_age_days=30).decode("utf-8")
    block = text.split("players = [", 1)[1].split("wnba_players", 1)[0]
    for line in block.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("[") and line.endswith("]"):
            try:
                row = ast.literal_eval(line)
                weights[row[3]] += 0
            except (ValueError, SyntaxError, IndexError):
                continue
    # Career points since 1999-2000 (ESPN) as the fame weight.
    from .nba import BASE
    for y in range(2000, 2027):
        try:
            data = fetch_json(f"{BASE}/statistics/byathlete?season={y}&seasontype=2&limit=1000"
                              f"&sort=offensive.avgPoints:desc", max_age_days=7 if y >= 2025 else None)
        except Exception as e:  # noqa: BLE001
            log(f"NBA roster {y}: skipped ({e})")
            continue
        names = {c["name"]: c["names"] for c in data.get("categories", [])}
        for a in data.get("athletes", []):
            pts = 0.0
            for cat in a["categories"]:
                for n, v in zip(names.get(cat["name"], []), cat.get("values", [])):
                    if n == "points":
                        pts = float(v or 0)
            weights[a["athlete"]["displayName"]] += pts / 1000
    _save("nba", weights)


def mlb(first: int = 1960, last: int = 2026) -> None:
    weights: dict[str, float] = defaultdict(float)
    base = "https://statsapi.mlb.com/api/v1/stats?stats=season&sportId=1&playerPool=all&limit=3000"
    for y in range(first, last + 1):
        for group, stat, scale in (("hitting", "hits", 100), ("pitching", "inningsPitched", 100)):
            try:
                data = fetch_json(f"{base}&group={group}&season={y}", max_age_days=7 if y >= 2025 else None)
            except Exception as e:  # noqa: BLE001
                log(f"MLB roster {y} {group}: skipped ({e})")
                continue
            for sp in (data.get("stats") or [{}])[0].get("splits", []):
                try:
                    v = float(sp["stat"].get(stat) or 0)
                except ValueError:
                    v = 0
                weights[sp["player"]["fullName"]] += v / scale
    _save("mlb", weights)


def nfl() -> None:
    weights: dict[str, float] = defaultdict(float)
    body = fetch(f"{nfl_miner.REL}/players/players.csv", ext="csv", max_age_days=30)
    for r in csv.DictReader(io.StringIO(body.decode("utf-8"))):
        if r.get("position") not in ("QB", "RB", "WR", "TE", "FB"):
            continue
        try:
            years = int(r.get("last_season") or 0) - int(r.get("rookie_season") or 0) + 1
        except ValueError:
            years = 0
        weights[r["display_name"]] += max(years, 0) * 0.3
    # Scrimmage yards since 1999 (from the weekly files the miner already caches).
    for y in nfl_miner.DEFAULT_SEASONS + [nfl_miner.DEFAULT_SEASONS[-1] + 1]:
        try:
            rows = nfl_miner.weekly(y)
        except Exception:  # noqa: BLE001
            continue
        for r in rows:
            if r.get("position") not in ("QB", "RB", "WR", "TE", "FB"):
                continue
            yds = sum(nfl_miner.i(r, k) for k in ("passing_yards", "rushing_yards", "receiving_yards"))
            weights[r["player_display_name"]] += yds / 1000
    _save("nfl", weights)


def refresh(sport: str) -> None:
    {"nba": nba, "mlb": mlb, "nfl": nfl}[sport]()


def load(sport: str) -> dict[str, float]:
    p = roster_path(sport)
    return json.loads(p.read_text()) if p.exists() else {}
