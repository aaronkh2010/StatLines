"""Copy just the playable files into site/ for static hosting.

pipeline/ (including pool.json, which holds every answer in plain text) is
deliberately left out.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
if SITE.exists():
    shutil.rmtree(SITE)
(SITE / "puzzles").mkdir(parents=True)
for name in ("index.html", "app.js", "players.json"):
    shutil.copy2(ROOT / name, SITE / name)
for f in (ROOT / "puzzles").glob("*.json"):
    shutil.copy2(f, SITE / "puzzles" / f.name)
(SITE / ".nojekyll").write_text("")
if (ROOT / "CNAME").exists():
    shutil.copy2(ROOT / "CNAME", SITE / "CNAME")
print(f"site/: {len(list((SITE / 'puzzles').glob('*.json')))} puzzle files")
