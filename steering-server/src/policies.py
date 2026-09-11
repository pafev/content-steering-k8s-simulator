"""Policies over per-pathway sufficient statistics.

UCB1: Auer et al. (2002), exploration sqrt(2 log(t) / n).
LinUCB: Li et al. (WWW 2010), disjoint ridge models, alpha=1.
Context: intercept and pre-decision session buffer.
"""
import math

STRATEGIES = {"fixed", "random", "epsilon_greedy", "ucb1", "linucb"}


def rank_pathways(strategy, pathways, stats, context, rng):
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    if strategy == "fixed":
        return list(pathways)
    order = list(pathways)
    rng.shuffle(order)
    if strategy == "random" or (strategy == "epsilon_greedy" and rng.random() < 0.2):
        return order
    counts = {p: int(stats.get(p, {}).get("n", 0)) for p in order}
    total = max(1, sum(counts.values()))

    def score(pathway):
        s = stats.get(pathway, {})
        n = counts[pathway]
        if strategy != "linucb":
            if not n:
                return float("inf")
            mean = float(s.get("reward_sum", 0)) / n
            return mean + (math.sqrt(2 * math.log(total) / n) if strategy == "ucb1" else 0)
        # A = I + sum(x x^T), b = sum(reward x), one model per pathway.
        a = 1 + float(s.get("a00", 0))
        off = float(s.get("a01", 0))
        d = 1 + float(s.get("a11", 0))
        b0, b1 = float(s.get("b0", 0)), float(s.get("b1", 0))
        determinant = a * d - off * off
        x0, x1 = context
        v0 = (d * x0 - off * x1) / determinant
        v1 = (a * x1 - off * x0) / determinant
        return v0 * b0 + v1 * b1 + math.sqrt(max(0, x0 * v0 + x1 * v1))

    return sorted(order, key=score, reverse=True)
