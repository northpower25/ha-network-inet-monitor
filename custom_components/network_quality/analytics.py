"""Historical analytics helpers for Network Quality."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from statistics import mean
from typing import Any

METRICS = (
    "download",
    "upload",
    "ping",
    "jitter",
    "packet_loss",
    "availability",
    "contract_ratio",
    "score",
)

HIGHER_IS_BETTER_METRICS = {
    "download",
    "upload",
    "availability",
    "contract_ratio",
    "score",
}
LOWER_IS_BETTER_METRICS = {"ping", "jitter", "packet_loss"}
BASELINE_MINIMUM_SAMPLES = 3
BASELINE_FALLBACK_SAMPLES = 24
DRAMATIC_DROP_FACTOR = 0.75
DRAMATIC_RISE_FACTOR = 1.35
MIN_HISTORY_DAYS_FOR_REGULARITY = 7
REGULARITY_MIN_OCCURRENCES = 3
REGULARITY_LOOKBACK_DAYS = 90
OUTAGE_AVAILABILITY_THRESHOLD = 90.0
QUALITY_DROP_SCORE_DELTA = 15.0
QUALITY_DROP_SCORE_FACTOR = 0.8


StoredSample = dict[str, Any]


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp into UTC."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_stored_sample(entry: dict[str, Any]) -> StoredSample | None:
    """Normalize persisted sample data."""
    timestamp = parse_iso_datetime(entry.get("timestamp"))
    if timestamp is None:
        return None

    sample = entry.get("sample", {})
    services = entry.get("services", [])
    normalized_services: list[dict[str, Any]] = []
    for service in services:
        name = str(service.get("name", "")).strip()
        if not name:
            continue
        normalized_services.append(
            {
                "name": name,
                "reachable": bool(service.get("reachable", False)),
                "detail": str(service.get("detail", "")),
            }
        )

    normalized: StoredSample = {
        "timestamp": timestamp,
        "sample": {metric: _safe_float(sample.get(metric)) for metric in METRICS if metric in sample},
        "online": bool(entry.get("online", False)),
        "services": normalized_services,
        "quality_class": str(entry.get("quality_class", "E")),
        "active_test_events": _normalize_active_test_events(entry.get("active_test_events")),
        "tests": _normalize_tests(entry.get("tests")),
    }
    for metric in ("contract_ratio", "score"):
        if metric in entry:
            normalized[metric] = _safe_float(entry.get(metric))
    return normalized


def serialize_stored_sample(entry: StoredSample) -> dict[str, Any]:
    """Serialize a stored sample for persistence."""
    return {
        "timestamp": entry["timestamp"].astimezone(UTC).isoformat(),
        "sample": dict(entry.get("sample", {})),
        "online": bool(entry.get("online", False)),
        "services": [dict(service) for service in entry.get("services", [])],
        "contract_ratio": entry.get("contract_ratio"),
        "score": entry.get("score"),
        "quality_class": entry.get("quality_class", "E"),
        "active_test_events": list(entry.get("active_test_events", [])),
        "tests": dict(entry.get("tests", {})),
    }


def trim_history(history: list[StoredSample], *, keep_days: int) -> list[StoredSample]:
    """Trim history to the configured retention period."""
    if not history:
        return []
    latest = history[-1]["timestamp"]
    cutoff = latest - timedelta(days=keep_days)
    return [entry for entry in history if entry["timestamp"] >= cutoff]


def compute_analysis_overview(
    history: list[StoredSample],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a compact analytics summary for entity attributes and reports."""
    now = now or datetime.now(tz=UTC)
    if not history:
        return {
            "available": False,
            "periods": {},
            "recurring_patterns": [],
            "coverage": {"samples": 0},
        }

    latest = history[-1]
    periods: dict[str, Any] = {}
    for label, interval, days in (
        ("hour", "hour", 2),
        ("day", "day", 14),
        ("week", "week", 90),
        ("month", "month", 400),
    ):
        start = now - timedelta(days=days)
        payload = build_dashboard_payload(history, start=start, end=now, interval=interval)
        baseline = payload.get("baseline_current", {})
        periods[label] = {
            "baseline_score": baseline.get("score"),
            "baseline_download": baseline.get("download"),
            "baseline_upload": baseline.get("upload"),
            "baseline_ping": baseline.get("ping"),
            "outages": payload.get("summary", {}).get("outages", 0),
            "drastic_quality_drops": payload.get("summary", {}).get("drastic_quality_drops", 0),
        }

    baseline_current = periods["day"]
    current_score = latest.get("score", latest.get("sample", {}).get("score"))
    baseline_score = baseline_current.get("baseline_score")
    score_delta = None
    if baseline_score is not None and current_score is not None:
        score_delta = round(current_score - baseline_score, 2)

    recurring_patterns = build_dashboard_payload(
        history,
        start=max(history[0]["timestamp"], now - timedelta(days=REGULARITY_LOOKBACK_DAYS)),
        end=now,
        interval="day",
    ).get("summary", {}).get("recurring_patterns", [])

    return {
        "available": True,
        "baseline_score": baseline_score,
        "score_delta": score_delta,
        "anomaly_state": _anomaly_state(latest, {"score": baseline_score} if baseline_score is not None else {}),
        "periods": periods,
        "recurring_patterns": recurring_patterns,
        "coverage": {
            "samples": len(history),
            "first": history[0]["timestamp"].isoformat(),
            "last": history[-1]["timestamp"].isoformat(),
        },
    }


