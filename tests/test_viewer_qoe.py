import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from viewer_qoe import summarize


def tick(ms, time, quality=1500, paused=False):
    return dict(ms=ms, time=time, quality_kbps=quality,
                paused=paused, ended=False, buffered_ahead=18)


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


def test_recovery_seek_does_not_count_as_media_progress():
    trace = {"ticks": [tick(0, 10), tick(1000, 11), tick(2000, 0),
                       tick(3000, 11), tick(4000, 12)],
             "events": [{"ms": 1200, "type": "media_error", "code": 3},
                        {"ms": 1200, "type": "recovery_attempt", "resume_at": 11},
                        {"ms": 3500, "type": "recovery_success", "resumed_at": 11.5}]}
    result = summarize(trace, 0, 4000)
    assert result["no_progress_seconds"] == 3
    assert result["media_progress_seconds"] == 1
    assert result["recovery_attempts"] == 1
    assert result["recovery_successes"] == 1
    assert not result["terminal_failure"]


def test_failed_recovery_is_terminal_even_if_old_trace_progressed():
    trace = {"ticks": [tick(0, 0), tick(1000, 1), tick(2000, 2)],
             "events": [{"ms": 1500, "type": "media_error", "code": 3},
                        {"ms": 1600, "type": "recovery_attempt"},
                        {"ms": 1900, "type": "recovery_failure"}]}
    result = summarize(trace, 0, 2000)
    assert result["terminal_failure"]
    assert result["recovery_failures"] == 1


def test_recovery_pending_at_window_end_is_terminal():
    trace = {"ticks": [tick(0, 0), tick(1000, 1), tick(2000, 1)],
             "events": [{"ms": 1500, "type": "recovery_attempt"},
                        {"ms": 1510, "type": "media_error", "code": 3}]}
    assert summarize(trace, 0, 2000)["terminal_failure"]


def test_low_buffer_reduces_new_index_while_playback_continues():
    trace = {"ticks": [dict(tick(0, 0), buffered_ahead=18),
                       dict(tick(1000, 1), buffered_ahead=1),
                       dict(tick(2000, 2), buffered_ahead=18)],
             "events": []}
    result = summarize(trace, 0, 2000, max_kbps=1500)
    assert result["no_progress_seconds"] == 0
    assert result["buffer_reserve_mean_seconds"] == 9.5
    assert result["low_buffer_seconds"] == 1
    assert result["qoe_index"] == 127 / 144


def test_one_second_stall_costs_more_than_one_second_without_reserve():
    stalled = {"ticks": [dict(tick(0, 0), buffered_ahead=18),
                         dict(tick(1000, 0), buffered_ahead=0),
                         dict(tick(2000, 1), buffered_ahead=18)], "events": []}
    low_reserve = {"ticks": [dict(tick(0, 0), buffered_ahead=18),
                             dict(tick(1000, 1), buffered_ahead=0),
                             dict(tick(2000, 2), buffered_ahead=18)], "events": []}
    stall_qoe = summarize(stalled, 0, 2000, max_kbps=1500)["qoe_index"]
    buffer_qoe = summarize(low_reserve, 0, 2000, max_kbps=1500)["qoe_index"]
    assert stall_qoe == 0.5
    assert buffer_qoe == 0.875


def test_old_trace_does_not_invent_buffer_capacity():
    trace = {"ticks": [dict(ms=ms, time=time, quality_kbps=1500,
                            paused=False, ended=False)
                       for ms, time in ((0, 0), (1000, 1))], "events": []}
    result = summarize(trace, 0, 1000)
    assert result["qoe_index"] is None
    assert result["buffer_reserve_mean_seconds"] is None
