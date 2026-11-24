"""Shared helpers: HTTP with on-disk cache, candidate pool storage, text helpers."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # project root (index.html lives here)
PIPELINE = Path(__file__).resolve().parent
DATA_DIR = PIPELINE / "data"
CACHE_DIR = PIPELINE / ".cache"
POOL_PATH = DATA_DIR / "pool.json"
BASE_PLAYERS_PATH = DATA_DIR / "base_players.json"
PUZZLE_DIR = ROOT / "puzzles"
PLAYERS_OUT = ROOT / "players.json"

SPORTS = ("nba", "mlb", "nfl")
KINDS = ("game", "season", "wildcard")
# The five stages of a sport, in order.
STAGE_PLAN = ("game", "game", "season", "season", "wildcard")

USER_AGENT = "StatLines-pipeline/0.1"
_last_request = 0.0


# ---------------------------------------------------------------- HTTP

def _cache_path(url: str, ext: str) -> Path:
    return CACHE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()}.{ext}"


def fetch(url: str, *, ext: str = "json", max_age_days: float | None = None, delay: float = 0.25) -> bytes:
    """GET a URL with a polite delay, retries, and an on-disk cache.

    Cached responses are reused forever unless max_age_days is set (use it for
    the current season, whose numbers still change).
    """
    global _last_request
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url, ext)
    if path.exists():
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if max_age_days is None or age_days < max_age_days:
            return path.read_bytes()

    for attempt in range(4):
        wait = delay - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
            path.write_bytes(body)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url}: {err}")


def fetch_json(url: str, **kw) -> dict:
    return json.loads(fetch(url, ext="json", **kw))


def is_current_season(year: int) -> bool:
    """True if `year` may still be in progress (so cached data could be stale)."""
    return year >= datetime.now().year


# ---------------------------------------------------------------- pool

# The pool holds every answer, so the repo only carries an encrypted copy
# (pool.json.enc). The key comes from $STATLINES_POOL_KEY (GitHub secret) or
# pipeline/data/.pool_key (local, gitignored). pool.json itself is gitignored.
POOL_ENC_PATH = DATA_DIR / "pool.json.enc"
POOL_KEY_PATH = DATA_DIR / ".pool_key"


def _pool_key() -> bytes:
    import os
    k = os.environ.get("STATLINES_POOL_KEY") or (POOL_KEY_PATH.read_text().strip() if POOL_KEY_PATH.exists() else "")
    if not k:
        raise SystemExit("No pool key: set STATLINES_POOL_KEY or create pipeline/data/.pool_key")
    return hashlib.sha256(k.encode()).digest()


def _seal(data: bytes) -> bytes:
    import hmac, os
    key = _pool_key()
    nonce = os.urandom(16)
    enc_key, mac_key = hmac.new(key, b"enc" + nonce, hashlib.sha256).digest(), hmac.new(key, b"mac", hashlib.sha256).digest()
    body = _keystream_xor(enc_key, data)
    tag = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + body)


def _open(blob: bytes) -> bytes:
    import hmac
    raw = base64.b64decode(blob)
    nonce, tag, body = raw[:16], raw[16:48], raw[48:]
    key = _pool_key()
    mac_key = hmac.new(key, b"mac", hashlib.sha256).digest()
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + body, hashlib.sha256).digest()):
        raise SystemExit("pool.json.enc: wrong key or corrupted file")
    return _keystream_xor(hmac.new(key, b"enc" + nonce, hashlib.sha256).digest(), body)


def load_pool() -> dict:
    if POOL_PATH.exists() and (not POOL_ENC_PATH.exists() or POOL_PATH.stat().st_mtime >= POOL_ENC_PATH.stat().st_mtime):
        return json.loads(POOL_PATH.read_text())
    if POOL_ENC_PATH.exists():
        return json.loads(_open(POOL_ENC_PATH.read_bytes()))
    return {}


def save_pool(pool: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(pool, indent=1, ensure_ascii=False, sort_keys=True)
    tmp = POOL_PATH.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(POOL_PATH)
    POOL_ENC_PATH.write_bytes(_seal(text.encode("utf-8")))


def add_candidates(pool: dict, candidates: list[dict]) -> int:
    """Insert new candidates; never overwrite one that's already been reviewed."""
    added = 0
    for c in candidates:
        existing = pool.get(c["id"])
        if existing is None:
            pool[c["id"]] = c
            added += 1
        elif existing["status"] == "pending":
            # refresh stats/hints for still-unreviewed items (e.g. current season)
            c["status"] = "pending"
            pool[c["id"]] = c
    return added