def build_dashboard_payload(
    history: list[StoredSample],
    *,
    start: datetime,
    end: datetime,
    interval: str,
) -> dict[str, Any]:
    """Aggregate historical data for the dashboard."""
    normalized_interval = interval.lower()
    if end < start:
        start, end = end, start

    relevant = [entry for entry in history if start <= entry["timestamp"] <= end]
    buckets = _build_buckets(relevant, normalized_interval, history)
    baseline_current = _baseline_for_timestamp(history, end, normalized_interval)
    services = _service_summary(relevant)
    summary = {
        "outages": sum(1 for bucket in buckets if bucket["anomaly"]["outage"]),
        "drastic_quality_drops": sum(1 for bucket in buckets if bucket["anomaly"]["drastic_drop"]),
        "test_event_windows": sum(1 for bucket in buckets if bucket.get("test_events")),
        "recurring_patterns": _regularity_patterns(history, normalized_interval, end),
        "samples": len(relevant),
    }
    current = _current_snapshot(relevant or history)
    return {
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "interval": normalized_interval,
        },
        "current": current,
        "baseline_current": baseline_current,
        "buckets": buckets,
        "summary": summary,
        "services": services,
        "coverage": {
            "samples": len(history),
            "range_samples": len(relevant),
            "first": history[0]["timestamp"].isoformat() if history else None,
            "last": history[-1]["timestamp"].isoformat() if history else None,
        },
    }


def _build_buckets(
    history: list[StoredSample],
    interval: str,
    baseline_source: list[StoredSample] | None = None,
) -> list[dict[str, Any]]:
    baseline_source = baseline_source or history
    grouped: dict[datetime, list[StoredSample]] = defaultdict(list)
    for entry in history:
        grouped[_floor_datetime(entry["timestamp"], interval)].append(entry)

    buckets: list[dict[str, Any]] = []
    for bucket_start in sorted(grouped):
        entries = grouped[bucket_start]
        metrics_entries = [entry for entry in entries if not _has_speedtest_event(entry)] or entries
        metrics = _mean_metrics(metrics_entries)
        bucket_end = _next_bucket(bucket_start, interval)
        baseline = _baseline_for_timestamp(baseline_source, bucket_start, interval)
        anomaly = _bucket_anomaly(metrics_entries, metrics, baseline)
        test_events = sorted(
            {
                str(event)
                for entry in entries
                for event in entry.get("active_test_events", [])
                if str(event).strip()
            }
        )
        buckets.append(
            {
                "start": bucket_start.isoformat(),
                "end": bucket_end.isoformat(),
                "label": _bucket_label(bucket_start, interval),
                "metrics": metrics,
                "baseline": baseline,
                "samples": len(entries),
                "online_ratio": round(
                    sum(1 for entry in entries if entry.get("online")) / len(entries) * 100.0,
                    2,
                ),
                "quality_class": _quality_class_from_score(metrics.get("score")),
                "anomaly": anomaly,
                "test_events": test_events,
            }
        )
    return buckets


def _baseline_for_timestamp(
    history: list[StoredSample], timestamp: datetime, interval: str
) -> dict[str, float | None]:
    candidate_entries = [
        entry for entry in history if entry["timestamp"] < timestamp and not _has_speedtest_event(entry)
    ]
    if not candidate_entries:
        candidate_entries = [entry for entry in history if entry["timestamp"] < timestamp]
    if not candidate_entries:
        return {metric: None for metric in METRICS}

    matching_entries = [
        entry for entry in candidate_entries if _slot_key(entry["timestamp"], interval) == _slot_key(timestamp, interval)
    ]
    if len(matching_entries) < BASELINE_MINIMUM_SAMPLES:
        matching_entries = candidate_entries[-BASELINE_FALLBACK_SAMPLES:]

    return _mean_metrics(matching_entries)


