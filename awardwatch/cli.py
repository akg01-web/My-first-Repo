"""Entry point: python -m awardwatch [--config config.yaml] [--dry-run]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_mod
from . import baseline, estimate, notify, observations, providers, report, transfers
from .rank import build_round_trips
from .state import State


def run(config_path: str, dry_run: bool, out_path: str | None, optimize: str = "miles") -> int:
    cfg = config_mod.load(config_path)
    notes: list[str] = []

    partners = transfers.load_partners(cfg.partners_path)
    conversions = transfers.convert_all(
        partners, cfg.mr_balance, cfg.card_tier, cfg.bonus_pct
    )
    by_key = {c.partner.key: c for c in conversions}

    unverified = [c.partner.key for c in conversions if not c.partner.verified]
    if unverified:
        notes.append(
            f"{len(unverified)} transfer ratio(s) still unverified: {', '.join(unverified)}."
        )

    # A programme that has no such cabin on this route cannot be searched for
    # it -- say so once rather than reporting "no availability" every run.
    impossible = [
        (p.key, cabin)
        for p in partners
        for cabin in cfg.trip.cabins
        if p.cabins_available and cabin not in p.cabins_available
    ]
    for program, cabin in impossible:
        notes.append(f"{program} has no {cabin} cabin on this route; not searched.")

    options = []
    active = providers.build(cfg.providers)
    if not active:
        notes.append("No live provider was available; falling back to chart estimates.")
    for provider in active:
        for direction in ("outbound", "return"):
            for cabin in cfg.trip.cabins:
                found = provider.search(cfg.trip, direction, cabin)
                options.extend(found)
                print(f"[{provider.name}] {direction}/{cabin}: {len(found)} option(s)")

    if not options:
        baselines = estimate.load_baselines(cfg.baselines_path)
        options = estimate.estimated_options(cfg.trip, baselines, list(by_key))

    options = [
        o for o in options
        if not (
            by_key.get(o.program)
            and by_key[o.program].partner.cabins_available
            and o.cabin not in by_key[o.program].partner.cabins_available
        )
    ]

    # Log every confirmed observation before anything is ranked or filtered:
    # the baseline must reflect what was actually offered, not what survived
    # this run's trip constraints.
    log_path = cfg.state_path.parent / "data" / "observations.csv"
    fresh = observations.from_options([o for o in options if not o.estimated])
    history = observations.load(log_path)
    bases = baseline.build(history)

    deals = baseline.find_deals(fresh, bases)
    established, total = baseline.coverage(bases, min_rows=24, min_hours=48.0)
    if total:
        notes.append(
            f"Baseline: {established}/{total} slots have enough history to judge "
            f"against (need 24+ observations over 48+ hours)."
        )
    for deal in deals[:10]:
        notes.append(f"DEAL: {deal.describe()}")

    if not dry_run and fresh:
        written = observations.append(log_path, fresh)
        print(f"[log] appended {written} observation(s) to {log_path}")

    trips, rejections = build_round_trips(
        options, by_key, cfg.trip.constraints, optimize
    )

    state = State(cfg.state_path)
    new_keys: set[str] = set()
    for trip in trips:
        if trip.estimated:
            continue
        if state.is_new(trip.key()):
            new_keys.add(trip.key())
            state.mark(trip.key())
        previous = state.record(trip.program, trip.cabin, trip.miles)
        if previous is not None and trip.miles < previous:
            notes.append(
                f"{trip.program} {trip.cabin} dropped {previous:,} -> {trip.miles:,} miles."
            )

    if rejections:
        notes.append(
            f"{len(rejections)} programme/cabin combination(s) had availability but no "
            "pairing that satisfies the trip constraints."
        )

    ceiling = cfg.alerts.get("max_miles_roundtrip")
    if ceiling:
        trips = [t for t in trips if t.miles <= int(ceiling)]

    body = report.render(cfg, conversions, trips, new_keys, notes, rejections)

    if out_path:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        print(f"[report] wrote {target}")

    if dry_run:
        print(body)
        return 0

    state.save()
    if cfg.alerts.get("github_issue"):
        notify.publish(
            body,
            str(cfg.alerts.get("issue_title", "Award watch")),
            comment_on_change=bool(new_keys),
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awardwatch")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="print, do not publish or save state")
    parser.add_argument("--out", default=None, help="also write the report to this path")
    parser.add_argument(
        "--optimize",
        choices=("miles", "cash"),
        default="miles",
        help="rank by mileage cost (default) or by out-of-pocket cash",
    )
    args = parser.parse_args(argv)
    return run(args.config, args.dry_run, args.out, args.optimize)


if __name__ == "__main__":
    sys.exit(main())
