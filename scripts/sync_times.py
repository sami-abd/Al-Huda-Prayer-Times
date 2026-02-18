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

    original = target_path.read_text(encoding="utf-8")
    updated = original
    for name, value in extracted.items():
        updated = replace_var(updated, name, value)

    if updated == original:
        print("No changes detected.")
        return 0

    target_path.write_text(updated, encoding="utf-8")
    print("Updated variables:", ", ".join(TARGET_VARS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
