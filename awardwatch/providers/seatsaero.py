"""seats.aero Partner API client.

seats.aero is the only award-availability source with a documented REST API
that covers the programmes Amex India feeds. The Partner API is a paid add-on;
there is no free API key (see README for what to do about that). This client
is written defensively because the response shape is not something we can
pin -- unknown fields are ignored and missing ones degrade to None.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

from ..config import Trip
from .base import AwardOption

API_ROOT = "https://seats.aero/partnerapi"

# seats.aero calls its programmes "sources". Map ours onto theirs.
SOURCE_TO_PARTNER = {
    "singapore": "krisflyer",
    "emirates": "emirates",
    "etihad": "etihad",
    "americanairlines": "ba_avios",
    "british": "ba_avios",
    "qatar": "ba_avios",
    "flyingblue": "flyingblue",
    "airindia": "maharaja",
}

# seats.aero encodes cabin as a single letter in its field names.
CABIN_CODE = {"economy": "Y", "premium": "W", "business": "J", "first": "F"}


class SeatsAeroProvider:
    name = "seatsaero"

    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str]) -> dict:
        url = f"{API_ROOT}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "Partner-Authorization": self.api_key,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search(self, trip: Trip, direction: str, cabin: str) -> list[AwardOption]:
        window = trip.outbound if direction == "outbound" else trip.ret
        origin = trip.origin if direction == "outbound" else trip.destination
        dest = trip.destination if direction == "outbound" else trip.origin

        params = {
            "origin_airport": origin,
            "destination_airport": dest,
            "start_date": window.start.isoformat(),
            "end_date": window.end.isoformat(),
            "cabin": cabin,
            "take": "500",
        }

        try:
            payload = self._get("search", params)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            print(f"[seatsaero] HTTP {exc.code} for {origin}-{dest} {cabin}: {body}")
            return []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[seatsaero] request failed for {origin}-{dest} {cabin}: {exc}")
            return []

        return self._parse(payload, direction, origin, dest, cabin)

    def _parse(
        self, payload: dict, direction: str, origin: str, dest: str, cabin: str
    ) -> list[AwardOption]:
        code = CABIN_CODE.get(cabin, "J")
        out: list[AwardOption] = []

        for row in payload.get("data", []) or []:
            if not row.get(f"{code}Available"):
                continue

            miles = _int(row.get(f"{code}MileageCost"))
            if not miles:
                continue

            route = row.get("Route") or {}
            source = str(row.get("Source", "")).lower()
            program = SOURCE_TO_PARTNER.get(source)
            if program is None:
                # A programme Amex India cannot reach. Not useful here.
                continue

            date = _date(row.get("Date"))
            if date is None:
                continue

            # Taxes come back in the smallest currency unit.
            taxes = _int(row.get(f"{code}TotalTaxes"))
            taxes_usd = round(taxes / 100.0, 2) if taxes else None

            out.append(
                AwardOption(
                    program=program,
                    direction=direction,
                    origin=str(route.get("OriginAirport") or origin),
                    destination=str(route.get("DestinationAirport") or dest),
                    date=date,
                    cabin=cabin,
                    miles=miles,
                    taxes_usd=taxes_usd,
                    seats=_int(row.get(f"{code}RemainingSeats")) or None,
                    source=self.name,
                    detail_url=_detail_url(row),
                    carrier=row.get(f"{code}Airlines") or None,
                )
            )
        return out


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _date(value: object) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _detail_url(row: dict) -> str | None:
    ident = row.get("ID") or row.get("id")
    return f"https://seats.aero/availability/{ident}" if ident else None
