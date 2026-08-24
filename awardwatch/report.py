"""Render the run as markdown."""

from __future__ import annotations

import datetime as dt

from .config import Config
from .links import program_link, seats_aero_link
from .rank import Rejection, RoundTrip
from .transfers import Conversion

MARKER = "<!-- awardwatch:report -->"


def _fmt_taxes(value: float | None) -> str:
    return f"${value:,.0f}" if value is not None else "-"


def transfer_table(conversions: list[Conversion]) -> str:
    lines = [
        "| Programme | Ratio | Miles from balance | Rate | Stranded MR | Verified |",
        "|---|---|---:|---:|---:|:--:|",
    ]
    for c in conversions:
        mr_per, miles_per = c.partner.ratio(c.tier)
        ratio = f"{mr_per:,}:{miles_per:,}"
        if c.bonus_pct:
            ratio += f" +{c.bonus_pct:.0f}%"
        lines.append(
            f"| {c.partner.name} | {ratio} | **{c.miles:,}** | "
            f"{c.effective_rate:.2f} | {c.mr_stranded:,} | "
            f"{'yes' if c.partner.verified else '**no**'} |"
        )
    return "\n".join(lines)


def trip_table(trips: list[RoundTrip], limit: int) -> str:
    if not trips:
        return "_No legal round trip found on this run._"
    lines = [
        "| | Programme | Cabin | Leave BOM | Land ORD | Leave US | Days in US "
        "| Round-trip miles | Taxes | vs balance |",
        "|:--:|---|---|---|---|---|---:|---:|---:|---|",
    ]
    for t in trips[:limit]:
        flag = "OK" if t.affordable else "short"
        verdict = "**covered**" if t.affordable else f"short {t.gap:,}"
        tag = " _(est)_" if t.estimated else ""
        lines.append(
            f"| {flag} | {t.program}{tag} | {t.cabin} | {t.out.date:%d %b} | "
            f"{t.arrival_date:%d %b} | {t.back.date:%d %b} | {t.full_days} | "
            f"{t.miles:,} | {_fmt_taxes(t.taxes_usd)} | {verdict} |"
        )
    return "\n".join(lines)


def rejection_table(rejections: list[Rejection]) -> str:
    if not rejections:
        return ""
    lines = [
        "",
        "### Ruled out by the trip constraints",
        "",
        "| Programme | Cabin | Why |",
        "|---|---|---|",
    ]
    for r in rejections:
        lines.append(f"| {r.program} | {r.cabin} | {r.reason} |")
    return "\n".join(lines) + "\n"


def constraints_block(cfg: Config) -> str:
    c = cfg.trip.constraints
    rows = []
    if c.arrive_by:
        rows.append(f"- On the ground in {cfg.trip.destination} by **{c.arrive_by:%d %b %Y}**")
    if c.depart_us_not_before:
        rows.append(f"- Cannot leave the US before **{c.depart_us_not_before:%d %b %Y}**")
    span = f"at least **{c.min_full_days_in_us}**"
    if c.max_full_days_in_us is not None:
        span += f" and at most {c.max_full_days_in_us}"
    rows.append(f"- {span} full non-flying days on the ground, either side of the event")
    return "\n".join(rows)


def links_section(cfg: Config, programs: list[str]) -> str:
    lines = ["Free manual checks (no API key needed):", ""]
    for direction in ("outbound", "return"):
        window = cfg.trip.outbound if direction == "outbound" else cfg.trip.ret
        origin = cfg.trip.origin if direction == "outbound" else cfg.trip.destination
        dest = cfg.trip.destination if direction == "outbound" else cfg.trip.origin
        lines.append(f"**{origin} to {dest}** ({window})")
        for cabin in cfg.trip.cabins:
            lines.append(
                f"- seats.aero, {cabin}: <{seats_aero_link(cfg.trip, direction, cabin)}>"
            )
        for program in programs:
            url = program_link(program, origin, dest, window.start)
            if url:
                lines.append(f"- {program}: <{url}>")
        lines.append("")
    return "\n".join(lines)


def render(
    cfg: Config,
    conversions: list[Conversion],
    trips: list[RoundTrip],
    new_keys: set[str],
    notes: list[str],
    rejections: list[Rejection] | None = None,
) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    programs = [c.partner.key for c in conversions]
    best = trips[0] if trips else None
    affordable = [t for t in trips if t.affordable]
    live = [t for t in trips if not t.estimated]

    parts = [
        MARKER,
        f"# Award watch: {cfg.trip.origin} to {cfg.trip.destination}, May 2027",
        "",
        f"_Updated {now:%Y-%m-%d %H:%M} UTC_",
        "",
        f"- Balance: **{cfg.mr_balance:,} Amex India MR** ({cfg.card_tier})",
        f"- Outbound {cfg.trip.origin}-{cfg.trip.destination}: {cfg.trip.outbound}",
        f"- Return {cfg.trip.destination}-{cfg.trip.origin}: {cfg.trip.ret}",
        f"- Cabins: {', '.join(cfg.trip.cabins)}",
        f"- Best convertible balance: **{max((c.miles for c in conversions), default=0):,} miles**",
        "",
        "**Trip constraints**",
        "",
        constraints_block(cfg),
        "",
    ]

    if best:
        status = (
            f"Cheapest legal round trip is **{best.miles:,} miles** ({best.program}, "
            f"{best.cabin}){' - estimate only' if best.estimated else ''}: "
            f"leave BOM {best.out.date:%d %b}, land {best.arrival_date:%d %b}, "
            f"leave the US {best.back.date:%d %b}, {best.full_days} full days. "
        )
        status += (
            f"{len(affordable)} of {len(trips)} options are covered by the balance."
            if affordable
            else f"Nothing is covered by the balance yet; closest is short **{best.gap:,} miles**."
        )
        parts += ["## Status", "", status, ""]

    if new_keys:
        parts += [f"**{len(new_keys)} new option(s) since the last run.**", ""]

    parts += [
        "## (b) Round trips found",
        "",
        trip_table(trips, int(cfg.alerts.get("max_rows", 30))),
        "",
        rejection_table(rejections or []),
    ]
    if not live:
        parts += [
            "> Every row above is a static-chart **estimate**, not live availability -- "
            "no live provider returned data on this run. Treat the numbers as planning "
            "figures only and confirm with the links below.",
            "",
        ]

    parts += [
        "## (a) What 115k MR converts into",
        "",
        transfer_table(conversions),
        "",
        "> Ratios marked **no** under Verified have not been confirmed against "
        "americanexpress.com/in. Confirm before transferring -- transfers are irreversible.",
        "",
        "## Check these yourself",
        "",
        links_section(cfg, programs),
    ]

    if notes:
        parts += ["## Run notes", ""] + [f"- {n}" for n in notes] + [""]

    return "\n".join(parts)
