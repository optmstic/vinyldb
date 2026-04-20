# VinylDb

A scraped, browsable snapshot of a Discogs vinyl collection.

- `scrape_collection.py` — pulls the collection, detects original release year (via master release), reissue/repress status, limited/numbered editions, and coloured vinyl variants; fetches cover art (Deezer → Discogs → Cover Art Archive, with per-release override via `covers_override.json`).
- `app.py` — Flask viewer for local use.
- `build_static.py` — generates the `docs/` directory published to GitHub Pages.
- `.github/workflows/scrape.yml` — daily rescrape and commit at 20:00 UTC.

## Local use

```bash
pip install -r requirements.txt
# .env:
#   DISCOGS_TOKEN=...
#   DISCOGS_USERNAME=...
python scrape_collection.py     # pulls data + covers
python app.py                   # http://127.0.0.1:5000
```

Force re-fetch of every cover after changing sources or logic:

```bash
python scrape_collection.py --refresh-covers
```

## Publishing to GitHub Pages

1. Create a public repo called `vinyldb` on GitHub.
2. Push this project:
   ```bash
   git remote add origin https://github.com/<you>/vinyldb.git
   git push -u origin main
   ```
3. Add repo secrets (Settings → Secrets and variables → Actions):
   - `DISCOGS_TOKEN`
   - `DISCOGS_USERNAME`
4. Enable Pages (Settings → Pages): Source **Deploy from a branch**, branch `main`, folder `/docs`.
5. Run the workflow once from the Actions tab to verify.

Site URL: `https://<you>.github.io/vinyldb/`.

## Data

SQLite `releases` columns:
`release_id, artist, album, genre, style, year, original_year, reissue, edition, color, country, date_added, cover_path, cover_source`.

## Fixing a wrong cover

Add an entry to `covers_override.json` mapping the Discogs release ID (as a string) to the correct image URL:

```json
{ "32416002": "https://example.com/correct-cover.jpg" }
```

The override is re-downloaded on every scrape and wins over the automatic chain.
