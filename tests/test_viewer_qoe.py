import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from viewer_qoe import summarize


def tick(ms, time, quality=1500, paused=False):
    return dict(ms=ms, time=time, quality_kbps=quality,
                paused=paused, ended=False)


def test_pause_and_quality_reduce_distinct_outcomes():
    trace = {
        "ticks": [tick(0, 0), tick(1000, 1),
                  tick(2000, 1, paused=True), tick(3000, 1),
                  tick(4000, 2, quality=750)],
        "events": [{"ms": 1500, "type": "pause"}],
    }
    result = summarize(trace, 0, 4000, max_kbps=1500)
    assert result["no_progress_seconds"] == 2
    assert result["paused_seconds"] == 1
    assert result["rendered_quality_kbps"] == 1125
    assert result["qoe_index"] == 0.375
    assert not result["terminal_failure"]


def test_fatal_error_and_recovery_are_distinguished():
    trace = {
        "ticks": [tick(0, 0), tick(1000, 1), tick(2000, 0, paused=True),
                  tick(3000, 0, paused=True)],
        "events": [{"ms": 1500, "type": "media_error", "code": 4}],
    }
    assert summarize(trace, 0, 3000)["terminal_failure"]
    trace["ticks"].append(tick(4000, 1))
    assert not summarize(trace, 0, 4000)["terminal_failure"]


def test_brief_recovery_followed_by_final_freeze_is_terminal():
    trace = {
        "ticks": [tick(0, 0), tick(1000, 0), tick(2000, 1),
                  tick(3000, 1, paused=True), tick(4000, 1, paused=True),
                  tick(5000, 1, paused=True)],
        "events": [{"ms": 500, "type": "media_error", "code": 3}],
    }
    assert summarize(trace, 0, 5000)["terminal_failure"]


def test_missing_rendered_quality_is_reported_not_invented():
    trace = {"ticks": [tick(0, 0, None), tick(1000, 1, None)], "events": []}
    result = summarize(trace, 0, 1000)
    assert result["rendered_quality_kbps"] is None
    assert result["qoe_index"] is None


def test_complete_unavailability_has_zero_composite_index():
    trace = {"ticks": [tick(0, 0, None, True),
                       tick(1000, 0, None, True)], "events": []}
    result = summarize(trace, 0, 1000)
    assert result["rendered_quality_kbps"] is None
    assert result["qoe_index"] == 0


def test_qoe_uses_selected_abr_cap():
    trace = {"ticks": [tick(0, 0), tick(1000, 1)], "events": []}
    assert summarize(trace, 0, 1000, max_kbps=1500)["qoe_index"] == 1
    assert summarize(trace, 0, 1000, max_kbps=3000)["qoe_index"] == .5
    assert summarize(trace, 0, 1000)["qoe_index"] == .5
