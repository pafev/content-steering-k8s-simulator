import csv
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plot_qoe_dose_response


def write_run(root, number, ttlb, qoe):
    path = root / f"batch-{number}" / f"multi-{number}"
    path.mkdir(parents=True)
    cfg = dict(strategy="ucb1", clients=10, reward_lambda=10, seconds=120,
               measurement_start=40, fault_sha256="same-fault", mpd="same-mpd",
               replicate=1, allow_viewer_failure=True, require_fresh_cache=True,
               max_video_kbps=3000, bounded_start=True, buffer_trace_version=5,
               malicious_count=3 if ttlb else 0, malicious_cdn="cdn-1",
               attack_ttlb=ttlb, attack_delay=40 if ttlb else 0,
               attack_from_start=False)
    viewers = [dict(client=client, rebuffer_seconds=1 if ttlb else 0,
                    qoe=dict(qoe_index=qoe, no_progress_seconds=2 if ttlb else 0,
                             rendered_quality_kbps=750 if ttlb else 1500,
                             buffer_reserve_mean_seconds=18,
                             low_buffer_seconds=0,
                             terminal_failure=False))
               for client in range(1, 11)]
    (path / "summary.json").write_text(json.dumps(dict(
        run_id=f"run-{number}", success=True, configuration=cfg, viewers=viewers)))
    (path / "cache-validation.json").write_text(json.dumps(
        dict(cached_non_hit_responses=[])))


def test_all_doses_share_six_controls_and_four_attacks(tmp_path, monkeypatch):
    doses = [1200, 3500, 5000]
    (tmp_path / "doses.txt").write_text("\n".join(map(str, doses)) + "\n")
    for number in range(6):
        write_run(tmp_path, number, 0, 1)
    for index, dose in enumerate(doses):
        for replica in range(4):
            write_run(tmp_path, 6 + 4 * index + replica, dose, .8 - .1 * index)
    monkeypatch.setattr(sys, "argv", ["plot_qoe_dose_response.py", str(tmp_path)])
    plot_qoe_dose_response.main()
    output = tmp_path / "plots"
    assert all((output / filename).exists() for _, _, filename in
               plot_qoe_dose_response.METRICS)
    rows = list(csv.DictReader((output / "dose-summary.csv").open()))
    assert len(rows) == 3
    assert [float(row["delta_qoe_index"]) for row in rows] == pytest.approx(
        [-.2, -.3, -.4])
    assert len(list(csv.DictReader((output / "run-qoe.csv").open()))) == 18


def test_undefined_qoe_keeps_run_and_components(tmp_path):
    write_run(tmp_path, 1, 20000, None)
    run = plot_qoe_dose_response.read_run(
        tmp_path / "batch-1" / "multi-1" / "summary.json")
    assert run["qoe_index"] is None
    assert run["no_progress_seconds"] == 2
    assert run["terminal_failures"] == 0


@pytest.mark.parametrize("attack_runs", [2, 4])
def test_single_calibrated_dose_has_six_controls(tmp_path, monkeypatch, attack_runs):
    (tmp_path / "doses.txt").write_text("20000\n")
    for number in range(6):
        write_run(tmp_path, number, 0, 1)
    for number in range(6, 6 + attack_runs):
        write_run(tmp_path, number, 20000, .8 if number % 2 == 0 else .7)
    monkeypatch.setattr(sys, "argv", ["plot_qoe_dose_response.py", str(tmp_path)])
    plot_qoe_dose_response.main()
    rows = list(csv.DictReader((tmp_path / "plots" / "dose-summary.csv").open()))
    assert len(rows) == 1
    assert rows[0]["control_runs"] == "6"
    assert rows[0]["attack_runs"] == str(attack_runs)


def test_time_series_uses_official_qoe(tmp_path):
    path = tmp_path / "multi-1"
    path.mkdir()
    tick = lambda ms, seconds: dict(ms=ms, time=seconds, quality_kbps=1500,
                                    paused=False, ended=False, buffered_ahead=18)
    traces = {str(client): dict(ticks=[tick(0, 0), tick(1000, 1),
                                             tick(2000, 2)], events=[])
              for client in range(4, 11)}
    viewers = [dict(client=client, qoe_full=dict(window_start_ms=0,
                                                window_end_ms=2000))
               for client in range(4, 11)]
    (path / "summary.json").write_text(json.dumps(dict(viewers=viewers)))
    (path / "viewer-traces.json").write_text(json.dumps(traces))
    run = dict(summary_path=str(path / "summary.json"), kind="control",
               ttlb_ms=0, run_id="r1", configuration=dict(max_video_kbps=3000))
    rows = plot_qoe_dose_response.trace_series(run, range(3))
    assert rows[-1]["bitrate_kbps"] == 1500
    assert rows[-1]["qoe_index"] == pytest.approx(0.5)


def test_legacy_run_cannot_be_plotted_as_official_qoe(tmp_path):
    (tmp_path / "doses.txt").write_text("20000\n")
    for number in range(6):
        write_run(tmp_path, number, 0, 1)
    for number in range(6, 10):
        write_run(tmp_path, number, 20000, .8)
    first = tmp_path / "batch-0" / "multi-0" / "summary.json"
    summary = json.loads(first.read_text())
    del summary["configuration"]["buffer_trace_version"]
    first.write_text(json.dumps(summary))
    runs = [plot_qoe_dose_response.read_run(path) for path in
            tmp_path.glob("*/multi-*/summary.json")]
    with pytest.raises(ValueError):
        plot_qoe_dose_response.validate(runs, [20000])
