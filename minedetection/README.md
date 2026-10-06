# minedetection.org

Static dashboard: sourced landmine statistics, ordnance recognition profiles, and a headline feed refreshed every 6 hours by GitHub Actions. No server, no database.

```
docs/                  the website (served by GitHub Pages)
  index.html
  CNAME                minedetection.org
  data/stats.json      hand-edited figures
  data/ordnance.json   hand-edited profiles
  data/feed.json       written by the bot, do not edit
scripts/fetch_feed.py  headline fetcher (Python stdlib only)
config/sources.json    feed sources and title filter
.github/workflows/update-feed.yml
```

## Setup

1. Create a public GitHub repo, push this folder to `main`.
2. **Settings → Pages**: Source "Deploy from a branch", branch `main`, folder `/docs`.
3. **Settings → Actions → General → Workflow permissions**: "Read and write permissions" (the bot commits `feed.json`).
4. **Actions tab → Update feed → Run workflow** to fill the feed now instead of waiting 6 hours.
5. Custom domain: at your registrar, point `minedetection.org` at GitHub Pages using the A/AAAA records listed in GitHub's current Pages custom-domain docs (look them up there, they are not reproduced here). Then **Settings → Pages → Custom domain** = `minedetection.org`, tick "Enforce HTTPS" once the certificate is issued.

## ReliefWeb (optional, recommended)

ReliefWeb requires a pre-approved `appname` since 1 Nov 2025. Request one via the form linked at https://apidoc.reliefweb.int/parameters (name format: organization + purpose + random characters). When approved, add it as repository secret **`RELIEFWEB_APPNAME`** (Settings → Secrets and variables → Actions). Until then the fetcher skips ReliefWeb.

First run after adding it: check the Actions log shows a non-zero ReliefWeb count. If it shows 0, the `theme` filter value or field names need adjusting; test the query with `&verbose=1`.

## Adding RSS/Atom feeds

Open the feed URL in a browser first and confirm it returns live XML. Then add to `config/sources.json`:

```json
"feeds": [ { "name": "Organization name", "url": "https://example.org/feed.xml" } ]
```

Check the source's terms of use allow headline-and-link display.

## Editing stats

`docs/data/stats.json`. A stat renders only if it has `value`, `label`, `source.name`, `source.url` and `as_of`. Missing any one and the page drops it (console warning). `headline` picks the hero figure.

## Editing ordnance profiles

`docs/data/ordnance.json`. Only `"status": "published"` renders. Each fact cites `src` indices into that profile's `sources`. Scope: identification and impact only. No fuze internals, arming, render-safe or charge data.

Images: `"image": {"url": "...", "alt": "...", "credit": "Photo: Name, CC BY-SA 4.0, Wikimedia Commons"}`. Licensed images only; a missing credit hides the image.

## Local preview

```
cd docs && python3 -m http.server 8000
```
Open http://localhost:8000. (Opening index.html directly as a file will not load the JSON.)

Run the fetcher locally: `python3 scripts/fetch_feed.py`
