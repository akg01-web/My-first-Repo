"""Unit tests. Run with: python -m pytest -q  (or python tests/test_awardwatch.py)"""

from __future__ import annotations

import datetime as dt
import pathlib
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


# --- observation log and baselines -------------------------------------------


def _obs(slot_miles, program="virgin", cabin="premium", direction="outbound",
         flight="2027-05-03", start=None, step_hours=1, estimated=False):
    """Build a run of observations one hour apart for a single slot."""
    from awardwatch.observations import Observation
    start = start or dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc)
    return [
        Observation(
            observed_at=start + dt.timedelta(hours=i * step_hours),
            program=program, cabin=cabin, direction=direction,
            flight_date=dt.date.fromisoformat(flight),
            miles=m, taxes_usd=240.0, seats=2, carrier="VS",
            source="fixture", estimated=estimated,
        )
        for i, m in enumerate(slot_miles)
    ]


def test_observation_log_round_trips(tmp_path=None):
    import tempfile
    from awardwatch import observations
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "obs.csv"
        rows = _obs([90000, 90000, 88000])
        assert observations.append(path, rows) == 3
        assert observations.append(path, _obs([87000])) == 1

        back = observations.load(path)
        assert len(back) == 4
        assert [o.miles for o in back] == [90000, 90000, 88000, 87000]
        assert back[0].slot == "virgin|premium|outbound|2027-05-03"
        # Header written exactly once despite two appends.
        assert path.read_text().count("observed_at,program") == 1


def test_malformed_row_does_not_destroy_history():
    import tempfile
    from awardwatch import observations
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "obs.csv"
        observations.append(path, _obs([90000, 88000]))
        with path.open("a") as fh:
            fh.write("garbage,not,a,valid,row\n")
        assert len(observations.load(path)) == 2


def test_estimates_are_excluded_from_baselines():
    from awardwatch import baseline
    rows = _obs([90000] * 5, estimated=True)
    assert baseline.build(rows) == {}


def test_baseline_uses_median_not_mean():
    from awardwatch import baseline
    # One absurd outlier would drag a mean; the median ignores it.
    b = baseline.build(_obs([90000, 90000, 90000, 90000, 900000]))
    slot = next(iter(b))
    assert b[slot].median_miles == 90000
    assert b[slot].worst_seen == 900000


def test_baseline_needs_enough_history_before_flagging():
    from awardwatch import baseline
    history = _obs([90000] * 5)          # only 5 hours of data
    bases = baseline.build(history)
    current = _obs([70000], start=dt.datetime(2026, 8, 21, tzinfo=dt.timezone.utc))
    assert baseline.find_deals(current, bases, min_rows=24, min_hours=48) == []


def test_flat_slot_still_flags_a_real_drop():
    """The common case: a price that never moved, so MAD is zero."""
    from awardwatch import baseline
    history = _obs([90000] * 72)         # 72 hours, never moved
    bases = baseline.build(history)
    slot = next(iter(bases))
    assert bases[slot].spread == 0

    current = _obs([70000], start=dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc))
    deals = baseline.find_deals(current, bases)
    assert len(deals) == 1
    assert deals[0].kind == "price_drop"
    assert deals[0].z is None                       # floor decided, not a z-score
    assert round(deals[0].drop_pct, 4) == 0.2222


def test_trivial_drop_on_a_flat_slot_is_not_a_deal():
    from awardwatch import baseline
    bases = baseline.build(_obs([90000] * 72))
    current = _obs([89500], start=dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc))
    assert baseline.find_deals(current, bases) == []


def test_statistically_large_but_economically_trivial_is_not_a_deal():
    from awardwatch import baseline
    # Noisy by a few hundred miles: a 2,000-mile drop is many MADs but ~2%.
    history = _obs([90000, 90200, 89800, 90100, 89900] * 15)
    bases = baseline.build(history)
    current = _obs([88000], start=dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc))
    assert baseline.find_deals(current, bases) == []


def test_new_availability_is_reported_separately_from_a_drop():
    from awardwatch import baseline
    bases = baseline.build(_obs([90000] * 72))
    fresh = _obs([120000], flight="2027-05-04",
                 start=dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc))
    deals = baseline.find_deals(fresh, bases)
    assert len(deals) == 1
    assert deals[0].kind == "new_availability"
    assert "availability appeared" in deals[0].describe()


def test_price_drops_rank_above_new_availability():
    from awardwatch import baseline
    bases = baseline.build(_obs([90000] * 72))
    now = dt.datetime(2026, 8, 24, tzinfo=dt.timezone.utc)
    current = _obs([120000], flight="2027-05-04", start=now) + _obs([70000], start=now)
    kinds = [d.kind for d in baseline.find_deals(current, bases)]
    assert kinds == ["price_drop", "new_availability"]


