"""NFL miner — nflverse open data (weekly player stats CSVs, 1999+)."""
from __future__ import annotations

import csv
import io
from collections import defaultdict

from .common import eastern_today, fetch, fmt_1, fmt_int, initials, is_current_season, log, make_candidate

def current_season() -> int:
    t = eastern_today()
    return t.year if t.month >= 8 else t.year - 1


DEFAULT_SEASONS = list(range(1999, current_season() + 1))


def current_seasons() -> list[int]:
    return [current_season()]
REL = "https://github.com/nflverse/nflverse-data/releases/download"

TEAMS = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams", "LAR": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "OAK": "Oakland Raiders", "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers", "SD": "San Diego Chargers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "STL": "St. Louis Rams", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
}
ROUNDS = ["Wild Card Round", "Divisional Round", "Conference Championship", "Super Bowl"]


def team_name(abbr: str, season: int) -> str:
    if abbr == "WAS":
        return ("Washington Redskins" if season < 2020 else
                "Washington Football Team" if season < 2022 else "Washington Commanders")
    if abbr == "LA" and season < 2016:
        return "St. Louis Rams"
    return TEAMS.get(abbr, abbr)


def i(row: dict, k: str) -> int:
    try:
        return int(float(row.get(k) or 0))
    except ValueError:
        return 0


def weekly(season: int) -> list[dict]:
    url = f"{REL}/stats_player/stats_player_week_{season}.csv"
    body = fetch(url, ext="csv", max_age_days=1 if is_current_season(season) else None)
    return list(csv.DictReader(io.StringIO(body.decode("utf-8"))))


_players: dict | None = None


def bio(pid: str) -> dict:
    global _players
    if _players is None:
        body = fetch(f"{REL}/players/players.csv", ext="csv", max_age_days=30)
        _players = {r["gsis_id"]: r for r in csv.DictReader(io.StringIO(body.decode("utf-8")))}
    return _players.get(pid, {})


def bio_hint(pid: str, position: str) -> str:
    b = bio(pid)
    college = (b.get("college_name") or "").strip()
    rnd, year = b.get("draft_round"), b.get("draft_year")
    pos = {"QB": "quarterback", "RB": "running back", "WR": "wide receiver", "TE": "tight end",
           "FB": "fullback"}.get(position, position or "player")
    draft = (f"was a {'1st' if rnd == '1' else '2nd' if rnd == '2' else '3rd' if rnd == '3' else rnd + 'th'}-round pick in {year}"
             if rnd and year else "went undrafted" if b else "")
    parts = [f"He's a {pos}"]
    if college:
        parts.append(f"who played college ball at {college}")
    if draft:
        parts.append(f"and {draft}" if college else draft)
    return " ".join(parts) + "."


def lines_for(cat: str, t: dict, games: int | None = None) -> list[tuple[str, str]]:
    """Stat cells for a passing / rushing / receiving line. `t` holds summed raw counts."""
    gp = [("GP", games)] if games else []
    if cat == "pass":
        return gp + [("C/ATT", f"{t['completions']}/{t['attempts']}"), ("PASS YDS", fmt_int(t["passing_yards"])),
                     ("PASS TD", t["passing_tds"]), ("INT", t["passing_interceptions"]),
                     ("RUSH YDS", fmt_int(t["rushing_yards"])), ("RUSH TD", t["rushing_tds"])]
    if cat == "rush":
        ypc = t["rushing_yards"] / t["carries"] if t["carries"] else 0
        return gp + [("CAR", t["carries"]), ("RUSH YDS", fmt_int(t["rushing_yards"])), ("YPC", fmt_1(ypc)),
                     ("RUSH TD", t["rushing_tds"]), ("REC", t["receptions"]), ("REC YDS", fmt_int(t["receiving_yards"]))]
    ypr = t["receiving_yards"] / t["receptions"] if t["receptions"] else 0
    return gp + [("REC", t["receptions"]), ("TGT", t["targets"]), ("REC YDS", fmt_int(t["receiving_yards"])),
                 ("YPR", fmt_1(ypr)), ("REC TD", t["receiving_tds"])]


FIELDS = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries",
          "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds"]


def totals(rows: list[dict]) -> dict:
    return {f: sum(i(r, f) for r in rows) for f in FIELDS}


