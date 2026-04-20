"""Build the static site that gets published to GitHub Pages.

Reads collection.db, writes site/index.html + site/data.json, copies covers/.
"""

import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
DB_PATH = ROOT / "collection.db"
COVERS_DIR = ROOT / "covers"
SITE_DIR = ROOT / "docs"
TEMPLATE = ROOT / "templates" / "static.html"


def load_releases():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT release_id, artist, album, genre, style, year, original_year, reissue,
               edition, color, country, date_added, cover_path
        FROM releases
        ORDER BY artist COLLATE NOCASE, year
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def main():
    if not DB_PATH.exists():
        print("collection.db not found — run scrape_collection.py first", file=sys.stderr)
        sys.exit(1)

    SITE_DIR.mkdir(exist_ok=True)
    releases = load_releases()

    genres = sorted({g.strip() for r in releases for g in (r["genre"] or "").split(",") if g.strip()})
    countries = sorted({r["country"] for r in releases if r["country"]})

    data = {
        "releases": releases,
        "genres": genres,
        "countries": countries,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(releases),
    }
    (SITE_DIR / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__EMBEDDED_DATA__", json.dumps(data, ensure_ascii=False))
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")

    site_covers = SITE_DIR / "covers"
    if site_covers.exists():
        shutil.rmtree(site_covers)
    if COVERS_DIR.exists():
        shutil.copytree(COVERS_DIR, site_covers)

    favicon = ROOT / "favicon.svg"
    if favicon.exists():
        shutil.copy(favicon, SITE_DIR / "favicon.svg")

    # Jekyll off so dotfiles/underscores in site/ aren't skipped.
    (SITE_DIR / ".nojekyll").write_text("")

    print(f"Built docs/ with {len(releases)} releases.")


if __name__ == "__main__":
    main()
