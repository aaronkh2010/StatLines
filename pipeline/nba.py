"""NBA miner — ESPN's public JSON API (stats.nba.com blocks scripted requests).

Seasons are identified by their END year: 2016 means the 2015-16 season.
"""
from __future__ import annotations

from .common import (eastern_today, eastern_date, fetch_json, fmt_1, fmt_pct, initials, is_current_season, log, make_candidate,
                     pretty_date)

def current_season() -> int:
    """END year of the season in progress (or most recently finished)."""
    t = eastern_today()
    return t.year + 1 if t.month >= 10 else t.year


DEFAULT_SEASONS = list(range(2000, current_season() + 1))


def current_seasons() -> list[int]:
    return [current_season()]
BASE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
TOP_SCORERS_FOR_GAMELOGS = 80


def label(y: int) -> str:
    return f"{y - 1}-{str(y)[2:]}"


def by_athlete(season: int, season_type: int, limit: int = 150) -> list[dict]:
    """Per-game leaders for a season. season_type 2 = regular season, 3 = playoffs."""
    url = (f"{BASE}/statistics/byathlete?season={season}&seasontype={season_type}"
           f"&limit={limit}&sort=offensive.avgPoints:desc")
    data = fetch_json(url, max_age_days=1 if is_current_season(season) else None)
    names = {c["name"]: c["names"] for c in data.get("categories", [])}
    rows = []
    for a in data.get("athletes", []):
        stats = {}
        for cat in a["categories"]:
            for n, v in zip(names.get(cat["name"], []), cat.get("values", [])):
                stats[n] = float(v or 0)
        ath = a["athlete"]
        team = (ath.get("teams") or [{}])[0].get("displayName") or ath.get("teamName", "")
        rows.append({
            "id": ath["id"], "name": ath["displayName"], "team": team,
            "position": (ath.get("position") or {}).get("displayName", ""),
            "debut": ath.get("debutYear"), "s": stats,
        })
    return rows


def player_hint(p: dict) -> str:
    pos = p["position"].lower() or "player"
    return f"He's a {pos} who made his NBA debut in {p['debut']}." if p.get("debut") else f"He's a {pos}."


def season_candidates(season: int, rows: list[dict]) -> list[dict]:
    out = []
    qualified = [r for r in rows if r["s"].get("gamesPlayed", 0) >= 55]
    for rank, p in enumerate(rows, 1):
        s = p["s"]
        if p not in qualified:
            continue
        ppg, apg, rpg, td = s.get("avgPoints", 0), s.get("avgAssists", 0), s.get("avgRebounds", 0), s.get("tripleDouble", 0)
        bpg, spg = s.get("avgBlocks", 0), s.get("avgSteals", 0)
        notable = (rank <= 5 or ppg >= 24 or (ppg >= 16 and apg >= 8.5) or (ppg >= 14 and rpg >= 12) or td >= 10
                   or bpg >= 2.8 or spg >= 2.2 or (ppg >= 20 and apg >= 7) or (ppg >= 20 and rpg >= 10))
        if not notable:
            continue
        hint1 = "He led the NBA in scoring that season." if rank == 1 else player_hint(p)
        out.append(make_candidate(
            sport="nba", kind="season", key=f"{season}:{p['id']}", answer=p["name"], player_id=p["id"],
            type_="Full Season Statline", context=f"Regular Season · {int(s['gamesPlayed'])} games",
            stats=[("PPG", fmt_1(ppg)), ("RPG", fmt_1(rpg)), ("APG", fmt_1(apg)),
                   ("SPG", fmt_1(s.get("avgSteals", 0))), ("BPG", fmt_1(s.get("avgBlocks", 0))),
                   ("FG%", fmt_pct(s.get("fieldGoalPct", 0))), ("3P%", fmt_pct(s.get("threePointFieldGoalPct", 0))),
                   ("FT%", fmt_pct(s.get("freeThrowPct", 0)))],
            hints=[hint1, f"He played for the {p['team']}.", f"His initials are {initials(p['name'])}"],
            reveal=f"{label(season)} · {p['team']}",
            score=ppg + 1.2 * apg + 0.8 * rpg + 0.3 * td + 2 * bpg + 2 * spg + (5 if rank == 1 else 0),
        ))
    return out


