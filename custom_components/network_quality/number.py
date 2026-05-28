"""Number platform for Network Quality test frequencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DOWNLOAD_TEST_INTERVAL,
    CONF_PING_INTERVAL,
    CONF_SPEEDTEST_INTERVAL,
    CONF_STATUS_INTERVAL,
    CONF_TRACEROUTE_INTERVAL,
    CONF_UPLOAD_TEST_INTERVAL,
    DATA_COORDINATOR,
    DEFAULT_SPEEDTEST_INTERVAL,
    DOMAIN,
)
from .coordinator import NetworkQualityCoordinator
from .entity import build_device_info


@dataclass(frozen=True, kw_only=True)
class NetworkQualityNumberDescription(NumberEntityDescription):
    """Description for test interval entities."""

    options_key: str
    test_key: str


NUMBER_DESCRIPTIONS: tuple[NetworkQualityNumberDescription, ...] = (
    NetworkQualityNumberDescription(
        key="ping_test_frequency",
        translation_key="ping_test_frequency",
        native_unit_of_measurement="s",
        native_min_value=10,
        native_max_value=3600,
        native_step=5,
        mode=NumberMode.BOX,
        options_key=CONF_PING_INTERVAL,
        test_key="ping",
    ),
    NetworkQualityNumberDescription(
        key="traceroute_test_frequency",
        translation_key="traceroute_test_frequency",
        native_unit_of_measurement="s",
        native_min_value=60,
        native_max_value=86400,
        native_step=30,
        mode=NumberMode.BOX,
        options_key=CONF_TRACEROUTE_INTERVAL,
        test_key="traceroute",
    ),
    NetworkQualityNumberDescription(
        key="download_test_frequency",
        translation_key="download_test_frequency",
        native_unit_of_measurement="s",
        native_min_value=60,
        native_max_value=86400,
        native_step=30,
        mode=NumberMode.BOX,
        options_key=CONF_DOWNLOAD_TEST_INTERVAL,
        test_key="download",
    ),
    NetworkQualityNumberDescription(
        key="upload_test_frequency",
        translation_key="upload_test_frequency",
        native_unit_of_measurement="s",
        native_min_value=60,
        native_max_value=86400,
        native_step=30,
        mode=NumberMode.BOX,
        options_key=CONF_UPLOAD_TEST_INTERVAL,
        test_key="upload",
    ),
    NetworkQualityNumberDescription(
        key="status_test_frequency",
        translation_key="status_test_frequency",
        native_unit_of_measurement="s",
        native_min_value=30,
        native_max_value=86400,
        native_step=30,
        mode=NumberMode.BOX,
        options_key=CONF_STATUS_INTERVAL,
        test_key="status",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator: NetworkQualityCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        [NetworkQualityTestFrequencyNumber(coordinator, entry, description) for description in NUMBER_DESCRIPTIONS]
    )


class NetworkQualityTestFrequencyNumber(CoordinatorEntity[NetworkQualityCoordinator], NumberEntity):
    """Entity controlling test frequency."""

    entity_description: NetworkQualityNumberDescription

    def __init__(
        self,
        coordinator: NetworkQualityCoordinator,
        entry: ConfigEntry,
        description: NetworkQualityNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = description.key
        self._attr_suggested_object_id = f"{DOMAIN}_{description.key}"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float:
        """Return current configured interval."""
        return float(
            self._entry.options.get(
                self.entity_description.options_key,
                self._entry.options.get(CONF_SPEEDTEST_INTERVAL, DEFAULT_SPEEDTEST_INTERVAL),
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return latest test execution timestamps."""
        if not self.coordinator.data:
            return None

        tests = self.coordinator.data.get("tests", {})
        details = tests.get(self.entity_description.test_key)
        if not isinstance(details, dict):
            return None

        attributes: dict[str, Any] = {}
        for key in ("last_run_at", "last_started_at", "last_finished_at"):
            value = details.get(key)
            if value:
                attributes[key] = value
        return attributes or None

    async def async_set_native_value(self, value: float) -> None:
        """Persist the new interval to config entry options."""
        new_value = int(value)
        options = dict(self._entry.options)
        options[self.entity_description.options_key] = new_value

        if self.entity_description.options_key in {CONF_DOWNLOAD_TEST_INTERVAL, CONF_UPLOAD_TEST_INTERVAL}:
            download_interval = int(options.get(CONF_DOWNLOAD_TEST_INTERVAL, new_value))
            upload_interval = int(options.get(CONF_UPLOAD_TEST_INTERVAL, new_value))
            options[CONF_SPEEDTEST_INTERVAL] = min(download_interval, upload_interval)

        self.hass.config_entries.async_update_entry(self._entry, options=options)
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> dict[str, object]:
        """Return device metadata so entities are grouped in one integration device."""
        return build_device_info(self._entry)
