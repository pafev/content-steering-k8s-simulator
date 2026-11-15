"""Plot QoE dose response from six shared controls and two or four attacks per TTLB."""

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from viewer_qoe import summarize as summarize_qoe


METRICS = (
    ("qoe_index", "Índice composto de QoE", "qoe-dose-response.png"),
    ("no_progress_seconds", "Tempo sem progresso (s)", "no-progress.png"),
    ("rebuffer_seconds", "Rebuffer (s)", "rebuffer.png"),
    ("buffer_reserve_mean_seconds", "Reserva média de buffer (s)", "buffer-reserve.png"),
    ("low_buffer_seconds", "Tempo com reserva < 18 s (s)", "low-buffer.png"),
    ("rendered_quality_kbps", "Qualidade exibida (kb/s)", "rendered-quality.png"),
    ("terminal_failures", "Falhas terminais entre 7 honestos", "terminal-failures.png"),
    ("media_errors", "Erros de mídia entre 7 honestos", "media-errors.png"),
    ("recovery_successes", "Recuperações entre 7 honestos", "recoveries.png"),
    ("recovery_failures", "Falhas de recuperação entre 7 honestos", "recovery-failures.png"),
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
    qoe_values = [viewer["qoe"]["qoe_index"] for viewer in honest]
    quality = [
        viewer["qoe"]["rendered_quality_kbps"]
        for viewer in honest
        if viewer["qoe"]["rendered_quality_kbps"] is not None
    ]
    def mean_qoe_field(field):
        values = [viewer["qoe"].get(field) for viewer in honest]
        return mean(values) if all(value is not None for value in values) else None
    return {
        "run_id": summary["run_id"],
        "summary_path": str(path),
        "kind": "control" if config["malicious_count"] == 0 else "attack",
        "ttlb_ms": config.get("attack_ttlb") or 0,
        "configuration": config,
        "qoe_index": mean(qoe_values) if all(value is not None for value in qoe_values) else None,
        "no_progress_seconds": mean(
            viewer["qoe"]["no_progress_seconds"] for viewer in honest
        ),
        "rebuffer_seconds": mean(viewer["rebuffer_seconds"] for viewer in honest),
        "buffer_reserve_mean_seconds": mean_qoe_field("buffer_reserve_mean_seconds"),
        "low_buffer_seconds": mean_qoe_field("low_buffer_seconds"),
        "rendered_quality_kbps": mean(quality) if quality else None,
        "terminal_failures": sum(
            viewer["qoe"]["terminal_failure"] for viewer in honest
        ),
        "media_errors": sum(viewer.get("media_errors", 0) for viewer in honest),
        "recovery_successes": sum(viewer.get("recovery_successes", 0) for viewer in honest),
        "recovery_failures": sum(viewer.get("recovery_failures", 0) for viewer in honest),
    }


def validate(runs, doses):
    if len({run["run_id"] for run in runs}) != len(runs):
        raise ValueError("Duplicate run IDs")
    controls = [run for run in runs if run["kind"] == "control"]
    attacks = [run for run in runs if run["kind"] == "attack"]
    per_dose = len(attacks) // len(doses)
    if len(controls) != 6 or per_dose not in (2, 4) or len(attacks) != per_dose * len(doses):
        raise ValueError("Expected six controls and two or four attacks per TTLB")
    reference = controls[0]["configuration"]
    keys = (
        "strategy",
        "clients",
        "reward_lambda",
        "seconds",
        "measurement_start",
        "fault_sha256",
        "mpd",
        "replicate",
        "max_video_kbps",
        "buffer_trace_version",
    )
    if (
        reference["clients"],
        reference["reward_lambda"],
        reference["seconds"],
        reference["measurement_start"],
    ) != (10, 10, 120, 40):
        raise ValueError("Expected 10 clients, lambda=10 and a 40–120 s window")
    if (reference["strategy"] != "ucb1" or not reference["fault_sha256"]
        or reference.get("buffer_trace_version") != 5):
        raise ValueError("Expected UCB1 and a versioned NetChaos manifest")
    for run in runs:
        cfg = run["configuration"]
        if any(cfg.get(key) != reference.get(key) for key in keys):
            raise ValueError(f"Unmatched conditions: {run['summary_path']}")
        if (not cfg.get("allow_viewer_failure") or not cfg.get("require_fresh_cache")
            or not cfg.get("bounded_start") or cfg.get("induce_media_error_at") is not None):
            raise ValueError(f"QoE/cache validation disabled: {run['summary_path']}")
        if run["kind"] == "control":
            if cfg["malicious_count"] != 0:
                raise ValueError("Invalid control")
        elif (
            cfg["malicious_count"] != 3
            or cfg["malicious_cdn"] != "cdn-1"
            or cfg["attack_delay"] != 40
            or cfg.get("attack_from_start")
            or run["ttlb_ms"] not in doses
        ):
            raise ValueError(f"Unexpected attack: {run['summary_path']}")
    for dose in doses:
        if sum(run["ttlb_ms"] == dose for run in attacks) != per_dose:
            raise ValueError(f"Expected {per_dose} attacks at {dose} ms")
    return controls, attacks


def plot_metric(controls, attacks, doses, field, label, output, primary=False):
    baseline = [run[field] for run in controls if run[field] is not None]
    values = [
        [run[field] for run in attacks if run["ttlb_ms"] == dose] for dose in doses
    ]
    if not baseline:
        return False
    values = [[value for value in group if value is not None] for group in values]
    base_mean = mean(baseline)
    base_sd = stdev(baseline) if len(baseline) > 1 else 0
    averages = [mean(group) if group else float("nan") for group in values]
    fig, axes = plt.subplots(
        2 if primary else 1,
        1,
        figsize=(8.5, 7 if primary else 4.7),
        sharex=primary,
        constrained_layout=True,
    )
    if not primary:
        axes = [axes]
    fig.suptitle(
        f"Teto ABR: {controls[0]['configuration'].get('max_video_kbps', 3000)} kb/s"
    )
    ax = axes[0]
    ax.axhspan(
        base_mean - base_sd,
        base_mean + base_sd,
        color="#2166ac",
        alpha=0.15,
        label="Controle: média ± desvio padrão (6 runs)",
    )
    ax.axhline(base_mean, color="#2166ac", linestyle="--",
               label="Controle: média")
    for dose, group in zip(doses, values):
        for index, value in enumerate(group):
            ax.scatter(dose, value,
                       marker="o", s=12, color="#b2182b", alpha=0.5,
                       zorder=3 + index)
    ax.plot(
        doses,
        averages,
        color="#b2182b",
        marker="o",
        markersize=8,
        linewidth=1.3,
        label=f"Ataque: média de {len(attacks) // len(doses)} runs",
        zorder=8,
    )
    ax.set_ylabel(label)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Line2D([], [], color="#b2182b", marker="o", markersize=4,
                          alpha=0.5, linestyle="None"))
    labels.append(f"Ataques individuais ({len(attacks) // len(doses)} por dose)")
    ax.legend(handles, labels, loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    if primary:
        ax.set_ylim(0, 1)
        effect = axes[1]
        effect.axhline(0, color="#2166ac", linestyle="--")
        for dose, group in zip(doses, values):
            for index, value in enumerate(group):
                effect.scatter(dose, value - base_mean, marker="o", s=12,
                               color="#b2182b", alpha=0.5, zorder=3 + index)
        effect.plot(
            doses,
            [value - base_mean for value in averages],
            color="#b2182b",
            marker="o",
            markersize=8,
            linewidth=1.3,
            zorder=8,
        )
        effect.set_ylabel("Ataque − controle (QoE)")
        effect.grid(alpha=0.2)
    else:
        observed = baseline + [value for group in values for value in group]
        if field in ("terminal_failures", "media_errors", "recovery_successes",
                     "recovery_failures"):
            ax.set_ylim(-0.15, max(1, math.ceil(max(observed))) + 0.5)
            ax.set_yticks(range(max(1, math.ceil(max(observed))) + 1))
        elif field == "rendered_quality_kbps":
            ax.set_ylim(0, controls[0]["configuration"]["max_video_kbps"] * 1.05)
        else:
            ax.set_ylim(0, max(1, max(observed) * 1.2))
    if len(doses) > 1:
        axes[-1].set_xscale("log")
    else:
        axes[-1].set_xlim(doses[0] * 0.9, doses[0] * 1.1)
    axes[-1].set_xticks(doses, [str(dose) for dose in doses])
    axes[-1].set_xlabel("TTLB forjado para CDN-1 (ms)")
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return True


def trace_series(run, grid):
    """Use run means as the independent units, with QoE accumulated from 0 s."""
    summary_path = Path(run["summary_path"])
    summary = json.loads(summary_path.read_text())
    traces = json.loads((summary_path.parent / "viewer-traces.json").read_text())
    viewers = {viewer["client"]: viewer for viewer in summary["viewers"]}
    cap = run["configuration"]["max_video_kbps"]
    rows = []
    for second in grid:
        bitrates, qoes, reserves = [], [], []
        for client in range(4, 11):
            viewer = viewers[client]
            trace = traces[str(client)]
            start = viewer["qoe_full"]["window_start_ms"]
            end = min(start + second * 1000,
                      viewer["qoe_full"]["window_end_ms"])
            if second > 0:
                try:
                    qoe = summarize_qoe(trace, start, end, cap)
                except ValueError:
                    qoe = {}
                index = qoe.get("qoe_index")
                if index is not None:
                    qoes.append(index)
            ticks = [tick for tick in trace["ticks"] if tick["ms"] <= end]
            if ticks and ticks[-1]["quality_kbps"] is not None:
                bitrates.append(ticks[-1]["quality_kbps"])
            if ticks and ticks[-1].get("buffered_ahead") is not None:
                reserves.append(ticks[-1]["buffered_ahead"])
        rows.append(dict(kind=run["kind"], ttlb_ms=run["ttlb_ms"],
                         run_id=run["run_id"], second=second,
                         bitrate_kbps=mean(bitrates) if bitrates else None,
                         qoe_index=mean(qoes) if len(qoes) == 7 else None,
                         buffer_reserve_seconds=(mean(reserves)
                                                 if len(reserves) == 7 else None)))
    return rows


def plot_time_series(runs, doses, output):
    grid = range(121)
    rows = [row for run in runs for row in trace_series(run, grid)]
    write_csv(output / "time-series-runs.csv", rows)
    fields = ["bitrate_kbps", "qoe_index", "buffer_reserve_seconds"]
    fig, axes = plt.subplots(len(fields), 1, figsize=(10, 3.5 * len(fields)), sharex=True,
                             constrained_layout=True)
    groups = [("Controle (6 runs)", "#2166ac", [r for r in runs
                                                if r["kind"] == "control"])]
    colors = plt.cm.tab10.colors
    attack_groups = [[r for r in runs if r["kind"] == "attack" and r["ttlb_ms"] == dose]
                     for dose in doses]
    groups += [(f"Ataque {dose} ms ({len(group)} runs)", colors[(i + 3) % len(colors)], group)
               for i, (dose, group) in enumerate(zip(doses, attack_groups))]
    for label, color, group in groups:
        ids = {run["run_id"] for run in group}
        curves = {field: [] for field in fields}
        for second in grid:
            at_second = [row for row in rows if row["run_id"] in ids
                         and row["second"] == second]
            for field in curves:
                values = [row[field] for row in at_second]
                curves[field].append(mean(values) if all(v is not None for v in values)
                                     else float("nan"))
        for ax, field in zip(axes, curves):
            ax.plot(list(grid), curves[field], label=label, color=color, linewidth=1.8)
    axes[0].set_ylabel("Bitrate exibido médio (kb/s)")
    axes[0].set_ylim(0, runs[0]["configuration"]["max_video_kbps"] * 1.05)
    axes[1].set_ylabel("Índice de QoE acumulado")
    axes[1].set_ylim(0, 1.02)
    axes[2].set_ylabel("Reserva de buffer (s)")
    axes[2].set_ylim(bottom=0)
    axes[-1].set_xlabel("Tempo desde o início da janela (s)")
    for ax in axes:
        ax.axvline(40, color="gray", linestyle=":", linewidth=1)
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=8)
    fig.suptitle("Clientes honestos 4–10 · médias por run; ataque inicia em 40 s")
    fig.savefig(output / "honest-clients-timeline.png", dpi=160)
    plt.close(fig)


