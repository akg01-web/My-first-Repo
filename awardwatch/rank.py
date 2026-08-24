"""Pair one-way options into round trips and price them against the balance."""

from __future__ import annotations

from dataclasses import dataclass

from .providers.base import AwardOption
from .transfers import Conversion


@dataclass(frozen=True)
class RoundTrip:
    program: str
    cabin: str
    out: AwardOption
    back: AwardOption
    conversion: Conversion

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
    def affordable(self) -> bool:
        return self.conversion.miles >= self.miles

    @property
    def gap(self) -> int:
        """Miles still missing. Zero when the balance already covers it."""
        return max(0, self.miles - self.conversion.miles)

    @property
    def mr_needed(self) -> int:
        return self.conversion.mr_needed_for(self.miles)

    @property
    def mr_shortfall(self) -> int:
        return max(0, self.mr_needed - self.conversion.mr_balance)

    def key(self) -> str:
        return f"{self.out.key()}+{self.back.key()}"


def build_round_trips(
    options: list[AwardOption], conversions: dict[str, Conversion]
) -> list[RoundTrip]:
    """Cheapest outbound paired with cheapest return, per programme and cabin.

    Award seats are booked one direction at a time, so there is no need to hold
    a single itinerary together -- the cheapest of each half is the real answer.
    """
    best: dict[tuple[str, str, str], AwardOption] = {}
    for opt in options:
        slot = (opt.program, opt.cabin, opt.direction)
        current = best.get(slot)
        if current is None or opt.miles < current.miles:
            best[slot] = opt

    trips: list[RoundTrip] = []
    seen = {(p, c) for (p, c, _) in best}
    for program, cabin in sorted(seen):
        out = best.get((program, cabin, "outbound"))
        back = best.get((program, cabin, "return"))
        conv = conversions.get(program)
        if out and back and conv:
            trips.append(RoundTrip(program, cabin, out, back, conv))

    # Real availability first, then cheapest, so estimates never outrank a
    # bookable seat at the same price.
    return sorted(trips, key=lambda t: (t.estimated, t.miles))