def test_coverage_counts_only_established_slots():
    from awardwatch import baseline
    bases = baseline.build(_obs([90000] * 72) + _obs([50000] * 3, flight="2027-05-04"))
    assert baseline.coverage(bases, min_rows=24, min_hours=48) == (1, 2)


def test_fixture_data_can_never_enter_the_observation_log():
    """The bug that would have poisoned every baseline: sample data logged as real."""
    from awardwatch import observations
    cfg = _cfg()
    opts = FixtureProvider().search(cfg.trip, "outbound", "business")
    assert opts, "fixture returned nothing, so this test proves nothing"
    assert observations.from_options(opts, live_sources={"seatsaero"}) == []
    assert observations.from_options(opts, live_sources=set()) == []


def test_only_live_sources_are_admitted_to_the_log():
    from awardwatch import observations
    cfg = _cfg()
    opts = FixtureProvider().search(cfg.trip, "outbound", "business")
    # Naming fixture as live is the only way its rows get in -- tests may, config may not.
    assert len(observations.from_options(opts, live_sources={"fixture"})) == len(opts)


def test_estimates_are_rejected_even_from_a_live_source():
    from awardwatch import estimate, observations
    cfg = _cfg()
    baselines = estimate.load_baselines(cfg.baselines_path)
    est = estimate.estimated_options(cfg.trip, baselines, ["virgin"])
    assert est
    for o in est:
        object.__setattr__(o, "source", "seatsaero")  # even if a live source emitted it
    assert observations.from_options(est, live_sources={"seatsaero"}) == []


def test_production_config_does_not_enable_the_fixture_provider():
    assert "fixture" not in _cfg().providers


# --- transfer routing --------------------------------------------------------


def _graph():
    from awardwatch import routing
    return routing.load_graph(config.REPO_ROOT / "data" / "transfer_graph.yaml")


def test_virgin_direct_is_the_maximum_route():
    from awardwatch import routing
    cur, edges = _graph()
    best = routing.best_routes(edges, cur, 115_000)[0]
    assert best.target == "virgin"
    assert best.miles == 92_000
    assert best.hops == 1
    assert best.verified


def test_the_one_to_one_hotel_exit_is_a_trap():
    """MR reaches Marriott at 1:1 -- double any airline edge -- and still loses.

    This is the whole reason routing is computed rather than eyeballed: the
    better first hop is more than undone by the 3:1 second hop.
    """
    from awardwatch import routing
    cur, edges = _graph()
    routes = {r.target: r for r in routing.best_routes(edges, cur, 115_000)}

    via_marriott = routes["united"]
    assert via_marriott.hops == 2
    assert via_marriott.rate < 0.5          # worse than a plain 2:1 direct transfer
    assert via_marriott.rate < routes["virgin"].rate

    # And no two-hop route wins anywhere it competes with a direct edge.
    for target in ("virgin", "avios_ba", "krisflyer", "etihad", "asiamiles"):
        assert routes[target].hops == 1


def test_marriott_block_bonus_is_granted_per_whole_block():
    from awardwatch import routing
    cur, edges = _graph()
    edge = next(e for e in edges if e.source == "marriott" and e.target == "krisflyer")

    # 60,000 -> 20,000 base + 5,000 bonus
    assert edge.apply(60_000)[1] == 25_000
    # 119,000 -> only one whole block earns the bonus
    assert edge.apply(119_000)[1] == 39_666 + 5_000
    # 59,000 -> no block, no bonus
    assert edge.apply(59_000)[1] == 19_666


def test_united_gets_the_larger_block_bonus():
    from awardwatch import routing
    _, edges = _graph()
    united = next(e for e in edges if e.source == "marriott" and e.target == "united")
    other = next(e for e in edges if e.source == "marriott" and e.target == "krisflyer")
    assert united.apply(60_000)[1] - other.apply(60_000)[1] == 5_000


def test_each_hop_strands_its_own_remainder():
    from awardwatch import routing
    cur, edges = _graph()
    mr_to_marriott = next(e for e in edges if e.source == "amex_mr" and e.target == "marriott")
    onward = next(e for e in edges if e.source == "marriott" and e.target == "krisflyer")

    route = routing.evaluate((mr_to_marriott, onward), 115_600)
    assert route.stranded["amex_mr"] == 600      # 1,000-point increment
    assert route.total_stranded >= 600


