import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plot_qoe_timeline


def make_run(root, name, attack):
    path = root / name
    path.mkdir()
    config = dict(clients=10, reward_lambda=10, fault_sha256="same-fault",
                  mpd="same-video", seconds=120, measurement_start=40,
                  allow_viewer_failure=True, malicious_count=6 if attack else 0,
                  max_video_kbps=3000,
                  attack_ttlb=12000 if attack else None,
                  attack_delay=40 if attack else 0, attack_from_start=False)
    viewers = []
    traces = {}
    for client in range(1, 11):
        qoe = dict(window_start_ms=40000, window_end_ms=120000,
                   window_seconds=80, no_progress_fraction=.0625 if attack else 0,
                   terminal_failure=False,
                   rendered_quality_kbps=500 if attack else 1500,
                   qoe_index=.31 if attack else 1)
        viewers.append(dict(client=client, rebuffer_seconds=5 if attack else 0,
                            qoe=qoe))
        ticks = ([dict(ms=40000, time=40, quality_kbps=500, paused=False),
                  dict(ms=60000, time=60, quality_kbps=500, paused=False),
                  dict(ms=65000, time=60, quality_kbps=500, paused=False),
                  dict(ms=120000, time=115, quality_kbps=500, paused=False)]
                 if attack else
                 [dict(ms=40000, time=40, quality_kbps=1500, paused=False),
                  dict(ms=120000, time=120, quality_kbps=1500, paused=False)])
        events = ([dict(ms=60000, type="waiting", paused=False),
                   dict(ms=65000, type="playing", paused=False)]
                  if attack else [])
        traces[str(client)] = dict(ticks=ticks, events=events)
    (path / "summary.json").write_text(json.dumps(dict(
        run_id=name, success=True, configuration=config, viewers=viewers)))
    (path / "viewer-traces.json").write_text(json.dumps(traces))
    return path


def test_twelve_runs_are_aggregated_without_treating_clients_as_replicates(
        tmp_path, monkeypatch):
    controls = [make_run(tmp_path, f"control-{i}", False) for i in range(6)]
    attacks = [make_run(tmp_path, f"attack-{i}", True) for i in range(6)]
    output = tmp_path / "timeline.png"
    monkeypatch.setattr(sys, "argv", ["plot_qoe_timeline.py", "--controls",
                                      *map(str, controls), "--attacks",
                                      *map(str, attacks), "--output", str(output)])
    plot_qoe_timeline.main()
    assert output.exists()
    rows = list(csv.DictReader(output.with_suffix(".csv").open()))
    assert len(rows) == 12
    assert [float(row["mean_rebuffer_seconds"]) for row in rows[:6]] == [0] * 6
    assert [float(row["mean_rebuffer_seconds"]) for row in rows[6:]] == [5] * 6
