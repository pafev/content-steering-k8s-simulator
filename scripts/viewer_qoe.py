"""Windowed playback outcomes from a research-runner event/tick trace."""

BUFFER_RESERVE_SECONDS = 18  # dash.js bufferTimeDefault for this player.
BUFFER_RESERVE_WEIGHT = 0.25  # A stall costs more than low reserve at equal duration.


def summarize(trace, start_ms, end_ms, max_kbps=3000):
    all_ticks = trace["ticks"]
    ticks = [tick for tick in all_ticks if start_ms <= tick["ms"] <= end_ms]
    if len(ticks) < 2 or end_ms <= start_ms:
        raise ValueError("Playback trace does not cover the measurement window")

    window_ms = end_ms - start_ms
    no_progress_ms = 0.0
    progress_ms = 0.0
    media_progress_ms = 0.0
    quality_weight = 0.0
    quality_covered_ms = 0.0
    buffer_weight = 0.0
    buffer_seconds_weight = 0.0
    buffer_covered_ms = 0.0
    low_buffer_ms = 0.0
    recovery_events = [event for event in trace["events"] if event["type"].startswith("recovery_")]
    attempts = [event for event in recovery_events if event["type"] == "recovery_attempt"]
    recovery_intervals = []
    for attempt in attempts:
        completion = next((event["ms"] for event in recovery_events
                           if event["ms"] > attempt["ms"] and event["type"] in
                           ("recovery_success", "recovery_failure", "recovery_exhausted")), end_ms)
        recovery_intervals.append((attempt["ms"], completion))
    for before, after in zip(ticks, ticks[1:]):
        elapsed = after["ms"] - before["ms"]
        if elapsed <= 0:
            continue
        if any(before["ms"] < stop and after["ms"] > start
               for start, stop in recovery_intervals):
            no_progress_ms += elapsed
            continue
        media_advance_ms = max(0.0, (after["time"] - before["time"]) * 1000)
        if media_advance_ms < 50:
            no_progress_ms += elapsed
            continue
        progress_ms += elapsed
        media_progress_ms += media_advance_ms
        quality = after["quality_kbps"]
        if quality is not None:
            quality_weight += elapsed * quality
            quality_covered_ms += elapsed
        reserve = after.get("buffered_ahead")
        if reserve is not None:
            reserve = max(0.0, reserve)
            buffer_weight += elapsed * min(reserve / BUFFER_RESERVE_SECONDS, 1)
            buffer_seconds_weight += elapsed * reserve
            buffer_covered_ms += elapsed
            if reserve < BUFFER_RESERVE_SECONDS:
                low_buffer_ms += elapsed

    events = [event for event in trace["events"] if event["ms"] <= end_ms]
    failures = [event for event in events if event["type"] == "media_error"
                or (event["type"] == "dash_error" and
                    (str(event.get("code")) in ("3", "4") or
                     "MEDIA_ERR_" in str(event.get("message"))))]
    last_failure = failures[-1] if failures else None
    recovery_events = [event for event in recovery_events if event["ms"] <= end_ms]
    recovery_terminal = any(event["type"] in ("recovery_failure", "recovery_exhausted")
                            for event in recovery_events)
    last_attempt = next((event for event in reversed(recovery_events)
                         if event["type"] == "recovery_attempt"), None)
    recovery_pending = bool(last_attempt and not any(
        event["ms"] > last_attempt["ms"] and event["type"] in
        ("recovery_success", "recovery_failure", "recovery_exhausted")
        for event in recovery_events))
    explicit_recovery = any(event["type"] == "recovery_success" and
                            (last_failure is None or event["ms"] >= last_failure["ms"])
                            for event in recovery_events)
    recovered = explicit_recovery or (last_failure is not None and any(
        before["ms"] >= last_failure["ms"] and
        after["ms"] >= end_ms - 2000 and
        after["time"] > before["time"] + 0.05
        for before, after in zip(all_ticks, all_ticks[1:])
        if after["ms"] <= end_ms
    ))
    mean_kbps = quality_weight / quality_covered_ms if quality_covered_ms else None
    coverage = quality_covered_ms / progress_ms if progress_ms else 0.0
    availability = progress_ms / window_ms
    buffer_coverage = buffer_covered_ms / progress_ms if progress_ms else 0.0
    buffer_factor = buffer_weight / buffer_covered_ms if buffer_covered_ms else None
    base_qoe = (0.0 if progress_ms == 0 else
                availability * mean_kbps / max_kbps
                if mean_kbps is not None and coverage >= 0.95 else None)
    return {
        "window_start_ms": start_ms,
        "window_end_ms": end_ms,
        "window_seconds": window_ms / 1000,
        "no_progress_seconds": no_progress_ms / 1000,
        "no_progress_fraction": no_progress_ms / window_ms,
        "media_progress_seconds": media_progress_ms / 1000,
        "paused_seconds": sum(
            after["ms"] - before["ms"] for before, after in zip(ticks, ticks[1:])
            if before["paused"] and not before["ended"]
        ) / 1000,
        "terminal_failure": bool(recovery_terminal or recovery_pending or
                                 (last_failure and not recovered)),
        "terminal_error": last_failure if recovery_terminal or recovery_pending or
                          (last_failure and not recovered) else None,
        "media_errors": sum(event["type"] == "media_error" for event in events),
        "recovery_attempts": sum(event["type"] == "recovery_attempt" for event in recovery_events),
        "recovery_successes": sum(event["type"] == "recovery_success" for event in recovery_events),
        "recovery_failures": sum(event["type"] in ("recovery_failure", "recovery_exhausted")
                                 for event in recovery_events),
        "rendered_quality_kbps": mean_kbps,
        "quality_coverage_fraction": coverage,
        "buffer_reserve_mean_seconds": (buffer_seconds_weight / buffer_covered_ms
                                        if buffer_covered_ms else None),
        "low_buffer_seconds": low_buffer_ms / 1000 if buffer_covered_ms else None,
        "buffer_coverage_fraction": buffer_coverage,
        "buffer_health_factor": buffer_factor,
        "qoe_index": (0.0 if progress_ms == 0 and all(
            "buffered_ahead" in tick for tick in ticks) else
            base_qoe * (1 - BUFFER_RESERVE_WEIGHT * (1 - buffer_factor))
            if base_qoe is not None
            and buffer_factor is not None and buffer_coverage >= 0.95 else None),
    }
