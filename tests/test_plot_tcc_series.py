import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from plot_tcc_series import full_series


def test_full_window_qoe_is_cumulative_without_double_counting():
    ticks = [dict(ms=ms, time=ms / 1000, quality_kbps=3000)
             for ms in (0, 1000, 2000)]
    run = dict(summary=dict(configuration=dict(seconds=120), viewers=[dict(client=1, qoe_full=dict(
        window_start_ms=0, window_end_ms=2000))]),
        traces={"1": dict(ticks=ticks)})
    _, bitrate, qoe = full_series(run, 1)
    assert bitrate[1] == 3000
    assert qoe[1:3] == pytest.approx([1, 1])
    assert max(qoe[1:]) <= 1
