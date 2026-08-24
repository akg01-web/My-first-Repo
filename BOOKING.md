# Booking runbook

The one rule that governs everything below: **find and hold the seat first,
transfer the points second.** Amex transfers are irreversible and take anywhere
from instant to several days. Points moved into a programme that turns out to
have no award space are stranded there permanently. Nobody gets those back.

---

## Step 0 — Understand what you are buying

**115,000 Membership Rewards converts to at most 92,000 airline miles**
(Virgin Atlantic, 10:8). Every other partner is 2:1 and yields 57,500.

Realistic BOM-ORD round trip, per person:

| Cabin | Miles | Reachable? |
|---|---|---|
| Premium economy | ~88,000-110,000 | Yes, on Virgin only |
| Business | ~155,000-200,000 | No — short by ~60,000 at best |

So the target is **premium economy, and Virgin is the only programme whose
transfer ratio gets you there.**

### The catch, and it is a real one

Virgin has the best ratio and the worst cash cost on this roster. Verified
August 2026:

| Programme | Miles available | Carrier surcharge | True premium cabin? |
|---|---:|---|---|
| Virgin Atlantic | **92,000** | **~$240 per one-way, ~$480 return** | Yes |
| Qatar Privilege Club | 57,500 | **None** — taxes only, well under $200 | No |
| Etihad Guest | 57,500 | Moderate | Yes |
| BA Executive Club | 57,500 | High | Yes |
| Asia Miles | 57,500 | Moderate | Yes |
| KrisFlyer | 57,500 | Varies by operating carrier | Yes |

There is no zero-cash award ticket. Every option carries government taxes at
minimum. **Budget roughly $480 for the Virgin premium-economy booking.** If that
is unacceptable, the trip does not happen on points this year — no combination
here produces a cash-free ticket.

Virgin has raised these fees twice since 2025 and has signalled more changes, so
check the actual figure at booking rather than trusting this table.

---

## Step 1 — Find the seat (do this before anything else)

Run the watcher for the exact search list:

```bash
python -m awardwatch --dry-run --optimize cash
```

Work the generated link sheet under **Check these yourself**. You are looking
for **two separate one-way Premium awards**, not a round trip — award seats are
booked one direction at a time and pairing the two cheapest legals is what the
tool is for.

Search **Virgin first**, since it is the only programme your balance can reach
in premium:

- Outbound BOM to ORD, any date **15 April to 5 May**
- Return ORD to BOM, any date **11 May to 5 June**
- The pair must leave **at least 15 full days on the ground** and land you in
  Chicago by **6 May**

Look for the routing **BOM-LHR-ORD**, which is Virgin metal end to end.

If Virgin shows nothing, the balance does not cover premium economy anywhere
else, and Step 4 is your fallback.

---

## Step 2 — Hold the seat

Virgin allows award holds in some circumstances; call Flying Club rather than
relying on the website. Explain that a transfer is inbound.

**If no hold is possible**, you are exposed for the length of the transfer. Amex
India to Virgin is usually quick but is not guaranteed instant. Accept that risk
knowingly, and prefer dates where you can see several seats rather than the last
one.

---

## Step 3 — Transfer, then book immediately

Only once you know the seat exists and the exact mileage price:

1. Transfer **only what the booking needs**, rounded up to the next 1,000. Do
   not move the whole balance out of habit — points left in Membership Rewards
   stay flexible; points in Flying Club are committed forever.
   - 90,000 miles needed = 112,500 MR at 10:8
   - The tool prints the exact figure in the `MR needed` column
2. Wait for the miles to land in Flying Club.
3. Book both one-ways.
4. Pay the ~$480 in taxes and surcharges. This part is unavoidable cash.

---

## Step 4 — If premium economy is not available

In rough order of preference:

1. **Wait and keep polling.** Award space opens and closes continuously, and
   your date range is wide. This is what the 6-hourly workflow is for.
2. **Watch for a Virgin transfer bonus.** 30% turns 115,000 MR into 119,600
   miles; 60% reaches 147,200 and puts *business* within range. Ask the Amex
   concierge to flag the next Virgin promotion — this is the single biggest
   lever available to you.
3. **Split the cabins.** Premium one way, economy the other, which the balance
   covers comfortably.
4. **Qatar business, part-paid.** 57,500 Avios will not cover a business round
   trip, but Qatar charges no surcharges, so a one-way business plus a cash
   economy return can work out cheaper overall than Virgin's fees.

---

## What this repository cannot do for you

- **It cannot see live award space.** Without a seats.aero Partner API key, every
  mileage figure in the report is an estimate. The link sheet is how you get real
  numbers.
- **It cannot transfer points or book tickets.** Both need your logins, and the
  booking needs a payment card.
- **The mileage estimates are the weakest data here.** The transfer ratios are
  confirmed and the Virgin and Qatar surcharges are verified. Award costs are
  not — Virgin, Qatar and Etihad all price dynamically, so there is no fixed
  chart to be right about.

If you want unattended monitoring instead of manual sweeps, a seats.aero Pro
subscription is roughly $10 a month. For a trip worth 90,000 miles, one month
while you hunt is a reasonable trade.
