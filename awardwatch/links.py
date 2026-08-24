"""Deep links into each programme's own award search.

This is the free fallback. No API, no scraping, no terms-of-service problem:
the tool works out exactly which searches are worth running and hands you the
URLs, so a manual sweep takes a couple of minutes instead of an hour.
"""

from __future__ import annotations

import datetime as dt

from .config import Trip

# %(o)s origin, %(d)s destination, %(iso)s YYYY-MM-DD, %(dmy)s DD/MM/YYYY
TEMPLATES: dict[str, str] = {
    "virgin": (
        "https://www.virginatlantic.com/flight-search/search?origin=%(o)s"
        "&destination=%(d)s&departureDate=%(iso)s&adults=1&awardTravel=true"
    ),
    "qatar_avios": (
        "https://booking.qatarairways.com/nsp/views/showBooking.action"
        "?widget=QR&searchType=F&bookingClass=B&tripType=O"
        "&fromStation=%(o)s&toStation=%(d)s&departingDate=%(iso)s&allowRedemption=Y"
    ),
    "ba_avios": (
        "https://www.britishairways.com/travel/redeem/execclub/_gf/en_gb"
        "?eId=111011&departurePoint=%(o)s&destinationPoint=%(d)s"
        "&departInputDate=%(dmy)s&oneWay=on&CabinCode=C"
    ),
    "etihad": "https://www.etihad.com/en-in/book/",
    "asiamiles": "https://www.cathaypacific.com/cx/en_IN/book-a-trip/redeem-flights.html",
}

# seats.aero's web search is usable on the free tier even though its API is not.
SEATS_AERO = (
    "https://seats.aero/search?origin=%(o)s&destination=%(d)s"
    "&startDate=%(iso)s&endDate=%(end)s&cabin=%(cabin)s"
)


def _fields(origin: str, dest: str, date: dt.date) -> dict[str, str]:
    return {
        "o": origin,
        "d": dest,
        "iso": date.isoformat(),
        "dmy": date.strftime("%d/%m/%Y"),
    }


def program_link(program: str, origin: str, dest: str, date: dt.date) -> str:
    template = TEMPLATES.get(program)
    if not template:
        return ""
    try:
        return template % _fields(origin, dest, date)
    except (KeyError, ValueError):
        return template


def seats_aero_link(trip: Trip, direction: str, cabin: str) -> str:
    window = trip.outbound if direction == "outbound" else trip.ret
    origin = trip.origin if direction == "outbound" else trip.destination
    dest = trip.destination if direction == "outbound" else trip.origin
    fields = _fields(origin, dest, window.start)
    fields["end"] = window.end.isoformat()
    fields["cabin"] = cabin
    return SEATS_AERO % fields


def manual_sweep(trip: Trip, programs: list[str]) -> list[tuple[str, str, str, str]]:
    """(program, direction, label, url) rows for a hand sweep of the window."""
    rows: list[tuple[str, str, str, str]] = []
    for direction in ("outbound", "return"):
        window = trip.outbound if direction == "outbound" else trip.ret
        origin = trip.origin if direction == "outbound" else trip.destination
        dest = trip.destination if direction == "outbound" else trip.origin
        for program in programs:
            for date in window.dates():
                url = program_link(program, origin, dest, date)
                if url:
                    rows.append((program, direction, f"{origin}-{dest} {date:%d %b}", url))
    return rows
