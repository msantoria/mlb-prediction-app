"""Summaries of real samples, never synthetic probability claims from a mean."""
import math
import statistics


def percentile(values, q):
    ordered = sorted(values)
    at = (len(ordered) - 1) * q
    low = math.floor(at)
    high = math.ceil(at)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def empirical(values, baseline=None):
    if not values:
        return None
    n = len(values)
    result = {"mean": statistics.mean(values), "median": statistics.median(values),
              "sd": statistics.pstdev(values), "sample_size": n,
              "p0": sum(v == 0 for v in values) / n}
    result.update({f"p{k}_plus": sum(v >= k for v in values) / n for k in (1, 2, 3, 4, 5, 6, 75, 90)})
    result.update({f"p{int(q * 100)}": percentile(values, q) for q in (.1, .25, .75, .9)})
    if baseline is not None:
        result.update(probability_over_baseline=sum(v > baseline for v in values) / n,
                      probability_under_baseline=sum(v < baseline for v in values) / n,
                      probability_equal_baseline=sum(v == baseline for v in values) / n)
    return result


def wilson(successes, n):
    if not n:
        return None
    p, z = successes / n, 1.96
    centre = (p + z*z/(2*n)) / (1 + z*z/n)
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return [max(0, centre-radius), min(1, centre+radius)]
