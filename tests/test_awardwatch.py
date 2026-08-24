"""Unit tests. Run with: python -m pytest -q  (or python tests/test_awardwatch.py)"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from awardwatch import config, estimate, transfers  # noqa: E402
from awardwatch.providers.fixture import FixtureProvider  # noqa: E402
from awardwatch.rank import build_round_trips  # noqa: E402


def _cfg():
    return config.load("config.yaml")


def test_window_expands_inclusively():
    w = config.DateWindow(dt.date(2027, 5, 1), dt.date(2027, 5, 5))
    assert len(w.dates()) == 5
    assert w.dates()[0] == dt.date(2027, 5, 1)
    assert w.dates()[-1] == dt.date(2027, 5, 5)


def test_standard_tier_halves_the_balance():
    partners = transfers.load_partners(_cfg().partners_path)
    fb = next(p for p in partners if p.key == "flyingblue")
    conv = transfers.convert(fb, 115_000, "standard")
    assert conv.miles == 57_500
    assert conv.mr_stranded == 0


def test_platinum_charge_is_one_to_one():
    partners = transfers.load_partners(_cfg().partners_path)
    fb = next(p for p in partners if p.key == "flyingblue")
    assert transfers.convert(fb, 115_000, "platinum_charge").miles == 115_000


def test_transfer_bonus_applies():
    partners = transfers.load_partners(_cfg().partners_path)
    fb = next(p for p in partners if p.key == "flyingblue")
    assert transfers.convert(fb, 115_000, "standard", bonus_pct=20).miles == 69_000


def test_partial_block_is_stranded():
    partners = transfers.load_partners(_cfg().partners_path)
    fb = next(p for p in partners if p.key == "flyingblue")
    conv = transfers.convert(fb, 115_600, "standard")
    assert conv.mr_spent == 115_000
    assert conv.mr_stranded == 600


def test_below_minimum_converts_nothing():
    partners = transfers.load_partners(_cfg().partners_path)
    fb = next(p for p in partners if p.key == "flyingblue")
    conv = transfers.convert(fb, 500, "standard")
    assert conv.miles == 0 and conv.mr_stranded == 500


def test_fixture_provider_respects_the_window():
    cfg = _cfg()
    rows = FixtureProvider().search(cfg.trip, "outbound", "business")
    assert rows, "fixture returned nothing"
    assert all(cfg.trip.outbound.start <= r.date <= cfg.trip.outbound.end for r in rows)
    assert all(r.direction == "outbound" and r.cabin == "business" for r in rows)


def test_round_trip_pairs_the_cheapest_halves():
    cfg = _cfg()
    partners = transfers.load_partners(cfg.partners_path)
    convs = {c.partner.key: c for c in transfers.convert_all(partners, cfg.mr_balance)}

    options = []
    for direction in ("outbound", "return"):
        for cabin in cfg.trip.cabins:
            options += FixtureProvider().search(cfg.trip, direction, cabin)

    trips = build_round_trips(options, convs)
    fb_j = next(t for t in trips if t.program == "flyingblue" and t.cabin == "business")
    # 76,000 is the cheaper of the two outbound business fixtures.
    assert fb_j.out.miles == 76_000
    assert fb_j.miles == 76_000 + 82_000
    assert not fb_j.affordable
    assert fb_j.gap == 158_000 - 57_500


def test_estimates_never_outrank_live_availability():
    cfg = _cfg()
    partners = transfers.load_partners(cfg.partners_path)
    convs = {c.partner.key: c for c in transfers.convert_all(partners, cfg.mr_balance)}
    baselines = estimate.load_baselines(cfg.baselines_path)

    options = estimate.estimated_options(cfg.trip, baselines, list(convs))
    for direction in ("outbound", "return"):
        for cabin in cfg.trip.cabins:
            options += FixtureProvider().search(cfg.trip, direction, cabin)

    trips = build_round_trips(options, convs)
    live = [i for i, t in enumerate(trips) if not t.estimated]
    est = [i for i, t in enumerate(trips) if t.estimated]
    assert max(live) < min(est)


def test_mr_needed_rounds_up_to_a_whole_block():
    partners = transfers.load_partners(_cfg().partners_path)
    fb = next(p for p in partners if p.key == "flyingblue")
    conv = transfers.convert(fb, 115_000, "standard")
    # 2 MR per mile, so 158,000 miles needs 316,000 MR.
    assert conv.mr_needed_for(158_000) == 316_000


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
