# awardwatch

Polls award availability for a single trip and prices it against an Amex
Membership Rewards balance. Built for one specific question:

- **Trip:** Bombay (BOM) to Chicago (ORD) and back
- **Dates:** 3 May 2027 out, 18 May 2027 back, +/- 2 days each
- **Cabins:** business and premium economy (economy deliberately excluded)
- **Balance:** 115,000 Amex **India** Membership Rewards

## Read this before anything else

The points sit on an Amex India **Platinum Charge**, which transfers most
airline partners at **1 MR : 1 mile** rather than the 2:1 the other Indian Amex
cards get. That is the difference between this trip being possible and not:

| | Miles | Covers a BOM-ORD round trip in... |
|---|---:|---|
| 115,000 MR at 1:1 (Platinum Charge — **your card**) | **115,000** | premium economy, yes. Business, no. |
| 115,000 MR at 2:1 (MRCC, Gold Charge, Platinum Travel/Reserve) | 57,500 | neither |

Rough round-trip cost on this route, per person:

- **Premium economy:** ~88,000-110,000 miles — **within reach**
- **Business:** ~175,000-210,000 miles — **short by roughly 60,000-95,000 miles**

So premium economy is a live booking today, and business is the thing worth
watching for. Three things can close the business gap, and the poller tracks
all of them:

1. **Flying Blue Promo Rewards.** Air France-KLM discounts selected routes
   25-50% every month. A 50% promo on BOM-CDG-ORD is the single most plausible
   route to business on this balance. Flying Blue is also fully dynamic, which
   is why the workflow polls every 6 hours rather than daily.
2. **Transfer bonuses.** Amex India runs periodic bonus-transfer promos. Put a
   live one in `points.bonus_pct` (e.g. `{flyingblue: 30}`) and the report
   re-prices everything against it. A 30% bonus turns 115,000 MR into 149,500
   miles, which puts a discounted business round trip in range.
3. **Business one way, premium the other.** 115,000 miles covers a one-way
   business leg (~88,000) outright. The report prices each direction
   separately, so this split is visible directly in the output.

**Transfers are irreversible.** Never move points into a programme until you
have the specific award seat held. Every ratio in
`data/amex_in_partners.yaml` ships marked `verified: false` — confirm each one
on americanexpress.com/in and flip the flag before you act on any of it. The
Platinum Charge 1:1 ratios in particular are worth confirming per partner,
since not every partner necessarily matches.

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
| `points.card_tier` | Set to `platinum_charge`. Reverting to `standard` halves your usable miles. |
| `points.bonus_pct` | Per-partner transfer bonus, e.g. `{etihad: 20}` |
| `trip.*_window` | The +/- 2 days. Widen it and the odds improve sharply. |
| `alerts.max_miles_roundtrip` | Suppress everything above a mileage ceiling |

## Scheduling

`.github/workflows/award-watch.yml` runs every 6 hours, opens a tracking issue
titled *"Award watch: BOM <-> ORD, May 2027"*, and rewrites its body in place on
each run so there is one live view rather than a wall of comments. A comment is
posted only when genuinely new availability appears — that is what triggers a
GitHub notification. It also commits `docs/award-watch.md`, so the git history
becomes a record of how the price moved.

## Caveats worth stating plainly

- The baseline numbers in `data/award_baselines.yaml` are **planning estimates,
  not prices.** Several of these programmes are fully dynamic; the same seat can
  differ 2x between two dates.
- Surcharges matter as much as miles here. Emirates in particular levies very
  heavy carrier-imposed fees on India-US business. The report shows taxes
  alongside miles for exactly this reason.
- Singapore Airlines does not fly to ORD, and Air India's US nonstop is DEL-ORD,
  not BOM-ORD. Every option on this route involves a connection.
- Award space for India-US in early May is thin and goes early. Polling from now
  is the right call; 2027 schedules are already inside most programmes' booking
  windows.
