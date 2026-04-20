"""Fetch a Discogs collection and save it to SQLite + CSV with original
release year, reissue/edition/color metadata, and cover art from Deezer.

Requires DISCOGS_TOKEN and DISCOGS_USERNAME in a .env file (or env vars).
"""

import csv
import difflib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://api.discogs.com"
USER_AGENT = "VinylDb/1.0 +https://github.com/local"
PER_PAGE = 100

ROOT = Path(__file__).parent
DB_PATH = ROOT / "collection.db"
CSV_PATH = ROOT / "collection.csv"
COVERS_DIR = ROOT / "covers"
OVERRIDES_PATH = ROOT / "covers_override.json"

REFRESH_COVERS = os.environ.get("REFRESH_COVERS") == "1" or "--refresh-covers" in sys.argv

SCHEMA_COLUMNS = [
    ("release_id", "INTEGER PRIMARY KEY"),
    ("artist", "TEXT NOT NULL"),
    ("album", "TEXT NOT NULL"),
    ("genre", "TEXT"),
    ("style", "TEXT"),
    ("year", "INTEGER"),
    ("original_year", "INTEGER"),
    ("reissue", "TEXT"),
    ("edition", "TEXT"),
    ("color", "TEXT"),
    ("country", "TEXT"),
    ("date_added", "TEXT"),
    ("cover_path", "TEXT"),
    ("cover_source", "TEXT"),
]


def _descriptions(formats):
    out = []
    for f in formats or []:
        out.extend(f.get("descriptions") or [])
    return out


def _format_texts(formats):
    return [f.get("text") for f in (formats or []) if f.get("text")]


def detect_reissue(formats):
    """Return 'Reissue' or 'Repress' if the release's format descriptions
    mark it as such, else None. Repress wins if both are present."""
    lowered = [d.lower() for d in _descriptions(formats)]
    if any("repress" in d or d == "re" for d in lowered):
        return "Repress"
    if any("reissue" in d or "re-issue" in d for d in lowered):
        return "Reissue"
    return None


EDITION_LABELS = [
    ("limited edition", "Limited"),
    ("special edition", "Special"),
    ("deluxe edition", "Deluxe"),
    ("numbered", "Numbered"),
    ("limited", "Limited"),
    ("deluxe", "Deluxe"),
    ("promo", "Promo"),
]

COLOR_KEYWORDS = [
    "picture disc", "multi-color", "multi-colour", "multicolor", "multicoloured",
    "tri-color", "tricolor", "bicolor", "coloured", "colored",
    "red", "blue", "green", "yellow", "orange", "pink", "purple", "white", "gold",
    "silver", "bronze", "clear", "transparent", "translucent", "marbled", "marble",
    "splatter", "smoke", "smoky", "swirl", "swirled", "neon", "grey", "gray",
    "brown", "turquoise", "teal", "magenta", "cyan", "violet", "amber", "olive",
    "cream", "beige", "ivory", "crystal",
]
_COLOR_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in COLOR_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def detect_edition_color(formats):
    """Return (edition, color) picked out of format descriptions and format text."""
    descs = _descriptions(formats)
    edition_parts = []
    seen = set()
    for d in descs:
        dl = d.lower()
        for kw, label in EDITION_LABELS:
            if kw in dl and label not in seen:
                edition_parts.append(label)
                seen.add(label)
                break
    color = None
    # format[].text is Discogs' canonical spot for the colour variant string
    for t in _format_texts(formats):
        if _COLOR_RE.search(t):
            color = t.strip()
            break
    if color is None:
        for d in descs:
            if _COLOR_RE.search(d):
                color = d
                break
    return (", ".join(edition_parts) or None, color)


def format_artists(artists):
    parts = []
    for a in artists:
        name = a.get("anv") or a.get("name") or ""
        if name.endswith(")") and " (" in name:
            name = name.rsplit(" (", 1)[0]
        parts.append(name)
        join = (a.get("join") or "").strip()
        if join:
            parts.append(join)
    return " ".join(p for p in parts if p).strip()


