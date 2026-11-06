"""Plot QoE dose response from six shared controls and two attacks per TTLB."""

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


METRICS = (
    ("qoe_index", "Índice composto de QoE", "qoe-dose-response.png"),
    ("no_progress_seconds", "Tempo sem progresso (s)", "no-progress.png"),
    ("rebuffer_seconds", "Rebuffer (s)", "rebuffer.png"),
    ("rendered_quality_kbps", "Qualidade exibida (kb/s)", "rendered-quality.png"),
    ("terminal_failures", "Falhas terminais entre 7 honestos", "terminal-failures.png"),
)


def read_run(path):
    summary = json.loads(path.read_text())
    if not summary.get("success"):
        return None
    cache = json.loads((path.parent / "cache-validation.json").read_text())
    if cache.get("cached_non_hit_responses"):
        return None
    config = summary["configuration"]
    viewers = {viewer["client"]: viewer for viewer in summary["viewers"]}
    honest = [viewers[client] for client in range(4, 11)]
    if any(viewer["qoe"]["qoe_index"] is None for viewer in honest):
        raise ValueError(f"Missing QoE index for an honest client: {path}")
    quality = [viewer["qoe"]["rendered_quality_kbps"] for viewer in honest
               if viewer["qoe"]["rendered_quality_kbps"] is not None]
    return {
        "run_id": summary["run_id"], "summary_path": str(path),
        "kind": "control" if config["malicious_count"] == 0 else "attack",
        "ttlb_ms": config.get("attack_ttlb") or 0,
        "configuration": config,
        "qoe_index": mean(viewer["qoe"]["qoe_index"] for viewer in honest),
        "no_progress_seconds": mean(viewer["qoe"]["no_progress_seconds"]
                                    for viewer in honest),
        "rebuffer_seconds": mean(viewer["rebuffer_seconds"] for viewer in honest),
        "rendered_quality_kbps": mean(quality) if quality else None,
        "terminal_failures": sum(viewer["qoe"]["terminal_failure"]
                                 for viewer in honest),
    }


def validate(runs, doses):
    if len({run["run_id"] for run in runs}) != len(runs):
        raise ValueError("Duplicate run IDs")
    controls = [run for run in runs if run["kind"] == "control"]
    attacks = [run for run in runs if run["kind"] == "attack"]
    if len(controls) != 6 or len(attacks) != 2 * len(doses):
        raise ValueError("Expected six controls and two attacks per TTLB")
    reference = controls[0]["configuration"]
    keys = ("strategy", "clients", "reward_lambda", "seconds",
            "measurement_start", "fault_sha256", "mpd", "replicate")
    if (reference["clients"], reference["reward_lambda"],
            reference["seconds"], reference["measurement_start"]) != (10, 10, 120, 40):
        raise ValueError("Expected 10 clients, lambda=10 and a 40–120 s window")
    if reference["strategy"] != "ucb1" or not reference["fault_sha256"]:
        raise ValueError("Expected UCB1 and a versioned NetChaos manifest")
    for run in runs:
        cfg = run["configuration"]
        if any(cfg.get(key) != reference.get(key) for key in keys):
            raise ValueError(f"Unmatched conditions: {run['summary_path']}")
        if not cfg.get("allow_viewer_failure") or not cfg.get("require_fresh_cache"):
            raise ValueError(f"QoE/cache validation disabled: {run['summary_path']}")
        if run["kind"] == "control":
            if cfg["malicious_count"] != 0:
                raise ValueError("Invalid control")
        elif (cfg["malicious_count"] != 3 or cfg["malicious_cdn"] != "cdn-1"
              or cfg["attack_delay"] != 40 or cfg.get("attack_from_start")
              or run["ttlb_ms"] not in doses):
            raise ValueError(f"Unexpected attack: {run['summary_path']}")
    for dose in doses:
        if sum(run["ttlb_ms"] == dose for run in attacks) != 2:
            raise ValueError(f"Expected two attacks at {dose} ms")
    return controls, attacks


