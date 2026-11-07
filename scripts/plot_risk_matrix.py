"""Compare modified-player runs with all clean controls in each replicate."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

TTLB_VALUES_MS = (90, 200, 340, 530, 800, 1200)
COUNTS = range(1, 7)
PRICES_USD_PER_GB = {"cdn-1": 0.045, "cdn-2": 0.11, "cdn-3": 0.10}
# Fixed limits make the same color mean the same effect in every regime.
# Values outside a limit retain their numeric annotation; the colorbar marks clipping.
PLOT_SPECS = {
    "d_steer": (r"$D_{\mathrm{steer}}$", "pontos percentuais", 100, 50, 1),
    "delta_c": (r"$\Delta_{\mathrm{egress\ cost}}$", "USD/GB", 1, 0.025, 4),
}


def read_run(path):
    summary = json.loads(path.read_text())
    if not summary.get("success"):
        return None  # Keep failed artifacts, but only analyze completed attempts.
    cache = json.loads((path.parent / "cache-validation.json").read_text())
    if cache.get("cached_non_hit_responses"):
        return None  # Cached but stale media is not comparable to HIT-only cells.
    config = summary["configuration"]
    if config["clients"] != 10:
        raise ValueError(f"Expected 10 players: {path}")
    events = [
        json.loads(line)
        for line in (path.parent / "events.jsonl").read_text().splitlines()
        if line
    ]
    return dict(path=str(path), summary=summary, events=events)


def steering_probability(run, clients):
    summary = run["summary"]
    start = summary["observation_start"]
    config = summary["configuration"]
    end = summary.get(
        "observation_end",
        start + config["seconds"] - config.get("measurement_start", 0),
    )
    values = []
    for client in clients:
        priorities = [
            event["response"]["PATHWAY-PRIORITY"][0]
            for event in run["events"]
            if event["kind"] == "steering"
            and event.get("status") == 200
            and event["client"] == client
            and start <= event["elapsed"] < end
            and event.get("response", {}).get("PATHWAY-PRIORITY")
        ]
        if not priorities:
            raise ValueError(
                f"No observed steering response for client {client}: {run['path']}"
            )
        values.append(
            sum(pathway in ("cdn-2", "cdn-3") for pathway in priorities)
            / len(priorities)
        )
    return sum(values) / len(values)


def mean_reward(run):
    model = run["summary"]["final"]["state"]["model"]
    if any(int(model[p].get("n", 0)) == 0 for p in PRICES_USD_PER_GB):
        raise ValueError(f"Control did not learn all three CDNs: {run['path']}")
    return {p: float(model[p]["reward_sum"]) / int(model[p]["n"])
            for p in PRICES_USD_PER_GB}


def unit_cost(run):
    byte_counts = run["summary"].get("cdn_bytes_window")
    if byte_counts is None:
        raise ValueError(f"Missing interval byte counters: {run['path']}")
    if any(byte_counts[p] < 0 for p in PRICES_USD_PER_GB):
        raise ValueError(f"Negative byte delta: {run['path']}")
    total = sum(byte_counts.values())
    if not total:
        raise ValueError(f"No delivered bytes in analysis window: {run['path']}")
    return sum(byte_counts[p] * price for p, price in PRICES_USD_PER_GB.items()) / total


def observed_cost(run):
    byte_counts = run["summary"]["cdn_bytes_window"]
    return sum(byte_counts[p] * price for p, price in PRICES_USD_PER_GB.items()) / 1e9


def write_table(path, rows, columns):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot(rows, field, output):
    title, unit, multiplier, limit, decimals = PLOT_SPECS[field]
    grid = np.full((len(COUNTS), len(TTLB_VALUES_MS)), np.nan)
    for count in COUNTS:
        for index, ttlb in enumerate(TTLB_VALUES_MS):
            values = [
                row[field]
                for row in rows
                if row["malicious_count"] == count and row["claimed_ttlb_ms"] == ttlb
            ]
            if values:
                grid[count - 1, index] = sum(values) / len(values) * multiplier
    fig, ax = plt.subplots(figsize=(9.2, 5.8), constrained_layout=True)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f3f4f6")
    masked = np.ma.masked_invalid(grid)
    cmap = LinearSegmentedColormap.from_list(
        "effect", ["#2166ac", "#f7f7f7", "#b2182b"]
    ).copy()
    cmap.set_bad("#e5e7eb")
    image = ax.imshow(masked, cmap=cmap, vmin=-limit, vmax=limit, aspect="auto")
    ax.set(
        xticks=range(len(TTLB_VALUES_MS)),
        xticklabels=[str(v) for v in TTLB_VALUES_MS],
        yticks=range(len(COUNTS)),
        yticklabels=list(COUNTS),
        xlabel="TTLB declarado para CDN-1 (ms)",
        ylabel="Clientes modificados (de 10)",
    )
    ax.set_xticks(np.arange(-0.5, len(TTLB_VALUES_MS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(COUNTS), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for y, count in enumerate(COUNTS):
        for x, ttlb in enumerate(TTLB_VALUES_MS):
            if np.isfinite(grid[y, x]):
                value = grid[y, x]
                shown = f"{value:+.{decimals}f}" if abs(value) >= 0.5 * 10 ** -decimals else f"{0:.{decimals}f}"
                ax.text(
                    x,
                    y,
                    shown,
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="medium",
                    color="white" if abs(value) > 0.67 * limit else "#20242a",
                )
    below = np.isfinite(grid).any() and float(np.nanmin(grid)) < -limit
    above = np.isfinite(grid).any() and float(np.nanmax(grid)) > limit
    extend = "both" if below and above else "min" if below else "max" if above else "neither"
    colorbar = fig.colorbar(image, ax=ax, extend=extend, shrink=0.88, pad=0.035)
    colorbar.set_ticks(np.linspace(-limit, limit, 5))
    colorbar.set_label(f"Ataque − controles ({unit})")
    colorbar.outline.set_visible(False)
    ax.set_title(title, loc="left", fontsize=15, fontweight="semibold", pad=16)
    fig.savefig(output, dpi=180, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="Directory containing control and attack run summaries"
    )
    parser.add_argument(
        "--strategy", choices=("ucb1", "epsilon_greedy", "linucb"), required=True
    )
    parser.add_argument("--replicate", type=int,
                        help="Analyze only this replicate (default: all replicates)")
    parser.add_argument(
        "--output", type=Path, help="Figure directory (default: INPUT/plots/STRATEGY)"
    )
    parser.add_argument("--require-complete", action="store_true",
                        help="Require six controls and two valid runs in each of 36 attack cells")
    args = parser.parse_args()
    found = [read_run(path) for path in args.input.rglob("summary.json")]
    if any(run is None for run in found):
        print(f"Ignoring {sum(run is None for run in found)} failed or non-HIT run(s)")
    runs = [run for run in found if run is not None]
    runs = [run for run in runs if run["summary"]["strategy"] == args.strategy]
    if args.replicate is not None:
        runs = [run for run in runs
                if run["summary"]["configuration"]["replicate"] == args.replicate]
    if not runs:
        raise ValueError(f"No {args.strategy} runs in {args.input}")
    controls = {}
    for run in runs:
        config = run["summary"]["configuration"]
        if config["malicious_count"] == 0:
            replicate = config["replicate"]
            controls.setdefault(replicate, []).append(run)
    if args.require_complete:
        for replicate, group in controls.items():
            attacks = [run for run in runs
                       if run["summary"]["configuration"]["replicate"] == replicate
                       and run["summary"]["configuration"]["malicious_count"]]
            cells = Counter(
                (run["summary"]["configuration"]["malicious_count"],
                 run["summary"]["configuration"]["attack_ttlb"])
                for run in attacks
            )
            expected = {(m, ttlb) for m in COUNTS for ttlb in TTLB_VALUES_MS}
            if len(group) != 6 or set(cells) != expected or any(
                cells[cell] != 2 for cell in expected
            ):
                raise ValueError(f"Incomplete replicate {replicate}: "
                                 f"{len(group)} controls, {len(cells)} distinct cells, "
                                 f"{len(attacks)} attack runs; expected two per cell")
    rows = []
    for attack in runs:
        config = attack["summary"]["configuration"]
        count = config["malicious_count"]
        if not count:
            continue
        if config["malicious_cdn"] != "cdn-1":
            raise ValueError(f"Risk matrix expects attacks on CDN-1: {attack['path']}")
        ttlb = config["attack_ttlb"]
        if count not in COUNTS or ttlb not in TTLB_VALUES_MS:
            continue
        matched = controls.get(config["replicate"], [])
        if not matched:
            raise ValueError(f"Missing clean control for {attack['path']}")
        for control in matched:
            if (
                control["summary"]["configuration"]["mpd"] != config["mpd"]
                or control["summary"]["configuration"].get("fault_manifest")
                != config.get("fault_manifest")
                or control["summary"]["configuration"].get("fault_sha256")
                != config.get("fault_sha256")
                or control["summary"]["configuration"]["seconds"] != config["seconds"]
                or control["summary"]["configuration"].get("measurement_start", 0)
                != config.get("measurement_start", 0)
                or control["summary"]["configuration"].get("reward_lambda", 5)
                != config.get("reward_lambda", 5)
                or control["summary"]["configuration"].get("max_video_kbps", 1500)
                != config.get("max_video_kbps", 1500)
            ):
                raise ValueError(f"Control and attack conditions differ: {attack['path']}")
        clients = range(count + 1, 11)
        p_control = sum(steering_probability(c, clients) for c in matched) / len(matched)
        p_attack = steering_probability(attack, clients)
        means = {p: sum(mean_reward(c)[p] for c in matched) / len(matched)
                 for p in PRICES_USD_PER_GB}
        best_alternative = max(means["cdn-2"], means["cdn-3"])
        c_control = sum(unit_cost(c) for c in matched) / len(matched)
        c_attack = unit_cost(attack)
        target_model = attack["summary"]["final"]["state"]["model"][
            config["malicious_cdn"]
        ]
        target_count = int(target_model.get("n", 0))
        falsified = attack["summary"]["malicious"]["accepted_falsified"]
        if not target_count or falsified > target_count:
            raise ValueError(f"Invalid falsified feedback count: {attack['path']}")
        rows.append(
            dict(
                strategy=args.strategy,
                replicate=config["replicate"],
                malicious_count=count,
                claimed_ttlb_ms=ttlb,
                mean_accepted_claimed_reward=attack["summary"]["malicious"]["mean_accepted_claimed_reward"],
                p_control=p_control,
                p_attack=p_attack,
                d_steer=p_attack - p_control,
                c_control=c_control,
                c_attack=c_attack,
                delta_c=c_attack - c_control,
                observed_cost_usd=observed_cost(attack),
                prices_usd_per_gb=PRICES_USD_PER_GB,
                cdn_bytes_attack=attack["summary"]["cdn_bytes_window"],
                control_mean_rewards=means,
                g_12=means["cdn-1"] - means["cdn-2"],
                g_13=means["cdn-1"] - means["cdn-3"],
                honest_reward_gap=means["cdn-1"] - best_alternative,
                claimed_reward_gap=(
                    attack["summary"]["malicious"]["mean_accepted_claimed_reward"]
                    - best_alternative
                ),
                falsified_learning_count=falsified,
                target_cdn_learning_count=target_count,
                falsified_feedback_share=falsified / target_count,
                control_order_valid=means["cdn-1"] > means["cdn-3"] > means["cdn-2"],
                controls=[c["path"] for c in matched],
                attack=attack["path"],
            )
        )
    output = args.output or args.input / "plots" / args.strategy
    if args.replicate is not None and args.output is None:
        output /= f"replicate-{args.replicate}"
    output.mkdir(parents=True, exist_ok=True)
    calibrations = []
    for replicate, group in sorted(controls.items()):
        for run in group:
            delivery = run["summary"].get("delivery_calibration")
            rewards = (
                {path: values["mean_learning_reward"] for path, values in delivery.items()}
                if delivery
                else None
            )
            calibrations.append(
                dict(
                    replicate=replicate,
                    reward_lambda=run["summary"]["configuration"].get("reward_lambda", 5),
                    delivery=delivery,
                    mean_rewards=rewards,
                    g_12=rewards["cdn-1"] - rewards["cdn-2"],
                    g_13=rewards["cdn-1"] - rewards["cdn-3"],
                    cdn1_first_priority=1 - steering_probability(run, range(1, 11)),
                    c_usd_per_gb=unit_cost(run),
                    reward_order_valid=(
                        rewards["cdn-1"] > rewards["cdn-3"] > rewards["cdn-2"]
                    )
                    if rewards and all(value is not None for value in rewards.values())
                    else None,
                    control=run["path"],
                )
            )
    (output / "calibration.json").write_text(json.dumps(calibrations, indent=2) + "\n")
    write_table(output / "controls.csv", calibrations,
                ["replicate", "reward_lambda", "g_13", "g_12",
                 "cdn1_first_priority", "c_usd_per_gb", "reward_order_valid", "control"])
    control_summaries = []
    for replicate in sorted(controls):
        group = [item for item in calibrations if item["replicate"] == replicate]
        row = {"replicate": replicate, "reward_lambda": group[0]["reward_lambda"],
               "controls": len(group),
               "reward_order_valid_all": all(item["reward_order_valid"] for item in group)}
        for field in ("g_13", "g_12", "cdn1_first_priority", "c_usd_per_gb"):
            values = [item[field] for item in group]
            row[f"mean_{field}"] = statistics.mean(values)
            row[f"sd_{field}"] = statistics.stdev(values) if len(values) > 1 else None
        control_summaries.append(row)
    write_table(output / "controls-summary.csv", control_summaries,
                ["replicate", "reward_lambda", "controls", "reward_order_valid_all",
                 *(name for field in ("g_13", "g_12", "cdn1_first_priority", "c_usd_per_gb")
                   for name in (f"mean_{field}", f"sd_{field}"))])
    if not rows:
        print(
            f"Wrote {len(calibrations)} control calibrations to {output}; no attack pairs yet"
        )
        return
    (output / "metrics.json").write_text(json.dumps(rows, indent=2) + "\n")
    columns = ["replicate", "malicious_count", "claimed_ttlb_ms",
               "mean_accepted_claimed_reward", "g_13", "g_12",
               "d_steer", "c_attack", "delta_c",
               "observed_cost_usd", "falsified_feedback_share", "attack"]
    write_table(output / "attack-runs.csv", rows, columns)
    groups = {}
    for row in rows:
        key = (row["replicate"], row["malicious_count"], row["claimed_ttlb_ms"])
        groups.setdefault(key, []).append(row)
    cell_rows = []
    averaged = ("mean_accepted_claimed_reward", "g_13", "g_12", "d_steer",
                "c_attack", "delta_c", "observed_cost_usd",
                "falsified_feedback_share")
    for key, group in sorted(groups.items()):
        cell = dict(replicate=key[0], malicious_count=key[1],
                    claimed_ttlb_ms=key[2], attack_runs=len(group))
        cell.update({field: statistics.mean(row[field] for row in group)
                     for field in averaged})
        cell_rows.append(cell)
    write_table(output / "cells.csv", cell_rows,
                ["replicate", "malicious_count", "claimed_ttlb_ms",
                 "attack_runs",
                 "mean_accepted_claimed_reward", "g_13", "g_12",
                 "d_steer", "c_attack", "delta_c",
                 "observed_cost_usd", "falsified_feedback_share"])
    for field, filename in (("d_steer", "D_steer.png"),
                            ("delta_c", "Delta_c.png")):
        plot(cell_rows, field, output / filename)
    print(f"Wrote {len(cell_rows)} cell averages from {len(rows)} attack runs to {output}")
    if any(not row["control_order_valid"] for row in rows):
        print(
            "Warning: at least one control did not show CDN-1 > CDN-3 > CDN-2 in observed reward"
        )


if __name__ == "__main__":
    main()
