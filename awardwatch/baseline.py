"""Per-slot baselines, and what counts as a deal against them.

The statistics here are deliberately conservative, because the failure mode
that matters is crying wolf: a flagged deal that turns out not to exist costs
trust, and trust is the only thing this tool has.

Two properties of award data drive the design.

First, prices are heavily autocorrelated. Polling hourly for three days gives
72 rows, but if the price never moved they carry the information of a single
observation. Sample counts are therefore measured in *distinct values* and in
elapsed hours, not in rows.

Second, the common case is zero variance -- a slot sits at one number for days.
Standard deviation is then 0, every drop divides by zero and looks infinitely
significant. So a proportional floor does the work whenever spread collapses,
and robust statistics (median, MAD) are used throughout rather than mean and
standard deviation, which one outlier would drag around.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from .observations import Observation

# Scales MAD to be comparable with a standard deviation on normal data.
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Baseline:
    slot: str
    median_miles: float
    spread: float          # MAD, scaled
    best_seen: int
    worst_seen: int
    n_rows: int
    n_distinct: int
    first_seen: dt.datetime
    last_seen: dt.datetime

    @property
    def hours_observed(self) -> float:
        return (self.last_seen - self.first_seen).total_seconds() / 3600.0

    def is_established(self, min_rows: int, min_hours: float) -> bool:
        """Enough history to judge a new price against.

        Distinct values are not required -- a slot that never moves is a
        perfectly good baseline. What is required is that we watched it for
        long enough to know that.
        """
        return self.n_rows >= min_rows and self.hours_observed >= min_hours


@dataclass(frozen=True)
class Deal:
    slot: str
    kind: str              # "price_drop" | "new_availability"
    miles: int
    baseline: Baseline | None
    drop_pct: float
    z: float | None        # None when spread collapsed and the floor decided

    def describe(self) -> str:
        if self.kind == "new_availability":
            return f"{self.slot}: availability appeared at {self.miles:,} miles"
        assert self.baseline is not None
        detail = f"{self.drop_pct:.0%} below a baseline of {self.baseline.median_miles:,.0f}"
        if self.z is not None:
            detail += f" ({self.z:.1f} MAD)"
        return f"{self.slot}: {self.miles:,} miles, {detail}"


def build(observations: list[Observation]) -> dict[str, Baseline]:
    """One baseline per slot, from confirmed observations only."""
    grouped: dict[str, list[Observation]] = {}
    for obs in observations:
        if obs.estimated:
            continue  # An estimate is our own guess; it cannot inform a baseline.
        grouped.setdefault(obs.slot, []).append(obs)

    out: dict[str, Baseline] = {}
    for slot, rows in grouped.items():
        miles = [r.miles for r in rows]
        median = statistics.median(miles)
        mad = statistics.median([abs(m - median) for m in miles]) * MAD_TO_SIGMA
        stamps = [r.observed_at for r in rows]
        out[slot] = Baseline(
            slot=slot,
            median_miles=median,
            spread=mad,
            best_seen=min(miles),
            worst_seen=max(miles),
            n_rows=len(miles),
            n_distinct=len(set(miles)),
            first_seen=min(stamps),
            last_seen=max(stamps),
        )
    return out


def find_deals(
    current: list[Observation],
    baselines: dict[str, Baseline],
    min_rows: int = 24,
    min_hours: float = 48.0,
    min_drop_pct: float = 0.10,
    z_threshold: float = 3.0,
) -> list[Deal]:
    """Flag this poll's observations that beat their own history.

    A slot with no history is reported as new availability rather than as a
    price drop -- "there is a seat where there was none" is a different and
    often more valuable event than "the price moved", and conflating them would
    make the alert meaningless.
    """
    deals: list[Deal] = []

    for obs in current:
        if obs.estimated:
            continue

        base = baselines.get(obs.slot)
        if base is None or base.n_rows == 0:
            deals.append(Deal(obs.slot, "new_availability", obs.miles, None, 0.0, None))
            continue

        if not base.is_established(min_rows, min_hours):
            continue  # Not enough history yet to call anything a deal.

        if obs.miles >= base.median_miles:
            continue

        drop = (base.median_miles - obs.miles) / base.median_miles

        if base.spread > 0:
            z = (base.median_miles - obs.miles) / base.spread
            # Both tests must pass: a statistically large move that is
            # economically trivial is not a deal worth waking someone for.
            if z >= z_threshold and drop >= min_drop_pct:
                deals.append(Deal(obs.slot, "price_drop", obs.miles, base, drop, z))
        elif drop >= min_drop_pct:
            # Spread collapsed -- the slot never moved before. The proportional
            # floor is the only meaningful test available.
            deals.append(Deal(obs.slot, "price_drop", obs.miles, base, drop, None))

    deals.sort(key=lambda d: (d.kind != "price_drop", -d.drop_pct))
    return deals


def coverage(baselines: dict[str, Baseline], min_rows: int, min_hours: float) -> tuple[int, int]:
    """How many slots are ready to be judged against. (established, total)"""
    established = sum(1 for b in baselines.values() if b.is_established(min_rows, min_hours))
    return established, len(baselines)
