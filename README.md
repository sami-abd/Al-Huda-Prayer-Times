# IISC Prayer Times

## Overview
This is a single-page static site that displays daily Athan and Iqamah times,
plus a live clock and a "next prayer" countdown. Times live in `times.js`
and are loaded by `index.html`, which selects the current day of the year
and renders the corresponding entries into the table.

## Author and Ownership
- Author: [Afzal]
- Maintined by: [Afzal and Sami]
- Organization: [Islamic Information Society of Calgary]

## Source and Hosting
- Original site: [(https://iqamah.ca/)]
- Current development URL: [https://www.iqamah.xyz/]
- Hosting platform (production): [Firebase]

## How It Works (Short Version)
1. `index.html` computes the day-of-year index (`cday`) from the current date.
2. Prayer and Iqamah times are stored as comma-separated strings in `times.js`.
3. The strings are split into arrays and indexed by `cday`.
4. JavaScript writes those values into the table cells.
5. A small countdown script finds the next upcoming prayer and shows a timer.

## Files
- `index.html`: Main page and JavaScript logic.
- `iqamah.css`: Styling for the page layout and typography.
- `times.js`: Times data (auto-synced).
- `scripts/sync_times.py`: Fetches times from the original site and regenerates `times.js`.

## Sync Times (Manual)
Set the source URL and run the sync script:

```bash
python scripts/sync_times.py --source "https://iqamah.ca/"
```

Or set `IISC_TIMES_SOURCE_URL` and run without arguments:

```bash
set IISC_TIMES_SOURCE_URL=https://iqamah.ca/
python scripts/sync_times.py
```

After syncing, deploy with:

```bash
firebase deploy --only hosting
```

## Sync Times (Scheduled via GitHub Actions + Auto-Deploy)
This repo includes `.github/workflows/sync_times.yml`. It runs daily and can
be triggered manually. It updates `times.js`, commits changes, and deploys
to Firebase Hosting.

Setup:
1. Add a repo variable named `IISC_TIMES_SOURCE_URL` (optional). The default is `https://iqamah.ca/`.
2. Add a repo secret named `FIREBASE_TOKEN`.
   - Generate locally with: `firebase login:ci`
   - Copy the token into GitHub → Settings → Secrets and variables → Actions → New repository secret

After setup, the workflow will sync and deploy automatically.

