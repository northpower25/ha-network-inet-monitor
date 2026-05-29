"""Coordinator for Network Quality integration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import logging
import math
from time import monotonic
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
    AGENT_MODE_ADDON,
    AGENT_MODE_EXTERNAL_AGENT,
    AGENT_MODE_FALLBACK,
    AGENT_MODE_LOCAL_RUNNER,
    AGENT_MODES,
    CONF_AGENT_MODE,
    CONF_AGENT_TOKEN,
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
    DEFAULT_ADDON_AGENT_URL,
    DEFAULT_PING_INTERVAL,
    DEFAULT_SPEEDTEST_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DEFAULT_TEST_TARGETS,
    DEFAULT_TRACEROUTE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL_SECONDS,
    SERVICE_CHECK_URLS,
    UPDATE_TIMEOUT_SECONDS,
)
from .target_parser import parse_target_host_port

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
DIAGNOSTIC_STALE_FACTOR = 2.0
FALLBACK_CONNECT_PROBE_ATTEMPTS = 3
FALLBACK_CONNECT_TIMEOUT_SECONDS = 3.0
FALLBACK_CONNECT_PORT = 443
LOCAL_RUNNER_TOTAL_TIMEOUT_SECONDS = 8.0
LOCAL_RUNNER_MAX_PARALLEL_PROBES = 2
AGENT_CIRCUIT_BREAKER_THRESHOLD = 3
AGENT_CIRCUIT_BREAKER_SECONDS = 60


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
        self._last_success_at: str | None = None
        self._last_error_at: str | None = None
        self._last_error_message: str | None = None
        self._last_error_type: str | None = None
        self._agent_failures = 0
        self._agent_circuit_open_until_monotonic = 0.0
        self._agent_circuit_open_until_iso: str | None = None
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
        method_metrics: dict[str, dict[str, float]] = {}

        agent_mode = self._resolve_agent_mode(options)
        agent_url = self._resolve_agent_url(options=options, mode=agent_mode)
        agent_token = str(options.get(CONF_AGENT_TOKEN, "")).strip()
        services = options.get(CONF_SERVICE_STATUSES, [])
        external_opt_in = options.get(CONF_EXTERNAL_OPT_IN, False)
        targets = options.get(CONF_TEST_TARGETS, DEFAULT_TEST_TARGETS)

        try:
            if agent_mode == AGENT_MODE_EXTERNAL_AGENT and not agent_url:
                raise UpdateFailed("external_agent mode requires agent_url")
            if agent_mode in (AGENT_MODE_ADDON, AGENT_MODE_EXTERNAL_AGENT) and agent_url:
                payload = await self._async_fetch_agent_metrics(
                    agent_url=agent_url,
                    agent_token=agent_token,
                )
                method_metrics = self._extract_method_metrics(payload)
                download = self._first_float_value(
                    payload.get("download_mbps"),
                    payload.get("download"),
                    method_metrics.get("ookla", {}).get("download"),
                    method_metrics.get("iperf3", {}).get("download"),
                    method_metrics.get("http_download", {}).get("download"),
                    method_metrics.get("fast", {}).get("download"),
                ) or 0.0
                upload = self._first_float_value(
                    payload.get("upload_mbps"),
                    payload.get("upload"),
                    method_metrics.get("ookla", {}).get("upload"),
                    method_metrics.get("iperf3", {}).get("upload"),
                ) or 0.0
                ping = self._first_float_value(
                    payload.get("ping_ms"),
                    payload.get("ping"),
                    method_metrics.get("ookla", {}).get("ping"),
                ) or 0.0
                jitter = self._first_float_value(
                    payload.get("jitter_ms"),
                    payload.get("jitter"),
                    method_metrics.get("iperf3", {}).get("jitter"),
                ) or 0.0
                packet_loss = self._first_float_value(
                    payload.get("packet_loss_percent"),
                    payload.get("packet_loss"),
                    method_metrics.get("ookla", {}).get("packet_loss"),
                    method_metrics.get("iperf3", {}).get("packet_loss"),
                ) or 0.0
                availability = float(payload.get("availability_percent", 0.0))
                online = bool(payload.get("online", self._is_online_from_metrics(download, ping)))
                tests = self._extract_test_runs(payload)
                active_test_events = self._extract_active_test_events(payload, tests)
            elif agent_mode == AGENT_MODE_LOCAL_RUNNER:
                (
                    download,
                    upload,
                    online,
                    ping,
                    jitter,
                    packet_loss,
                    availability,
                ) = await self._async_collect_local_mode_metrics(contract=contract, targets=targets)
                tests = self._build_default_test_runs(now, agent_mode)
                active_test_events = []
            else:
                (
                    download,
                    upload,
                    online,
                    ping,
                    jitter,
                    packet_loss,
                    availability,
                ) = await self._async_collect_local_mode_metrics(contract=contract, targets=targets)
                tests = self._build_default_test_runs(now, agent_mode)
                active_test_events = []
        except Exception as err:
            self._last_error_at = now.isoformat()
            self._last_error_message = str(err)
            self._last_error_type = type(err).__name__
            source = (
                "agent endpoint"
                if agent_mode in (AGENT_MODE_ADDON, AGENT_MODE_EXTERNAL_AGENT)
                else "local runner"
            )
            raise UpdateFailed(f"Failed to update from {source}: {err}") from err

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
        service_statuses = await self._build_service_statuses(services, external_opt_in, online)
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

        self._last_success_at = now.isoformat()
        self._last_error_at = None
        self._last_error_message = None
        self._last_error_type = None
        return {
            "timestamp": now.isoformat(),
            "sample": sample,
            "online": online,
            "agent_mode": agent_mode,
            "agent_url": agent_url,
            "targets": targets,
            "services": service_statuses,
            "contract_ratio": stored_sample["contract_ratio"],
            "score": score,
            "quality_class": self._quality_class(score),
            "tests": tests,
            "active_test_events": active_test_events,
            "method_metrics": method_metrics,
            "rolling": self._rolling_aggregates(),
            "analysis": analysis,
        }

    def _resolve_agent_mode(self, options: dict[str, Any]) -> str:
        mode = str(options.get(CONF_AGENT_MODE, "")).strip().lower()
        if mode in AGENT_MODES:
            return mode
        if str(options.get(CONF_AGENT_URL, "")).strip():
            return AGENT_MODE_EXTERNAL_AGENT
        return AGENT_MODE_FALLBACK

    def _resolve_agent_url(self, *, options: dict[str, Any], mode: str) -> str:
        raw = str(options.get(CONF_AGENT_URL, "")).strip()
        if raw:
            return raw
        if mode == AGENT_MODE_ADDON:
            return DEFAULT_ADDON_AGENT_URL
        return ""

    async def _async_fetch_agent_metrics(
        self,
        *,
        agent_url: str,
        agent_token: str,
    ) -> dict[str, Any]:
        if monotonic() < self._agent_circuit_open_until_monotonic:
            raise UpdateFailed("Agent circuit breaker active")
        headers: dict[str, str] = {}
        if agent_token:
            headers["Authorization"] = "Bearer " + agent_token
        try:
            response = await self._session.get(
                f"{agent_url.rstrip('/')}/metrics",
                timeout=UPDATE_TIMEOUT_SECONDS,
                headers=headers,
            )
            response.raise_for_status()
            payload = await response.json()
        except Exception:
            self._register_agent_failure()
            raise
        self._reset_agent_failures()
        return payload if isinstance(payload, dict) else {}

    def _register_agent_failure(self) -> None:
        self._agent_failures += 1
        if self._agent_failures < AGENT_CIRCUIT_BREAKER_THRESHOLD:
            return
        reopen_at = monotonic() + AGENT_CIRCUIT_BREAKER_SECONDS
        self._agent_circuit_open_until_monotonic = reopen_at
        self._agent_circuit_open_until_iso = (
            datetime.now(tz=UTC) + timedelta(seconds=AGENT_CIRCUIT_BREAKER_SECONDS)
        ).isoformat()

    def _reset_agent_failures(self) -> None:
        self._agent_failures = 0
        self._agent_circuit_open_until_monotonic = 0.0
        self._agent_circuit_open_until_iso = None

    async def _async_collect_local_mode_metrics(
        self,
        *,
        contract: dict[str, Any],
        targets: list[str] | Any,
    ) -> tuple[float, float, bool, float, float, float, float]:
        download = float(contract.get(CONF_DOWNLOAD_NORMAL, 0.0))
        upload = float(contract.get(CONF_UPLOAD_NORMAL, 0.0))
        fallback_probe = await self._async_collect_local_probe_metrics(
            targets,
            total_timeout=LOCAL_RUNNER_TOTAL_TIMEOUT_SECONDS,
        )
        return (
            download,
            upload,
            bool(fallback_probe["online"]),
            float(fallback_probe["ping"]),
            float(fallback_probe["jitter"]),
            float(fallback_probe["packet_loss"]),
            float(fallback_probe["availability"]),
        )

    def diagnostic_state(self) -> str:
        """Return debug state for diagnostics sensor."""
        now = datetime.now(tz=UTC)
        mode = self._resolve_agent_mode(self.entry.options)
        if not self.last_update_success:
            return "error"
        if mode == AGENT_MODE_FALLBACK:
            return "warning"
        if mode in (AGENT_MODE_ADDON, AGENT_MODE_EXTERNAL_AGENT) and not self._resolve_agent_url(
            options=self.entry.options,
            mode=mode,
        ):
            return "warning"
        if self._is_data_stale(now=now):
            return "warning"
        return "ok"

    def diagnostic_attributes(self) -> dict[str, Any]:
        """Return checklist-oriented debug details."""
        now = datetime.now(tz=UTC)
        tests = self.data.get("tests", {}) if isinstance(self.data, dict) else {}
        mode = self._resolve_agent_mode(self.entry.options)
        agent_url = self._resolve_agent_url(options=self.entry.options, mode=mode)
        checklist = self._build_diagnostic_checklist(now=now, tests=tests)
        return {
            "agent_mode": mode,
            "agent_url_configured": bool(agent_url),
            "agent_url": agent_url or None,
            "agent_token_configured": bool(str(self.entry.options.get(CONF_AGENT_TOKEN, "")).strip()),
            "agent_circuit_open_until": self._agent_circuit_open_until_iso,
            "coordinator_last_update_success": self.last_update_success,
            "coordinator_update_interval_seconds": int(self.update_interval.total_seconds()),
            "last_success_at": self._last_success_at,
            "last_error_at": self._last_error_at,
            "last_error_type": self._last_error_type,
            "last_error_message": self._last_error_message,
            "configured_intervals": {
                "ping": int(self.entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL)),
                "traceroute": int(
                    self.entry.options.get(CONF_TRACEROUTE_INTERVAL, DEFAULT_TRACEROUTE_INTERVAL)
                ),
                "download": int(
                    self.entry.options.get(
                        CONF_DOWNLOAD_TEST_INTERVAL,
                        self.entry.options.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_SPEEDTEST_INTERVAL),
                    )
                ),
                "upload": int(
                    self.entry.options.get(
                        CONF_UPLOAD_TEST_INTERVAL,
                        self.entry.options.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_SPEEDTEST_INTERVAL),
                    )
                ),
                "status": int(self.entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)),
            },
            "local_runner_limits": {
                "total_timeout_seconds": LOCAL_RUNNER_TOTAL_TIMEOUT_SECONDS,
                "max_parallel_probes": LOCAL_RUNNER_MAX_PARALLEL_PROBES,
                "connect_timeout_seconds": FALLBACK_CONNECT_TIMEOUT_SECONDS,
                "connect_probe_attempts": FALLBACK_CONNECT_PROBE_ATTEMPTS,
            },
            "diagnostic_checklist": checklist,
        }

    def _is_data_stale(self, *, now: datetime) -> bool:
        if not isinstance(self.data, dict):
            return True
        timestamp = self._safe_parse_iso(self.data.get("timestamp"))
        if timestamp is None:
            return True
        stale_after = self.update_interval.total_seconds() * DIAGNOSTIC_STALE_FACTOR
        age_seconds = (now - timestamp).total_seconds()
        return age_seconds > stale_after

    def _build_diagnostic_checklist(
        self,
        *,
        now: datetime,
        tests: dict[str, dict[str, str | None]],
    ) -> list[dict[str, str]]:
        is_stale = self._is_data_stale(now=now)
        mode = self._resolve_agent_mode(self.entry.options)
        agent_url = self._resolve_agent_url(options=self.entry.options, mode=mode)
        if mode == AGENT_MODE_FALLBACK:
            mode_status = "warning"
            mode_detail = "Fallback mode active (light local reachability probes only)"
        elif mode == AGENT_MODE_LOCAL_RUNNER:
            mode_status = "ok"
            mode_detail = "Local runner mode active (light local probe runner enabled)"
        elif agent_url:
            mode_status = "ok"
            mode_detail = f"Agent mode '{mode}' active with configured endpoint"
        else:
            mode_status = "warning"
            mode_detail = f"Agent mode '{mode}' selected but no endpoint configured"
        checklist: list[dict[str, str]] = [
            {
                "id": "coordinator_refresh",
                "status": "ok" if self.last_update_success else "error",
                "detail": (
                    "Coordinator refresh successful"
                    if self.last_update_success
                    else "Coordinator refresh failed"
                ),
            },
            {
                "id": "agent_configuration",
                "status": mode_status,
                "detail": mode_detail,
            },
            {
                "id": "sample_freshness",
                "status": "warning" if is_stale else "ok",
                "detail": (
                    "Latest sample appears stale"
                    if is_stale
                    else "Latest sample age is within expected interval"
                ),
            },
        ]
        test_names = ["ping", "traceroute", "download", "upload", "status"]
        if isinstance(tests, dict):
            for key in sorted(tests):
                if key not in test_names:
                    test_names.append(key)
        for test_name in test_names:
            details = tests.get(test_name, {})
            last_run = (
                self._safe_parse_iso(details.get("last_run_at"))
                if isinstance(details, dict)
                else None
            )
            reason = str(details.get("reason", "")).strip() if isinstance(details, dict) else ""
            checklist.append(
                {
                    "id": f"{test_name}_last_run",
                    "status": "ok" if last_run else "warning",
                    "detail": (
                        f"Last run at {last_run.isoformat()}"
                        if last_run
                        else (
                            "Skipped: no agent endpoint configured"
                            if reason in ("agent_url_not_configured", "agent_endpoint_not_configured")
                            else (
                                "Skipped: fallback mode active"
                                if reason == "fallback_mode_active"
                                else (
                                    "Skipped: local runner mode active"
                                    if reason == "local_runner_mode_active"
                                    else f"No valid last_run_at for {test_name} test"
                                )
                            )
                        )
                    ),
                }
            )
        if self._last_error_message:
            checklist.append(
                {
                    "id": "last_error",
                    "status": "error",
                    "detail": f"{self._last_error_type or 'Error'}: {self._last_error_message}",
                }
            )
        return checklist

    def _safe_parse_iso(self, value: str | None) -> datetime | None:
        try:
            return parse_iso_datetime(value)
        except (TypeError, ValueError):
            return None

    def _is_online_from_metrics(self, download_mbps: float, ping_ms: float) -> bool:
        """Infer online state when agent payload does not provide an explicit flag."""
        return download_mbps > 0 or ping_ms > 0

    async def _build_service_statuses(
        self, services: list[str], external_opt_in: bool, online: bool
    ) -> list[ServiceStatus]:
        if not services:
            return []
        if not external_opt_in:
            return [
                ServiceStatus(name=name, reachable=online, detail="external_checks_disabled")
                for name in services
            ]
        results: list[ServiceStatus] = []
        for name in services:
            url = SERVICE_CHECK_URLS.get(name)
            if not url:
                results.append(ServiceStatus(name=name, reachable=online, detail="not_configured"))
                continue
            try:
                resp = await self._session.get(
                    url,
                    timeout=8,
                    allow_redirects=True,
                )
                reachable = resp.status < 500
            except Exception:
                reachable = False
            results.append(ServiceStatus(name=name, reachable=reachable, detail=url))
        return results

    def _build_default_test_runs(
        self, now: datetime, agent_mode: str
    ) -> dict[str, dict[str, str | None]]:
        """Provide fallback test metadata when no agent endpoint is configured."""
        timestamp = now.isoformat()
        reason = (
            "local_runner_mode_active"
            if agent_mode == AGENT_MODE_LOCAL_RUNNER
            else "fallback_mode_active"
        )
        return {
            "ping": {"last_run_at": timestamp},
            "traceroute": {"last_run_at": timestamp},
            "status": {"last_run_at": timestamp},
            "download": {
                "last_run_at": None,
                "last_started_at": None,
                "last_finished_at": None,
                "reason": reason,
            },
            "upload": {
                "last_run_at": None,
                "last_started_at": None,
                "last_finished_at": None,
                "reason": reason,
            },
        }

    async def _async_collect_local_probe_metrics(
        self,
        targets: list[str] | Any,
        *,
        total_timeout: float,
    ) -> dict[str, float | bool]:
        """Measure local TCP connect latency as fallback when no agent URL is configured."""
        hosts = self._normalize_probe_targets(targets)
        if not hosts:
            return {
                "online": False,
                "ping": 0.0,
                "jitter": 0.0,
                "packet_loss": 100.0,
                "availability": 0.0,
            }

        latencies: list[float] = []
        failed = 0
        total = 0
        host_count = len(hosts)
        semaphore = asyncio.Semaphore(LOCAL_RUNNER_MAX_PARALLEL_PROBES)

        async def _probe_once(host: str) -> float | None:
            async with semaphore:
                return await self._async_measure_connect_latency_ms(host)

        tasks = [
            asyncio.create_task(_probe_once(hosts[probe_index % host_count]))
            for probe_index in range(FALLBACK_CONNECT_PROBE_ATTEMPTS)
        ]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=total_timeout,
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        total = len(results)
        for result in results:
            if isinstance(result, BaseException):
                failed += 1
                continue
            if result is None:
                failed += 1
                continue
            latencies.append(result)

        if not latencies:
            return {
                "online": False,
                "ping": 0.0,
                "jitter": 0.0,
                "packet_loss": 100.0,
                "availability": 0.0,
            }

        deltas = [abs(current - previous) for previous, current in zip(latencies, latencies[1:])]
        successful = total - failed
        return {
            "online": successful > 0,
            "ping": round(mean(latencies), 2),
            "jitter": round(mean(deltas), 2) if deltas else 0.0,
            "packet_loss": round((failed / total) * 100.0, 2),
            "availability": round((successful / total) * 100.0, 2),
        }

    async def _async_measure_connect_latency_ms(self, host: str) -> float | None:
        """Return TCP connect latency for one target."""
        started = datetime.now(tz=UTC)
        writer = None
        try:
            connection = asyncio.open_connection(host, FALLBACK_CONNECT_PORT)
            _, writer = await asyncio.wait_for(
                connection,
                timeout=FALLBACK_CONNECT_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError):
            return None
        try:
            latency_ms = (datetime.now(tz=UTC) - started).total_seconds() * 1000.0
            return round(latency_ms, 2)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    def _normalize_probe_targets(self, targets: list[str] | Any) -> list[str]:
        """Extract unique hostnames/IPs from configured targets."""
        if not isinstance(targets, list):
            return []
        hosts: list[str] = []
        for value in targets:
            if not isinstance(value, str):
                continue
            candidate = value.strip()
            if not candidate:
                continue
            parsed = parse_target_host_port(candidate)
            if parsed is None:
                continue
            host, _ = parsed
            host = host.strip("[]").strip()
            if host and host not in hosts:
                hosts.append(host)
        return hosts

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
        ookla_data = _source("ookla")
        if not ookla_data:
            ookla_data = _source("speedtest_ookla")
        fast_data = _source("fast")
        if not fast_data:
            fast_data = _source("fast_com")
        iperf_data = _source("iperf3")
        if not iperf_data:
            iperf_data = _source("iperf")
        http_data = _source("http_download")
        if not http_data:
            http_data = _source("http")

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
            "ookla_speedtest": {
                "last_run_at": _pick(
                    ookla_data.get("last_run_at"),
                    ookla_data.get("last_run"),
                    payload.get("last_ookla_test_at"),
                    payload.get("ookla_last_run_at"),
                    payload.get("last_speedtest_at"),
                    payload.get("speedtest_last_run_at"),
                )
            },
            "fast_speedtest": {
                "last_run_at": _pick(
                    fast_data.get("last_run_at"),
                    fast_data.get("last_run"),
                    payload.get("last_fast_test_at"),
                    payload.get("fast_last_run_at"),
                )
            },
            "iperf3": {
                "last_run_at": _pick(
                    iperf_data.get("last_run_at"),
                    iperf_data.get("last_run"),
                    payload.get("last_iperf3_test_at"),
                    payload.get("iperf3_last_run_at"),
                    payload.get("last_iperf_test_at"),
                    payload.get("iperf_last_run_at"),
                )
            },
            "http_download": {
                "last_run_at": _pick(
                    http_data.get("last_run_at"),
                    http_data.get("last_run"),
                    payload.get("last_http_download_test_at"),
                    payload.get("http_download_last_run_at"),
                )
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

    def _extract_method_metrics(self, payload: dict[str, Any]) -> dict[str, dict[str, float]]:
        """Extract optional per-method measurement values from agent payload."""
        methods_payload = payload.get("methods", {})

        def _source(*names: str) -> dict[str, Any]:
            merged: dict[str, Any] = {}
            for name in names:
                direct = payload.get(name, {})
                method = methods_payload.get(name, {}) if isinstance(methods_payload, dict) else {}
                if isinstance(direct, dict):
                    merged.update(direct)
                if isinstance(method, dict):
                    merged.update(method)
            return merged

        ookla = _source("ookla", "speedtest_ookla", "speedtest")
        fast = _source("fast", "fast_com", "fastcom")
        iperf = _source("iperf3", "iperf")
        http_download = _source("http_download", "http", "download_http")

        values: dict[str, dict[str, float]] = {
            "ookla": {
                "download": self._first_float_value(
                    ookla.get("download_mbps"),
                    ookla.get("download"),
                    payload.get("ookla_download_mbps"),
                ),
                "upload": self._first_float_value(
                    ookla.get("upload_mbps"),
                    ookla.get("upload"),
                    payload.get("ookla_upload_mbps"),
                ),
                "ping": self._first_float_value(
                    ookla.get("ping_ms"),
                    ookla.get("ping"),
                    payload.get("ookla_ping_ms"),
                ),
                "packet_loss": self._first_float_value(
                    ookla.get("packet_loss_percent"),
                    ookla.get("packet_loss"),
                    payload.get("ookla_packet_loss_percent"),
                ),
            },
            "fast": {
                "download": self._first_float_value(
                    fast.get("download_mbps"),
                    fast.get("download"),
                    payload.get("fast_download_mbps"),
                )
            },
            "iperf3": {
                "download": self._first_float_value(
                    iperf.get("download_mbps"),
                    iperf.get("download"),
                    payload.get("iperf3_download_mbps"),
                    payload.get("iperf_download_mbps"),
                ),
                "upload": self._first_float_value(
                    iperf.get("upload_mbps"),
                    iperf.get("upload"),
                    payload.get("iperf3_upload_mbps"),
                    payload.get("iperf_upload_mbps"),
                ),
                "jitter": self._first_float_value(
                    iperf.get("jitter_ms"),
                    iperf.get("jitter"),
                    payload.get("iperf3_jitter_ms"),
                    payload.get("iperf_jitter_ms"),
                ),
                "packet_loss": self._first_float_value(
                    iperf.get("packet_loss_percent"),
                    iperf.get("packet_loss"),
                    payload.get("iperf3_packet_loss_percent"),
                    payload.get("iperf_packet_loss_percent"),
                ),
            },
            "http_download": {
                "download": self._first_float_value(
                    http_download.get("download_mbps"),
                    http_download.get("download"),
                    payload.get("http_download_mbps"),
                )
            },
        }
        cleaned: dict[str, dict[str, float]] = {}
        for method_name, metrics in values.items():
            normalized_metrics = {
                metric_name: value
                for metric_name, value in metrics.items()
                if value is not None
            }
            if normalized_metrics:
                cleaned[method_name] = normalized_metrics
        return cleaned

    def _first_float_value(self, *values: Any) -> float | None:
        for value in values:
            parsed = self._to_float(value)
            if parsed is not None:
                return parsed
        return None

    def _to_float(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

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
