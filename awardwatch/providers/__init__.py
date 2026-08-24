"""Pluggable award-availability sources."""

from __future__ import annotations

import os

from .base import AwardOption, Provider
from .fixture import FixtureProvider
from .seatsaero import SeatsAeroProvider

__all__ = ["AwardOption", "Provider", "build"]


def build(names: tuple[str, ...] | list[str]) -> list[Provider]:
    """Instantiate the configured providers, skipping any that cannot run.

    A provider that has no credentials is skipped with a note rather than
    raising -- the rest of the report is still worth producing without it.
    """
    built: list[Provider] = []
    for name in names:
        if name == "seatsaero":
            key = os.environ.get("SEATS_AERO_API_KEY", "").strip()
            if not key:
                print("[providers] skipping seatsaero: SEATS_AERO_API_KEY is not set")
                continue
            built.append(SeatsAeroProvider(key))
        elif name == "fixture":
            built.append(FixtureProvider())
        else:
            print(f"[providers] skipping unknown provider {name!r}")
    return built
