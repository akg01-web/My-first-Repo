"""Amex India Membership Rewards -> partner-mile conversion maths.

This answers part (a) of the problem: given a Membership Rewards balance,
what is the largest number of miles it can become in each programme?
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Partner:
    key: str
    name: str
    alliance: str
    ratios: dict[str, tuple[int, int]]
    min_transfer_mr: int
    increment_mr: int
    verified: bool
    last_checked: str | None
    award_search_url: str
    notes: str

    def ratio(self, tier: str) -> tuple[int, int]:
        if tier in self.ratios:
            return self.ratios[tier]
        return self.ratios["standard"]


@dataclass(frozen=True)
class Conversion:
    partner: Partner
    tier: str
    mr_balance: int
    bonus_pct: float
    mr_spent: int
    mr_stranded: int
    miles: int

    @property
    def effective_rate(self) -> float:
        """Miles obtained per MR point spent."""
        return self.miles / self.mr_spent if self.mr_spent else 0.0

    def mr_needed_for(self, miles: int) -> int:
        """MR required to reach `miles`, rounded up to a valid transfer block."""
        mr_per, miles_per = self.partner.ratio(self.tier)
        miles_per_block = miles_per * (1 + self.bonus_pct / 100.0)
        if miles_per_block <= 0:
            return 0
        blocks = -(-miles // int(miles_per_block))  # ceiling division
        mr = blocks * mr_per
        return max(mr, self.partner.min_transfer_mr)


def load_partners(path: str | Path) -> list[Partner]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    partners: list[Partner] = []
    for row in raw.get("partners", []):
        ratios = {
            tier: (int(pair[0]), int(pair[1]))
            for tier, pair in (row.get("ratio") or {}).items()
        }
        if "standard" not in ratios:
            raise ValueError(f"partner {row.get('key')!r} is missing a 'standard' ratio")
        partners.append(
            Partner(
                key=str(row["key"]),
                name=str(row["name"]),
                alliance=str(row.get("alliance", "none")),
                ratios=ratios,
                min_transfer_mr=int(row.get("min_transfer_mr", 1000)),
                increment_mr=int(row.get("increment_mr", 1000)),
                verified=bool(row.get("verified", False)),
                last_checked=row.get("last_checked"),
                award_search_url=str(row.get("award_search_url", "")),
                notes=str(row.get("notes", "")).strip(),
            )
        )
    return partners


def convert(
    partner: Partner,
    mr_balance: int,
    tier: str = "standard",
    bonus_pct: float = 0.0,
) -> Conversion:
    """Convert the whole balance, respecting transfer increments.

    Amex moves points in fixed blocks, so a balance rarely converts cleanly --
    whatever falls short of a full block is stranded in Membership Rewards.
    """
    mr_per_block, miles_per_block = partner.ratio(tier)
    increment = partner.increment_mr or mr_per_block

    if mr_balance < partner.min_transfer_mr:
        return Conversion(partner, tier, mr_balance, bonus_pct, 0, mr_balance, 0)

    blocks = mr_balance // increment
    mr_spent = blocks * increment
    base_miles = int(blocks * increment / mr_per_block * miles_per_block)
    miles = int(base_miles * (1 + bonus_pct / 100.0))

    return Conversion(
        partner=partner,
        tier=tier,
        mr_balance=mr_balance,
        bonus_pct=bonus_pct,
        mr_spent=mr_spent,
        mr_stranded=mr_balance - mr_spent,
        miles=miles,
    )


def convert_all(
    partners: list[Partner],
    mr_balance: int,
    tier: str = "standard",
    bonus_pct: dict[str, float] | None = None,
) -> list[Conversion]:
    """Every partner, best mileage yield first."""
    bonus_pct = bonus_pct or {}
    out = [convert(p, mr_balance, tier, bonus_pct.get(p.key, 0.0)) for p in partners]
    return sorted(out, key=lambda c: c.miles, reverse=True)