def _bucket_anomaly(
    entries: list[StoredSample],
    metrics: dict[str, float],
    baseline: dict[str, float | None],
) -> dict[str, Any]:
    outage = any(not entry.get("online", False) for entry in entries) or metrics.get(
        "availability", 100.0
    ) < OUTAGE_AVAILABILITY_THRESHOLD
    drastic_drop = False
    score = metrics.get("score")
    baseline_score = baseline.get("score")
    if score is not None and baseline_score is not None:
        drastic_drop = score <= max(
            baseline_score - QUALITY_DROP_SCORE_DELTA,
            baseline_score * QUALITY_DROP_SCORE_FACTOR,
        )

    metrics_deviation: dict[str, float] = {}
    for metric in METRICS:
        metric_value = metrics.get(metric)
        baseline_value = baseline.get(metric)
        if metric_value is None or baseline_value in (None, 0):
            continue
        if metric in HIGHER_IS_BETTER_METRICS:
            deviation = ((metric_value - baseline_value) / baseline_value) * 100.0
        else:
            deviation = ((baseline_value - metric_value) / baseline_value) * 100.0
        metrics_deviation[metric] = round(deviation, 2)
        if metric in HIGHER_IS_BETTER_METRICS and metric_value < baseline_value * DRAMATIC_DROP_FACTOR:
            drastic_drop = True
        if metric in LOWER_IS_BETTER_METRICS and metric_value > baseline_value * DRAMATIC_RISE_FACTOR:
            drastic_drop = True

    return {
        "outage": outage,
        "drastic_drop": drastic_drop,
        "state": _anomaly_state(
            {
                "sample": metrics,
                "online": not outage,
                "score": score,
            },
            baseline,
        ),
        "deviation": metrics_deviation,
    }


def _anomaly_state(entry: dict[str, Any], baseline: dict[str, float | None]) -> str:
    score = entry.get("score")
    if score is None:
        score = entry.get("sample", {}).get("score")
    if not entry.get("online", True):
        return "outage"
    baseline_score = baseline.get("score")
    if baseline_score is not None and score is not None:
        if score <= max(baseline_score - QUALITY_DROP_SCORE_DELTA, baseline_score * QUALITY_DROP_SCORE_FACTOR):
            return "critical"
        if score < baseline_score:
            return "degraded"
    return "normal"


def _current_snapshot(history: list[StoredSample]) -> dict[str, Any]:
    if not history:
        return {}
    latest = history[-1]
    sample = latest.get("sample", {})
    return {
        **{metric: sample.get(metric) for metric in METRICS},
        "contract_ratio": latest.get("contract_ratio", sample.get("contract_ratio")),
        "score": latest.get("score", sample.get("score")),
        "online": latest.get("online"),
        "quality_class": latest.get("quality_class") or _quality_class_from_score(latest.get("score")),
        "timestamp": latest["timestamp"].isoformat(),
    }


def _service_summary(history: list[StoredSample]) -> list[dict[str, Any]]:
    per_service: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in history:
        for service in entry.get("services", []):
            per_service[service["name"]].append(service)

    summary: list[dict[str, Any]] = []
    for name in sorted(per_service):
        items = per_service[name]
        last = items[-1]
        availability = round(
            sum(1 for item in items if item.get("reachable")) / len(items) * 100.0,
            2,
        )
        outages = 0
        previous = None
        for item in items:
            current = bool(item.get("reachable"))
            if previous is True and current is False:
                outages += 1
            previous = current
        summary.append(
            {
                "name": name,
                "current_reachable": bool(last.get("reachable")),
                "current_detail": str(last.get("detail", "")),
                "availability_ratio": availability,
                "outages": outages,
                "samples": len(items),
            }
        )
    return summary


def _regularity_patterns(
    history: list[StoredSample], interval: str, now: datetime
) -> list[str]:
    if not history or (now - history[0]["timestamp"]).days < MIN_HISTORY_DAYS_FOR_REGULARITY:
        return []

    recent_history = [
        entry for entry in history if entry["timestamp"] >= now - timedelta(days=REGULARITY_LOOKBACK_DAYS)
    ]
    buckets = _build_buckets(recent_history, interval, history)
    counter: Counter[str] = Counter()
    for bucket in buckets:
        anomaly = bucket.get("anomaly", {})
        if not anomaly.get("drastic_drop") and not anomaly.get("outage"):
            continue
        key = _recurring_label(parse_iso_datetime(bucket["start"]), interval)
        counter[key] += 1

    patterns = []
    for label, count in counter.most_common(5):
        if count < REGULARITY_MIN_OCCURRENCES:
            continue
        patterns.append(f"{label}: {count} anomaly windows")
    return patterns