def make_candidate(*, sport: str, kind: str, key: str, answer: str, player_id: str, type_: str,
                   context: str, stats: list[tuple[str, str]], hints: list[str], reveal: str,
                   score: float, extra_aliases: list[str] | None = None) -> dict:
    assert sport in SPORTS and kind in KINDS
    return {
        "id": f"{sport}:{kind}:{key}",
        "sport": sport,
        "kind": kind,
        "status": "pending",          # pending -> approved | rejected -> scheduled
        "scheduled_for": None,
        "player_id": str(player_id),
        "answer": answer,
        "aliases": default_aliases(answer) + list(extra_aliases or []),
        "type": type_,
        "context": context,
        "stats": [{"label": l, "value": str(v)} for l, v in stats],
        "hints": hints,
        "reveal": reveal,
        "score": round(float(score), 2),
        "mined_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# ---------------------------------------------------------------- text helpers

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def default_aliases(name: str) -> list[str]:
    parts = name.replace(".", "").split()
    out = []
    if len(parts) > 2 and parts[-1].lower() in SUFFIXES:
        out.append(" ".join(parts[:-1]))
    return out


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p.lower() not in SUFFIXES]
    return ".".join(p[0].upper() for p in parts if p) + "."


def fmt_int(n) -> str:
    return f"{int(round(float(n))):,}"


def fmt_1(x) -> str:
    return f"{float(x):.1f}"


def fmt_pct(x) -> str:
    """ESPN gives 50.4 for 50.4%; keep one decimal."""
    return f"{float(x):.1f}"


def ordinal_round(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def eastern_date(iso_utc: str) -> datetime:
    """ESPN game times are UTC; the US calendar date is the Eastern one."""
    from zoneinfo import ZoneInfo
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("America/New_York"))


def eastern_today():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()


def pretty_date(d: datetime) -> str:
    return d.strftime("%b %-d, %Y")


# ---------------------------------------------------------------- publishing

def encode_secret(payload: dict) -> str:
    """Light obfuscation so answers aren't readable at a glance in the JSON.

    Not security: anyone can decode it. Mirrors decodeSecret() in app.js.
    """
    raw = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return raw[::-1]


# ---------------------------------------------------------------- answer lock
# The browser never receives an answer in readable form. For each accepted name
# (answer + aliases) a stage stores:
#   h: the first 16 bytes of PBKDF2-SHA256(normalize(name), salt, LOCK_ITERATIONS)
#   c: {"answer", "reveal"} encrypted with the next 32 bytes as key
#      (XOR with an HMAC-SHA256 counter keystream).
# A guess is right when its PBKDF2 matches h; the same derivation then decrypts c.
# Checking every name in players.json means ~26k slow hashes per stage.
# Mirrors unlockGuess() in app.js.
LOCK_ITERATIONS = 200_000


def _derive(name: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha256", normalize(name).encode("utf-8"), salt, iterations, 48)
    return dk[:16], dk[16:]


def _keystream_xor(key: bytes, data: bytes) -> bytes:
    import hmac
    out = bytearray()
    for i in range(0, len(data), 32):
        block = hmac.new(key, (i // 32).to_bytes(4, "big"), hashlib.sha256).digest()
        out += bytes(a ^ b for a, b in zip(data[i:i + 32], block))
    return bytes(out)


def lock_answer(answer: str, aliases: list[str], reveal: str) -> dict:
    import os
    salt = os.urandom(16)
    plain = json.dumps({"answer": answer, "reveal": reveal}, ensure_ascii=False).encode("utf-8")
    keys, seen = [], set()
    for name in [answer, *aliases]:
        n = normalize(name)
        if not n or n in seen:
            continue
        seen.add(n)
        check, key = _derive(name, salt, LOCK_ITERATIONS)
        keys.append({"h": check.hex(), "c": base64.b64encode(_keystream_xor(key, plain)).decode("ascii")})
    return {"salt": base64.b64encode(salt).decode("ascii"), "iter": LOCK_ITERATIONS, "keys": keys}


def unlock(lock: dict, guess: str) -> dict | None:
    """Python twin of the browser check, used by tests."""
    check, key = _derive(guess, base64.b64decode(lock["salt"]), lock["iter"])
    for k in lock["keys"]:
        if k["h"] == check.hex():
            return json.loads(_keystream_xor(key, base64.b64decode(k["c"])))
    return None


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
