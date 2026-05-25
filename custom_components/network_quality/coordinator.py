"""Coordinator for Network Quality integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from statistics import mean
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AGENT_URL,
    CONF_DOWNLOAD_NORMAL,
    CONF_EXTERNAL_OPT_IN,
    CONF_PING_INTERVAL,
    CONF_SERVICE_STATUSES,
    CONF_STATUS_INTERVAL,
    CONF_TEST_TARGETS,
    CONF_UPLOAD_NORMAL,
    DEFAULT_PING_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DEFAULT_TEST_TARGETS,
    DOMAIN,
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

        refresh_interval = min(
            int(entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL)),
            int(entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=max(10, refresh_interval)),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update and normalize data."""
        now = datetime.now(tz=UTC)
        options = self.entry.options
        contract = self.entry.data

        download = 0.0
        upload = 0.0
        ping = 0.0
        jitter = 0.0
        packet_loss = 0.0
        availability = 0.0
        online = False

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
                online = bool(payload.get("online", download > 0 or ping > 0))
            else:
                online = True
                download = float(contract.get(CONF_DOWNLOAD_NORMAL, 0.0))
                upload = float(contract.get(CONF_UPLOAD_NORMAL, 0.0))
                ping = 10.0
                jitter = 1.0
                packet_loss = 0.0
                availability = 100.0
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
        self._samples = self._samples[-500:]

        score = self._calculate_score(sample)
        return {
            "timestamp": now.isoformat(),
            "sample": sample,
            "online": online,
            "targets": targets,
            "services": self._build_service_statuses(services, external_opt_in, online),
            "contract_ratio": self._contract_ratio_percent(sample),
            "score": score,
            "quality_class": self._quality_class(score),
            "rolling": self._rolling_aggregates(),
        }

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
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        if score >= 40:
            return "D"
        return "E"

    def build_report_payload(self, *, include_raw: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "isp": self.entry.data.get("isp"),
            "router_type": self.entry.data.get("router_type"),
            "latest": self.data or {},
            "samples": len(self._samples),
            "rolling": (self.data or {}).get("rolling", {}),
        }
        if include_raw:
            payload["raw_samples"] = self._samples
        return payload

    def render_report_text(self, payload: dict[str, Any]) -> str:
        latest = payload.get("latest", {})
        sample = latest.get("sample", {})
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
            ]
        )
