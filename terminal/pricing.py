"""Price rule for made-up markets: a scored tick nudges the price in log-odds."""
import math


def nudge(price: float, strength: float, k: float = 0.4) -> float:
    """New price (percent) after a tick of the given strength (-1..1). Stays within 1..99."""
    p = min(max(price, 1.0), 99.0) / 100
    x = math.log(p / (1 - p)) + k * strength
    return min(max(100 / (1 + math.exp(-x)), 1.0), 99.0)


def history(price: float, ticks: list[tuple[float, float]], k: float = 0.4, lead: float = 3600) -> list[tuple[float, float]]:
    """The path a made-up price took to reach `price`, drawn from the coverage found for it: [(ts, price)],
    oldest first. `ticks` are (when published, strength) of the items found. Walking back from the price,
    each item is undone in turn, so the line steps at every item and ends where the price stands now.
    It opens `lead` seconds before the oldest item, at the price before any of them. Empty without ticks."""
    out: list[tuple[float, float]] = []
    for ts, strength in sorted(ticks, reverse=True):
        if not out or out[-1][0] != ts:  # two items of one moment are one step
            out.append((ts, price))
        price = nudge(price, -strength, k)
    if out:
        out.append((out[-1][0] - lead, price))
    return out[::-1]
