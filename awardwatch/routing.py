"""Find the best route from Membership Rewards to airline miles.

Treating conversion as a lookup table -- balance times the best ratio -- gets
the wrong answer whenever an indirect route exists. Amex India reaches Marriott
at 1:1 while every airline is 2:1, and Marriott reaches twenty-odd airlines, so
a two-hop path starts from twice the points. Whether it survives the second hop
is an arithmetic question, and arithmetic questions should be computed rather
than eyeballed.

Three things make the arithmetic non-obvious:

- Transfers move in fixed blocks, so every hop strands a remainder, and a
  two-hop route strands twice.
- Marriott's bonus is granted per whole 60,000 points moved, which makes its
  effective rate depend on how much is transferred -- it is not a constant.
- Pooling edges (Avios between BA, Qatar, Iberia, Aer Lingus) move points at
  1:1 and create no miles at all. They are worthless for maximising mileage and
  invaluable for reach, so they are tracked separately rather than ranked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    ratio_in: int
    ratio_out: int
    min_transfer: int
    increment: int
    block_per: int = 0
    block_bonus: int = 0
    pooling: bool = False
    verified: bool = True

    def apply(self, amount: int, bonus_pct: float = 0.0) -> tuple[int, int, int]:
        """Move `amount` across this edge. Returns (spent, produced, stranded)."""
        if amount < self.min_transfer or self.increment <= 0:
            return 0, 0, amount

        spent = (amount // self.increment) * self.increment
        if spent < self.min_transfer:
            return 0, 0, amount

        produced = int(spent / self.ratio_in * self.ratio_out)
        if self.block_per > 0:
            produced += (spent // self.block_per) * self.block_bonus
        if bonus_pct:
            produced = int(produced * (1 + bonus_pct / 100.0))

        return spent, produced, amount - spent


@dataclass(frozen=True)
class Route:
    path: tuple[Edge, ...]
    start_amount: int
    miles: int
    stranded: dict[str, int] = field(default_factory=dict)

    @property
    def target(self) -> str:
        return self.path[-1].target if self.path else ""

    @property
    def hops(self) -> int:
        return len(self.path)

    @property
    def rate(self) -> float:
        """Miles obtained per starting point."""
        return self.miles / self.start_amount if self.start_amount else 0.0

    @property
    def verified(self) -> bool:
        return all(e.verified for e in self.path)

    @property
    def total_stranded(self) -> int:
        return sum(self.stranded.values())

    def describe(self) -> str:
        if not self.path:
            return ""
        chain = self.path[0].source
        for edge in self.path:
            chain += f" -> {edge.target}"
        return chain


def load_graph(path: str | Path) -> tuple[dict[str, dict], list[Edge]]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    currencies = raw.get("currencies", {}) or {}
    edges = []
    for row in raw.get("edges", []) or []:
        block = row.get("block_bonus") or {}
        edges.append(
            Edge(
                source=row["from"],
                target=row["to"],
                ratio_in=int(row["ratio"][0]),
                ratio_out=int(row["ratio"][1]),
                min_transfer=int(row.get("min", 0)),
                increment=int(row.get("increment", 1)),
                block_per=int(block.get("per", 0)),
                block_bonus=int(block.get("bonus", 0)),
                pooling=bool(row.get("pooling", False)),
                verified=bool(row.get("verified", False)),
            )
        )
    return currencies, edges


def _paths(edges: list[Edge], start: str, max_hops: int) -> list[tuple[Edge, ...]]:
    """Every simple path out of `start`, ignoring pooling edges.

    Pooling edges are excluded because they cannot increase mileage -- allowing
    them would produce a combinatorial spray of equal-value routes that differ
    only in which badge the same Avios are wearing.
    """
    out: list[tuple[Edge, ...]] = []

    def walk(node: str, path: tuple[Edge, ...], seen: frozenset[str]) -> None:
        if len(path) >= max_hops:
            return
        for edge in edges:
            if edge.source != node or edge.pooling or edge.target in seen:
                continue
            extended = path + (edge,)
            out.append(extended)
            walk(edge.target, extended, seen | {edge.target})

    walk(start, (), frozenset({start}))
    return out


def evaluate(path: tuple[Edge, ...], balance: int, bonuses: dict[str, float] | None = None) -> Route:
    """Push `balance` along a path, hop by hop, tracking what is stranded."""
    bonuses = bonuses or {}
    amount = balance
    stranded: dict[str, int] = {}

    for edge in path:
        _, produced, left = edge.apply(amount, bonuses.get(edge.target, 0.0))
        if left:
            stranded[edge.source] = stranded.get(edge.source, 0) + left
        amount = produced
        if amount == 0:
            break

    return Route(path=path, start_amount=balance, miles=amount, stranded=stranded)


def best_routes(
    edges: list[Edge],
    currencies: dict[str, dict],
    balance: int,
    start: str = "amex_mr",
    bonuses: dict[str, float] | None = None,
    max_hops: int = 3,
) -> list[Route]:
    """Best route to each terminal currency, most miles first."""
    best: dict[str, Route] = {}

    for path in _paths(edges, start, max_hops):
        target = path[-1].target
        if not (currencies.get(target) or {}).get("terminal"):
            continue
        route = evaluate(path, balance, bonuses)
        if route.miles == 0:
            continue
        incumbent = best.get(target)
        # Prefer more miles; on a tie prefer the shorter, less fragile path.
        if incumbent is None or (route.miles, -route.hops) > (incumbent.miles, -incumbent.hops):
            best[target] = route

    return sorted(best.values(), key=lambda r: (-r.miles, r.hops))


def pooling_group(edges: list[Edge], currency: str) -> set[str]:
    """Currencies reachable from `currency` by pooling alone -- one balance,
    several award charts. Transitive, since pooling edges chain."""
    group = {currency}
    changed = True
    while changed:
        changed = False
        for edge in edges:
            if edge.pooling and edge.source in group and edge.target not in group:
                group.add(edge.target)
                changed = True
    return group - {currency}
