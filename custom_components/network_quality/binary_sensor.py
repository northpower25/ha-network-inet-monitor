"""Binary sensor platform for Network Quality integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERVICE_STATUSES, DATA_COORDINATOR, DOMAIN
from .coordinator import NetworkQualityCoordinator, ServiceStatus


@dataclass(frozen=True, kw_only=True)
class NetworkQualityBinaryDescription(BinarySensorEntityDescription):
    """Description for network quality binary sensors."""


BASE_BINARY_DESCRIPTION = NetworkQualityBinaryDescription(
    key="internet_online",
    translation_key="internet_online",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    coordinator: NetworkQualityCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[BinarySensorEntity] = [
        NetworkQualityBinarySensor(coordinator, BASE_BINARY_DESCRIPTION)
    ]
    for service in entry.options.get(CONF_SERVICE_STATUSES, []):
        entities.append(NetworkQualityServiceBinarySensor(coordinator, service))
    async_add_entities(entities)


class NetworkQualityBinarySensor(CoordinatorEntity[NetworkQualityCoordinator], BinarySensorEntity, RestoreEntity):
    """Network online sensor."""

    entity_description: NetworkQualityBinaryDescription

    def __init__(
        self,
        coordinator: NetworkQualityCoordinator,
        description: NetworkQualityBinaryDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = description.key
        self._attr_suggested_object_id = f"{DOMAIN}_{description.key}"
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known state if coordinator data is not yet available."""
        await super().async_added_to_hass()
        if not self.coordinator.data:
            if (last_state := await self.async_get_last_state()) is not None:
                self._attr_is_on = last_state.state == "on"

    @property
    def is_on(self) -> bool | None:
        """Return online state."""
        if not self.coordinator.data:
            return self._attr_is_on
        return bool(self.coordinator.data.get("online"))


class NetworkQualityServiceBinarySensor(CoordinatorEntity[NetworkQualityCoordinator], BinarySensorEntity, RestoreEntity):
    """Service status sensor."""

    def __init__(self, coordinator: NetworkQualityCoordinator, service_name: str) -> None:
        super().__init__(coordinator)
        self._service_name = service_name
        self._attr_translation_key = "service_status"
        self._attr_unique_id = f"service_{service_name}"
        self._attr_suggested_object_id = f"{DOMAIN}_service_{service_name}"
        self._attr_has_entity_name = True
        self._attr_name = service_name.replace("_", " ").title()
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known state if coordinator data is not yet available."""
        await super().async_added_to_hass()
        if not self.coordinator.data:
            if (last_state := await self.async_get_last_state()) is not None:
                self._attr_is_on = last_state.state == "on"

    @property
    def is_on(self) -> bool | None:
        """Return service status."""
        if not self.coordinator.data:
            return self._attr_is_on
        status = self._lookup_status()
        if status is None:
            return None
        return status.reachable

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return additional details."""
        status = self._lookup_status()
        if status is None:
            return None
        return {"service": status.name, "detail": status.detail}

    def _lookup_status(self) -> ServiceStatus | None:
        if not self.coordinator.data:
            return None
        services = self.coordinator.data.get("services", [])
        for status in services:
            if status.name == self._service_name:
                return status
        return None
