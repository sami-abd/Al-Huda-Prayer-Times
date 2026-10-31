#!/usr/bin/env python3
"""Sync prayer times in index.html from iqamah.ca.

iqamah.ca links two schedule scripts from its home page:
  schedule.js       IQAMAH_SCHEDULE = { "YYYY-MM-DD": { fajr: "...", ... }, ... }
  salahschedule.js  SALAH_SCHEDULE  = { "YYYY-MM-DD": { fajr: "...", sunrise: "...", ... }, ... }
Older versions of the site had the arrays inline as `var IqamahFajr = "...";`.

iqamah.ca usually answers GitHub runners with HTTP 403. When that happens the
files are fetched through the r.jina.ai reader, which is asked for raw HTML or
plain text so the script tags and schedule objects come through intact.

After syncing, Al-Huda's own Fajr iqamah rule is applied to index.html. The rule
is applied even when iqamah.ca can't be read; the script then still exits with 1.
"""
import argparse
import calendar
import html as html_lib
import os
import pathlib
import re
import sys
import time
import traceback
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse

import requests


# Not synced from iqamah.ca:
#   IqamahIsha: Al-Huda keeps it hardcoded in index.html.
#   IqamahFajr: computed from the Fajr athan by apply_fajr_iqamah_rule().
SCHEDULE_VARIABLES = {
    "IqamahZuhr": ("iqamah", "zuhr"),
    "IqamahAsr": ("iqamah", "asr"),
    "IqamahMaghrib": ("iqamah", "maghrib"),
    "SalahFajr": ("salah", "fajr"),
    "SalahSunrise": ("salah", "sunrise"),
    "SalahZuhr": ("salah", "zuhr"),
    "SalahAsr": ("salah", "asr"),
    "SalahMaghrib": ("salah", "maghrib"),
    "SalahIsha": ("salah", "isha"),
}

SCHEDULE_FILES = {
    "iqamah": ("schedule.js", "IQAMAH_SCHEDULE"),
    "salah": ("salahschedule.js", "SALAH_SCHEDULE"),
}

# Other spellings the source could use for the same field.
FIELD_ALIASES = {
    "fajr": "fajr",
    "fajar": "fajr",
    "sunrise": "sunrise",
    "shuruq": "sunrise",
    "shurooq": "sunrise",
    "zuhr": "zuhr",
    "dhuhr": "zuhr",
    "duhr": "zuhr",
    "zuhur": "zuhr",
    "asr": "asr",
    "maghrib": "maghrib",
    "magrib": "maghrib",
    "isha": "isha",
    "ishaa": "isha",
}

# The page reads yesterday through today + 7 ("Next Sunday"), so those days
# must come from the source. Other missing days keep the value already in index.html.
REQUIRED_DAYS_BEFORE = 1
REQUIRED_DAYS_AFTER = 7

# Al-Huda's Fajr iqamah: 10 minutes after the athan, never earlier than 7:10 AM.
# The 7:10 minimum is skipped on days when 7:10 is less than 30 minutes before
# sunrise (spring and summer); those days use athan + 10.
FAJR_IQAMAH_DELAY_MINUTES = 10
FAJR_IQAMAH_EARLIEST = "7:10 AM"
FAJR_IQAMAH_SUNRISE_BUFFER_MINUTES = 30

READER_PREFIX = "https://r.jina.ai/"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

CHALLENGE_MARKERS = (
    "just a moment...",
    "cf-chl",
    "challenge-platform",
    "attention required! | cloudflare",
)


class SyncError(RuntimeError):
    pass


