"""Plot run-level means for six independent controls and six attacks."""

import argparse
import csv
import json
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load(path):
    path = path / "summary.json" if path.is_dir() else path
    return json.loads(path.read_text()), json.loads(
        (path.parent / "viewer-traces.json").read_text())


def check(controls, attacks):
    runs = controls + attacks
    if len({summary["run_id"] for summary, _ in runs}) != 12:
        raise ValueError("Supply twelve distinct runs")
    first = controls[0][0]["configuration"]
    keys = ("clients", "reward_lambda", "fault_sha256", "mpd",
            "seconds", "measurement_start")
    if (first["clients"], first["reward_lambda"], first["seconds"],
            first["measurement_start"]) != (10, 10, 120, 40):
        raise ValueError("Expected ten clients, lambda=10 and a 40–120 s window")
    for summary, _ in runs:
        config = summary["configuration"]
        if not summary["success"] or not config.get("allow_viewer_failure"):
            raise ValueError(f"Incomplete QoE run: {summary['run_id']}")
        if any(config.get(key) != first.get(key) for key in keys):
            raise ValueError(f"Different conditions: {summary['run_id']}")
    if any(s["configuration"]["malicious_count"] for s, _ in controls):
        raise ValueError("A control has modified clients")
    attack = attacks[0][0]["configuration"]
    count, ttlb = attack["malicious_count"], attack["attack_ttlb"]
    if not 1 <= count < 10:
        raise ValueError("Attack must leave honest clients")
    for summary, _ in attacks:
        config = summary["configuration"]
        if (config["malicious_count"], config["attack_ttlb"],
                config["attack_delay"], config.get("attack_from_start")) != (
                count, ttlb, 40, False):
            raise ValueError(f"Different attack: {summary['run_id']}")
    return count, ttlb


def client_series(trace, start, grid):
    end = start + 1000 * grid[-1]
    ticks = [t for t in trace["ticks"] if start <= t["ms"] <= end]
    x = np.array([(t["ms"] - start) / 1000 for t in ticks])
    if len(x) < 2 or x[0] > 0.01 or x[-1] < grid[-1] - 0.6:
        raise ValueError("Incomplete playback trace")
    lost = [0.0]
    for before, after in zip(ticks, ticks[1:]):
        lost.append(lost[-1] + (after["ms"] - before["ms"]) / 1000
                    * (after["time"] - before["time"] < 0.05))
    waiting, stalls = None, []
    for event in trace["events"]:
        when = event["ms"]
        if when > end:
            break
        if event["type"] == "waiting" and waiting is None and not event["paused"]:
            waiting = when
        if event["type"] in ("playing", "pause", "media_error", "ended"):
            if waiting is not None:
                stalls.append((waiting, when))
                waiting = None
    if waiting is not None:
        stalls.append((waiting, end))
    rebuffer = [sum(max(0, min(start + 1000 * t, stop) - max(start, begin))
                    for begin, stop in stalls) / 1000 for t in grid]
    indices = np.clip(np.searchsorted(x, grid, side="right") - 1, 0, len(x) - 1)
    quality = [float(ticks[i]["quality_kbps"])
               if ticks[i]["quality_kbps"] is not None else np.nan
               for i in indices]
    return np.interp(grid, x, lost), np.array(rebuffer), np.array(quality)


def run_series(summary, traces, first_honest, grid):
    clients = [v for v in summary["viewers"] if v["client"] >= first_honest]
    series = [client_series(traces[str(v["client"])],
                            v["qoe"]["window_start_ms"], grid) for v in clients]
    output = []
    for metric in range(3):
        values = np.stack([item[metric] for item in series])
        valid = np.sum(np.isfinite(values), axis=0)
        output.append(np.divide(np.nansum(values, axis=0), valid,
                                out=np.full(len(grid), np.nan), where=valid > 0))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", type=Path, nargs=6, required=True)
    parser.add_argument("--attacks", type=Path, nargs=6, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    controls = [load(p) for p in args.controls]
    attacks = [load(p) for p in args.attacks]
    count, ttlb = check(controls, attacks)
    duration = min(v["qoe"]["window_seconds"]
                   for summary, _ in controls + attacks for v in summary["viewers"])
    grid = np.arange(0, int(duration) + 1)
    fig, axes = plt.subplots(4, 1, figsize=(10, 11), sharex=True,
                             constrained_layout=True)
    rows = []
    groups = {}
    for label, color, runs in (("Controle", "#2166ac", controls),
                               ("Ataque", "#b2182b", attacks)):
        curves = [run_series(s, t, count + 1, grid) for s, t in runs]
        groups[label] = curves
        for axis, metric in zip(axes[:3], range(3)):
            values = np.stack([curve[metric] for curve in curves])
            valid = np.sum(np.isfinite(values), axis=0)
            mean = np.divide(np.nansum(values, axis=0), valid,
                             out=np.full(len(grid), np.nan), where=valid > 0)
            sd = np.nanstd(values, axis=0, ddof=1)
            axis.plot(grid, mean, color=color, linewidth=2, label=label)
            axis.fill_between(grid, mean - sd, mean + sd, color=color, alpha=0.16)
        for summary, _ in runs:
            viewers = [v for v in summary["viewers"] if v["client"] > count]
            quality = [v["qoe"]["rendered_quality_kbps"] for v in viewers
                       if v["qoe"]["rendered_quality_kbps"] is not None]
            index = [v["qoe"]["qoe_index"] for v in viewers]
            rows.append(dict(
                condition=label, run_id=summary["run_id"],
                mean_rebuffer_seconds=statistics.mean(v["rebuffer_seconds"]
                                                       for v in viewers),
                mean_no_progress_fraction=statistics.mean(
                    v["qoe"]["no_progress_fraction"] for v in viewers),
                terminal_failures=sum(v["qoe"]["terminal_failure"] for v in viewers),
                mean_rendered_quality_kbps=statistics.mean(quality) if quality else None,
                mean_qoe_index=statistics.mean(index) if all(v is not None for v in index)
                else None,
            ))
    controls_lost = np.stack([curve[0] for curve in groups["Controle"]])
    attacks_lost = np.stack([curve[0] for curve in groups["Ataque"]])
    effect = attacks_lost.mean(axis=0) - controls_lost.mean(axis=0)
    rng = np.random.default_rng(20261104)
    boot = (attacks_lost[rng.integers(0, 6, size=(2000, 6))].mean(axis=1)
            - controls_lost[rng.integers(0, 6, size=(2000, 6))].mean(axis=1))
    lower, upper = np.percentile(boot, (2.5, 97.5), axis=0)
    axes[3].plot(grid, effect, color="#20242a", linewidth=2)
    axes[3].fill_between(grid, lower, upper, color="#20242a", alpha=0.16)
    axes[3].axhline(0, color="gray", linewidth=1)
    for axis, ylabel in zip(axes, ("Sem progresso acumulado (s)",
                                     "Rebuffer acumulado (s)",
                                     "Qualidade exibida (kb/s)",
                                     "Excesso sem progresso (s)")):
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.2)
    for axis in axes[:3]:
        axis.set_ylim(bottom=0)
    axes[0].legend()
    axes[-1].set_xlabel("Segundos desde o início do ataque / janela")
    fig.suptitle(f"Clientes honestos {count + 1}–10 · M={count} · "
                 f"TTLB={ttlb} ms · 6 runs por grupo (média ± DP)")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160)
    plt.close(fig)
    with args.output.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
