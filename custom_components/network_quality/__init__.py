"""The Network Quality integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    ATTR_ENTRY_ID,
    ATTR_INCLUDE_RAW,
    ATTR_INSTANCE_ID,
    ATTR_OUTPUT_PATH,
    AVAILABLE_SERVICE_CATALOG,
    CONF_DASHBOARD_AUTO_EMITTED,
    CONF_SERVICE_STATUSES,
    DATA_COORDINATOR,
    DOMAIN,
    SERVICE_EXPORT_REPORT,
    SERVICE_INSTALL_DASHBOARD,
)
from .coordinator import NetworkQualityCoordinator

PLATFORMS: list[str] = ["sensor", "binary_sensor"]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration."""
    hass.data.setdefault(DOMAIN, {})

    async def _async_export_report(call: ServiceCall) -> None:
        include_raw = call.data.get(ATTR_INCLUDE_RAW, False)
        output_path = call.data.get(ATTR_OUTPUT_PATH)
        target_entry_id = call.data.get(ATTR_INSTANCE_ID) or call.data.get(ATTR_ENTRY_ID)

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.warning("No config entry found for report export")
            return

        entry_id = target_entry_id or entries[0].entry_id
        entry_data = hass.data[DOMAIN].get(entry_id)
        if not entry_data:
            _LOGGER.warning("Config entry id %s not found for report export", entry_id)
            return

        coordinator: NetworkQualityCoordinator = entry_data[DATA_COORDINATOR]
        report_data = coordinator.build_report_payload(include_raw=include_raw)

        if output_path:
            path = Path(output_path)
            await hass.async_add_executor_job(
                path.write_text,
                coordinator.render_report_text(report_data),
                "utf-8",
            )
            _LOGGER.info("Network quality report exported to %s", path)
            return

        hass.bus.async_fire(f"{DOMAIN}_report_generated", report_data)

    async def _async_emit_dashboard_template() -> None:
        dashboard_file = (
            Path(__file__).parent / "dashboard" / "network_quality_dashboard.json"
        )
        data = await hass.async_add_executor_job(dashboard_file.read_text, "utf-8")
        hass.bus.async_fire(f"{DOMAIN}_dashboard_ready", {"dashboard_json": data})

    async def _async_install_dashboard(call: ServiceCall) -> None:
        await _async_emit_dashboard_template()

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_REPORT,
        _async_export_report,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_OUTPUT_PATH): cv.string,
                vol.Optional(ATTR_INCLUDE_RAW, default=False): cv.boolean,
                vol.Optional(ATTR_INSTANCE_ID): cv.string,
                vol.Optional(ATTR_ENTRY_ID): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_INSTALL_DASHBOARD,
        _async_install_dashboard,
        schema=vol.Schema({}),
    )

    return True


async def _async_migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate legacy entity ids containing the config entry id."""
    registry = er.async_get(hass)
    migration_pairs: dict[str, str] = {
        f"sensor.{DOMAIN}_{entry.entry_id}_internet_download": f"sensor.{DOMAIN}_internet_download",
        f"sensor.{DOMAIN}_{entry.entry_id}_internet_upload": f"sensor.{DOMAIN}_internet_upload",
        f"sensor.{DOMAIN}_{entry.entry_id}_ping_public": f"sensor.{DOMAIN}_ping_public",
        f"sensor.{DOMAIN}_{entry.entry_id}_packet_loss": f"sensor.{DOMAIN}_packet_loss",
        f"sensor.{DOMAIN}_{entry.entry_id}_jitter": f"sensor.{DOMAIN}_jitter",
        f"sensor.{DOMAIN}_{entry.entry_id}_availability": f"sensor.{DOMAIN}_availability",
        f"sensor.{DOMAIN}_{entry.entry_id}_contract_ratio": f"sensor.{DOMAIN}_contract_ratio",
        f"sensor.{DOMAIN}_{entry.entry_id}_quality_score": f"sensor.{DOMAIN}_quality_score",
        f"sensor.{DOMAIN}_{entry.entry_id}_quality_class": f"sensor.{DOMAIN}_quality_class",
        f"binary_sensor.{DOMAIN}_{entry.entry_id}_internet_online": f"binary_sensor.{DOMAIN}_internet_online",
    }
    known_services = set(AVAILABLE_SERVICE_CATALOG)
    known_services.update(entry.options.get(CONF_SERVICE_STATUSES, []))
    for service in known_services:
        migration_pairs[
            f"binary_sensor.{DOMAIN}_{entry.entry_id}_service_{service}"
        ] = f"binary_sensor.{DOMAIN}_service_{service}"

    for old_entity_id, new_entity_id in migration_pairs.items():
        old_entry = registry.async_get(old_entity_id)
        if old_entry is None or old_entry.config_entry_id != entry.entry_id:
            continue
        if registry.async_get(new_entity_id) is not None:
            continue
        try:
            registry.async_update_entity(old_entity_id, new_entity_id=new_entity_id)
            _LOGGER.info("Migrated entity id %s -> %s", old_entity_id, new_entity_id)
        except ValueError:
            _LOGGER.warning("Could not migrate entity id %s to %s", old_entity_id, new_entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = NetworkQualityCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    await _async_migrate_entity_ids(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = {DATA_COORDINATOR: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if not entry.options.get(CONF_DASHBOARD_AUTO_EMITTED, False):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_INSTALL_DASHBOARD,
            {},
            blocking=True,
        )
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_DASHBOARD_AUTO_EMITTED: True},
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    if not hass.config_entries.async_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_EXPORT_REPORT)
        hass.services.async_remove(DOMAIN, SERVICE_INSTALL_DASHBOARD)
    return unload_ok
