"""Pair one-way options into legal round trips and price them against the balance."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from .config import Constraints
from .providers.base import AwardOption
from .transfers import Conversion


@dataclass(frozen=True)
class RoundTrip:
    program: str
    cabin: str
    out: AwardOption
    back: AwardOption
    conversion: Conversion
    constraints: Constraints

    @property
    def miles(self) -> int:
        return self.out.miles + self.back.miles

    @property
    def taxes_usd(self) -> float | None:
        parts = [p for p in (self.out.taxes_usd, self.back.taxes_usd) if p is not None]
        return round(sum(parts), 2) if parts else None

    @property
    def estimated(self) -> bool:
        return self.out.estimated or self.back.estimated

    @property
    def arrival_date(self) -> dt.date:
        return self.constraints.arrival_date(self.out.date)

    @property
    def home_date(self) -> dt.date:
        return self.back.date + dt.timedelta(days=self.constraints.return_transit_days)

    @property
    def full_days(self) -> int:
        return self.constraints.full_days(self.out.date, self.back.date)

    @property
    def affordable(self) -> bool:
        return self.conversion.miles >= self.miles

    @property
    def gap(self) -> int:
        """Miles still missing. Zero when the balance already covers it."""
        return max(0, self.miles - self.conversion.miles)

    @property
    def mr_needed(self) -> int:
        return self.conversion.mr_needed_for(self.miles)

    def key(self) -> str:
        return f"{self.out.key()}+{self.back.key()}"


@dataclass(frozen=True)
class Rejection:
    """A programme/cabin that had availability but no legal pairing of it."""

    program: str
    cabin: str
    reason: str


def build_round_trips(
    options: list[AwardOption],
    conversions: dict[str, Conversion],
    constraints: Constraints | None = None,
    optimize: str = "miles",
) -> tuple[list[RoundTrip], list[Rejection]]:
    """Cheapest *legal* outbound/return pairing per programme and cabin.

    The two halves cannot be chosen independently any more: the trip is anchored
    by a fixed date on the ground, so the cheapest outbound may only pair with a
    return far enough after it. This walks every combination -- the windows are
    weeks, not months, so the cross product stays small -- and keeps the cheapest
    pairing that survives the constraints.
    """
    constraints = constraints or Constraints()

    legs: dict[tuple[str, str, str], list[AwardOption]] = defaultdict(list)
    for opt in options:
        legs[(opt.program, opt.cabin, opt.direction)].append(opt)

    slots = {(p, c) for (p, c, _) in legs}
    trips: list[RoundTrip] = []
    rejections: list[Rejection] = []

    for program, cabin in sorted(slots):
        conv = conversions.get(program)
        outbound = legs.get((program, cabin, "outbound"), [])
        inbound = legs.get((program, cabin, "return"), [])

        if conv is None:
            continue
        if not outbound or not inbound:
            missing = "outbound" if not outbound else "return"
            rejections.append(Rejection(program, cabin, f"no {missing} availability"))
            continue

        best: RoundTrip | None = None
        reasons: list[str] = []
        for out in outbound:
            for back in inbound:
                why = constraints.check(out.date, back.date)
                if why:
                    reasons.append(why)
                    continue
                candidate = RoundTrip(program, cabin, out, back, conv, constraints)
                if best is None or _cost(candidate, optimize) < _cost(best, optimize):
                    best = candidate

        if best is not None:
            trips.append(best)
        else:
            # Surface the most common blocker rather than an arbitrary one.
            reason = max(set(reasons), key=reasons.count) if reasons else "no legal pairing"
            rejections.append(Rejection(program, cabin, reason))

    # Real availability first, then cheapest, so estimates never outrank a
    # bookable seat at the same price.
    trips.sort(key=lambda t: (t.estimated, _cost(t, optimize)))
    return trips, rejections


def _cost(trip: RoundTrip, optimize: str) -> tuple[float, float]:
    """Sort key. The secondary axis breaks ties on the primary one."""
    cash = trip.taxes_usd if trip.taxes_usd is not None else float("inf")
    if optimize == "cash":
        return (cash, trip.miles)
    return (trip.miles, cash)
