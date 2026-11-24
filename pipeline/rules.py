"""Selection rules: what qualifies for each stage type, with no manual review.

The miners only emit lines that clear the stat thresholds below. `select` then
applies the fame rule to full seasons. Everything that survives is approved and
the daily scheduler picks from it. Tune here, then rerun:

    python3 -m pipeline mine <sport> && python3 -m pipeline select
"""

# ---- Single games: pure stat thresholds -----------------------------------
MLB_GAME_MIN_TOTAL_BASES = 12      # hitters: 12+ total bases (e.g. 3 HR + a single)
MLB_GAME_MIN_STRIKEOUTS = 15       # pitchers: 15+ K, or any no-hitter,
MLB_MADDUX_MIN_STRIKEOUTS = 10     # or a Maddux (shutout in under 100 pitches) with 10+ K
NBA_GAME_MIN_POINTS = 50           # or 40 with 15 reb / 12 ast, 30-15-15, 25-25, 20 ast (see nba.py)
NFL_GAME_MIN_PASS_YARDS = 450      # or 6 pass TD; rush 210 yds; rec 220 yds (see nfl.py)

# ---- Full seasons: the stat line alone ------------------------------------
# A great year qualifies even for an obscure player; the miners' season thresholds
# (e.g. 26+ PPG, 50 HR, 1,500 rush yds) are the whole test.
SEASON_REQUIRES_FAME = False

# ---- Obscurity floor for games and wild cards -------------------------------
# Thresholds alone can surface a journeyman's one big night. To keep puzzles
# gettable, games/wild cards also need the player in the top N by career volume,
# OR at least FLOOR_MIN_STANDOUTS qualifying lines in the pool.
FLOOR_TOP_N = {"nba": 700, "mlb": 3000, "nfl": 1000}
FLOOR_MIN_STANDOUTS = 2
# Career totals clear Hall-of-Fame-level bars already (400 HR, 14,000 pts, 30,000 pass yds...).
FLOOR_EXEMPT_TYPES = {"Wild Card · Career Totals"}

# ---- Wild cards: anything notable ------------------------------------------
# Postseason runs, playoff single games, rookie seasons and career totals all qualify
# on their miner thresholds; the scheduler rotates between the types.
