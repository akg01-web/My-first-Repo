"""Offline provider that replays JSON fixtures.

Keeps the whole pipeline -- ranking, affordability, reporting, alerting --
runnable and testable with no API key and no network.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..config import REPO_ROOT, Trip
from .base import AwardOption

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"


class FixtureProvider:
    name = "fixture"

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or FIXTURE_DIR

    def search(self, trip: Trip, direction: str, cabin: str) -> list[AwardOption]:
        path = self.directory / "sample_availability.json"
        if not path.exists():
            return []

        window = trip.outbound if direction == "outbound" else trip.ret
        origin = trip.origin if direction == "outbound" else trip.destination
        dest = trip.destination if direction == "outbound" else trip.origin

        rows = json.loads(path.read_text())
        out: list[AwardOption] = []
        for row in rows:
            if row.get("cabin") != cabin or row.get("direction") != direction:
                continue
            date = dt.date.fromisoformat(row["date"])
            if not (window.start <= date <= window.end):
                continue
            out.append(
                AwardOption(
                    program=row["program"],
                    direction=direction,
                    origin=origin,
                    destination=dest,
                    date=date,
                    cabin=cabin,
                    miles=int(row["miles"]),
                    taxes_usd=row.get("taxes_usd"),
                    seats=row.get("seats"),
                    source=self.name,
                    detail_url=None,
                    carrier=row.get("carrier"),
                )
            )
        return out