def strip_parens(s):
    return re.sub(r"\s*\([^)]*\)\s*", " ", s or "").strip()


def request(session, url, params=None, accept_404=False):
    while True:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "5"))
            print(f"  rate-limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if accept_404 and r.status_code == 404:
            time.sleep(1.1)
            return None
        r.raise_for_status()
        remaining = r.headers.get("X-Discogs-Ratelimit-Remaining")
        if remaining is not None and int(remaining) < 5:
            time.sleep(2)
        else:
            time.sleep(1.1)
        return r.json()


def iter_collection(session, username):
    page = 1
    while True:
        data = request(
            session,
            f"{API}/users/{username}/collection/folders/0/releases",
            params={"page": page, "per_page": PER_PAGE},
        )
        for item in data["releases"]:
            yield item
        if page >= data["pagination"]["pages"]:
            return
        page += 1


def fetch_release_details(session, release_id):
    data = request(session, f"{API}/releases/{release_id}")
    return {
        "country": data.get("country") or "",
        "master_id": data.get("master_id") or None,
        "formats": data.get("formats") or [],
    }


def fetch_master_year(session, master_id):
    data = request(session, f"{API}/masters/{master_id}", accept_404=True)
    if not data:
        return None
    return data.get("year") or None


def norm_title(s):
    """Normalize a title for fuzzy comparison."""
    s = (s or "").lower()
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    s = re.sub(r"\s*\[[^\]]*\]\s*", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_similarity(a, b):
    a, b = norm_title(a), norm_title(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def pick_best(candidates, want_title, want_year):
    """Score candidates; return the best (candidate, score) or (None, 0)."""
    best, best_score = None, 0.0
    for c in candidates:
        title_sim = title_similarity(c["title"], want_title)
        if title_sim < 0.55:
            continue
        score = title_sim
        if want_year and c.get("year"):
            diff = abs(int(c["year"]) - int(want_year))
            if diff == 0:
                score += 0.25
            elif diff <= 2:
                score += 0.10
            else:
                score -= 0.10
        # penalise obvious non-album variants
        t = (c["title"] or "").lower()
        if any(k in t for k in ("karaoke", "tribute", "instrumental version", "remixes")):
            score -= 0.20
        if score > best_score:
            best, best_score = c, score
    return best, best_score


def fetch_deezer_cover(http, artist, album, year):
    q = f'artist:"{strip_parens(artist)}" album:"{strip_parens(album)}"'
    url = "https://api.deezer.com/search/album"
    r = http.get(url, params={"q": q, "limit": 10}, timeout=15)
    results = []
    if r.ok:
        results = (r.json() or {}).get("data") or []
    if not results:
        # looser query
        r = http.get(url, params={"q": f"{strip_parens(artist)} {strip_parens(album)}", "limit": 10}, timeout=15)
        if r.ok:
            results = (r.json() or {}).get("data") or []
    candidates = [
        {
            "title": c.get("title"),
            "year": (c.get("release_date") or "")[:4] or None,
            "art": c.get("cover_xl") or c.get("cover_big"),
        }
        for c in results
        if c.get("cover_xl") or c.get("cover_big")
    ]
    best, _ = pick_best(candidates, album, year)
    return best["art"] if best else None


def download_image(http, url, dest):
    r = http.get(url, timeout=30, allow_redirects=True)
    if r.status_code != 200 or not r.content:
        return False
    dest.write_bytes(r.content)
    return True


def load_overrides():
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  warning: covers_override.json invalid: {e}", file=sys.stderr)
        return {}


def fetch_cover(http, artist, album, release_id, year, overrides):
    COVERS_DIR.mkdir(exist_ok=True)
    dest = COVERS_DIR / f"{release_id}.jpg"

    override = overrides.get(str(release_id))
    if override:
        if download_image(http, override, dest):
            return f"covers/{release_id}.jpg", "override"
        print(f"  override url failed for {release_id}", file=sys.stderr)

    if dest.exists() and dest.stat().st_size > 0 and not REFRESH_COVERS:
        return f"covers/{release_id}.jpg", "cached"

    url = fetch_deezer_cover(http, artist, album, year)
    if url and download_image(http, url, dest):
        return f"covers/{release_id}.jpg", "deezer"

    return None, None


def init_db(conn):
    cols_sql = ",\n  ".join(f"{name} {typ}" for name, typ in SCHEMA_COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS releases (\n  {cols_sql}\n)")
    existing = {row[1] for row in conn.execute("PRAGMA table_info(releases)")}
    wanted = {name for name, _ in SCHEMA_COLUMNS}
    for name, typ in SCHEMA_COLUMNS:
        if name not in existing:
            base_type = typ.split()[0]
            conn.execute(f"ALTER TABLE releases ADD COLUMN {name} {base_type}")
    for name in existing - wanted:
        conn.execute(f"ALTER TABLE releases DROP COLUMN {name}")
    conn.commit()


def upsert(conn, row):
    cols = [c[0] for c in SCHEMA_COLUMNS]
    placeholders = ",".join(["?"] * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "release_id")
    sql = (
        f"INSERT INTO releases ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(release_id) DO UPDATE SET {updates}"
    )
    conn.execute(sql, [row[c] for c in cols])
    conn.commit()


def dump_csv(conn):
    cols = [c[0] for c in SCHEMA_COLUMNS]
    rows = conn.execute(f"SELECT {','.join(cols)} FROM releases ORDER BY artist COLLATE NOCASE").fetchall()
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def main():
    load_dotenv()
    token = os.environ.get("DISCOGS_TOKEN")
    username = os.environ.get("DISCOGS_USERNAME")
    if not token or not username:
        print("Missing DISCOGS_TOKEN or DISCOGS_USERNAME", file=sys.stderr)
        sys.exit(1)

    discogs = requests.Session()
    discogs.headers.update({"User-Agent": USER_AGENT, "Authorization": f"Discogs token={token}"})

    http = requests.Session()
    http.headers.update({"User-Agent": USER_AGENT})

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    overrides = load_overrides()
    master_year_cache = {}

    count = 0
    for i, item in enumerate(iter_collection(discogs, username), 1):
        info = item["basic_information"]
        release_id = info["id"]
        artist = format_artists(info.get("artists", []))
        album = info.get("title", "")
        genre = ", ".join(info.get("genres", []) or [])
        style = ", ".join(info.get("styles", []) or [])
        year = info.get("year") or None
        date_added = item.get("date_added", "")

        print(f"[{i}] {artist} — {album} ({year or '?'})")
        details = fetch_release_details(discogs, release_id)
        full_formats = details["formats"] or info.get("formats", [])
        reissue = detect_reissue(full_formats)
        edition, color = detect_edition_color(full_formats)
        master_id = details["master_id"]
        if master_id:
            if master_id not in master_year_cache:
                master_year_cache[master_id] = fetch_master_year(discogs, master_id)
            original_year = master_year_cache[master_id] or year
        else:
            original_year = year
        if original_year and year and original_year < year and not reissue:
            reissue = "Reissue"
        cover_path, cover_source = fetch_cover(http, artist, album, release_id, year, overrides)
        if cover_source and cover_source != "cached":
            print(f"     cover: {cover_source}")

        row = {
            "release_id": release_id,
            "artist": artist,
            "album": album,
            "genre": genre,
            "style": style,
            "year": year,
            "original_year": original_year,
            "reissue": reissue,
            "edition": edition,
            "color": color,
            "country": details["country"],
            "date_added": date_added,
            "cover_path": cover_path,
            "cover_source": cover_source,
        }
        upsert(conn, row)
        count += 1

    dump_csv(conn)
    conn.close()
    print(f"\nDone. {count} releases in {DB_PATH.name} / {CSV_PATH.name}. Covers in covers/.")


if __name__ == "__main__":
    main()
