import argparse
import os
import re
import sys
import urllib.request
from pathlib import Path

VAR_NAMES = [
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


def fetch_html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def extract_vars(html: str) -> list[str]:
    extracted = []
    for name in VAR_NAMES:
        pattern = re.compile(rf"var\s+{re.escape(name)}\s*=\s*\".*?\";", re.S)
        match = pattern.search(html)
        if not match:
            raise ValueError(f"Missing variable: {name}")
        line = re.sub(r"\s+", " ", match.group(0)).strip()
        extracted.append(line)
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync prayer times into times.js")
    parser.add_argument("--source", help="Source URL for the original HTML")
    parser.add_argument("--out", default="times.js", help="Output JS file path")
    args = parser.parse_args()

    source = args.source or os.environ.get("IISC_TIMES_SOURCE_URL") or "https://iqamah.ca/"

    html = fetch_html(source)
    lines = extract_vars(html)

    out_path = Path(args.out)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
