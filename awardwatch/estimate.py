"""Baseline award-cost estimates, used when no live provider has data."""

from __future__ import annotations

from pathlib import Path

import yaml

from .config import Trip
from .providers.base import AwardOption


def load_baselines(path: str | Path) -> dict[str, dict[str, dict]]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return raw.get("baselines", {}) or {}


def anchor_dates(trip: Trip) -> tuple[object, object] | None:
    """A representative legal (outbound, return) pair for the window.

    A static chart says nothing about which day is cheaper, so fanning estimates
    across every date would just be fake precision. Instead pick the one pairing
    that anchors the trip: leave as late as the arrival deadline allows, and come
    home as soon as the required days on the ground are served. That is the
    shortest legal trip, which is what a planning figure should describe.
    """
    for out in reversed(trip.outbound.dates()):
        for back in trip.ret.dates():
            if trip.constraints.check(out, back) is None:
                return out, back
    return None


def estimated_options(
    trip: Trip, baselines: dict[str, dict[str, dict]], programs: list[str]
) -> list[AwardOption]:
    anchors = anchor_dates(trip)
    if anchors is None:
        return []
    out_date, back_date = anchors

    options: list[AwardOption] = []
    for direction, date in (("outbound", out_date), ("return", back_date)):
        origin = trip.origin if direction == "outbound" else trip.destination
        dest = trip.destination if direction == "outbound" else trip.origin
        for program in programs:
            for cabin in trip.cabins:
                row = (baselines.get(program) or {}).get(cabin)
                if not row:
                    continue
                options.append(
                    AwardOption(
                        program=program,
                        direction=direction,
                        origin=origin,
                        destination=dest,
                        date=date,
                        cabin=cabin,
                        miles=int(row["miles"]),
                        taxes_usd=row.get("taxes_usd"),
                        seats=None,
                        source="baseline",
                        detail_url=None,
                        estimated=True,
                    )
                )
    return options
