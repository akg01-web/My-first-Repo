"""Summarise a raw Partner API response so the client can be checked against it.

Prints the top-level shape and the field names on the first record. Those field
names are exactly what awardwatch/providers/seatsaero.py parses, and they have
never been validated against the live API -- the session that wrote the client
cannot reach seats.aero.
"""

from __future__ import annotations

import json
import pathlib
import sys

EXPECTED = [
    "Route", "Date", "Source", "ID",
    "JAvailable", "JMileageCost", "JTotalTaxes", "JRemainingSeats", "JAirlines",
    "WAvailable", "WMileageCost", "WTotalTaxes", "WRemainingSeats", "WAirlines",
]


def main(path: str) -> int:
    raw = pathlib.Path(path).read_text()[:200_000]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("Response was not JSON. First 1,500 characters:\n")
        print(raw[:1500])
        return 0

    if not isinstance(payload, dict):
        print(f"Top level is {type(payload).__name__}, not an object.")
        return 0

    records = payload.get("data") or []
    first = records[0] if records else None

    print(json.dumps({
        "top_level_keys": sorted(payload),
        "record_count": len(records),
        "first_record_keys": sorted(first) if isinstance(first, dict) else None,
    }, indent=2)[:4000])

    if isinstance(first, dict):
        missing = [k for k in EXPECTED if k not in first]
        print("\nFields our client expects but the API did not return:")
        print("  " + (", ".join(missing) if missing else "none - the client matches"))
        print("\nFirst record verbatim:")
        print(json.dumps(first, indent=2, default=str)[:3000])

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/probe.json"))
