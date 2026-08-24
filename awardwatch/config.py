"""Load and validate config.yaml."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

CABINS = ("business", "premium", "economy")


@dataclass(frozen=True)
class DateWindow:
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"window ends ({self.end}) before it starts ({self.start})")

    def dates(self) -> list[dt.date]:
        span = (self.end - self.start).days
        return [self.start + dt.timedelta(days=i) for i in range(span + 1)]

    def __str__(self) -> str:
        return f"{self.start:%Y-%m-%d}..{self.end:%Y-%m-%d}"


@dataclass(frozen=True)
class Constraints:
    """Rules a candidate round trip has to satisfy to be worth showing.

    The trip is anchored by a fixed event -- be on the ground by `arrive_by`,
    cannot leave before `depart_us_not_before` -- with a required number of
    full days on the ground that may fall on either side of it.
    """

    arrive_by: dt.date | None = None
    depart_us_not_before: dt.date | None = None
    min_full_days_in_us: int = 0
    max_full_days_in_us: int | None = None
    outbound_transit_days: int = 1
    return_transit_days: int = 1

    def arrival_date(self, outbound_departure: dt.date) -> dt.date:
        return outbound_departure + dt.timedelta(days=self.outbound_transit_days)

    def full_days(self, outbound_departure: dt.date, us_departure: dt.date) -> int:
        """Whole days on the ground, counting neither travel day."""
        return (us_departure - self.arrival_date(outbound_departure)).days - 1

    def check(self, outbound_departure: dt.date, us_departure: dt.date) -> str | None:
        """None if the pairing is legal, else why it is not."""
        arrival = self.arrival_date(outbound_departure)
        if self.arrive_by and arrival > self.arrive_by:
            return f"lands {arrival:%d %b}, after the {self.arrive_by:%d %b} deadline"
        if self.depart_us_not_before and us_departure < self.depart_us_not_before:
            return f"leaves {us_departure:%d %b}, before {self.depart_us_not_before:%d %b}"
        days = self.full_days(outbound_departure, us_departure)
        if days < self.min_full_days_in_us:
            return f"only {days} full day(s), need {self.min_full_days_in_us}"
        if self.max_full_days_in_us is not None and days > self.max_full_days_in_us:
            return f"{days} full days, over the {self.max_full_days_in_us} cap"
        return None


@dataclass(frozen=True)
class Trip:
    origin: str
    destination: str
    passengers: int
    outbound: DateWindow
    ret: DateWindow
    cabins: tuple[str, ...]
    constraints: Constraints = field(default_factory=Constraints)


@dataclass(frozen=True)
class Config:
    mr_balance: int
    card_tier: str
    bonus_pct: dict[str, float]
    trip: Trip
    providers: tuple[str, ...]
    alerts: dict[str, Any]
    partners_path: Path
    baselines_path: Path
    state_path: Path


def _opt_date(value: object) -> dt.date | None:
    return dt.date.fromisoformat(str(value)) if value else None


def _window(raw: dict[str, str], label: str) -> DateWindow:
    try:
        return DateWindow(
            dt.date.fromisoformat(str(raw["start"])),
            dt.date.fromisoformat(str(raw["end"])),
        )
    except KeyError as exc:
        raise ValueError(f"{label} needs both 'start' and 'end'") from exc


def load(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    raw = yaml.safe_load(path.read_text()) or {}

    points = raw.get("points", {})
    balance = int(points.get("amex_in_mr", 0))
    if balance <= 0:
        raise ValueError("points.amex_in_mr must be a positive number")

    tier = str(points.get("card_tier", "standard"))
    if tier not in ("standard", "platinum_charge"):
        raise ValueError(f"unknown card_tier {tier!r}")

    t = raw.get("trip", {})
    cabins = tuple(str(c).lower() for c in t.get("cabins", ["business"]))
    unknown = [c for c in cabins if c not in CABINS]
    if unknown:
        raise ValueError(f"unknown cabin(s) {unknown}; pick from {list(CABINS)}")

    c = t.get("constraints", {}) or {}
    max_days = c.get("max_full_days_in_us")
    constraints = Constraints(
        arrive_by=_opt_date(c.get("arrive_by")),
        depart_us_not_before=_opt_date(c.get("depart_us_not_before")),
        min_full_days_in_us=int(c.get("min_full_days_in_us", 0)),
        max_full_days_in_us=None if max_days is None else int(max_days),
        outbound_transit_days=int(c.get("outbound_transit_days", 1)),
        return_transit_days=int(c.get("return_transit_days", 1)),
    )
    if (
        constraints.max_full_days_in_us is not None
        and constraints.max_full_days_in_us < constraints.min_full_days_in_us
    ):
        raise ValueError("max_full_days_in_us is below min_full_days_in_us")

    trip = Trip(
        origin=str(t.get("origin", "")).upper(),
        destination=str(t.get("destination", "")).upper(),
        passengers=int(t.get("passengers", 1)),
        outbound=_window(t["outbound_window"], "trip.outbound_window"),
        ret=_window(t["return_window"], "trip.return_window"),
        cabins=cabins,
        constraints=constraints,
    )
    if len(trip.origin) != 3 or len(trip.destination) != 3:
        raise ValueError("trip.origin and trip.destination must be IATA codes")

    paths = raw.get("paths", {})
    return Config(
        mr_balance=balance,
        card_tier=tier,
        bonus_pct={str(k): float(v) for k, v in (points.get("bonus_pct") or {}).items()},
        trip=trip,
        providers=tuple(str(p) for p in raw.get("providers", [])),
        alerts=raw.get("alerts", {}) or {},
        partners_path=REPO_ROOT / paths.get("partners", "data/amex_in_partners.yaml"),
        baselines_path=REPO_ROOT / paths.get("baselines", "data/award_baselines.yaml"),
        state_path=REPO_ROOT / paths.get("state", ".awardwatch_state.json"),
    )