def playoff_candidates(season: int, rows: list[dict]) -> list[dict]:
    out = []
    for p in rows:
        s = p["s"]
        gp, ppg, rpg, apg = s.get("gamesPlayed", 0), s.get("avgPoints", 0), s.get("avgRebounds", 0), s.get("avgAssists", 0)
        if gp < 8 or not (ppg >= 26 or (ppg >= 22 and rpg >= 8 and apg >= 6) or (ppg >= 20 and rpg >= 12)):
            continue
        out.append(make_candidate(
            sport="nba", kind="wildcard", key=f"{season}:{p['id']}", answer=p["name"], player_id=p["id"],
            type_="Wild Card · Playoff Run", context=f"NBA Playoffs · {int(gp)} games",
            stats=[("GP", int(gp)), ("PPG", fmt_1(ppg)), ("RPG", fmt_1(rpg)), ("APG", fmt_1(apg)),
                   ("SPG", fmt_1(s.get("avgSteals", 0))), ("BPG", fmt_1(s.get("avgBlocks", 0))),
                   ("FG%", fmt_pct(s.get("fieldGoalPct", 0))), ("3P%", fmt_pct(s.get("threePointFieldGoalPct", 0)))],
            hints=[player_hint(p), f"He played for the {p['team']}.", f"His initials are {initials(p['name'])}"],
            reveal=f"{label(season)} Playoffs · {p['team']}",
            score=ppg + 1.0 * apg + 0.8 * rpg + 0.4 * gp,
        ))
    return out


def rookie_candidates(season: int, rows: list[dict]) -> list[dict]:
    out = []
    for p in rows:
        s = p["s"]
        if p.get("debut") != season - 1 or s.get("gamesPlayed", 0) < 50:
            continue
        ppg, rpg, apg = s.get("avgPoints", 0), s.get("avgRebounds", 0), s.get("avgAssists", 0)
        if not (ppg >= 15 or (ppg >= 10 and (rpg >= 9 or apg >= 6))):
            continue
        out.append(make_candidate(
            sport="nba", kind="wildcard", key=f"rookie:{season}:{p['id']}", answer=p["name"], player_id=p["id"],
            type_="Wild Card · Rookie Season", context=f"Rookie Season · {int(s['gamesPlayed'])} games",
            stats=[("PPG", fmt_1(ppg)), ("RPG", fmt_1(rpg)), ("APG", fmt_1(apg)),
                   ("SPG", fmt_1(s.get("avgSteals", 0))), ("BPG", fmt_1(s.get("avgBlocks", 0))),
                   ("FG%", fmt_pct(s.get("fieldGoalPct", 0))), ("3P%", fmt_pct(s.get("threePointFieldGoalPct", 0)))],
            hints=[f"He's a {p['position'].lower() or 'player'} and this was his first NBA season.",
                   f"He played for the {p['team']}.", f"His initials are {initials(p['name'])}"],
            reveal=f"{label(season)} rookie season · {p['team']}",
            score=ppg + 0.8 * rpg + 1.0 * apg,
        ))
    return out


def career_candidates(last_season: int) -> list[dict]:
    """Regular-season career totals for players whose whole career is in ESPN's data (debut 1999 or later)."""
    tot: dict[str, dict] = {}
    for y in range(2000, last_season + 1):
        try:
            data = fetch_json(f"{BASE}/statistics/byathlete?season={y}&seasontype=2&limit=1000"
                              f"&sort=offensive.avgPoints:desc", max_age_days=7 if is_current_season(y) else None)
        except Exception as e:  # noqa: BLE001
            log(f"NBA careers {y}: skipped ({e})")
            continue
        names = {c["name"]: c["names"] for c in data.get("categories", [])}
        for a in data.get("athletes", []):
            ath = a["athlete"]
            if not ath.get("debutYear") or ath["debutYear"] < 1999:
                continue
            t = tot.setdefault(ath["id"], {"name": ath["displayName"], "debut": ath["debutYear"], "seasons": 0,
                                           "teams": {}, "last": y,
                                           "position": (ath.get("position") or {}).get("displayName", "")})
            t["seasons"] += 1
            t["last"] = y
            team = (ath.get("teams") or [{}])[0].get("displayName") or ath.get("teamName", "")
            if team:
                t["teams"][team] = t["teams"].get(team, 0) + 1
            for cat in a["categories"]:
                for n, v in zip(names.get(cat["name"], []), cat.get("values", [])):
                    if n in ("gamesPlayed", "points", "rebounds", "assists", "steals", "blocks",
                             "fieldGoalsMade", "fieldGoalsAttempted", "threePointFieldGoalsMade"):
                        t[n] = t.get(n, 0) + float(v or 0)
    out = []
    for pid, t in tot.items():
        gp, pts = t.get("gamesPlayed", 0), t.get("points", 0)
        if pts < 14000 or gp < 400:
            continue
        reb, ast = t.get("rebounds", 0), t.get("assists", 0)
        main_team = max(t["teams"], key=t["teams"].get) if t["teams"] else ""
        active = t["last"] >= last_season
        out.append(make_candidate(
            sport="nba", kind="wildcard", key=f"career:{pid}", answer=t["name"], player_id=pid,
            type_="Wild Card · Career Totals",
            context=f"Regular-season career · {t['seasons']} seasons" + (f" · through {label(last_season)}" if active else ""),
            stats=[("GP", f"{int(gp):,}"), ("PTS", f"{int(pts):,}"), ("REB", f"{int(reb):,}"), ("AST", f"{int(ast):,}"),
                   ("PPG", fmt_1(pts / gp)), ("RPG", fmt_1(reb / gp)), ("APG", fmt_1(ast / gp)),
                   ("3PM", f"{int(t.get('threePointFieldGoalsMade', 0)):,}")],
            hints=[f"He's a {t['position'].lower() or 'player'} who made his NBA debut in {t['debut']}.",
                   f"He played the most seasons for the {main_team}." if main_team else "He played for several teams.",
                   f"His initials are {initials(t['name'])}"],
            reveal=f"Career {label(t['debut'] + 1)} to {'present' if active else label(t['last'])}",
            score=pts / 1000 + ast / 800 + reb / 1000,
        ))
    return out


