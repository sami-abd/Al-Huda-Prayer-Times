#!/usr/bin/env python3
import argparse
import pathlib
import re
import sys

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

    response = requests.get(args.source, timeout=30)
    response.raise_for_status()
    source_html = response.text

    extracted = {name: extract_var(source_html, name) for name in TARGET_VARS}
    maghrib_iqamah_text, maghrib_next_text = extract_maghrib_static_cells(source_html)

    original = target_path.read_text(encoding="utf-8")
    updated = original
    for name, value in extracted.items():
        updated = replace_var(updated, name, value)
    updated = replace_maghrib_static_cells(updated, maghrib_iqamah_text, maghrib_next_text)

    if updated == original:
        print("No changes detected.")
        return 0

    target_path.write_text(updated, encoding="utf-8")
    print("Updated variables:", ", ".join(TARGET_VARS))
    print("Updated Maghrib static cells:", maghrib_iqamah_text, "|", maghrib_next_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
