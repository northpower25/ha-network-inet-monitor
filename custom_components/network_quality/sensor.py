"""Sensor platform for Network Quality integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfDataRate, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import NetworkQualityCoordinator
from .entity import build_device_info


@dataclass(frozen=True, kw_only=True)
class NetworkQualitySensorDescription(SensorEntityDescription):
    """Describes Network Quality sensor entities."""

    value_fn: Callable[[dict[str, Any]], Any]
    """Callable extracting the sensor value from coordinator data."""


SENSOR_DESCRIPTIONS: tuple[NetworkQualitySensorDescription, ...] = (
    NetworkQualitySensorDescription(
        key="internet_download",
        translation_key="internet_download",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        value_fn=lambda data: data.get("sample", {}).get("download"),
    ),
    NetworkQualitySensorDescription(
        key="internet_upload",
        translation_key="internet_upload",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        value_fn=lambda data: data.get("sample", {}).get("upload"),
    ),
    NetworkQualitySensorDescription(
        key="ping_public",
        translation_key="ping_public",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        value_fn=lambda data: data.get("sample", {}).get("ping"),
    ),
    NetworkQualitySensorDescription(
        key="packet_loss",
        translation_key="packet_loss",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.get("sample", {}).get("packet_loss"),
    ),
    NetworkQualitySensorDescription(
        key="jitter",
        translation_key="jitter",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        value_fn=lambda data: data.get("sample", {}).get("jitter"),
    ),
    NetworkQualitySensorDescription(
        key="availability",
        translation_key="availability",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.get("sample", {}).get("availability"),
    ),
    NetworkQualitySensorDescription(
        key="contract_ratio",
        translation_key="contract_ratio",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.get("contract_ratio"),
    ),
    NetworkQualitySensorDescription(
        key="quality_score",
        translation_key="quality_score",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.get("score"),
    ),
    NetworkQualitySensorDescription(
        key="quality_class",
        translation_key="quality_class",
        value_fn=lambda data: data.get("quality_class"),
    ),
    NetworkQualitySensorDescription(
        key="debug_status",
        translation_key="debug_status",
        value_fn=lambda data: None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: NetworkQualityCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([NetworkQualitySensor(coordinator, desc) for desc in SENSOR_DESCRIPTIONS])


class NetworkQualitySensor(CoordinatorEntity[NetworkQualityCoordinator], RestoreSensor):
    """Representation of a Network Quality sensor."""

    entity_description: NetworkQualitySensorDescription

    def __init__(
        self,
        coordinator: NetworkQualityCoordinator,
        description: NetworkQualitySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = description.key
        self._attr_suggested_object_id = f"{DOMAIN}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Restore last known state if coordinator data is not yet available."""
        await super().async_added_to_hass()
        if not self.coordinator.data:
            if (last_sensor_data := await self.async_get_last_sensor_data()) is not None:
                self._attr_native_value = last_sensor_data.native_value

    @property
    def native_value(self) -> Any:
        """Return sensor value."""
        if self.entity_description.key == "debug_status":
            return self.coordinator.diagnostic_state()
        if not self.coordinator.data:
            return self._attr_native_value
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return availability."""
        if self.entity_description.key == "debug_status":
            return True
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional attributes."""
        if not self.coordinator.data:
            return None

        if self.entity_description.key in {"internet_download", "internet_upload"}:
            analysis = self.coordinator.data.get("analysis", {})
            period = (analysis.get("periods", {}) or {}).get("day", {})
            return {
                **self.coordinator.data.get("rolling", {}),
                "baseline": period.get(
                    "baseline_download"
                    if self.entity_description.key == "internet_download"
                    else "baseline_upload"
                ),
                "analysis_available": analysis.get("available", False),
            }

        if self.entity_description.key == "quality_score":
            analysis = self.coordinator.data.get("analysis", {})
            return {
                "quality_class": self.coordinator.data.get("quality_class"),
                "contract_ratio": self.coordinator.data.get("contract_ratio"),
                "baseline_score": analysis.get("baseline_score"),
                "score_delta": analysis.get("score_delta"),
                "anomaly_state": analysis.get("anomaly_state"),
                "recurring_patterns": analysis.get("recurring_patterns", []),
            }

        if self.entity_description.key == "debug_status":
            return self.coordinator.diagnostic_attributes()

        return None

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device metadata so entities are grouped in one integration device."""
        return build_device_info(self.coordinator.entry)
