import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from plot_tcc_series import full_series, reconstruct_buffer_qoe


def test_full_window_qoe_is_cumulative_without_double_counting():
    ticks = [dict(ms=ms, time=ms / 1000, quality_kbps=3000,
                  buffered_ahead=18, paused=False, ended=False)
             for ms in (0, 1000, 2000)]
    run = dict(summary=dict(configuration=dict(seconds=120, max_video_kbps=3000,
                                               buffer_trace_version=5), viewers=[dict(client=1, qoe_full=dict(
        window_start_ms=0, window_end_ms=2000))]),
        traces={"1": dict(ticks=ticks, events=[])})
    _, bitrate, qoe = full_series(run, 1)
    assert bitrate[1] == 3000
    assert qoe[1:3] == pytest.approx([1, 1])
    assert max(qoe[1:]) <= 1


def test_reconstructs_official_qoe_from_saved_buffer_reports():
    ticks = [dict(ms=ms, time=ms / 1000, quality_kbps=3000,
                  paused=False, ended=False) for ms in (0, 1000, 2000)]
    viewer = dict(client=1, buffer_at_run_start_seconds=18,
                  buffer_at_attack_seconds=18,
                  qoe=dict(window_start_ms=1000, window_end_ms=2000,
                           qoe_index=1),
                  qoe_full=dict(window_start_ms=0, window_end_ms=2000,
                                qoe_index=1))
    events = [dict(kind="media", client=1, elapsed=when,
                   url=f"https://cdn-1/seg-1.m4s?CMCD=bl%3D%2818000%3B{track}%29")
              for track in ("a", "v") for when in (0, 2)]
    run = dict(path="saved-run", summary=dict(
        configuration=dict(malicious_count=0, seconds=2, max_video_kbps=3000),
        run_start_elapsed=0, viewer_outcomes=dict(media_errors=0),
        viewers=[viewer]), events=events,
        traces={"1": dict(ticks=ticks, events=[])})
    reconstruct_buffer_qoe(run)
    assert run["qoe_source"] == "cmcd_reconstruction"
    assert viewer["qoe_full"]["qoe_index"] == pytest.approx(143 / 144)
