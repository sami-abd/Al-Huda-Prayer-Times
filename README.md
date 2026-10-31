# Al-Huda Prayer Times

## Overview
This is a single-page static site that displays daily Athan and Iqamah times,
plus a live clock and a "next prayer" countdown. It reads precomputed times
from arrays in `index.html`, selects the current day of the year, and renders
the corresponding entries into the table.

## Author and Ownership
- Author: [Sami]
- Maintined by: [Sami]
- Organization: [Al-Huda Musallah]

## Source and Hosting
- Original site (IISC): [(https://iqamah.ca/)]
- Current production URL: [https://www.iqamah.xyz/]
- Hosting platform (production): [Firebase]

## How It Works (Short Version)
1. `index.html` computes the day-of-year index (`cday`) from the current date.
2. Prayer and Iqamah times are stored as comma-separated strings.
3. The strings are split into arrays and indexed by `cday`.
4. JavaScript writes those values into the table cells.
5. A small countdown script finds the next upcoming prayer and shows a timer.
6. Events such as sunrise, midnight and the last third of the night are also computed and displayed the prayer table.

## Files
- `index.html`: Main page and all JavaScript data/logic.
- `iqamah.css`: Styling for the page layout and typography.
- `scripts/sync_times.py`: Daily sync of the arrays from iqamah.ca (GitHub Actions, `sync_times.yml`).

## Al-Huda Rules Applied by the Sync
- Fajr iqamah: athan + 10 minutes, never earlier than 7:10 AM. The 7:10 minimum is
  skipped on days when 7:10 is less than 30 minutes before sunrise; those days use athan + 10.
  The values are set in `scripts/sync_times.py` (`FAJR_IQAMAH_*`), not taken from iqamah.ca.
- Isha iqamah: shown as "+10 min", set in `index.html`.

If iqamah.ca blocks the GitHub runner, the sync reads it through `r.jina.ai`.
Sync results and errors appear as annotations on each workflow run.

## GitHub Actions Email Alerts
When a sync commit updates prayer times and deploys successfully, an email alert is sent.

Configure these GitHub repository secrets:
- `FIREBASE_TOKEN`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_TO`

For multiple recipients, set `ALERT_EMAIL_TO` as a comma-separated list:
- `owner@example.com,second@example.com`

