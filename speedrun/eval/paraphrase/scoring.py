# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The three numbers, their intervals, and the two gaps.

Stdlib only, and deliberately explicit about which interval is used where,
because the three points are not three samples of the same shape:

- **Card recall** is 30 independent binary outcomes. Wilson score interval.
- **R-set accuracy** is 60 outcomes drawn from **30 cards**, two per card. Two
  rewordings of one fact are not two independent observations of a student: a
  student who does not know the fact usually misses both. A Wilson interval on
  n = 60 would therefore be too narrow, so the reported interval is a **cluster
  bootstrap over the 30 cards**. The naive Wilson is printed beside it, labelled
  naive, so the size of the correction is visible rather than asserted.
- **P-set accuracy** is 28 independent binary outcomes. Wilson again.

And the two gaps are not the same shape either:

- **card - R-set** is **paired**: the same 30 facts appear on both sides. The
  interval is a bootstrap over the 30 cards of the per-card difference, which
  keeps the pairing.
- **card - P-set** is **independent**: different items, different provenance.
  Newcombe's hybrid score interval, which is the standard one for a difference
  of two independent proportions with small n.

The pre-registered target is on the second gap: **>= 15 points** between card
recall and P-set accuracy. It is reported whichever way it comes out, and a
result that misses it is printed with the same emphasis as one that clears it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float
    n: int
    method: str

    def pct(self) -> str:
        return f"{100 * self.point:5.1f}%  [{100 * self.low:5.1f}, {100 * self.high:5.1f}]"

    def as_dict(self) -> dict[str, object]:
        return {
            "point": round(self.point, 4),
            "low": round(self.low, 4),
            "high": round(self.high, 4),
            "n": self.n,
            "method": self.method,
        }


def wilson(successes: int, n: int, z: float = Z95) -> Interval:
    """Wilson score interval. Behaves at 0/n and n/n, which Wald does not."""
    if n == 0:
        return Interval(float("nan"), float("nan"), float("nan"), 0, "wilson-95")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return Interval(p, max(0.0, centre - half), min(1.0, centre + half), n, "wilson-95")


def cluster_bootstrap(
    clusters: list[list[int]], *, draws: int = 10000, seed: int = 20260802
) -> Interval:
    """Percentile CI for the item-level mean, resampling whole clusters.

    Each cluster is one card's list of 0/1 item outcomes. Resampling cards
    rather than items is what keeps two rewordings of one fact from counting as
    two independent looks at the student.
    """
    items = [x for cluster in clusters for x in cluster]
    if not items:
        return Interval(float("nan"), float("nan"), float("nan"), 0, "cluster-bootstrap-95")
    point = sum(items) / len(items)
    if len(clusters) < 2:
        return Interval(point, float("nan"), float("nan"), len(items), "cluster-bootstrap-95")
    rng = random.Random(seed)
    means: list[float] = []
    size = len(clusters)
    for _ in range(draws):
        drawn = [clusters[rng.randrange(size)] for _ in range(size)]
        flat = [x for cluster in drawn for x in cluster]
        if flat:
            means.append(sum(flat) / len(flat))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(math.ceil(0.975 * (len(means) - 1)))]
    return Interval(point, low, high, len(items), f"cluster-bootstrap-95 ({size} clusters)")


def paired_bootstrap(
    differences: list[float], *, draws: int = 10000, seed: int = 20260802
) -> Interval:
    """Percentile CI for the mean of per-card differences. Keeps the pairing."""
    if not differences:
        return Interval(float("nan"), float("nan"), float("nan"), 0, "paired-bootstrap-95")
    point = sum(differences) / len(differences)
    if len(differences) < 2:
        return Interval(point, float("nan"), float("nan"), len(differences), "paired-bootstrap-95")
    rng = random.Random(seed)
    means: list[float] = []
    size = len(differences)
    for _ in range(draws):
        means.append(sum(differences[rng.randrange(size)] for _ in range(size)) / size)
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(math.ceil(0.975 * (len(means) - 1)))]
    return Interval(point, low, high, size, "paired-bootstrap-95")


def newcombe(a: Interval, b: Interval) -> Interval:
    """Newcombe hybrid score interval for `a.point - b.point`, a and b independent."""
    if a.n == 0 or b.n == 0:
        return Interval(float("nan"), float("nan"), float("nan"), 0, "newcombe-95")
    difference = a.point - b.point
    low = difference - math.sqrt((a.point - a.low) ** 2 + (b.high - b.point) ** 2)
    high = difference + math.sqrt((a.high - a.point) ** 2 + (b.point - b.low) ** 2)
    return Interval(difference, max(-1.0, low), min(1.0, high), min(a.n, b.n), "newcombe-95")


#: MANIFEST.md, H4, "Pre-registered comparison". Points, not a proportion.
TARGET_GAP_POINTS = 15.0
