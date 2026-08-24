"""Baseline award-cost estimates, used when no live provider has data."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from .config import Trip
from .providers.base import AwardOption


def load_baselines(path: str | Path) -> dict[str, dict[str, dict]]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return raw.get("baselines", {}) or {}


def estimated_options(
    trip: Trip, baselines: dict[str, dict[str, dict]], programs: list[str]
) -> list[AwardOption]:
    """One estimate per programme, per cabin, per direction.

    Anchored to the middle of each window rather than fanned across every date,
    because a static chart says nothing about which day is cheaper -- pretending
    otherwise would just pad the table with fake precision.
    """
    out: list[AwardOption] = []
    for direction in ("outbound", "return"):
        window = trip.outbound if direction == "outbound" else trip.ret
        origin = trip.origin if direction == "outbound" else trip.destination
        dest = trip.destination if direction == "outbound" else trip.origin
        mid = window.start + dt.timedelta(days=(window.end - window.start).days // 2)

        for program in programs:
            for cabin in trip.cabins:
                row = (baselines.get(program) or {}).get(cabin)
                if not row:
                    continue
                out.append(
                    AwardOption(
                        program=program,
                        direction=direction,
                        origin=origin,
                        destination=dest,
                        date=mid,
                        cabin=cabin,
                        miles=int(row["miles"]),
                        taxes_usd=row.get("taxes_usd"),
                        seats=None,
                        source="baseline",
                        detail_url=None,
                        estimated=True,
                    )
                )
    return out
