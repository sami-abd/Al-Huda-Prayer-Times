# IISC Prayer Times

## Overview
This is a single-page static site that displays daily Athan and Iqamah times,
plus a live clock and a "next prayer" countdown. It reads precomputed times
from arrays in `index.html`, selects the current day of the year, and renders
the corresponding entries into the table.

## Author and Ownership
- Author: [Ifzal]
- Maintined by: [Ifzal and Sami]
- Organization: [Islamic Information Society of Calgary]
- Contact: [sami.abdel99@gmail.com]
- License: [Free License]

## Source and Hosting
- Original site: [(https://iqamah.ca/)]
- Current production URL: []
- Hosting platform (production): [Firebase]

## How It Works (Short Version)
1. `index.html` computes the day-of-year index (`cday`) from the current date.
2. Prayer and Iqamah times are stored as comma-separated strings.
3. The strings are split into arrays and indexed by `cday`.
4. JavaScript writes those values into the table cells.
5. A small countdown script finds the next upcoming prayer and shows a timer.

## Files
- `index.html`: Main page and all JavaScript data/logic.
- `iqamah.css`: Styling for the page layout and typography.

## Running Locally
1. Open `index.html` in a browser, or run a static server:
   - Example: `python -m http.server` and visit `http://localhost:8000/`.
2. If times do not display, check for script-loading issues or blocked
   external assets (fonts, analytics, etc.).

## Notes and Known Issues
- External assets (fonts, analytics, icons) may not load offline.
- If the original site used optimization/protection scripts, they might need
  to be removed or adapted for local use.