def game_candidates(season: int, p: dict) -> list[dict]:
    data = fetch_json(f"{BASE}/athletes/{p['id']}/gamelog?season={season}",
                      max_age_days=1 if is_current_season(season) else None)
    names = data.get("names", [])
    if not names:
        return []
    idx = {n: i for i, n in enumerate(names)}
    out = []
    for st in data.get("seasonTypes", []):
        playoffs = "Postseason" in st.get("displayName", "")
        if "Regular" not in st.get("displayName", "") and not playoffs:
            continue  # skip play-in / preseason
        for cat in st.get("categories", []):
            for ev in cat.get("events") or []:
                row = ev["stats"]
                try:
                    pts = int(row[idx["points"]]); reb = int(row[idx["totalRebounds"]]); ast = int(row[idx["assists"]])
                except (KeyError, ValueError, IndexError):
                    continue
                if playoffs:
                    notable = pts >= 40 or (pts >= 30 and (reb >= 15 or ast >= 12)) or (pts >= 20 and reb >= 10 and ast >= 10)
                else:
                    notable = (pts >= 50 or (pts >= 40 and (reb >= 15 or ast >= 12)) or (pts >= 30 and reb >= 15 and ast >= 15)
                               or (pts >= 25 and reb >= 25) or ast >= 20)
                if not notable:
                    continue
                meta = data["events"].get(ev["eventId"], {})
                opp = (meta.get("opponent") or {}).get("displayName", "an unknown opponent")
                home = meta.get("atVs") == "vs"
                when = eastern_date(meta["gameDate"]) if meta.get("gameDate") else None
                result = meta.get("gameResult", "")
                score = meta.get("score", "")
                out.append(make_candidate(
                    sport="nba", kind="wildcard" if playoffs else "game",
                    key=f"{'pgame:' if playoffs else ''}{ev['eventId']}:{p['id']}", answer=p["name"], player_id=p["id"],
                    type_="Wild Card · Playoff Game" if playoffs else "Single Game Box Score",
                    context=f"{'Playoffs' if playoffs else 'Regular Season'} · {'Home' if home else 'Road'} game · {label(season)}",
                    stats=[("PTS", pts), ("FG", row[idx["fieldGoalsMade-fieldGoalsAttempted"]]),
                           ("3PT", row[idx["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]]),
                           ("FT", row[idx["freeThrowsMade-freeThrowsAttempted"]]), ("REB", reb), ("AST", ast),
                           ("STL", row[idx["steals"]]), ("BLK", row[idx["blocks"]]), ("MIN", row[idx["minutes"]])],
                    hints=[f"The opponent was the {opp}.", f"He played for the {p['team']}.",
                           f"His initials are {initials(p['name'])}"],
                    reveal=" · ".join(x for x in [pretty_date(when) if when else "",
                                                  f"{'vs.' if home else '@'} {opp}", f"{result} {score}".strip()] if x),
                    score=pts + 0.8 * reb + 0.8 * ast,
                ))
    return out


def mine(seasons: list[int]) -> list[dict]:
    out: list[dict] = []
    for y in seasons:
        try:
            reg = by_athlete(y, 2)
        except Exception as e:  # noqa: BLE001 — a missing season shouldn't kill the run
            log(f"NBA {label(y)}: skipped ({e})")
            continue
        found = season_candidates(y, reg) + rookie_candidates(y, reg)
        try:
            found += playoff_candidates(y, by_athlete(y, 3, limit=30))
        except Exception as e:  # noqa: BLE001
            log(f"NBA {label(y)} playoffs: skipped ({e})")
        for p in reg[:TOP_SCORERS_FOR_GAMELOGS]:
            try:
                found += game_candidates(y, p)
            except Exception as e:  # noqa: BLE001
                log(f"NBA {label(y)} {p['name']} game log: skipped ({e})")
        log(f"NBA {label(y)}: {len(found)} candidates")
        out += found
    if len(seasons) > 5:  # careers need the full history; daily refreshes skip them
        found = career_candidates(max(seasons))
        log(f"NBA careers: {len(found)} candidates")
        out += found
    return out