def plot_metric(controls, attacks, doses, field, label, output, primary=False):
    baseline = [run[field] for run in controls if run[field] is not None]
    values = [[run[field] for run in attacks if run["ttlb_ms"] == dose]
              for dose in doses]
    if not baseline:
        return False
    values = [[value for value in group if value is not None] for group in values]
    base_mean = mean(baseline)
    base_sd = stdev(baseline) if len(baseline) > 1 else 0
    averages = [mean(group) if group else float("nan") for group in values]
    fig, axes = plt.subplots(2 if primary else 1, 1,
                             figsize=(8.5, 7 if primary else 4.7),
                             sharex=primary, constrained_layout=True)
    if not primary:
        axes = [axes]
    ax = axes[0]
    ax.axhspan(base_mean - base_sd, base_mean + base_sd,
               color="#2166ac", alpha=0.15, label="Controle ± DP (6 runs)")
    ax.axhline(base_mean, color="#2166ac", linestyle="--")
    for dose, group in zip(doses, values):
        ax.scatter([dose * (0.98 if index == 0 else 1.02)
                    for index in range(len(group))], group, color="#b2182b",
                   s=28, alpha=0.75, zorder=3)
    ax.plot(doses, averages, color="#b2182b", marker="o", linewidth=1.3,
            label="Ataque: média de 2 runs")
    ax.set_ylabel(label)
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    if primary:
        ax.set_ylim(0, 1)
        effect = axes[1]
        effect.axhline(0, color="#2166ac", linestyle="--")
        for dose, group in zip(doses, values):
            effect.scatter([dose * (0.98 if index == 0 else 1.02)
                            for index in range(len(group))],
                           [value - base_mean for value in group],
                           color="#b2182b", s=28, alpha=0.75)
        effect.plot(doses, [value - base_mean for value in averages],
                    color="#b2182b", marker="o", linewidth=1.3)
        effect.set_ylabel("Ataque − controle (QoE)")
        effect.grid(alpha=0.2)
    else:
        ax.set_ylim(bottom=0)
    axes[-1].set_xscale("log")
    axes[-1].set_xticks(doses, [str(dose) for dose in doses])
    axes[-1].set_xlabel("TTLB forjado para CDN-1 (ms)")
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return True


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    doses = [int(value) for value in (args.root / "doses.txt").read_text().split()]
    if len(set(doses)) != len(doses) or any(value <= 0 for value in doses):
        parser.error("doses.txt must contain unique positive TTLBs")
    doses.sort()
    found = [read_run(path) for path in args.root.glob("*/multi-*/summary.json")]
    runs = [run for run in found if run is not None]
    controls, attacks = validate(runs, doses)
    output = args.output or args.root / "plots"
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "run-qoe.csv",
              [{key: value for key, value in run.items() if key != "configuration"}
               for run in runs])
    summary = []
    for dose in doses:
        group = [run for run in attacks if run["ttlb_ms"] == dose]
        row = {"ttlb_ms": dose, "control_runs": 6, "attack_runs": 2}
        for field, _, _ in METRICS:
            control_values = [run[field] for run in controls]
            attack_values = [run[field] for run in group]
            if any(value is None for value in control_values + attack_values):
                row.update({f"control_{field}": None,
                            f"attack_{field}": None, f"delta_{field}": None})
            else:
                c, a = mean(control_values), mean(attack_values)
                row.update({f"control_{field}": c,
                            f"attack_{field}": a, f"delta_{field}": a - c})
        summary.append(row)
    write_csv(output / "dose-summary.csv", summary)
    for field, label, filename in METRICS:
        if not plot_metric(controls, attacks, doses, field, label,
                           output / filename, primary=field == "qoe_index"):
            print(f"Skipped {filename}: no observed video quality in controls")
    print(f"Wrote {len(controls)} controls and {len(attacks)} attacks to {output}")


if __name__ == "__main__":
    main()
