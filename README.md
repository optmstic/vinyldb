# vinyldb

Personal project for browsing and publishing a Discogs vinyl collection.

`vinyldb` creates a local database and static website from a Discogs collection, enriches each release with metadata, downloads cover art, and publishes a browsable collection through GitHub Pages.

---

## What it does

- Scrapes a Discogs collection using the Discogs API
- Stores the collection in SQLite and CSV formats
- Detects original release year, reissue/repress status, editions, and coloured vinyl variants
- Fetches cover art from Deezer, with Discogs image fallback
- Supports manual cover overrides through `covers_override.json`
- Provides a local Flask viewer
- Generates a static `docs/` site for GitHub Pages
- Includes a GitHub Actions workflow for scheduled collection refreshes

---

## Repository structure

```text
.
├── app.py                  # Local Flask viewer
├── build_static.py          # Static site generator
├── scrape_collection.py     # Discogs scraper and metadata enrichment
├── collection.csv           # Exported collection data
├── collection.db            # SQLite database
├── covers/                  # Downloaded cover images
├── covers_override.json     # Manual cover override rules
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Local setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file with your Discogs credentials:

```env
DISCOGS_TOKEN=your_token_here
DISCOGS_USERNAME=your_username_here
```

Scrape the collection and run the local viewer:

```bash
python scrape_collection.py
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

---

## Refreshing covers

Force a full cover re-fetch after changing sources or override logic:

```bash
python scrape_collection.py --refresh-covers
```

---

## Fixing incorrect covers

Add an entry to `covers_override.json` using the Discogs release ID as the key.

Use either a direct image URL:

```json
{
  "32416002": "https://example.com/correct-cover.jpg"
}
```

Or force the Discogs primary image:

```json
{
  "31128872": "discogs"
}
```

Overrides are applied on every scrape and take priority over the automatic Deezer → Discogs fallback chain.

---

## Publishing with GitHub Pages

1. Generate the static site:

   ```bash
   python build_static.py
   ```

2. Enable GitHub Pages for the repository:
   - Source: deploy from branch
   - Branch: `main`
   - Folder: `/docs`

3. Add repository secrets for automated scraping:
   - `DISCOGS_TOKEN`
   - `DISCOGS_USERNAME`

Published site:

```text
https://optmstic.github.io/vinyldb/
```

---

## Technologies

`Python` · `Flask` · `SQLite` · `Discogs API` · `GitHub Pages` · `GitHub Actions`
