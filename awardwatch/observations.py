"""Append-only log of every award price seen, one row per observation.

This is the raw record the baseline is computed from. It is deliberately dumb:
every poll appends, nothing is ever rewritten. Being able to reconstruct what
was true at any past hour matters more than keeping the file small, and a log
that edits history cannot be audited when a flagged deal turns out not to exist.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from .providers.base import AwardOption

FIELDS = [
    "observed_at",
    "program",
    "cabin",
    "direction",
    "flight_date",
    "miles",
    "taxes_usd",
    "seats",
    "carrier",
    "source",
    "estimated",
]


@dataclass(frozen=True)
class Observation:
    observed_at: dt.datetime
    program: str
    cabin: str
    direction: str
    flight_date: dt.date
    miles: int
    taxes_usd: float | None
    seats: int | None
    carrier: str | None
    source: str
    estimated: bool

    @property
    def slot(self) -> str:
        """The unit a baseline is computed over: one leg, one cabin, one date."""
        return f"{self.program}|{self.cabin}|{self.direction}|{self.flight_date:%Y-%m-%d}"

    def row(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at.isoformat(timespec="seconds"),
            "program": self.program,
            "cabin": self.cabin,
            "direction": self.direction,
            "flight_date": self.flight_date.isoformat(),
            "miles": self.miles,
            "taxes_usd": "" if self.taxes_usd is None else f"{self.taxes_usd:.2f}",
            "seats": "" if self.seats is None else self.seats,
            "carrier": self.carrier or "",
            "source": self.source,
            "estimated": int(self.estimated),
        }


def from_options(options: list[AwardOption], when: dt.datetime | None = None) -> list[Observation]:
    when = when or dt.datetime.now(dt.timezone.utc)
    return [
        Observation(
            observed_at=when,
            program=o.program,
            cabin=o.cabin,
            direction=o.direction,
            flight_date=o.date,
            miles=o.miles,
            taxes_usd=o.taxes_usd,
            seats=o.seats,
            carrier=o.carrier,
            source=o.source,
            estimated=o.estimated,
        )
        for o in options
    ]


def append(path: str | Path, observations: list[Observation]) -> int:
    """Append rows, writing a header if the file is new. Returns rows written."""
    if not observations:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for obs in observations:
            writer.writerow(obs.row())
    return len(observations)


def load(path: str | Path) -> list[Observation]:
    path = Path(path)
    if not path.exists():
        return []

    out: list[Observation] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out.append(
                    Observation(
                        observed_at=dt.datetime.fromisoformat(row["observed_at"]),
                        program=row["program"],
                        cabin=row["cabin"],
                        direction=row["direction"],
                        flight_date=dt.date.fromisoformat(row["flight_date"]),
                        miles=int(row["miles"]),
                        taxes_usd=float(row["taxes_usd"]) if row["taxes_usd"] else None,
                        seats=int(row["seats"]) if row["seats"] else None,
                        carrier=row["carrier"] or None,
                        source=row["source"],
                        estimated=row["estimated"] == "1",
                    )
                )
            except (KeyError, ValueError):
                # A malformed row must not take down the whole history.
                continue
    return out
