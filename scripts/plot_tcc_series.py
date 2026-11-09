"""Analyze TCC final series: 0–120 s plots, 40–120 s steering and unit cost."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from plot_risk_matrix import PRICES_USD_PER_GB, steering_probability, unit_cost


def mean_series(values):
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values)
    return np.divide(np.where(valid, values, 0).sum(axis=0), valid.sum(axis=0),
                     out=np.full(values.shape[1], np.nan), where=valid.sum(axis=0) > 0)


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def load_run(path):
    summary = json.loads(path.read_text())
    if not summary.get("success"):
        return None
    cache = json.loads((path.parent / "cache-validation.json").read_text())
    if cache.get("cached_non_hit_responses"):
        return None
    events = [json.loads(line) for line in (path.parent / "events.jsonl").read_text().splitlines()]
    traces = json.loads((path.parent / "viewer-traces.json").read_text())
    return dict(path=str(path), summary=summary, events=events, traces=traces)


def validate(runs, plan):
    expected = {(int(m), int(t)): 2 for m, t in plan["cells"]}
    counts = Counter((r["summary"]["configuration"]["malicious_count"],
                      r["summary"]["configuration"].get("attack_ttlb") or 0) for r in runs)
    if counts != Counter({(0, 0): 6, **expected}):
        raise ValueError(f"Incomplete/unexpected series: {counts}")
    if len({r["summary"]["run_id"] for r in runs}) != len(runs):
        raise ValueError("Duplicate run IDs")
    for run in runs:
        s = run["summary"]; c = s["configuration"]
        if any(c.get(key) != plan[key] for key in
               ("clients", "seconds", "measurement_start", "reward_lambda",
                "max_video_kbps", "fault_sha256")):
            raise ValueError(f"Unmatched conditions: {run['path']}")
        if (c["strategy"] != "ucb1" or not c["allow_viewer_failure"]
            or not c["require_fresh_cache"]):
            raise ValueError(f"Unmatched runner flags: {run['path']}")
        if "run_start_elapsed" not in s or not all("qoe_full" in v for v in s["viewers"]):
            raise ValueError(f"Missing full-window instrumentation: {run['path']}")


def full_series(run, first_honest):
    """Per-run mean of per-client curves; one run remains one replicate."""
    duration = int(run["summary"]["configuration"]["seconds"])
    grid = np.arange(0, duration + 1, 1)
    quality, qoe = [], []
    for viewer in run["summary"]["viewers"]:
        client = viewer["client"]
        if client < first_honest:
            continue
        ticks = run["traces"][str(client)]["ticks"]
        start = viewer["qoe_full"]["window_start_ms"]
        end = viewer["qoe_full"]["window_end_ms"]
        ticks = [t for t in ticks if start <= t["ms"] <= end]
        if len(ticks) < 2:
            raise ValueError(f"Incomplete trace: {run['path']} client {client}")
        qsum = np.zeros(len(grid)); progress = np.zeros(len(grid)); covered = np.zeros(len(grid))
        for before, after in zip(ticks, ticks[1:]):
            left, right = (before["ms"] - start) / 1000, (after["ms"] - start) / 1000
            elapsed = right - left
            if elapsed <= 0 or after["time"] - before["time"] < 0.05:
                continue
            kbps = after["quality_kbps"]
            for i, t in enumerate(grid[1:], 1):
                overlap = max(0, min(t, right) - max(0, left))
                progress[i] += overlap
                if kbps is not None:
                    covered[i] += overlap
                    qsum[i] += overlap * kbps
        tick_times = np.array([(t["ms"] - start) / 1000 for t in ticks])
        positions = np.clip(np.searchsorted(tick_times, grid, side="right") - 1, 0, len(ticks) - 1)
        bitrate = np.array([float(ticks[i]["quality_kbps"]) if ticks[i]["quality_kbps"] is not None
                            else np.nan for i in positions])
        index = np.divide(qsum, 3000 * np.maximum(grid, 1), out=np.full(len(grid), np.nan), where=covered >= .95 * progress)
        index[0] = np.nan
        quality.append(bitrate); qoe.append(index)
    return grid, mean_series(quality), mean_series(qoe)


def priority_series(run, first_honest):
    start = run["summary"]["run_start_elapsed"]
    duration = int(run["summary"]["configuration"]["seconds"])
    values = []
    for client in range(first_honest, 11):
        bins = [[] for _ in range((duration + 9) // 10)]
        for event in run["events"]:
            t = event["elapsed"] - start
            if event["kind"] == "steering" and event.get("status") == 200 and event["client"] == client and 0 <= t < duration:
                priority = event.get("response", {}).get("PATHWAY-PRIORITY", [])
                if priority:
                    bins[int(t // 10)].append(priority[0] == "cdn-1")
        values.append([np.mean(group) if group else np.nan for group in bins])
    return np.arange(5, duration, 10), mean_series(values)


def plot_combined(controls, groups, count, field, output):
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    items = [("Controle", controls, "#2166ac")]
    colors = plt.cm.plasma(np.linspace(.12, .85, len(groups)))
    items += [(f"TTLB {dose} ms", runs, color) for (dose, runs), color in zip(groups, colors)]
    for label, runs, color in items:
        curves = []
        for run in runs:
            if field == "priority":
                x, y = priority_series(run, count + 1)
            else:
                x, bitrate, qoe = full_series(run, count + 1)
                y = bitrate if field == "bitrate" else qoe
            curves.append(y)
            ax.plot(x, y, color=color, alpha=.18, linewidth=.7)
        ax.plot(x, mean_series(curves), color=color, linewidth=1.8, label=label)
    duration = controls[0]["summary"]["configuration"]["seconds"]
    attack_start = groups[0][1][0]["summary"]["configuration"]["attack_delay"]
    ax.axvline(attack_start, color="gray", linestyle="--", linewidth=.8)
    ax.set(xlim=(0, duration), xlabel="Tempo desde início do run (s)",
           ylabel={"priority": "Fração CDN-1 em primeira prioridade",
                   "bitrate": "Bitrate exibido médio (kb/s)",
                   "qoe": "Índice QoE acumulado"}[field])
    if field != "bitrate": ax.set_ylim(0, 1)
    ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.savefig(output, dpi=150); plt.close(fig)


def video_advance(run, first_honest, output):
    duration = run["summary"]["configuration"]["seconds"]
    boundary = run["summary"]["configuration"]["measurement_start"]
    viewers = [v for v in run["summary"]["viewers"] if v["client"] >= first_honest]
    fig, axes = plt.subplots(len(viewers), 1, figsize=(9, 2 * len(viewers)), sharex=True, constrained_layout=True)
    if len(viewers) == 1: axes = [axes]
    rows = []
    for ax, viewer in zip(axes, viewers):
        client = viewer["client"]; trace = run["traces"][str(client)]
        decoder_error = any(e["type"] == "media_error" and
                            "DECODE" in str(e.get("message", "")) for e in trace["events"])
        start = viewer["qoe_full"]["window_start_ms"]
        ticks = [t for t in trace["ticks"] if t["ms"] >= start]
        ax.plot([(t["ms"] - start) / 1000 for t in ticks], [t["time"] for t in ticks], linewidth=1.2)
        q = viewer["qoe_full"]
        label = (f"C{client}: sem avanço {q['no_progress_seconds']:.1f}s, "
                 f"rebuffer {viewer['rebuffer_seconds_full']:.1f}s, "
                 f"falha terminal {'sim' if q['terminal_failure'] else 'não'}, "
                 f"erro de decode {'sim' if decoder_error else 'não'}")
        ax.set_ylabel(label, fontsize=8); ax.grid(alpha=.2); ax.axvline(boundary, color="gray", linestyle="--", linewidth=.7)
        rows.append(dict(run_id=run["summary"]["run_id"], client=client,
                         no_progress_seconds=q["no_progress_seconds"],
                         rebuffer_seconds=viewer["rebuffer_seconds_full"],
                         terminal_failure=q["terminal_failure"], decoder_error=decoder_error,
                         qoe_index=q["qoe_index"]))
    axes[-1].set(xlim=(0, duration), xlabel="Tempo desde início do run (s) / avanço do vídeo (s)")
    fig.savefig(output, dpi=130); plt.close(fig)
    return rows


def effective_shares(run, first_honest):
    start = run["summary"]["observation_start"]
    end = run["summary"]["observation_end"]
    counts = Counter()
    for e in run["events"]:
        if e["kind"] != "media" or e.get("status") != 200 or e["client"] < first_honest or not start <= e["elapsed"] < end:
            continue
        url = urlsplit(e["url"]); cmcd = parse_qs(url.query).get("CMCD", [""])[0]
        if "ot=v" in cmcd and "/seg-" in url.path:
            counts[url.hostname.split(".")[0]] += 1
    total = sum(counts.values())
    return {cdn: counts[cdn] / total if total else None for cdn in PRICES_USD_PER_GB}


def honest_qoe(run, first_honest):
    values = [v["qoe_full"]["qoe_index"] for v in run["summary"]["viewers"]
              if v["client"] >= first_honest]
    return float(np.mean(values)) if all(v is not None for v in values) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    plan = json.loads((args.root / "plan.json").read_text())
    runs = [r for path in args.root.glob("*/multi-*/summary.json") if (r := load_run(path))]
    validate(runs, plan)
    output = args.root / "plots"; output.mkdir(exist_ok=True)
    controls = [r for r in runs if r["summary"]["configuration"]["malicious_count"] == 0]
    summary_rows, run_rows, client_rows = [], [], []
    for m, dose in plan["cells"]:
        attacks = [r for r in runs if (r["summary"]["configuration"]["malicious_count"],
                                        r["summary"]["configuration"].get("attack_ttlb")) == (m, dose)]
        c_steer = np.mean([steering_probability(r, range(m + 1, 11)) for r in controls])
        c_cost = np.mean([unit_cost(r) for r in controls])
        control_qoe = [honest_qoe(r, m + 1) for r in controls]
        c_qoe = float(np.mean(control_qoe)) if all(v is not None for v in control_qoe) else None
        for r in attacks:
            s = r["summary"]
            paths = effective_shares(r, m + 1)
            a_qoe = honest_qoe(r, m + 1)
            honest = [v for v in s["viewers"] if v["client"] >= m + 1]
            decoder_errors = sum(any(e["type"] == "media_error" and
                "DECODE" in str(e.get("message", ""))
                for e in r["traces"][str(v["client"])]["events"]) for v in honest)
            a_steer = steering_probability(r, range(m + 1, 11))
            a_cost = unit_cost(r)
            row = dict(run_id=s["run_id"], m=m, ttlb_ms=dose,
                       control_cdn1_priority_40_120=1 - c_steer,
                       attack_cdn1_priority_40_120=1 - a_steer,
                       d_steer=a_steer - c_steer,
                       control_cost_usd_per_gb_40_120=c_cost,
                       attack_cost_usd_per_gb_40_120=a_cost,
                       delta_c_usd_per_gb=a_cost - c_cost,
                       control_qoe_0_120=c_qoe,
                       attack_qoe_0_120=a_qoe,
                       delta_qoe=a_qoe - c_qoe if a_qoe is not None and c_qoe is not None else None,
                       undefined_qoe_clients=sum(v["qoe_full"]["qoe_index"] is None for v in honest),
                       mean_no_progress_seconds_0_120=np.mean([v["qoe_full"]["no_progress_seconds"] for v in honest]),
                       terminal_failures=sum(v["qoe_full"]["terminal_failure"] for v in honest),
                       decoder_error_clients=decoder_errors,
                       cdn1_effective_share=paths["cdn-1"],
                       cdn2_effective_share=paths["cdn-2"],
                       cdn3_effective_share=paths["cdn-3"],
                       cdn1_bytes_40_120=s["cdn_bytes_window"]["cdn-1"],
                       cdn2_bytes_40_120=s["cdn_bytes_window"]["cdn-2"],
                       cdn3_bytes_40_120=s["cdn_bytes_window"]["cdn-3"],
                       falsified_share=s["malicious"]["accepted_falsified"] /
                           int(s["final"]["state"]["model"]["cdn-1"]["n"]))
            run_rows.append(row)
        group = run_rows[-2:]
        deltas = [r["delta_qoe"] for r in group]
        summary_rows.append(dict(m=m, ttlb_ms=dose,
                                 d_steer=np.mean([r["d_steer"] for r in group]),
                                 delta_c_usd_per_gb=np.mean([r["delta_c_usd_per_gb"] for r in group]),
                                 delta_qoe=float(np.mean(deltas)) if all(v is not None for v in deltas) else None,
                                 cdn1_effective_share=np.mean([r["cdn1_effective_share"] for r in group])))
    advance = output / "advance"; advance.mkdir(exist_ok=True)
    for r in runs:
        c = r["summary"]["configuration"]
        if c["malicious_count"] in (0, 3):
            first_honest = c["malicious_count"] + 1
            client_rows += video_advance(r, first_honest,
                advance / f"{r['summary']['run_id']}.png")
    write_csv(output / "run-effects.csv", run_rows)
    write_csv(output / "cell-effects.csv", summary_rows)
    write_csv(output / "honest-clients.csv", client_rows)
    for m in sorted({m for m, _ in plan["cells"]}):
        doses = [dose for count, dose in plan["cells"] if count == m]
        groups = [(dose, [r for r in runs if
                   (r["summary"]["configuration"]["malicious_count"],
                    r["summary"]["configuration"].get("attack_ttlb")) == (m, dose)])
                  for dose in doses]
        for field in (("priority", "bitrate", "qoe") if m == 3 else ("priority",)):
            plot_combined(controls, groups, m, field, output / f"M{m}-{field}-timeline.png")
    for field, label, filename, scale in (
            ("d_steer", "D_steer (pontos percentuais)", "D_steer.png", 100),
            ("delta_c_usd_per_gb", "Δ custo (USD/GB)", "Delta_c.png", 1),
            ("delta_qoe", "Δ QoE (ataque − controle)", "Delta_qoe.png", 1),
    ):
        fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
        for m in sorted({m for m, _ in plan["cells"]}):
            cells = [r for r in summary_rows if r["m"] == m]
            visible = [r for r in cells if r[field] is not None]
            ax.plot([r["ttlb_ms"] for r in visible], [r[field] * scale for r in visible], marker="o", label=f"M={m}")
            individual = [r for r in run_rows if r["m"] == m and r[field] is not None]
            ax.scatter([r["ttlb_ms"] for r in individual], [r[field] * scale for r in individual], s=12, alpha=.5)
        ax.axhline(0, color="gray", linewidth=.8)
        ax.set(xscale="log", xlabel="TTLB falso (ms)", ylabel=label)
        doses = sorted({dose for _, dose in plan["cells"]})
        ax.set_xticks(doses, [str(dose) for dose in doses])
        ax.grid(alpha=.2); ax.legend()
        fig.savefig(output / filename, dpi=150); plt.close(fig)
    print(f"Wrote {len(summary_rows)} cells to {output}")


if __name__ == "__main__":
    main()