def _recurring_label(timestamp: datetime | None, interval: str) -> str:
    if timestamp is None:
        return "Unknown"
    if interval == "hour":
        return f"Hour {timestamp.hour:02d}:00"
    if interval == "day":
        return timestamp.strftime("%A")
    if interval == "week":
        return f"Week {timestamp.isocalendar().week}"
    if interval == "month":
        return timestamp.strftime("%B")
    return f"Q{((timestamp.month - 1) // 3) + 1}"


def _mean_metrics(entries: list[StoredSample]) -> dict[str, float]:
    aggregated: dict[str, list[float]] = defaultdict(list)
    for entry in entries:
        sample = dict(entry.get("sample", {}))
        sample["contract_ratio"] = _safe_float(entry.get("contract_ratio", sample.get("contract_ratio")))
        sample["score"] = _safe_float(entry.get("score", sample.get("score")))
        for metric in METRICS:
            value = sample.get(metric)
            if value is None:
                continue
            aggregated[metric].append(_safe_float(value))

    return {
        metric: round(mean(values), 2)
        for metric, values in aggregated.items()
        if values
    }


def _slot_key(timestamp: datetime, interval: str) -> tuple[int, ...]:
    if interval == "hour":
        return (timestamp.hour,)
    if interval == "day":
        return (timestamp.weekday(),)
    if interval == "week":
        return (timestamp.isocalendar().week,)
    if interval == "month":
        return (timestamp.month,)
    return (((timestamp.month - 1) // 3) + 1,)


def _floor_datetime(timestamp: datetime, interval: str) -> datetime:
    local = timestamp.astimezone(UTC)
    if interval == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    if interval == "day":
        return datetime.combine(local.date(), time.min, tzinfo=UTC)
    if interval == "week":
        return datetime.combine(local.date() - timedelta(days=local.weekday()), time.min, tzinfo=UTC)
    if interval == "month":
        return datetime(local.year, local.month, 1, tzinfo=UTC)
    quarter_month = ((local.month - 1) // 3) * 3 + 1
    return datetime(local.year, quarter_month, 1, tzinfo=UTC)


def _next_bucket(timestamp: datetime, interval: str) -> datetime:
    if interval == "hour":
        return timestamp + timedelta(hours=1)
    if interval == "day":
        return timestamp + timedelta(days=1)
    if interval == "week":
        return timestamp + timedelta(days=7)
    if interval == "month":
        year = timestamp.year + (1 if timestamp.month == 12 else 0)
        month = 1 if timestamp.month == 12 else timestamp.month + 1
        return datetime(year, month, 1, tzinfo=UTC)
    quarter_start_month = timestamp.month
    month = quarter_start_month + 3
    year = timestamp.year
    if month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1, tzinfo=UTC)


def _bucket_label(timestamp: datetime, interval: str) -> str:
    if interval == "hour":
        return timestamp.strftime("%d.%m. %H:00")
    if interval == "day":
        return timestamp.strftime("%d.%m.%Y")
    if interval == "week":
        iso = timestamp.isocalendar()
        return f"{iso.year}-KW{iso.week:02d}"
    if interval == "month":
        return timestamp.strftime("%Y-%m")
    return f"{timestamp.year}-Q{((timestamp.month - 1) // 3) + 1}"


def _quality_class_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def _normalize_active_test_events(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        event = str(item).strip()
        if event:
            normalized.append(event)
    return normalized


def _normalize_tests(value: Any) -> dict[str, dict[str, str | None]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, str | None]] = {}
    for test_name, details in value.items():
        name = str(test_name).strip().lower()
        if not name or not isinstance(details, dict):
            continue
        parsed_details: dict[str, str | None] = {}
        for key in ("last_run_at", "last_started_at", "last_finished_at"):
            parsed = parse_iso_datetime(details.get(key))
            parsed_details[key] = parsed.isoformat() if parsed else None
        normalized[name] = parsed_details
    return normalized


def _has_speedtest_event(entry: StoredSample) -> bool:
    events = entry.get("active_test_events", [])
    if not isinstance(events, list):
        return False
    return any(event in {"download_test", "upload_test"} for event in events)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
