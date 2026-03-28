#!/usr/bin/env python3
import argparse
import pathlib
import re
import sys
import time
from urllib.parse import urlparse

import requests


TARGET_VARS = [
    "IqamahFajr",
    "IqamahZuhr",
    "IqamahAsr",
    "IqamahMaghrib",
    "IqamahIsha",
    "SalahFajr",
    "SalahSunrise",
    "SalahZuhr",
    "SalahAsr",
    "SalahMaghrib",
    "SalahIsha",
]

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

    # Last-resort proxy mirror for sites that block non-browser/CI requests.
    # This can return plain text but still includes the JS variable lines.
    candidates.append(f"https://r.jina.ai/http://{parsed.netloc}{parsed.path or '/'}")

    # Deduplicate while preserving order.
    seen = set()
    unique_candidates = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique_candidates.append(url)
    return unique_candidates


def fetch_source_html(source_url: str) -> str:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    last_error = None
    candidates = build_source_candidates(source_url)
    attempts_per_candidate = 2

    for candidate in candidates:
        for attempt in range(1, attempts_per_candidate + 1):
            try:
                response = session.get(candidate, timeout=30)
                if response.status_code == 200:
                    return response.text
                last_error = RuntimeError(f"{candidate} returned HTTP {response.status_code}")
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(1.0)

    raise RuntimeError(
        "Failed to fetch source HTML from all candidates. "
        f"Last error: {last_error}"
    )


def extract_maghrib_static_cells(html: str) -> tuple[str, str]:
    row_pattern = re.compile(r"<tr>\s*<td>\s*Maghrib\s*</td>[\s\S]*?</tr>", re.IGNORECASE)
    row_match = row_pattern.search(html)
    if not row_match:
        raise ValueError("Could not find Maghrib row in source HTML.")

    row_html = row_match.group(0)

    iqamah_match = re.search(
        r'<td\s+class="iqamah-time">\s*([^<]+?)\s*</td>',
        row_html,
        re.IGNORECASE,
    )
    if not iqamah_match:
        raise ValueError("Could not find Maghrib Iqamah static cell in source HTML.")

    next_match = re.search(
        r'<td\s+class="prayer-time">\s*<span[^>]*>\s*([^<]+?)\s*</span>\s*</td>',
        row_html,
        re.IGNORECASE,
    )

    iqamah_text = iqamah_match.group(1).strip()
    next_text = next_match.group(1).strip() if next_match else iqamah_text
    return iqamah_text, next_text


def extract_var(html: str, name: str) -> str:
    pattern = re.compile(
        rf"^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*\"([\s\S]*?)\";",
        re.MULTILINE,
    )
    match = pattern.search(html)
    if not match:
        raise ValueError(f"Could not find variable '{name}' in source HTML.")
    return match.group(1)


def try_extract_var(html: str, name: str) -> str | None:
    try:
        return extract_var(html, name)
    except ValueError:
        return None


def replace_var(content: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf"(^[ \t]*var[ \t]+{re.escape(name)}[ \t]*=[ \t]*\")[\s\S]*?(\";)",
        re.MULTILINE,
    )
    replaced, count = pattern.subn(rf"\g<1>{value}\2", content, count=1)
    if count != 1:
        raise ValueError(f"Could not replace variable '{name}' in target file.")
    return replaced


def replace_maghrib_static_cells(content: str, iqamah_text: str, next_text: str) -> str:
    row_pattern = re.compile(r"<tr>\s*<td>\s*Maghrib\s*</td>[\s\S]*?</tr>", re.IGNORECASE)
    row_match = row_pattern.search(content)
    if not row_match:
        raise ValueError("Could not find Maghrib row in target file.")

    row_html = row_match.group(0)

    row_updated, iq_count = re.subn(
        r'(<td\s+class="iqamah-time">\s*)([^<]+?)(\s*</td>)',
        lambda m: f"{m.group(1)}{iqamah_text}{m.group(3)}",
        row_html,
        count=1,
        flags=re.IGNORECASE,
    )
    if iq_count != 1:
        raise ValueError("Could not replace Maghrib Iqamah static cell in target file.")

    row_updated, next_count = re.subn(
        r'(<td\s+class="iqamah-time">\s*[^<]+?\s*</td>\s*<td\s+class="prayer-time">\s*<span[^>]*>\s*)([^<]+?)(\s*</span>\s*</td>)',
        lambda m: f"{m.group(1)}{next_text}{m.group(3)}",
        row_updated,
        count=1,
        flags=re.IGNORECASE,
    )
    if next_count != 1:
        raise ValueError("Could not replace Maghrib Next Sunday static cell in target file.")

    return content[: row_match.start()] + row_updated + content[row_match.end() :]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync prayer-time variables from source site.")
    parser.add_argument("--source", default="https://iqamah.ca/", help="Source URL")
    parser.add_argument("--target", default="index.html", help="Target local HTML file")
    args = parser.parse_args()

    target_path = pathlib.Path(args.target)
    if not target_path.exists():
        print(f"Target file not found: {target_path}", file=sys.stderr)
        return 2

    source_html = fetch_source_html(args.source)

    extracted: dict[str, str] = {}
    missing_vars: list[str] = []
    for name in TARGET_VARS:
        value = try_extract_var(source_html, name)
        if value is None:
            missing_vars.append(name)
        else:
            extracted[name] = value

    maghrib_iqamah_text = None
    maghrib_next_text = None
    try:
        maghrib_iqamah_text, maghrib_next_text = extract_maghrib_static_cells(source_html)
    except ValueError:
        pass

    original = target_path.read_text(encoding="utf-8")
    updated = original
    for name, value in extracted.items():
        updated = replace_var(updated, name, value)
    if maghrib_iqamah_text and maghrib_next_text:
        updated = replace_maghrib_static_cells(updated, maghrib_iqamah_text, maghrib_next_text)

    if not extracted and not (maghrib_iqamah_text and maghrib_next_text):
        print("Warning: No variables or Maghrib static cells found in source HTML.")
        print("Skipping sync without failing so current deployed site remains stable.")
        return 0

    if missing_vars:
        print(
            "Warning: Missing source variables (kept existing local values):",
            ", ".join(missing_vars),
        )

    if updated == original:
        print("No changes detected.")
        return 0

    target_path.write_text(updated, encoding="utf-8")
    if extracted:
        print("Updated variables:", ", ".join(sorted(extracted.keys())))
    if maghrib_iqamah_text and maghrib_next_text:
        print("Updated Maghrib static cells:", maghrib_iqamah_text, "|", maghrib_next_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
