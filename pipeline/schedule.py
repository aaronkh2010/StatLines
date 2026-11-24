"""Assign approved candidates to dates and publish puzzles/<date>.json."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

from .common import (BASE_PLAYERS_PATH, PLAYERS_OUT, PUZZLE_DIR, SPORTS, STAGE_PLAN, encode_secret, load_pool, lock_answer,
                     log, normalize, save_pool)


def stage_payload(c: dict) -> dict:
    return {
        "type": c["type"],
        "context": c["context"],
        "stats": c["stats"],
        "hints": encode_secret(c["hints"]),  # hints only; light obfuscation
        "lock": lock_answer(c["answer"], c["aliases"], c["reveal"]),
    }


def previous_answers(pool: dict, day: date) -> dict | None:
    """Yesterday's answers in plain text, shipped in today's file so a struck-out
    stage gets its answer the next day."""
    prev = (day - timedelta(days=1)).isoformat()
    chosen = [c for c in pool.values() if c.get("scheduled_for") == prev]
    if not chosen:
        return None
    out = {"date": prev}
    for s in SPORTS:
        stages = sorted((c for c in chosen if c["sport"] == s), key=lambda c: c.get("stage", 0))
        out[s] = [{"answer": c["answer"], "reveal": c["reveal"]} for c in stages]
    return out


def write_day(pool: dict, day: date) -> None:
    """(Re)write puzzles/<day>.json from the pool's assignments for that day."""
    picks = {s: sorted((c for c in pool.values() if c.get("scheduled_for") == day.isoformat() and c["sport"] == s),
                       key=lambda c: c.get("stage", 0)) for s in SPORTS}
    doc = {"date": day.isoformat(), **{s: [stage_payload(c) for c in picks[s]] for s in SPORTS}}
    prev = previous_answers(pool, day)
    if prev:
        doc["previous"] = prev
    (PUZZLE_DIR / f"{day.isoformat()}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))


def last_used(pool: dict, sport: str, day: date) -> dict[str, int]:
    """normalized player name -> days between `day` and their nearest scheduled use."""
    out: dict[str, int] = {}
    for c in pool.values():
        if c["sport"] != sport or not c.get("scheduled_for"):
            continue
        gap = abs((date.fromisoformat(c["scheduled_for"]) - day).days)
        k = normalize(c["answer"])
        out[k] = min(out.get(k, gap), gap)
    return out


def wild_type(c: dict) -> str:
    t = c["type"].split("·")[-1].strip()
    return "Playoff Game" if t in ("Super Bowl", "Postseason Game") else t


# Fill the scarcest slot first so common slots can't starve it.
PICK_ORDER = ("wildcard", "season", "game")


def pick_sport(pool: dict, sport: str, day: date, cooldown: int) -> list[dict] | str:
    """Return 5 candidates in stage order, or an error string describing the shortfall."""
    rng = random.Random(f"statlines:{day.isoformat()}:{sport}")
    gaps = last_used(pool, sport, day)
    taken: set[str] = set()
    by_kind: dict[str, list[dict]] = {}
    for kind in PICK_ORDER:
        need = STAGE_PLAN.count(kind)
        picks: list[dict] = []
        for _ in range(need):
            options = [c for c in pool.values()
                       if c["sport"] == sport and c["kind"] == kind and c["status"] == "approved"
                       and gaps.get(normalize(c["answer"]), 10**6) >= cooldown
                       and normalize(c["answer"]) not in taken]
            if not options:
                return (f"{sport.upper()} needs another approved '{kind}' candidate "
                        f"(no-repeat window of {cooldown} days excludes recent players)")
            if kind == "wildcard":
                # Rotate wild card types (playoff run, playoff game, rookie season, career...) so no
                # single type crowds out the rest; scores aren't comparable across types anyway.
                types = sorted({wild_type(c) for c in options})
                chosen = rng.choice(types)
                options = [c for c in options if wild_type(c) == chosen]
            # Lean toward notable items (score rank) and players not seen lately.
            options.sort(key=lambda c: -c["score"])
            weights = [(1.0 / (i + 3)) * min(1.0, gaps.get(normalize(c["answer"]), 90) / 90)
                       for i, c in enumerate(options)]
            pick = rng.choices(options, weights=weights, k=1)[0]
            picks.append(pick)
            taken.add(normalize(pick["answer"]))
        # Within a pair of same-kind stages, the more famous one goes first.
        by_kind[kind] = sorted(picks, key=lambda c: -c["score"])
    return [by_kind[k].pop(0) for k in STAGE_PLAN]


def write_index() -> list[str]:
    dates = sorted(p.stem for p in PUZZLE_DIR.glob("????-??-??.json"))
    (PUZZLE_DIR / "index.json").write_text(json.dumps({"dates": dates}, indent=1))
    return dates


def write_players(pool: dict | None = None) -> None:
    """Autocomplete list per sport, most famous first.

    Names = full-league roster (pipeline/data/roster_<sport>.json, from
    `players --refresh`) + curated base list + every mined name of any status.
    Answers get no special boost, so nothing in the list or its order gives
    them away.
    """
    from . import roster
    pool = pool if pool is not None else load_pool()
    base = json.loads(BASE_PLAYERS_PATH.read_text()) if BASE_PLAYERS_PATH.exists() else {}
    out = {}
    for s in SPORTS:
        weight: dict[str, float] = {}
        display: dict[str, str] = {}

        def add(name: str, w: float) -> None:
            k = normalize(name)
            if not k:
                return
            display.setdefault(k, name)
            weight[k] = max(weight.get(k, 0.0), w)

        for name, w in roster.load(s).items():
            add(name, w)
        for c in pool.values():
            if c["sport"] == s:
                add(c["answer"], 0.0)
        for name in base.get(s, []):
            add(name, 1000.0)  # curated icons always rank first
        out[s] = [display[k] for k in sorted(display, key=lambda k: (-weight[k], display[k].lower()))]
    PLAYERS_OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    log("players.json: " + ", ".join(f"{s.upper()} {len(out[s]):,}" for s in SPORTS) + " names")


def run(start: date, days: int, cooldown: int, force: bool) -> None:
    pool = load_pool()
    PUZZLE_DIR.mkdir(exist_ok=True)
    written = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        path = PUZZLE_DIR / f"{day.isoformat()}.json"
        if path.exists() and not force:
            log(f"{day}: already published, skipping (use --force to redo)")
            continue
        if not force and any(c.get("scheduled_for") == day.isoformat() for c in pool.values()):
            write_day(pool, day)  # picked earlier but not yet published
            written.append(day.isoformat())
            log(f"{day}: published earlier picks")
            continue
        if force:
            # Release whatever was previously assigned to this date.
            for c in pool.values():
                if c.get("scheduled_for") == day.isoformat():
                    c["status"], c["scheduled_for"] = "approved", None

        picks = {}
        for sport in SPORTS:
            result = pick_sport(pool, sport, day, cooldown)
            if isinstance(result, str):
                log(f"{day}: STOPPED — {result}. Mine/review more, then rerun.")
                save_pool(pool)
                _finish(pool, written)
                return
            picks[sport] = result

        for sport, chosen in picks.items():
            for stage_no, c in enumerate(chosen):
                c["status"], c["scheduled_for"], c["stage"] = "scheduled", day.isoformat(), stage_no
        write_day(pool, day)
        written.append(day.isoformat())
        log(f"{day}: " + " | ".join(f"{s.upper()}: " + ", ".join(c["answer"] for c in picks[s]) for s in SPORTS))
        save_pool(pool)
    _finish(pool, written)


def _finish(pool: dict, written: list[str]) -> None:
    write_players(pool)
    dates = write_index()
    log(f"Published {len(written)} new day(s). puzzles/ now covers {dates[0] if dates else '—'} → "
        f"{dates[-1] if dates else '—'}.")