def annotate(level: str, message: str, title: str = "") -> None:
    """Print a GitHub Actions annotation. These show up on the run page and in the API."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    data = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    properties = ""
    if title:
        escaped_title = title.replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
        properties = f" title={escaped_title}"
    print(f"::{level}{properties}::{data}", flush=True)


# ---------------------------------------------------------------- fetching


def fetch_candidates(url: str, reader_format: str) -> list[tuple[str, dict[str, str], str]]:
    parsed = urlparse(url)
    host = parsed.netloc
    other_host = host[4:] if host.startswith("www.") else f"www.{host}"
    return [
        (url, {}, "direct"),
        (url.replace(f"://{host}", f"://{other_host}", 1), {}, "direct"),
        (
            READER_PREFIX + url,
            {"X-Return-Format": reader_format, "X-No-Cache": "true"},
            "r.jina.ai",
        ),
    ]


def is_challenge_page(text: str) -> bool:
    head = text[:5000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


def fetch(url: str, reader_format: str, is_usable, attempts_log: list[str]) -> tuple[str, str, str]:
    """Return (text, fetched_url, route) for the first candidate that gives usable content."""
    session = requests.Session()
    attempts: list[str] = []

    for candidate, extra_headers, route in fetch_candidates(url, reader_format):
        headers = {**BROWSER_HEADERS, **extra_headers}
        for attempt in range(2):
            try:
                response = session.get(candidate, headers=headers, timeout=45)
            except requests.RequestException as exc:
                result = type(exc).__name__
                retry = True
            else:
                text = response.text
                if response.status_code != 200:
                    result = f"HTTP {response.status_code}"
                    retry = response.status_code == 429 or response.status_code >= 500
                elif is_challenge_page(text):
                    result = "Cloudflare challenge page"
                    retry = False
                elif not is_usable(text):
                    result = f"HTTP 200, but the expected content is missing ({len(text)} chars)"
                    retry = False
                else:
                    attempts.append(f"{candidate}: OK")
                    attempts_log.extend(attempts)
                    return text, candidate, route
            attempts.append(f"{candidate}: {result}")
            if not retry or attempt == 1:
                break
            time.sleep(3)

    attempts_log.extend(attempts)
    raise SyncError(f"Could not fetch {url}. Tried: " + "; ".join(attempts))


# ---------------------------------------------------------------- parsing


def find_script_url(html: str, page_url: str, filename: str) -> str | None:
    """Find a <script src> whose file name is exactly `filename`.

    Matching the whole file name keeps "schedule.js" from matching "salahschedule.js".
    """
    for match in re.finditer(r'<script\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE):
        src = html_lib.unescape(match.group(1).strip())
        name = urlparse(src).path.rsplit("/", 1)[-1]
        if name.lower() == filename.lower():
            return urljoin(page_url, src)
    return None


def has_linked_schedules(html: str) -> bool:
    return all(
        find_script_url(html, "https://example.invalid/", filename)
        for filename, _ in SCHEDULE_FILES.values()
    )


def has_inline_variables(html: str) -> bool:
    return all(
        re.search(rf'^[ \t]*var[ \t]+{name}[ \t]*=[ \t]*"', html, re.MULTILINE)
        for name in SCHEDULE_VARIABLES
    )


def extract_object_literal(javascript: str, object_name: str) -> str:
    """Return the text between the braces of `const NAME = { ... }`."""
    match = re.search(
        rf"(?:\b(?:const|let|var)\s+|\bwindow\.){re.escape(object_name)}\s*=\s*\{{",
        javascript,
    )
    if not match:
        raise SyncError(f"Could not find {object_name} in the linked schedule file.")

    start = match.end() - 1
    depth = 0
    quote = None
    index = start
    length = len(javascript)
    while index < length:
        char = javascript[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif javascript.startswith("//", index):
            newline = javascript.find("\n", index)
            index = length if newline == -1 else newline
            continue
        elif javascript.startswith("/*", index):
            end = javascript.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return javascript[start + 1 : index]
        index += 1

    raise SyncError(f"{object_name} is not closed in the linked schedule file.")


ROW_PATTERN = re.compile(r"""["']?(\d{4}-\d{2}-\d{2})["']?\s*:\s*\{([^{}]*)\}""")
FIELD_PATTERN = re.compile(r"""["']?([A-Za-z_]\w*)["']?\s*:\s*(["'`])(.*?)\2""", re.DOTALL)


def extract_date_schedule(javascript: str, object_name: str) -> dict[str, dict[str, str]]:
    body = extract_object_literal(javascript, object_name)
    rows: dict[str, dict[str, str]] = {}
    for row in ROW_PATTERN.finditer(body):
        values: dict[str, str] = {}
        for field in FIELD_PATTERN.finditer(row.group(2)):
            key = FIELD_ALIASES.get(field.group(1).lower())
            if key:
                values[key] = field.group(3).strip()
        rows[row.group(1)] = values

    if not rows:
        raise SyncError(f"{object_name} did not contain any dated rows.")
    return rows


def read_array(content: str, name: str) -> list[str] | None:
    match = re.search(
        rf'^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*"([\s\S]*?)";',
        content,
        re.MULTILINE,
    )
    return [part.strip() for part in match.group(1).split(",")] if match else None


def read_existing_arrays(content: str) -> dict[str, list[str]]:
    return {name: read_array(content, name) or [] for name in SCHEDULE_VARIABLES}


def year_days(year: int) -> list[date]:
    """Jan 1 of `year` through Jan 7 of the next year, so cday + 7 works in late December."""
    count = (366 if calendar.isleap(year) else 365) + 7
    start = date(year, 1, 1)
    return [start + timedelta(days=offset) for offset in range(count)]


def build_year_array(
    schedule: dict[str, dict[str, str]],
    prayer: str,
    days: list[date],
    existing: list[str],
    required: set[date],
    label: str,
) -> tuple[str, list[date]]:
    values = ["00"]
    kept: list[date] = []
    for index, day in enumerate(days, start=1):
        value = schedule.get(day.isoformat(), {}).get(prayer, "").strip()
        if not value:
            if day in required:
                raise SyncError(f"iqamah.ca has no {label} time for {day.isoformat()}.")
            if index < len(existing) and existing[index]:
                value = existing[index]
                kept.append(day)
            else:
                raise SyncError(
                    f"No {label} time for {day.isoformat()} in iqamah.ca or in index.html."
                )
        values.append(value)
    return ", ".join(values), kept


def describe_days(days: list[date]) -> str:
    if not days:
        return ""
    ranges = []
    start = previous = days[0]
    for day in days[1:]:
        if day - previous != timedelta(days=1):
            ranges.append((start, previous))
            start = day
        previous = day
    ranges.append((start, previous))
    return ", ".join(a.isoformat() if a == b else f"{a.isoformat()} to {b.isoformat()}" for a, b in ranges)


def extract_inline_variables(html: str) -> dict[str, str]:
    extracted = {}
    for name in SCHEDULE_VARIABLES:
        match = re.search(
            rf'^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*"([\s\S]*?)";',
            html,
            re.MULTILINE,
        )
        if not match:
            raise SyncError(f"Could not find legacy variable '{name}' in the iqamah.ca page.")
        extracted[name] = match.group(1)
    return extracted


# ---------------------------------------------------------------- writing


def replace_var(content: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf'(^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*")[\s\S]*?(";)',
        re.MULTILINE,
    )
    replaced, count = pattern.subn(lambda match: f"{match.group(1)}{value}{match.group(2)}", content, count=1)
    if count != 1:
        raise SyncError(f"Could not replace variable '{name}' in the target file.")
    return replaced


def maghrib_display_text(value: str) -> str:
    value = re.sub(r"^\s*sunset\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^\+\s*", "+", value)
    return re.sub(r"\s+", " ", value)


def replace_maghrib_static_cells(content: str, iqamah_text: str, next_text: str) -> str:
    row_pattern = re.compile(r"<tr>\s*<td>\s*Maghrib\s*</td>[\s\S]*?</tr>", re.IGNORECASE)
    row_match = row_pattern.search(content)
    if not row_match:
        raise SyncError("Could not find the Maghrib row in the target file.")

    row_html = row_match.group(0)
    row_updated, iq_count = re.subn(
        r'(<td\s+class="iqamah-time">\s*)([^<]+?)(\s*</td>)',
        lambda match: f"{match.group(1)}{iqamah_text}{match.group(3)}",
        row_html,
        count=1,
        flags=re.IGNORECASE,
    )
    row_updated, next_count = re.subn(
        r'(<td\s+class="iqamah-time">\s*[^<]+?\s*</td>\s*<td\s+class="prayer-time">\s*<span[^>]*>\s*)([^<]+?)(\s*</span>\s*</td>)',
        lambda match: f"{match.group(1)}{next_text}{match.group(3)}",
        row_updated,
        count=1,
        flags=re.IGNORECASE,
    )
    if iq_count != 1 or next_count != 1:
        raise SyncError("Could not replace the Maghrib static cells in the target file.")
    return content[: row_match.start()] + row_updated + content[row_match.end() :]


# ---------------------------------------------------------------- Fajr iqamah


def clock_to_minutes(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*", value or "", re.IGNORECASE)
    if not match:
        return None
    hours = int(match.group(1)) % 12 + (12 if match.group(3).upper() == "PM" else 0)
    return hours * 60 + int(match.group(2))


def minutes_to_clock(total: int) -> str:
    hours, minutes = divmod(total % (24 * 60), 60)
    return f"{hours % 12 or 12}:{minutes:02d} {'AM' if hours < 12 else 'PM'}"


def fajr_iqamah(athan: str, sunrise: str) -> str | None:
    athan_minutes = clock_to_minutes(athan)
    if athan_minutes is None:
        return None
    iqamah = athan_minutes + FAJR_IQAMAH_DELAY_MINUTES
    earliest = clock_to_minutes(FAJR_IQAMAH_EARLIEST)
    sunrise_minutes = clock_to_minutes(sunrise)
    earliest_fits_before_sunrise = (
        sunrise_minutes is not None
        and earliest <= sunrise_minutes - FAJR_IQAMAH_SUNRISE_BUFFER_MINUTES
    )
    if iqamah < earliest and earliest_fits_before_sunrise:
        iqamah = earliest
    return minutes_to_clock(iqamah)


def apply_fajr_iqamah_rule(content: str) -> str:
    athans = read_array(content, "SalahFajr")
    sunrises = read_array(content, "SalahSunrise")
    current = read_array(content, "IqamahFajr")
    if athans is None or sunrises is None or current is None:
        raise SyncError("Could not find SalahFajr, SalahSunrise or IqamahFajr in the target file.")

    values = ["00"]
    for index in range(1, len(athans)):
        sunrise = sunrises[index] if index < len(sunrises) else ""
        computed = fajr_iqamah(athans[index], sunrise)
        if computed is None:  # Unreadable athan: keep what was there.
            computed = current[index] if index < len(current) else ""
        values.append(computed)
    return replace_var(content, "IqamahFajr", ", ".join(values))


# ---------------------------------------------------------------- main


def sync_from_iqamah_ca(source: str, content: str, sync_date: date) -> tuple[str, str]:
    """Return index.html content updated from iqamah.ca, and a note on where it came from."""
    attempts: list[str] = []
    notes: list[str] = []

    page_html = None
    page_url = source
    try:
        page_html, fetched_url, route = fetch(
            source,
            "html",
            lambda text: has_linked_schedules(text) or has_inline_variables(text),
            attempts,
        )
        if route == "direct":
            page_url = fetched_url
        notes.append(f"page via {route}")
    except SyncError as exc:
        # The script files can still be tried at their usual address next to the page.
        notes.append("page unavailable, used default schedule file URLs")
        annotate("warning", str(exc), "iqamah.ca page not readable")

    try:
        if page_html and not has_linked_schedules(page_html) and has_inline_variables(page_html):
            extracted = extract_inline_variables(page_html)
            source_format = "legacy inline variables"
            kept_days: list[date] = []
        else:
            days = year_days(sync_date.year)
            required = {
                day
                for day in days
                if sync_date - timedelta(days=REQUIRED_DAYS_BEFORE)
                <= day
                <= sync_date + timedelta(days=REQUIRED_DAYS_AFTER)
            }
            schedules = {}
            for schedule_name, (filename, object_name) in SCHEDULE_FILES.items():
                script_url = (page_html and find_script_url(page_html, page_url, filename)) or urljoin(
                    source, filename
                )
                javascript, _, route = fetch(
                    script_url,
                    "text",
                    lambda text, name=object_name: re.search(rf"\b{name}\s*=\s*\{{", text) is not None,
                    attempts,
                )
                schedules[schedule_name] = extract_date_schedule(javascript, object_name)
                notes.append(f"{filename} via {route}")

            existing = read_existing_arrays(content)
            extracted = {}
            kept_by_day: set[date] = set()
            for variable, (schedule_name, prayer) in SCHEDULE_VARIABLES.items():
                extracted[variable], kept = build_year_array(
                    schedules[schedule_name],
                    prayer,
                    days,
                    existing[variable],
                    required,
                    f"{schedule_name} {prayer}",
                )
                kept_by_day.update(kept)
            kept_days = sorted(kept_by_day)
            source_format = "linked date schedules"
    finally:
        print("Fetch attempts:")
        for line in attempts:
            print(f"  {line}")

    updated = content
    for name, value in extracted.items():
        updated = replace_var(updated, name, value)

    maghrib_values = [part.strip() for part in extracted["IqamahMaghrib"].split(",")]
    day_index = sync_date.timetuple().tm_yday
    updated = replace_maghrib_static_cells(
        updated,
        maghrib_display_text(maghrib_values[day_index]),
        maghrib_display_text(maghrib_values[day_index + 7]),
    )

    source_note = f"{source_format} for {sync_date.year} ({', '.join(notes)})"
    print(f"Read iqamah.ca as {source_note}.")

    if kept_days:
        message = (
            f"iqamah.ca has no times for {len(kept_days)} day(s) of {sync_date.year}; "
            f"kept the values already in index.html for: {describe_days(kept_days)}"
        )
        print(message)
        annotate("warning", message, "Some days not in iqamah.ca")

    return updated, source_note


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync prayer times from iqamah.ca.")
    parser.add_argument("--source", default="https://iqamah.ca/", help="Source URL")
    parser.add_argument("--target", default="index.html", help="Target local HTML file")
    parser.add_argument("--date", help="Date to sync for, in YYYY-MM-DD format")
    args = parser.parse_args()

    sync_date = date.fromisoformat(args.date) if args.date else date.today()
    target_path = pathlib.Path(args.target)
    if not target_path.exists():
        print(f"Target file not found: {target_path}", file=sys.stderr)
        return 2

    original = target_path.read_text(encoding="utf-8")
    content = original
    sync_failed = False
    source_note = ""
    try:
        content, source_note = sync_from_iqamah_ca(args.source, content, sync_date)
    except SyncError as exc:
        sync_failed = True
        print(f"Sync from iqamah.ca failed: {exc}", file=sys.stderr)
        annotate("error", str(exc), "iqamah.ca sync failed")
    except Exception as exc:  # Unexpected errors still need to show up on the run page.
        sync_failed = True
        traceback.print_exc()
        annotate("error", f"{type(exc).__name__}: {exc}", "iqamah.ca sync crashed")

    # The Fajr rule only needs the athan times, so it runs even if the sync failed.
    try:
        content = apply_fajr_iqamah_rule(content)
    except Exception as exc:
        traceback.print_exc()
        annotate("error", f"{type(exc).__name__}: {exc}", "Fajr iqamah rule failed")
        return 1

    if content == original:
        summary = "No changes: index.html is already up to date."
    else:
        target_path.write_text(content, encoding="utf-8")
        summary = "Updated index.html."
    print(summary)
    if not sync_failed:
        annotate("notice", f"{summary} Source: {source_note}.", "iqamah.ca sync")
    return 1 if sync_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
