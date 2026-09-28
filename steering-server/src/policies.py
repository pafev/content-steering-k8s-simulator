"""Policies over per-pathway sufficient statistics.

UCB1: Auer et al. (2002), exploration sqrt(2 log(t) / n).
LinUCB: Li et al. (WWW 2010), disjoint ridge models, alpha=1.
Context: intercept and pre-decision session buffer.
"""
import math

def _rank_fixed(pathways, stats, context, rng):
    return list(pathways)


def _shuffled_pathways(pathways, rng):
    """Randomize equal-score ties without modifying the caller's pathways."""
    order = list(pathways)
    rng.shuffle(order)
    return order


def _rank_random(pathways, stats, context, rng):
    return _shuffled_pathways(pathways, rng)


def _mean_reward(stats):
    count = int(stats.get("n", 0))
    return float(stats.get("reward_sum", 0)) / count if count else float("inf")


def _rank_epsilon_greedy(pathways, stats, context, rng):
    order = _shuffled_pathways(pathways, rng)
    if rng.random() < 0.2:
        return order
    return sorted(order, key=lambda p: _mean_reward(stats.get(p, {})), reverse=True)


def _rank_ucb1(pathways, stats, context, rng):
    order = _shuffled_pathways(pathways, rng)
    counts = {p: int(stats.get(p, {}).get("n", 0)) for p in order}
    total = max(1, sum(counts.values()))

    def score(pathway):
        n = counts[pathway]
        if not n:
            return float("inf")
        return _mean_reward(stats.get(pathway, {})) + math.sqrt(2 * math.log(total) / n)

    return sorted(order, key=score, reverse=True)


def _linucb_score(stats, context):
    """Disjoint LinUCB: x^T A^-1 b + sqrt(x^T A^-1 x), alpha=1."""
    # A = I + sum(x x^T), b = sum(reward x), one model per pathway.
    a = 1 + float(stats.get("a00", 0))
    off = float(stats.get("a01", 0))
    d = 1 + float(stats.get("a11", 0))
    b0, b1 = float(stats.get("b0", 0)), float(stats.get("b1", 0))
    determinant = a * d - off * off
    x0, x1 = context
    v0 = (d * x0 - off * x1) / determinant
    v1 = (a * x1 - off * x0) / determinant
    return v0 * b0 + v1 * b1 + math.sqrt(max(0, x0 * v0 + x1 * v1))


def _rank_linucb(pathways, stats, context, rng):
    order = _shuffled_pathways(pathways, rng)
    return sorted(order, key=lambda p: _linucb_score(stats.get(p, {}), context), reverse=True)


_POLICIES = {
    "fixed": _rank_fixed,
    "random": _rank_random,
    "epsilon_greedy": _rank_epsilon_greedy,
    "ucb1": _rank_ucb1,
    "linucb": _rank_linucb,
}
STRATEGIES = set(_POLICIES)


def rank_pathways(strategy, pathways, stats, context, rng):
    """Rank pathways using the run's strategy and explicit random generator."""
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    return _POLICIES[strategy](pathways, stats, context, rng)
