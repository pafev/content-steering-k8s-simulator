"""Compare modified-player runs with all clean controls in each replicate."""

import argparse
import csv
import json
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REWARDS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4)
COUNTS = range(1, 7)
PRICES_USD_PER_GB = {"cdn-1": 0.045, "cdn-2": 0.11, "cdn-3": 0.10}


def read_run(path):
    summary = json.loads(path.read_text())
    if not summary.get("success"):
        raise ValueError(f"Incomplete run: {path}")
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


def buffering_ratio(run, clients):
    viewers = {viewer["client"]: viewer for viewer in run["summary"]["viewers"]}
    return sum(viewers[client]["buffering_ratio"] for client in clients) / len(clients)


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


def plot(rows, field, label, output):
    grid = np.full((len(COUNTS), len(REWARDS)), np.nan)
    for count in COUNTS:
        for index, reward in enumerate(REWARDS):
            values = [
                row[field]
                for row in rows
                if row["malicious_count"] == count and row["claimed_reward"] == reward
            ]
            if values:
                grid[count - 1, index] = sum(values) / len(values)
    fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
    masked = np.ma.masked_invalid(grid)
    maximum = max(
        0.05, float(np.nanmax(np.abs(grid))) if np.isfinite(grid).any() else 0.05
    )
    image = ax.imshow(masked, cmap="RdBu_r", vmin=-maximum, vmax=maximum, aspect="auto")
    image.cmap.set_bad("#eeeeee")
    ax.set(
        xticks=range(len(REWARDS)),
        xticklabels=[f"{v:.1f}" for v in REWARDS],
        yticks=range(len(COUNTS)),
        yticklabels=list(COUNTS),
        xlabel="Claimed reward for CDN-1 delivery",
        ylabel="Modified players out of 10",
        title=label,
    )
    for y, count in enumerate(COUNTS):
        for x, reward in enumerate(REWARDS):
            if np.isfinite(grid[y, x]):
                trials = sum(
                    row["malicious_count"] == count and row["claimed_reward"] == reward
                    for row in rows
                )
                ax.text(
                    x,
                    y,
                    f"{grid[y, x]:+.3f}\n(n={trials})",
                    ha="center",
                    va="center",
                    fontsize=9,
                )
    fig.colorbar(image, ax=ax, label="Attack − matched clean control")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="Directory containing control and attack run summaries"
    )
    parser.add_argument(
        "--strategy", choices=("ucb1", "epsilon_greedy", "linucb"), required=True
    )
    parser.add_argument(
        "--output", type=Path, help="Figure directory (default: INPUT/plots/STRATEGY)"
    )
    parser.add_argument("--require-complete", action="store_true",
                        help="Require six controls and all 36 attack cells per replicate")
    args = parser.parse_args()
    runs = [read_run(path) for path in args.input.rglob("summary.json")]
    runs = [run for run in runs if run["summary"]["strategy"] == args.strategy]
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
            cells = {(run["summary"]["configuration"]["malicious_count"],
                      round(run["summary"]["configuration"]["attack_reward"], 1))
                     for run in attacks}
            expected = {(m, r) for m in COUNTS for r in REWARDS}
            if len(group) != 6 or cells != expected or len(attacks) != 36:
                raise ValueError(f"Incomplete replicate {replicate}: "
                                 f"{len(group)} controls, {len(cells)} distinct cells, "
                                 f"{len(attacks)} attack runs")
    rows = []
    for attack in runs:
        config = attack["summary"]["configuration"]
        count = config["malicious_count"]
        if not count:
            continue
        if config["malicious_cdn"] != "cdn-1":
            raise ValueError(f"Risk matrix expects attacks on CDN-1: {attack['path']}")
        reward = round(config["attack_reward"], 1)
        if count not in COUNTS or reward not in REWARDS:
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
            ):
                raise ValueError(f"Control and attack conditions differ: {attack['path']}")
        clients = range(count + 1, 11)
        p_control = sum(steering_probability(c, clients) for c in matched) / len(matched)
        p_attack = steering_probability(attack, clients)
        b_control = sum(buffering_ratio(c, clients) for c in matched) / len(matched)
        b_attack = buffering_ratio(attack, clients)
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
                claimed_reward=reward,
                p_control=p_control,
                p_attack=p_attack,
                d_steer=p_attack - p_control,
                b_control=b_control,
                b_attack=b_attack,
                d_viewer=b_attack - b_control,
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
                claimed_reward_gap=reward - best_alternative,
                falsified_learning_count=falsified,
                target_cdn_learning_count=target_count,
                falsified_feedback_share=falsified / target_count,
                control_order_valid=means["cdn-1"] > means["cdn-3"] > means["cdn-2"],
                controls=[c["path"] for c in matched],
                attack=attack["path"],
            )
        )
    output = args.output or args.input / "plots" / args.strategy
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
    write_table(output / "cells.csv", rows,
                ["replicate", "malicious_count", "claimed_reward", "g_13", "g_12",
                 "d_steer", "d_viewer", "c_attack", "delta_c",
                 "observed_cost_usd", "falsified_feedback_share", "attack"])
    plot(
        rows,
        "d_steer",
        "D_steer: change in honest viewers' delayed-CDN priority",
        output / "D_steer.png",
    )
    plot(
        rows,
        "d_viewer",
        "D_viewer: change in honest viewers' buffering fraction",
        output / "D_viewer.png",
    )
    plot(rows, "delta_c", "Change in unit egress cost (USD/GB)",
         output / "Delta_c.png")
    print(f"Wrote {len(rows)} paired comparisons to {output}")
    if any(not row["control_order_valid"] for row in rows):
        print(
            "Warning: at least one control did not show CDN-1 > CDN-3 > CDN-2 in observed reward"
        )


if __name__ == "__main__":
    main()
