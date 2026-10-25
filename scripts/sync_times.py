#!/usr/bin/env python3
import argparse
import calendar
import pathlib
import re
import sys
import time
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse

import requests


# Isha iqamah is intentionally omitted: Al-Huda keeps it hardcoded in index.html.
SCHEDULE_VARIABLES = {
    "IqamahFajr": ("iqamah", "fajr"),
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

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def build_source_candidates(source_url: str) -> list[str]:
    candidates = [source_url]
    parsed = urlparse(source_url)

    if parsed.netloc == "iqamah.ca":
        candidates.append(source_url.replace("://iqamah.ca", "://www.iqamah.ca", 1))
    elif parsed.netloc == "www.iqamah.ca":
        candidates.append(source_url.replace("://www.iqamah.ca", "://iqamah.ca", 1))

    # This mirror remains useful if Cloudflare blocks the GitHub runner.
    candidates.append(f"https://r.jina.ai/http://{parsed.netloc}{parsed.path or '/'}")
    return list(dict.fromkeys(candidates))


def fetch_url(url: str, candidates: list[str] | None = None) -> tuple[str, str]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    last_error: Exception | None = None

    for candidate in candidates or [url]:
        for _ in range(2):
            try:
                response = session.get(candidate, timeout=30)
                if response.status_code == 200:
                    return response.text, candidate
                last_error = RuntimeError(f"{candidate} returned HTTP {response.status_code}")
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(1)

    raise RuntimeError(f"Failed to fetch {url}. Last error: {last_error}")


def find_script_url(html: str, page_url: str, filename: str) -> str:
    match = re.search(
        rf'<script\b[^>]*\bsrc=["\']([^"\']*{re.escape(filename)}[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Could not find {filename} in source HTML.")
    return urljoin(page_url, match.group(1))


def extract_date_schedule(javascript: str, object_name: str) -> dict[str, dict[str, str]]:
    object_match = re.search(
        rf"\b(?:const|let|var)\s+{re.escape(object_name)}\s*=\s*\{{([\s\S]*?)\n\}};",
        javascript,
    )
    if not object_match:
        raise ValueError(f"Could not find {object_name} in linked schedule file.")

    rows: dict[str, dict[str, str]] = {}
    for row in re.finditer(
        r'"(\d{4}-\d{2}-\d{2})"\s*:\s*\{([^}]+)\}',
        object_match.group(1),
    ):
        values = dict(re.findall(r'(\w+)\s*:\s*"([^"]*)"', row.group(2)))
        rows[row.group(1)] = values

    if not rows:
        raise ValueError(f"{object_name} did not contain any dated rows.")
    return rows


def build_year_array(schedule: dict[str, dict[str, str]], prayer: str, year: int) -> str:
    # Include seven January entries so cday + 7 works at the end of December.
    final_index = (366 if calendar.isleap(year) else 365) + 7
    values = ["00"]
    start = date(year, 1, 1)

    for offset in range(final_index):
        iso_date = (start + timedelta(days=offset)).isoformat()
        value = schedule.get(iso_date, {}).get(prayer, "").strip()
        if not value:
            raise ValueError(f"Missing {prayer} value for {iso_date} in source schedule.")
        values.append(value)

    return ", ".join(values)


def extract_linked_variables(html: str, page_url: str, year: int) -> dict[str, str]:
    iqamah_url = find_script_url(html, page_url, "schedule.js")
    salah_url = find_script_url(html, page_url, "salahschedule.js")
    iqamah_js, _ = fetch_url(iqamah_url, build_source_candidates(iqamah_url))
    salah_js, _ = fetch_url(salah_url, build_source_candidates(salah_url))

    schedules = {
        "iqamah": extract_date_schedule(iqamah_js, "IQAMAH_SCHEDULE"),
        "salah": extract_date_schedule(salah_js, "SALAH_SCHEDULE"),
    }
    return {
        variable: build_year_array(schedules[schedule_name], prayer, year)
        for variable, (schedule_name, prayer) in SCHEDULE_VARIABLES.items()
    }


def extract_inline_variables(html: str) -> dict[str, str]:
    extracted = {}
    for name in SCHEDULE_VARIABLES:
        match = re.search(
            rf'^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*"([\s\S]*?)";',
            html,
            re.MULTILINE,
        )
        if not match:
            raise ValueError(f"Could not find legacy variable '{name}' in source HTML.")
        extracted[name] = match.group(1)
    return extracted


def replace_var(content: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf'(^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*")[\s\S]*?(";)',
        re.MULTILINE,
    )
    replaced, count = pattern.subn(rf"\g<1>{value}\2", content, count=1)
    if count != 1:
        raise ValueError(f"Could not replace variable '{name}' in target file.")
    return replaced


def maghrib_display_text(value: str) -> str:
    value = re.sub(r"^\s*sunset\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^\+\s*", "+", value)
    return re.sub(r"\s+", " ", value)


def replace_maghrib_static_cells(content: str, iqamah_text: str, next_text: str) -> str:
    row_pattern = re.compile(r"<tr>\s*<td>\s*Maghrib\s*</td>[\s\S]*?</tr>", re.IGNORECASE)
    row_match = row_pattern.search(content)
    if not row_match:
        raise ValueError("Could not find Maghrib row in target file.")

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
        raise ValueError("Could not replace Maghrib static cells in target file.")
    return content[: row_match.start()] + row_updated + content[row_match.end() :]


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

    source_html, fetched_url = fetch_url(
        args.source,
        candidates=build_source_candidates(args.source),
    )

    if re.search(r"(?:schedule|salahschedule)\.js", source_html, re.IGNORECASE):
        # A proxy copy of the HTML still contains source-relative script URLs.
        page_url = args.source if "r.jina.ai" in fetched_url else fetched_url
        extracted = extract_linked_variables(source_html, page_url, sync_date.year)
        source_format = "linked date schedules"
    else:
        extracted = extract_inline_variables(source_html)
        source_format = "legacy inline variables"

    original = target_path.read_text(encoding="utf-8")
    updated = original
    for name, value in extracted.items():
        updated = replace_var(updated, name, value)

    maghrib_values = [part.strip() for part in extracted["IqamahMaghrib"].split(",")]
    day_index = sync_date.timetuple().tm_yday
    updated = replace_maghrib_static_cells(
        updated,
        maghrib_display_text(maghrib_values[day_index]),
        maghrib_display_text(maghrib_values[day_index + 7]),
    )

    print(f"Fetched {fetched_url} using {source_format} for {sync_date.year}.")
    print(f"Validated and extracted all {len(extracted)} required variables.")
    if updated == original:
        print("No changes detected.")
        return 0

    target_path.write_text(updated, encoding="utf-8")
    print("Updated variables:", ", ".join(sorted(extracted)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
