"""Local web viewer for the Discogs collection DB.

Uses the same static template as the GitHub Pages build; data is injected
inline on each request so edits to the DB or template appear on refresh.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, send_from_directory

ROOT = Path(__file__).parent
DB_PATH = ROOT / "collection.db"
COVERS_DIR = ROOT / "covers"
TEMPLATE = ROOT / "templates" / "static.html"

app = Flask(__name__)


def load_data():
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
    releases = [dict(r) for r in rows]
    genres = sorted({g.strip() for r in releases for g in (r["genre"] or "").split(",") if g.strip()})
    countries = sorted({r["country"] for r in releases if r["country"]})
    return {
        "releases": releases,
        "genres": genres,
        "countries": countries,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(releases),
    }


@app.route("/")
def index():
    html = TEMPLATE.read_text(encoding="utf-8")
    return html.replace("__EMBEDDED_DATA__", json.dumps(load_data(), ensure_ascii=False))


@app.route("/covers/<path:name>")
def covers(name):
    return send_from_directory(COVERS_DIR, name)


@app.route("/favicon.svg")
def favicon():
    return send_from_directory(ROOT, "favicon.svg")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
