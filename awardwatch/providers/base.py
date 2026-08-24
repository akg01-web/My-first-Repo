"""Shared provider types."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

from ..config import Trip


@dataclass(frozen=True)
class AwardOption:
    """One bookable (or estimated) award on one date, in one direction."""

    program: str          # partner key, e.g. "flyingblue"
    direction: str        # "outbound" | "return"
    origin: str
    destination: str
    date: dt.date
    cabin: str            # "business" | "premium" | "economy"
    miles: int            # per passenger, one way
    taxes_usd: float | None
    seats: int | None
    source: str           # which provider produced this
    detail_url: str | None = None
    estimated: bool = False
    carrier: str | None = None

    def key(self) -> str:
        """Stable identity, used to tell a new find from one already alerted."""
        return f"{self.program}|{self.direction}|{self.date:%Y%m%d}|{self.cabin}|{self.miles}"


class Provider(Protocol):
    name: str

    def search(
        self, trip: Trip, direction: str, cabin: str
    ) -> list[AwardOption]: ...
