"""Price rule for made-up markets: a scored tick nudges the price in log-odds."""
import math


def nudge(price: float, strength: float, k: float = 0.4) -> float:
    """New price (percent) after a tick of the given strength (-1..1). Stays within 1..99."""
    p = min(max(price, 1.0), 99.0) / 100
    x = math.log(p / (1 - p)) + k * strength
    return min(max(100 / (1 + math.exp(-x)), 1.0), 99.0)