def test_below_minimum_yields_nothing_and_strands_everything():
    from awardwatch import routing
    _, edges = _graph()
    edge = next(e for e in edges if e.source == "amex_mr" and e.target == "virgin")
    spent, produced, stranded = edge.apply(500)
    assert (spent, produced, stranded) == (0, 0, 500)


def test_transfer_bonus_lifts_the_winning_route():
    from awardwatch import routing
    cur, edges = _graph()
    plain = routing.best_routes(edges, cur, 115_000)[0]
    boosted = routing.best_routes(edges, cur, 115_000, bonuses={"virgin": 30})[0]
    assert boosted.miles == int(plain.miles * 1.3)
    assert boosted.rate > 1.0    # a 30% bonus beats 1 mile per point


def test_pooling_edges_never_appear_in_a_route():
    """Pooling moves Avios between badges 1:1. It cannot create miles."""
    from awardwatch import routing
    cur, edges = _graph()
    for route in routing.best_routes(edges, cur, 115_000):
        assert not any(e.pooling for e in route.path)


def test_pooling_group_is_transitive():
    from awardwatch import routing
    _, edges = _graph()
    group = routing.pooling_group(edges, "avios_ba")
    # Iberia and Aer Lingus are only reachable via BA; Qatar both ways.
    assert group == {"avios_qatar", "avios_iberia", "avios_aerlingus"}


def test_unverified_routes_are_flagged_as_such():
    from awardwatch import routing
    cur, edges = _graph()
    routes = {r.target: r for r in routing.best_routes(edges, cur, 115_000)}
    # Concierge confirmed the airline edges; the Marriott chain is inference.
    assert routes["virgin"].verified
    assert not routes["united"].verified


# --- workflow validity -------------------------------------------------------


def _workflows():
    import yaml
    root = config.REPO_ROOT / ".github" / "workflows"
    return {p.name: (p.read_text(), yaml.safe_load(p.read_text())) for p in root.glob("*.yml")}


def test_workflows_are_valid_yaml():
    assert _workflows(), "no workflows found"


def test_no_workflow_references_secrets_in_a_step_condition():
    """GitHub rejects the entire file, and every run fails instantly with zero jobs.

    This cost six silent failures before anyone looked, because a workflow that
    never starts produces no job logs to read.
    """
    import re
    offenders = []
    for name, (text, _) in _workflows().items():
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.search(r"^\s*if:.*secrets\.", line):
                offenders.append(f"{name}:{lineno}")
    assert not offenders, f"secrets context used in a step condition: {offenders}"


def test_scheduled_workflow_does_not_enable_the_fixture_provider():
    """The 19:35 run wrote fixture rows into the observation log as real data."""
    import yaml
    cfg = yaml.safe_load((config.REPO_ROOT / "config.yaml").read_text())
    assert "fixture" not in (cfg.get("providers") or [])


def test_no_fabricated_rows_in_the_committed_observation_log():
    from awardwatch import observations
    path = config.REPO_ROOT / "data" / "observations.csv"
    if not path.exists():
        return  # nothing collected yet
    bad = [o for o in observations.load(path) if o.source not in {"seatsaero"}]
    assert not bad, f"{len(bad)} row(s) from a non-live source: {sorted({o.source for o in bad})}"


def test_scheduled_poll_is_pinned_to_the_default_branch_dynamically():
    """GitHub runs schedules ONLY on the default branch, whatever it is called.

    An earlier version of this guard hardcoded 'refs/heads/main'. This
    repository's default branch is not main, so that condition could never be
    true on a scheduled run -- it would have silently disabled the poll forever
    while reading like a safety measure. Comparing against the default branch
    from the event payload cannot drift.
    """
    _, doc = _workflows()["award-watch.yml"]
    condition = doc["jobs"]["poll"].get("if", "")
    assert "github.event.repository.default_branch" in condition
    assert "refs/heads/" not in condition, "hardcoded branch name reintroduced"


def test_commit_logic_lives_in_a_testable_script():
    """Inline shell in YAML cannot be tested, and this block was wrong twice.

    First it committed on every run, because the report embeds a timestamp and
    so always differs. Then it failed the entire job, because `git add` on a
    path that does not exist is fatal under `bash -e` -- and a missing
    observation log is the normal state until a live provider runs.
    """
    text, _ = _workflows()["award-watch.yml"]
    commit_step = text[text.index("Commit report and state"):]
    assert "scripts/commit_if_observed.sh" in commit_step
    assert "git add" not in commit_step, "inline git plumbing reintroduced"
    assert (config.REPO_ROOT / "scripts" / "commit_if_observed.sh").exists()


def test_the_commit_script_is_exercised_by_ci():
    text, _ = _workflows()["award-watch.yml"]
    assert "tests/test_commit_step.sh" in text
