"""Entry point: python -m awardwatch [--config config.yaml] [--dry-run]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_mod
from . import estimate, notify, providers, report, transfers
from .rank import build_round_trips
from .state import State


def run(config_path: str, dry_run: bool, out_path: str | None) -> int:
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

    trips = build_round_trips(options, by_key)

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

    ceiling = cfg.alerts.get("max_miles_roundtrip")
    if ceiling:
        trips = [t for t in trips if t.miles <= int(ceiling)]

    body = report.render(cfg, conversions, trips, new_keys, notes)

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
    args = parser.parse_args(argv)
    return run(args.config, args.dry_run, args.out)


if __name__ == "__main__":
    sys.exit(main())