def classify(t: dict, kind: str) -> tuple[str, float] | None:
    """Return (category, notability score) if the line clears the bar for `kind`."""
    py, ptd = t["passing_yards"], t["passing_tds"]
    ry, rtd = t["rushing_yards"], t["rushing_tds"]
    wy, wtd, rec = t["receiving_yards"], t["receiving_tds"], t["receptions"]
    if kind == "pgame":
        if py >= 330 or ptd >= 4 or (py >= 280 and ptd >= 3):
            return "pass", py / 10 + ptd * 6
        if ry >= 130 or rtd >= 3:
            return "rush", ry / 4 + rtd * 6
        if wy >= 140 or wtd >= 3:
            return "rec", wy / 4 + wtd * 6 + rec
    elif kind == "career":
        if py >= 30000:
            return "pass", py / 1500 + ptd / 15
        if ry >= 7500:
            return "rush", ry / 400 + rtd / 5
        if wy >= 8500:
            return "rec", wy / 400 + wtd / 5
    elif kind == "rookie":
        if py >= 3300 or ptd >= 22:
            return "pass", py / 100 + ptd * 1.5
        if ry >= 1000 or rtd >= 10:
            return "rush", ry / 30 + rtd * 1.5
        if wy >= 900 or wtd >= 9:
            return "rec", wy / 30 + wtd * 1.5
    elif kind == "game":
        if py >= 450 or ptd >= 6:
            return "pass", py / 10 + ptd * 6
        if ry >= 210 or (ry >= 150 and rtd >= 4):
            return "rush", ry / 4 + rtd * 6
        if wy >= 220 or (wy >= 150 and wtd >= 4) or rec >= 17:
            return "rec", wy / 4 + wtd * 6 + rec
    elif kind == "season":
        if py >= 4500 or ptd >= 38:
            return "pass", py / 100 + ptd * 1.5
        if ry >= 1500 or rtd >= 16:
            return "rush", ry / 30 + rtd * 1.5
        if wy >= 1450 or rec >= 115 or wtd >= 14:
            return "rec", wy / 30 + wtd * 1.5 + rec / 10
    else:  # postseason run
        if ptd >= 7 or py >= 900:
            return "pass", py / 40 + ptd * 3
        if ry >= 300 or rtd >= 5:
            return "rush", ry / 10 + rtd * 3
        if wy >= 330 or wtd >= 5:
            return "rec", wy / 10 + wtd * 3
    return None


