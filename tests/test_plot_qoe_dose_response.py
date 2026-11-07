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
               max_video_kbps=3000,
               malicious_count=3 if ttlb else 0, malicious_cdn="cdn-1",
               attack_ttlb=ttlb, attack_delay=40 if ttlb else 0,
               attack_from_start=False)
    viewers = [dict(client=client, rebuffer_seconds=1 if ttlb else 0,
                    qoe=dict(qoe_index=qoe, no_progress_seconds=2 if ttlb else 0,
                             rendered_quality_kbps=750 if ttlb else 1500,
                             terminal_failure=False))
               for client in range(1, 11)]
    (path / "summary.json").write_text(json.dumps(dict(
        run_id=f"run-{number}", success=True, configuration=cfg, viewers=viewers)))
    (path / "cache-validation.json").write_text(json.dumps(
        dict(cached_non_hit_responses=[])))


def test_all_doses_share_six_controls_and_two_attacks(tmp_path, monkeypatch):
    doses = [1200, 3500, 5000]
    (tmp_path / "doses.txt").write_text("\n".join(map(str, doses)) + "\n")
    for number in range(6):
        write_run(tmp_path, number, 0, 1)
    for index, dose in enumerate(doses):
        write_run(tmp_path, 6 + 2 * index, dose, .8 - .1 * index)
        write_run(tmp_path, 7 + 2 * index, dose, .8 - .1 * index)
    monkeypatch.setattr(sys, "argv", ["plot_qoe_dose_response.py", str(tmp_path)])
    plot_qoe_dose_response.main()
    output = tmp_path / "plots"
    assert all((output / filename).exists() for _, _, filename in
               plot_qoe_dose_response.METRICS)
    rows = list(csv.DictReader((output / "dose-summary.csv").open()))
    assert len(rows) == 3
    assert [float(row["delta_qoe_index"]) for row in rows] == pytest.approx(
        [-.2, -.3, -.4])
    assert len(list(csv.DictReader((output / "run-qoe.csv").open()))) == 12
