"""Coordinator for Network Quality integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import logging
from statistics import mean
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .analytics import (
    build_dashboard_payload,
    compute_analysis_overview,
    normalize_stored_sample,
    parse_iso_datetime,
    serialize_stored_sample,
    trim_history,
)
from .const import (
    CONF_AGENT_URL,
    CONF_DOWNLOAD_TEST_INTERVAL,
    CONF_DOWNLOAD_NORMAL,
    CONF_EXTERNAL_OPT_IN,
    CONF_PING_INTERVAL,
    CONF_SERVICE_STATUSES,
    CONF_SPEEDTEST_INTERVAL,
    CONF_STATUS_INTERVAL,
    CONF_TEST_TARGETS,
    CONF_TRACEROUTE_INTERVAL,
    CONF_UPLOAD_TEST_INTERVAL,
    CONF_UPLOAD_NORMAL,
    DEFAULT_PING_INTERVAL,
    DEFAULT_SPEEDTEST_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DEFAULT_TEST_TARGETS,
    DEFAULT_TRACEROUTE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL_SECONDS,
    UPDATE_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# Score model constants.
MAX_CONTRACT_RATIO_MULTIPLIER = 1.2
PING_THRESHOLD_MS = 200.0
JITTER_THRESHOLD_MS = 100.0
PACKET_LOSS_THRESHOLD_PERCENT = 10.0
PERCENT_BASE = 100.0

# Weighting of the quality score:
# Contract fulfillment dominates, then latency and stability, then availability.
WEIGHT_CONTRACT_RATIO = 0.4
WEIGHT_LATENCY = 0.2
WEIGHT_JITTER = 0.1
WEIGHT_PACKET_LOSS = 0.15
WEIGHT_AVAILABILITY = 0.15

# Keep enough history for trend metrics while limiting memory growth.
# Effective lookback depends on configured polling intervals.
MAX_SAMPLE_HISTORY = 500
MAX_STORED_HISTORY_DAYS = 400
STORE_VERSION = 1
STORED_SAMPLE_INTERVAL = timedelta(minutes=15)
SCORE_CHANGE_THRESHOLD = 10.0
# Project-specific quality grade boundaries for A-E classification.
QUALITY_CLASS_A_THRESHOLD = 90.0
QUALITY_CLASS_B_THRESHOLD = 75.0
QUALITY_CLASS_C_THRESHOLD = 60.0
QUALITY_CLASS_D_THRESHOLD = 40.0
MAX_REASONABLE_FUTURE_DAYS = 3650


@dataclass(slots=True)
class ServiceStatus:
    """Single service status item."""

    name: str
    reachable: bool
    detail: str


class NetworkQualityCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate measurement data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._session = async_get_clientsession(hass)
        self._samples: list[dict[str, float]] = []
        self._history: list[dict[str, Any]] = []
        self._store = Store[dict[str, Any]](hass, STORE_VERSION, f"{DOMAIN}_{entry.entry_id}_history")
        refresh_interval = self._resolve_refresh_interval(entry.options)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(
                seconds=max(MIN_UPDATE_INTERVAL_SECONDS, refresh_interval)
            ),
        )

    async def async_initialize(self) -> None:
        """Load persisted history before the first refresh."""
        stored = await self._store.async_load()
        raw_history = stored.get("history", []) if isinstance(stored, dict) else []
        history: list[dict[str, Any]] = []
        for entry in raw_history:
            if not isinstance(entry, dict):
                continue
            normalized = normalize_stored_sample(entry)
            if normalized is not None:
                history.append(normalized)
        history.sort(key=lambda item: item["timestamp"])
        self._history = trim_history(history, keep_days=MAX_STORED_HISTORY_DAYS)

    async def _async_update_data(self) -> dict[str, Any]:
        """Update and normalize data."""
        now = datetime.now(tz=UTC)
        options = self.entry.options
        self.update_interval = timedelta(
            seconds=max(MIN_UPDATE_INTERVAL_SECONDS, self._resolve_refresh_interval(options))
        )
        contract = self.entry.data

        download = 0.0
        upload = 0.0
        ping = 0.0
        jitter = 0.0
        packet_loss = 0.0
        availability = 0.0
        online = False
        tests: dict[str, dict[str, str | None]] = {}
        active_test_events: list[str] = []

        agent_url = options.get(CONF_AGENT_URL)
        services = options.get(CONF_SERVICE_STATUSES, [])
        external_opt_in = options.get(CONF_EXTERNAL_OPT_IN, False)
        targets = options.get(CONF_TEST_TARGETS, DEFAULT_TEST_TARGETS)

        try:
            if agent_url:
                response = await self._session.get(
                    f"{agent_url.rstrip('/')}/metrics",
                    timeout=UPDATE_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = await response.json()
                download = float(payload.get("download_mbps", 0.0))
                upload = float(payload.get("upload_mbps", 0.0))
                ping = float(payload.get("ping_ms", 0.0))
                jitter = float(payload.get("jitter_ms", 0.0))
                packet_loss = float(payload.get("packet_loss_percent", 0.0))
                availability = float(payload.get("availability_percent", 0.0))
                online = bool(payload.get("online", self._is_online_from_metrics(download, ping)))
                tests = self._extract_test_runs(payload)
                active_test_events = self._extract_active_test_events(payload, tests)
            else:
                online = True
                download = float(contract.get(CONF_DOWNLOAD_NORMAL, 0.0))
                upload = float(contract.get(CONF_UPLOAD_NORMAL, 0.0))
                ping = 10.0
                jitter = 1.0
                packet_loss = 0.0
                availability = 100.0
                tests = self._build_default_test_runs(now)
                active_test_events = []
        except Exception as err:
            raise UpdateFailed(f"Failed to update from agent endpoint: {err}") from err

        sample = {
            "download": max(0.0, download),
            "upload": max(0.0, upload),
            "ping": max(0.0, ping),
            "jitter": max(0.0, jitter),
            "packet_loss": min(max(0.0, packet_loss), 100.0),
            "availability": min(max(0.0, availability), 100.0),
        }
        self._samples.append(sample)
        self._samples = self._samples[-MAX_SAMPLE_HISTORY:]

        score = self._calculate_score(sample)
        service_statuses = self._build_service_statuses(services, external_opt_in, online)
        stored_sample = self._build_stored_sample(
            timestamp=now,
            sample=sample,
            online=online,
            services=service_statuses,
            score=score,
            tests=tests,
            active_test_events=active_test_events,
        )
        await self._async_persist_sample(stored_sample)
        analysis = compute_analysis_overview(self._history, now=now)

        return {
            "timestamp": now.isoformat(),
            "sample": sample,
            "online": online,
            "targets": targets,
            "services": service_statuses,
            "contract_ratio": stored_sample["contract_ratio"],
            "score": score,
            "quality_class": self._quality_class(score),
            "tests": tests,
            "active_test_events": active_test_events,
            "rolling": self._rolling_aggregates(),
            "analysis": analysis,
        }

    def _is_online_from_metrics(self, download_mbps: float, ping_ms: float) -> bool:
        """Infer online state when agent payload does not provide an explicit flag."""
        return download_mbps > 0 or ping_ms > 0

    def _build_service_statuses(
        self, services: list[str], external_opt_in: bool, online: bool
    ) -> list[ServiceStatus]:
        if not services:
            return []
        if not external_opt_in:
            return [
                ServiceStatus(name=name, reachable=online, detail="external_checks_disabled")
                for name in services
            ]
        return [ServiceStatus(name=name, reachable=online, detail="not_configured") for name in services]

    def _build_default_test_runs(self, now: datetime) -> dict[str, dict[str, str | None]]:
        """Provide fallback test metadata when no agent endpoint is configured."""
        timestamp = now.isoformat()
        return {
            "ping": {"last_run_at": timestamp},
            "traceroute": {"last_run_at": timestamp},
            "status": {"last_run_at": timestamp},
            "download": {
                "last_run_at": timestamp,
                "last_started_at": timestamp,
                "last_finished_at": timestamp,
            },
            "upload": {
                "last_run_at": timestamp,
                "last_started_at": timestamp,
                "last_finished_at": timestamp,
            },
        }

    def _extract_test_runs(self, payload: dict[str, Any]) -> dict[str, dict[str, str | None]]:
        """Normalize test run metadata from agent payload."""
        tests_payload = payload.get("tests", {})
        runs_payload = payload.get("test_runs", {})

        def _pick(*values: Any) -> str | None:
            for value in values:
                normalized = self._normalize_timestamp(value)
                if normalized:
                    return normalized
            return None

        def _source(name: str) -> dict[str, Any]:
            merged: dict[str, Any] = {}
            tests_data = tests_payload.get(name, {}) if isinstance(tests_payload, dict) else {}
            runs_data = runs_payload.get(name, {}) if isinstance(runs_payload, dict) else {}
            if isinstance(tests_data, dict):
                merged.update(tests_data)
            if isinstance(runs_data, dict):
                merged.update(runs_data)
            return merged

        ping_data = _source("ping")
        traceroute_data = _source("traceroute")
        status_data = _source("status")
        download_data = _source("download")
        upload_data = _source("upload")

        return {
            "ping": {
                "last_run_at": _pick(
                    ping_data.get("last_run_at"),
                    ping_data.get("last_run"),
                    payload.get("last_ping_test_at"),
                    payload.get("last_ping_test"),
                    payload.get("ping_last_run_at"),
                    payload.get("ping_last_run"),
                )
            },
            "traceroute": {
                "last_run_at": _pick(
                    traceroute_data.get("last_run_at"),
                    traceroute_data.get("last_run"),
                    payload.get("last_traceroute_test_at"),
                    payload.get("last_traceroute_test"),
                    payload.get("traceroute_last_run_at"),
                    payload.get("traceroute_last_run"),
                )
            },
            "status": {
                "last_run_at": _pick(
                    status_data.get("last_run_at"),
                    status_data.get("last_run"),
                    payload.get("last_status_test_at"),
                    payload.get("last_status_test"),
                    payload.get("status_last_run_at"),
                    payload.get("status_last_run"),
                )
            },
            "download": {
                "last_run_at": _pick(
                    download_data.get("last_run_at"),
                    download_data.get("last_run"),
                    payload.get("last_download_test_at"),
                    payload.get("last_download_test"),
                    payload.get("download_last_run_at"),
                    payload.get("download_last_run"),
                ),
                "last_started_at": _pick(
                    download_data.get("last_started_at"),
                    download_data.get("started_at"),
                    payload.get("download_test_started_at"),
                    payload.get("last_download_test_started_at"),
                ),
                "last_finished_at": _pick(
                    download_data.get("last_finished_at"),
                    download_data.get("finished_at"),
                    payload.get("download_test_finished_at"),
                    payload.get("last_download_test_finished_at"),
                ),
            },
            "upload": {
                "last_run_at": _pick(
                    upload_data.get("last_run_at"),
                    upload_data.get("last_run"),
                    payload.get("last_upload_test_at"),
                    payload.get("last_upload_test"),
                    payload.get("upload_last_run_at"),
                    payload.get("upload_last_run"),
                ),
                "last_started_at": _pick(
                    upload_data.get("last_started_at"),
                    upload_data.get("started_at"),
                    payload.get("upload_test_started_at"),
                    payload.get("last_upload_test_started_at"),
                ),
                "last_finished_at": _pick(
                    upload_data.get("last_finished_at"),
                    upload_data.get("finished_at"),
                    payload.get("upload_test_finished_at"),
                    payload.get("last_upload_test_finished_at"),
                ),
            },
        }

    def _extract_active_test_events(
        self,
        payload: dict[str, Any],
        tests: dict[str, dict[str, str | None]],
    ) -> list[str]:
        """Extract active tests so analytics can mark them separately."""
        active_events: set[str] = set()
        active_tests = payload.get("active_tests", [])
        if isinstance(active_tests, list):
            for item in active_tests:
                name = str(item).strip().lower()
                if name:
                    active_events.add(f"{name.removesuffix('_test')}_test")

        if payload.get("download_test_running"):
            active_events.add("download_test")
        if payload.get("upload_test_running"):
            active_events.add("upload_test")

        for metric in ("download", "upload"):
            details = tests.get(metric, {})
            started = parse_iso_datetime(details.get("last_started_at"))
            finished = parse_iso_datetime(details.get("last_finished_at"))
            if started is None:
                continue
            if finished is None or finished < started:
                active_events.add(f"{metric}_test")

        return sorted(active_events)

    def _normalize_timestamp(self, value: Any) -> str | None:
        parsed = None
        if isinstance(value, datetime):
            parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
        elif isinstance(value, (int, float)):
            try:
                unix_timestamp = float(value)
                if unix_timestamp < 0:
                    return None
                max_reasonable_timestamp = (
                    datetime.now(tz=UTC) + timedelta(days=MAX_REASONABLE_FUTURE_DAYS)
                ).timestamp()
                if unix_timestamp > max_reasonable_timestamp:
                    return None
                parsed = datetime.fromtimestamp(unix_timestamp, tz=UTC)
            except (OverflowError, OSError, ValueError):
                return None
        elif isinstance(value, str):
            try:
                parsed = parse_iso_datetime(value)
            except ValueError:
                return None
        if parsed is None:
            return None
        return parsed.astimezone(UTC).isoformat()

    def _resolve_refresh_interval(self, options: dict[str, Any]) -> int:
        speedtest_interval = int(options.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_SPEEDTEST_INTERVAL))
        download_interval = int(options.get(CONF_DOWNLOAD_TEST_INTERVAL, speedtest_interval))
        upload_interval = int(options.get(CONF_UPLOAD_TEST_INTERVAL, speedtest_interval))
        return min(
            speedtest_interval,
            int(options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL)),
            int(options.get(CONF_TRACEROUTE_INTERVAL, DEFAULT_TRACEROUTE_INTERVAL)),
            download_interval,
            upload_interval,
            int(options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)),
        )

    def _rolling_aggregates(self) -> dict[str, float]:
        if not self._samples:
            return {}
        return {
            "download_avg": mean(x["download"] for x in self._samples),
            "download_min": min(x["download"] for x in self._samples),
            "download_max": max(x["download"] for x in self._samples),
            "upload_avg": mean(x["upload"] for x in self._samples),
            "upload_min": min(x["upload"] for x in self._samples),
            "upload_max": max(x["upload"] for x in self._samples),
            "ping_avg": mean(x["ping"] for x in self._samples),
            "packet_loss_avg": mean(x["packet_loss"] for x in self._samples),
            "jitter_avg": mean(x["jitter"] for x in self._samples),
            "availability_avg": mean(x["availability"] for x in self._samples),
        }

    def _contract_ratio_percent(self, sample: dict[str, float]) -> float:
        expected_download = float(self.entry.data.get(CONF_DOWNLOAD_NORMAL, 0.0))
        expected_upload = float(self.entry.data.get(CONF_UPLOAD_NORMAL, 0.0))
        ratios: list[float] = []
        if expected_download > 0:
            ratios.append(sample["download"] / expected_download)
        if expected_upload > 0:
            ratios.append(sample["upload"] / expected_upload)
        if not ratios:
            return 0.0
        return round(mean(ratios) * 100.0, 2)

    def _calculate_score(self, sample: dict[str, float]) -> float:
        contract_ratio = min(
            MAX_CONTRACT_RATIO_MULTIPLIER,
            max(0.0, self._contract_ratio_percent(sample) / PERCENT_BASE),
        )
        latency_factor = max(0.0, 1.0 - (sample["ping"] / PING_THRESHOLD_MS))
        jitter_factor = max(0.0, 1.0 - (sample["jitter"] / JITTER_THRESHOLD_MS))
        packet_loss_factor = max(
            0.0, 1.0 - (sample["packet_loss"] / PACKET_LOSS_THRESHOLD_PERCENT)
        )
        availability_factor = max(0.0, sample["availability"] / PERCENT_BASE)
        score = (
            contract_ratio * WEIGHT_CONTRACT_RATIO
            + latency_factor * WEIGHT_LATENCY
            + jitter_factor * WEIGHT_JITTER
            + packet_loss_factor * WEIGHT_PACKET_LOSS
            + availability_factor * WEIGHT_AVAILABILITY
        ) * PERCENT_BASE
        return round(max(0.0, min(100.0, score)), 2)

    def _quality_class(self, score: float) -> str:
        if score >= QUALITY_CLASS_A_THRESHOLD:
            return "A"
        if score >= QUALITY_CLASS_B_THRESHOLD:
            return "B"
        if score >= QUALITY_CLASS_C_THRESHOLD:
            return "C"
        if score >= QUALITY_CLASS_D_THRESHOLD:
            return "D"
        return "E"

    def _build_stored_sample(
        self,
        *,
        timestamp: datetime,
        sample: dict[str, float],
        online: bool,
        services: list[ServiceStatus],
        score: float,
        tests: dict[str, dict[str, str | None]],
        active_test_events: list[str],
    ) -> dict[str, Any]:
        return {
            "timestamp": timestamp,
            "sample": sample,
            "online": online,
            "services": [asdict(service) for service in services],
            "contract_ratio": self._contract_ratio_percent(sample),
            "score": score,
            "quality_class": self._quality_class(score),
            "tests": tests,
            "active_test_events": active_test_events,
        }

    async def _async_persist_sample(self, sample: dict[str, Any]) -> None:
        """Persist downsampled history for analytics."""
        should_store = not self._history
        if not should_store:
            last_entry = self._history[-1]
            elapsed = sample["timestamp"] - last_entry["timestamp"]
            status_changed = bool(last_entry.get("online")) != bool(sample.get("online"))
            score_changed = (
                abs(float(last_entry.get("score", 0.0)) - float(sample.get("score", 0.0)))
                >= SCORE_CHANGE_THRESHOLD
            )
            should_store = elapsed >= STORED_SAMPLE_INTERVAL or status_changed or score_changed

        if should_store:
            self._history.append(sample)
        else:
            self._history[-1] = sample

        self._history.sort(key=lambda item: item["timestamp"])
        self._history = trim_history(self._history, keep_days=MAX_STORED_HISTORY_DAYS)
        self._store.async_delay_save(
            lambda: {"history": [serialize_stored_sample(entry) for entry in self._history]},
            5,
        )

    def build_dashboard_payload(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str = "day",
    ) -> dict[str, Any]:
        """Return aggregated analytics payload for the frontend dashboard."""
        if not self._history:
            return {
                "range": {
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                    "interval": interval,
                },
                "current": self.data or {},
                "baseline_current": {},
                "buckets": [],
                "summary": {"outages": 0, "drastic_quality_drops": 0, "recurring_patterns": []},
                "services": [],
                "coverage": {"samples": 0, "range_samples": 0, "first": None, "last": None},
            }

        resolved_end = end or self._history[-1]["timestamp"]
        resolved_start = start or max(self._history[0]["timestamp"], resolved_end - timedelta(days=30))
        payload = build_dashboard_payload(
            self._history,
            start=resolved_start,
            end=resolved_end,
            interval=interval,
        )
        payload["entry_id"] = self.entry.entry_id
        payload["name"] = self.entry.title
        return payload

    def build_report_payload(self, *, include_raw: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "isp": self.entry.data.get("isp"),
            "router_type": self.entry.data.get("router_type"),
            "latest": self.data or {},
            "samples": len(self._samples),
            "rolling": (self.data or {}).get("rolling", {}),
            "analytics": self.build_dashboard_payload(interval="day"),
        }
        if include_raw:
            payload["raw_samples"] = self._samples
            payload["raw_history"] = [serialize_stored_sample(entry) for entry in self._history]
        return payload

    def render_report_text(self, payload: dict[str, Any]) -> str:
        latest = payload.get("latest", {})
        sample = latest.get("sample", {})
        analytics = payload.get("analytics", {}).get("summary", {})
        return "\n".join(
            [
                "Network Quality Report",
                f"Generated: {payload.get('generated_at')}",
                f"ISP: {payload.get('isp')}",
                f"Router: {payload.get('router_type')}",
                f"Download: {sample.get('download', 0.0)} Mbit/s",
                f"Upload: {sample.get('upload', 0.0)} Mbit/s",
                f"Ping: {sample.get('ping', 0.0)} ms",
                f"Packet Loss: {sample.get('packet_loss', 0.0)} %",
                f"Jitter: {sample.get('jitter', 0.0)} ms",
                f"Availability: {sample.get('availability', 0.0)} %",
                f"Contract Ratio: {latest.get('contract_ratio', 0.0)} %",
                f"Score: {latest.get('score', 0.0)}",
                f"Quality Class: {latest.get('quality_class', 'E')}",
                f"Detected Outages (range): {analytics.get('outages', 0)}",
                f"Drastic Quality Drops (range): {analytics.get('drastic_quality_drops', 0)}",
            ]
        )
