"""Generate offline PNG, SVG and PDF figures from multi_client.py artifacts."""
import argparse
import html
import json
from pathlib import Path
from urllib.parse import urlsplit

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

PATHWAYS = ("cdn-1", "cdn-2", "cdn-3")
COLORS = {"cdn-1": "#0072B2", "cdn-2": "#D55E00", "cdn-3": "#009E73"}


def media_pathway(url):
    parsed = urlsplit(url)
    for pathway in PATHWAYS:
        if parsed.hostname == f"{pathway}.default.svc.cluster.local" or parsed.path.startswith(f"/cdn{pathway[-1]}/"):
            return pathway
    return None


def records(path):
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: invalid JSON; plot after the writer finishes") from error
    return sorted(result, key=lambda row: row["elapsed"])


def plot(directory, output, formats):
    samples = records(directory / "samples.jsonl")
    events = records(directory / "events.jsonl")
    if not samples:
        raise ValueError(f"No snapshots in {directory / 'samples.jsonl'}")
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    strategy = summary.get("strategy", "strategy unknown / partial run")
    times = [sample["elapsed"] for sample in samples]
    end = max(times + [event["elapsed"] for event in events])
    clients = sorted(set(range(1, max(len(s["clients"]) for s in samples) + 1)) |
                     {e["client"] for e in events})
    fig, axes = plt.subplots(3, 2, figsize=(15, 12), constrained_layout=True)
    reward_ax, count_ax, priority_ax, media_ax, playback_ax, cache_ax = axes.flat
    fig.suptitle(f"{strategy} — {directory.name}\nShared model and individual client behavior", fontsize=14)

    for pathway in PATHWAYS:
        models = [s["state"]["model"].get(pathway, {}) for s in samples]
        counts = [int(m.get("n", 0)) for m in models]
        means = [float(m.get("reward_sum", 0)) / n if n else float("nan")
                 for m, n in zip(models, counts)]
        reward_ax.plot(times, means, marker="o", color=COLORS[pathway], label=pathway)
        count_ax.step(times, counts, where="post", color=COLORS[pathway], label=pathway)
        count_ax.scatter(times, counts, s=16, color=COLORS[pathway])
    reward_ax.set(title="Shared mean CMCD delivery reward", ylabel="Mean reward", ylim=(-0.03, 1.03))
    count_ax.set(title="Shared accepted learning observations", ylabel="Cumulative count")
    reward_ax.legend()
    count_ax.legend()

    # Event markers represent observed responses, not an inferred continuous
    # routing state. Full priorities and decision IDs remain in events.jsonl.
    for pathway in PATHWAYS:
        steering = [e for e in events if e["kind"] == "steering" and e.get("status") == 200
                    and (e.get("response", {}).get("PATHWAY-PRIORITY") or [None])[0] == pathway]
        media = [e for e in events if e["kind"] == "media"
                 and media_pathway(e.get("url", "")) == pathway
                 and urlsplit(e["url"]).path.endswith(".m4s")]
        priority_ax.scatter([e["elapsed"] for e in steering], [e["client"] for e in steering],
                            c=COLORS[pathway], marker="s", s=50)
        media_ax.scatter([e["elapsed"] for e in media], [e["client"] for e in media],
                         c=COLORS[pathway], marker="|", s=65, alpha=0.65)
    handles = [Line2D([], [], color=COLORS[p], marker="s", linestyle="None", label=p) for p in PATHWAYS]
    for ax, title in ((priority_ax, "CSS first priority per steering response"),
                      (media_ax, "Actual .m4s responses (video, audio and init)")):
        ax.set(title=title, ylabel="Client", yticks=clients, ylim=(min(clients)-0.5, max(clients)+0.5))
        ax.legend(handles=handles, loc="upper right")
        if not events:
            ax.text(0.5, 0.5, "No captured events", ha="center", transform=ax.transAxes)

    for client in clients:
        available = [s for s in samples if len(s["clients"]) >= client]
        playback_ax.plot([s["elapsed"] for s in available],
                         [s["clients"][client-1]["time"] for s in available],
                         marker="o", label=f"Client {client}")
    playback_ax.set(title="Playback position (sampled)", ylabel="Video position (s)")
    playback_ax.legend()

    # These are browser-captured media responses. Uncorrelated warmup traffic
    # is deliberately excluded; no claim of total CDN traffic or QoE is made.
    cache_statuses = ("HIT", "MISS", "OTHER / missing")
    for index, pathway in enumerate(PATHWAYS):
        media = [e for e in events if e["kind"] == "media"
                 and media_pathway(e.get("url", "")) == pathway]
        bottom = 0
        for status, color in zip(cache_statuses, ("#009E73", "#E69F00", "#999999")):
            count = sum(e.get("cache") == status if status != "OTHER / missing"
                        else e.get("cache") not in ("HIT", "MISS") for e in media)
            cache_ax.bar(index, count, bottom=bottom, color=color,
                         label=status if index == 0 else None)
            bottom += count
    cache_ax.set(title="Cache status of captured client media responses",
                 ylabel="Responses (includes MPD)", xticks=range(3), xticklabels=PATHWAYS)
    cache_ax.legend()
    for ax in (reward_ax, count_ax, priority_ax, media_ax, playback_ax):
        ax.set_xlabel("Elapsed wall time since run start (s)")
        ax.set_xlim(0, max(end, 1))
        ax.grid(alpha=0.2)
    cache_ax.grid(axis="y", alpha=0.2)
    output.mkdir(parents=True, exist_ok=True)
    for extension in formats:
        fig.savefig(output / f"overview.{extension}", dpi=180)
    plt.close(fig)
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>{html.escape(directory.name)}</title>
<style>body{{font-family:system-ui;max-width:1500px;margin:24px auto;padding:16px}}img{{width:100%}}</style>
<h1>{html.escape(strategy)}: run overview</h1>
<p>{html.escape(directory.name)}</p><img src="overview.png" alt="Six charts of the shared model and client behavior">
<p>Rewards use successful segment duration and download time; reported failures score zero. Unobserved means are blank.
Model and playback curves are sampled; pathway markers are captured response events.
Time starts before the first client launches. Cache warmup is excluded.</p>
</html>"""
    (output / "index.html").write_text(page)
    print(f"Plots: {output / 'index.html'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="One run directory or its timestamp parent")
    parser.add_argument("--output", type=Path, help="Optional output root; default: <run>/plots")
    parser.add_argument("--formats", nargs="+", choices=("png", "svg", "pdf"), default=["png", "svg", "pdf"])
    args = parser.parse_args()
    runs = [args.input] if (args.input / "samples.jsonl").exists() else sorted(
        path.parent for path in args.input.glob("*/samples.jsonl"))
    if not runs:
        parser.error("No samples.jsonl found in the supplied run or its immediate children")
    for directory in runs:
        output = args.output / directory.name if args.output else directory / "plots"
        # HTML always has a PNG preview, even when only vector exports were requested.
        plot(directory, output, list(dict.fromkeys(["png", *args.formats])))


if __name__ == "__main__":
    main()
