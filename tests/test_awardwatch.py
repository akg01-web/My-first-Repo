"""Unit tests. Run with: python -m pytest -q  (or python tests/test_awardwatch.py)"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from awardwatch import config, estimate, report, transfers  # noqa: E402
from awardwatch.providers.fixture import FixtureProvider  # noqa: E402
from awardwatch.rank import build_round_trips  # noqa: E402


def _cfg():
    return config.load("config.yaml")


def test_window_expands_inclusively():
    w = config.DateWindow(dt.date(2027, 5, 1), dt.date(2027, 5, 5))
    assert len(w.dates()) == 5
    assert w.dates()[0] == dt.date(2027, 5, 1)
    assert w.dates()[-1] == dt.date(2027, 5, 5)


def _partner(key):
    return next(p for p in transfers.load_partners(_cfg().partners_path) if p.key == key)


def test_two_to_one_partners_halve_the_balance():
    conv = transfers.convert(_partner("etihad"), 115_000, "platinum_charge")
    assert conv.miles == 57_500
    assert conv.mr_stranded == 0


def test_virgin_ten_to_eight_is_the_best_ratio():
    conv = transfers.convert(_partner("virgin"), 115_000, "platinum_charge")
    assert conv.miles == 92_000
    assert conv.effective_rate == 0.8


def test_platinum_charge_is_not_one_to_one_anywhere():
    # Confirmed with the concierge: the roster tops out at 10:8, not 1:1.
    cfg = _cfg()
    for p in transfers.load_partners(cfg.partners_path):
        mr_per, miles_per = p.ratio("platinum_charge")
        assert miles_per < mr_per


def test_every_ratio_is_concierge_confirmed():
    for p in transfers.load_partners(_cfg().partners_path):
        assert p.verified, f"{p.key} is not marked verified"
        assert p.last_checked


def test_avios_partners_share_one_currency():
    partners = {p.key: p for p in transfers.load_partners(_cfg().partners_path)}
    assert partners["ba_avios"].currency == partners["qatar_avios"].currency == "avios"
    # ...and nothing else collides with them.
    others = [p.currency for k, p in partners.items() if k not in ("ba_avios", "qatar_avios")]
    assert "avios" not in others


def test_transfer_bonus_applies():
    assert transfers.convert(_partner("etihad"), 115_000, "platinum_charge", 20).miles == 69_000


def test_partial_block_is_stranded():
    conv = transfers.convert(_partner("etihad"), 115_600, "platinum_charge")
    assert conv.mr_spent == 115_000
    assert conv.mr_stranded == 600


def test_below_minimum_converts_nothing():
    conv = transfers.convert(_partner("etihad"), 500, "platinum_charge")
    assert conv.miles == 0 and conv.mr_stranded == 500


def test_fixture_provider_respects_the_window():
    cfg = _cfg()
    rows = FixtureProvider().search(cfg.trip, "outbound", "business")
    assert rows, "fixture returned nothing"
    assert all(cfg.trip.outbound.start <= r.date <= cfg.trip.outbound.end for r in rows)
    assert all(r.direction == "outbound" and r.cabin == "business" for r in rows)


def _options(cfg, provider=None):
    provider = provider or FixtureProvider()
    out = []
    for direction in ("outbound", "return"):
        for cabin in cfg.trip.cabins:
            out += provider.search(cfg.trip, direction, cabin)
    return out


def _convs(cfg):
    partners = transfers.load_partners(cfg.partners_path)
    return {
        c.partner.key: c
        for c in transfers.convert_all(partners, cfg.mr_balance, cfg.card_tier)
    }


# --- trip constraints -------------------------------------------------------


def test_full_days_excludes_both_travel_days():
    c = _cfg().trip.constraints
    # Leave BOM 5 May, land 6 May, leave the US 22 May -> 7..21 May on the ground.
    assert c.full_days(dt.date(2027, 5, 5), dt.date(2027, 5, 22)) == 15


def test_both_trip_shapes_are_legal():
    c = _cfg().trip.constraints
    # Days banked after the wedding.
    assert c.check(dt.date(2027, 5, 5), dt.date(2027, 5, 22)) is None
    # Days banked before it.
    assert c.check(dt.date(2027, 4, 24), dt.date(2027, 5, 11)) is None


def test_arrival_deadline_is_enforced():
    c = _cfg().trip.constraints
    # Leaving BOM on the 6th lands on the 7th, after the wedding deadline.
    assert "after the 06 May deadline" in c.check(dt.date(2027, 5, 6), dt.date(2027, 5, 25))


def test_cannot_leave_before_the_wedding_is_over():
    c = _cfg().trip.constraints
    assert "before 11 May" in c.check(dt.date(2027, 4, 20), dt.date(2027, 5, 9))


def test_short_stay_is_rejected():
    c = _cfg().trip.constraints
    assert "need 15" in c.check(dt.date(2027, 5, 5), dt.date(2027, 5, 15))


def test_overlong_stay_is_rejected():
    c = _cfg().trip.constraints
    assert "over the 30" in c.check(dt.date(2027, 4, 15), dt.date(2027, 6, 5))


# --- constraint-aware pairing ----------------------------------------------


def test_cheapest_pairing_is_skipped_when_it_is_illegal():
    cfg = _cfg()
    trips, _ = build_round_trips(_options(cfg), _convs(cfg), cfg.trip.constraints)
    vs = next(t for t in trips if t.program == "virgin" and t.cabin == "business")

    # 76,000 out (5 May) + 70,000 back (11 May) is the cheapest arithmetic
    # pairing at 146,000, but it leaves only 4 full days on the ground.
    assert vs.miles == 155_000
    assert (vs.out.date, vs.back.date) == (dt.date(2027, 4, 24), dt.date(2027, 5, 11))
    assert vs.full_days == 15


def test_every_returned_trip_satisfies_the_constraints():
    cfg = _cfg()
    trips, _ = build_round_trips(_options(cfg), _convs(cfg), cfg.trip.constraints)
    assert trips
    for t in trips:
        assert cfg.trip.constraints.check(t.out.date, t.back.date) is None
        assert t.full_days >= cfg.trip.constraints.min_full_days_in_us


def test_missing_return_leg_is_reported_not_dropped():
    cfg = _cfg()
    _, rejections = build_round_trips(_options(cfg), _convs(cfg), cfg.trip.constraints)
    cx = next(r for r in rejections if r.program == "asiamiles")
    assert cx.reason == "no return availability"


def test_the_ratio_decides_affordability_not_the_fare():
    """The same 88,000-mile trip is reachable on Virgin and not on Etihad."""
    cfg = _cfg()
    trips, _ = build_round_trips(_options(cfg), _convs(cfg), cfg.trip.constraints)
    by_slot = {(t.program, t.cabin): t for t in trips}

    virgin = by_slot[("virgin", "premium")]
    etihad = by_slot[("etihad", "premium")]

    assert virgin.miles == 90_000 and virgin.affordable      # 92,000 available
    assert etihad.miles == 88_000 and not etihad.affordable  # 57,500 available
    assert etihad.gap == 88_000 - 57_500


def test_business_is_out_of_reach_on_every_programme():
    cfg = _cfg()
    trips, _ = build_round_trips(_options(cfg), _convs(cfg), cfg.trip.constraints)
    business = [t for t in trips if t.cabin == "business"]
    assert business
    assert not any(t.affordable for t in business)


def test_estimates_never_outrank_live_availability():
    cfg = _cfg()
    convs = _convs(cfg)
    baselines = estimate.load_baselines(cfg.baselines_path)

    options = estimate.estimated_options(cfg.trip, baselines, list(convs))
    options += _options(cfg)

    trips, _ = build_round_trips(options, convs, cfg.trip.constraints)
    live = [i for i, t in enumerate(trips) if not t.estimated]
    est = [i for i, t in enumerate(trips) if t.estimated]
    assert max(live) < min(est)


def test_estimator_anchors_to_a_legal_pairing():
    cfg = _cfg()
    anchors = estimate.anchor_dates(cfg.trip)
    assert anchors is not None
    assert cfg.trip.constraints.check(*anchors) is None


def test_mr_needed_rounds_up_to_a_whole_block():
    conv = transfers.convert(_partner("etihad"), 115_000, "platinum_charge")
    # 2 MR per mile, so 158,000 miles needs 316,000 MR.
    assert conv.mr_needed_for(158_000) == 316_000


def test_mr_needed_rounds_up_on_an_uneven_ratio():
    conv = transfers.convert(_partner("virgin"), 115_000, "platinum_charge")
    # 800 miles per 1,000 MR: 155,000 miles needs 194 blocks, not 193.75.
    assert conv.mr_needed_for(155_000) == 194_000


def test_report_warns_that_avios_partners_share_a_pot():
    cfg = _cfg()
    partners = transfers.load_partners(cfg.partners_path)
    convs = transfers.convert_all(partners, cfg.mr_balance, cfg.card_tier)
    note = report.shared_currency_note(convs)
    assert "share the same avios balance" in note
    assert "do not add them together" in note


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
