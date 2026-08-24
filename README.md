# awardwatch

Polls award availability for a single trip and prices it against an Amex
Membership Rewards balance. Built for one specific question:

- **Trip:** Bombay (BOM) to Chicago (ORD) and back, May 2027
- **Fixed point:** a wedding in Chicago on **8 May 2027**
- **Cabins:** business and premium economy (economy deliberately excluded)
- **Balance:** 115,000 Amex **India** Membership Rewards, Platinum Charge
  (max **92,000 airline miles**, via Virgin Atlantic)

## The trip is defined by constraints, not by fixed dates

There is no single departure date to search. The trip is pinned by an event and
otherwise floats:

- Be on the ground in Chicago **48 hours before the 8 May wedding**, so land by
  **6 May**. Every BOM-ORD routing connects and spans a calendar day, so the
  latest possible BOM departure is **5 May**.
- The earliest the US can be left once the wedding is over is **11 May**.
- At least **15 full non-flying days** on the ground, and those days may fall
  before the wedding, after it, or be split across both.

That last clause is what makes this interesting, because it admits two
completely different trip shapes:

| Shape | Leave BOM | Land ORD | Leave US | Full days |
|---|---|---|---|---|
| Days banked **after** the wedding | 5 May | 6 May | 22 May | 15 (7-21 May) |
| Days banked **before** it | 24 Apr | 25 Apr | 11 May | 15 (26 Apr-10 May) |

So the searchable space is BOM departures across **mid-April to 5 May** paired
with ORD departures across **11 May to early June** -- roughly twenty times the
span of a fixed date with a few days' slack either side. On a route where
business space is the scarce resource, that width is the most valuable thing
you have.

The consequence for the code is that **the two halves can no longer be chosen
independently.** The cheapest outbound may only pair with a return far enough
after it to serve the 15 days. `rank.py` therefore walks every outbound/return
combination, discards the illegal ones, and keeps the cheapest pairing that
survives -- and the sample data is built so the cheapest arithmetic pairing is
an illegal one, to keep that behaviour honest under test.

All of it is config, in `trip.constraints`:

```yaml
constraints:
  arrive_by: "2027-05-06"
  depart_us_not_before: "2027-05-11"
  min_full_days_in_us: 15
  max_full_days_in_us: 30      # so the search does not propose a two-month trip
  outbound_transit_days: 1     # leave the 5th, land the 6th
  return_transit_days: 2
```

Anything ruled out by these gets its own table in the report with the reason,
rather than silently vanishing -- "no legal pairing" and "no availability" are
very different problems and you want to know which one you have.

## Read this before anything else

The transfer ratios here were confirmed with the Amex card concierge on
**24 August 2026** for a Platinum Charge card. The roster is six airlines, and
**nothing transfers better than 10:8**:

| Programme | Currency | Ratio | 115,000 MR becomes |
|---|---|---|---:|
| **Virgin Atlantic Flying Club** | virgin | **10:8** | **92,000** |
| Qatar Airways Privilege Club | avios | 2:1 | 57,500 |
| British Airways Executive Club | avios | 2:1 | 57,500 |
| Etihad Guest | etihad | 2:1 | 57,500 |
| Cathay Pacific Asia Miles | asiamiles | 2:1 | 57,500 |
| Singapore Airlines KrisFlyer | krisflyer | 2:1 | 57,500 |

Two things follow from that table, and both matter more than anything else in
this repository.

**Virgin is worth 60% more than everything else.** 0.80 miles per point against
0.50 is not a marginal edge — it is the difference between 92,000 miles and
57,500 from the same balance. Unless another programme prices a specific award
dramatically lower, Virgin is where these points should go.

**Qatar and BA are not two options.** They share the Avios currency, so the
57,500 figure is what the balance becomes in *either* — not in each. Transferring
splits one pot; it does not create two. The report prints this warning every run
because it is an easy and expensive mistake.

### Best ratio is not best deal

Virgin has the best transfer ratio on the roster and the worst cash cost, and
those pull in opposite directions. Verified August 2026:

| Programme | Miles | Carrier surcharge | True premium cabin? |
|---|---:|---|---|
| Virgin Atlantic | **92,000** | **~$240/one-way, ~$480 return** | Yes |
| Qatar Privilege Club | 57,500 | **None** — taxes only | No |
| Etihad Guest | 57,500 | Moderate | Yes |
| BA Executive Club | 57,500 | High | Yes |
| Asia Miles | 57,500 | Moderate | Yes |
| KrisFlyer | 57,500 | Varies by carrier | Yes |

Virgin has raised award fees twice since 2025. Qatar levies no carrier-imposed
surcharge at all, but has no true premium economy cabin, so it is a
business-class play or nothing. Rank by cash rather than miles with
`--optimize cash`.

**There is no zero-cash award ticket.** Every option carries government taxes at
minimum; the Virgin premium booking runs about $480. See
[BOOKING.md](BOOKING.md) for the full runbook.

### What 92,000 miles actually reaches

Rough round-trip cost, BOM–ORD, per person:

- **Premium economy:** ~88,000–110,000 miles — **borderline.** Virgin can reach
  the bottom of that band. Nothing at 2:1 can.
- **Business:** ~155,000–200,000 miles — **out of reach on every programme,**
  short by roughly 60,000 miles at best.

So premium economy on Virgin is the realistic target today, and business is what
the poller exists to watch for. Three things could close the business gap:

1. **An Amex transfer bonus.** A 30% bonus on Virgin turns 115,000 MR into
   119,600 miles; a 60% bonus reaches 147,200. Put a live promo in
   `points.bonus_pct` and the whole report re-prices against it. This is the
   single most likely route to business, and it is worth asking the concierge to
   flag the next Virgin promotion.
2. **A cheap Virgin partner award.** Virgin redeems on Delta and Air France-KLM
   as well as its own metal, and prices those separately from Virgin flights.
3. **Business one way, premium the other.** 92,000 miles covers a one-way
   business leg on the cheaper programmes. Each direction is priced separately in
   the report, so this split shows up on its own.

Note what is *not* on the list: Flying Blue Promo Rewards, Emirates and Air India
are **not Amex India partners**, whatever general Membership Rewards guidance
suggests. Do not plan around them.

**Transfers are irreversible.** Never move points into a programme until the
specific award seat is held.

## On seats.aero and doing this for free

seats.aero is the only source with a documented REST API covering the
programmes Amex India can reach. Its **Partner API is paid — there is no free
API key.** I have not built anything that pretends otherwise.

What you get for free, out of the box:

- The **whole transfer-maths engine** (part (a)) — offline, no API, exact.
- **Ranking, gap analysis, price-drop history and GitHub issue alerts.**
- A **generated link sheet** — every award search worth running, pre-filled
  with your origin, destination and dates, including seats.aero's own web
  search, which is usable on its free tier. A manual sweep of the whole window
  takes a couple of minutes instead of an hour.

What you do not get for free: unattended live availability. If you want the
watcher to find seats while you sleep, add a seats.aero Partner API key as the
`SEATS_AERO_API_KEY` repo secret and the `seatsaero` provider activates itself.
Nothing else changes.

I deliberately did **not** build an airline-site scraper. Award search on every
one of these carriers sits behind commercial bot protection, breaks constantly,
and violates their terms of service — it is not a foundation worth putting a
2027 trip on.

## Usage

```bash
pip install -r requirements.txt

python -m awardwatch --dry-run              # print the report, change nothing
python -m awardwatch --out docs/award-watch.md
python tests/test_awardwatch.py             # 10 tests, no pytest needed
```

`--dry-run` neither saves state nor touches GitHub.

## How it works

```
config.yaml ──> transfers.py ──> how many miles 115k MR becomes, per programme
                                              │
providers/ ──> seatsaero (live, needs key) ───┤
               fixture   (offline sample)     ├──> rank.py ──> report.py ──> notify.py
estimate.py ──> chart baselines (fallback) ───┘                                 │
                                                                       GitHub issue
```

- `providers/` is a plug-in point. Anything exposing `search(trip, direction,
  cabin) -> list[AwardOption]` drops straight in.
- Live results always outrank estimates at the same price, and estimated rows
  are labelled `(est)` so they are never mistaken for bookable seats.
- Each direction is priced independently, because award seats are booked one
  way at a time — pairing the cheapest outbound with the cheapest return is the
  real answer, not a single fused itinerary.
- `state.py` remembers what has been alerted, so a run only shouts about what
  is new, and logs price history so drops get called out.

## Configuration

Everything lives in `config.yaml`. The fields worth revisiting:

| Field | Why you would change it |
|---|---|
| `points.card_tier` | Set to `platinum_charge`, matching the confirmed ratios |
| `points.bonus_pct` | Live transfer bonus, e.g. `{virgin: 30}` — the main lever on business |
| `trip.*_window` | Search span. Widen it and the odds improve sharply. |
| `trip.constraints` | The wedding anchor, the 15-day minimum, transit-day assumptions |
| `alerts.max_miles_roundtrip` | Suppress everything above a mileage ceiling |

## Scheduling

`.github/workflows/award-watch.yml` runs every 6 hours, opens a tracking issue
titled *"Award watch: BOM <-> ORD, May 2027"*, and rewrites its body in place on
each run so there is one live view rather than a wall of comments. A comment is
posted only when genuinely new availability appears — that is what triggers a
GitHub notification. It also commits `docs/award-watch.md`, so the git history
becomes a record of how the price moved.

## Caveats worth stating plainly

- The transfer ratios are confirmed; **the award costs in
  `data/award_baselines.yaml` are not.** They are rough planning figures, and
  they are the weakest numbers in this repository. Virgin, Qatar and Etihad all
  price dynamically, so there is no chart to be right about.
- Surcharges matter as much as miles here. Emirates in particular levies very
  heavy carrier-imposed fees on India-US business. The report shows taxes
  alongside miles for exactly this reason.
- No programme here flies BOM-ORD nonstop; every option connects. Qatar
  (BOM-DOH-ORD) is the cleanest single-airline routing. Singapore does not serve
  ORD at all, so KrisFlyer means a Star Alliance partner award — worth watching
  anyway, since Star has more Chicago capacity than any other alliance.
- Watch UK Air Passenger Duty on anything routing through Heathrow: a
  business-class departure attracts roughly GBP 200 per person. A sub-24h transit
  connection should be exempt, but confirm it on the actual itinerary.
- Award space for India-US in early May is thin and goes early. Polling from now
  is the right call; 2027 schedules are already inside most programmes' booking
  windows.
- The transit-day assumptions are conservative round numbers, not a timetable.
  Confirm the actual arrival date on any itinerary before booking -- a routing
  that lands on 7 May instead of 6 May breaks the whole trip.