def plot_client_progress(run, output):
    summary_path = Path(run["summary_path"])
    summary = json.loads(summary_path.read_text())
    traces = json.loads((summary_path.parent / "viewer-traces.json").read_text())
    fig, axes = plt.subplots(7, 1, figsize=(11, 12), sharex=True,
                             constrained_layout=True)
    for ax, viewer in zip(axes, summary["viewers"][3:]):
        client = viewer["client"]
        trace = traces[str(client)]
        start = viewer["qoe_full"]["window_start_ms"]
        end = viewer["qoe_full"]["window_end_ms"]
        ticks = [tick for tick in trace["ticks"] if start <= tick["ms"] <= end]
        position = ticks[0]["time"]
        advance = []
        for tick in ticks:
            advance.append(max(advance[-1] if advance else 0,
                               tick["time"] - position))
        ax.plot([(tick["ms"] - start) / 1000 for tick in ticks],
                advance, color="#2166ac",
                linewidth=1.3)
        recovery_events = [event for event in trace["events"]
                           if event["type"].startswith("recovery_")]
        recovery_intervals = []
        for attempt in recovery_events:
            if attempt["type"] != "recovery_attempt":
                continue
            stop = next((event["ms"] for event in recovery_events
                         if event["ms"] > attempt["ms"] and event["type"] in
                         ("recovery_success", "recovery_failure", "recovery_exhausted")),
                        end)
            recovery_intervals.append((attempt["ms"], stop))
        no_progress = []
        for before, after in zip(ticks, ticks[1:]):
            in_recovery = any(before["ms"] < stop and after["ms"] > begin
                              for begin, stop in recovery_intervals)
            if in_recovery or after["time"] - before["time"] < 0.05:
                if no_progress and before["ms"] - no_progress[-1][1] < 1:
                    no_progress[-1] = (no_progress[-1][0], after["ms"])
                else:
                    no_progress.append((before["ms"], after["ms"]))
        for begin, stop in no_progress:
            ax.axvspan((begin - start) / 1000, (stop - start) / 1000,
                       color="gray", alpha=0.25)
        waiting = None
        for event in trace["events"]:
            when = event["ms"]
            if when > end:
                break
            if event["type"] == "waiting" and waiting is None and not event["paused"]:
                waiting = when
            elif event["type"] in ("playing", "pause", "media_error", "ended"):
                if waiting is not None:
                    ax.axvspan(max(0, (waiting - start) / 1000),
                               (when - start) / 1000, color="#e69f00", alpha=0.35)
                    waiting = None
        if waiting is not None:
            ax.axvspan(max(0, (waiting - start) / 1000),
                       (end - start) / 1000, color="#e69f00", alpha=0.35)
        if viewer["qoe_full"]["terminal_failure"]:
            ax.plot((end - start) / 1000, advance[-1],
                    marker="x", color="#b2182b", markersize=8)
        ax.set_ylabel(f"C{client} (s)")
        ax.grid(alpha=0.15)
    axes[-1].set_xlim(0, 120)
    axes[-1].set_xlabel("Tempo desde o início da janela (s)")
    handles = [Line2D([], [], color="#2166ac"),
               Line2D([], [], color="gray", linewidth=7, alpha=0.25),
               Line2D([], [], color="#e69f00", linewidth=7, alpha=0.35),
               Line2D([], [], marker="x", color="#b2182b", linestyle="None")]
    fig.legend(handles, ["Avanço do vídeo", "Sem progresso", "Rebuffer",
                         "Falha terminal"], loc="upper center", ncol=4,
               bbox_to_anchor=(0.5, 0.975), fontsize=8)
    fig.suptitle(f"{run['run_id']} · {run['kind']} · TTLB={run['ttlb_ms']} ms",
                 fontsize=10)
    fig.savefig(output / f"{run['run_id']}.png", dpi=140)
    plt.close(fig)


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
    found = [read_run(path) for path in sorted(args.root.glob("*/multi-*/summary.json"))]
    runs = [run for run in found if run is not None]
    controls, attacks = validate(runs, doses)
    output = args.output or args.root / "plots"
    output.mkdir(parents=True, exist_ok=True)
    write_csv(
        output / "run-qoe.csv",
        [
            {key: value for key, value in run.items() if key != "configuration"}
            for run in runs
        ],
    )
    summary = []
    for dose in doses:
        group = [run for run in attacks if run["ttlb_ms"] == dose]
        row = {"ttlb_ms": dose, "control_runs": 6, "attack_runs": len(group)}
        for field, _, _ in METRICS:
            control_values = [run[field] for run in controls]
            attack_values = [run[field] for run in group]
            if any(value is None for value in control_values + attack_values):
                row.update(
                    {
                        f"control_{field}": None,
                        f"attack_{field}": None,
                        f"delta_{field}": None,
                    }
                )
            else:
                c, a = mean(control_values), mean(attack_values)
                row.update(
                    {
                        f"control_{field}": c,
                        f"attack_{field}": a,
                        f"delta_{field}": a - c,
                    }
                )
        summary.append(row)
    write_csv(output / "dose-summary.csv", summary)
    for field, label, filename in METRICS:
        if not plot_metric(
            controls,
            attacks,
            doses,
            field,
            label,
            output / filename,
            primary=field == "qoe_index",
        ):
            print(f"Skipped {filename}: metric unavailable in controls")
    if all("qoe_full" in viewer for run in runs
           for viewer in json.loads(Path(run["summary_path"]).read_text())["viewers"][3:]):
        plot_time_series(runs, doses, output)
        progress_dir = output / "client-progress"
        progress_dir.mkdir(exist_ok=True)
        for run in runs:
            plot_client_progress(run, progress_dir)
    print(f"Wrote {len(controls)} controls and {len(attacks)} attacks to {output}")


if __name__ == "__main__":
    main()
