"""Windowed playback outcomes from a research-runner event/tick trace."""


def summarize(trace, start_ms, end_ms, max_kbps=1500):
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
    for before, after in zip(ticks, ticks[1:]):
        elapsed = after["ms"] - before["ms"]
        if elapsed <= 0:
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

    events = [event for event in trace["events"] if event["ms"] <= end_ms]
    failures = [event for event in events if event["type"] == "media_error"
                or (event["type"] == "dash_error" and
                    (str(event.get("code")) in ("3", "4") or
                     "MEDIA_ERR_" in str(event.get("message"))))]
    last_failure = failures[-1] if failures else None
    recovered = last_failure is not None and any(
        before["ms"] >= last_failure["ms"] and
        after["time"] > before["time"] + 0.05
        for before, after in zip(all_ticks, all_ticks[1:])
        if after["ms"] <= end_ms
    )
    mean_kbps = quality_weight / quality_covered_ms if quality_covered_ms else None
    coverage = quality_covered_ms / progress_ms if progress_ms else 0.0
    availability = progress_ms / window_ms
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
        "terminal_failure": bool(last_failure and not recovered),
        "terminal_error": last_failure if last_failure and not recovered else None,
        "rendered_quality_kbps": mean_kbps,
        "quality_coverage_fraction": coverage,
        # Operational index: fraction of wall time with progress, weighted by
        # the displayed video bitrate relative to the configured 1500 kb/s cap.
        # Missing quality is not silently counted as zero bitrate.
        "qoe_index": 0.0 if progress_ms == 0 else
        availability * mean_kbps / max_kbps
        if mean_kbps is not None and coverage >= 0.95 else None,
    }
