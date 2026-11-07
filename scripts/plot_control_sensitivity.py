"""Summarize honest reward gaps and steering by lambda, not a sensitivity scale."""

import argparse
import csv
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REGIMES = ("low", "medium", "high")
LABELS = (r"$\lambda=1$", r"$\lambda=10$", r"$\lambda=25$")
FIELDS = ("g_13", "g_12", "cdn1_first_priority")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("results/research-matrices"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    averages = {}
    for regime in REGIMES:
        path = args.root / regime / "plots" / "ucb1" / "controls.csv"
        with path.open(newline="") as file:
            rows = list(csv.DictReader(file))
        if len(rows) != 6 or any(row["reward_order_valid"] != "True" for row in rows):
            raise ValueError(f"Expected six valid honest controls in {path}")
        averages[regime] = {field: mean(float(row[field]) for row in rows) for field in FIELDS}

    x = np.arange(len(REGIMES))
    fig, (gaps, priority) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for shift, field, label, color in ((-0.18, "g_13", r"$g_{13}$", "#4c78a8"),
                                       (0.18, "g_12", r"$g_{12}$", "#f58518")):
        values = [averages[regime][field] for regime in REGIMES]
        bars = gaps.bar(x + shift, values, width=0.34, label=label, color=color)
        gaps.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
    gaps.set(title="Separação das recompensas", ylabel="Gap médio", xticks=x, xticklabels=LABELS)
    gaps.set_ylim(0, max(averages[regime]["g_12"] for regime in REGIMES) * 1.2)
    gaps.legend(frameon=False)

    values = [100 * averages[regime]["cdn1_first_priority"] for regime in REGIMES]
    bars = priority.bar(x, values, width=0.55, color="#54a24b")
    priority.bar_label(bars, fmt="%.1f%%", padding=3)
    priority.set(title="CDN-1 em primeira prioridade", ylabel="Média dos controles (%)",
                 xticks=x, xticklabels=LABELS, ylim=(0, 100))
    for ax in (gaps, priority):
        ax.set_xlabel("Coeficiente da recompensa")
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Seis controles honestos por regime (UCB1)", fontsize=13)
    output = args.output or args.root / "controls-sensitivity.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
