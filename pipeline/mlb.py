"""MLB miner — MLB's official Stats API (statsapi.mlb.com)."""
from __future__ import annotations

from . import rules
from .common import eastern_today, fetch_json, fmt_int, initials, is_current_season, log, make_candidate, pretty_date

def current_season() -> int:
    t = eastern_today()
    return t.year if t.month >= 3 else t.year - 1


DEFAULT_SEASONS = list(range(1995, current_season() + 1))


def current_seasons() -> list[int]:
    return [current_season()]
BASE = "https://statsapi.mlb.com/api/v1"
HITTER_GAMELOGS = 60
PITCHER_GAMELOGS = 30


def _age(season: int):
    return 1 if is_current_season(season) else None


def season_splits(season: int, group: str, *, postseason: bool = False) -> list[dict]:
    pool = "all" if postseason else "qualified"
    sort = "homeRuns" if group == "hitting" else ("inningsPitched" if postseason else "strikeOuts")
    url = (f"{BASE}/stats?stats=season&group={group}&season={season}&sportId=1&playerPool={pool}"
           f"&limit=400&sortStat={sort}&order=desc" + ("&gameType=P" if postseason else ""))
    return fetch_json(url, max_age_days=_age(season))["stats"][0]["splits"]


def person(pid) -> dict:
    data = fetch_json(f"{BASE}/people/{pid}")
    return (data.get("people") or [{}])[0]


def bio_hint(pid, fallback_pos: str) -> str:
    p = person(pid)
    pos = (p.get("primaryPosition") or {}).get("name", fallback_pos).lower()
    debut = (p.get("mlbDebutDate") or "")[:4]
    country = p.get("birthCountry")
    bits = [f"He's a {pos}"]
    if debut:
        bits.append(f"who debuted in {debut}")
    if country:
        bits.append(f"and was born in {country}" if debut else f"born in {country}")
    return " ".join(bits) + "."


