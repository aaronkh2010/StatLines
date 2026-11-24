# StatLines

Daily sports stat-deduction game: 3 sports × 5 stages, 3 strikes per sport, win the day with 12/15.

## Play locally

```bash
python3 -m http.server 8000
```

Then open http://localhost:8000. Opening `index.html` directly from disk won't work, because browsers block `fetch()` on `file://` pages.

## Layout

| Path | What it is |
|---|---|
| `index.html`, `app.js` | The game (Tailwind via CDN, vanilla JS) |
| `puzzles/<date>.json` | One published day. Answers/hints are in an obfuscated `secret` field |
| `puzzles/index.json` | List of published dates; the app plays today's, or the latest earlier one |
| `players.json` | Autocomplete names (base list + every mined name, so answers don't stand out) |
| `pipeline/` | Content pipeline (Python 3.9+, standard library only) |
| `pipeline/data/pool.json` | Every candidate puzzle and its review status. **Commit this file**: it's your editorial history |
| `pipeline/data/base_players.json` | Hand-curated autocomplete names |
| `pipeline/.cache/` | Cached API responses (safe to delete) |

## How each day is picked (automatic)

A GitHub Actions job (`.github/workflows/daily.yml`) runs every morning at 07:00 UTC:

1. `python3 -m pipeline daily` refreshes current-season stats, applies the rules and publishes today's and tomorrow's puzzles.
2. It commits the new day to the repo and deploys the site to GitHub Pages.

Use "Run workflow" on the Actions tab to publish by hand.

**Rules** (all in `pipeline/rules.py`):

| Stage | Qualifies when |
|---|---|
| Single game (stages 1-2) | It clears a stat threshold. MLB hitters: 12+ total bases. MLB pitchers: 15+ K, a no-hitter, or a 10+ K Maddux (shutout under 100 pitches). NBA: 50+ pts, 40 with 15 reb or 12 ast, 30-15-15, 25-25 or 20 ast. NFL: 450 pass yds or 6 pass TD, 210 rush yds, 220 rec yds or 17 catches |
| Full season (stages 3-4) | A great year by the stat line alone (e.g. 26+ PPG, 50 HR, 1,500 rush yds), even for an obscure player |
| Wild card (stage 5) | Any of: postseason run, playoff single game, rookie season, career totals. The scheduler rotates the type |

Single games and wild cards (except career totals) skip truly obscure players: outside the top 700 NBA / 3,000 MLB / 1,000 NFL by career volume, with fewer than 2 standout lines in the pool. A player can't repeat in a sport within 14 days, and picks lean toward bigger performances.

### Running it by hand

```bash
python3 -m pipeline mine nba            # full history (also: mlb, nfl)
python3 -m pipeline select              # apply rules.py to every candidate
python3 -m pipeline status              # counts + days of runway
python3 -m pipeline schedule --days 7   # publish ahead (the daily job does 2 days)
python3 -m pipeline review --sport nba  # optional: hand-review; your decisions override the rules
```

The public site only serves `index.html`, `app.js`, `players.json` and `puzzles/` (see `tools/build_site.py`). The repo itself contains `pipeline/data/pool.json` with every candidate answer, so a public repo is readable by anyone who goes looking.

## Data sources

| Sport | Source | Notes |
|---|---|---|
| NBA | ESPN's public JSON API (`site.web.api.espn.com`) | Undocumented. stats.nba.com blocks scripted requests |
| MLB | MLB Stats API (`statsapi.mlb.com`) | Official, free. Its terms allow individual, non-commercial use |
| NFL | [nflverse](https://github.com/nflverse/nflverse-data) weekly player stats | Open data, 1999+ only |

If StatLines ever makes money, switch to a licensed feed (e.g. Sportradar) before launch.

## Known limits

- NFL data starts in 1999, so pre-1999 legends (Rice's prime, Sanders, Marino) only appear in hand-written puzzles. NBA and NFL career totals only cover players who debuted in 1999 or later, so every career shown is complete. MLB careers cover all eras.
- MLB single games are only searched for each season's top hitters/strikeout pitchers, so a random journeyman's no-hitter will be missed.
- The answer obfuscation stops casual peeking, not a determined cheater; real protection needs a server that checks guesses.