def mine(seasons: list[int]) -> list[dict]:
    out: list[dict] = []
    career_rows: dict[str, list[dict]] = defaultdict(list)
    for y in seasons:
        try:
            rows = weekly(y)
        except Exception as e:  # noqa: BLE001
            log(f"NFL {y}: skipped ({e})")
            continue
        found: list[dict] = []
        post_weeks = sorted({int(r["week"]) for r in rows if r["season_type"] == "POST"})
        round_of = {w: ROUNDS[len(ROUNDS) - len(post_weeks) + k] for k, w in enumerate(post_weeks)} \
            if len(post_weeks) <= len(ROUNDS) else {}

        # ---- single games
        for r in rows:
            t = totals([r])
            post = r["season_type"] == "POST"
            hit = classify(t, "pgame" if post else "game")
            if not hit:
                continue
            cat, score = hit
            name, pid, team, opp = r["player_display_name"], r["player_id"], r["team"], r["opponent_team"]
            home = r["game_id"].rsplit("_", 1)[-1] == team
            week = int(r["week"])
            rnd = round_of.get(week, "Playoffs") if post else None
            if rnd == "Super Bowl":
                ctx, when = f"Super Bowl · {y} season", f"{y} season Super Bowl"
            elif post:
                ctx, when = f"{rnd} · {'Home' if home else 'Road'} game · {y} season", f"{y} {rnd}"
            else:
                ctx, when = f"Regular Season · Week {week} · {'Home' if home else 'Road'} game · {y}", f"{y} Week {week}"
            found.append(make_candidate(
                sport="nfl", kind="wildcard" if post else "game", key=f"{'pgame:' if post else ''}{r['game_id']}:{pid}",
                answer=name, player_id=pid,
                type_=("Wild Card · Super Bowl" if rnd == "Super Bowl" else "Wild Card · Playoff Game") if post
                else "Single Game Box Score", context=ctx, stats=lines_for(cat, t),
                hints=[f"The opponent was the {team_name(opp, y)}.", f"He played for the {team_name(team, y)}.",
                       f"His initials are {initials(name)}"],
                reveal=f"{when} · {'vs.' if home else '@'} {team_name(opp, y)}",
                score=score + (15 if rnd == "Super Bowl" else 6 if post else 0),
            ))

        # ---- seasons and postseason runs
        by_player: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in rows:
            by_player[(r["player_id"], r["season_type"])].append(r)
        for (pid, stype), prow in by_player.items():
            if stype not in ("REG", "POST"):
                continue
            kind = "season" if stype == "REG" else "wildcard"
            t = totals(prow)
            name, pos = prow[0]["player_display_name"], prow[0].get("position", "")
            teams = sorted({r["team"] for r in prow})
            team = team_name(teams[-1], y) if len(teams) == 1 else " / ".join(team_name(x, y) for x in teams)
            if kind == "season" and bio(pid).get("rookie_season") == str(y):
                rk = classify(t, "rookie")
                if rk:
                    found.append(make_candidate(
                        sport="nfl", kind="wildcard", key=f"rookie:{y}:{pid}", answer=name, player_id=pid,
                        type_="Wild Card · Rookie Season", context=f"Rookie Season · {len(prow)} games",
                        stats=lines_for(rk[0], t, games=len(prow)),
                        hints=[bio_hint(pid, pos), f"He played for the {team}.", f"His initials are {initials(name)}"],
                        reveal=f"{y} rookie season · {team}", score=rk[1],
                    ))
            hit = classify(t, kind)
            if not hit:
                continue
            cat, score = hit
            if kind == "season":
                ctx = f"Regular Season · {len(prow)} games"
                reveal = f"{y} · {team}"
            else:
                reached = max(int(r["week"]) for r in prow)
                ctx = f"{y} Postseason · {len(prow)} games"
                reveal = f"{y} Postseason · {team} (reached the {round_of.get(reached, 'playoffs')})"
                score += 10 if round_of.get(reached) == "Super Bowl" else 0
            found.append(make_candidate(
                sport="nfl", kind=kind, key=f"{y}:{pid}", answer=name, player_id=pid,
                type_="Full Season Statline" if kind == "season" else "Wild Card · Postseason Run",
                context=ctx, stats=lines_for(cat, t, games=len(prow)),
                hints=[bio_hint(pid, pos), f"He played for the {team}.", f"His initials are {initials(name)}"],
                reveal=reveal, score=score,
            ))
        log(f"NFL {y}: {len(found)} candidates")
        out += found
        for r in rows:
            if r["season_type"] == "REG":
                career_rows[r["player_id"]].append(r)
    if len(seasons) > 5:  # careers need the full history; daily refreshes skip them
        found = career_candidates(career_rows, max(seasons))
        log(f"NFL careers: {len(found)} candidates")
        out += found
    return out


def career_candidates(career_rows: dict[str, list[dict]], last_season: int) -> list[dict]:
    """Regular-season careers for players who debuted in 1999 or later (fully inside nflverse's data)."""
    out = []
    for pid, prow in career_rows.items():
        b = bio(pid)
        try:
            rookie = int(b.get("rookie_season") or 0)
        except ValueError:
            continue
        if rookie < 1999:
            continue
        t = totals(prow)
        hit = classify(t, "career")
        if not hit:
            continue
        cat, score = hit
        name, pos = prow[-1]["player_display_name"], prow[-1].get("position", "")
        seasons = sorted({int(r["season"]) for r in prow})
        teams: dict[str, int] = defaultdict(int)
        for r in prow:
            teams[team_name(r["team"], int(r["season"]))] += 1
        main = max(teams, key=teams.get)
        active = seasons[-1] >= last_season
        out.append(make_candidate(
            sport="nfl", kind="wildcard", key=f"career:{pid}", answer=name, player_id=pid,
            type_="Wild Card · Career Totals",
            context=f"Regular-season career · {len(seasons)} seasons" + (f" · through {last_season}" if active else ""),
            stats=lines_for(cat, t, games=len(prow)),
            hints=[bio_hint(pid, pos), f"He played the most games for the {main}.", f"His initials are {initials(name)}"],
            reveal=f"Career {seasons[0]}–{'present' if active else seasons[-1]}",
            score=score,
        ))
    return out