def num(x, default: float = 0.0) -> float:
    """Stats API sends rates as strings and uses '-.--' / '.---' for undefined."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def hitter_season(season: int, sp: dict, hr_rank: int) -> dict | None:
    s = sp["stat"]
    ops = num(s.get("ops", 0), 0); hr = s.get("homeRuns", 0); avg = num(s.get("avg", 0), 0)
    sb = s.get("stolenBases", 0)
    if not (ops >= 1.000 or hr >= 50 or avg >= .350 or (hr >= 40 and sb >= 30) or hr_rank == 1):
        return None
    pl, team = sp["player"], (sp.get("team") or {}).get("name", "")
    hint1 = "He led the majors in home runs that season." if hr_rank == 1 else bio_hint(pl["id"], "position player")
    return make_candidate(
        sport="mlb", kind="season", key=f"{season}:H:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
        type_="Full Season Statline", context=f"Regular Season · {s.get('gamesPlayed')} games",
        stats=[("AVG", s["avg"]), ("HR", hr), ("RBI", s.get("rbi")), ("R", s.get("runs")), ("SB", sb),
               ("OBP", s.get("obp")), ("SLG", s.get("slg")), ("OPS", s.get("ops"))],
        hints=[hint1, f"He played for the {team}." if team else "He was traded during that season.",
               f"His initials are {initials(pl['fullName'])}"],
        reveal=f"{season} · {team}".rstrip(" ·"),
        score=ops * 40 + hr * 0.4 + sb * 0.1 + (5 if hr_rank == 1 else 0),
    )


def pitcher_season(season: int, sp: dict, k_rank: int) -> dict | None:
    s = sp["stat"]
    era = num(s.get("era", 99), 99); k = s.get("strikeOuts", 0); w = s.get("wins", 0)
    if not (era <= 2.10 or k >= 300 or w >= 23 or k_rank == 1):
        return None
    pl, team = sp["player"], (sp.get("team") or {}).get("name", "")
    hint1 = "He led the majors in strikeouts that season." if k_rank == 1 else bio_hint(pl["id"], "pitcher")
    return make_candidate(
        sport="mlb", kind="season", key=f"{season}:P:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
        type_="Full Season Statline", context=f"Regular Season · {s.get('gamesStarted')} starts",
        stats=[("W-L", f"{w}-{s.get('losses')}"), ("ERA", s.get("era")), ("IP", s.get("inningsPitched")),
               ("K", k), ("BB", s.get("baseOnBalls")), ("WHIP", s.get("whip"))],
        hints=[hint1, f"He pitched for the {team}." if team else "He was traded during that season.",
               f"His initials are {initials(pl['fullName'])}"],
        reveal=f"{season} · {team}".rstrip(" ·"),
        score=(4.0 - era) * 12 + k * 0.08 + w * 0.6 + (5 if k_rank == 1 else 0),
    )


def postseason(season: int) -> list[dict]:
    out = []
    for sp in season_splits(season, "hitting", postseason=True):
        s, pl = sp["stat"], sp["player"]
        pa = s.get("plateAppearances", 0); hr = s.get("homeRuns", 0); ops = num(s.get("ops", 0), 0)
        if pa < 25 or not (hr >= 5 or (ops >= 1.150 and pa >= 30)):
            continue
        team = (sp.get("team") or {}).get("name", "")
        out.append(make_candidate(
            sport="mlb", kind="wildcard", key=f"{season}:H:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
            type_="Wild Card · Postseason Run", context=f"{season} Postseason · {s.get('gamesPlayed')} games",
            stats=[("AVG", s["avg"]), ("HR", hr), ("RBI", s.get("rbi")), ("H", s.get("hits")),
                   ("OBP", s.get("obp")), ("SLG", s.get("slg")), ("OPS", s.get("ops"))],
            hints=[bio_hint(pl["id"], "position player"), f"He played for the {team}.",
                   f"His initials are {initials(pl['fullName'])}"],
            reveal=f"{season} Postseason · {team}",
            score=ops * 25 + hr * 2.5,
        ))
    for sp in season_splits(season, "pitching", postseason=True):
        s, pl = sp["stat"], sp["player"]
        ip = num(s.get("inningsPitched", 0), 0); era = num(s.get("era", 99), 99); w = s.get("wins", 0)
        if ip < 18 or not (era <= 1.80 or (w >= 3 and era <= 2.75)):
            continue
        team = (sp.get("team") or {}).get("name", "")
        out.append(make_candidate(
            sport="mlb", kind="wildcard", key=f"{season}:P:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
            type_="Wild Card · Postseason Run", context=f"{season} Postseason · {s.get('gamesPlayed')} appearances",
            stats=[("W-L", f"{w}-{s.get('losses')}"), ("ERA", s.get("era")), ("IP", s.get("inningsPitched")),
                   ("K", s.get("strikeOuts")), ("WHIP", s.get("whip")), ("SV", s.get("saves", 0))],
            hints=[bio_hint(pl["id"], "pitcher"), f"He pitched for the {team}.",
                   f"His initials are {initials(pl['fullName'])}"],
            reveal=f"{season} Postseason · {team}",
            score=(3.5 - era) * 10 + ip * 0.4 + w * 2,
        ))
    return out


def game_logs(pid, season: int, group: str, postseason: bool = False) -> list[dict]:
    data = fetch_json(f"{BASE}/people/{pid}/stats?stats=gameLog&group={group}&season={season}"
                      + ("&gameType=P" if postseason else ""),
                      max_age_days=_age(season))
    stats = data.get("stats") or []
    return stats[0]["splits"] if stats else []


def hitter_games(season: int, pl: dict) -> list[dict]:
    out = []
    for g in game_logs(pl["id"], season, "hitting"):
        s = g["stat"]
        hr, h, rbi = s.get("homeRuns", 0), s.get("hits", 0), s.get("rbi", 0)
        tb = s.get("totalBases", h + s.get("doubles", 0) + 2 * s.get("triples", 0) + 3 * hr)
        if tb < rules.MLB_GAME_MIN_TOTAL_BASES:
            continue
        opp, team, home = g["opponent"]["name"], g["team"]["name"], g.get("isHome")
        from datetime import datetime
        when = pretty_date(datetime.fromisoformat(g["date"]))
        out.append(make_candidate(
            sport="mlb", kind="game", key=f"{g['game']['gamePk']}:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
            type_="Single Game Box Score",
            context=f"Regular Season · {'Home' if home else 'Road'} game · {season}",
            stats=[("AB", s.get("atBats")), ("H", h), ("HR", hr), ("2B", s.get("doubles")), ("TB", tb), ("RBI", rbi),
                   ("R", s.get("runs")), ("BB", s.get("baseOnBalls"))],
            hints=[f"The opponent was the {opp}.", f"He played for the {team}.",
                   f"His initials are {initials(pl['fullName'])}"],
            reveal=f"{when} · {'vs.' if home else '@'} {opp}",
            score=tb * 3 + rbi * 1.5,
        ))
    return out


def pitcher_games(season: int, pl: dict) -> list[dict]:
    out = []
    for g in game_logs(pl["id"], season, "pitching"):
        s = g["stat"]
        ip = num(s.get("inningsPitched", 0), 0); k = s.get("strikeOuts", 0); h = s.get("hits", 0)
        bb = s.get("baseOnBalls", 0); hbp = s.get("hitBatsmen", s.get("hitByPitch", 0))
        no_hitter = ip >= 9 and h == 0
        perfect = no_hitter and bb == 0 and hbp == 0 and s.get("runs", 0) == 0
        pitches = s.get("numberOfPitches") or 999
        shutout = s.get("shutouts", 0) >= 1 or (s.get("completeGames", 0) >= 1 and s.get("runs", 0) == 0)
        maddux = shutout and pitches < 100 and k >= rules.MLB_MADDUX_MIN_STRIKEOUTS
        if not (k >= rules.MLB_GAME_MIN_STRIKEOUTS or no_hitter or maddux):
            continue
        opp, team, home = g["opponent"]["name"], g["team"]["name"], g.get("isHome")
        from datetime import datetime
        when = pretty_date(datetime.fromisoformat(g["date"]))
        tag = "Perfect game" if perfect else ("No-hitter" if no_hitter else "Maddux (shutout under 100 pitches)" if maddux else "")
        out.append(make_candidate(
            sport="mlb", kind="game", key=f"{g['game']['gamePk']}:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
            type_="Single Game Box Score",
            context=f"Regular Season · {'Home' if home else 'Road'} start · {season}",
            stats=[("IP", s.get("inningsPitched")), ("H", h), ("R", s.get("runs")), ("ER", s.get("earnedRuns")),
                   ("BB", bb), ("K", k), ("PITCHES", s.get("numberOfPitches", "—"))],
            hints=[f"The opponent was the {opp}.", f"He pitched for the {team}.",
                   f"His initials are {initials(pl['fullName'])}"],
            reveal=" · ".join(x for x in [when, f"{'vs.' if home else '@'} {opp}", tag] if x),
            score=k * 3 + (25 if perfect else 15 if no_hitter else 8 if maddux else 0),
        ))
    return out


ROUND = {"F": "Wild Card Series", "D": "Division Series", "L": "League Championship Series", "W": "World Series"}


def rookies(season: int) -> list[dict]:
    out = []
    url = (f"{BASE}/stats?stats=season&group=hitting&season={season}&sportId=1&playerPool=qualified_rookies"
           f"&limit=50&sortStat=ops&order=desc")
    for sp in fetch_json(url, max_age_days=_age(season))["stats"][0]["splits"]:
        s, pl = sp["stat"], sp["player"]
        ops, hr = num(s.get("ops")), s.get("homeRuns", 0)
        if not (ops >= .850 or hr >= 25 or (s.get("stolenBases", 0) >= 35 and num(s.get("avg")) >= .290)):
            continue
        team = (sp.get("team") or {}).get("name", "")
        out.append(make_candidate(
            sport="mlb", kind="wildcard", key=f"rookie:{season}:H:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
            type_="Wild Card · Rookie Season", context=f"Rookie Season · {s.get('gamesPlayed')} games",
            stats=[("AVG", s["avg"]), ("HR", hr), ("RBI", s.get("rbi")), ("R", s.get("runs")),
                   ("SB", s.get("stolenBases")), ("OBP", s.get("obp")), ("SLG", s.get("slg")), ("OPS", s.get("ops"))],
            hints=[bio_hint(pl["id"], "position player"), f"He played for the {team}." if team else "He was traded that season.",
                   f"His initials are {initials(pl['fullName'])}"],
            reveal=f"{season} rookie season · {team}".rstrip(" ·"),
            score=ops * 40 + hr * 0.4,
        ))
    url = (f"{BASE}/stats?stats=season&group=pitching&season={season}&sportId=1&playerPool=qualified_rookies"
           f"&limit=50&sortStat=era&order=asc")
    for sp in fetch_json(url, max_age_days=_age(season))["stats"][0]["splits"]:
        s, pl = sp["stat"], sp["player"]
        era, k = num(s.get("era"), 99), s.get("strikeOuts", 0)
        if not (era <= 3.00 or k >= 180):
            continue
        team = (sp.get("team") or {}).get("name", "")
        out.append(make_candidate(
            sport="mlb", kind="wildcard", key=f"rookie:{season}:P:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
            type_="Wild Card · Rookie Season", context=f"Rookie Season · {s.get('gamesStarted')} starts",
            stats=[("W-L", f"{s.get('wins')}-{s.get('losses')}"), ("ERA", s.get("era")), ("IP", s.get("inningsPitched")),
                   ("K", k), ("BB", s.get("baseOnBalls")), ("WHIP", s.get("whip"))],
            hints=[bio_hint(pl["id"], "pitcher"), f"He pitched for the {team}." if team else "He was traded that season.",
                   f"His initials are {initials(pl['fullName'])}"],
            reveal=f"{season} rookie season · {team}".rstrip(" ·"),
            score=(4.0 - era) * 12 + k * 0.08,
        ))
    return out


def postseason_games(season: int) -> list[dict]:
    """Big single games from that October, searched for everyone with a real postseason workload."""
    out = []
    for group in ("hitting", "pitching"):
        for sp in season_splits(season, group, postseason=True):
            s, pl = sp["stat"], sp["player"]
            if (group == "hitting" and s.get("plateAppearances", 0) < 15) or \
               (group == "pitching" and num(s.get("inningsPitched")) < 10):
                continue
            for g in game_logs(pl["id"], season, group, postseason=True):
                st = g["stat"]
                if group == "hitting":
                    hr, h, rbi = st.get("homeRuns", 0), st.get("hits", 0), st.get("rbi", 0)
                    if not (hr >= 2 or (h >= 4) or rbi >= 6):
                        continue
                    stats = [("AB", st.get("atBats")), ("H", h), ("HR", hr), ("2B", st.get("doubles")), ("RBI", rbi),
                             ("R", st.get("runs")), ("BB", st.get("baseOnBalls"))]
                    score = hr * 9 + h * 4 + rbi * 2.5
                else:
                    ip, k, h, r = num(st.get("inningsPitched")), st.get("strikeOuts", 0), st.get("hits", 0), st.get("runs", 0)
                    if not (k >= 11 or (ip >= 9 and r == 0) or (ip >= 8 and h <= 2)):
                        continue
                    stats = [("IP", st.get("inningsPitched")), ("H", h), ("R", r), ("ER", st.get("earnedRuns")),
                             ("BB", st.get("baseOnBalls")), ("K", k), ("PITCHES", st.get("numberOfPitches", "—"))]
                    score = k * 3 + (15 if ip >= 9 and r == 0 else 0)
                rnd = ROUND.get(g.get("gameType", ""), "Postseason")
                opp, team, home = g["opponent"]["name"], g["team"]["name"], g.get("isHome")
                from datetime import datetime
                when = pretty_date(datetime.fromisoformat(g["date"]))
                out.append(make_candidate(
                    sport="mlb", kind="wildcard", key=f"pgame:{g['game']['gamePk']}:{pl['id']}", answer=pl["fullName"],
                    player_id=pl["id"], type_="Wild Card · Postseason Game",
                    context=f"{season} {rnd} · {'Home' if home else 'Road'} game",
                    stats=stats,
                    hints=[f"The opponent was the {opp}.", f"He {'played' if group == 'hitting' else 'pitched'} for the {team}.",
                           f"His initials are {initials(pl['fullName'])}"],
                    reveal=f"{when} · {season} {rnd} · {'vs.' if home else '@'} {opp}",
                    score=score + (10 if rnd == "World Series" else 0),
                ))
    return out


def careers() -> list[dict]:
    out = []
    for group, sort in (("hitting", "homeRuns"), ("hitting", "hits"), ("hitting", "stolenBases"),
                        ("pitching", "wins"), ("pitching", "strikeOuts"), ("pitching", "saves")):
        url = (f"{BASE}/stats?stats=career&group={group}&sportId=1&playerPool=all&limit=120"
               f"&sortStat={sort}&order=desc")
        for sp in fetch_json(url, max_age_days=30)["stats"][0]["splits"]:
            s, pl = sp["stat"], sp["player"]
            if group == "hitting":
                hr, h, sb = s.get("homeRuns", 0), s.get("hits", 0), s.get("stolenBases", 0)
                if not (hr >= 400 or h >= 2700 or sb >= 550):
                    continue
                stats = [("G", f"{s.get('gamesPlayed', 0):,}"), ("H", f"{h:,}"), ("HR", hr), ("RBI", f"{s.get('rbi', 0):,}"),
                         ("SB", sb), ("AVG", s.get("avg")), ("OBP", s.get("obp")), ("OPS", s.get("ops"))]
                score, key, pos = hr / 20 + h / 150 + sb / 60, "H", "position player"
            else:
                w, k, sv = s.get("wins", 0), s.get("strikeOuts", 0), s.get("saves", 0)
                if not (w >= 230 or k >= 2800 or sv >= 400):
                    continue
                stats = [("W-L", f"{w}-{s.get('losses')}"), ("ERA", s.get("era")), ("IP", s.get("inningsPitched")),
                         ("K", f"{k:,}"), ("SV", sv), ("WHIP", s.get("whip"))]
                score, key, pos = w / 12 + k / 150 + sv / 25, "P", "pitcher"
            bio = person(pl["id"])
            debut, last = (bio.get("mlbDebutDate") or "")[:4], (bio.get("lastPlayedDate") or "")[:4]
            out.append(make_candidate(
                sport="mlb", kind="wildcard", key=f"career:{key}:{pl['id']}", answer=pl["fullName"], player_id=pl["id"],
                type_="Wild Card · Career Totals", context="Regular-season career totals",
                stats=stats,
                hints=[bio_hint(pl["id"], pos),
                       "He's still active." if bio.get("active") else f"His last MLB season was {last}.",
                       f"His initials are {initials(pl['fullName'])}"],
                reveal=f"Career {debut}–{'present' if bio.get('active') else last}" if debut else "Career totals",
                score=score,
            ))
    seen, uniq = set(), []
    for c in out:
        if c["id"] not in seen:
            seen.add(c["id"]); uniq.append(c)
    return uniq


def mine(seasons: list[int]) -> list[dict]:
    out: list[dict] = []
    for y in seasons:
        found: list[dict] = []
        try:
            hitters = season_splits(y, "hitting")
            pitchers = season_splits(y, "pitching")
        except Exception as e:  # noqa: BLE001
            log(f"MLB {y}: skipped ({e})")
            continue
        for rank, sp in enumerate(hitters, 1):
            c = hitter_season(y, sp, rank)
            if c:
                found.append(c)
        for rank, sp in enumerate(pitchers, 1):
            c = pitcher_season(y, sp, rank)
            if c:
                found.append(c)
        for extra in (postseason, postseason_games, rookies):
            try:
                found += extra(y)
            except Exception as e:  # noqa: BLE001
                log(f"MLB {y} {extra.__name__}: skipped ({e})")
        by_ops = sorted(hitters, key=lambda sp: -float(sp["stat"].get("ops", 0) or 0))
        targets = {sp["player"]["id"]: sp["player"] for sp in by_ops[:HITTER_GAMELOGS] + hitters[:10]}
        for pl in targets.values():
            try:
                found += hitter_games(y, pl)
            except Exception as e:  # noqa: BLE001
                log(f"MLB {y} {pl['fullName']} game log: skipped ({e})")
        for sp in pitchers[:PITCHER_GAMELOGS]:
            try:
                found += pitcher_games(y, sp["player"])
            except Exception as e:  # noqa: BLE001
                log(f"MLB {y} {sp['player']['fullName']} game log: skipped ({e})")
        log(f"MLB {y}: {len(found)} candidates")
        out += found
    if len(seasons) <= 5:  # careers only on full mines
        return out
    try:
        found = careers()
        log(f"MLB careers: {len(found)} candidates")
        out += found
    except Exception as e:  # noqa: BLE001
        log(f"MLB careers: skipped ({e})")
    return out
