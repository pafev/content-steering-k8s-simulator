"""Compare one QoE control/attack pilot; these are calibration, not final replicas."""

import argparse
import json
from pathlib import Path
from statistics import mean

from plot_risk_matrix import steering_probability, unit_cost
from plot_tcc_series import effective_shares, full_series, load_run


def describe(run):
    s = run["summary"]
    honest = [v for v in s["viewers"] if v["client"] >= 4]
    qoe = [v["qoe_full"]["qoe_index"] for v in honest]
    bitrate = [v["qoe_full"]["rendered_quality_kbps"] for v in honest]
    decoder_errors = [v["client"] for v in honest if any(
        e["type"] == "media_error" and "DECODE" in str(e.get("message", ""))
        for e in run["traces"][str(v["client"])]["events"])]
    c = s["configuration"]
    _, bitrate_series, qoe_series = full_series(run, 4)
    boundary = int(c["measurement_start"])
    return dict(run_id=s["run_id"], seconds=c["seconds"],
             analysis_start=c["measurement_start"], reward={k: v["mean_learning_reward"]
             for k, v in s["delivery_calibration"].items()},
             ttlb_median={k: v["median_ttlb_ms"] for k, v in s["delivery_calibration"].items()},
             cdn1_priority_analysis=1 - steering_probability(run, range(4, 11)),
             cdn1_effective_share_analysis=effective_shares(run, 4)["cdn-1"],
             unit_cost_usd_per_gb_analysis=unit_cost(run),
             mean_qoe_full=mean(qoe) if all(v is not None for v in qoe) else None,
             undefined_qoe_clients=[v["client"] for v in honest if v["qoe_full"]["qoe_index"] is None],
             decoder_error_clients=decoder_errors,
             mean_bitrate_full=mean(bitrate) if all(v is not None for v in bitrate) else None,
             mean_bitrate_before_attack=float(mean(bitrate_series[1:boundary])),
             mean_bitrate_after_attack=float(mean(bitrate_series[boundary:])),
             qoe_at_attack=float(qoe_series[boundary]), qoe_at_end=float(qoe_series[-1]),
             mean_no_progress_full=mean(v["qoe_full"]["no_progress_seconds"] for v in honest),
             mean_buffer_at_attack=mean(v["buffer_at_attack_seconds"] for v in honest)
             if all("buffer_at_attack_seconds" in v for v in honest) else None,
             terminal_failures=sum(v["qoe_full"]["terminal_failure"] for v in honest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("control", type=Path)
    parser.add_argument("attack", type=Path)
    args = parser.parse_args()
    control, attack = (load_run(p / "summary.json" if p.is_dir() else p)
                       for p in (args.control, args.attack))
    if control is None or attack is None:
        parser.error("Both pilots must be valid completed runs")
    c, a = control["summary"]["configuration"], attack["summary"]["configuration"]
    if (c["fault_sha256"] != a["fault_sha256"] or c["malicious_count"] != 0
        or a["malicious_count"] != 3 or c["seconds"] != a["seconds"]
        or c["measurement_start"] != a["measurement_start"]
        or a["attack_delay"] != c["measurement_start"]):
        parser.error("Expected matched manifest, one control and an M=3 attack")
    print(json.dumps({"control": describe(control), "attack": describe(attack)}, indent=2))


if __name__ == "__main__":
    main()
